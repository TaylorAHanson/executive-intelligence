"""Tests for the dashboard endpoint pattern.

Dependency-free like test_sql.py: no pytest, no network, no credentials.

    server/venv/bin/python tests/test_dashboards.py

These pin what keeps dashboards safe and portable: queries name only contract
views, filter values travel as parameters, warehouse values come back typed,
truncation survives, and a missing grant or view reads as one.
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

from config import settings  # noqa: E402
from fakes import FakeClient  # noqa: E402
from queries import executive as queries  # noqa: E402
from services.dashboards import (  # noqa: E402
    MAX_LIST_VALUES,
    Period,
    list_filter,
    period_filter,
    run_widget,
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


def status_of(call) -> int | None:
    try:
        call()
    except HTTPException as e:
        return e.status_code
    except ValueError:
        return -1
    return None


# --- Contract views only -----------------------------------------------------

print("\nContract views")

check(
    "a contract view resolves to a quoted three-part name",
    settings.get_data_object("v_customers") == "`test_catalog`.`exec_intel`.`v_customers`",
)
check("a name outside the contract is refused", status_of(lambda: settings.get_data_object("users")) == -1)

os.environ["DATA_CATALOG"] = "x`; DROP TABLE t; --"
check("a hostile catalog name is refused", status_of(lambda: settings.get_data_object("v_customers")) == -1)
os.environ["DATA_CATALOG"] = ""
check("an unset catalog is refused", status_of(lambda: settings.get_data_object("v_customers")) == -1)
check(
    "and a query against it fails with a 500 rather than running",
    status_of(lambda: queries.kpis(period_filter(None, None), "")) == 500,
)
os.environ["DATA_CATALOG"] = "test_catalog"


# --- Filters -----------------------------------------------------------------

print("\nPeriod filter")

this_month = datetime.date.today().replace(day=1)
default = period_filter(None, None)
check("defaults to 12 months", default.months == 12)
check("of complete months: it ends where this month begins", default.end == this_month)
check("with an equal-length prior period", (default.start - default.prior_start).days in range(334, 367))

p = period_filter("2025-01", "2025-03")
check("an explicit range includes both months", (p.start, p.end) == (datetime.date(2025, 1, 1), datetime.date(2025, 4, 1)))
check("its prior period is the three months before", p.prior_start == datetime.date(2024, 10, 1))
check("a range across a year end works", period_filter("2024-11", "2025-02").months == 4)
check("first after last is a 400", status_of(lambda: period_filter("2025-05", "2025-01")) == 400)
check("more than 60 months is a 400", status_of(lambda: period_filter("2015-01", "2025-01")) == 400)
check("month 13 is a 400", status_of(lambda: period_filter("2025-13", "2025-13")) == 400)

print("\nList filter")

check("empty means no filter", list_filter(None) == "" and list_filter("") == "")
check("values are trimmed and de-duplicated", list_filter(" EMEA, APAC ,EMEA,,") == "EMEA,APAC")
check("too many values is a 400", status_of(lambda: list_filter(",".join(f"r{i}" for i in range(MAX_LIST_VALUES + 1)))) == 400)


# --- Queries bind values -----------------------------------------------------

print("\nQueries")

hostile = "EMEA') OR 1=1 --"
period = Period(start=datetime.date(2025, 1, 1), end=datetime.date(2026, 1, 1), prior_start=datetime.date(2024, 1, 1))
for name in ("kpis", "monthly", "revenue_by_region", "top_customers"):
    statement, params = getattr(queries, name)(period, hostile)
    check(f"{name}: the filter value is not in the SQL text", hostile not in statement)
    check(f"{name}: it travels as a parameter", params.get("regions") == hostile)
    check(f"{name}: reads contract views only", "`test_catalog`.`exec_intel`.`v_" in statement and "{" not in statement)

client = FakeClient(columns=[("month", "DATE")])
run_widget(client, *queries.monthly(period, ""))
sent = {p.name: p for p in client.statement_execution.captured["parameters"]}
check("dates are sent typed as DATE", sent["start"].type == "DATE" and sent["start"].value == "2025-01-01")
check("strings stay untyped (STRING)", sent["regions"].type is None and sent["regions"].value == "")


# --- Results -----------------------------------------------------------------

print("\nResults")

client = FakeClient(
    columns=[("customer_id", "STRING"), ("units", "LONG"), ("revenue_usd", "DECIMAL"), ("on_time", "BOOLEAN"), ("otif", "DOUBLE")],
    rows=[["007", "12", "1500.50", "true", None]],
    total_row_count=1,
)
result = run_widget(client, "SELECT 1")
row = result.rows[0]
check("an id stays a string, leading zeros and all", row["customer_id"] == "007")
check("LONG becomes int", row["units"] == 12)
check("DECIMAL becomes float", row["revenue_usd"] == 1500.5)
check("BOOLEAN becomes bool", row["on_time"] is True)
check("NULL stays None", row["otif"] is None)

client = FakeClient(columns=[("id", "LONG")], rows=[[str(i)] for i in range(5)], total_row_count=5)
result = run_widget(client, "SELECT id FROM t", max_rows=2)
check("truncation passes through", result.truncated is True and result.returned_rows == 2 and result.total_rows == 5)

denied = FakeClient(error="[INSUFFICIENT_PERMISSIONS] User does not have SELECT on Table 'v_customers'.")
check("a missing grant is a 403", status_of(lambda: run_widget(denied, "SELECT 1")) == 403)
missing = FakeClient(error="[TABLE_OR_VIEW_NOT_FOUND] The table or view `v_customers` cannot be found.")
check("a missing view is a 404", status_of(lambda: run_widget(missing, "SELECT 1")) == 404)
broken = FakeClient(error="[PARSE_SYNTAX_ERROR] Syntax error at or near 'SELEC'.")
check("any other failed statement stays a 400", status_of(lambda: run_widget(broken, "SELEC 1")) == 400)


print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
