"""Unity Catalog AI Gateway MCP services that admins attach to a context in Settings.

An admin picks services, and optionally which of their tools, for each context in the client's
Settings page; the client sends them in ``input.settings`` (``agent/contexts.py``). Each turn this
module connects to every attached service **as the signed-in user** and offers the chosen tools.
Three rules hold it together:

* **Names, never URLs.** Settings carry ``catalog.schema.name``. The URL is built here on the host of
  the user's own workspace client, so no caller can send the user's token anywhere else.
* **A failing service costs that service, not the turn.** A user who hasn't signed in to a service
  that acts with their own account (Slack, GitHub, ...) or lacks EXECUTE on it gets the turn without
  its tools, and the prompt says so. A tool call that fails reaches the model as a tool error.
* **Definitions are cached, credentials are not.** Listing a service opens an MCP session and the
  graph is rebuilt every turn, so each user's view of a service's tools (names, descriptions and
  schemas) is kept for five minutes, keyed by a hash of their token. The tools are built every turn
  on that turn's client, and each call opens its own session.

The Settings page lists a service's tools through ``GET /api/mcp-services/{service}/tools``
(``runtime/main.py``), which calls ``list_tools`` here, so the names an admin picks are exactly the
names the agent offers.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from databricks.sdk import WorkspaceClient
from databricks_langchain import DatabricksMCPServer
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.sessions import create_session
from langchain_mcp_adapters.tools import convert_mcp_tool_to_langchain_tool
from mcp.types import CallToolResult, TextContent
from mcp.types import Tool as MCPTool

from agent.contexts import MCP_SERVICE_RE, MCP_TOOL_NAME_RE, ContextSettings
from databricks_agentkit import workspace_client, workspace_headers
from databricks_agentkit.runtime.mcp_auth import resolve_mcp_workspace_client

logger = logging.getLogger(__name__)

GATEWAY_PATH = "/ai-gateway/mcp-services/"
_CACHE_SECONDS = 300.0
_CACHE_MAX_ENTRIES = 1000
_TIMEOUT_SECONDS = 120.0
#: How long a turn waits for a service to list its tools. Calls keep the longer timeout above; a
#: service that hangs while listing must not hold up every turn in its context.
_LIST_TIMEOUT_SECONDS = 20.0
_MAX_PAGES = 50
_MAX_DETAIL_CHARS = 300

#: What a service answers when it acts with each person's own account and this one hasn't connected
#: it yet: HTTP 401 from the gateway, or MCP's "authorization required" (-32042).
_SIGN_IN_MARKERS = (
    "http 401",
    "401 unauthorized",
    "-32042",
    "please login first",
    "please log in first",
    "credential for user identity",
)
SIGN_IN_HINT = (
    "If this service connects with each person's own account, sign in to it once under "
    "AI Gateway > MCPs in Databricks."
)

_cache: dict[tuple[str, str], tuple[float, list[MCPTool]]] = {}


@dataclass
class McpTurn:
    """What a turn gets from its context's MCP services."""

    tools: list[BaseTool] = field(default_factory=list)
    #: Tool name -> True for each tool that waits for the user's approval.
    approval: dict[str, bool] = field(default_factory=dict)
    #: (service, needs sign-in) for each attached service this user could not use this turn.
    unavailable: list[tuple[str, bool]] = field(default_factory=list)


def service_url(client: WorkspaceClient, service: str) -> str:
    """The AI Gateway URL for ``service`` on the client's own workspace."""
    if not MCP_SERVICE_RE.match(service):
        raise ValueError(f"Not a Unity Catalog MCP service name: {service!r}")
    return f"{client.config.host.rstrip('/')}{GATEWAY_PATH}{service}"


def _connection(client: WorkspaceClient, service: str) -> dict:
    return DatabricksMCPServer(
        name=service,
        url=service_url(client, service),
        headers=workspace_headers() or None,
        workspace_client=client,
        timeout=_TIMEOUT_SECONDS,
    ).to_connection_dict()


def _credential_key(client: WorkspaceClient) -> str:
    """Whose view of a service this is: a hash of the token, never the token or a name."""
    config = client.config
    if token := getattr(config, "token", None):
        return "token:" + hashlib.sha256(token.encode()).hexdigest()
    return f"{config.host}|{config.auth_type}|{config.profile}"


async def _fetch_tools(connection: dict) -> list[MCPTool]:
    async with create_session(connection) as session:
        await session.initialize()
        tools: list[MCPTool] = []
        cursor = None
        for _ in range(_MAX_PAGES):
            page = await session.list_tools(cursor=cursor)
            tools.extend(page.tools or [])
            cursor = page.nextCursor
            if not cursor:
                break
    return tools


