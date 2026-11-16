"""MCP services from a context's settings: parsing, the tools a turn gets, approval, and the route.

Hermetic: the MCP session is replaced by a fake listing, so nothing here touches a workspace.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agent import mcp_services
from agent.contexts import CONTEXTS, McpService, parse_settings, system_prompt
from fastapi.testclient import TestClient
from mcp.types import CallToolResult, ToolAnnotations
from mcp.types import Tool as MCPTool
from runtime.settings_api import install_settings_api

from databricks_agentkit import DurableAgentServer
from databricks_agentkit.runtime.auth import AuthError
from databricks_agentkit.runtime.store import RUNTIME_STORE_LOCAL_ENV, InMemoryRuntimeStore

SCHEMA = {"type": "object", "properties": {"q": {"type": "string"}}}


def mcp_tool(name: str, *, read_only: bool | None = None) -> MCPTool:
    annotations = ToolAnnotations(readOnlyHint=read_only) if read_only is not None else None
    return MCPTool(name=name, description=f"{name} tool", inputSchema=SCHEMA, annotations=annotations)


def fake_client(token: str | None = "tok-1", host: str = "https://ws.example.com/"):
    config = SimpleNamespace(host=host, token=token, auth_type="pat", profile=None)
    return SimpleNamespace(config=config)


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    mcp_services._cache.clear()
    monkeypatch.delenv("DATABRICKS_APP_NAME", raising=False)
    monkeypatch.delenv(RUNTIME_STORE_LOCAL_ENV, raising=False)
    # The real connection wraps a WorkspaceClient; the fake listing never opens it.
    monkeypatch.setattr(mcp_services, "_connection", lambda client, service: {"url": service})


def listing(by_service: dict, calls: list | None = None):
    """A fake `_fetch_tools`: tools per service, or an exception to raise."""

    async def fetch(connection):
        if calls is not None:
            calls.append(connection["url"])
        result = by_service[connection["url"]]
        if isinstance(result, BaseException):
            raise result
        return result

    return fetch


# --- Parsing -----------------------------------------------------------------------------------


def test_parse_settings_reads_mcp_services():
    settings = parse_settings({
        "tools": {
            "mcp": [
                {"service": "system.ai.slack", "tools": ["search", "post", "bad name", 3], "approve": ["post"]},
                {"service": "system.ai.web_search"},
                {"service": "system.ai.slack"},
                {"service": "https://evil.example.com/mcp"},
                {"service": "../../api/2.0/secrets"},
                {"service": "system.ai.sandbox"},
                "not an object",
            ]
        }
    })
    assert settings.mcp_services == (
        McpService("system.ai.slack", tools=("search", "post"), approve=("post",)),
        McpService("system.ai.web_search"),
    )


def test_mcp_service_defaults_offer_everything_and_gate_unmarked_tools():
    default = McpService("system.ai.dbsql")
    assert default.offers("anything")
    assert default.asks_first("execute_sql", read_only=False)
    assert not default.asks_first("poll_sql_result", read_only=True)
    chosen = McpService("system.ai.dbsql", tools=("execute_sql",), approve=())
    assert not chosen.offers("poll_sql_result")
    assert not chosen.asks_first("execute_sql", read_only=False)


def test_service_url_is_built_on_the_users_workspace():
    assert (
        mcp_services.service_url(fake_client(), "system.ai.slack")
        == "https://ws.example.com/ai-gateway/mcp-services/system.ai.slack"
    )
    with pytest.raises(ValueError):
        mcp_services.service_url(fake_client(), "evil.com/x.y")


# --- A turn's tools ------------------------------------------------------------------------------


async def test_turn_offers_chosen_tools_as_the_user_and_gates_by_annotation(monkeypatch):
    monkeypatch.setattr(mcp_services, "_fetch_tools", listing({
        "system.ai.dbsql": [mcp_tool("execute_sql"), mcp_tool("poll_sql_result", read_only=True)],
        "system.ai.web_search": [mcp_tool("web_search"), mcp_tool("dotted.name")],
    }))
    settings = parse_settings({"tools": {"mcp": [
        {"service": "system.ai.dbsql"},
        {"service": "system.ai.web_search", "approve": []},
    ]}})
    modes = []

    def client_for(mode):
        modes.append(mode)
        return fake_client()

    turn = await mcp_services.settings_mcp_tools(settings, client_for)

    assert modes == ["user"]
    assert [t.name for t in turn.tools] == ["execute_sql", "poll_sql_result", "web_search"]
    assert turn.approval == {"execute_sql": True}
    assert turn.unavailable == []


async def test_turn_skips_names_already_taken(monkeypatch):
    monkeypatch.setattr(mcp_services, "_fetch_tools", listing({
        "system.ai.a": [mcp_tool("search")],
        "system.ai.b": [mcp_tool("search"), mcp_tool("get_current_time")],
    }))
    settings = parse_settings({"tools": {"mcp": [{"service": "system.ai.a"}, {"service": "system.ai.b"}]}})
    turn = await mcp_services.settings_mcp_tools(
        settings, lambda mode: fake_client(), taken=["get_current_time"]
    )
    assert [t.name for t in turn.tools] == ["search"]


async def test_a_failing_service_costs_only_itself(monkeypatch):
    rejected = ExceptionGroup("unhandled errors in a TaskGroup", [
        RuntimeError("The MCP service request was rejected (HTTP 401). Check the service authentication.")
    ])
    monkeypatch.setattr(mcp_services, "_fetch_tools", listing({
        "system.ai.slack": rejected,
        "system.ai.github": ConnectionError("connection reset"),
        "system.ai.web_search": [mcp_tool("web_search")],
    }))
    settings = parse_settings({"tools": {"mcp": [
        {"service": "system.ai.slack"}, {"service": "system.ai.github"}, {"service": "system.ai.web_search"},
    ]}})
    turn = await mcp_services.settings_mcp_tools(settings, lambda mode: fake_client())
    assert [t.name for t in turn.tools] == ["web_search"]
    assert turn.unavailable == [("system.ai.slack", True), ("system.ai.github", False)]

    prompt = system_prompt(CONTEXTS["general"], settings, unavailable_services=turn.unavailable)
    assert "- system.ai.slack: the user has not connected it yet" in prompt
    assert "- system.ai.github: it did not answer" in prompt
    assert "set up for this part of the app" not in system_prompt(CONTEXTS["general"], settings)


async def test_a_service_that_hangs_while_listing_is_skipped(monkeypatch):
    import asyncio

    async def fetch(connection):
        if connection["url"] == "system.ai.slow":
            await asyncio.sleep(5)
        return [mcp_tool("web_search")]

    monkeypatch.setattr(mcp_services, "_fetch_tools", fetch)
    monkeypatch.setattr(mcp_services, "_LIST_TIMEOUT_SECONDS", 0.05)
    settings = parse_settings({"tools": {"mcp": [{"service": "system.ai.slow"}, {"service": "system.ai.web_search"}]}})
    turn = await mcp_services.settings_mcp_tools(settings, lambda mode: fake_client())
    assert [t.name for t in turn.tools] == ["web_search"]
    assert turn.unavailable == [("system.ai.slow", False)]


async def test_deployed_without_the_request_user_refuses(monkeypatch):
    monkeypatch.setenv("DATABRICKS_APP_NAME", "agent-bricks-exec-intel-agent")
    settings = parse_settings({"tools": {"mcp": [{"service": "system.ai.slack"}]}})
    with pytest.raises(AuthError):
        await mcp_services.settings_mcp_tools(settings, None)


async def test_no_services_needs_no_client():
    def client_for(mode):
        raise AssertionError("no client needed")

    turn = await mcp_services.settings_mcp_tools(parse_settings({}), client_for)
    assert turn.tools == [] and turn.approval == {} and turn.unavailable == []


# --- Caching -------------------------------------------------------------------------------------


async def test_definitions_are_cached_per_user_and_failures_are_not(monkeypatch):
    calls = []
    by_service = {"system.ai.web_search": [mcp_tool("web_search")], "system.ai.slack": RuntimeError("HTTP 401")}
    monkeypatch.setattr(mcp_services, "_fetch_tools", listing(by_service, calls))

    await mcp_services.list_tools(fake_client("tok-1"), "system.ai.web_search")
    await mcp_services.list_tools(fake_client("tok-1"), "system.ai.web_search")
    assert calls == ["system.ai.web_search"]
    await mcp_services.list_tools(fake_client("tok-2"), "system.ai.web_search")
    await mcp_services.list_tools(fake_client("tok-1"), "system.ai.web_search", fresh=True)
    assert len(calls) == 3

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await mcp_services.list_tools(fake_client("tok-1"), "system.ai.slack")
    assert calls.count("system.ai.slack") == 2
    assert all("tok-" not in key[0] for key in mcp_services._cache)


# --- Calls ---------------------------------------------------------------------------------------


async def test_a_call_that_fails_in_transport_reaches_the_model_as_a_tool_error():
    interceptor = mcp_services._failure_interceptor("system.ai.slack")

    async def handler(request):
        raise ExceptionGroup("task group", [RuntimeError("rejected (HTTP 401)")])

    result = await interceptor(SimpleNamespace(name="search"), handler)
    assert isinstance(result, CallToolResult) and result.isError
    text = result.content[0].text
    assert "system.ai.slack could not run search" in text and "AI Gateway > MCPs" in text


# --- Settings route --------------------------------------------------------------------------------


def settings_app():
    app = DurableAgentServer(runtime_store=InMemoryRuntimeStore())
    install_settings_api(app)
    return TestClient(app)


def test_route_lists_tools_as_the_caller(monkeypatch):
    import databricks_agentkit.runtime.workspace as workspace

    monkeypatch.setattr(workspace, "workspace_client", lambda: fake_client(token=None))
    list_tools = AsyncMock(return_value=[mcp_tool("execute_sql"), mcp_tool("poll", read_only=True)])
    monkeypatch.setattr(mcp_services, "list_tools", list_tools)

    response = settings_app().get("/api/mcp-services/system.ai.dbsql/tools", params={"refresh": "true"})

    assert response.status_code == 200
    body = response.json()
    assert body["problem"] is None
    assert [(t["name"], t["read_only"], t["offerable"]) for t in body["tools"]] == [
        ("execute_sql", False, True),
        ("poll", True, True),
    ]
    assert list_tools.await_args.kwargs == {"fresh": True}


def test_route_reports_a_service_that_wants_sign_in(monkeypatch):
    import databricks_agentkit.runtime.workspace as workspace

    monkeypatch.setattr(workspace, "workspace_client", lambda: fake_client(token=None))
    monkeypatch.setattr(mcp_services, "list_tools", AsyncMock(side_effect=RuntimeError("rejected (HTTP 401)")))

    body = settings_app().get("/api/mcp-services/system.ai.slack/tools").json()

    assert body["tools"] == [] and body["problem"]["sign_in"] is True


def test_route_refuses_names_it_cannot_attach():
    client = settings_app()
    assert client.get("/api/mcp-services/system.ai.sandbox/tools").status_code == 400
    assert client.get("/api/mcp-services/not-three-parts/tools").status_code == 400


def test_route_needs_the_user_when_deployed(monkeypatch):
    monkeypatch.setenv("DATABRICKS_APP_NAME", "agent-bricks-exec-intel-agent")
    assert settings_app().get("/api/mcp-services/system.ai.slack/tools").status_code == 401


def test_contexts_route_still_describes_defaults():
    body = settings_app().get("/api/contexts").json()
    assert {c["id"] for c in body["contexts"]} == set(CONTEXTS)


# --- The graph -------------------------------------------------------------------------------------


async def test_graph_adds_service_tools_and_their_approval(monkeypatch):
    import agent.agent as agent_module
    from langchain_core.tools import tool

    @tool
    def web_search(q: str) -> str:
        """Search the web."""
        return q

    @tool
    def send_email(to: str) -> str:
        """Send an email."""
        return to

    seen = {}
    taken = {}

    async def fake_settings_mcp_tools(settings, workspace_client_for, *, taken=()):
        seen["taken"] = list(taken)
        return mcp_services.McpTurn(
            tools=[web_search, send_email],
            approval={"send_email": True},
            unavailable=[("system.ai.slack", True)],
        )

    monkeypatch.setattr(agent_module, "settings_mcp_tools", fake_settings_mcp_tools)
    monkeypatch.setattr(agent_module, "mcp_tools", AsyncMock(return_value=[]))
    monkeypatch.setattr(agent_module.stores, "refresh", AsyncMock(return_value=SimpleNamespace(memory=False)))
    monkeypatch.setattr(agent_module, "_app_workspace_client", lambda: None)
    monkeypatch.setattr(agent_module, "_RoutedChatDatabricks", lambda **kwargs: "model")
    monkeypatch.setattr(agent_module, "create_agent", lambda **kwargs: taken.update(kwargs) or "graph")

    graph = await agent_module.create_agent_graph(
        "actor", context="general", settings={"tools": {"mcp": [{"service": "system.ai.web_search"}]}}
    )

    assert graph == "graph"
    names = [t.name for t in taken["tools"]]
    assert names[-2:] == ["web_search", "send_email"]
    assert "get_current_time" in seen["taken"]
    [middleware] = taken["middleware"]
    assert set(middleware.interrupt_on) == {"send_message", "send_email"}
    assert "system.ai.slack: the user has not connected it yet" in taken["system_prompt"]
