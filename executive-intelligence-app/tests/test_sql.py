"""Tests for the SQL helpers.

Deliberately dependency-free: no pytest, no network, no Databricks credentials.
Run it directly.

    server/venv/bin/python tests/test_sql.py

The point of these is to pin the security-relevant behaviour — that values leave
as bound parameters rather than baked into the statement, and that a hostile
identifier is rejected. If you change `services/sql.py`, these should still pass.
"""
import sys
from pathlib import Path

# The backend uses flat imports (`from services.sql import ...`), matching how
# uvicorn runs it. Put server/ on the path so this file can do the same.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

from fastapi import HTTPException  # noqa: E402

from services.sql import require_identifier, run_query  # noqa: E402

passed = 0
failed = 0


def check(description: str, condition: bool) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  ok   {description}")
    else:
        failed += 1
        print(f"  FAIL {description}")


class FakeChunk:
    """One page of a result set, optionally pointing at the next."""

    def __init__(self, data_array, next_chunk_index=None):
        self.data_array = data_array
        self.next_chunk_index = next_chunk_index


class FakeStatementExecution:
    """Captures what would have been sent to Databricks, and replays a result."""

    def __init__(self, chunks=None, columns=None, total_row_count=None, api_truncated=False):
        self.captured = None
        self.chunks = chunks or {}
        self.columns = columns
        self.total_row_count = total_row_count
        self.api_truncated = api_truncated
        self.chunk_requests = []
        self.chunk_error = None

    def execute_statement(self, **kwargs):
        self.captured = kwargs
        outer = self

        class Status:
            state = None

        class Response:
            status = Status()
            manifest = outer._manifest()
            result = outer.chunks.get(0)
            statement_id = "fake-statement-id"

        return Response()

    def get_statement_result_chunk_n(self, statement_id, chunk_index):
        self.chunk_requests.append((statement_id, chunk_index))
        if self.chunk_error:
            raise self.chunk_error
        return self.chunks[chunk_index]

    def _manifest(self):
        if self.columns is None and self.total_row_count is None and not self.api_truncated:
            return None
        outer = self

        class Column:
            def __init__(self, name):
                self.name = name

        class Schema:
            columns = [Column(c) for c in (outer.columns or [])]

        class Manifest:
            schema = Schema()
            total_row_count = outer.total_row_count
            truncated = outer.api_truncated

        return Manifest()


class FakeClient:
    def __init__(self, **kwargs):
        self.statement_execution = FakeStatementExecution(**kwargs)


# --- Values are bound, never interpolated ------------------------------------

print("\nParameter binding")

client = FakeClient()
hostile = "x' OR 1=1 --"
run_query(
    client,
    "SELECT * FROM t WHERE name = :name",
    parameters={"name": hostile},
    warehouse_id="w-123",
)
sent = client.statement_execution.captured

check(
    "the statement is sent unmodified, with the marker intact",
    sent["statement"] == "SELECT * FROM t WHERE name = :name",
)
check(
    "the hostile value never appears in the statement text",
    hostile not in sent["statement"],
)
check(
    "the value travels in the parameters list instead",
    [p.name for p in sent["parameters"]] == ["name"]
    and [p.value for p in sent["parameters"]] == [hostile],
)

# A None value must reach the API as a real NULL, not the string "None".
client = FakeClient()
run_query(client, "SELECT :maybe", parameters={"maybe": None}, warehouse_id="w-123")
check(
    "None becomes a NULL parameter rather than the string 'None'",
    client.statement_execution.captured["parameters"][0].value is None,
)

# Numbers are stringified for transport; the warehouse casts them back.
client = FakeClient()
run_query(client, "SELECT :n", parameters={"n": 42}, warehouse_id="w-123")
check(
    "numeric values are serialized for transport",
    client.statement_execution.captured["parameters"][0].value == "42",
)

# No parameters at all should send None, not an empty list.
client = FakeClient()
run_query(client, "SELECT 1", warehouse_id="w-123")
check(
    "a statement with no parameters sends none",
    client.statement_execution.captured["parameters"] is None,
)


# --- Identifier validation ---------------------------------------------------

print("\nIdentifier validation")

check("a plain identifier is accepted", require_identifier("my_table") == "my_table")
check("digits and underscores are accepted", require_identifier("_t2_x") == "_t2_x")


def rejects(value) -> bool:
    try:
        require_identifier(value)
    except HTTPException as e:
        return e.status_code == 400
    return False


check("a quoted injection is rejected", rejects("t; DROP TABLE users --"))
check("a backtick is rejected", rejects("t`x"))
check("a space is rejected", rejects("my table"))
check("a leading digit is rejected", rejects("1table"))
check("a dotted name is rejected (validate each part separately)", rejects("schema.table"))
check("an empty string is rejected", rejects(""))
check("None is rejected", rejects(None))


# --- Results are complete, or say that they are not --------------------------
#
# The danger here is not an error, it is a plausible wrong answer: rows silently
# cut off at a chunk boundary or a row cap, reported as if they were the whole
# result. Every case below exists to make that impossible to miss.

print("\nThe fake matches the real SDK")

