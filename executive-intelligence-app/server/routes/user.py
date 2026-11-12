"""Who is signed in.

The frontend has no way to know the user's identity on its own — the Apps proxy
authenticates the request and tells the *backend*, not the browser. So the SPA
asks this endpoint rather than trying to decode anything client-side.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from config import settings
from middleware.auth import CallerIdentity, get_caller, get_user_token, get_workspace_client
from services import agent_settings

router = APIRouter()


def _is_admin(request: Request, user_token: Optional[str], email: str) -> bool:
    # Built here rather than as a dependency, so a missing token costs only
    # the Settings item, not the whole identity response.
    try:
        client = get_workspace_client(request, user_token)
    except HTTPException:
        return False
    return agent_settings.is_admin(client, email)


@router.get("/me", summary="The signed-in user")
def me(
    request: Request,
    caller: CallerIdentity = Depends(get_caller),
    user_token: Optional[str] = Depends(get_user_token),
) -> dict:
    # Return identity only. The user's token is not the frontend's business:
    # anything needing it should be a backend endpoint the browser calls.
    return {
        "email": caller.email,
        "username": caller.username,
        # False during local dev, where the app acts as your CLI login rather
        # than through a forwarded user token. The UI badges this so nobody
        # mistakes a laptop session for real per-user governance.
        "on_behalf_of": caller.is_obo,
        # Separate from `on_behalf_of`: an app that requests no user scopes
        # gets no forwarded token even when deployed, so that flag alone would
        # badge every deployed session as local.
        "local_dev": not settings.is_running_in_databricks_apps(),
        # Shows Settings in the account menu. Display only: the settings routes
        # check again, and Unity Catalog grants decide what a write can do.
        "is_admin": _is_admin(request, user_token, caller.email),
    }
