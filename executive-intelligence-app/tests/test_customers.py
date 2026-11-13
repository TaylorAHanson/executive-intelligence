"""Tests for the Customer Intelligence widgets.

Dependency-free like test_dashboards.py: no pytest, no network, no credentials.

    server/venv/bin/python tests/test_customers.py

These pin the briefing's fixed windows, that its queries read contract views
only with the customer bound as a parameter, and that an account outside the
top 10 is a 404 rather than an empty page.
"""
import datetime
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ["DATA_CATALOG"] = "test_catalog"
os.environ["DATA_SCHEMA"] = "exec_intel"
os.environ["SQL_WAREHOUSE_ID"] = "w-123"

from fastapi import HTTPException  # noqa: E402

from fakes import FakeClient  # noqa: E402
from queries import customers as queries  # noqa: E402
from routes.dashboards import customers as routes  # noqa: E402

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


# --- Windows -------------------------------------------------------------------

print("\nWindows")

w = queries.windows(datetime.date(2026, 11, 11))
check("the period is the last 12 complete months", (w.period.start, w.period.end) == (datetime.date(2025, 11, 1), datetime.date(2026, 11, 1)))
check("with the 12 before as the comparison", w.period.prior_start == datetime.date(2024, 11, 1))
check("next quarter from November is Q1 of next year", (w.nq_start, w.nq_end) == (datetime.date(2027, 1, 1), datetime.date(2027, 4, 1)))
check("and is labelled so", w.next_quarter == "Q1 2027")
check("next quarter from February is Q2", queries.windows(datetime.date(2027, 2, 3)).next_quarter == "Q2 2027")
check("next quarter from 1 October is Q1 of next year", queries.windows(datetime.date(2026, 10, 1)).next_quarter == "Q1 2027")
check("an account is at risk on signals from the last 120 days", w.risk_since == datetime.date(2026, 7, 14))
check("a contract renews soon when it ends within 120 days", w.renewal_until == datetime.date(2027, 3, 11))
check("the renewal ladder looks a year ahead", w.ladder_end == datetime.date(2027, 11, 11))
check("every window reaches the queries as a parameter", {"renewal_until", "ladder_end", "risk_since"} <= set(w.params()))
check("today's windows match the dashboards' default period", queries.windows().period.end == datetime.date.today().replace(day=1))


# --- Queries -------------------------------------------------------------------

print("\nQueries")

hostile = "C001' OR 1=1 --"
scoped = ("signals", "deals", "profile", "revenue", "footprint", "contracts", "coverage")
unscoped = ("themes", "kpis", "accounts", "accounts_monthly", "outlook", "renewals")
for name in scoped:
    statement, params = getattr(queries, name)(w, hostile)
    check(f"{name}: the customer is not in the SQL text", hostile not in statement)
    check(f"{name}: it travels as a parameter", params.get("customer") == hostile)
    check(f"{name}: reads contract views only", "`test_catalog`.`exec_intel`.`v_" in statement and "{" not in statement)
for name in unscoped:
    statement, params = getattr(queries, name)(w)
    check(f"{name}: reads contract views only", "`test_catalog`.`exec_intel`.`v_" in statement and "{" not in statement)
    check(f"{name}: every :name it uses is bound", all(f":{p}" not in statement or p in params for p in ("start", "end", "nq_start", "risk_since", "renewal_until", "ladder_end")))

# What the executive's triage columns and visuals rest on.
accounts_sql, _ = queries.accounts(w)
check("accounts: carries why an account is flagged and when it renews", all(c in accounts_sql for c in ("AS reason", "AS next_renewal", "AS days_to_renewal", "AS nq_gap_usd")))
check("accounts: sums over the ten are computed in SQL", "OVER () AS at_risk_revenue_usd" in accounts_sql and "OVER () AS portfolio_revenue_usd" in accounts_sql)
check("accounts: still limited to the top 10", "tier = 'Top 10'" in accounts_sql)

ladder_sql, ladder_params = queries.renewals(w)
check("renewals: only top-10 contracts, only live ones, only the next year", "tier = 'Top 10'" in ladder_sql and "end_date >= current_date()" in ladder_sql and "< :ladder_end" in ladder_sql)
check("renewals: reads v_contracts", "`v_contracts`" in ladder_sql)

cover_sql, cover_params = queries.coverage(w, "")
check("coverage: counts only open deals closing next quarter", "'Lead', 'Qualified', 'Proposal', 'Commit'" in cover_sql and ":nq_start" in cover_sql)
check("coverage: all ten when no customer is given", cover_params["customer"] == "")
check("coverage: labels the quarter", cover_params["nq_label"] == "Q1 2027")

profile_sql, _ = queries.profile(w, "C003")
check("profile: compares plan attainment with the year before", "AS plan_attainment_prior" in profile_sql)
check("profile: states the gap to plan in SQL", "AS nq_gap_usd" in profile_sql)

theme_sql, _ = queries.themes(w)
check("themes: risks are listed before opportunities", "WHEN 'risk' THEN 0 ELSE 1" in theme_sql)

statement, params = queries.briefing(w, hostile)
check("briefing: the scope is a parameter", hostile not in statement and params == {"scope": hostile})
check("briefing: chapters read in story order", statement.index("'headline'") < statement.index("'know'") < statement.index("'act'"))
check("briefing: reads v_insights", "`v_insights`" in statement)


# --- Routes --------------------------------------------------------------------

print("\nRoutes")

empty = FakeClient(columns=[("customer_id", "STRING")], rows=[])
try:
    routes.profile(customer="C999", client=empty)
    status = None
except HTTPException as e:
    status = e.status_code
check("an account outside the top 10 is a 404", status == 404)

found = FakeClient(columns=[("customer_id", "STRING")], rows=[["C003"]], total_row_count=1)
check("a top-10 account returns its row", routes.profile(customer="C003", client=found).rows == [{"customer_id": "C003"}])
check("the customer reached the warehouse as a parameter", any(
    p.name == "customer" and p.value == "C003" for p in found.statement_execution.captured["parameters"]
))


print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