async def list_tools(client: WorkspaceClient, service: str, *, fresh: bool = False) -> list[MCPTool]:
    """``service``'s tools as the client's user sees them. Cached per user; failures are not."""
    key = (_credential_key(client), service)
    now = time.monotonic()
    hit = None if fresh else _cache.get(key)
    if hit and now - hit[0] < _CACHE_SECONDS:
        return hit[1]
    tools = await _fetch_tools(_connection(client, service))
    if len(_cache) >= _CACHE_MAX_ENTRIES:
        _cache.clear()
    _cache[key] = (now, tools)
    return tools


def read_only(tool: MCPTool) -> bool:
    """Whether the service marks the tool read-only. Unmarked tools are treated as acting."""
    return bool(tool.annotations and tool.annotations.readOnlyHint)


def describe(tool: MCPTool) -> dict:
    """One tool as the Settings page shows it. Holds no credentials or data."""
    return {
        "name": tool.name,
        "description": (tool.description or "").strip()[:1000],
        "read_only": read_only(tool),
        # The model API rejects other names, so the agent never offers such a tool.
        "offerable": bool(MCP_TOOL_NAME_RE.match(tool.name)),
    }


def readable(error: BaseException, depth: int = 0) -> str:
    """The error inside the error: MCP's transport reports failures as exception groups."""
    inner = getattr(error, "exceptions", None)
    if inner and depth < 3:
        return "; ".join(readable(e, depth + 1) for e in inner)
    text = f"{type(error).__name__}: {str(error).strip() or 'no message'}"
    return text[:_MAX_DETAIL_CHARS]


def needs_sign_in(error: BaseException) -> bool:
    text = readable(error).lower()
    return any(marker in text for marker in _SIGN_IN_MARKERS)


def problem(error: BaseException) -> dict:
    """Why a service listed nothing, for the Settings page."""
    return {"sign_in": needs_sign_in(error), "detail": readable(error)}


def _failure_interceptor(service: str):
    """Turn a call that fails in transport into a tool error the model can explain."""

    async def interceptor(request, handler):
        try:
            return await handler(request)
        except Exception as error:  # noqa: BLE001 - one tool failing must not end the turn
            logger.warning("MCP service %s: %s failed: %s", service, request.name, readable(error))
            text = f"{service} could not run {request.name}: {readable(error)}"
            if needs_sign_in(error):
                text = f"{text} {SIGN_IN_HINT}"
            return CallToolResult(content=[TextContent(type="text", text=text)], isError=True)

    return interceptor


async def settings_mcp_tools(
    settings: ContextSettings,
    workspace_client_for: Callable[[str], WorkspaceClient] | None,
    *,
    taken: Iterable[str] = (),
) -> McpTurn:
    """The tools of the context's MCP services, as the user, minus names already in ``taken``."""
    turn = McpTurn()
    services = settings.mcp_services
    if not services:
        return turn
    # Deployed without the request user, this raises rather than fall back to the app's identity.
    client = await asyncio.to_thread(
        resolve_mcp_workspace_client,
        "user",
        "settings-mcp-services",
        workspace_client_for,
        workspace_client,
    )
    listed = await asyncio.gather(
        *(asyncio.wait_for(list_tools(client, s.service), _LIST_TIMEOUT_SECONDS) for s in services),
        return_exceptions=True,
    )
    seen = set(taken)
    for service, result in zip(services, listed, strict=True):
        if isinstance(result, BaseException):
            if not isinstance(result, Exception):
                raise result
            logger.warning("MCP service %s unavailable this turn: %s", service.service, readable(result))
            turn.unavailable.append((service.service, needs_sign_in(result)))
            continue
        connection = _connection(client, service.service)
        for mcp_tool in result:
            name = mcp_tool.name
            if not service.offers(name):
                continue
            if not MCP_TOOL_NAME_RE.match(name):
                logger.warning("MCP service %s: skipping tool %r, a name the model rejects.", service.service, name)
                continue
            if name in seen:
                logger.warning("MCP service %s: skipping tool %r, a name another tool has.", service.service, name)
                continue
            seen.add(name)
            turn.tools.append(
                convert_mcp_tool_to_langchain_tool(
                    None,
                    mcp_tool,
                    connection=connection,
                    server_name=service.service,
                    tool_interceptors=[_failure_interceptor(service.service)],
                    handle_tool_errors=True,
                )
            )
            if service.asks_first(name, read_only(mcp_tool)):
                turn.approval[name] = True
    return turn
