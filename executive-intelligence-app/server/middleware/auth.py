"""Identity and Databricks client construction.

READ THIS BEFORE ADDING AN ENDPOINT THAT TOUCHES DATA.

Databricks Apps sits behind a reverse proxy that authenticates the user and then
forwards their identity to this process as HTTP headers:

    x-forwarded-access-token        the user's OAuth token  (never log this)
    x-forwarded-email               their email
    x-forwarded-preferred-username  their username
    x-forwarded-user                their IdP user id

The token is what makes **on-behalf-of (OBO)** auth possible: a `WorkspaceClient`
built with it acts as the signed-in user, so Unity Catalog enforces that user's
own grants. That is the behaviour you almost always want, and it is the default
here (`get_workspace_client`).

The alternative is the app's own **service principal** (SP), which the platform
injects as `DATABRICKS_CLIENT_ID` / `DATABRICKS_CLIENT_SECRET`. An SP client acts
as the *app*, identically for everyone, which silently bypasses per-user
governance. `get_service_principal_client` exists for the rare operation that is
genuinely app-level, and every call site must say why in a comment.

Two rules that keep this honest:

1. **Never log, print, or return a token.** Not in debug output, not in an error
   message, not in a health payload. Log its presence or length, never its value.
2. **SP is never a silent fallback for a missing user token.** In a deployment a
   missing token is an error (401). Only on a laptop, where nothing forwards the
   header, does the app fall back to your CLI login — and
   `settings.local_dev_auth_enabled()` hard-codes that to False inside Databricks
   Apps, so the fallback cannot ship.
"""
import hashlib
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from databricks.sdk import WorkspaceClient
from fastapi import Depends, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

from config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CallerIdentity:
    """Who is making this request, as reported by the Apps proxy."""

    email: str
    username: str
    user_id: str
    #: True when a real user token was forwarded. False during local dev, where
    #: the app is acting as you via your CLI login rather than via OBO.
    is_obo: bool


class AuthMiddleware(BaseHTTPMiddleware):
    """Lift the forwarded identity headers onto `request.state`.

    Reading headers in one place means route handlers never touch them directly,
    which is what keeps a token from being accidentally logged or echoed back.
    """

    async def dispatch(self, request: Request, call_next):
        request.state.user_token = request.headers.get("x-forwarded-access-token")
        request.state.user_email = request.headers.get("x-forwarded-email")
        request.state.user_username = request.headers.get("x-forwarded-preferred-username")
        request.state.user_id = request.headers.get("x-forwarded-user")
        return await call_next(request)


# --- Dependencies -----------------------------------------------------------


def get_user_token(request: Request) -> Optional[str]:
    """The raw forwarded token, or None.

    Depend on this only when you must pass the token onward to another service.
    To call Databricks, use `get_workspace_client` instead — it handles the
    local-dev case and the error handling for you.
    """
    return getattr(request.state, "user_token", None)


def get_caller(request: Request) -> CallerIdentity:
    """Who is calling. Raises 401 when there is no identity to report.

    Use this for display, for audit log rows, and for authorization decisions.
    """
    token = getattr(request.state, "user_token", None)
    email = getattr(request.state, "user_email", None)

    if token or email:
        return CallerIdentity(
            email=email or "unknown",
            username=getattr(request.state, "user_username", None) or email or "unknown",
            user_id=getattr(request.state, "user_id", None) or "unknown",
            is_obo=bool(token),
        )

    if settings.local_dev_auth_enabled():
        email = settings.get_local_dev_user_email()
        return CallerIdentity(email=email, username=email, user_id="local-dev", is_obo=False)

    raise HTTPException(
        status_code=401,
        detail="No authenticated user. This endpoint must be called through Databricks Apps.",
    )


def get_workspace_client(
    request: Request,
    user_token: Optional[str] = Depends(get_user_token),
) -> WorkspaceClient:
    """A Databricks client acting AS THE SIGNED-IN USER. Use this by default.

    Unity Catalog applies the caller's own grants to everything this client does,
    so a user cannot read through the app what they could not read directly.
    """
    _ensure_home()

    if user_token:
        host = settings.get_databricks_host() or _discover_host()
        # `auth_type="pat"` pins token auth. Without it the SDK also sees the
        # service principal credentials that Apps injects into the environment
        # and fails with "more than one authorization method configured".
        return _cached_client(
            _token_key(user_token),
            lambda: WorkspaceClient(host=host, token=user_token, auth_type="pat"),
        )

    # No user token. On a laptop, nothing forwards one, so fall back to the
    # developer's own CLI login. This branch is unreachable in a deployment.
    if settings.local_dev_auth_enabled():
        logger.info("No forwarded user token; using local CLI credentials (local dev only).")
        return _cached_client(
            "local-dev",
            WorkspaceClient,
            # The overwhelmingly common cause here is an expired CLI login, and
            # a bare "authentication failed" sends people looking at the app
            # instead of at the one command that fixes it.
            failure_detail=(
                "Could not authenticate with your local Databricks CLI login. It has most "
                "likely expired — run `databricks auth login --host <workspace-url>`, then "
                "set DATABRICKS_HOST in .env to the same workspace."
            ),
        )

    # In a deployment, a missing token is a real failure. Falling back to the
    # service principal here would run every user's query as the app, quietly
    # bypassing Unity Catalog — so we refuse instead.
    logger.error("Request requires a user token but none was forwarded.")
    raise HTTPException(
        status_code=401,
        detail=(
            "This action runs as the signed-in user, but no user token was forwarded. "
            "Check that user authorization is enabled on the app and that the required "
            "scopes are declared in databricks.yml."
        ),
    )


