"""Tests for load.py's schema handling, with no workspace.

    executive-intelligence-app/server/venv/bin/python data/test_load.py

The point of ensure_schema: a schema that exists is used as it is, so loading works for someone who is
never granted CREATE SCHEMA.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

import load  # noqa: E402
from databricks.sdk.errors import NotFound, PermissionDenied  # noqa: E402

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


class Schemas:
    def __init__(self, error=None):
        self.error = error
        self.asked = []

    def get(self, name):
        self.asked.append(name)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(full_name=name)


def run(error=None, create_fails=None):
    """ensure_schema against a fake workspace. Returns (statements executed, what it raised or None)."""
    client = SimpleNamespace(schemas=Schemas(error))
    executed = []

    def fake_execute(_client, _warehouse, sql):
        executed.append(sql)
        if create_fails:
            raise RuntimeError(create_fails)

    real = load.execute
    load.execute = fake_execute
    try:
        load.ensure_schema(client, "wh", "cat", "sch")
        raised = None
    except SystemExit as e:
        raised = str(e)
    finally:
        load.execute = real
    return client.schemas.asked, executed, raised


print("\nA schema that exists")
asked, executed, raised = run()
check("is looked up by its full name", asked == ["cat.sch"])
check("is not created again, so CREATE SCHEMA is never needed", executed == [] and raised is None)

print("\nA schema that is missing")
_, executed, raised = run(error=NotFound("no such schema"))
check("is created", executed == ["CREATE SCHEMA IF NOT EXISTS `cat`.`sch`"] and raised is None)

print("\nA schema that cannot be created")
_, executed, raised = run(error=NotFound("no such schema"), create_fails="PERMISSION_DENIED: CREATE SCHEMA")
check("stops with a message", raised is not None and "does not exist and could not be created" in raised)
check("that carries the reason", "PERMISSION_DENIED" in raised)
check("and says to use an existing schema", "--schema" in raised and "data_schema" in raised)

print("\nA schema you cannot see")
_, executed, raised = run(error=PermissionDenied("not allowed"))
check("is treated as missing, and creating it settles the question", len(executed) == 1 and raised is None)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
