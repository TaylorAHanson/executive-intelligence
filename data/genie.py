#!/usr/bin/env python3
"""Create or update a Genie space the agent uses to answer questions about dashboard data.

    python data/genie.py -p <profile> --catalog <catalog> --schema <schema> --warehouse <id>
    python data/genie.py ... --space customer --grant-app agent-bricks-exec-intel-agent

Each space is defined in genie/<name>.json (default: executive): its contract views, the business
definitions the dashboards use, example SQL, and sample questions. The script finds the space by
title and updates it, or creates it, then prints its id. Bind that id to the agent once per
workspace, from executive-intelligence-agent/, under the name its context's tool pattern expects
(executive -> exec_data, customer -> ci_data):

    agentbricks tools add genie-agent <space_id> --name exec_data --auth app

--grant-app gives that app's service principal what Genie needs to answer as it: CAN_RUN on the
space, CAN_USE on the warehouse, and USE + SELECT on the contract views (grants.sql).

Needs only `databricks-sdk`; the client app's venv has it:

    executive-intelligence-app/server/venv/bin/python data/genie.py ...
"""
import argparse
import json
import string
import sys
import uuid
from pathlib import Path

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.iam import AccessControlRequest, PermissionLevel
from databricks.sdk.service.sql import WarehouseAccessControlRequest, WarehousePermissionLevel

from load import HERE, NAME_RE, execute, statements


def serialized_space(definition: dict, catalog: str, schema: str) -> str:
    """The Genie serialized_space payload (version 2) for a definition file."""
    prefix = uuid.uuid4().hex[:24]
    counter = iter(range(1, 1_000_000))

    def new_id() -> str:
        # Ids within a list must be unique and ascending.
        return f"{prefix}{next(counter):08x}"

    def fill(text: str) -> str:
        return string.Template(text).substitute(catalog=catalog, schema=schema)

    return json.dumps({
        "version": 2,
        "config": {
            "sample_questions": [{"id": new_id(), "question": [q]} for q in definition["sample_questions"]],
        },
        "data_sources": {
            "tables": [{"identifier": f"{catalog}.{schema}.{t}"} for t in sorted(definition["tables"])],
        },
        "instructions": {
            "text_instructions": [{"id": new_id(), "content": ["\n".join(definition["instructions"])]}],
            "example_question_sqls": [
                {"id": new_id(), "question": [e["question"]], "sql": [fill(e["sql"])]}
                for e in definition["examples"]
            ],
        },
    })


def find_space(client: WorkspaceClient, title: str) -> str | None:
    token = None
    while True:
        page = client.genie.list_spaces(page_size=100, page_token=token)
        for space in page.spaces or []:
            if space.title == title:
                return space.space_id
        token = page.next_page_token
        if not token:
            return None


def grant_app(client: WorkspaceClient, app_name: str, space_id: str, args) -> None:
    principal = client.apps.get(app_name).service_principal_client_id
    client.permissions.update("genie", space_id, access_control_list=[
        AccessControlRequest(service_principal_name=principal, permission_level=PermissionLevel.CAN_RUN)])
    client.warehouses.update_permissions(args.warehouse, access_control_list=[
        WarehouseAccessControlRequest(service_principal_name=principal,
                                      permission_level=WarehousePermissionLevel.CAN_USE)])
    values = {"catalog": args.catalog, "schema": args.schema, "group": principal}
    for sql in statements(HERE / "grants.sql", values):
        execute(client, args.warehouse, sql)
    print(f"Granted {app_name}'s service principal ({principal}) CAN_RUN on the space, "
          f"CAN_USE on warehouse {args.warehouse}, and SELECT on the contract views")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-p", "--profile", required=True, help="Databricks CLI profile")
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--warehouse", required=True, help="SQL warehouse id the space runs on")
    parser.add_argument("--space", default="executive", help="Definition file in genie/, without .json")
    parser.add_argument("--grant-app", help="Databricks App whose service principal will query the space")
    args = parser.parse_args()

    for label, value in (("--catalog", args.catalog), ("--schema", args.schema), ("--space", args.space)):
        if not NAME_RE.match(value):
            parser.error(f"{label} must be letters, digits, underscores, and hyphens only.")
    definition = json.loads((HERE / "genie" / f"{args.space}.json").read_text())

    client = WorkspaceClient(profile=args.profile)
    payload = serialized_space(definition, args.catalog, args.schema)
    space_id = find_space(client, definition["title"])
    if space_id:
        client.genie.update_space(space_id, serialized_space=payload, warehouse_id=args.warehouse,
                                  description=definition["description"])
        print(f"Updated Genie space {definition['title']!r}")
    else:
        space_id = client.genie.create_space(args.warehouse, payload, title=definition["title"],
                                             description=definition["description"]).space_id
        print(f"Created Genie space {definition['title']!r}")
    print(f"  space_id: {space_id}")
    print(f"  {client.config.host.rstrip('/')}/genie/rooms/{space_id}")

    if args.grant_app:
        grant_app(client, args.grant_app, space_id, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
