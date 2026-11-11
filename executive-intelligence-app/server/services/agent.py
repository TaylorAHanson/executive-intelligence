"""Calls to the Executive Intelligence agent app.

The browser never talks to the agent. It calls `/api/agent/...` on this app, and
this module forwards the turn to the agent's `/api/invocations` endpoint. That
keeps every credential server-side, and it is where the signed-in user's
identity is attached — from the proxy headers, never from the request body.

Two identities matter, and they are easy to conflate:

  * The **actor** is the signed-in user's email. The agent partitions long-term
    memory by actor, so what it learns about one user is not recalled for
    another.
  * The **session** is one conversation. The agent namespaces sessions by the
    authenticated caller, which is this app's service principal for every user,
    so the browser's session id is hashed together with the user's email here.
    Otherwise two users sending the same id would share a conversation.

The pure helpers (`session_key`, `invocation_body`, `resume_body`,
`normalize_output`) hold all of the logic and are tested without a network in
`tests/test_agent.py`.
"""
import logging
import uuid
from typing import Any, Optional

import requests
from fastapi import HTTPException

from config import settings
from middleware.auth import get_agent_app_client

logger = logging.getLogger(__name__)

# Fixed namespace so the same (user, browser session) always maps to the same
# agent session, across workers and restarts.
_SESSION_NAMESPACE = uuid.UUID("6b3f6f0e-2f5c-4c1e-9a7e-0f6f5e1c2d3a")

_MAX_TOOL_OUTPUT_CHARS = 600


def session_key(user_email: str, client_session_id: str) -> str:
    """The agent session id for one user's browser session."""
    return str(uuid.uuid5(_SESSION_NAMESPACE, f"{user_email}\n{client_session_id}"))


def invocation_body(*, session: str, actor: str, context: str, message: str) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "session_id": session,
        "input": {
            "messages": [{"role": "user", "content": message}],
            "actor": actor,
            "context": context,
        },
    }


def resume_body(*, session: str, actor: str, context: str, decisions: list[dict]) -> dict:
    """Answer a paused approval. Same session and actor, new invocation id."""
    return {
        "id": str(uuid.uuid4()),
        "session_id": session,
        "input": {"resume": {"decisions": decisions}, "actor": actor, "context": context},
    }


def _text(content: Any) -> str:
    """Answer text from a LangChain message's `content`, which is a string or parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def normalize_output(result: dict) -> dict:
    """Reduce the agent's native output to what the tray renders.

    The agent returns serialized LangChain messages plus HITL `interrupt` events.
    Reasoning parts are dropped, tool results are truncated, and an interrupt is
    reduced to the tool calls awaiting approval.
    """
    messages: list[dict] = []
    interrupt: Optional[dict] = None

    for item in (result.get("output") or {}).get("output") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "interrupt":
            value = item.get("value") or {}
            interrupt = {
                "actions": [
                    {"name": action.get("name", ""), "args": action.get("args") or {}}
                    for action in value.get("action_requests") or []
                    if isinstance(action, dict)
                ]
            }
        elif item.get("type") == "tool":
            messages.append({
                "role": "tool",
                "name": item.get("name") or "tool",
                "content": _text(item.get("content"))[:_MAX_TOOL_OUTPUT_CHARS],
            })
        elif item.get("type") == "ai" or item.get("role") == "assistant":
            text = _text(item.get("content"))
            if text:
                messages.append({"role": "assistant", "content": text})

    status = (result.get("output") or {}).get("status") or result.get("status") or "completed"
    return {"status": status, "messages": messages, "interrupt": interrupt}


def _error_detail(response: requests.Response) -> str:
    """The agent's sanitized error message. Its error bodies never carry credentials."""
    try:
        body = response.json()
    except ValueError:
        return f"Agent returned HTTP {response.status_code}."
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict) and error.get("message"):
        return f"Agent error ({error.get('code', response.status_code)}): {error['message']}"
    if isinstance(body, dict) and isinstance(body.get("detail"), str):
        return f"Agent error: {body['detail']}"
    return f"Agent returned HTTP {response.status_code}."


def invoke(body: dict) -> dict:
    """POST one invocation and return the normalized result. Blocking."""
    url = settings.get_agent_app_url()
    if not url:
        raise HTTPException(
            status_code=503,
            detail="No agent configured. Set AGENT_APP_URL (deploy.sh sets it on deploy).",
        )

    headers = {"Content-Type": "application/json", "X-Routing-Key": body["session_id"]}
    if not settings.agent_app_is_local():
        headers.update(get_agent_app_client().config.authenticate())

    try:
        response = requests.post(
            f"{url}/api/invocations",
            json=body,
            headers=headers,
            timeout=settings.get_agent_timeout_seconds(),
            # The Apps proxy answers an unauthenticated call with a login
            # redirect; following it would turn an auth failure into HTML.
            allow_redirects=False,
        )
    except requests.Timeout:
        raise HTTPException(status_code=504, detail="The agent took too long to answer. Try again.")
    except requests.RequestException as e:
        # The exception text can include the URL but never the headers.
        logger.error("Agent request failed: %s", e)
        raise HTTPException(status_code=502, detail="Could not reach the agent app.")

    if response.status_code in (301, 302, 303, 307, 308, 401, 403):
        logger.error("Agent app rejected this app's credentials: HTTP %s", response.status_code)
        raise HTTPException(
            status_code=502,
            detail="The agent app rejected this app's credentials. Grant this app's service principal CAN_USE on it.",
        )
    if not response.ok:
        raise HTTPException(status_code=502, detail=_error_detail(response))

    try:
        result = response.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="The agent app returned a non-JSON response.")
    return normalize_output(result)
