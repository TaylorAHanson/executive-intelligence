import os
from collections.abc import AsyncGenerator, Callable
from functools import lru_cache
from typing import Any

from databricks.sdk import WorkspaceClient
from databricks_langchain import ChatDatabricks
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain.agents.middleware.human_in_the_loop import HITLResponse
from langchain_core.tools import BaseTool, tool
from langgraph.types import Command
from pydantic import TypeAdapter, ValidationError

from agent.contexts import (
    ContextSettings,
    parse_settings,
    resolve_context,
    select_tools,
    system_prompt,
)
from agent import stores
from agent.mcps import build_mcp_servers

# Importing the tools package auto-registers every tool module.
from agent.tools import all_tools
from databricks_agentkit import workspace_client, workspace_headers
from databricks_agentkit.langgraph import (
    configure_tracing,
    genie_tools,
    mcp_tools,
    start_trace,
    thread_config,
)
from databricks_agentkit.langgraph.messages import gateway_messages
from databricks_agentkit.langgraph.session_store import (
    invocation_id_from_metadata,
    invocation_metadata,
)
from databricks_agentkit.runtime.auth import AuthError
from databricks_agentkit.runtime.genie import GenieAgent
from databricks_agentkit.runtime.tool_manifest import resolve_model_service

# A Unity Catalog AI Gateway model service, served from the `system.ai` schema and queried through
# the gateway (see `use_ai_gateway=True` below). Swap for any `system.ai.*` model service your
# workspace exposes — the demo chat app's picker lists what's available.
# `agentbricks experimental models bind` swaps this for a model service you own (wired in by `agentbricks deploy`
# as AGENT_MODEL_SERVICE_AGENT), so `agentbricks experimental models upgrade` can change the model without a code
# change.
MODEL = resolve_model_service() or "system.ai.claude-sonnet-5-5"

# Tools that require human approval before they run. Map a tool name to True to allow every decision
# (approve / edit / reject / respond), or to a config dict to restrict them (see HumanInTheLoopMiddleware).
# When a listed tool is about to run, the agent pauses and emits an `interrupt` event; the client
# resumes by sending `resume` with the same session id. Empty this dict to disable approval gating.
REQUIRE_APPROVAL = {"send_message": True}


