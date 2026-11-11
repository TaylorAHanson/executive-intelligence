"""Running SQL against a Databricks warehouse, safely.

THE RULE: values go in as parameters, never as string formatting.

    # WRONG — an f-string. `dept` closes the quote and appends its own SQL.
    sql = f"SELECT * FROM employees WHERE dept = '{dept}'"

    # RIGHT — a named marker; the value is sent separately and can only ever
    # be read as a literal.
    run_query(client, "SELECT * FROM employees WHERE dept = :dept", {"dept": dept})

This is not a style preference. A value that reaches an f-string is executable
SQL: `dept = "x' OR 1=1 --"` turns a filtered read into a full table scan, and
`"x'; DROP TABLE employees --"` is the version that makes the news. Escaping
quotes by hand is the fix that looks right and keeps failing, because it has to
be perfect everywhere while an attacker needs one miss.

Parameter markers are `:name`. Positional `?` markers are NOT supported by the
Statement Execution API.

Identifiers — table, schema, and column NAMES — cannot be parameterized, because
they change what the query is rather than what it filters on. When one has to be
dynamic, either use SQL's `IDENTIFIER(:name)` clause or validate it with
`require_identifier` below. Never interpolate a raw string.

THE SECOND RULE: a partial result says so.

Results arrive in chunks, and `run_query` stops at `max_rows`. Both of those mean
the rows you get back can be a subset of the rows the query matched, so every
response carries `truncated` and, where the warehouse reports it, `total_rows`.

Check `truncated` before you do anything with the rows that assumes you have all
of them. A truncated read is far more dangerous than a failed one: an error gets
noticed and fixed, whereas a total summed over the first 1,000 of 50,000 rows
looks entirely reasonable and is simply wrong. **Aggregate in SQL, not in Python
over the returned rows** — `SELECT SUM(x)` returns one row and is always
complete, while summing `rows` in the handler is correct only until the data
grows past the cap.
"""
import datetime
import logging
import re
from typing import Any, Optional

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import (
    Disposition,
    StatementParameterListItem,
    StatementState,
)
from fastapi import HTTPException

logger = logging.getLogger(__name__)

#: How long to hold the request open waiting for results. The API caps this at
#: 50s; a query slower than that needs a polling flow rather than a bigger number.
_WAIT_TIMEOUT = "50s"

#: Unqualified SQL identifiers: a letter or underscore, then word characters.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def run_query(
    client: WorkspaceClient,
    statement: str,
    parameters: Optional[dict[str, Any]] = None,
    warehouse_id: Optional[str] = None,
    max_rows: int = 1000,
) -> dict[str, Any]:
    """Execute `statement` and return the result, saying so if it is partial.

    Returns a dict of:
        columns:       column names, in order
        column_types:  the warehouse's type name for each column (`LONG`,
                       `DECIMAL`, `DATE`, ...), or None where unreported. Every
                       value in `rows` arrives as a string; these say how to
                       read it.
        rows:          the rows retrieved, at most `max_rows` of them
        returned_rows: how many rows are in `rows`
        total_rows:    how many the query actually matched, or None if the
                       warehouse did not report it
        truncated:     True when the query matched more rows than were returned
        statement_id:  the warehouse's id for this execution, for correlating logs

    `returned_rows` is deliberately not called `row_count`: it counts what is in
    this payload, which is not the size of the result set whenever `truncated`
    is True. Treating one as the other is the mistake this shape exists to make
    hard.

    Args:
        client: Pass the OBO client from `get_workspace_client` so the query runs
            under the caller's own Unity Catalog grants.
        statement: SQL using `:name` markers for every value.
        parameters: Values for those markers. Sent separately from the SQL text.
            A `datetime.date` or `datetime.datetime` is sent typed as DATE or
            TIMESTAMP; everything else as STRING.
        warehouse_id: Defaults to `SQL_WAREHOUSE_ID`.
        max_rows: Ceiling on rows returned, so one query cannot exhaust memory.
            Raise it if you must, but prefer aggregating in SQL.
    """
    from config import settings

    warehouse_id = warehouse_id or settings.get_sql_warehouse_id()
    if not warehouse_id:
        raise HTTPException(
            status_code=500,
            detail="No SQL warehouse configured. Set SQL_WAREHOUSE_ID in databricks.yml (or .env locally).",
        )

    # Every value becomes a parameter. Types are optional and default to STRING;
    # name them when the column is not a string, so the warehouse can compare
    # correctly rather than casting behind your back.
    parameter_items = [_parameter(name, value) for name, value in (parameters or {}).items()]

    # Log the statement, never the parameter values — they are user data, and a
    # WHERE clause is a fine place for a national ID number to hide.
    logger.info("Executing statement with %d parameter(s)", len(parameter_items))

    response = client.statement_execution.execute_statement(
        warehouse_id=warehouse_id,
        statement=statement,
        parameters=parameter_items or None,
        wait_timeout=_WAIT_TIMEOUT,
        disposition=Disposition.INLINE,
    )

    _raise_if_unsuccessful(response)

    columns: list[str] = []
    column_types: list[Optional[str]] = []
    if response.manifest and response.manifest.schema and response.manifest.schema.columns:
        columns = [column.name for column in response.manifest.schema.columns]
        column_types = [_type_name(column) for column in response.manifest.schema.columns]

    rows, truncated = _collect_rows(client, response, columns, max(1, max_rows))
    total_rows = getattr(response.manifest, "total_row_count", None) if response.manifest else None

    if truncated:
        # Worth a log line of its own: the request still succeeds, so this is
        # otherwise invisible until someone notices a total is too small.
        logger.warning(
            "Result truncated at %d row(s) of %s for statement %s",
            len(rows),
            total_rows if total_rows is not None else "an unreported number",
            response.statement_id,
        )

    return {
        "columns": columns,
        "column_types": column_types,
        "rows": rows,
        "returned_rows": len(rows),
        "total_rows": total_rows,
        "truncated": truncated,
        "statement_id": response.statement_id,
    }