def get_service_principal_client() -> WorkspaceClient:
    """A client acting as THE APP ITSELF. Justify every use in a comment.

    This bypasses per-user governance: it behaves the same no matter who is
    signed in. Legitimate uses are operations the app performs on its own behalf
    rather than for a user — writing to the app's own state store, for example.
    Reading a user's data is not one of them; use `get_workspace_client`.
    """
    _ensure_home()
    return _cached_client(
        "service-principal",
        lambda: WorkspaceClient(
            host=settings.get_databricks_host() or None,
            client_id=os.environ.get("DATABRICKS_CLIENT_ID"),
            client_secret=os.environ.get("DATABRICKS_CLIENT_SECRET"),
        ),
    )


def agent_auth_headers(user_token: Optional[str]) -> dict[str, str]:
    """Headers that authenticate THE SIGNED-IN USER to the deployed agent app.

    The agent's data tools run on behalf of whoever calls it, so the call must
    carry the user's token, not this app's: the `apps` scope in databricks.yml
    lets the forwarded token call another app, and the agent app's proxy then
    forwards the user to the agent. The user needs CAN_USE on the agent app
    (`deploy.sh` copies this app's CAN_USE grants to it).

    Never the service principal: an agent called as the app would query every
    user's data as the agent, which is the bypass rule 2 above forbids.
    """
    if user_token:
        return {"Authorization": f"Bearer {user_token}"}

    if settings.local_dev_auth_enabled():
        _ensure_home()
        client = _cached_client(
            "local-dev",
            WorkspaceClient,
            failure_detail=(
                "Could not authenticate with your local Databricks CLI login to call the "
                "agent app. Run `databricks auth login`, or point AGENT_APP_URL at a local "
                "`agentbricks dev` server."
            ),
        )
        return client.config.authenticate()

    logger.error("Agent call requires a user token but none was forwarded.")
    raise HTTPException(
        status_code=401,
        detail=(
            "The agent runs as the signed-in user, but no user token was forwarded. Check "
            "that user authorization is enabled and the `apps` scope is in databricks.yml."
        ),
    )


# --- Client construction internals ------------------------------------------
#
# Building a WorkspaceClient is not free: the constructor resolves the auth
# configuration and then instantiates the SDK's entire surface of service
# wrappers. That is order-100ms of CPU under the GIL, so without caching,
# concurrent requests queue behind each other instead of overlapping.
#
# Clients are cached by a hash of the credential, never by username — a cache
# keyed on identity rather than credential would eventually hand one user's
# client to another. The TTL bounds both staleness and how long a token stays
# resident in memory.

_CLIENT_TTL_SECONDS = float(os.environ.get("WORKSPACE_CLIENT_TTL_SECONDS", "300"))
_MAX_CACHED_CLIENTS = 200
_client_cache: dict[str, tuple[float, WorkspaceClient]] = {}
_client_cache_lock = threading.Lock()


def _token_key(token: str) -> str:
    """Cache key for a token. Hashed so the raw token is never a dict key."""
    return "obo:" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]


def _cached_client(
    key: str,
    build: Callable[[], WorkspaceClient],
    failure_detail: str = "Databricks authentication failed.",
) -> WorkspaceClient:
    now = time.monotonic()
    with _client_cache_lock:
        hit = _client_cache.get(key)
        if hit and now - hit[0] < _CLIENT_TTL_SECONDS:
            return hit[1]

    try:
        client = build()
    except Exception as e:
        # Log the underlying cause, but hand the caller `failure_detail` — the SDK's
        # own message is written for whoever configured the auth, not for a user
        # looking at a browser. Neither may ever contain a token.
        logger.error("Failed to build a Databricks client: %s", e)
        raise HTTPException(status_code=401, detail=failure_detail)

    with _client_cache_lock:
        if len(_client_cache) >= _MAX_CACHED_CLIENTS:
            for expired in [k for k, (t, _) in _client_cache.items() if now - t >= _CLIENT_TTL_SECONDS]:
                _client_cache.pop(expired, None)
            if len(_client_cache) >= _MAX_CACHED_CLIENTS:
                _client_cache.clear()
        _client_cache[key] = (now, client)
    return client


def _ensure_home() -> None:
    """The SDK reads $HOME while resolving config; app containers may not set it."""
    if "HOME" not in os.environ:
        os.environ["HOME"] = "/tmp"


def _discover_host() -> Optional[str]:
    """Fall back to the SDK's own host discovery when DATABRICKS_HOST is unset."""
    try:
        from databricks.sdk.config import Config

        return Config().host
    except Exception as e:
        logger.warning("Could not discover the Databricks host: %s", e)
        return None
