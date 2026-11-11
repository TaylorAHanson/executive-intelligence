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
a local MLflow server; use `--deployed-agent` to test memory. Logs are
`executive-intelligence-agent/agent.log` and `executive-intelligence-app/{backend,frontend}.log`.
`executive-intelligence-app/dev.sh` still runs the client on its own.

## Deploying

```bash
# Once per workspace: synthetic data and insight records for the dashboards (dev workspaces only).
executive-intelligence-app/server/venv/bin/python data/load.py \
  -p <profile> --catalog <catalog> --schema exec_intel --warehouse <warehouse id>

# Agent and client. Runs preflight first.
./deploy.sh -p <profile> --var data_catalog=<catalog>
```

## Moving to another workspace

Nothing in the code names a workspace, catalog, or table. Moving changes bundle variables and
workspace setup, in this order:

1. **Previews.** An admin enables **Agent Memory Sessions** (profile menu > Previews). The agent
   answers every request with `FEATURE_DISABLED` without it.
2. **User authorization for apps.** An admin enables it, so the client's `user_api_scopes`
   (`sql`, `sql.statement-execution`, `sql.warehouses`) take effect and dashboards query as the
   signed-in user.
3. **Model.** The agent's default model is `system.ai.claude-sonnet-5-5`
   (`databricks-claude-sonnet-5-5`). If the workspace lacks it, change `MODEL` in
   `executive-intelligence-agent/agent/agent.py`.
4. **Warehouse.** Pick the SQL warehouse; pass `--var warehouse_id=<id>` unless it is named
   "Serverless Starter Warehouse". Grant the users' group **CAN_USE** on it.
5. **Data.** Read "What is not real" in [`data/contract.md`](data/contract.md) first: it lists every
   invented table, rule, and sentence, and the definitions to confirm with sales and finance. Then
   create the contract views over the workspace's real tables, in one catalog and schema. Use
   `data/views/views.sql` as the template, and keep `data/views/insights.sql`, which creates the
   insight records table rather than reading a source. Do not run the synthetic step.
6. **Grants and insights.** Give the users' group `USE CATALOG`, `USE SCHEMA`, and `SELECT` on the
   views, and write Customer Intelligence's insight records:
   `data/load.py ... --steps insights,grants --grant-to <group>`. Check the records first with
   `data/insights.py ... --dry-run`; the templates were written against the synthetic data.
7. **Genie spaces.** `data/genie.py -p <profile> --catalog <catalog> --schema <schema> --warehouse <id> --space <space>`
   creates a space the agent queries, from `data/genie/<space>.json`. Create both: `executive`
   (bound as `exec_data`) and `customer` (bound as `ci_data`). Bind each id in place of the one in
   `agent.toml`: from `executive-intelligence-agent/`, run `agentbricks tools remove <name>` if the
   binding exists, then `agentbricks tools add genie-agent <space_id> --name <name> --auth app`.
8. **Trace storage.** From `executive-intelligence-agent/`, run
   `uv run python scripts/trace_storage.py -p <profile> --catalog <catalog> --warehouse <id>`
   before the first deploy, so traces go to Unity Catalog tables. MLflow links only an experiment
   with no traces; if the one named in `agent.toml` has some, choose a new name.
9. **Preflight.** `scripts/preflight.sh -p <profile> --catalog <catalog> [--warehouse <id>]` and
   fix every FAIL.
10. **Deploy.** `./deploy.sh -p <profile> -t <target> --var data_catalog=<catalog> [--var ...]`. It
    grants the client's service principal CAN_USE on the agent app.
11. **Agent grants.** The agent's service principal exists only after its first deploy. The deploy
    grants it CAN_RUN on the Genie spaces and MODIFY on the trace tables; rerun
    `data/genie.py ... --space <space> --grant-app agent-bricks-exec-intel-agent` for each space
    to give it CAN_USE on the warehouse and SELECT on the views, which Genie queries as it.
12. **Access.** For `prod`, replace the commented `CAN_USE` group in `databricks.yml` with the
    group that should open the app.
13. **Verify.** Rerun preflight without `--before-deploy`. It should now pass the user
    authorization and agent-grant checks too. Open a dashboard and confirm the queries appear
    under your own name in the warehouse's query history. Ask the tray about a dashboard figure
    and confirm the trace in the agent's experiment has its spans. Read the Customer Intelligence
    briefing end to end with someone from sales or finance before anyone else sees it.
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
