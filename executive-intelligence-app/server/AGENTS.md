# AGENTS.md — Backend (FastAPI)

Read `../AGENTS.md` first for the OBO rule, the SQL parameterization rule, and
the commands. This file covers what you need to change code in `server/`.

## Imports are flat — this catches everyone once

Uvicorn runs with `server/` as its working directory, so packages resolve from
*inside* `server/`, not from the repo root:

```python
from routes import health              # correct
from middleware.auth import get_workspace_client
from services.sql import run_query
from server.routes import health       # WRONG — will not import
```

`databricks.yml` sets `PYTHONPATH=".:server"` so the deployed app resolves the
same way, and `tests/test_sql.py` puts `server/` on `sys.path` itself. If you
see `ModuleNotFoundError: No module named 'server'`, this is why.

## Adding an endpoint

1. Create or extend a module in `routes/` that defines `router = APIRouter()`.
2. **Register it in `main.py`.** Import it and call `app.include_router(...)`
   with an `/api/...` prefix. There is no auto-discovery. A router you forget to
   register falls through to the SPA catch-all and returns a JSON 404, which
   looks like a routing bug in the frontend.
3. Take auth as a dependency (`Depends(get_workspace_client)`), rather than
   reading headers yourself.
4. Take input as a Pydantic model with bounds on it, so the handler can trust
   what it receives instead of re-validating.

`routes/agent.py` follows all four (its auth dependency is `get_caller`, since
it calls the agent rather than Databricks data). For a query run as the user,
see the dashboard endpoints below.

Interactive docs are at `/api/docs`.

## Adding a dashboard endpoint

Dashboards are three layers, each a file, and `routes/dashboards/executive.py`
with `queries/executive.py` is the reference (`customers.py` is the same
pattern without filters: fixed windows and a `customer` or `scope` parameter):

| File | Holds |
| --- | --- |
| `queries/<section>.py` | One function per widget returning `(statement, parameters)`. |
| `routes/dashboards/<section>.py` | One `GET` per widget: filters in, `WidgetResult` out. Registered in `main.py` at `/api/dashboards/<section>`. |
| `services/dashboards.py` | Shared: `run_widget`, `data_object`, the filter dependencies, `WidgetResult`. |

```python
@router.get("/kpis")
def kpis(
    period: Period = Depends(period_filter),        # ?from=YYYY-MM&to=YYYY-MM
    regions: str = Depends(regions_filter),         # ?regions=a,b
    client: WorkspaceClient = Depends(get_workspace_client),
) -> WidgetResult:
    return run_widget(client, *queries.kpis(period, regions))
```

The rules the reference follows:

- **Queries run as the user.** `client` is always `get_workspace_client`, so a
  user sees what their own grants allow. A 403 means a missing grant
  (`../../data/grants.sql`); never fix it with the service principal.
- **Only contract views.** Name tables with `data_object("v_...")`, which
  returns the quoted name in `DATA_CATALOG`.`DATA_SCHEMA` and refuses names not
  in `settings.DATA_OBJECTS`. That is what lets the app move workspaces by
  changing two variables. It is also the only thing spliced into SQL text.
- **Every value is a parameter.** Dates pass as `datetime.date` and are sent
  typed as `DATE`. A multi-select binds as one string and is tested with
  `(:regions = '' OR array_contains(split(:regions, ','), c.region))`.
- **Periods are half-open months.** `[:start, :end)`, compared with the
  equal-length prior period `[:prior_start, :start)`. The default is the last 12
  complete months, because a period ending in the current, partial month
  compares weeks against months.
- **Aggregate and rank in SQL.** A widget's result is a handful of rows.

`run_widget` converts values by the column's reported type (`LONG` to int,
`DECIMAL`/`DOUBLE` to float, `BOOLEAN` to bool), so ids such as `"007"` stay
strings. It maps a permission error to 403 and a missing view to 404, with a
message naming the fix, and passes `truncated` through.

## Auth (`middleware/auth.py`)

| Dependency | Identity | Use for |
| --- | --- | --- |
| `get_workspace_client` | **the signed-in user** (OBO) | default for anything touching data |
| `get_caller` | — | who is calling: display, audit rows, authorization |
| `get_user_token` | raw forwarded token | only when passing the token to another service |
| `get_service_principal_client` | the app itself | app-level operations only; justify in a comment |

