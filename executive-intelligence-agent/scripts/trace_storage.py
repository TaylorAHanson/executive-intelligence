#!/usr/bin/env python3
"""Store the agent's traces in Unity Catalog tables instead of the experiment's artifact store.

    uv run python scripts/trace_storage.py -p <profile> --catalog <catalog> --warehouse <id>
    uv run python scripts/trace_storage.py ... --schema agent_traces --prefix exec_intel_agent

By default MLflow uploads each trace's spans to the experiment's artifact store through the
regional storage proxy (<region>.storage.cloud.databricks.com). Where Databricks Apps cannot reach
that host, as in some workspaces, every trace is saved without its spans. Linking the
experiment to a Unity Catalog table prefix makes MLflow write spans through the workspace API
instead; the deployed agent picks the link up from the experiment, with no code change.

MLflow links only an experiment that has no traces yet, so run this before the first deploy that
uses the experiment named in agent.toml [tracing], and again after it to add the grants. Idempotent.
Steps:

    1. CREATE SCHEMA <catalog>.<schema> if missing
    2. create the experiment if missing and link it to <catalog>.<schema>.<prefix>
       (MLflow creates the <prefix>_* tables)
    3. if the agent app exists, grant its service principal USE CATALOG, and USE SCHEMA, SELECT,
       and MODIFY on the schema (`agentbricks deploy` also binds the tables to the app with MODIFY)

Viewing the traces in the MLflow UI then needs a SQL warehouse and SELECT on the schema.
"""
import argparse
import os
import re
import sys
import tomllib
from pathlib import Path

import mlflow
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound
from databricks.sdk.service.catalog import PermissionsChange, Privilege
from mlflow.entities.trace_location import UnityCatalog
from mlflow.exceptions import RestException

AGENT_DIR = Path(__file__).resolve().parent.parent
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
APP_PREFIX = "agent-bricks-"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-p", "--profile", required=True, help="Databricks CLI profile")
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--schema", default="agent_traces")
    parser.add_argument("--prefix", default="exec_intel_agent", help="Table name prefix")
    parser.add_argument("--warehouse", required=True, help="SQL warehouse id, used to create the tables")
    args = parser.parse_args()

    for label, value in (("--catalog", args.catalog), ("--schema", args.schema), ("--prefix", args.prefix)):
        if not NAME_RE.match(value):
            parser.error(f"{label} must be letters, digits, and underscores only.")

    config = tomllib.loads((AGENT_DIR / "agent.toml").read_text())
    experiment_name = config["tracing"]["experiment_name"]
    app_name = APP_PREFIX + config["agent"]["deployment_name"]

    client = WorkspaceClient(profile=args.profile)
    try:
        client.schemas.get(f"{args.catalog}.{args.schema}")
    except NotFound:
        client.schemas.create(name=args.schema, catalog_name=args.catalog,
                              comment=f"MLflow traces for {app_name}")
        print(f"Created schema {args.catalog}.{args.schema}")

    os.environ["MLFLOW_TRACING_SQL_WAREHOUSE_ID"] = args.warehouse
    # MLflow's warehouse check builds its own WorkspaceClient(), which ignores the tracking URI's
    # profile and would otherwise use DEFAULT.
    os.environ["DATABRICKS_CONFIG_PROFILE"] = args.profile
    mlflow.set_tracking_uri(f"databricks://{args.profile}")
    location = UnityCatalog(args.catalog, args.schema, args.prefix)
    experiment = mlflow.get_experiment_by_name(experiment_name)
    try:
        if experiment is None:
            linked = mlflow.set_experiment(experiment_name=experiment_name, trace_location=location)
        else:
            linked = mlflow.set_experiment(experiment_id=experiment.experiment_id, trace_location=location)
    except RestException as e:
        if "already contains traces" not in str(e):
            raise
        print(f"Experiment {experiment_name} already has traces in its artifact store, so it can't be "
              "linked. Set a new experiment_name in agent.toml [tracing] and rerun.", file=sys.stderr)
        return 1
    print(f"Linked experiment {experiment_name} ({linked.experiment_id}) to {linked.trace_location.full_table_prefix}")

    try:
        principal = client.apps.get(app_name).service_principal_client_id
    except NotFound:
        print(f"App {app_name} doesn't exist yet. Deploy the agent, then rerun this to add the grants.")
        return 0
    client.grants.update("catalog", args.catalog, changes=[
        PermissionsChange(principal=principal, add=[Privilege.USE_CATALOG])])
    client.grants.update("schema", f"{args.catalog}.{args.schema}", changes=[
        PermissionsChange(principal=principal, add=[Privilege.USE_SCHEMA, Privilege.SELECT, Privilege.MODIFY])])
    print(f"Granted {app_name}'s service principal ({principal}) write access to {args.catalog}.{args.schema}")

    tables = sorted(t.name for t in client.tables.list(args.catalog, args.schema) if t.name.startswith(args.prefix))
    print("Tables: " + (", ".join(tables) or "none yet"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
