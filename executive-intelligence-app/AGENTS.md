# AGENTS.md — Executive Intelligence client app

A React SPA served by a FastAPI backend, deployed as a single Databricks App,
seeded from `app-template`: a landing page, a set of dashboards generated from
one registry (`src/sections.ts`), and the agent tray docked on the right.
Dashboards query Unity Catalog views as the signed-in user; the tray talks to
the Executive Intelligence agent, a separate Databricks App in
`../executive-intelligence-agent`, through this app's backend. See
`../architecture.md` for how the pieces fit together, and "Adding a dashboard"
in `src/AGENTS.md` to build a new one.

**This file is the contract.** It exists so that whoever works here next —
human or AI — starts from the same rules rather than rediscovering them.
Scoped detail lives in `server/AGENTS.md` and `src/AGENTS.md`; read the one
covering the code you're changing.

## Commands

| Task | Command |
| --- | --- |
| Run agent + client locally | `../dev.sh` (`--deployed-agent` to use the deployed agent) |
| Run the client locally | `./dev.sh` |
| Frontend only | `npm run dev` |
| Backend only | `cd server && venv/bin/python -m uvicorn main:app --reload --port 8010` |
| Build the frontend | `npm run build` |
| Lint | `npm run lint` |
| Backend tests | `for t in tests/test_*.py; do server/venv/bin/python "$t"; done` |
| Deploy (agent + client) | `../deploy.sh -p <profile> --var data_catalog=<catalog>` |
| Deploy client only | `../deploy.sh -p <profile> --var data_catalog=<catalog> --app-only` |
| Check a workspace | `../scripts/preflight.sh -p <profile> --catalog <catalog>` |
| Load synthetic dashboard data | `server/venv/bin/python ../data/load.py -p <profile> --catalog <c> --schema exec_intel --warehouse <id>` |

For the tray to answer locally, run the agent too: `../dev.sh` starts
`agentbricks dev` in `../executive-intelligence-agent` (port 8000), waits for it,
then runs `./dev.sh` with `AGENT_APP_URL=http://localhost:8000`, which overrides
`.env`. `../dev.sh --deployed-agent` points the tray at the deployed agent
instead, called with your CLI login.

`./dev.sh` is the happy path. On a first run it walks through workspace and
warehouse selection (see below), then creates `server/venv` if missing, installs
dependencies when an import is absent, frees the ports, and starts both servers.
Backend runs on **8010**, frontend on **5180**, and Vite proxies `/api` to the
backend.

Its dependency checks test whether the environment **works**, never whether a
directory exists. A `server/venv` with no usable interpreter and a `node_modules`
missing a transitive package both look installed to `[ -d ... ]`, so gating on
the directory means the broken state is skipped over on every subsequent run and
never repaired. The venv is validated by running its interpreter and the npm tree
by `npm ls --all`, which — unlike `--depth=0` — fails when a dependency two
levels down is missing. Keep that property if you add a dependency step.

The setup prompts only appear when `.env` is unconfigured or the CLI login has
expired, and are skipped entirely when stdin is not a terminal — otherwise
`./dev.sh` in CI would block forever on a `read`. Keep that guard if you extend
the prompts.

Those ports are deliberately unusual. `dev.sh` kills whatever is holding them,
so defaulting to 8000 or 5173 would mean stomping on another project's dev
server. If you change them, change `dev.sh` and `vite.config.ts` together.

**On Windows, use Git Bash and substitute `venv/Scripts` for `venv/bin` in the
commands above.** A virtualenv puts its executables in `bin/` on macOS and
Linux and in `Scripts/` on Windows, so any path written out by hand is wrong on
one of them. `dev.sh` searches for the interpreter instead of assuming — keep it
that way, and see the "Platform differences" block at the top of the script
before changing anything about paths, ports, or the interpreter.

**Server output goes to `backend.log` and `frontend.log`, not your terminal.**
When something doesn't work, read those files first — a backend that failed to
start looks identical to one that started fine until you check.

## Layout

```
AGENTS.md            This file — read before changing anything
README.md            Human onboarding
../databricks.yml    Bundle (at the repo root): the app resource, scopes, per-target config
../deploy.sh         Deploys the agent and this app, and grants this app access to the agent
../scripts/preflight.sh  Read-only check that a workspace has what the app needs
../data/             Dashboard data contract (contract.md), synthetic data, grants
dev.sh               Local dev launcher
requirements.txt     Backend dependencies (frontend deps in package.json)
server/              FastAPI backend — see server/AGENTS.md
  main.py            App setup, router registration, SPA catch-all
  config/settings.py Every environment variable this app reads
  middleware/auth.py Identity and Databricks client construction
  routes/            One module per API area, registered by hand in main.py
  routes/agent.py    /api/agent/chat and /api/agent/resume for the tray
  routes/dashboards/ One module per dashboard: /api/dashboards/<section>/<widget>
  queries/           One module per dashboard: the widgets' SQL, over contract views
  services/agent.py  Calls the agent app: session hashing, actor, output shaping
  services/dashboards.py  Widget execution, filters, errors, shared by every dashboard
  services/sql.py    Parameterized SQL execution (warehouses)
  database.py        Lakebase: credentials, transactions, schema init
  db_pool.py         Connection pool aware of expiring credentials
src/                 React SPA — see src/AGENTS.md
  api.ts             Typed fetch helpers against /api
  App.tsx main.tsx   Entry point; routes generated from sections.ts
  sections.ts        Dashboard registry: routes, nav, landing tiles, agent context
  agentContexts.ts   App contexts the tray sends; ids match the agent's contexts.py
  providers/         Session, agent tray, and query-client providers
  hooks/             useDashboardQuery, useFilters
  components/        Layout, AgentTray, dashboard/ (the dashboard toolkit)
  pages/             LandingPage (a tile per dashboard), one page per dashboard, NotFoundPage
public/              Logo and favicon, copied to dist/ root and served by FastAPI
tests/               Standalone Python tests (no pytest, no credentials)
dist/                Build output; FastAPI serves this in production
```

