"""Liveness and deployment metadata.

This is the one route that answers without an authenticated user, because the
frontend needs the environment label before auth resolves. Keep it that way, and
keep it boring: no secrets, no tokens, no internal hostnames. Anyone who can
reach the app can read this.
"""
from fastapi import APIRouter

import db_pool
from config import settings

router = APIRouter()


@router.get("/health", summary="Liveness check and deployment metadata")
def health() -> dict:
    return {
        "status": "healthy",
        "environment": settings.get_app_environment(),
        "synthetic_data": settings.data_is_synthetic(),
        # Whether these are configured, never their values.
        "sql_warehouse_configured": bool(settings.get_sql_warehouse_id()),
        "dashboard_data_configured": bool(settings.get_data_catalog() and settings.get_data_schema()),
        "agent_configured": bool(settings.get_agent_app_url()),
        "database_configured": settings.lakebase_configured(),
        # Per worker, so a deployment's totals are these times the worker count.
        # `reused` far above `opened` is the pool working; see db_pool.stats().
        "db_pool": db_pool.stats(),
    }
