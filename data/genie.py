#!/usr/bin/env python3
"""Create or update a Genie space the agent uses to answer questions about dashboard data.

    python data/genie.py -p <profile> --catalog <catalog> --schema <schema> --warehouse <id>
    python data/genie.py ... --space customer --grant-to <users-group> --bind customer-intelligence:ci_data

Each space is defined in genie/<name>.json (default: executive): its contract views, the business
definitions the dashboards use, example SQL, and sample questions. The script finds the space by
title and updates it, or creates it, then prints its id.

--bind <context>:<name> attaches the space to an agent context as tools <name>_ask, <name>_poll
and <name>_query_result, by writing it into that context's row of agent_context_settings
(views/agent_settings.sql). Admins can do the same, or change it later, in the client app's
Settings page. The usual bindings are executive:exec_data and customer-intelligence:ci_data.

The agent asks Genie as the signed-in user, so each user needs CAN_RUN on the space, as well as
the view and warehouse access in grants.sql. --grant-to gives a group CAN_RUN on the space.

Needs only `databricks-sdk`; the client app's venv has it:

    executive-intelligence-app/server/venv/bin/python data/genie.py ...
"""
import argparse
import json
import re
import string
import sys
import uuid
from pathlib import Path

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.iam import AccessControlRequest, PermissionLevel
from databricks.sdk.service.sql import StatementParameterListItem, StatementState

from load import HERE, NAME_RE

# Match agent/contexts.py: context ids, and Genie tool names (<name>_ask is the longest tool name).
CONTEXT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,23}$")


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


def _sql(client: WorkspaceClient, warehouse: str, statement: str, **params: str):
    response = client.statement_execution.execute_statement(
        warehouse_id=warehouse,
        statement=statement,
        parameters=[StatementParameterListItem(name=k, value=v) for k, v in params.items()],
        wait_timeout="50s",
    )
    if response.status.state != StatementState.SUCCEEDED:
        message = response.status.error.message if response.status.error else response.status.state
        raise RuntimeError(f"Writing agent settings failed: {message}")
    return response.result.data_array if response.result else None


def bind(client: WorkspaceClient, args, space_id: str, definition: dict) -> None:
    """Add (or replace) this space in a context's agent settings, keeping everything else there."""
    context_id, name = args.bind.split(":", 1)
    table = f"`{args.catalog}`.`{args.schema}`.agent_context_settings"
    rows = _sql(client, args.warehouse, f"SELECT tools FROM {table} WHERE context_id = :context_id",
                context_id=context_id)
    tools = json.loads(rows[0][0]) if rows and rows[0][0] else {"builtin": None, "genie": []}
    space = {"name": name, "space_id": space_id, "title": definition["title"],
             "description": definition["description"][:500]}
    tools["genie"] = [g for g in tools.get("genie") or [] if g.get("name") != name] + [space]
    _sql(
        client, args.warehouse,
        f"MERGE INTO {table} t USING (SELECT :context_id AS context_id, :tools AS tools) s "
        "ON t.context_id = s.context_id "
        "WHEN MATCHED THEN UPDATE SET tools = s.tools, updated_by = current_user(), updated_at = current_timestamp() "
        "WHEN NOT MATCHED THEN INSERT (context_id, prompt, tools, updated_by, updated_at) "
        "VALUES (s.context_id, NULL, s.tools, current_user(), current_timestamp())",
        context_id=context_id, tools=json.dumps(tools),
    )
    print(f"Bound the space to context {context_id!r} as {name}_ask, {name}_poll, {name}_query_result")


def grant_to(client: WorkspaceClient, group: str, space_id: str) -> None:
    client.permissions.update("genie", space_id, access_control_list=[
        AccessControlRequest(group_name=group, permission_level=PermissionLevel.CAN_RUN)])
    print(f"Granted {group} CAN_RUN on the space")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-p", "--profile", required=True, help="Databricks CLI profile")
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--warehouse", required=True, help="SQL warehouse id the space runs on")
    parser.add_argument("--space", default="executive", help="Definition file in genie/, without .json")
    parser.add_argument("--grant-to", help="Group whose members ask the agent; gets CAN_RUN on the space")
    parser.add_argument("--bind", metavar="CONTEXT:NAME", help="Attach the space to an agent context, e.g. customer-intelligence:ci_data")
    args = parser.parse_args()
    if args.bind:
        context_id, _, name = args.bind.partition(":")
        if not (CONTEXT_RE.match(context_id) and TOOL_NAME_RE.match(name)):
            parser.error("--bind takes <context>:<name>, e.g. customer-intelligence:ci_data "
                         "(name: lowercase letters, digits, underscores; at most 24).")

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

    if args.grant_to:
        grant_to(client, args.grant_to, space_id)
    if args.bind:
        bind(client, args, space_id, definition)
    return 0


if __name__ == "__main__":
    sys.exit(main())
