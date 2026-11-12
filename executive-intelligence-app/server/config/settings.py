"""Environment-derived configuration.

Every environment variable read in this app should be read *here*, not scattered
through route modules with inline `os.environ.get` calls. That way there is one
list of what the app can be configured with, and one place to change a default.

Deployed values are set in `databricks.yml` under the app's `env:` block. Local
values come from `.env`, which `dev.sh` sources.
"""
import functools
import logging
import os
import re


def get_app_environment() -> str:
    """Which deployment this process is: local | dev | prod.

    Set per bundle target in `databricks.yml`. The frontend reads this from
    /api/health to badge the browser tab, so it must be available before a user
    is authenticated.
    """
    return os.environ.get("APP_ENVIRONMENT", "local")


def get_sql_warehouse_id() -> str:
    """The SQL warehouse the app queries. Empty string when unconfigured."""
    return os.environ.get("SQL_WAREHOUSE_ID", "")


def get_databricks_host() -> str:
    return os.environ.get("DATABRICKS_HOST", "")


# --- Dashboard data ----------------------------------------------------------
#
# Dashboards read only the views in the data contract (../../data/contract.md),
# in one catalog and schema. In this repo's dev workspace those views sit over
# synthetic tables; in another workspace they are created over that
# workspace's real tables. Either way no query names a table directly, so
# moving workspaces changes these two variables and nothing else.

#: Every object a dashboard query may read. Adding a view means adding it to
#: the contract, to `data/views/`, and here.
DATA_OBJECTS = frozenset({
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
})

#: Unity Catalog names as this app accepts them. Stricter than UC itself
#: (which allows any character inside backticks), because these are spliced
#: into SQL text: identifiers cannot be bound as parameters.
_UC_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


def get_data_catalog() -> str:
    """Catalog holding the contract views. Empty string when unconfigured."""
    return os.environ.get("DATA_CATALOG", "")


def get_data_schema() -> str:
    """Schema holding the contract views. Empty string when unconfigured."""
    return os.environ.get("DATA_SCHEMA", "")


def data_is_synthetic() -> bool:
    """Whether the contract views sit over synthetic data. Badges every page when true.

    Unset counts as synthetic, so a deployment only drops the badge when someone
    has said, in `databricks.yml`, that the views read real tables.
    """
    return os.environ.get("SYNTHETIC_DATA", "true").lower() != "false"


def get_data_object(name: str) -> str:
    """The quoted, fully qualified name of contract view `name`.

    Raises ValueError when `name` is not in the contract, or the catalog or
    schema is unset or not a plain name. `services/dashboards.py` turns that
    into an HTTP error.
    """
    if name not in DATA_OBJECTS:
        raise ValueError(f"{name!r} is not in the data contract (settings.DATA_OBJECTS).")
    catalog, schema = get_data_catalog(), get_data_schema()
    if not catalog or not schema:
        raise ValueError("DATA_CATALOG and DATA_SCHEMA are not set. Set them in databricks.yml (or .env locally).")
    for label, part in (("DATA_CATALOG", catalog), ("DATA_SCHEMA", schema)):
        if not _UC_NAME_RE.match(part):
            raise ValueError(f"{label} must be letters, digits, underscores, and hyphens only.")
    return f"`{catalog}`.`{schema}`.`{name}`"


def get_admin_group() -> str:
    """Workspace group whose members see Settings and edit the agent (bundle variable admin_group).

    This check is the only gate on Settings: the rows live in the app's own
    Lakebase, which the app writes as its service principal.
    """
    return os.environ.get("ADMIN_GROUP", "admins")


_BINDING_CONTEXT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_BINDING_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,23}$")
_BINDING_SPACE_RE = re.compile(r"^[0-9a-f]{32}$")


def get_genie_bindings() -> dict[str, list[dict]]:
    """Each context's default Genie spaces, from GENIE_BINDINGS (bundle variable genie_bindings).

    The format is `context:tool_name:space_id`, separated by spaces (the CLI's
    `--var` splits on commas, so the bundle variable cannot use them; commas
    are accepted here too). A malformed
    entry is logged and skipped rather than failing startup, so one typo costs
    one binding. Parsed once per process; callers get copies.
    """
    return {context: [dict(b) for b in spaces] for context, spaces in _parse_genie_bindings().items()}


@functools.lru_cache(maxsize=1)
def _parse_genie_bindings() -> dict[str, list[dict]]:
    bindings: dict[str, list[dict]] = {}
    for entry in os.environ.get("GENIE_BINDINGS", "").replace(",", " ").split():
        parts = entry.split(":")
        if (
            len(parts) != 3
            or not _BINDING_CONTEXT_RE.match(parts[0])
            or not _BINDING_NAME_RE.match(parts[1])
            or not _BINDING_SPACE_RE.match(parts[2])
        ):
            logging.getLogger(__name__).warning(
                "Ignoring GENIE_BINDINGS entry %r; expected context:tool_name:space_id.", entry
            )
            continue
        context, name, space_id = parts
        if any(b["name"] == name for b in bindings.get(context, [])):
            logging.getLogger(__name__).warning("Ignoring a second %r binding for %r.", name, context)
            continue
        bindings.setdefault(context, []).append({"name": name, "space_id": space_id})
    return bindings


