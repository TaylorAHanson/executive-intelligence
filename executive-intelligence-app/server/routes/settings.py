"""Settings: each app context's agent prompt and tools. Admins only.

Every route checks the caller is in the admin group (`ADMIN_GROUP`). That is
the only gate: the rows live in the app's own Lakebase, which the app writes as
its service principal. See `services/agent_settings.py`.

The field limits below match what the agent accepts (`agent/contexts.py`);
anything the agent would drop is rejected here instead, so an admin sees why.
"""
from typing import Annotated, Optional

from databricks.sdk import WorkspaceClient
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field

from middleware.auth import CallerIdentity, get_caller, get_user_token, get_workspace_client
from services import agent_settings

router = APIRouter()

_CONTEXT_ID = Path(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
_SPACE_ID = r"^[0-9a-f]{32}$"
_MCP_SERVICE = agent_settings.MCP_SERVICE_RE.pattern
_SCHEMA = r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$"
#: What the model API accepts as a tool name (`MCP_TOOL_NAME_RE` in the agent).
ToolName = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


class GenieSpace(BaseModel):
    #: Tools are <name>_ask, <name>_poll and <name>_query_result.
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,23}$")
    space_id: str = Field(pattern=_SPACE_ID)
    description: str = Field(default="", max_length=500)


class McpServiceSetting(BaseModel):
    service: str = Field(pattern=_MCP_SERVICE)
    #: None offers every tool the service has, including any it adds later.
    tools: Optional[list[ToolName]] = Field(default=None, max_length=100)
    #: None asks the user first for every tool the service doesn't mark read-only.
    approve: Optional[list[ToolName]] = Field(default=None, max_length=100)


class ContextSettingsUpdate(BaseModel):
    #: None keeps the agent's default prompt section.
    prompt: Optional[str] = Field(default=None, max_length=8000)
    #: None keeps the context's default local tools.
    builtin_tools: Optional[list[str]] = Field(default=None, max_length=50)
    #: None keeps the bundle's Genie bindings for the context (GENIE_BINDINGS).
    genie_spaces: Optional[list[GenieSpace]] = Field(default=None, max_length=10)
    #: None keeps the default, which is no MCP services.
    mcp_services: Optional[list[McpServiceSetting]] = Field(default=None, max_length=10)


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
    saved = agent_settings.read_all()
    contexts = []
    for context in defaults.get("contexts", []):
        row = saved.get(context["id"]) or {}
        tools = row.get("tools") or {}
        contexts.append({
            "id": context["id"],
            "label": context["label"],
            "default_prompt": context["prompt"],
            "default_builtin_tools": context["builtin_tools"],
            "default_genie_spaces": agent_settings.default_genie_spaces(client, context["id"]),
            "prompt": row.get("prompt"),
            "builtin_tools": tools.get("builtin"),
            "genie_spaces": tools.get("genie"),
            "default_mcp_services": [],
            "mcp_services": tools.get("mcp"),
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
    spaces = None
    if update.genie_spaces is not None:
        names = [s.name for s in update.genie_spaces]
        if len(set(names)) != len(names):
            raise HTTPException(status_code=400, detail="Each Genie space needs a different tool name.")
        # The title comes from Genie, read as this admin, which also proves the id
        # is real and that the admin can open the space.
        spaces = [
            {**space.model_dump(), "title": agent_settings.genie_space(client, space.space_id)["title"]}
            for space in update.genie_spaces
        ]
    services = None
    if update.mcp_services is not None:
        names = [s.service for s in update.mcp_services]
        if len(set(names)) != len(names):
            raise HTTPException(status_code=400, detail="Each MCP service can be added once.")
        if unsupported := set(names) & agent_settings.UNSUPPORTED_MCP_SERVICES:
            raise HTTPException(
                status_code=400,
                detail=f"{', '.join(sorted(unsupported))} can't be added in Settings; bind it in the agent's agent.toml.",
            )
        # Read as this admin, which proves the service exists and that they can see it.
        for name in names:
            agent_settings.mcp_service(client, name)
        services = [
            {"service": s.service, "tools": s.tools, "approve": s.approve} for s in update.mcp_services
        ]
    prompt = (update.prompt or "").strip() or None
    agent_settings.save(
        context_id,
        prompt,
        {"builtin": update.builtin_tools, "genie": spaces, "mcp": services},
        caller.email,
    )
    return {"status": "saved"}


@router.delete("/agent/{context_id}", summary="Return one context to the agent's defaults")
def reset_context(context_id: str = _CONTEXT_ID, _client: WorkspaceClient = Depends(_admin_client)) -> dict:
    agent_settings.reset(context_id)
    return {"status": "reset"}


@router.get("/genie-spaces/{space_id}", summary="Look up a Genie space before adding it")
def genie_space(
    space_id: str = Path(pattern=_SPACE_ID),
    client: WorkspaceClient = Depends(_admin_client),
) -> dict:
    return agent_settings.genie_space(client, space_id)


@router.get("/genie-spaces", summary="The Genie spaces you can open, to search in the tool picker")
def genie_spaces(client: WorkspaceClient = Depends(_admin_client)) -> dict:
    return {"spaces": agent_settings.list_genie_spaces(client)}


@router.get("/mcp-services", summary="The MCP services in a Unity Catalog schema that you can use")
def mcp_services(
    schema: str = Query(default="system.ai", pattern=_SCHEMA),
    client: WorkspaceClient = Depends(_admin_client),
) -> dict:
    return {"schema": schema, "services": agent_settings.list_mcp_services(client, schema)}


@router.get("/mcp-services/{service}/tools", summary="One MCP service's tools, as you see them")
def mcp_service_tools(
    service: str = Path(pattern=_MCP_SERVICE),
    refresh: bool = False,
    _client: WorkspaceClient = Depends(_admin_client),
    user_token: Optional[str] = Depends(get_user_token),
) -> dict:
    if service in agent_settings.UNSUPPORTED_MCP_SERVICES:
        raise HTTPException(status_code=400, detail=f"{service} can't be added in Settings.")
    return agent_settings.mcp_service_tools(user_token, service, refresh)