## Non-negotiables

These are the rules that turn a working app into one that is safe to give
people. Breaking any of them is a bug, not a style disagreement.

### On-behalf-of, not the service principal

**Every Databricks operation that touches data runs as the signed-in user.**
Databricks Apps forwards each user's OAuth token, and a client built from it is
governed by that user's own Unity Catalog grants. Use
`get_workspace_client` from `middleware/auth.py` and you get this for free.

The app also has a **service principal** identity of its own. An SP client
behaves identically no matter who is signed in, which means it silently
bypasses per-user governance: a user reads data through the app that they could
never read directly, and no audit trail shows who actually asked. That is the
failure mode this rule exists to prevent.

`get_service_principal_client` is there for the genuinely app-level operation —
the app writing to its own state store, say. If you use it, say why in a
comment at the call site. A reviewer should never have to guess whether SP auth
was deliberate.

The dashboards follow the rule: every `/api/dashboards/...` handler takes
`get_workspace_client`, so each user's queries run under their own grants on
the contract views. That needs the `sql` scopes in `../databricks.yml` and user
authorization enabled in the workspace.

The one exception here is `database.py` minting Lakebase credentials: the app is
authenticating *itself* to its own database, not reading a user's data. Unity
Catalog access still runs under the user's token. That exception has a
consequence of its own, which is the next rule.

The agent follows the rule too. `agent_auth_headers` sends the signed-in user's
token to the agent app, and the agent's Genie tools (built with `auth="user"`
from the Genie spaces on the Settings page) run with it, so the tray can reach
only what the user could query directly. Two things make that work, and both
are easy to undo by accident:

- The token reaches the agent only if it carries the `apps` scope *and* every
  scope the agent's user-auth tools need (`genie` today). Adding a tool with a
  new scope means adding that scope to `user_api_scopes` here.
- Each user needs CAN_USE on the agent app; `../deploy.sh` copies this app's
  CAN_USE grants to it.

The actor and session the agent sees still come from `get_caller`, never from
the request body. See `../architecture.md`, section 6.

The reason this needs stating: SP auth is *easier*. It works locally without
setup, and it never 401s. Reaching for it is the path of least resistance and
the wrong answer almost every time.

**A missing user token is an error, never a reason to fall back to SP.** The
one exception is local development, where nothing forwards the header — and
that fallback is disabled inside Databricks Apps by
`settings.is_running_in_databricks_apps()`, so it cannot ship.

### Every Lakebase query filters by the caller

Unity Catalog does not reach Postgres. The app connects to Lakebase as its own
service principal — it has to, since it is authenticating itself to its own
database — so **the database will happily return every row to anyone.** There is
no per-user governance underneath to catch a query that asks for too much.

That makes the `WHERE` clause the entire access control mechanism:

```python
# WRONG — returns every user's rows to whoever is signed in
run(lambda cur: cur.execute("SELECT id, body FROM notes"))

# RIGHT — scoped to the caller, whose identity comes from the proxy
run(lambda cur: cur.execute(
    "SELECT id, body FROM notes WHERE author = %s", (caller.email,)
))
```

Take the identity from `get_caller`, never from the request body — a
client-supplied user id is a request to impersonate. `routes/agent.py` follows
the same rule for the agent: the actor and session come from `get_caller`.

This one is unusually easy to get wrong because **it looks correct in testing.**
With one user signed in, an unfiltered query returns exactly the rows you
expected; the bug only appears once a second person has data, by which time it
is in production. Write the `WHERE` clause first.

### Values go into SQL as parameters

Never build SQL with f-strings, `.format()`, `%`, or concatenation. Use `:name`
markers and pass values through `run_query`'s `parameters` argument:

```python
# WRONG — dept is executable SQL the moment it contains a quote
run_query(client, f"SELECT * FROM t WHERE dept = '{dept}'")

# RIGHT
run_query(client, "SELECT * FROM t WHERE dept = :dept", {"dept": dept})
```

