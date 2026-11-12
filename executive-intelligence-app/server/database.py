"""Lakebase (Postgres) connectivity.

This is the part of a Databricks App that is genuinely fiddly, so the reasoning
is written down rather than left to be rediscovered.

**The password is a token that expires.** Lakebase does not have a static
password. The app mints a short-lived OAuth credential (valid roughly an hour)
and uses it as the Postgres password. So:

  * Resolving credentials costs control-plane round trips, which is far too slow
    to do per request — hence `_CRED_TTL_SECONDS` caching.
  * A cached credential can stop working before the TTL is up (revoked, instance
    replaced). Every failure re-resolves once rather than surfacing an error.
  * Postgres checks the password only at connect time, so an expired token does
    NOT kill a live connection. That is why `db_pool` recycles by age instead of
    watching for auth errors on existing sessions.

**The database is an Autoscaling project that scales to zero** (the bundle's
`postgres_projects.app_db`). Its credential API is addressed by endpoint
(`LAKEBASE_ENDPOINT`) and reached over REST. After five idle minutes the
compute suspends, so the first connection after a quiet spell waits a few
seconds while it wakes.

**Minting is the app's own operation, so it uses the service principal.** This
is a deliberate, documented exception to the OBO rule in `../AGENTS.md`: the app
is authenticating *itself* to its own database, which holds app state such as
Settings, never business data. Rows that belong to a user still carry their
identity, and every Unity Catalog read continues to run under the user's token.

**Locally there is no Lakebase.** `dev.sh` sets LOCAL_POSTGRES_DIR and this
module starts a bundled Postgres in that directory (pixeltable-pgserver, a dev
dependency), so `./dev.sh` needs no Docker and no workspace database.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable, Optional, TypeVar

import psycopg2
from databricks.sdk import WorkspaceClient

import db_pool
from config import settings

logger = logging.getLogger(__name__)

#: How long resolved connection parameters (including the minted token) are
#: reused. Conservative next to the token's ~1h life, so a cached credential is
#: never close to expiry when handed to a new connection.
_CRED_TTL_SECONDS = int(os.environ.get("LAKEBASE_CRED_TTL_SECONDS", "600"))

_cred_cache: dict[str, Any] = {}
_cred_lock = threading.Lock()

#: Serializes schema creation across uvicorn workers. Any int64 works; it only
#: has to be the same in every worker of this app.
_INIT_LOCK_KEY = 4472025001


class LakebaseUnavailable(RuntimeError):
    """No database is attached, or credentials could not be resolved."""


# --- Credential resolution --------------------------------------------------


def _workspace_client() -> WorkspaceClient:
    """A service principal client for minting database credentials.

    Auth is pinned explicitly rather than left to the SDK's default detection,
    which reads process-global environment variables at call time — a concurrent
    request mutating those can make a bare `WorkspaceClient()` fail with
    "default auth: cannot configure default credentials". Falls back to default
    auth when the SP variables are absent, which is the local-dev case.
    """
    host = os.environ.get("DATABRICKS_HOST")
    client_id = os.environ.get("DATABRICKS_CLIENT_ID")
    client_secret = os.environ.get("DATABRICKS_CLIENT_SECRET")
    if host and client_id and client_secret:
        return WorkspaceClient(
            host=host,
            client_id=client_id,
            client_secret=client_secret,
            auth_type="oauth-m2m",
        )
    return WorkspaceClient()


def _mint_token(endpoint: str) -> str:
    """Get a short-lived Postgres password for the Lakebase `endpoint`."""
    try:
        response = _workspace_client().api_client.do(
            "POST", "/api/2.0/postgres/credentials", body={"endpoint": endpoint}
        )
    except Exception as e:  # noqa: BLE001
        raise LakebaseUnavailable(f"Could not mint a credential for {endpoint!r}: {e}") from e
    token = response.get("token")
    if not token:
        raise LakebaseUnavailable(f"The credential response for {endpoint!r} contained no token.")
    logger.info("Minted a Lakebase credential.")
    return token


_local_server: Any = None
_local_lock = threading.Lock()


def _local_postgres_dsn(data_dir: str) -> str:
    """Start (or reuse) the bundled local Postgres and return its connection URI.

    The server outlives this process (`cleanup_mode=None`), so uvicorn's reloads
    reconnect to it instead of starting another.
    """
    global _local_server
    with _local_lock:
        if _local_server is None:
            try:
                import pixeltable_pgserver as pgserver  # dev dependency (requirements-dev.txt)
            except ImportError as e:
                raise LakebaseUnavailable(
                    "LOCAL_POSTGRES_DIR is set but pixeltable-pgserver is not installed. "
                    "Run ./dev.sh, which installs requirements-dev.txt."
                ) from e
            os.makedirs(data_dir, exist_ok=True)
            _local_server = pgserver.get_server(data_dir, cleanup_mode=None)
        return _local_server.get_uri()


def _resolve_connection_kwargs() -> dict[str, Any]:
    """Build psycopg2 connection parameters, minting a token if needed."""
    local_dir = settings.get_local_postgres_dir()
    if local_dir:
        return {"dsn": _local_postgres_dsn(local_dir)}
    config = settings.get_lakebase_config()
    if not config["host"]:
        raise LakebaseUnavailable(
            "No database attached. Add a `postgres` resource to the app in databricks.yml, "
            "or set PGHOST locally to point at your own Postgres."
        )

    password = config["password"]
    user = config["user"]

    if not password:
        endpoint = settings.get_lakebase_endpoint()
        if not endpoint:
            raise LakebaseUnavailable(
                "LAKEBASE_ENDPOINT is not set, so no credential can be minted. "
                "The bundle sets it from the attached project."
            )
        password = _mint_token(endpoint)
        # The Postgres role is the identity that minted the token — the app's
        # service principal in a deployment, you in local dev. PGUSER is
        # normally injected and correct, so this only fills a gap.
        if not user:
            try:
                user = _workspace_client().current_user.me().user_name or ""
            except Exception as e:  # noqa: BLE001
                logger.warning("Could not resolve the Postgres user: %s", e)

    return {
        "host": config["host"],
        "port": config["port"],
        "dbname": config["database"],
        "user": user,
        "password": password,
        "sslmode": config["sslmode"],
    }


def _cached_kwargs() -> Optional[dict[str, Any]]:
    with _cred_lock:
        entry = _cred_cache.get("current")
        if not entry:
            return None
        if time.monotonic() >= entry["expires_at"]:
            _cred_cache.pop("current", None)
            return None
        return dict(entry["kwargs"])


def _store_kwargs(kwargs: dict[str, Any]) -> None:
    with _cred_lock:
        _cred_cache["current"] = {
            "kwargs": dict(kwargs),
            "expires_at": time.monotonic() + _CRED_TTL_SECONDS,
        }


def invalidate_credentials() -> None:
    """Drop cached parameters so the next connection re-resolves them.

    Also retires pooled connections, since they were opened with the credentials
    being dropped — a pool that kept serving them would keep serving the failure.
    """
    with _cred_lock:
        _cred_cache.pop("current", None)
    db_pool.invalidate()


# --- Connecting -------------------------------------------------------------

#: `CREATE SCHEMA IF NOT EXISTS` only needs to succeed once. Running it per
#: connection costs the DDL plus a commit — around 400ms from outside the
#: workspace — to assert something only the first connection can change.
_schema_ready = False
_schema_lock = threading.Lock()


def _connect(kwargs: dict[str, Any]) -> Any:
    """Open one connection with the schema pinned."""
    schema = settings.get_db_schema()
    connect_kwargs = dict(kwargs)

    # A libpq `options` string is whitespace-separated, so only a plain
    # identifier can ride along in it. Sending search_path here means the session
    # starts correct with no extra round trip.
    inline = schema.replace("_", "").isalnum()
    if inline:
        connect_kwargs["options"] = f"-c search_path={schema}"

    conn = psycopg2.connect(connect_kwargs.pop("dsn", None), **connect_kwargs)

    global _schema_ready
    with _schema_lock:
        needs_schema = not _schema_ready
    if needs_schema:
        try:
            with conn.cursor() as cur:
                cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            conn.commit()
            with _schema_lock:
                _schema_ready = True
        except Exception as e:  # noqa: BLE001
            conn.rollback()
            logger.warning("Could not ensure schema '%s': %s", schema, e)

    if not inline:
        try:
            with conn.cursor() as cur:
                cur.execute(f'SET search_path TO "{schema}"')
            conn.commit()
        except Exception as e:  # noqa: BLE001
            conn.rollback()
            logger.warning("Could not select schema '%s': %s", schema, e)

    return conn


def _open_connection() -> Any:
    """Open a connection, re-resolving credentials once if the cached ones fail."""
    cached = _cached_kwargs()
    if cached:
        try:
            return _connect(cached)
        except Exception as e:  # noqa: BLE001
            # Usually an expired or revoked credential. Re-resolve rather than
            # failing the request.
            logger.warning("Cached credentials failed, re-resolving: %s", e)
            invalidate_credentials()

    kwargs = _resolve_connection_kwargs()
    conn = _connect(kwargs)
    # Only cache parameters that actually produced a connection.
    _store_kwargs(kwargs)
    return conn


def get_connection(pooled: bool = True) -> Any:
    """Get a database connection. Call `close()` when done.

    `close()` returns the connection to the pool rather than closing it, so it
    is the cheap thing — keep calling it. The pool also reclaims connections on
    garbage collection, which covers the error path that returns early.

    Pass `pooled=False` for work whose session state must not be inherited by
    the next caller. `init_db` does, because it holds a session-level advisory
    lock that would keep blocking other workers if the connection carrying it
    went back into circulation.
    """
    if not settings.lakebase_configured():
        raise LakebaseUnavailable(
            "No database attached. See the `postgres` resource in databricks.yml."
        )
    if not pooled:
        return _open_connection()
    return db_pool.acquire(_open_connection)


T = TypeVar("T")

#: Errors that mean "this connection is gone", as opposed to "your SQL is wrong".
_CONNECTION_ERRORS = (psycopg2.OperationalError, psycopg2.InterfaceError)


def run(work: Callable[[Any], T]) -> T:
    """Run `work(cursor)` in a transaction, commit it, and return its result.

    **Prefer this over calling `get_connection` directly.** It handles the
    connection lifecycle, the commit, the rollback on failure, and — the part
    that is easy to miss — a retry when the pooled connection turns out to be
    dead.

    A pooled connection can be closed by the far end without the app being told:
    the database restarts, a failover happens, an idle reaper on the server side
    reclaims it. `db_pool` only pings connections that have been idle longer than
    `PING_AFTER_SECONDS`, because pinging on every checkout would add a round
    trip to every query. So the first request after a database restart is handed
    a corpse. Measured: without this retry that request returns a 500 while the
    database is perfectly healthy, and only the *next* one succeeds.

    The retry is safe because a connection-level failure means the transaction
    never committed — Postgres rolls back whatever was in flight when the
    session dropped. Note the deliberate asymmetry: a failure during `commit`
    itself is NOT retried, because at that point there is no way to know whether
    the transaction landed, and running it twice could double-apply a write.

        notes = run(lambda cur: (
            cur.execute("SELECT id, body FROM notes WHERE author = %s", (email,)),
            cur.fetchall(),
        )[1])
    """
    last_error: Optional[BaseException] = None

    for attempt in (1, 2):
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                result = work(cur)
        except _CONNECTION_ERRORS as e:
            _safe_rollback(conn)
            conn.close()
            last_error = e
            if attempt == 1:
                logger.warning("Pooled connection was stale; retrying once: %s", e)
                continue
            raise
        except Exception:
            _safe_rollback(conn)
            conn.close()
            raise

        try:
            conn.commit()
        finally:
            conn.close()
        return result

    raise last_error  # type: ignore[misc]


def _safe_rollback(conn: Any) -> None:
    """Roll back, tolerating a connection too broken to roll back."""
    try:
        conn.rollback()
    except Exception:  # noqa: BLE001
        pass


# --- Schema ------------------------------------------------------------------

#: One row per app context an admin has changed in Settings
#: (services/agent_settings.py). `prompt` NULL keeps the agent's default;
#: `tools` holds {"builtin": [...] | null, "genie": [...] | null}, where null
#: keeps the default (the agent's patterns, or the bundle's GENIE_BINDINGS).
AGENT_CONTEXT_SETTINGS_DDL = """
CREATE TABLE IF NOT EXISTS agent_context_settings (
    context_id TEXT PRIMARY KEY,
    prompt TEXT,
    tools JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_by TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def init_db() -> None:
    """Create this app's tables. Idempotent, and safe to run in every worker.

    Serialized with a Postgres advisory lock because concurrent workers running
    `CREATE TABLE IF NOT EXISTS` can still collide in the system catalogs and
    raise `duplicate key` or `tuple concurrently updated`.

    Callers must not let this raise during startup: an unhandled exception there
    takes down the whole app with "Child process failed to start, stopping the
    parent process". `main.py` catches it.
    """
    if not settings.lakebase_configured():
        logger.info("No database attached; skipping schema initialization.")
        return

    conn = get_connection(pooled=False)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(%s)", (_INIT_LOCK_KEY,))
            try:
                # Add new columns in their own statement, as
                # `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, rather than editing
                # a CREATE — that only runs on a database that has never seen the
                # table.
                cur.execute(AGENT_CONTEXT_SETTINGS_DDL)
                conn.commit()
            finally:
                # Released explicitly rather than left to disconnect, so a
                # failure doesn't block the next worker for the session's life.
                cur.execute("SELECT pg_advisory_unlock(%s)", (_INIT_LOCK_KEY,))
                conn.commit()
        logger.info("Database schema is ready.")
    finally:
        conn.close()
