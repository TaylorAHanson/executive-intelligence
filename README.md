# Executive Intelligence

A client app of dashboards with an agent tray, and the one agent behind the tray. See
[architecture.md](architecture.md) for how the pieces fit and what is built versus proposed.

| Path | What it is |
|---|---|
| [`executive-intelligence-app/`](executive-intelligence-app/) | Client app (FastAPI + React): landing page, dashboards, agent tray. |
| [`executive-intelligence-agent/`](executive-intelligence-agent/) | The agent (Agent Bricks, LangGraph). |
| [`data/`](data/) | The dashboard data contract (and what in it is not real), synthetic data, insight records, grants, and the agent's Genie spaces. |
| [`databricks.yml`](databricks.yml) | Bundle for the client app. |
| [`dev.sh`](dev.sh) | Runs the agent and the client locally. |
| [`deploy.sh`](deploy.sh) | Deploys the agent and the client and connects them. |
| [`scripts/preflight.sh`](scripts/preflight.sh) | Read-only check that a workspace has what the app needs. |

## Running locally

```bash
./dev.sh                    # agent on :8000, client on :5180 (open this), tray wired to the local agent
./dev.sh --deployed-agent   # client only; the tray calls the deployed agent with your CLI login
```

The client reloads on save; the agent does not, so Ctrl+C and rerun after changing it (seconds,
against minutes for a deploy). The local agent queries the same workspace (profile from
`executive-intelligence-app/.env`, or `-p`) but has no Memory or Session Store and keeps traces in
a local MLflow server; use `--deployed-agent` to test memory. The client keeps Settings in a
local Postgres under `executive-intelligence-app/.pgdata` rather than Lakebase. Logs are
`executive-intelligence-agent/agent.log` and `executive-intelligence-app/{backend,frontend}.log`.
`executive-intelligence-app/dev.sh` still runs the client on its own.

## Deploying

```bash
# Once per workspace: synthetic data and insight records for the dashboards (dev workspaces only).
executive-intelligence-app/server/venv/bin/python data/load.py \
  -p <profile> --catalog <catalog> --schema exec_intel --warehouse <warehouse id>

# Agent and client. Runs preflight first. data/genie.py prints the genie_bindings entries.
./deploy.sh -p <profile> --var data_catalog=<catalog> --var "genie_bindings=<entries>"
```

## Moving to another workspace

Nothing in the code names a workspace, catalog, or table. Moving changes bundle variables and
workspace setup, in this order:

1. **Previews.** An admin enables **Agent Memory Sessions** (profile menu > Previews). Without it
   the agent still answers, but remembers nothing across conversations and keeps each conversation's
   state in the process, which a restart loses and instances do not share (`agent/stores.py`).
   `agentbricks deploy` creates the memory and session stores declared in `agent.toml`, and whether
   it can do that without the preview is not verified: if the deploy fails creating them, enable the
   preview, or run `agentbricks memory unbind` and `agentbricks sessions unbind` in
   `executive-intelligence-agent/` for this deploy and bind them again once it is enabled.
2. **User authorization for apps.** An admin enables it, so the client's `user_api_scopes` take
   effect. Everything that reads data runs as the signed-in user: dashboards with the `sql`
   scopes, and the agent's Genie tools with the user's token, which the client forwards with the
   `apps` and `genie` scopes.
3. **Lakebase.** The client keeps Settings in a Lakebase Autoscaling project that the bundle
   creates, so the workspace needs Lakebase, and the deployer needs to be allowed to create
   projects.
4. **Model.** The agent's default model is `system.ai.claude-sonnet-5-5`
   (`databricks-claude-sonnet-5-5`). If the workspace lacks it, change `MODEL` in
   `executive-intelligence-agent/agent/agent.py`.
5. **Warehouse.** Pick the SQL warehouse; pass `--var warehouse_id=<id>` unless it is named
   "Serverless Starter Warehouse". Grant the users' group **CAN_USE** on it.
