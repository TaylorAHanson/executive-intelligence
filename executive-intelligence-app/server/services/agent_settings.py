"""The agent's per-context settings: prompt and tools, edited by admins in Settings.

Settings are app state, not business data, so they live in the app's own
Lakebase (`agent_context_settings`, created by `database.init_db`) and are read
and written as the app's service principal. That makes the admin check
(`require_admin`, against `ADMIN_GROUP`) the only gate on writes. What the
settings control cannot widen anyone's access: every data tool they name runs
as the signed-in user.

  * The tray sends the current context's settings to the agent as
    `input.settings` on each turn (`for_context`). A database that is down or
    still waking costs the saved overrides for that turn, never the turn.
  * A context's defaults are the agent's (`agent/contexts.py`, read from its
    `/api/contexts`) plus the bundle's Genie bindings (`GENIE_BINDINGS`). A row
    overrides them field by field; NULL keeps the default.

Genie titles and descriptions for the bundle's bindings are read from Genie as
the signed-in user and cached, so the service principal needs no access to any
space.

Settings can also attach Unity Catalog MCP services (the AI Gateway's MCPs) to
a context. The picker lists them as the signed-in admin: services from the
Unity Catalog API (`unity-catalog` scope), and each service's tools from the
agent (`/api/mcp-services/<service>/tools`), which holds the MCP client and
lists them with the same code it runs on every turn. Only the service's name
is stored, never a URL; the agent builds the URL on its own workspace.
"""
import logging
import re
import threading
import time
from typing import Any, Optional
from urllib.parse import quote

import psycopg2
import requests
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import DatabricksError, NotFound, PermissionDenied, Unauthenticated
from fastapi import HTTPException
from psycopg2.extras import Json

import database
from config import settings
from middleware.auth import agent_auth_headers

logger = logging.getLogger(__name__)

_ADMIN_TTL_SECONDS = 60
_DEFAULTS_TTL_SECONDS = 300
_SPACE_TTL_SECONDS = 3600
_SPACE_MISS_TTL_SECONDS = 600
_lock = threading.Lock()
_admin_cache: dict[str, tuple[float, bool]] = {}
_defaults_cache: Optional[tuple[float, dict]] = None
_space_cache: dict[str, tuple[float, Optional[dict]]] = {}

_DB_ERRORS = (database.LakebaseUnavailable, psycopg2.Error)

#: `catalog.schema.name`, as the agent accepts it (`MCP_SERVICE_RE` in agent/contexts.py).
MCP_SERVICE_RE = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
#: The sandbox runs code and needs a downscoping policy only `agent.toml` can carry.
UNSUPPORTED_MCP_SERVICES = frozenset({"system.ai.sandbox"})
_MCP_SERVICES_PATH = "/api/2.1/unity-catalog/mcp-services"
_MAX_PAGES = 20
_MAX_GENIE_SPACES = 200
_SPACE_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def is_admin(client: WorkspaceClient, email: str) -> bool:
    """Whether the signed-in user is in the admin group. Cached briefly per user."""
    now = time.monotonic()
    with _lock:
        cached = _admin_cache.get(email)
        if cached and now - cached[0] < _ADMIN_TTL_SECONDS:
            return cached[1]
    try:
        me = client.current_user.me()
    except Exception as e:
        logger.warning("Could not read the signed-in user's groups: %s", e)
        return False
    group = settings.get_admin_group()
    member = any(g.display == group for g in me.groups or [])
    with _lock:
        _admin_cache[email] = (now, member)
    return member


def require_admin(client: WorkspaceClient, email: str) -> None:
    if not is_admin(client, email):
        raise HTTPException(
            status_code=403,
            detail=f"Settings are for members of the {settings.get_admin_group()!r} group.",
        )


# --- Rows ---------------------------------------------------------------------

_SELECT = (
    "SELECT context_id, prompt, tools, updated_by, "
    "to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') FROM agent_context_settings"
)


def _row(values: tuple) -> dict:
    context_id, prompt, tools, updated_by, updated_at = values
    return {
        "context_id": context_id,
        "prompt": prompt,
        "tools": tools if isinstance(tools, dict) else {},
        "updated_by": updated_by,
        "updated_at": updated_at,
    }


def _unavailable(e: Exception) -> HTTPException:
    logger.error("The app database is unavailable: %s", e)
    return HTTPException(status_code=503, detail="The app's database is unavailable. Try again in a minute.")


def read_all() -> dict[str, dict]:
    """Every context's saved settings, keyed by context id."""
    try:
        rows = database.run(lambda cur: (cur.execute(_SELECT), cur.fetchall())[1])
    except _DB_ERRORS as e:
        raise _unavailable(e)
    return {row["context_id"]: row for row in map(_row, rows)}


