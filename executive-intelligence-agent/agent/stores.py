"""Keep the agent answering when its managed stores are not available.

The agent uses two stores from the Agent Memory Sessions preview. The Session Store holds each
conversation's state (the checkpointer, which every turn reads and writes, and approval pauses).
The Memory Store holds long-term memory, which the model reaches through four tools. In a
workspace where the preview is not enabled, both fail with FEATURE_DISABLED, and because the
checkpointer is used on every turn, every request failed.

This module makes both fail open:

- Before a turn's graph is built, `refresh()` checks each store that is configured with one
  read-only request. A store that cannot answer is left out for this process: conversation state
  falls back to `InMemorySaver`, and the memory tools are not offered.
- A store that failed is checked again after `RECHECK_SECONDS`, so enabling the preview, or a brief
  outage ending, takes effect without a restart. A store that works is not checked again.
- A memory tool that fails mid-turn returns a plain message instead of raising, so the turn
  finishes. If the failure is the preview gate, memory is switched off for the next turns too.
- `system_prompt(..., memory=False)` (agent/contexts.py) tells the model it has no memory, so it
  does not promise to remember anything.

What failing open costs, so nobody is surprised by it:

- Conversation state kept in the process is lost when the process restarts, is not shared between
  instances, and is not moved to the Session Store when it comes back. A conversation spanning a
  switch loses the turns before it.
- Nothing is remembered across conversations while memory is off.
- Only the checks and the memory tools fail open. A Session Store that fails after it passed its
  check still fails the request: there is no safe way to move a conversation to another store
  halfway through it.
- Nothing is shared between users: the client hashes each session id with the user, and the memory
  tools are only ever built for one actor.
"""

import asyncio
import functools
import logging
import threading
import time
from dataclasses import dataclass, replace
from typing import Any, Callable

from langchain_core.tools import BaseTool, StructuredTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from databricks_agentkit import workspace_client
from databricks_agentkit.client import AgentKitClient
from databricks_agentkit.langgraph import checkpointer, memory_tools
from databricks_agentkit.runtime.tool_manifest import resolve_memory_store, resolve_session_store

logger = logging.getLogger(__name__)

#: How long after a failed check before the next one.
RECHECK_SECONDS = 60.0
#: How long a request waits for a check before treating the stores as unavailable.
CHECK_TIMEOUT_SECONDS = 15.0

#: Error codes that mean "this preview API is not enabled in the workspace".
PREVIEW_CODES = frozenset({"FEATURE_DISABLED", "NOT_IMPLEMENTED", "UNIMPLEMENTED"})

MEMORY_TOOL_UNAVAILABLE = (
    "Long-term memory is unavailable right now, so nothing was saved or recalled. Carry on without "
    "it, and tell the user plainly that you could not use memory."
)


@dataclass(frozen=True)
class Status:
    """What the managed stores can do now. `checked_at` is None until the first check."""

    checked_at: float | None = None
    #: Conversation state is in the managed Session Store (else it is in this process).
    session: bool = False
    #: The long-term memory tools are offered.
    memory: bool = False
    #: Why a store that is configured is not in use. None when it is in use or not configured.
    session_reason: str | None = None
    memory_reason: str | None = None

    @property
    def degraded(self) -> bool:
        return bool(self.session_reason or self.memory_reason)


_status = Status()
_lock = threading.Lock()
#: Where conversation state goes while the Session Store is unavailable. One per process, so a
#: conversation keeps its history for as long as the store stays unavailable.
_fallback_saver = InMemorySaver()
_now: Callable[[], float] = time.monotonic


def status() -> Status:
    """The last known state of the stores, without checking them."""
    return _status


# --- Errors ------------------------------------------------------------------------------------


def error_code(exc: BaseException | None) -> str | None:
    """The service error code on `exc` or whatever it was raised from, if it has one."""
    for _ in range(5):
        if exc is None:
            return None
        code = getattr(exc, "error_code", None)
        if isinstance(code, str) and code:
            return code
        exc = exc.__cause__ or exc.__context__
    return None


def is_preview_error(exc: BaseException) -> bool:
    """True when the store API is switched off in this workspace, as opposed to failing."""
    return error_code(exc) in PREVIEW_CODES or "FEATURE_DISABLED" in str(exc)


