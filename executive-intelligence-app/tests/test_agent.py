"""Tests for the agent proxy.

Deliberately dependency-free: no pytest, no network, no Databricks credentials.
Run it directly.

    server/venv/bin/python tests/test_agent.py

These pin the identity behaviour that is expensive to get wrong: two users can
never land in the same agent session, the actor always comes from the caller,
and the agent's native output reduces to what the tray renders.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

from services.agent import (  # noqa: E402
    invocation_body,
    normalize_output,
    resume_body,
    session_key,
)

passed = 0
failed = 0


def check(description: str, condition: bool) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  ok   {description}")
    else:
        failed += 1
        print(f"  FAIL {description}")


browser_session = "0f8c2f4e-6a1b-4c6d-9e2f-3a4b5c6d7e8f"

check(
    "the same user and browser session always map to the same agent session",
    session_key("a@example.com", browser_session) == session_key("a@example.com", browser_session),
)
check(
    "two users sending the same browser session id get different agent sessions",
    session_key("a@example.com", browser_session) != session_key("b@example.com", browser_session),
)
check(
    "the agent session is not the browser's id",
    session_key("a@example.com", browser_session) != browser_session,
)

body = invocation_body(session="s-1", actor="a@example.com", context="market-intelligence", message="hi")
check("a turn carries the actor inside input, where the agent reads it", body["input"]["actor"] == "a@example.com")
check("a turn carries the app context", body["input"]["context"] == "market-intelligence")
check("a turn sends the session at the top level", body["session_id"] == "s-1" and "actor" not in body)
check(
    "each turn gets a fresh invocation id",
    invocation_body(session="s", actor="a", context="general", message="x")["id"]
    != invocation_body(session="s", actor="a", context="general", message="x")["id"],
)

resume = resume_body(session="s-1", actor="a@example.com", context="general", decisions=[{"type": "approve"}])
check("a resume answers with decisions", resume["input"]["resume"] == {"decisions": [{"type": "approve"}]})
check("a resume keeps the same session and actor", resume["session_id"] == "s-1" and resume["input"]["actor"] == "a@example.com")

completed = normalize_output({
    "id": "inv-1",
    "status": "completed",
    "output": {
        "status": "completed",
        "output": [
            {"type": "ai", "content": "", "tool_calls": [{"name": "recall"}]},
            {"type": "tool", "name": "recall", "content": "x" * 5000},
            {"role": "assistant", "content": [{"type": "reasoning", "summary": "thinking"}]},
            {"type": "ai", "content": [{"type": "text", "text": "Your color is "}, {"type": "text", "text": "teal."}]},
        ],
    },
})
check("a completed turn reports completed", completed["status"] == "completed" and completed["interrupt"] is None)
check(
    "tool results are kept and truncated",
    completed["messages"][0]["role"] == "tool" and len(completed["messages"][0]["content"]) == 600,
)
check(
    "reasoning and empty tool-call messages are dropped; text parts are joined",
    [m for m in completed["messages"] if m["role"] == "assistant"] == [
        {"role": "assistant", "content": "Your color is teal."}
    ],
)

interrupted = normalize_output({
    "status": "completed",
    "output": {
        "status": "interrupted",
        "output": [
            {
                "type": "interrupt",
                "id": "int-1",
                "value": {
                    "action_requests": [{"name": "send_message", "args": {"recipient": "cfo", "body": "hi"}}],
                    "review_configs": [{"action_name": "send_message", "allowed_decisions": ["approve", "reject"]}],
                },
            }
        ],
    },
})
check("an approval pause reports interrupted, not the outer status", interrupted["status"] == "interrupted")
check(
    "an approval pause lists the tool calls awaiting a decision",
    interrupted["interrupt"] == {"actions": [{"name": "send_message", "args": {"recipient": "cfo", "body": "hi"}}]},
)

check("an empty response normalizes without failing", normalize_output({})["messages"] == [])


# The agent runs its data tools as whoever calls it, so the call must carry the
# user's token, and a deployment must refuse rather than fall back to the app.
import os  # noqa: E402

from fastapi import HTTPException  # noqa: E402

from middleware.auth import agent_auth_headers  # noqa: E402

os.environ["DATABRICKS_APP_NAME"] = "exec-intel-app"
os.environ["DATABRICKS_CLIENT_ID"] = "app-sp"
os.environ["DATABRICKS_CLIENT_SECRET"] = "app-secret"
check(
    "a deployed call to the agent carries the signed-in user's token",
    agent_auth_headers("user-token") == {"Authorization": "Bearer user-token"},
)
try:
    agent_auth_headers(None)
    refused = False
except HTTPException as e:
    refused = e.status_code == 401
check("a deployed call with no user token is refused, never sent as the app", refused)
for name in ("DATABRICKS_APP_NAME", "DATABRICKS_CLIENT_ID", "DATABRICKS_CLIENT_SECRET"):
    del os.environ[name]


print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