def save(context_id: str, prompt: Optional[str], tools: dict, email: str) -> None:
    try:
        database.run(lambda cur: cur.execute(
            "INSERT INTO agent_context_settings (context_id, prompt, tools, updated_by) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (context_id) DO UPDATE SET prompt = EXCLUDED.prompt, tools = EXCLUDED.tools, "
            "updated_by = EXCLUDED.updated_by, updated_at = now()",
            (context_id, prompt, Json(tools), email),
        ))
    except _DB_ERRORS as e:
        raise _unavailable(e)


def reset(context_id: str) -> None:
    try:
        database.run(lambda cur: cur.execute(
            "DELETE FROM agent_context_settings WHERE context_id = %s", (context_id,)
        ))
    except _DB_ERRORS as e:
        raise _unavailable(e)


# --- Defaults -----------------------------------------------------------------


def _space_metadata(client: WorkspaceClient, space_id: str) -> Optional[dict]:
    """A Genie space's title and description, read as the caller and cached per space."""
    now = time.monotonic()
    with _lock:
        cached = _space_cache.get(space_id)
        if cached and now < cached[0]:
            return cached[1]
    try:
        space = client.genie.get_space(space_id)
        meta: Optional[dict] = {"title": space.title or "", "description": space.description or ""}
    except Exception as e:
        logger.info("Genie space %s not readable by the caller: %s", space_id, e)
        meta = None
    with _lock:
        _space_cache[space_id] = (now + (_SPACE_TTL_SECONDS if meta else _SPACE_MISS_TTL_SECONDS), meta)
    return meta


def default_genie_spaces(client: WorkspaceClient, context_id: str) -> list[dict]:
    """The bundle's Genie bindings for `context_id`, with titles and descriptions from Genie."""
    spaces = []
    for binding in settings.get_genie_bindings().get(context_id, []):
        meta = _space_metadata(client, binding["space_id"]) or {"title": "", "description": ""}
        spaces.append({**binding, **meta})
    return spaces


def for_context(client: WorkspaceClient, context_id: str) -> Optional[dict]:
    """What the agent receives as `input.settings` for this context, or None for its defaults."""
    try:
        rows = database.run(lambda cur: (
            cur.execute(f"{_SELECT} WHERE context_id = %s", (context_id,)),
            cur.fetchall(),
        )[1]) if settings.lakebase_configured() else []
    except _DB_ERRORS as e:
        logger.warning("Could not read agent settings for %r; using the defaults: %s", context_id, e)
        rows = []
    row: dict[str, Any] = _row(rows[0]) if rows else {}
    tools = row.get("tools") or {}
    genie = tools.get("genie")
    if genie is None:
        genie = default_genie_spaces(client, context_id)
    mcp = tools.get("mcp")
    if not row and not genie:
        return None
    return {"prompt": row.get("prompt"), "tools": {"builtin": tools.get("builtin"), "genie": genie, "mcp": mcp}}


def agent_defaults(user_token: Optional[str]) -> dict:
    """The agent's default prompt and tools per context. The same for every user, so cached."""
    global _defaults_cache
    now = time.monotonic()
    with _lock:
        if _defaults_cache and now - _defaults_cache[0] < _DEFAULTS_TTL_SECONDS:
            return _defaults_cache[1]
    url = settings.get_agent_app_url()
    if not url:
        raise HTTPException(status_code=503, detail="No agent configured. Set AGENT_APP_URL.")
    headers = {} if settings.agent_app_is_local() else agent_auth_headers(user_token)
    try:
        response = requests.get(f"{url}/api/contexts", headers=headers, timeout=15, allow_redirects=False)
        response.raise_for_status()
        defaults = response.json()
    except (requests.RequestException, ValueError) as e:
        logger.error("Could not read the agent's context defaults: %s", e)
        raise HTTPException(status_code=502, detail="Could not read the agent's defaults. Is the agent running?")
    with _lock:
        _defaults_cache = (now, defaults)
    return defaults


def genie_space(client: WorkspaceClient, space_id: str) -> dict:
    """A Genie space's title and description, read as the signed-in admin."""
    try:
        space = client.genie.get_space(space_id)
    except Exception as e:
        logger.info("Genie space %s not readable by the admin: %s", space_id, e)
        raise HTTPException(
            status_code=404,
            detail="No Genie space with that id that you can open. Check the id and your CAN_RUN on it.",
        )
    return {"space_id": space_id, "title": space.title or "", "description": space.description or ""}


