"""Tests for the agent's per-context settings (Settings page and tray).

Deliberately dependency-free: no pytest, no network, no Databricks credentials.
Run it directly.

    server/venv/bin/python tests/test_agent_settings.py

What these pin: values reach SQL as bound parameters, a settings read never
fails a tray turn, only the admin group passes the admin check, and the routes
reject what the agent would silently drop.
"""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
os.environ.update({"DATA_CATALOG": "cat", "DATA_SCHEMA": "sch", "SQL_WAREHOUSE_ID": "w-1", "ADMIN_GROUP": "exec-admins"})

from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from routes.settings import ContextSettingsUpdate  # noqa: E402
from services import agent_settings  # noqa: E402
from services.agent import invocation_body, resume_body  # noqa: E402

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


SPACE = "0123456789abcdef0123456789abcdef"


class Recorder:
    """Stands in for services.sql.run_query and records each call."""

    def __init__(self, result=None, error=None):
        self.calls = []
        self.result = result or {"columns": [], "rows": []}
        self.error = error

    def __call__(self, client, statement, parameters=None, **kwargs):
        self.calls.append((statement, parameters or {}))
        if self.error:
            raise self.error
        return self.result


# --- Request bodies ---------------------------------------------------------

body = invocation_body(session="s", actor="a@x.com", context="executive", message="hi")
check("no settings: the agent input has no settings key", "settings" not in body["input"])
settings = {"prompt": "Custom.", "tools": {"genie": []}}
body = invocation_body(session="s", actor="a@x.com", context="executive", message="hi", settings=settings)
check("settings travel as input.settings on a chat turn", body["input"]["settings"] == settings)
body = resume_body(session="s", actor="a@x.com", context="executive", decisions=[{"type": "approve"}], settings=settings)
check("and on an approval resume, since the agent rebuilds its tools", body["input"]["settings"] == settings)

# --- Reading for the tray ---------------------------------------------------

tools = {"builtin": None, "genie": [{"name": "ci_data", "space_id": SPACE}]}
agent_settings.run_query = Recorder({"columns": ["context_id", "prompt", "tools"], "rows": [{"context_id": "ci", "prompt": None, "tools": json.dumps(tools)}]})
got = agent_settings.for_context(object(), "customer-intelligence")
statement, params = agent_settings.run_query.calls[0]
check("the context id is a bound parameter", params == {"context_id": "customer-intelligence"} and "customer-intelligence" not in statement)
check("the row becomes prompt + parsed tools", got == {"prompt": None, "tools": tools})

agent_settings.run_query = Recorder({"columns": ["context_id", "prompt", "tools"], "rows": []})
check("no row means the agent's defaults (None)", agent_settings.for_context(object(), "general") is None)

agent_settings.run_query = Recorder(error=HTTPException(status_code=403, detail="no SELECT"))
check("a failed read falls back to defaults instead of failing the turn", agent_settings.for_context(object(), "general") is None)

agent_settings.run_query = Recorder({"columns": ["context_id", "prompt", "tools"], "rows": [{"context_id": "x", "prompt": "P", "tools": "{not json"}]})
check("unreadable tools JSON is treated as no tools", agent_settings.for_context(object(), "x") == {"prompt": "P", "tools": {}})

agent_settings.run_query = Recorder({"columns": [], "rows": [
    {"context_id": "executive", "prompt": "P", "tools": "{}", "updated_by": "a@x.com", "updated_at": "2026-11-12"},
    {"context_id": "signals", "prompt": None, "tools": None, "updated_by": "b@x.com", "updated_at": "2026-11-11"},
]})
everything = agent_settings.read_all(object())
check("read_all keys rows by context id", set(everything) == {"executive", "signals"})
check("and keeps who saved each one", everything["signals"]["updated_by"] == "b@x.com" and everything["signals"]["tools"] == {})

# --- Writing ----------------------------------------------------------------

agent_settings.run_query = Recorder()
agent_settings.save(object(), "executive", "Hello'; DROP TABLE x; --", {"builtin": None, "genie": []}, "admin@x.com")
statement, params = agent_settings.run_query.calls[0]
check("save binds every value", params["prompt"].startswith("Hello'") and "DROP TABLE" not in statement)
check("save records who changed it", params["email"] == "admin@x.com")
check("save targets the configured table", "`cat`.`sch`.`agent_context_settings`" in statement)

# --- Admin check ------------------------------------------------------------


def client_in(*groups):
    me = SimpleNamespace(groups=[SimpleNamespace(display=g) for g in groups])
    return SimpleNamespace(current_user=SimpleNamespace(me=lambda: me))


check("a member of ADMIN_GROUP is an admin", agent_settings.is_admin(client_in("users", "exec-admins"), "a@x.com"))
check("anyone else is not", not agent_settings.is_admin(client_in("users", "admins"), "b@x.com"))
try:
    agent_settings.require_admin(client_in("users"), "c@x.com")
    check("require_admin refuses non-admins with 403", False)
except HTTPException as e:
    check("require_admin refuses non-admins with 403", e.status_code == 403)


def failing_me():
    raise RuntimeError("scope missing")


broken = SimpleNamespace(current_user=SimpleNamespace(me=failing_me))
check("an unreadable group list counts as not an admin", not agent_settings.is_admin(broken, "d@x.com"))

# --- Route validation -------------------------------------------------------


def rejected(payload) -> bool:
    try:
        ContextSettingsUpdate(**payload)
    except ValidationError:
        return True
    return False


check("a valid update parses", not rejected({"prompt": "x", "genie_spaces": [{"name": "ci_data", "space_id": SPACE}]}))
check("a tool name the agent would drop is rejected", rejected({"genie_spaces": [{"name": "CI-Data", "space_id": SPACE}]}))
check("a space id that isn't 32 hex characters is rejected", rejected({"genie_spaces": [{"name": "ci", "space_id": "../x"}]}))
check("an over-long prompt is rejected", rejected({"prompt": "x" * 8001}))
check("more than ten spaces is rejected",
      rejected({"genie_spaces": [{"name": f"s{i}", "space_id": SPACE} for i in range(11)]}))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