def is_running_in_databricks_apps() -> bool:
    """True when this process is the deployed app rather than a laptop.

    Databricks Apps injects `DATABRICKS_APP_NAME` into the container. It is the
    check that makes the local-dev auth fallback impossible to ship by accident:
    a stray `LOCAL_DEV_AUTH=true` in a bundle target still cannot downgrade a
    deployment to service principal auth. See `middleware/auth.py`.
    """
    return bool(os.environ.get("DATABRICKS_APP_NAME"))


def local_dev_auth_enabled() -> bool:
    """Whether to fall back to your own CLI login when no user token arrives.

    Never true in a deployment, regardless of how the variable is set.
    """
    if is_running_in_databricks_apps():
        return False
    return os.environ.get("LOCAL_DEV_AUTH", "").lower() == "true"


def get_local_dev_user_email() -> str:
    """Identity to display during local dev, where no IdP headers arrive."""
    return os.environ.get("LOCAL_DEV_USER_EMAIL", "local-developer@example.com")


# --- Executive Intelligence agent -------------------------------------------
#
# The agent is a separate Databricks App deployed by the Agent Bricks CLI from
# ../executive-intelligence-agent. `deploy.sh` looks up its URL after deploying
# it and passes it to the bundle, which sets AGENT_APP_URL here.


def get_agent_app_url() -> str:
    """Base URL of the agent app, without a trailing slash. Empty when unset.

    Locally this is usually `http://localhost:8000`, where `agentbricks dev`
    serves the agent with no authentication in front of it.
    """
    return os.environ.get("AGENT_APP_URL", "").rstrip("/")


def agent_app_is_local() -> bool:
    """True for an `agentbricks dev` server, which takes no bearer token."""
    url = get_agent_app_url()
    return url.startswith(("http://localhost", "http://127.0.0.1"))


def get_agent_timeout_seconds() -> float:
    """How long one agent turn may take. Tool-heavy turns take tens of seconds."""
    return float(os.environ.get("AGENT_TIMEOUT_SECONDS", "120"))


# --- Lakebase (Postgres) ----------------------------------------------------
#
# The bundle attaches the app's Lakebase project as a `postgres` resource, which
# makes Databricks Apps inject the PG* variables below. Locally, `dev.sh` sets
# LOCAL_POSTGRES_DIR instead and the app runs a bundled Postgres there.


def get_local_postgres_dir() -> str:
    """Data directory for the bundled local Postgres. Never used in a deployment."""
    if is_running_in_databricks_apps() or os.environ.get("PGHOST"):
        return ""
    return os.environ.get("LOCAL_POSTGRES_DIR", "")


def lakebase_configured() -> bool:
    """Whether the app has a database: an attached Lakebase, or the local one.

    The app still starts without one, so the dashboards keep working; Settings
    then shows the agent's defaults and refuses to save.
    """
    return bool(os.environ.get("PGHOST")) or bool(get_local_postgres_dir())


def get_lakebase_config() -> dict:
    """Connection parameters, as injected by the attached `postgres` resource.

    `PGPASSWORD` is normally absent: Lakebase authenticates with a short-lived
    OAuth token that `database.py` mints per credential refresh. It is read here
    anyway so a local Postgres (docker, say) can be used with a static password.
    """
    return {
        "host": os.environ.get("PGHOST", ""),
        "port": os.environ.get("PGPORT", "5432"),
        "user": os.environ.get("PGUSER", ""),
        "password": os.environ.get("PGPASSWORD", ""),
        "database": os.environ.get("PGDATABASE", "databricks_postgres"),
        "sslmode": os.environ.get("PGSSLMODE", "require"),
    }


def get_lakebase_endpoint() -> str:
    """The Lakebase endpoint to mint credentials against.

    `projects/<project>/branches/production/endpoints/primary`, set by the
    bundle from the attached project. Without it the app cannot ask for a token.
    """
    return os.environ.get("LAKEBASE_ENDPOINT", "")


# --- Third-party secrets ----------------------------------------------------
#
# Keys for non-Databricks services are read here like anything else. What differs
# is where the value comes from: a Databricks secret scope attached to the app as
# a `secret` resource, mapped into `env:` with `value_from:`. See databricks.yml.
#
# Return None rather than a default when a key is missing, and let the caller
# decide whether that disables a feature or fails the request — a placeholder
# default turns "nobody configured this" into a confusing 401 from the vendor.
#
# def get_openai_api_key() -> Optional[str]:
#     return os.environ.get("OPENAI_API_KEY") or None


def get_db_schema() -> str:
    """The Postgres schema this app's tables live in.

    Not `public`. On managed Lakebase the app's role may CONNECT and CREATE but
    does not own `public`, and Postgres 15+ no longer grants CREATE on `public`
    to everyone — so an unqualified CREATE TABLE fails with "permission denied
    for schema public". A dedicated schema the app's role owns avoids that, and
    keeps two apps sharing a project from colliding.
    """
    return os.environ.get("APP_DB_SCHEMA", "exec_intel")
