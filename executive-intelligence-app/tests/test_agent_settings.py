"""Tests for the agent's per-context settings (Settings page and tray).

Runs against a real Postgres: the bundled one from requirements-dev.txt, in a
temporary directory, so the SQL is exercised rather than mocked. No network, no
Databricks credentials. Run it directly.

    server/venv/bin/python tests/test_agent_settings.py

What these pin: saved rows override the defaults field by field, the bundle's
Genie bindings are the defaults and come back on reset, a database outage never
fails a tray turn, only the admin group passes the admin check, the routes
reject what the agent would silently drop, and the tool picker lists Genie
spaces and MCP services as the admin and asks the agent for a service's tools.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

SPACE_A = "0123456789abcdef0123456789abcdef"
SPACE_B = "fedcba9876543210fedcba9876543210"
pgdata = tempfile.mkdtemp(prefix="exec-intel-pg-")
os.environ.pop("PGHOST", None)
os.environ.update({
    "LOCAL_POSTGRES_DIR": pgdata,
    "ADMIN_GROUP": "exec-admins",
    "GENIE_BINDINGS": f"executive:exec_data:{SPACE_A}  customer-intelligence:ci_data:{SPACE_B},bad-entry",
})

from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402

import database  # noqa: E402
from config import settings  # noqa: E402
from databricks.sdk.errors import NotFound, PermissionDenied  # noqa: E402

import routes.settings as settings_routes  # noqa: E402
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


class FakeGenie:
    def __init__(self, readable):
        self.readable = readable
        self.calls = 0

    def get_space(self, space_id):
        self.calls += 1
        if space_id not in self.readable:
            raise PermissionError("no CAN_RUN")
        return SimpleNamespace(title=f"Space {space_id[:4]}", description="About the space.")


def client_with(readable=(), groups=()):
    me = SimpleNamespace(groups=[SimpleNamespace(display=g) for g in groups])
    return SimpleNamespace(genie=FakeGenie(set(readable)), current_user=SimpleNamespace(me=lambda: me))


try:
    database.init_db()

    # --- Bundle bindings ------------------------------------------------------

    bindings = settings.get_genie_bindings()
    check("GENIE_BINDINGS parses context:tool_name:space_id entries",
          bindings == {"executive": [{"name": "exec_data", "space_id": SPACE_A}],
                       "customer-intelligence": [{"name": "ci_data", "space_id": SPACE_B}]})

    # --- The tray, with nothing saved -----------------------------------------

    client = client_with(readable={SPACE_A})
    got = agent_settings.for_context(client, "executive")
    check("with no row, the bundle's binding is the context's Genie space",
          got == {"prompt": None, "tools": {"builtin": None, "genie": [
              {"name": "exec_data", "space_id": SPACE_A, "title": "Space 0123", "description": "About the space."}],
              "mcp": None}})
    agent_settings.for_context(client, "executive")
    check("the space's title is read from Genie once and cached", client.genie.calls == 1)
    check("a context with no row and no binding sends nothing",
          agent_settings.for_context(client, "general") is None)
    unreadable = agent_settings.for_context(client_with(), "customer-intelligence")
    check("a space the caller can't open is still offered, without a title",
          unreadable["tools"]["genie"][0]["space_id"] == SPACE_B and unreadable["tools"]["genie"][0]["title"] == "")

    # --- Saving and resetting ---------------------------------------------------

    agent_settings.save("executive", "Hello'; DROP TABLE agent_context_settings; --",
                        {"builtin": ["get_current_time"], "genie": None}, "admin@x.com")
    rows = agent_settings.read_all()
    check("a saved row reads back", rows["executive"]["prompt"].startswith("Hello'"))
    check("and records who changed it and when", rows["executive"]["updated_by"] == "admin@x.com"
          and len(rows["executive"]["updated_at"] or "") == 19)
    got = agent_settings.for_context(client, "executive")
    check("a saved prompt and tool list override the defaults", got["prompt"].startswith("Hello'")
          and got["tools"]["builtin"] == ["get_current_time"])
    check("a NULL Genie list keeps the bundle's binding", got["tools"]["genie"][0]["name"] == "exec_data")

    agent_settings.save("executive", None, {"builtin": None, "genie": []}, "admin@x.com")
    check("an empty Genie list removes the binding",
          agent_settings.for_context(client, "executive")["tools"]["genie"] == [])

    agent_settings.save("executive", None, {"builtin": None, "genie": [{"name": "other", "space_id": SPACE_B}]}, "b@x.com")
    rows = agent_settings.read_all()
    check("saving again updates the row instead of adding one",
          len(rows) == 1 and rows["executive"]["updated_by"] == "b@x.com")

    agent_settings.reset("executive")
    check("reset deletes the row", agent_settings.read_all() == {})
    check("and the bundle's binding is back",
          agent_settings.for_context(client, "executive")["tools"]["genie"][0]["name"] == "exec_data")

    # --- Outages ----------------------------------------------------------------

    real_run = database.run

    def down(_work):
        raise database.LakebaseUnavailable("compute waking up")

    database.run = down
    got = agent_settings.for_context(client, "executive")
    check("a database outage still sends the bundle's bindings", got["tools"]["genie"][0]["name"] == "exec_data")
    for label, call in (("read", agent_settings.read_all), ("save", lambda: agent_settings.save("x", None, {}, "a"))):
        try:
            call()
            check(f"a {label} during an outage answers 503", False)
        except HTTPException as e:
            check(f"a {label} during an outage answers 503", e.status_code == 503)
    database.run = real_run

    # --- Request bodies -----------------------------------------------------------

    body = invocation_body(session="s", actor="a@x.com", context="executive", message="hi")
    check("no settings: the agent input has no settings key", "settings" not in body["input"])
    sent = {"prompt": "Custom.", "tools": {"genie": []}}
    body = invocation_body(session="s", actor="a@x.com", context="executive", message="hi", settings=sent)
    check("settings travel as input.settings on a chat turn", body["input"]["settings"] == sent)
    body = resume_body(session="s", actor="a@x.com", context="executive", decisions=[{"type": "approve"}], settings=sent)
    check("and on an approval resume, since the agent rebuilds its tools", body["input"]["settings"] == sent)

    # --- Admin check ----------------------------------------------------------------

    check("a member of ADMIN_GROUP is an admin",
          agent_settings.is_admin(client_with(groups=("users", "exec-admins")), "a@x.com"))
    check("anyone else is not", not agent_settings.is_admin(client_with(groups=("users", "admins")), "b@x.com"))
    try:
        agent_settings.require_admin(client_with(groups=("users",)), "c@x.com")
        check("require_admin refuses non-admins with 403", False)
    except HTTPException as e:
        check("require_admin refuses non-admins with 403", e.status_code == 403)

    def failing_me():
        raise RuntimeError("scope missing")

    broken = SimpleNamespace(current_user=SimpleNamespace(me=failing_me))
    check("an unreadable group list counts as not an admin", not agent_settings.is_admin(broken, "d@x.com"))

    # --- Route validation -----------------------------------------------------------

    def rejected(payload) -> bool:
        try:
            ContextSettingsUpdate(**payload)
        except ValidationError:
            return True
        return False

    check("a valid update parses", not rejected({"prompt": "x", "genie_spaces": [{"name": "ci_data", "space_id": SPACE_A}]}))
    check("an update may leave the Genie spaces at their default", ContextSettingsUpdate().genie_spaces is None)
    check("a tool name the agent would drop is rejected", rejected({"genie_spaces": [{"name": "CI-Data", "space_id": SPACE_A}]}))
    check("a space id that isn't 32 hex characters is rejected", rejected({"genie_spaces": [{"name": "ci", "space_id": "../x"}]}))
    check("an over-long prompt is rejected", rejected({"prompt": "x" * 8001}))
    check("more than ten spaces is rejected",
          rejected({"genie_spaces": [{"name": f"s{i}", "space_id": SPACE_A} for i in range(11)]}))

    check("an MCP service with chosen tools parses",
          not rejected({"mcp_services": [{"service": "system.ai.slack", "tools": ["search"], "approve": []}]}))
    check("an MCP service may leave its tools and approvals at their defaults",
          ContextSettingsUpdate(mcp_services=[{"service": "system.ai.slack"}]).mcp_services[0].tools is None)
    for label, service in (("a URL", "https://evil.example.com/mcp"), ("a path", "../../api.x.y"),
                           ("a two-part name", "system.slack")):
        check(f"{label} is not an MCP service name", rejected({"mcp_services": [{"service": service}]}))
    check("a tool name the model would reject is rejected",
          rejected({"mcp_services": [{"service": "system.ai.slack", "tools": ["send message"]}]}))
    check("more than ten MCP services is rejected",
          rejected({"mcp_services": [{"service": f"system.ai.s{i}"} for i in range(11)]}))

    # --- MCP services in a turn ---------------------------------------------------

    mcp = [{"service": "system.ai.web_search", "tools": None, "approve": []}]
    agent_settings.save("general", None, {"builtin": None, "genie": None, "mcp": mcp}, "admin@x.com")
    got = agent_settings.for_context(client_with(), "general")
    check("saved MCP services travel to the agent with the turn", got["tools"]["mcp"] == mcp)
    agent_settings.reset("general")
    check("a context without MCP services sends none",
          agent_settings.for_context(client, "executive")["tools"]["mcp"] is None)

    # --- Listing MCP services as the admin ----------------------------------------

    class FakeApi:
        def __init__(self, pages=None, error=None):
            self.pages, self.error, self.calls = list(pages or []), error, []

        def do(self, method, path, query=None):
            self.calls.append((method, path, query))
            if self.error:
                raise self.error
            return self.pages.pop(0) if self.pages else {}

    api = FakeApi(pages=[
        {"mcp_services": [
            {"name": "mcp-services/system.ai.slack", "comment": "Slack.", "config": {}},
            {"name": "mcp-services/system.ai.sandbox", "config": {"internal": {}}},
            {"name": "mcp-services/system.ai.dbsql", "comment": "SQL.", "config": {"internal": {}}},
        ], "next_page_token": "p2"},
        {"mcp_services": [{"name": "mcp-services/system.ai.bad name"}, {"name": "mcp-services/system.ai.atlassian"}]},
    ])
    listed = agent_settings.list_mcp_services(SimpleNamespace(api_client=api), "system.ai")
    check("services from every page are listed, by name",
          [s["service"] for s in listed] == ["system.ai.atlassian", "system.ai.dbsql", "system.ai.slack"])
    check("the sandbox and names the agent would refuse are left out",
          not any(s["service"] in ("system.ai.sandbox", "system.ai.bad name") for s in listed))
    check("Databricks-run services are marked",
          [s["service"] for s in listed if s["databricks_managed"]] == ["system.ai.dbsql"])
    check("the schema is the list's parent, and the page token is passed on",
          api.calls[0][2] == {"parent": "schemas/system.ai"} and api.calls[1][2]["page_token"] == "p2")

    def status_of(call):
        try:
            call()
        except HTTPException as e:
            return e.status_code, e.detail
        return None, None

    status, detail = status_of(lambda: agent_settings.list_mcp_services(
        SimpleNamespace(api_client=FakeApi(error=PermissionDenied("token lacks scopes"))), "system.ai"))
    check("a refused list answers 403 and names the scope", status == 403 and "unity-catalog" in detail)
    status, _ = status_of(lambda: agent_settings.mcp_service(
        SimpleNamespace(api_client=FakeApi(error=NotFound("nope"))), "system.ai.gone"))
    check("a service the admin can't see answers 404", status == 404)

    # --- Listing Genie spaces as the admin ----------------------------------------

    pages = [
        SimpleNamespace(spaces=[SimpleNamespace(space_id=SPACE_B, title="Zeta", description="Z."),
                                SimpleNamespace(space_id="not-hex", title="Odd", description="")],
                        next_page_token="t2"),
        SimpleNamespace(spaces=[SimpleNamespace(space_id=SPACE_A, title="alpha", description=None)],
                        next_page_token=None),
    ]
    genie = SimpleNamespace(list_spaces=lambda page_size, page_token: pages.pop(0))
    spaces = agent_settings.list_genie_spaces(SimpleNamespace(genie=genie))
    check("Genie spaces from every page are listed by title, skipping odd ids",
          [(s["title"], s["space_id"]) for s in spaces] == [("alpha", SPACE_A), ("Zeta", SPACE_B)])

    # --- A service's tools come from the agent ------------------------------------

    real_get = agent_settings.requests.get
    sent = {}

    def fake_get(answer):
        def get(url, params=None, headers=None, **_kwargs):
            sent.update(url=url, params=params, headers=headers)
            return answer
        return get

    class Answer:
        def __init__(self, status, body=None):
            self.status_code, self.body = status, body

        def raise_for_status(self):
            if self.status_code >= 400:
                raise agent_settings.requests.HTTPError(f"HTTP {self.status_code}")

        def json(self):
            return self.body

    os.environ["AGENT_APP_URL"] = "http://localhost:8000"
    try:
        tools = [{"name": "web_search", "description": "Search.", "read_only": False, "offerable": True}]
        agent_settings.requests.get = fake_get(Answer(200, {"tools": tools, "problem": None}))
        got = agent_settings.mcp_service_tools(None, "system.ai.web_search", refresh=True)
        check("a service's tools are the agent's listing", got["tools"] == tools and got["problem"] is None)
        check("asked at the agent's MCP route, refreshing on request",
              sent["url"] == "http://localhost:8000/api/mcp-services/system.ai.web_search/tools"
              and sent["params"] == {"refresh": "true"})
        agent_settings.requests.get = fake_get(Answer(404))
        status, detail = status_of(lambda: agent_settings.mcp_service_tools(None, "system.ai.web_search"))
        check("an agent without the route says to redeploy it", status == 502 and "Redeploy" in detail)
    finally:
        agent_settings.requests.get = real_get
        os.environ.pop("AGENT_APP_URL", None)

    # --- Saving MCP services ------------------------------------------------------

    real_defaults, real_service = agent_settings.agent_defaults, agent_settings.mcp_service
    looked_up = []
    agent_settings.agent_defaults = lambda _token: {"contexts": [{"id": "general"}], "builtin_tools": []}
    agent_settings.mcp_service = lambda _client, name: looked_up.append(name) or {"service": name}
    caller = SimpleNamespace(email="admin@x.com")

    def save_mcp(services):
        return settings_routes.save_context(
            ContextSettingsUpdate(mcp_services=services), "general", caller, client_with(), None)

    try:
        save_mcp([{"service": "system.ai.slack", "tools": ["search"], "approve": ["search"]}])
        stored = agent_settings.read_all()["general"]["tools"]["mcp"]
        check("a saved MCP service keeps its tools and approvals",
              stored == [{"service": "system.ai.slack", "tools": ["search"], "approve": ["search"]}])
        check("each service is read as the admin before it is saved", looked_up == ["system.ai.slack"])
        status, _ = status_of(lambda: save_mcp([{"service": "system.ai.slack"}, {"service": "system.ai.slack"}]))
        check("the same service twice is rejected", status == 400)
        status, _ = status_of(lambda: save_mcp([{"service": "system.ai.sandbox"}]))
        check("the sandbox is rejected", status == 400)
        agent_settings.reset("general")
    finally:
        agent_settings.agent_defaults, agent_settings.mcp_service = real_defaults, real_service
finally:
    # The app starts the server to outlive the process, so stop this one explicitly.
    if database._local_server is not None:
        database._local_server.stop()
    shutil.rmtree(pgdata, ignore_errors=True)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