Default to `get_workspace_client`. See `../AGENTS.md` → *On-behalf-of, not the
service principal* for why this matters and when SP is legitimate.

**Clients are cached**, keyed by a hash of the credential and held for
`WORKSPACE_CLIENT_TTL_SECONDS` (300). Building a `WorkspaceClient` resolves the
auth config and then instantiates the SDK's entire service surface — order-100ms
of CPU under the GIL, so without the cache concurrent requests queue behind each
other instead of overlapping.

Two consequences: never mutate a client you were handed, since its config is
shared with other requests on the same credential; and never key that cache on
anything but the credential itself. A key derived from a username would
eventually hand one user's client to another, which is the worst bug this file
could have.

## SQL (`services/sql.py`)

`run_query(client, statement, parameters)` is the only way to run SQL here. Pass
the OBO client so the query is governed by the caller's grants, and pass every
value through `parameters`. The module docstring explains the rule in full.

Two behaviours worth knowing before you change it:

- **A failed statement doesn't raise.** `execute_statement` reports a rejected
  query in `response.status`, so a typo, a missing table, or a permission denial
  comes back as an ordinary response object with no rows. `_raise_if_unsuccessful`
  turns that into an HTTP error. Remove it and the UI renders "no data" for what
  was really an error — a genuinely awful thing to debug, because nothing
  anywhere reports a failure.
- **`wait_timeout` is capped at 50s** by the API. A query slower than that needs
  a polling flow, not a bigger number.

Log the statement if you like; never log the parameter values. They are user
data, and a `WHERE` clause is a fine place for something sensitive to hide.

## Results can be partial

`run_query` returns `{columns, column_types, rows, returned_rows, total_rows,
truncated, statement_id}`. There is no `row_count`, deliberately — it read like a
total and wasn't one. Every value in `rows` is a string; `column_types` says how
to read it.

Results arrive in chunks and the helper stops at `max_rows`, so check
`truncated` before doing anything with `rows` that assumes they are all there,
and pass the flag through to the frontend rather than dropping it. Any total,
average, or count belongs in the SQL, where the warehouse computes it over the
whole result instead of over the page you happened to receive.

## Blocking work belongs in a sync handler

FastAPI runs `def` handlers in a thread pool and `async def` handlers on the
event loop. The Databricks SDK is blocking, so a handler declared `async def`
that calls it holds the event loop for the entire call — up to 50 seconds — and
every other request in that worker waits behind it. Requests that should have
overlapped run one at a time.

**Declare a handler `def` unless its body actually `await`s something.** This
reads backwards if you're used to async web frameworks, which is exactly why
it's worth stating.

## Secrets for third-party services

You never need a secret to call Databricks — the user's forwarded token and the
app's service principal cover that. This is for everything else: an OpenAI key, a
Slack webhook, a partner API.

The rule is that the value reaches the process as an environment variable and
comes from a Databricks secret scope, so it exists in neither git nor the browser:

1. Create it once, outside the bundle:
   `databricks secrets create-scope my-app` then
   `databricks secrets put-secret my-app openai-api-key`
2. Attach it to the app as a `secret` resource in `databricks.yml`, and map it
   into `env:` with `value_from:` — see the commented example there. `value_from`
   names the *resource*, not the secret's key, and using `value:` instead would
   commit the secret to git.
3. Read it in `config/settings.py` like any other variable, and locally put a
   development key in `.env`, which is gitignored.

Two things not to do. Don't pass a secret to the frontend "just to make the call
from there" — that publishes it to every visitor, and the fix is a backend
endpoint that makes the call server-side. And don't log it, including in the
exception handler wrapping the call that failed, which is where keys most often
escape.

## Configuration

Every environment variable is read in `config/settings.py`. Add new ones there
as a function with a documented default, and set the deployed value in
`databricks.yml` under the app's `env:` block.

Note that Databricks Apps rejects an `env` entry whose value renders empty. If a
variable is optional, leave its entry commented out in `databricks.yml` rather
than setting it to `""`, and let the code default handle it.

## Startup and shutdown

