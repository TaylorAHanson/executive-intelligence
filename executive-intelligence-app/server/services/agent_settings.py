"""The agent's per-context settings: prompt and tools, edited by admins in Settings.

Settings live in a Unity Catalog table (`settings.get_agent_settings_table`),
one row per app context. Every read and write runs as the signed-in user:

  * The tray reads the current context's row on each turn and sends it to the
    agent as `input.settings` (`for_context`). Users need SELECT on the table;
    without it the agent falls back to its defaults, and the log says why.
  * The Settings page writes rows as the signed-in admin (`save`, `reset`). Only
    the admin group has MODIFY (`data/admin_grants.sql`), so Unity Catalog
    enforces the rule `is_admin` checks for the UI.

Defaults are the agent's (`agent/contexts.py`), read from its `/api/contexts`
route. A context with no row, or a NULL column, uses them.
"""
import json
import logging
import threading
import time
from typing import Any, Optional

import requests
from databricks.sdk import WorkspaceClient
from fastapi import HTTPException

from config import settings
from middleware.auth import agent_auth_headers
from services.sql import run_query

logger = logging.getLogger(__name__)

_ADMIN_TTL_SECONDS = 60
_DEFAULTS_TTL_SECONDS = 300
_lock = threading.Lock()
_admin_cache: dict[str, tuple[float, bool]] = {}
_defaults_cache: Optional[tuple[float, dict]] = None


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


def _table() -> str:
    try:
        return settings.get_agent_settings_table()
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))


def _row(row: dict[str, Any]) -> dict:
    try:
        tools = json.loads(row.get("tools") or "{}")
    except ValueError:
        logger.warning("Agent settings for %r have unreadable tools JSON; ignoring it.", row.get("context_id"))
        tools = {}
    return {
        "context_id": row.get("context_id"),
        "prompt": row.get("prompt"),
        "tools": tools if isinstance(tools, dict) else {},
        "updated_by": row.get("updated_by"),
        "updated_at": row.get("updated_at"),
    }


def read_all(client: WorkspaceClient) -> dict[str, dict]:
    """Every context's saved settings, keyed by context id."""
    result = run_query(
        client,
        f"SELECT context_id, prompt, tools, updated_by, CAST(updated_at AS STRING) AS updated_at FROM {_table()}",
    )
    return {row["context_id"]: row for row in map(_row, result["rows"])}


def for_context(client: WorkspaceClient, context_id: str) -> Optional[dict]:
    """What the agent receives as `input.settings` for this context, or None for its defaults.

    Never fails the turn: a missing table or grant logs a warning and the agent
    answers with its defaults instead.
    """
    try:
        result = run_query(
            client,
            f"SELECT context_id, prompt, tools FROM {_table()} WHERE context_id = :context_id",
            {"context_id": context_id},
            max_rows=1,
        )
    except HTTPException as e:
        logger.warning("Could not read agent settings for %r; using the agent's defaults: %s", context_id, e.detail)
        return None
    if not result["rows"]:
        return None
    row = _row(result["rows"][0])
    return {"prompt": row["prompt"], "tools": row["tools"]}


def save(client: WorkspaceClient, context_id: str, prompt: Optional[str], tools: dict, email: str) -> None:
    run_query(
        client,
        f"MERGE INTO {_table()} t "
        "USING (SELECT :context_id AS context_id, :prompt AS prompt, :tools AS tools, :email AS email) s "
        "ON t.context_id = s.context_id "
        "WHEN MATCHED THEN UPDATE SET prompt = s.prompt, tools = s.tools, "
        "updated_by = s.email, updated_at = current_timestamp() "
        "WHEN NOT MATCHED THEN INSERT (context_id, prompt, tools, updated_by, updated_at) "
        "VALUES (s.context_id, s.prompt, s.tools, s.email, current_timestamp())",
        {"context_id": context_id, "prompt": prompt, "tools": json.dumps(tools), "email": email},
    )


def reset(client: WorkspaceClient, context_id: str) -> None:
    run_query(client, f"DELETE FROM {_table()} WHERE context_id = :context_id", {"context_id": context_id})


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