def describe(exc: BaseException) -> str:
    """One line for a log or a reason: the code, and what to do when it is the preview gate."""
    code = error_code(exc) or type(exc).__name__
    detail = " ".join(str(exc).split())[:160]
    if is_preview_error(exc):
        return f"{code}: the Agent Memory Sessions preview is not enabled in this workspace"
    return f"{code}: {detail}" if detail else code


# --- Checking ----------------------------------------------------------------------------------


def _probe_session(name: str) -> None:
    """One read that needs the Session Store API enabled and the store to exist. Writes nothing."""
    AgentKitClient(workspace_client()).session_stores.get(name)


def _probe_memory(store_id: str) -> None:
    """The same for the Memory Store."""
    AgentKitClient(workspace_client()).memory_stores.get(store_id)


def _try(probe: Callable[[str], None], name: str | None) -> tuple[bool, str | None]:
    """(in use, why not). A store that is not configured is simply not in use."""
    if not name:
        return False, None
    try:
        probe(name)
    except Exception as exc:  # noqa: BLE001 - a store that cannot answer, for any reason, is done without
        return False, describe(exc)
    return True, None


def _due(status: Status) -> bool:
    if status.checked_at is None:
        return True
    return status.degraded and _now() - status.checked_at >= RECHECK_SECONDS


def _check() -> Status:
    """Check the configured stores (blocking; run in a thread). Serialized, and skipped if another
    request has just done it."""
    global _status
    with _lock:
        if not _due(_status):
            return _status
        session, session_reason = _try(_probe_session, resolve_session_store())
        memory, memory_reason = _try(_probe_memory, resolve_memory_store())
        new = Status(_now(), session, memory, session_reason, memory_reason)
        _log_changes(_status, new)
        _status = new
        return new


def _log_changes(old: Status, new: Status) -> None:
    for kind, was, now, reason in (
        ("Session Store", old.session_reason, new.session, new.session_reason),
        ("Memory Store", old.memory_reason, new.memory, new.memory_reason),
    ):
        if reason and reason != was:
            logger.warning("%s unavailable, so the agent runs without it (%s).", kind, reason)
        elif was and now:
            logger.info("%s is available again.", kind)


async def refresh() -> Status:
    """Check the stores if they have not been checked, or if one that failed is due another look.

    Call this before building a turn's graph. It costs nothing once the stores have passed.
    """
    global _status
    if not _due(_status):
        return _status
    try:
        return await asyncio.wait_for(asyncio.shield(asyncio.to_thread(_check)), CHECK_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        # Slower to answer than a request should wait: do without for now. The check carries on in
        # its thread, and its result replaces this the next time it completes.
        reason = f"no answer within {CHECK_TIMEOUT_SECONDS:g}s"
        _status = Status(
            _now(),
            session=False,
            memory=False,
            session_reason=reason if resolve_session_store() else None,
            memory_reason=reason if resolve_memory_store() else None,
        )
        logger.warning("Checking the agent's stores timed out; running without them (%s).", reason)
        return _status


# --- What the agent builds from the result -----------------------------------------------------


def session_saver() -> BaseCheckpointSaver:
    """The checkpointer for a turn: the managed Session Store, else this process's memory.

    The managed store is used until a check has found it unavailable.
    """
    if resolve_session_store() and _status.checked_at is not None and not _status.session:
        return _fallback_saver
    return checkpointer()


def memory_tools_for(actor: str) -> list[BaseTool]:
    """The long-term memory tools for `actor`, or none when memory is not available.

    Built for one actor and never reused for another, as the package requires. Each tool answers
    with a plain message, rather than raising, when the store fails mid-turn.
    """
    if not _status.memory:
        return []
    return [_guarded(tool) for tool in memory_tools(actor)]


def _guarded(tool: BaseTool) -> BaseTool:
    inner = getattr(tool, "func", None)
    if not isinstance(tool, StructuredTool) or inner is None:
        return tool

    @functools.wraps(inner)
    def run(*args: Any, **kwargs: Any) -> Any:
        try:
            return inner(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - memory must never take a turn down
            _tool_failed(tool.name, exc)
            return MEMORY_TOOL_UNAVAILABLE

    return StructuredTool(
        name=tool.name, description=tool.description, args_schema=tool.args_schema, func=run
    )


def _tool_failed(name: str, exc: BaseException) -> None:
    global _status
    logger.warning("Memory tool %s failed (%s); answering without it.", name, describe(exc))
    if is_preview_error(exc):
        # The gate is closed: stop offering the tools, and look again in a minute.
        _status = replace(_status, memory=False, memory_reason=describe(exc), checked_at=_now())