def list_genie_spaces(client: WorkspaceClient) -> list[dict]:
    """The Genie spaces the signed-in admin can open, by title, for the tool picker."""
    spaces: list[dict] = []
    token = None
    try:
        for _ in range(_MAX_PAGES):
            page = client.genie.list_spaces(page_size=100, page_token=token)
            for space in page.spaces or []:
                if space.space_id and _SPACE_ID_RE.match(space.space_id):
                    spaces.append({
                        "space_id": space.space_id,
                        "title": space.title or "",
                        "description": (space.description or "")[:500],
                    })
            token = page.next_page_token
            if not token or len(spaces) >= _MAX_GENIE_SPACES:
                break
    except DatabricksError as e:
        logger.info("Could not list Genie spaces as the admin: %s", e)
        raise HTTPException(status_code=502, detail=f"Could not list your Genie spaces: {e}")
    return sorted(spaces[:_MAX_GENIE_SPACES], key=lambda s: (s["title"].lower(), s["space_id"]))


def _mcp_api_error(e: DatabricksError, what: str, missing: str) -> HTTPException:
    """A Unity Catalog MCP services error, with the fix that usually applies."""
    if isinstance(e, NotFound):
        return HTTPException(status_code=404, detail=missing)
    if isinstance(e, (PermissionDenied, Unauthenticated)):
        # 403 even for a 401: the tray reads 401 as a lapsed sign-in, and this isn't one.
        return HTTPException(
            status_code=403,
            detail=(
                f"Can't read {what}: {e}. The app needs the `unity-catalog` user scope "
                "(databricks.yml), and you need USE CATALOG and USE SCHEMA on the schema "
                "and EXECUTE on the service."
            ),
        )
    return HTTPException(status_code=502, detail=f"Can't read {what}: {e}")


def list_mcp_services(client: WorkspaceClient, schema: str) -> list[dict]:
    """The MCP services in `schema` the signed-in admin can use, read as the admin."""
    services: dict[str, dict] = {}
    token = None
    seen_tokens: set[str] = set()
    for _ in range(_MAX_PAGES):
        query = {"parent": f"schemas/{schema}"}
        if token:
            query["page_token"] = token
        try:
            page = client.api_client.do("GET", _MCP_SERVICES_PATH, query=query)
        except DatabricksError as e:
            raise _mcp_api_error(
                e, f"the MCP services in {schema}", f"There's no schema {schema} that you can see."
            )
        for raw in (page or {}).get("mcp_services") or []:
            name = str(raw.get("name") or "").removeprefix("mcp-services/")
            if not MCP_SERVICE_RE.match(name) or name in UNSUPPORTED_MCP_SERVICES:
                continue
            services[name] = {
                "service": name,
                "comment": str(raw.get("comment") or "")[:1000],
                # Databricks runs these itself (SQL, Genie, web search); the rest reach a
                # third party, often with each person's own account.
                "databricks_managed": "internal" in (raw.get("config") or {}),
            }
        token = (page or {}).get("next_page_token")
        if not token or token in seen_tokens:
            break
        seen_tokens.add(token)
    return [services[name] for name in sorted(services)]


def mcp_service(client: WorkspaceClient, service: str) -> dict:
    """One MCP service, read as the admin: proves it exists and they can see it."""
    try:
        client.api_client.do("GET", f"{_MCP_SERVICES_PATH}/{quote(service, safe='')}")
    except DatabricksError as e:
        raise _mcp_api_error(
            e, f"the MCP service {service}", f"There's no MCP service {service} that you can use."
        )
    return {"service": service}


def mcp_service_tools(user_token: Optional[str], service: str, refresh: bool = False) -> dict:
    """`service`'s tools as the signed-in admin sees them, listed by the agent.

    The agent lists them because it holds the MCP client and uses the same code
    on each turn, so the names an admin picks are the names it offers. Answers
    `{service, tools: [{name, description, read_only, offerable}], problem}`;
    `problem` says why a service listed nothing, and whether signing in fixes it.
    """
    url = settings.get_agent_app_url()
    if not url:
        raise HTTPException(status_code=503, detail="No agent configured. Set AGENT_APP_URL.")
    headers = {} if settings.agent_app_is_local() else agent_auth_headers(user_token)
    try:
        response = requests.get(
            f"{url}/api/mcp-services/{quote(service, safe='')}/tools",
            params={"refresh": "true"} if refresh else None,
            headers=headers,
            timeout=60,
            allow_redirects=False,
        )
    except requests.RequestException as e:
        logger.error("Could not ask the agent for %s's tools: %s", service, e)
        raise HTTPException(status_code=502, detail="Could not reach the agent. Is it running?")
    if response.status_code == 404:
        raise HTTPException(
            status_code=502,
            detail="The agent can't list MCP tools yet. Redeploy it (../deploy.sh) and try again.",
        )
    try:
        response.raise_for_status()
        body = response.json()
    except (requests.RequestException, ValueError) as e:
        logger.error("The agent could not list %s's tools: %s", service, e)
        raise HTTPException(status_code=502, detail=f"The agent could not list {service}'s tools.")
    return {
        "service": service,
        "tools": body.get("tools") if isinstance(body.get("tools"), list) else [],
        "problem": body.get("problem"),
    }
