"""Settings: each app context's agent prompt and tools. Admins only.

Every route checks the caller is in the admin group (`ADMIN_GROUP`), and every
write runs as that caller, so Unity Catalog's MODIFY grant on the settings
table is the real gate. See `services/agent_settings.py`.

The field limits below match what the agent accepts (`agent/contexts.py`);
anything the agent would drop is rejected here instead, so an admin sees why.
"""
from typing import Optional

from databricks.sdk import WorkspaceClient
from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from middleware.auth import CallerIdentity, get_caller, get_user_token, get_workspace_client
from services import agent_settings

router = APIRouter()

_CONTEXT_ID = Path(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
_SPACE_ID = r"^[0-9a-f]{32}$"


class GenieSpace(BaseModel):
    #: Tools are <name>_ask, <name>_poll and <name>_query_result.
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,23}$")
    space_id: str = Field(pattern=_SPACE_ID)
    description: str = Field(default="", max_length=500)


class ContextSettingsUpdate(BaseModel):
    #: None keeps the agent's default prompt section.
    prompt: Optional[str] = Field(default=None, max_length=8000)
    #: None keeps the context's default local tools.
    builtin_tools: Optional[list[str]] = Field(default=None, max_length=50)
    genie_spaces: list[GenieSpace] = Field(default_factory=list, max_length=10)


def _admin_client(
    caller: CallerIdentity = Depends(get_caller),
    client: WorkspaceClient = Depends(get_workspace_client),
) -> WorkspaceClient:
    agent_settings.require_admin(client, caller.email)
    return client


@router.get("/agent", summary="Every context's agent settings, with the agent's defaults")
def list_contexts(
    client: WorkspaceClient = Depends(_admin_client),
    user_token: Optional[str] = Depends(get_user_token),
) -> dict:
    defaults = agent_settings.agent_defaults(user_token)
    saved = agent_settings.read_all(client)
    contexts = []
    for context in defaults.get("contexts", []):
        row = saved.get(context["id"]) or {}
        tools = row.get("tools") or {}
        contexts.append({
            "id": context["id"],
            "label": context["label"],
            "default_prompt": context["prompt"],
            "default_builtin_tools": context["builtin_tools"],
            "prompt": row.get("prompt"),
            "builtin_tools": tools.get("builtin"),
            "genie_spaces": tools.get("genie") or [],
            "updated_by": row.get("updated_by"),
            "updated_at": row.get("updated_at"),
        })
    return {
        "base_prompt": defaults.get("base_prompt", ""),
        "builtin_tools": defaults.get("builtin_tools", []),
        "contexts": contexts,
    }


@router.put("/agent/{context_id}", summary="Save one context's agent settings")
def save_context(
    update: ContextSettingsUpdate,
    context_id: str = _CONTEXT_ID,
    caller: CallerIdentity = Depends(get_caller),
    client: WorkspaceClient = Depends(_admin_client),
    user_token: Optional[str] = Depends(get_user_token),
) -> dict:
    defaults = agent_settings.agent_defaults(user_token)
    if context_id not in {c["id"] for c in defaults.get("contexts", [])}:
        raise HTTPException(status_code=404, detail=f"The agent has no context {context_id!r}.")
    known = {t["name"] for t in defaults.get("builtin_tools", [])}
    if update.builtin_tools is not None and (unknown := set(update.builtin_tools) - known):
        raise HTTPException(status_code=400, detail=f"Unknown built-in tools: {', '.join(sorted(unknown))}.")
    names = [s.name for s in update.genie_spaces]
    if len(set(names)) != len(names):
        raise HTTPException(status_code=400, detail="Each Genie space needs a different tool name.")

    # The title comes from Genie, read as this admin, which also proves the id is
    # real and that the admin can open the space.
    spaces = [
        {**space.model_dump(), "title": agent_settings.genie_space(client, space.space_id)["title"]}
        for space in update.genie_spaces
    ]
    prompt = (update.prompt or "").strip() or None
    agent_settings.save(
        client,
        context_id,
        prompt,
        {"builtin": update.builtin_tools, "genie": spaces},
        caller.email,
    )
    return {"status": "saved"}


@router.delete("/agent/{context_id}", summary="Return one context to the agent's defaults")
def reset_context(context_id: str = _CONTEXT_ID, client: WorkspaceClient = Depends(_admin_client)) -> dict:
    agent_settings.reset(client, context_id)
    return {"status": "reset"}


@router.get("/genie-spaces/{space_id}", summary="Look up a Genie space before adding it")
def genie_space(
    space_id: str = Path(pattern=_SPACE_ID),
    client: WorkspaceClient = Depends(_admin_client),
) -> dict:
    return agent_settings.genie_space(client, space_id)