def _parameter(name: str, value: Any) -> StatementParameterListItem:
    # `datetime` subclasses `date`, so it has to be checked first.
    if isinstance(value, datetime.datetime):
        return StatementParameterListItem(name=name, value=value.isoformat(), type="TIMESTAMP")
    if isinstance(value, datetime.date):
        return StatementParameterListItem(name=name, value=value.isoformat(), type="DATE")
    return StatementParameterListItem(name=name, value=None if value is None else str(value))


def _type_name(column) -> Optional[str]:
    type_name = getattr(column, "type_name", None)
    if type_name is None:
        return None
    return str(getattr(type_name, "value", type_name))


def _collect_rows(
    client: WorkspaceClient,
    response,
    columns: list[str],
    max_rows: int,
) -> tuple[list[dict[str, Any]], bool]:
    """Gather rows across result chunks, up to `max_rows`.

    A result set is delivered in chunks, and `response.result` holds only the
    FIRST one — reading it alone silently drops the rest of a large result. Each
    chunk points at the next through `next_chunk_index`, so this walks the chain
    until the rows run out or the cap is hit.

    Returns the rows and whether anything was left behind.
    """
    rows: list[dict[str, Any]] = []

    # The API truncates on its own if the result exceeds the byte limit, which is
    # independent of our row cap and has to be carried through.
    truncated = bool(getattr(response.manifest, "truncated", False)) if response.manifest else False

    chunk = response.result
    while chunk is not None:
        for raw in chunk.data_array or []:
            if len(rows) >= max_rows:
                return rows, True
            rows.append({name: raw[i] if i < len(raw) else None for i, name in enumerate(columns)})

        next_index = getattr(chunk, "next_chunk_index", None)
        if next_index is None:
            break

        try:
            # Note the `_n` suffix — there is no `get_statement_result_chunk`.
            chunk = client.statement_execution.get_statement_result_chunk_n(
                response.statement_id, next_index
            )
        except Exception as e:  # noqa: BLE001
            # Returning what we have is better than failing outright, but the
            # caller must be told it is incomplete.
            logger.warning("Could not fetch result chunk %s: %s", next_index, e)
            return rows, True

    return rows, truncated


def require_identifier(value: str, label: str = "identifier") -> str:
    """Validate a dynamic table/schema/column name, or raise 400.

    Only for the identifier case, where parameters are not an option. Prefer
    an allowlist of the names your app actually supports; reach for this when
    the set is genuinely open-ended.
    """
    if not _IDENTIFIER_RE.match(value or ""):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {label}. Expected letters, digits, and underscores only.",
        )
    return value


def _raise_if_unsuccessful(response) -> None:
    """Turn a failed statement into an HTTP error the caller can actually see.

    `execute_statement` reports a rejected query in `response.status` rather than
    by raising, so a query that failed on a typo, a missing table, or a
    permission denial comes back as a perfectly ordinary object with no rows.
    Skip this check and the UI renders "no data" for what was really an error,
    which is a genuinely awful thing to debug.
    """
    status = getattr(response, "status", None)
    state = getattr(status, "state", None)

    if state in (StatementState.PENDING, StatementState.RUNNING):
        raise HTTPException(
            status_code=504,
            detail=f"The query is still running after {_WAIT_TIMEOUT}. Narrow it, or pre-aggregate the data.",
        )

    if state in (StatementState.FAILED, StatementState.CANCELED, StatementState.CLOSED):
        error = getattr(status, "error", None)
        message = getattr(error, "message", "") or f"The query {str(getattr(state, 'value', state)).lower()}."
        logger.warning("Statement did not succeed: %s", message)
        raise HTTPException(status_code=400, detail=message)