This holds even when the value looks safe — a number, an enum, something a
dropdown produced. Making it unconditional is the point: the habit is what
catches the one case where the value turns out to be user input after all, and
"this one is fine" is how every injection gets written.

Table and column *names* can't be parameterized. Prefer an allowlist of the
names your app supports; use `require_identifier` or SQL's `IDENTIFIER(:name)`
when the set is genuinely open. Never interpolate a raw string.

Lakebase queries follow the same rule with psycopg2's syntax — `%s` placeholders
and a values tuple, `(dept,)` with the trailing comma. The `%s` is a placeholder,
**not** Python's `%` operator: `cur.execute("... = %s" % dept)` is the injection
this rule exists to prevent, and it looks almost identical to the safe version.

### A partial result must say so

`run_query` returns rows in chunks and stops at `max_rows`, so what comes back
can be a subset of what the query matched. It reports that as `truncated`, with
`total_rows` alongside `returned_rows`. Pass both through to the caller and show
`truncated` in the UI.

**Aggregate in SQL, never in Python over the returned rows.** `SELECT SUM(x)`
returns one row and is always complete; summing `rows` in a handler is correct
only until the data outgrows the cap, and then it is quietly, plausibly wrong.
This failure mode is worse than an outage — an error gets fixed, while a total
computed from the first 1,000 of 50,000 rows gets pasted into a deck.

### Tokens never get logged, returned, or stored

Not in a log line, not in an exception message, not in a health payload, not in
a debug endpoint that "will be removed later". Log a token's presence or its
length, never its value. Tokens live in memory for the life of a request and in
the client cache keyed by a hash — nowhere else.

### The frontend never holds a credential

No API keys, tokens, or connection strings in `src/` — not in code, not in
`localStorage`, not in a `VITE_` variable. Everything in the frontend bundle
ships to the browser and is readable by anyone who opens devtools. If a feature
needs a secret, it needs a backend endpoint, and the browser talks only to that.

Which raises the obvious question — where does the *backend* get it? From a
Databricks secret scope, attached to the app as a `secret` resource and read as
an environment variable. `databricks.yml` has the worked example, and
`server/AGENTS.md` has the steps. Never from a literal in the source, and never
from a `.env` file that gets committed. Calling Databricks itself needs no
secret at all; the user's forwarded token and the app's service principal
already cover it.

The user's Databricks token is never sent to the browser. The proxy gives it to
the backend; that is where it stays.

### Least-privilege scopes

`user_api_scopes` in `databricks.yml` is the ceiling on what the app can do on a
user's behalf. Request only what the app uses, and delete a scope when the
feature that needed it goes away. Adding scopes speculatively — because
something might need them later — is how an app ends up able to do far more
than anyone intended.

## Configuration

`databricks.yml` is authoritative for deployed configuration. `.env` covers
local development only and is gitignored; `.env.example` documents what goes in
it.

Read environment variables in `config/settings.py` and nowhere else. One list of
what the app can be configured with beats twenty `os.environ.get` calls with
inconsistent defaults scattered across route modules.

Nothing in `.env` is needed in production — the platform injects the host, the
service principal credentials, and the per-request user token.

`package-lock.json` is gitignored on purpose, which is the opposite of the usual
advice — `.gitignore` explains why. The short version: a lockfile generated
behind a private npm mirror pins every dependency to a URL that nobody outside
that network can resolve, so `npm install` fails for everyone who clones the
template. Don't add it back here. Do commit one in an app you build from this
template, generated against the public registry.

## Deploying

Run `../deploy.sh -p <profile> --var data_catalog=<catalog>` from anywhere. It
runs `../scripts/preflight.sh`, builds `dist/` (FastAPI serves it, and `bundle
deploy` does not build it), deploys the agent with the Agent Bricks CLI, deploys
this app from the root bundle with the agent's URL as `agent_app_url` plus any
`--var`, gives this app's users CAN_USE on the agent app, and starts this app.
`--app-only` skips the agent.

The app requests the `sql`, `apps` and `genie` scopes, so a workspace admin must enable user
authorization for apps before OBO works. Without it the token header never
arrives and every dashboard endpoint returns 401 — the single most common reason
an app that worked locally fails once deployed. Preflight checks the deployed
app's effective scopes.

Moving to a different workspace is variables and setup, not code: see "Moving
to another workspace" in `../README.md`.

## Conventions

Match the surrounding style rather than importing your own.

Comments here explain **why**, especially for non-obvious platform constraints —
why a handler is sync, why a client is cached by credential hash, why the SPA
catch-all must be declared last. Comments that restate what the code plainly
does are noise; delete them. Follow that pattern.

When you change how the app behaves, update the AGENTS.md that describes it in
the same commit. A separate documentation pass never happens, and a rule nobody
can trust is worse than no rule.

Every user-facing change ships in the same commit as a `RELEASE_NOTES.md` entry
(conventions in its header) and a matching `package.json` version bump. Users
read the notes from the account menu, and a dot on their initials says there is
a release they haven't opened. `tests/test_release_notes.py` and `../deploy.sh`
fail when the top release and the version disagree.