6. **Data.** Read "What is not real" in [`data/contract.md`](data/contract.md) first: it lists every
   invented table, rule, and sentence, and the definitions to confirm with sales and finance. Then
   create the contract views over the workspace's real tables, in one catalog and schema. Use
   `data/views/views.sql` as the template, and keep `data/views/insights.sql`, which creates the
   insight records table rather than reading a source. Do not run the synthetic step.
   Where you may not create schemas, use one that exists and that you can create tables in
   (CREATE TABLE also covers the views): pass it as `--schema` to `load.py`, `genie.py` and
   `trace_storage.py`, and as `--var data_schema=<name>` to every deploy. `load.py` creates a schema
   only if it is missing.
7. **Grants and insights.** Give the users' group `USE CATALOG`, `USE SCHEMA`, and `SELECT` on the
   views, and write Customer Intelligence's insight records:
   `data/load.py ... --steps insights,grants --grant-to <group>`. Check the records first with
   `data/insights.py ... --dry-run`; the templates were written against the synthetic data.
8. **Genie spaces.** `data/genie.py -p <profile> --catalog <catalog> --schema <schema> --warehouse <id> --space <space>`
   creates a space the agent queries, from `data/genie/<space>.json`. Create both (`--space executive`
   and `--space customer`), adding `--grant-to <group>` to give the users' group CAN_RUN on the
   space; Genie answers as each user. Each run prints a `genie_bindings` entry that attaches the
   space to its section's assistant. Pass both to every deploy, separated by a space:
   `--var "genie_bindings=executive:exec_data:<id> customer-intelligence:ci_data:<id>"`. Members of
   `--var admin_group=<group>` can change a section's spaces later under the account menu >
   Settings; the app keeps their changes in its own Lakebase database, and a section nobody has
   changed uses the bindings from the deploy.
9. **Trace storage.** From `executive-intelligence-agent/`, run
   `uv run python scripts/trace_storage.py -p <profile> --catalog <catalog> --warehouse <id>`
   before the first deploy, so traces go to Unity Catalog tables. MLflow links only an experiment
   with no traces; if the one named in `agent.toml` has some, choose a new name.
10. **Preflight.** `scripts/preflight.sh -p <profile> --catalog <catalog> [--warehouse <id>]
   --genie-bindings "<genie_bindings>" --before-deploy` and fix every FAIL. `deploy.sh` runs it too.
11. **Access.** For `prod`, replace the commented `CAN_USE` group in `databricks.yml` with the
    group that should open the app.
12. **Deploy.** `./deploy.sh -p <profile> -t <target> --var data_catalog=<catalog> [--var ...]`. It
    gives everyone with CAN_USE on the client CAN_USE on the agent app too, since the tray calls
    the agent as the user. The first deploy also creates the app's Lakebase project,
    `<app_name>-v1`, which scales to zero after five idle minutes. The bundle will not destroy it;
    delete it in the workspace's Lakebase page if you remove the app.
13. **Verify.** Rerun preflight without `--before-deploy`. It should now pass the user
    authorization and agent-access checks too. Open a dashboard and ask the tray about a
    dashboard figure, then confirm both sets of queries appear under your own name in the
    warehouse's query history. If the tray says the agent rejected your credentials right after
    a scope change, delete the app's site cookie in the browser so the next visit asks for consent
    to the new scopes. Confirm the trace in the agent's experiment has its spans. Read the
    Customer Intelligence briefing end to end with someone from sales or finance before anyone
    else sees it.
14. **Synthetic badge.** Once every view reads real tables, redeploy with
    `--var synthetic_data=false` to remove the header's "Synthetic data" badge.

| Variable | Default | Set it to |
|---|---|---|
| `data_catalog` | none | Catalog with the contract views. |
| `data_schema` | `exec_intel` | Schema with the contract views. |
| `warehouse_id` | lookup of "Serverless Starter Warehouse" | The dashboards' warehouse. |
| `app_name` | `exec-intel-app` (`exec-intel-app-prod` in prod) | A name unique in the workspace. |
| `environment` | `dev` / `prod` by target | Shown in `/api/health` and the header badge. |
| `synthetic_data` | `"true"` | `"false"` only once every contract view reads real tables. Shows the "Synthetic data" badge. |
| `admin_group` | `admins` | The workspace group whose members see and change Settings. |
| `genie_bindings` | none | Each section's default Genie spaces, `context:tool_name:space_id`, space-separated (step 8). |
