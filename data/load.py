#!/usr/bin/env python3
"""Create the dashboard data in a workspace: synthetic tables, contract views, grants.

    python data/load.py -p <profile> --catalog <catalog> --schema <schema> --warehouse <id>
    python data/load.py ... --grant-to <group>       # also grant the group read access
    python data/load.py ... --steps grants --grant-to <group>   # grants only

Steps run in order and each is idempotent (CREATE OR REPLACE, GRANT):

    synthetic   synthetic/*.sql   the synthetic_* tables (dev workspaces only)
    views       views/*.sql       the v_* contract views (see contract.md)
    insights    insights.py       Customer Intelligence insight records from templates
    grants      grants.sql        USE + SELECT on the views for --grant-to

The schema is created only if it does not exist, so --schema can name one you can already create
tables in without ever having CREATE SCHEMA. The grants step needs more: it grants USE CATALOG and
USE SCHEMA, which take ownership of (or MANAGE on) the catalog and schema; without that, leave out
--grant-to and have an owner grant them.

In a workspace with real data, skip `synthetic` and replace views/views.sql
with views over the real tables (keep views/insights.sql). Needs only
`databricks-sdk`; the client app's venv has it:

    executive-intelligence-app/server/venv/bin/python data/load.py ...
"""
import argparse
import re
import string
import sys
import time
from pathlib import Path

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound, PermissionDenied
from databricks.sdk.service.sql import StatementState

HERE = Path(__file__).resolve().parent
STEPS = ("synthetic", "views", "insights", "grants")
CONTRACT_VIEWS = (
    "v_customers",
    "v_shipments",
    "v_revenue_monthly",
    "v_design_wins",
    "v_pipeline",
    "v_revenue_outlook",
    "v_contracts",
    "v_device_footprint",
    "v_customer_signals",
    "v_insights",
)
# Spliced into SQL text, so held to plain names. Matches settings._UC_NAME_RE.
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
GROUP_RE = re.compile(r"^[A-Za-z0-9 _.@+-]+$")
TERMINAL = {StatementState.SUCCEEDED, StatementState.FAILED, StatementState.CANCELED, StatementState.CLOSED}


def statements(path: Path, values: dict) -> list[str]:
    """The file's statements with ${placeholders} filled, split on line-ending semicolons."""
    text = string.Template(path.read_text()).substitute(values)
    parts = re.split(r";\s*$", text, flags=re.MULTILINE)
    out = []
    for part in parts:
        code = "\n".join(line for line in part.splitlines() if not line.strip().startswith("--")).strip()
        if code:
            out.append(code)
    return out


def execute(client: WorkspaceClient, warehouse: str, sql: str) -> None:
    response = client.statement_execution.execute_statement(warehouse_id=warehouse, statement=sql, wait_timeout="50s")
    while response.status.state not in TERMINAL:
        time.sleep(3)
        response = client.statement_execution.get_statement(response.statement_id)
    if response.status.state != StatementState.SUCCEEDED:
        message = response.status.error.message if response.status.error else response.status.state
        raise RuntimeError(f"{message}\n--- statement ---\n{sql}")


def ensure_schema(client: WorkspaceClient, warehouse: str, catalog: str, schema: str) -> None:
    """Create the schema only if it is missing.

    A schema that already exists is left alone, so this needs no CREATE SCHEMA privilege: where that
    is never granted, point --schema at one you can create tables in (CREATE TABLE also covers the
    views). A schema that is missing is created if you are allowed to, and stops with that said if not.
    """
    try:
        client.schemas.get(f"{catalog}.{schema}")
        return
    except (NotFound, PermissionDenied):
        pass  # missing, or not visible to you; creating it settles which
    try:
        execute(client, warehouse, f"CREATE SCHEMA IF NOT EXISTS `{catalog}`.`{schema}`")
    except RuntimeError as e:
        raise SystemExit(
            f"{catalog}.{schema} does not exist and could not be created:\n{e}\n\n"
            "Use a schema that already exists and that you can create tables in: --schema <name> "
            "(and --var data_schema=<name> when deploying)."
        )


def scalar(client: WorkspaceClient, warehouse: str, sql: str):
    response = client.statement_execution.execute_statement(warehouse_id=warehouse, statement=sql, wait_timeout="50s")
    if response.status.state != StatementState.SUCCEEDED:
        return None
    return response.result.data_array[0][0] if response.result and response.result.data_array else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-p", "--profile", required=True, help="Databricks CLI profile")
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--warehouse", required=True, help="SQL warehouse id")
    parser.add_argument("--grant-to", help="Group to grant read access (runs the grants step)")
    parser.add_argument("--steps", default=None, help=f"Comma-separated subset of {','.join(STEPS)}")
    args = parser.parse_args()

    for label, value in (("--catalog", args.catalog), ("--schema", args.schema)):
        if not NAME_RE.match(value):
            parser.error(f"{label} must be letters, digits, underscores, and hyphens only.")
    if args.grant_to and not GROUP_RE.match(args.grant_to):
        parser.error("--grant-to has characters a group name cannot contain.")

    steps = args.steps.split(",") if args.steps else (
        ["synthetic", "views", "insights"] + (["grants"] if args.grant_to else [])
    )
    unknown = set(steps) - set(STEPS)
    if unknown:
        parser.error(f"Unknown step(s): {', '.join(sorted(unknown))}")
    if "grants" in steps and not args.grant_to:
        parser.error("The grants step needs --grant-to <group>.")

    client = WorkspaceClient(profile=args.profile)
    values = {"catalog": args.catalog, "schema": args.schema, "group": args.grant_to or ""}
    files = {
        "synthetic": sorted((HERE / "synthetic").glob("*.sql")),
        "views": sorted((HERE / "views").glob("*.sql")),
        "grants": [HERE / "grants.sql"],
    }

    print(f"Target: {args.catalog}.{args.schema} on warehouse {args.warehouse} ({client.config.host})")
    ensure_schema(client, args.warehouse, args.catalog, args.schema)

    for step in STEPS:
        if step not in steps:
            continue
        if step == "insights":
            import insights

            print("  insights  insights.py: insight records from templates")
            count = insights.generate(client, args.warehouse, args.catalog, args.schema)
            print(f"            wrote {count} records")
            continue
        for path in files[step]:
            for sql in statements(path, values):
                first = sql.splitlines()[0][:90]
                print(f"  {step:<9} {path.name}: {first}")
                start = time.monotonic()
                try:
                    execute(client, args.warehouse, sql)
                except RuntimeError as e:
                    print(f"\nFailed: {e}", file=sys.stderr)
                    return 1
                print(f"            done in {time.monotonic() - start:.1f}s")

    if "views" in steps:
        print("\nContract views:")
        for view in CONTRACT_VIEWS:
            count = scalar(client, args.warehouse, f"SELECT COUNT(*) FROM `{args.catalog}`.`{args.schema}`.{view}")
            print(f"  {view:<20} {count if count is not None else 'unreadable'} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
