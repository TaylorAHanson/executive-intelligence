"""The shared half of every dashboard endpoint.

A dashboard is three layers, one file each:

    queries/<section>.py         SQL for each widget, against contract views only
    routes/dashboards/<section>.py  one GET per widget: filters in, WidgetResult out
    services/dashboards.py       this file: filter parsing, execution, errors

Every widget endpoint takes `client = Depends(get_workspace_client)`, so its
query runs AS THE SIGNED-IN USER and Unity Catalog applies that user's grants.
A user who cannot SELECT from a view gets a 403 naming the problem, never
someone else's data. Do not swap in the service principal to "fix" a 403:
the fix is a grant (see data/grants.sql).
"""
import datetime
import logging
from dataclasses import dataclass
from typing import Any, Optional

from databricks.sdk import WorkspaceClient
from fastapi import HTTPException, Query
from pydantic import BaseModel

from config import settings
from services.sql import run_query

logger = logging.getLogger(__name__)

#: Widest date range a filter may ask for, so one request cannot scan everything.
MAX_PERIOD_MONTHS = 60
DEFAULT_PERIOD_MONTHS = 12

#: Multi-select filters: at most this many values, each at most this long.
MAX_LIST_VALUES = 50
MAX_LIST_VALUE_LENGTH = 100

_NUMERIC_TYPES = {"BYTE", "SHORT", "INT", "LONG", "FLOAT", "DOUBLE", "DECIMAL"}
_INTEGER_TYPES = {"BYTE", "SHORT", "INT", "LONG"}


class WidgetResult(BaseModel):
    """What every widget endpoint returns. Mirrored by `WidgetResult` in src/api.ts."""

    columns: list[str]
    rows: list[dict[str, Any]]
    returned_rows: int
    total_rows: Optional[int]
    truncated: bool
    statement_id: Optional[str]


def data_object(name: str) -> str:
    """Fully qualified name of a contract view, for splicing into a query."""
    try:
        return settings.get_data_object(name)
    except ValueError as e:
        logger.error("Dashboard data is misconfigured: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


def run_widget(
    client: WorkspaceClient,
    statement: str,
    parameters: Optional[dict[str, Any]] = None,
    max_rows: int = 1000,
) -> WidgetResult:
    """Run one widget's query and return its result with typed values.

    The warehouse returns every value as a string. Numeric and boolean columns
    are converted here, by the column's reported type rather than by what the
    value looks like, so an id such as "007" stays a string.
    """
    try:
        result = run_query(client, statement, parameters, max_rows=max_rows)
    except HTTPException as e:
        raise _explain(e) from e

    types = result.get("column_types") or [None] * len(result["columns"])
    rows = [
        {name: _coerce(row.get(name), type_name) for name, type_name in zip(result["columns"], types)}
        for row in result["rows"]
    ]
    return WidgetResult(
        columns=result["columns"],
        rows=rows,
        returned_rows=result["returned_rows"],
        total_rows=result["total_rows"],
        truncated=result["truncated"],
        statement_id=result["statement_id"],
    )


def _coerce(value: Any, type_name: Optional[str]) -> Any:
    if value is None or type_name is None:
        return value
    try:
        if type_name in _INTEGER_TYPES:
            return int(value)
        if type_name in _NUMERIC_TYPES:
            return float(value)
        if type_name == "BOOLEAN":
            return str(value).lower() == "true"
    except (TypeError, ValueError):
        return value
    return value


def _explain(error: HTTPException) -> HTTPException:
    """Turn the warehouse's error for a failed statement into one a user can act on."""
    detail = str(error.detail)
    if error.status_code != 400:
        return error
    if "INSUFFICIENT_PERMISSIONS" in detail or "PERMISSION_DENIED" in detail:
        return HTTPException(
            status_code=403,
            detail="You do not have access to this dashboard's data. Ask an admin for SELECT on the "
            f"{settings.get_data_catalog()}.{settings.get_data_schema()} views. ({detail})",
        )
    if "TABLE_OR_VIEW_NOT_FOUND" in detail or "SCHEMA_NOT_FOUND" in detail or "NO_SUCH_CATALOG" in detail:
        return HTTPException(
            status_code=404,
            detail="This dashboard's data is not set up in this workspace: a contract view is missing. "
            f"See data/contract.md. ({detail})",
        )
    return error


# --- Filters -----------------------------------------------------------------
#
# Use these as FastAPI dependencies so every dashboard parses the same query
# string the same way. Their values are always bound as parameters, never
# formatted into SQL.


@dataclass(frozen=True)
class Period:
    """A run of whole months. `end` is exclusive; `prior_start` begins the equal-length period before."""

    start: datetime.date
    end: datetime.date
    prior_start: datetime.date

    @property
    def months(self) -> int:
        return _months_between(self.start, self.end)

    def params(self) -> dict[str, datetime.date]:
        return {"start": self.start, "end": self.end, "prior_start": self.prior_start}


def period_filter(
    from_: Optional[str] = Query(None, alias="from", pattern=r"^\d{4}-\d{2}$", description="First month, YYYY-MM"),
    to: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}$", description="Last month (inclusive), YYYY-MM"),
) -> Period:
    """`?from=YYYY-MM&to=YYYY-MM`, both inclusive. Defaults to the last 12 complete months.

    The current month is left out of the default because it is partial: a
    period ending in it compares a few weeks of revenue against full months.
    """
    this_month = datetime.date.today().replace(day=1)
    last = _parse_month(to) if to else _add_months(this_month, -1)
    first = _parse_month(from_) if from_ else _add_months(last, -(DEFAULT_PERIOD_MONTHS - 1))
    if first > last:
        raise HTTPException(status_code=400, detail="The period's first month is after its last.")
    end = _add_months(last, 1)
    months = _months_between(first, end)
    if months > MAX_PERIOD_MONTHS:
        raise HTTPException(status_code=400, detail=f"The period can span at most {MAX_PERIOD_MONTHS} months.")
    return Period(start=first, end=end, prior_start=_add_months(first, -months))


def list_filter(value: Optional[str]) -> str:
    """Normalize a comma-separated multi-select value. '' means no filter.

    Queries test it with `(:p = '' OR array_contains(split(:p, ','), column))`,
    so the whole list binds as one parameter.
    """
    if not value:
        return ""
    items = list(dict.fromkeys(part.strip() for part in value.split(",") if part.strip()))
    if len(items) > MAX_LIST_VALUES or any(len(item) > MAX_LIST_VALUE_LENGTH for item in items):
        raise HTTPException(
            status_code=400,
            detail=f"A filter takes at most {MAX_LIST_VALUES} values of {MAX_LIST_VALUE_LENGTH} characters.",
        )
    return ",".join(items)


def regions_filter(regions: Optional[str] = Query(None, description="Comma-separated regions")) -> str:
    return list_filter(regions)


def _parse_month(value: str) -> datetime.date:
    try:
        year, month = (int(part) for part in value.split("-"))
        return datetime.date(year, month, 1)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{value!r} is not a month (YYYY-MM).")


def _add_months(day: datetime.date, months: int) -> datetime.date:
    index = day.year * 12 + (day.month - 1) + months
    return datetime.date(index // 12, index % 12 + 1, 1)


def _months_between(start: datetime.date, end: datetime.date) -> int:
    return (end.year - start.year) * 12 + (end.month - start.month)
