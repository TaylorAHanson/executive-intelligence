"""A stand-in WorkspaceClient for the dashboard tests: it records the statement and returns canned rows."""


class FakeStatementExecution:
    def __init__(self, columns=(), rows=(), total_row_count=None, error=None):
        self.captured = None
        self.columns = columns
        self.rows = [list(r) for r in rows]
        self.total_row_count = total_row_count
        self.error = error

    def execute_statement(self, **kwargs):
        self.captured = kwargs
        outer = self

        class Error:
            message = outer.error

        class Status:
            state = None
            error = None

        if self.error:
            from databricks.sdk.service.sql import StatementState

            Status.state = StatementState.FAILED
            Status.error = Error()

        class Column:
            def __init__(self, name, type_name):
                self.name = name
                self.type_name = type_name

        class Schema:
            columns = [Column(n, t) for n, t in outer.columns]

        class Manifest:
            schema = Schema()
            total_row_count = outer.total_row_count
            truncated = False

        class Chunk:
            data_array = outer.rows
            next_chunk_index = None

        class Response:
            status = Status()
            manifest = Manifest()
            result = Chunk()
            statement_id = "fake-statement-id"

        return Response()

    def get_statement_result_chunk_n(self, statement_id, chunk_index):
        raise AssertionError("not expected")


class FakeClient:
    def __init__(self, **kwargs):
        self.statement_execution = FakeStatementExecution(**kwargs)
