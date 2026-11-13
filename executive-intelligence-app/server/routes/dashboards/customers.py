"""Customer Intelligence: one GET per widget, mounted at /api/dashboards/customers.

Same shape as routes/dashboards/executive.py: every handler runs its query as
the signed-in user. The briefing takes no period filter (queries/customers.py
says why); `customer` scopes a widget to one top-10 account.
"""
from typing import Optional

from databricks.sdk import WorkspaceClient
from fastapi import APIRouter, Depends, HTTPException, Query

from middleware.auth import get_workspace_client
from queries import customers as queries
from services.dashboards import WidgetResult, run_widget

router = APIRouter()

_CUSTOMER_ID = r"^[A-Za-z0-9_-]{1,40}$"
_SCOPE = r"^(portfolio|[A-Za-z0-9_-]{1,40})$"


def optional_customer(
    customer: Optional[str] = Query(None, pattern=_CUSTOMER_ID, description="A top-10 customer_id; omit for all ten"),
) -> str:
    return customer or ""


def required_customer(customer: str = Query(..., pattern=_CUSTOMER_ID, description="A top-10 customer_id")) -> str:
    return customer


@router.get("/briefing", summary="Insight records for the top-10 briefing or one account")
def briefing(
    scope: str = Query("portfolio", pattern=_SCOPE, description='"portfolio" or a customer_id'),
    client: WorkspaceClient = Depends(get_workspace_client),
) -> WidgetResult:
    return run_widget(client, *queries.briefing(queries.windows(), scope))


@router.get("/themes", summary="What the top 10 are focused on")
def themes(client: WorkspaceClient = Depends(get_workspace_client)) -> WidgetResult:
    return run_widget(client, *queries.themes(queries.windows()))


@router.get("/signals", summary="Market and account signals with their sources")
def signals(
    customer: str = Depends(optional_customer),
    client: WorkspaceClient = Depends(get_workspace_client),
) -> WidgetResult:
    return run_widget(client, *queries.signals(queries.windows(), customer))


@router.get("/kpis", summary="Top 10: revenue vs plan, device share, lead-to-win conversion")
def kpis(client: WorkspaceClient = Depends(get_workspace_client)) -> WidgetResult:
    return run_widget(client, *queries.kpis(queries.windows()))


@router.get("/accounts", summary="The top 10 with trend, plan, share, focus, and risk")
def accounts(client: WorkspaceClient = Depends(get_workspace_client)) -> WidgetResult:
    return run_widget(client, *queries.accounts(queries.windows()))


@router.get("/accounts-monthly", summary="Monthly revenue per top-10 account")
def accounts_monthly(client: WorkspaceClient = Depends(get_workspace_client)) -> WidgetResult:
    return run_widget(client, *queries.accounts_monthly(queries.windows()))


@router.get("/outlook", summary="Next quarter: plan, commit, and best case")
def outlook(client: WorkspaceClient = Depends(get_workspace_client)) -> WidgetResult:
    return run_widget(client, *queries.outlook(queries.windows()))


@router.get("/renewals", summary="Top-10 contracts ending in the next 12 months")
def renewals(client: WorkspaceClient = Depends(get_workspace_client)) -> WidgetResult:
    return run_widget(client, *queries.renewals(queries.windows()))


@router.get("/coverage", summary="Next quarter's gap to plan against the open deals that close in it")
def coverage(
    customer: str = Depends(optional_customer),
    client: WorkspaceClient = Depends(get_workspace_client),
) -> WidgetResult:
    return run_widget(client, *queries.coverage(queries.windows(), customer))


@router.get("/deals", summary="Largest open deals closing next quarter")
def deals(
    customer: str = Depends(optional_customer),
    client: WorkspaceClient = Depends(get_workspace_client),
) -> WidgetResult:
    return run_widget(client, *queries.deals(queries.windows(), customer))


@router.get("/profile", summary="One account's headline numbers")
def profile(
    customer: str = Depends(required_customer),
    client: WorkspaceClient = Depends(get_workspace_client),
) -> WidgetResult:
    result = run_widget(client, *queries.profile(queries.windows(), customer))
    if not result.rows:
        raise HTTPException(status_code=404, detail="Customer Intelligence covers the top-10 accounts only.")
    return result


@router.get("/revenue", summary="One account's revenue, plan, and forecast by month")
def revenue(
    customer: str = Depends(required_customer),
    client: WorkspaceClient = Depends(get_workspace_client),
) -> WidgetResult:
    return run_widget(client, *queries.revenue(queries.windows(), customer))


@router.get("/footprint", summary="One account's share of new device models, by quarter")
def footprint(
    customer: str = Depends(required_customer),
    client: WorkspaceClient = Depends(get_workspace_client),
) -> WidgetResult:
    return run_widget(client, *queries.footprint(queries.windows(), customer))


@router.get("/contracts", summary="One account's live contracts")
def contracts(
    customer: str = Depends(required_customer),
    client: WorkspaceClient = Depends(get_workspace_client),
) -> WidgetResult:
    return run_widget(client, *queries.contracts(queries.windows(), customer))
