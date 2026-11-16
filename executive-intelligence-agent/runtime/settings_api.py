"""Routes the client's Settings page reads: context defaults, and what an MCP service offers.

The client app calls these with the signed-in admin's token (its ``services/agent_settings.py``), so
anything listed here is listed as that admin. Neither route holds credentials or data.
"""

import asyncio

from agent import mcp_services
from agent.contexts import MCP_SERVICE_RE, UNSUPPORTED_MCP_SERVICES, describe_contexts
from agent.tools import all_tools
from fastapi import FastAPI, HTTPException, Request

from databricks_agentkit.runtime.auth import RequestAuthContext


def install_settings_api(app: FastAPI) -> None:
    @app.get("/api/contexts", include_in_schema=False)
    def contexts() -> dict:
        """Each context's default prompt and tools, which the client's Settings page edits over."""
        return describe_contexts(all_tools())

    @app.get("/api/mcp-services/{service}/tools", include_in_schema=False)
    async def mcp_service_tools(service: str, request: Request, refresh: bool = False) -> dict:
        """A Unity Catalog MCP service's tools as the caller sees them.

        Listed through the same code the agent uses on each turn (``agent/mcp_services.py``), so
        the names an admin picks are the ones the agent offers. A service that answers with an
        error lists no tools and says why in ``problem``; signing in to it is often the fix.
        """
        if not MCP_SERVICE_RE.match(service) or service in UNSUPPORTED_MCP_SERVICES:
            raise HTTPException(
                status_code=400, detail=f"Not an MCP service settings can attach: {service!r}."
            )
        # Deployed, this raises AuthError (answered 401 by the server) when no user is forwarded.
        auth = RequestAuthContext.from_headers(request.headers)
        try:
            client = await asyncio.to_thread(auth.client_for, "user")
            try:
                tools = await mcp_services.list_tools(client, service, fresh=refresh)
            except Exception as error:  # noqa: BLE001 - reported to the admin, not raised
                return {"service": service, "tools": [], "problem": mcp_services.problem(error)}
            return {
                "service": service,
                "tools": [mcp_services.describe(tool) for tool in tools],
                "problem": None,
            }
        finally:
            auth.close()
