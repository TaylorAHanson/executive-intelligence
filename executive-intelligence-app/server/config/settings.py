"""Environment-derived configuration.

Every environment variable read in this app should be read *here*, not scattered
through route modules with inline `os.environ.get` calls. That way there is one
list of what the app can be configured with, and one place to change a default.

Deployed values are set in `databricks.yml` under the app's `env:` block. Local
values come from `.env`, which `dev.sh` sources.
"""
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


#: The agent's per-context settings, next to the contract views. Not a contract
#: view: the app owns it (data/views/agent_settings.sql).
AGENT_SETTINGS_TABLE = "agent_context_settings"


def get_agent_settings_table() -> str:
    """The quoted, fully qualified settings table. Raises ValueError like `get_data_object`."""
    catalog, schema = get_data_catalog(), get_data_schema()
    if not catalog or not schema:
        raise ValueError("DATA_CATALOG and DATA_SCHEMA are not set. Set them in databricks.yml (or .env locally).")
    for label, part in (("DATA_CATALOG", catalog), ("DATA_SCHEMA", schema)):
        if not _UC_NAME_RE.match(part):
            raise ValueError(f"{label} must be letters, digits, underscores, and hyphens only.")
    return f"`{catalog}`.`{schema}`.`{AGENT_SETTINGS_TABLE}`"


def get_admin_group() -> str:
    """Workspace group whose members see Settings and edit the agent (bundle variable admin_group).

    The app's check only hides the page. Unity Catalog enforces the same rule,
    because the settings table grants MODIFY to this group alone
    (data/admin_grants.sql) and every write runs as the signed-in user.
    """
    return os.environ.get("ADMIN_GROUP", "admins")


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
# Attaching a `postgres` resource to the app makes Databricks Apps inject the
# PG* variables below. Their presence is what tells the app a database exists —
# there is no separate "enabled" flag to forget to set.


def lakebase_configured() -> bool:
    """Whether a Lakebase instance is attached.

    The app must run without one: this template's hello-world path uses no
    database at all, and a local checkout has no PGHOST. Everything database
    related checks this first and degrades rather than failing to start.
    """
    return bool(os.environ.get("PGHOST"))


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


def get_lakebase_instance_name() -> str:
    """The database instance / project to mint credentials against.

    Set from the bundle so it always matches the instance the app is attached
    to. Without it the app cannot ask for a token, because the credential APIs
    are addressed by instance name.
    """
    return os.environ.get("LAKEBASE_INSTANCE_NAME", "")


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
    keeps two apps sharing an instance from colliding.
    """
    return os.environ.get("APP_DB_SCHEMA", "app")
