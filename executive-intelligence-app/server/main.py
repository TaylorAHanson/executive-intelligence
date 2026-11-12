"""FastAPI application: API routes plus the built React SPA.

One process serves both. The browser loads the SPA from `/`, and the SPA calls
`/api/...` on that same origin — no CORS in production, no second app to deploy,
and the user's forwarded token is already present on every request.

Imports here are flat (`from routes import health`, not `from server.routes ...`)
because uvicorn runs with `server/` on the path. See `AGENTS.md` in this folder.
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import db_pool
from config import settings
from database import init_db
from middleware.auth import AuthMiddleware
from routes import agent, health, user
from routes import settings as app_settings
from routes.dashboards import customers as customers_dashboard
from routes.dashboards import executive as executive_dashboard

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up in environment: %s", settings.get_app_environment())

    # Guarded, and deliberately so. An unhandled exception during startup takes
    # down the whole app with "Child process failed to start, stopping the
    # parent process" — so a database that is briefly unreachable would stop the
    # app from serving even the pages that need no database at all. Schema init
    # is idempotent, so the next worker or restart picks it up.
    try:
        init_db()
    except Exception as e:  # noqa: BLE001
        logger.error("init_db() failed during startup: %s", e, exc_info=True)

    yield

    logger.info("Shutting down.")
    try:
        db_pool.close_all()
    except Exception as e:  # noqa: BLE001
        logger.warning("Error closing the connection pool: %s", e)


app = FastAPI(
    title="Executive Intelligence",
    # Namespaced under /api so they don't collide with the SPA's routes.
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# Puts the forwarded identity on `request.state` for the auth dependencies.
app.add_middleware(AuthMiddleware)

# --- Routes -----------------------------------------------------------------
#
# There is no auto-discovery: a router that isn't registered here falls through
# to the SPA catch-all and returns a confusing 404. Add new routers to this list.

app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(user.router, prefix="/api/user", tags=["user"])
app.include_router(agent.router, prefix="/api/agent", tags=["agent"])
app.include_router(app_settings.router, prefix="/api/settings", tags=["settings"])

# Dashboards: one router per section in src/sections.ts, at /api/dashboards/<section id>.
app.include_router(executive_dashboard.router, prefix="/api/dashboards/executive", tags=["dashboards"])
app.include_router(customers_dashboard.router, prefix="/api/dashboards/customers", tags=["dashboards"])


# --- Static frontend --------------------------------------------------------

_DIST = Path(__file__).resolve().parent.parent / "dist"

if (_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=str(_DIST / "assets")), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def serve_spa(full_path: str):
    """Serve the built SPA, falling back to index.html for client-side routes.

    Must be declared LAST: it matches everything, so any route registered after
    it is unreachable.
    """
    # An unmatched /api path is a bug in the caller or a missing router. Answer
    # with JSON rather than handing back index.html, which makes a typo in a URL
    # look like the API returning HTML.
    if full_path.startswith("api/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)

    if not _DIST.is_dir():
        return JSONResponse(
            {"detail": "Frontend not built. Run `npm run build`, or use ./dev.sh for local development."},
            status_code=503,
        )

    requested = _DIST / full_path
    # `resolve()` and the prefix check stop `../../etc/passwd` from escaping the
    # dist directory.
    if full_path and requested.is_file() and requested.resolve().is_relative_to(_DIST.resolve()):
        return FileResponse(requested)

    return FileResponse(_DIST / "index.html")