Both live in the `lifespan` context manager in `main.py`. Wrap anything that can
fail in a try/except: an unhandled exception during startup takes down the whole
app with "Child process failed to start, stopping the parent process", which is
a confusing way to find out a database was briefly unreachable.

## Serving the frontend

`main.py` mounts `dist/assets` and has a catch-all that serves `index.html` for
any non-`/api` path, so client-side routing works on a hard refresh.

**The catch-all must stay last.** It matches everything, so any route registered
after it is unreachable.

An unmatched `/api/...` path deliberately returns JSON rather than `index.html`
— otherwise a typo in an API path hands the caller a page of HTML, and the error
reads as "the API is returning HTML" instead of "that route doesn't exist".

This is also what makes client-side routing work, which is why **every API route
must live under `/api`**: that prefix is the only thing distinguishing an
endpoint from a page the SPA will handle. See "Adding a page" in
`../src/AGENTS.md` for the frontend half.

## Lakebase (Postgres)

App state only (the Settings overrides today); business data stays in Unity
Catalog. Deployed, it is the bundle's Lakebase Autoscaling project, which scales
to zero; locally, a bundled Postgres in `.pgdata` (`LOCAL_POSTGRES_DIR`, set by
`dev.sh`). With neither, `get_connection` raises `LakebaseUnavailable`, which
callers turn into a 503 or a fallback, never a 500. Add tables to `init_db`.

**Use `database.run(work)`, not `get_connection()` directly.** It owns the
connection, the commit, the rollback, and a retry that matters more than it
looks:

```python
def query(cur):
    cur.execute("SELECT id, body FROM notes WHERE author = %s", (email,))
    return cur.fetchall()

rows = run(query)
```

Three things about this stack that cost real debugging time:

- **The password is a minted OAuth token that expires.** `database.py` caches
  resolved credentials for 10 minutes and re-resolves on failure. Postgres only
  checks the password at connect time, so an expired token does not kill a live
  connection — which is why `db_pool` recycles by age rather than watching for
  auth errors.
- **A pooled connection can be dead without the app knowing.** The pool pings
  connections idle longer than 30s, but a database restart inside that window
  hands out a corpse. Measured before the retry existed: the first request after
  a restart returned a 500 while the database was healthy. `run` retries once,
  and deliberately does *not* retry a failed `commit`, since that may have
  landed and re-running would double-apply the write.
- **Tables do not go in `public`.** The app's role can connect and create but
  does not own `public`, and Postgres 15+ no longer grants CREATE on it, so an
  unqualified `CREATE TABLE` fails with "permission denied for schema public".
  `APP_DB_SCHEMA` (default `app`) is pinned into the connection's startup packet.

Parameterize with `%s` and a values tuple — `(author,)` with the trailing comma,
since `(author)` is just a string in parentheses. This is **not** Python string
formatting; `"... WHERE author = %s" % author` re-introduces the injection the
placeholder prevents.

Schema changes go in `init_db()`, which runs under an advisory lock because
concurrent workers running `CREATE TABLE IF NOT EXISTS` can still collide in the
system catalogs. Add columns with a separate `ALTER TABLE ... ADD COLUMN IF NOT
EXISTS` rather than editing the `CREATE TABLE`, which only runs on a database
that has never seen the table.

`/api/health` reports per-worker pool counters. `reused` far above `opened` is
the pool working; a climbing `gc_released` means a route is leaking connections.

## Tests

```bash
# macOS / Linux. On Windows (Git Bash) use server/venv/Scripts/python.exe
server/venv/bin/python tests/test_sql.py         # 41 passed
server/venv/bin/python tests/test_dashboards.py  # 40 passed
server/venv/bin/python tests/test_customers.py   # 61 passed
server/venv/bin/python tests/test_agent.py       # 15 passed
server/venv/bin/python tests/test_db_pool.py     # 23 passed
server/venv/bin/python tests/test_database.py    # 21 passed
```

No pytest, no network, no credentials, no database. They use fakes to assert
what *would* have been sent — enough to pin the behaviour that is expensive to
get wrong: values leave as bound parameters, hostile identifiers are rejected,
dashboard queries read only contract views,
pooled connections are recycled and retried, and a failed commit is never
retried.

Keep them runnable with no setup. A test suite that needs a workspace is a test
suite nobody runs before committing. When you add a testable pure helper, extend
these files in the same style.
