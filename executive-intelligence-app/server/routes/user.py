"""Who is signed in.

The frontend has no way to know the user's identity on its own — the Apps proxy
authenticates the request and tells the *backend*, not the browser. So the SPA
asks this endpoint rather than trying to decode anything client-side.
"""
from fastapi import APIRouter, Depends

from config import settings
from middleware.auth import CallerIdentity, get_caller

router = APIRouter()


@router.get("/me", summary="The signed-in user")
def me(caller: CallerIdentity = Depends(get_caller)) -> dict:
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
    }