# A fake is only worth what its fidelity to the real thing. These assert that the
# SDK surface `run_query` depends on actually exists — the first version of this
# file called `get_statement_result_chunk`, which does not exist (it is
# `..._chunk_n`), and every test below passed anyway because the fake had the
# same typo. Checking the real class is what catches that.
from databricks.sdk.service.sql import (  # noqa: E402
    ResultData,
    ResultManifest,
    StatementExecutionAPI,
)

check(
    "the chunk-fetching method name is real",
    hasattr(StatementExecutionAPI, "get_statement_result_chunk_n"),
)
check(
    "the fake implements the same method the code calls",
    hasattr(FakeStatementExecution, "get_statement_result_chunk_n"),
)
check("ResultData really has next_chunk_index", "next_chunk_index" in ResultData.__annotations__)
check("ResultManifest really has total_row_count", "total_row_count" in ResultManifest.__annotations__)
check("ResultManifest really has truncated", "truncated" in ResultManifest.__annotations__)


print("\nComplete results")

client = FakeClient(
    columns=["id", "name"],
    chunks={0: FakeChunk([["1", "ada"], ["2", "grace"]])},
    total_row_count=2,
)
result = run_query(client, "SELECT id, name FROM t", warehouse_id="w-123")

check("columns come from the manifest", result["columns"] == ["id", "name"])
check(
    "rows are keyed by column name",
    result["rows"] == [{"id": "1", "name": "ada"}, {"id": "2", "name": "grace"}],
)
check("returned_rows counts what came back", result["returned_rows"] == 2)
check("total_rows reports what the query matched", result["total_rows"] == 2)
check("a complete result is not flagged as truncated", result["truncated"] is False)
check("no extra chunks are requested", client.statement_execution.chunk_requests == [])


print("\nChunked results")

# The bug this pins: `response.result` is only the FIRST chunk. Reading it alone
# returns 1 of 3 rows and calls it the answer.
client = FakeClient(
    columns=["id"],
    chunks={
        0: FakeChunk([["1"]], next_chunk_index=1),
        1: FakeChunk([["2"]], next_chunk_index=2),
        2: FakeChunk([["3"]]),
    },
    total_row_count=3,
)
result = run_query(client, "SELECT id FROM t", warehouse_id="w-123")

check("every chunk is followed, not just the first", result["returned_rows"] == 3)
check("rows arrive in order", [r["id"] for r in result["rows"]] == ["1", "2", "3"])
check("a fully-read chunked result is not truncated", result["truncated"] is False)
check(
    "the later chunks were actually fetched",
    [i for _, i in client.statement_execution.chunk_requests] == [1, 2],
)

# If a chunk can't be fetched, returning the rows we have is fine — pretending
# they are the whole result is not.
client = FakeClient(
    columns=["id"],
    chunks={0: FakeChunk([["1"]], next_chunk_index=1)},
    total_row_count=2,
)
client.statement_execution.chunk_error = RuntimeError("chunk expired")
result = run_query(client, "SELECT id FROM t", warehouse_id="w-123")
check("a failed chunk fetch still returns the rows already read", result["returned_rows"] == 1)
check("and marks the result truncated", result["truncated"] is True)


print("\nTruncation is always reported")

client = FakeClient(
    columns=["id"],
    chunks={0: FakeChunk([["1"], ["2"], ["3"], ["4"], ["5"]])},
    total_row_count=5,
)
result = run_query(client, "SELECT id FROM t", warehouse_id="w-123", max_rows=2)
check("max_rows caps the rows returned", result["returned_rows"] == 2)
check("hitting the cap sets truncated", result["truncated"] is True)
check("total_rows still reports the real size", result["total_rows"] == 5)

# The cap must be enforced across chunks too, and stop the walk early.
client = FakeClient(
    columns=["id"],
    chunks={
        0: FakeChunk([["1"], ["2"]], next_chunk_index=1),
        1: FakeChunk([["3"], ["4"]], next_chunk_index=2),
        2: FakeChunk([["5"]]),
    },
)
result = run_query(client, "SELECT id FROM t", warehouse_id="w-123", max_rows=3)
check("the cap applies across chunk boundaries", result["returned_rows"] == 3)
check("chunks beyond the cap are not fetched", client.statement_execution.chunk_requests == [("fake-statement-id", 1)])
check("and the result is flagged truncated", result["truncated"] is True)

# The warehouse can truncate on its own, for byte size, with no cap of ours hit.
client = FakeClient(columns=["id"], chunks={0: FakeChunk([["1"]])}, api_truncated=True)
result = run_query(client, "SELECT id FROM t", warehouse_id="w-123")
check(
    "truncation reported by the warehouse is carried through",
    result["truncated"] is True and result["returned_rows"] == 1,
)

# An empty result is complete, not truncated.
client = FakeClient(columns=["id"], chunks={0: FakeChunk([])}, total_row_count=0)
result = run_query(client, "SELECT id FROM t WHERE false", warehouse_id="w-123")
check(
    "an empty result is complete, not truncated",
    result["returned_rows"] == 0 and result["truncated"] is False,
)

# A statement with no result at all (a DDL, say) must not blow up.
client = FakeClient()
result = run_query(client, "CREATE TABLE t (id INT)", warehouse_id="w-123")
check(
    "a statement with no result set returns empty rather than failing",
    result["rows"] == [] and result["truncated"] is False and result["total_rows"] is None,
)


print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
