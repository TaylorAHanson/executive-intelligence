# Executive Intelligence client app

The web app for Executive Intelligence: a **React** frontend and a **FastAPI**
backend in one Databricks App, seeded from `app-template`. The landing page
(screenshot: `../docs/client-landing.png`) leads to dashboards built from a
shared toolkit; Executive Insights is the first (`../docs/client-dashboard.png`).
Branding is configurable per deployment; see [Branding](#branding).
Dashboards query Unity Catalog as the signed-in user. The agent tray on the
right talks to the agent in `../executive-intelligence-agent`, and each
dashboard tells the agent which context (prompt section and tool set) to use.
See `../architecture.md`.

```
┌─────────────────────────────────────────────┐
│  Databricks Apps (reverse proxy)            │
│  authenticates the user, forwards identity  │
└──────────────────┬──────────────────────────┘
                   │  x-forwarded-email, x-forwarded-access-token
┌──────────────────▼──────────────────────────┐
│  FastAPI  (server/)                         │
│    /api/dashboards/*  widgets, as the user  │
│    /api/agent/*  tray → agent, user = actor │
│    /api/*        other JSON endpoints       │
│    /*            serves the built React app │
└────────┬─────────────────────────┬──────────┘
         │ user token (OBO)        │ user token (OBO; user needs CAN_USE)
┌────────▼─────────────┐  ┌────────▼──────────────────────────┐
│  SQL warehouse       │  │  Agent app                        │
│  contract views (UC) │  │  agent-bricks-exec-intel-agent    │
└──────────────────────┘  └───────────────────────────────────┘
```

The browser only ever calls `/api/...` on this app. The backend calls the agent,
so no token reaches the browser and there is no CORS to configure.

## Quick start

**Prerequisites:** Python 3.11+, Node 20+, and the
[Databricks CLI](https://docs.databricks.com/dev-tools/cli/install.html) 0.283+.

On **Windows**, run `dev.sh` from **Git Bash** (bundled with
[Git for Windows](https://git-scm.com/download/win)) rather than PowerShell or
`cmd`. Install Python from [python.org](https://www.python.org/downloads/), not
the Microsoft Store — the Store build ships a stub that can't create virtual
environments.

```bash
./dev.sh
```

Then open **http://localhost:5180**.

This starts the client only. The tray calls the agent at `AGENT_APP_URL`
(default in `.env.example`: `http://localhost:8000`), so to run the agent too,
use the repo root's `../dev.sh`, which starts the agent on :8000 and then this
script. Or point `AGENT_APP_URL` at the deployed agent's URL
(`../dev.sh --deployed-agent` does that for you); locally the backend
authenticates with your CLI login.

That's the whole setup. On the first run `dev.sh` asks which workspace to use —
listing your configured CLI profiles and flagging which ones are logged in —
opens a browser to authenticate if needed, then offers your SQL warehouses and
writes both answers into `.env`. It also builds the Python virtual environment
and installs dependencies, which takes a couple of minutes. Later runs skip all
of it and start immediately.

Nothing needs editing by hand. If you'd rather set it up yourself, `.env.example`
documents every variable, and you can pick any option's "skip" to move on.

Server output goes to `backend.log` and `frontend.log`, not your terminal:

```bash
tail -f backend.log frontend.log
```

## What's in the box

| | |
| --- | --- |
| `AGENTS.md` | **The ground rules.** Read this before writing code. |
| `dev.sh` | One command to run everything locally. Self-repairing. |
| `../databricks.yml` | Bundle definition (repo root): the app, dev and prod targets. |
| `../deploy.sh` | Deploys the agent and this app and grants this app's users access to the agent. |
| `server/middleware/auth.py` | On-behalf-of auth for data and for agent calls, with the service principal as a deliberate exception. |
| `server/routes/agent.py`, `server/services/agent.py` | The tray's backend: chat, approval resume, calls to the agent app. |
| `src/components/AgentTray.tsx` | The tray: one conversation per context, approval cards. |
| `src/components/AccountMenu.tsx` | The menu under the user's initials: who is signed in, Settings (admins only), release notes, version. |
| `src/pages/SettingsPage.tsx`, `server/routes/settings.py` | Each section's assistant instructions, built-in tools, and Genie spaces, for members of `ADMIN_GROUP`. Stored in `agent_context_settings` and sent to the agent on every turn (`server/services/agent_settings.py`). |
| `RELEASE_NOTES.md` | User-facing release notes, shown under the account menu. Its header has the conventions. |
| `src/sections.ts` | The dashboard registry: routes, nav, landing tiles, and each dashboard's agent context. |
| `src/components/dashboard/` | The dashboard toolkit: page shell, KPI, chart, table, filters, widget states. |
| `src/components/story/` | The briefing toolkit behind Customer Intelligence: chapters, so-whats, recommendations. |
| `src/providers/`, `src/hooks/` | Session and tray providers; `useDashboardQuery`, URL-backed `useFilters`. |
| `server/routes/dashboards/`, `server/queries/` | Widget endpoints and their SQL, one module per dashboard. |
| `server/services/dashboards.py` | Shared widget execution, filters, typed results, and error mapping. |
| `src/agentContexts.ts` | Context ids, which must match the agent's `agent/contexts.py`. |
| `server/services/sql.py` | Parameterized SQL execution against a warehouse. |
| `server/database.py` | Lakebase: minted credentials, transactions, schema init. |
| `server/db_pool.py` | A pool that understands expiring credentials. |
| `src/api.ts` | Typed frontend API client. |
| `tests/` | Standalone tests. No pytest, no credentials, no database. |

Three `AGENTS.md` files carry the conventions: the root one for
architecture-wide rules, `server/AGENTS.md` for the backend,
`src/AGENTS.md` for the frontend. They are written for AI coding agents and
human newcomers alike — if you point Cursor or Claude at this repo, it will read
them and follow them.

## The three rules that matter most

**Queries run as the user, not as the app.** Databricks forwards each user's
token, and `get_workspace_client` builds a client from it, so Unity Catalog
applies that person's own grants. The app's service principal exists but is
reserved for operations that are genuinely app-level — using it for user data
silently bypasses governance for everyone.

```python
client = Depends(get_workspace_client)     # the user   — the default
client = get_service_principal_client()    # the app    — justify every use
```

**Values reach SQL as parameters, never as string formatting.** An f-string
makes user input executable SQL.

```python
run_query(client, "SELECT * FROM t WHERE dept = :dept", {"dept": dept})
```

**A partial result says so.** Results arrive in chunks and `run_query` stops at
a row cap, so what you get back can be a subset of what the query matched. It
reports that, and the UI shows a banner when it happens.

```python
result = run_query(...)
result["truncated"]   # check before treating `rows` as the whole answer
```

Aggregate in SQL rather than over the rows you got back. A sum over a truncated
result is wrong in a way that looks completely normal — which makes it worse
than an outage, because nobody goes looking for it.

All three are enforced by `tests/test_sql.py` and explained, with their
reasoning, in `AGENTS.md`.

## Adding a database

Lakebase (managed Postgres) is wired up but switched off, because deploying an
instance is billable and a hello-world app shouldn't quietly start costing
money. To turn it on, copy the three marked blocks from `app-template`'s
`databricks.yml` into `../databricks.yml` — the `database_instances` resource,
the app's `postgres` resource, and the two `LAKEBASE_*` environment entries —
then redeploy.

The backend needs no changes: it detects the injected `PGHOST` and stays dormant
until it appears. `app-template`'s `server/routes/example_notes.py` is a working
read/write example, and `/api/health` reports pool statistics.

The parts that are hard to get right are already handled, and the reasoning is
written down in `server/database.py` and `server/db_pool.py`:

- The Postgres password is a **short-lived OAuth token the app mints**, cached
  and re-minted on failure.
- Connections are **pooled and recycled by age**, because an expired token
  doesn't close a live connection but does break the next one opened.
- A **dead pooled connection is retried once**, so the first request after a
  database restart succeeds instead of returning a 500. A failed *commit* is
  deliberately not retried.
- Tables go in a **dedicated schema**, not `public`, which the app's role
  doesn't own.
- There are **two different credential APIs** — Autoscaling projects over REST,
  Provisioned instances via the SDK — and the code tries both.

## Adding a dashboard

Copy Executive Insights. In short (the full steps are "Adding a dashboard" in
`src/AGENTS.md`):

1. Document any new views in `../data/contract.md` and add them to `DATA_OBJECTS`.
2. Write the widgets' SQL in `server/queries/<section>.py` and their endpoints in
   `server/routes/dashboards/<section>.py`; register the router in `server/main.py`.
3. Add a context to the agent's `agent/contexts.py` and the same id to
   `src/agentContexts.ts`.
4. Add an entry to `src/sections.ts` and a page under `src/pages/` built from
   `components/dashboard`. The route, nav link, and tray context follow.

For a briefing that tells a story instead of laying out widgets, copy Customer
Intelligence (`src/pages/customers/`, `components/story`); "Briefings" in
`src/AGENTS.md` has its rules.

## Branding

The repo ships a neutral theme. To brand a deployment, create a `branding/`
folder in this directory (it is gitignored, so a customer's name and logo stay
out of the repo):

| File | Sets |
| --- | --- |
| `branding/brand.json` | `name` (app title), `assistant` (what the tray calls itself), and `colors` (`brand`, `bright`, `dark`, `accent`). Any key can be left out. |
| `branding/logo.svg` | The header logo. Without it, the header shows an icon in the brand color. |
| `branding/favicon.svg` | The browser tab icon. Without it, `public/favicon.svg`. |

```json
{ "name": "Acme Intelligence", "assistant": "Acme AI", "colors": { "brand": "#0F766E", "accent": "#B91C1C" } }
```

Branding is read by `brand.config.ts` at build time, so rebuild (`npm run build`,
or restart `dev.sh`) after changing it. `deploy.sh` builds from your checkout,
so the deployed app carries whatever `branding/` holds on the machine that
deploys.

## Deploying

```bash
../deploy.sh -p <profile> --var data_catalog=<catalog>              # agent + this app, target dev
../deploy.sh -p <profile> --var data_catalog=<catalog> --app-only   # this app only; the agent must exist
../deploy.sh -p <profile> --var data_catalog=<catalog> -t prod
```

Preflight (`../scripts/preflight.sh`) runs first and stops the deploy if the
workspace lacks a preview, the warehouse, or the contract views. The dashboards'
data comes from `../data/`; `load.py` creates synthetic data in a dev workspace,
and the header shows a "Synthetic data" badge until the bundle variable
`synthetic_data` is set to `"false"`. What is invented, and what to change for
real data, is "What is not real" in `../data/contract.md`.

The script builds `dist/` (FastAPI serves it, and `bundle deploy` doesn't build
it — skip it and the app returns a 503 saying so), deploys the agent with the
Agent Bricks CLI, deploys this app from the root bundle with the agent's URL,
gives everyone with CAN_USE on this app CAN_USE on the agent app, and starts this
app. The agent can't be deployed from the bundle: Agent Bricks provisions its
memory, session and runtime stores, which have no bundle resource type.

The app requests the `sql`, `apps` and `genie` user scopes, so **a workspace
admin must enable user authorization for apps** before on-behalf-of works; until
then the token header never arrives and dashboard endpoints return 401. The tray
calls the agent with the same user token, and the agent's Genie tools run as
that user. The agent app passes a caller's token on only if it already carries
the scopes the agent's tools need, which is why this app asks for `genie`. For a new workspace, follow
"Moving to another workspace" in `../README.md`.

The `dev` target lets everyone in the workspace open the app. Its name is
`exec-intel-app` for everyone who deploys it, so pass `--var app_name=...` to
`bundle deploy` if two people share a workspace. `prod` deploys
`exec-intel-app-prod` and grants access only to the deployer until you add a
group.

## Testing

```bash
# On Windows, substitute server/venv/Scripts/python.exe for server/venv/bin/python
for t in tests/test_*.py; do server/venv/bin/python "$t"; done   # backend
npm run lint                                                     # frontend
npm run build                                                    # type-check
```

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| Backend won't start | Read `backend.log`. Usually a missing import or a syntax error. |
| Tray says the agent isn't configured (503) | `AGENT_APP_URL` is unset. Set it in `.env`, or deploy with `../deploy.sh`. |
| Tray says the agent rejected your credentials (502) | `backend.log` (or `databricks apps logs`) prints the token's scopes. Without `apps` or `genie`, the browser's consent predates a scope change: delete the app's site cookie and reload to consent again. With both, the user lacks CAN_USE on the agent app; rerun `../deploy.sh`, which copies this app's users to it. |
| Tray can't reach the agent locally (502) | The agent isn't running. Start both with `../dev.sh`; if the agent won't start, read `../executive-intelligence-agent/agent.log`. |
| 401 from every data endpoint when deployed | User authorization isn't enabled on the app, or the scope is missing from `user_api_scopes`. |
| `ModuleNotFoundError: No module named 'server'` | Backend imports are flat — `from routes import x`, not `from server.routes import x`. |
| "Frontend not built" (503) | Run `npm run build`. |
| Query returns no rows and no error | Check the warehouse is running and `SQL_WAREHOUSE_ID` is set. |
| Port already in use | `./dev.sh` frees 8010 and 5180 itself; rerun it. |
| `server/venv/bin/python: No such file or directory` | You're on Windows, where the venv uses `Scripts/` not `bin/`. `dev.sh` handles this; a command you typed by hand doesn't. |
| `$'\r': command not found` | The script was checked out with CRLF endings. `.gitattributes` pins LF — re-clone, or run `git config core.autocrlf false` and check out again. |
| `dev.sh` re-asks for a workspace you already set | A stale or trailing-slash `DATABRICKS_HOST` in `.env` conflicting with the profile's host. Delete the line and rerun. |
| `[plugin:vite:react-babel] Cannot find module '@babel/types'` (or any other missing module) | An earlier `npm install` didn't finish, leaving `node_modules` incomplete. `./dev.sh` now detects and repairs this; if it persists, `rm -rf node_modules && npm install`. |
| "Could not list SQL warehouses" | The message now includes the CLI's own error. If it's a permission problem, set `SQL_WAREHOUSE_ID` in `.env` by hand. |