class _RoutedChatDatabricks(ChatDatabricks):
    """Forward account-host workspace routing to the underlying OpenAI clients."""

    def _get_client_kwargs(self) -> dict[str, Any]:
        kwargs = super()._get_client_kwargs()
        if headers := workspace_headers():
            kwargs["default_headers"] = headers
        return kwargs

    def _prepare_inputs(self, messages: list[Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
        # Send Claude 5.x reasoning (and its signature) back to the model on the next turn.
        return super()._prepare_inputs(gateway_messages(messages), *args, **kwargs)


@lru_cache(maxsize=1)
def _app_workspace_client() -> WorkspaceClient:
    """The App's own client, shared across turns.

    Constructing a WorkspaceClient resolves auth with blocking network calls (and, locally, a
    `databricks auth token` subprocess). Doing that per turn inside the async graph builder stalls
    every request on the event loop; the SDK refreshes tokens itself, so one client suffices.
    """
    return workspace_client()


def configure() -> None:
    """Wire up global state; call once at server startup (not at import)."""
    _check_databricks_auth()
    configure_tracing()


def _check_databricks_auth() -> None:
    """Fail fast at startup with a clear message if Databricks auth isn't configured.

    Without this, a missing/invalid profile only surfaces on the first model call — as a generic SDK
    error buried in a request traceback. Resolving a WorkspaceClient here validates the same config
    the model client uses, so the failure is immediate and actionable.
    """
    try:
        _app_workspace_client()
    except Exception as e:
        profile = os.getenv("DATABRICKS_CONFIG_PROFILE")
        target = (
            f"profile {profile!r}" if profile else "the DEFAULT profile / DATABRICKS_HOST+TOKEN"
        )
        raise RuntimeError(
            f"Databricks auth is not configured — the agent can't call the model. Tried {target}.\n"
            "Fix one of:\n"
            "  • set DATABRICKS_CONFIG_PROFILE in .env to a profile from `databricks auth profiles`, or\n"
            "  • run `databricks auth login --profile <name>` to create one, or\n"
            "  • set DATABRICKS_HOST and DATABRICKS_TOKEN in .env.\n"
            f"(underlying error: {e})"
        ) from e


def settings_genie_tools(
    context_settings: ContextSettings,
    workspace_client_for: Callable[[str], WorkspaceClient] | None,
) -> list[BaseTool]:
    """Ask, poll and query-result tools for each Genie space in a context's settings, as the user."""
    if context_settings.genie_spaces and workspace_client_for is None and os.getenv("DATABRICKS_APP_NAME"):
        # Deployed, the only credentials left would be the app's own; never query data with them.
        raise AuthError(
            "MCP_USER_AUTHORIZATION_MISSING", "Genie spaces in settings need the request user."
        )
    tools: list[BaseTool] = []
    for space in context_settings.genie_spaces:
        genie = GenieAgent(space.space_id, auth="user", workspace_client_for=workspace_client_for)
        tools.extend(
            tool(f"{space.name}_{method.__name__}")(method)
            for method in (genie.ask, genie.poll, genie.query_result)
        )
    return tools


async def create_agent_graph(
    actor: str,
    model: str | None = None,
    *,
    context: str | None = None,
    settings: Any = None,
    workspace_client_for: Callable[[str], WorkspaceClient] | None = None,
):
    """Build the LangGraph agent: local tools + long-term-memory tools + any MCP tools.

    ``actor`` is the identity whose long-term memory the agent reads/writes; it's captured in the
    memory tools' closures (never exposed to the model). The memory tools and the managed
    checkpointer are used only while their stores answer; see ``agent/stores.py``.

    ``model`` selects the gateway model for this run; the chat UI passes the picker's choice and
    everything else falls back to ``MODEL``. ``context`` is the client app section (see
    ``agent/contexts.py``); it picks the prompt section and which tools are offered, and
    ``settings`` is that context's admin settings from the client (``parse_settings``). The agent
    is rebuilt per turn, so model, context, settings, and tools can all vary request to request
    within one session.
    """
    app_context = resolve_context(context)
    context_settings = parse_settings(settings)
    # The managed stores may be off in this workspace; the agent answers without them (agent/stores.py).
    store_status = await stores.refresh()
    mcp = await mcp_tools(build_mcp_servers(), workspace_client_for=workspace_client_for)
    local = all_tools()
    tools = [
        *select_tools(
            app_context,
            [*local, *genie_tools(workspace_client_for=workspace_client_for), *mcp],
            context_settings,
            local_names=[t.name for t in local],
        ),
        *settings_genie_tools(context_settings, workspace_client_for),
        *stores.memory_tools_for(actor),
    ]
    middleware = (
        [HumanInTheLoopMiddleware(interrupt_on=REQUIRE_APPROVAL)] if REQUIRE_APPROVAL else []
    )
    endpoint = model or MODEL
    return create_agent(
        # use_ai_gateway routes to the Unity Catalog AI Gateway (`<host>/ai-gateway/mlflow/v1`), so
        # `endpoint` is a `system.ai.*` model name rather than a serving-endpoint name.
        model=_RoutedChatDatabricks(
            endpoint=endpoint, workspace_client=_app_workspace_client(), use_ai_gateway=True
        ),
        tools=tools,
        system_prompt=system_prompt(app_context, context_settings, memory=store_status.memory),
        middleware=middleware,
        checkpointer=stores.session_saver(),
    )


async def recovery_input(
    agent_input: Any,
    *,
    session_id: str,
    actor: str,
    invocation_id: str,
) -> Any:
    """Return the input that should be passed to ``run_agent`` after worker loss.

    A checkpoint tagged with this invocation means LangGraph can continue by receiving ``None``.
    Otherwise recovery replays the original application input.
    """
    await stores.refresh()
    checkpoint = await stores.session_saver().aget_tuple(thread_config(session_id, actor))
    current_invocation_checkpointed = bool(
        checkpoint and invocation_id_from_metadata(checkpoint.metadata) == invocation_id
    )
    return None if current_invocation_checkpointed else agent_input


async def _validate_approval_resume(graph: Any, config: dict, agent_input: Any) -> None:
    """Reject malformed middleware decisions before LangGraph checkpoints the resume value."""
    if not isinstance(agent_input, Command) or agent_input.resume is None:
        return
    state = await graph.aget_state(config)
    pending = [item for task in state.tasks for item in task.interrupts]
    resume = agent_input.resume
    keyed = isinstance(resume, dict) and any(item.id in resume for item in pending)
    for item in pending:
        if not isinstance(item.value, dict) or "review_configs" not in item.value:
            continue  # Application-defined interrupts keep their native resume contract.
        if keyed and item.id not in resume:
            continue
        response = resume[item.id] if keyed else resume
        try:
            decisions = TypeAdapter(HITLResponse).validate_python(response)["decisions"]
        except ValidationError as error:
            raise AuthError(
                "INVALID_APPROVAL", "Invalid approval decision payload.", 400
            ) from error
        reviews = item.value["review_configs"]
        if len(decisions) != len(reviews) or any(
            decision["type"] not in review["allowed_decisions"]
            for decision, review in zip(decisions, reviews, strict=True)
        ):
            raise AuthError(
                "INVALID_APPROVAL", "Provide one allowed decision per pending tool call.", 400
            )


async def run_agent(
    agent_input: Any,
    *,
    session_id: str,
    actor: str | None = None,
    model: str | None = None,
    context: str | None = None,
    settings: Any = None,
    invocation_id: str | None = None,
    workspace_client_for: Callable[[str], WorkspaceClient] | None = None,
    graph: Any = None,
) -> AsyncGenerator[Any, None]:
    """Run the agent and yield native LangGraph stream events.

    This is the framework-native entrypoint. It has no dependency on Agent Bricks request or context types,
    so it can be called from another server, a notebook, or a test harness.
    """
    # Each interactive resume builds tools from this request's credentials. Only graph state,
    # never the graph or its credential-bound clients, survives the approval pause.
    actor = actor or session_id
    if graph is None:
        graph = await create_agent_graph(
            actor,
            model,
            context=context,
            settings=settings,
            workspace_client_for=workspace_client_for,
        )
    config = thread_config(session_id, actor)
    if invocation_id:
        config["metadata"] = invocation_metadata(invocation_id)

    await _validate_approval_resume(graph, config, agent_input)

    last_update: Any = None
    with start_trace(name="invoke", inputs=agent_input, session_id=session_id) as span:
        async for event in graph.astream(
            input=agent_input,
            config=config,
            stream_mode=["updates", "messages"],
            durability="sync",
        ):
            if event[0] == "updates":
                last_update = event[1]
            yield event
        if span is not None and last_update is not None:
            span.set_outputs(last_update)
