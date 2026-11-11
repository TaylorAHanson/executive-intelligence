"""Executive Insights: one GET per widget, mounted at /api/dashboards/executive.

Every handler runs its query as the signed-in user (`get_workspace_client`).
Handlers stay this thin: parse filters, pick the query, run it.
"""
from databricks.sdk import WorkspaceClient
from fastapi import APIRouter, Depends

from middleware.auth import get_workspace_client
from queries import executive as queries
from services.dashboards import Period, WidgetResult, period_filter, regions_filter, run_widget

router = APIRouter()


@router.get("/kpis", summary="Revenue, OTIF, and design-win rate vs the prior period")
def kpis(
    period: Period = Depends(period_filter),
    regions: str = Depends(regions_filter),
    client: WorkspaceClient = Depends(get_workspace_client),
) -> WidgetResult:
    return run_widget(client, *queries.kpis(period, regions))


@router.get("/monthly", summary="Revenue, OTIF, and win rate per month")
def monthly(
    period: Period = Depends(period_filter),
    regions: str = Depends(regions_filter),
    client: WorkspaceClient = Depends(get_workspace_client),
) -> WidgetResult:
    return run_widget(client, *queries.monthly(period, regions))


@router.get("/revenue-by-region", summary="Monthly revenue per region")
def revenue_by_region(
    period: Period = Depends(period_filter),
    regions: str = Depends(regions_filter),
    client: WorkspaceClient = Depends(get_workspace_client),
) -> WidgetResult:
    return run_widget(client, *queries.revenue_by_region(period, regions))


@router.get("/top-customers", summary="Largest customers with growth, OTIF, and health")
def top_customers(
    period: Period = Depends(period_filter),
    regions: str = Depends(regions_filter),
    client: WorkspaceClient = Depends(get_workspace_client),
) -> WidgetResult:
    return run_widget(client, *queries.top_customers(period, regions))


@router.get("/regions", summary="Region filter options")
def regions(client: WorkspaceClient = Depends(get_workspace_client)) -> WidgetResult:
    return run_widget(client, *queries.regions())
