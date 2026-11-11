"""Tests for `database.run`, the transaction helper routes should use.

The behaviour worth protecting is the retry: it must recover from a dead pooled
connection, and it must NOT retry a commit, because a commit that failed may
still have landed and running the work twice would double-apply a write.

    server/venv/bin/python tests/test_database.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

import psycopg2  # noqa: E402

import database  # noqa: E402

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


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def execute(self, *_args):
        self.conn.executed += 1
        if self.conn.fail_with is not None:
            error, self.conn.fail_with = self.conn.fail_with, None
            raise error


class FakeConnection:
    def __init__(self, fail_with=None, commit_fails=False):
        self.fail_with = fail_with
        self.commit_fails = commit_fails
        self.executed = 0
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        if self.commit_fails:
            raise psycopg2.OperationalError("server closed the connection during commit")
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closes += 1


def use_connections(*connections):
    """Point `database.run` at a scripted sequence of fake connections."""
    queue = list(connections)
    handed_out = []

    def fake_get_connection(pooled: bool = True):
        conn = queue.pop(0)
        handed_out.append(conn)
        return conn

    database.get_connection = fake_get_connection
    return handed_out


real_get_connection = database.get_connection

# --- The happy path ----------------------------------------------------------

print("\nThe happy path")

use_connections(FakeConnection())
conn = FakeConnection()
use_connections(conn)
result = database.run(lambda cur: (cur.execute("SELECT 1"), "value")[1])
check("the work's return value is passed through", result == "value")
check("the transaction is committed", conn.commits == 1)
check("the connection is returned", conn.closes == 1)
check("nothing is rolled back", conn.rollbacks == 0)


# --- Retrying a dead connection ---------------------------------------------

print("\nRetrying a dead connection")

dead = FakeConnection(fail_with=psycopg2.OperationalError("server closed the connection unexpectedly"))
alive = FakeConnection()
use_connections(dead, alive)
result = database.run(lambda cur: (cur.execute("SELECT 1"), "recovered")[1])
check("a dead pooled connection is retried on a fresh one", result == "recovered")
check("the dead connection is not committed", dead.commits == 0)
check("the dead connection is returned so the pool can discard it", dead.closes == 1)
check("the retry commits", alive.commits == 1)

# Two dead connections in a row is a real outage, not a stale pool entry.
d1 = FakeConnection(fail_with=psycopg2.OperationalError("down"))
d2 = FakeConnection(fail_with=psycopg2.OperationalError("down"))
use_connections(d1, d2)
try:
    database.run(lambda cur: cur.execute("SELECT 1"))
    check("a persistent outage raises rather than looping", False)
except psycopg2.OperationalError:
    check("a persistent outage raises rather than looping", True)
check("and it retries exactly once, not forever", d1.executed == 1 and d2.executed == 1)

# InterfaceError is the other "connection is gone" flavour psycopg2 raises.
dead = FakeConnection(fail_with=psycopg2.InterfaceError("connection already closed"))
alive = FakeConnection()
use_connections(dead, alive)
database.run(lambda cur: cur.execute("SELECT 1"))
check("InterfaceError is treated as a dead connection too", alive.commits == 1)


# --- What must NOT be retried ------------------------------------------------

print("\nWhat must NOT be retried")

bad_sql = FakeConnection(fail_with=psycopg2.ProgrammingError('relation "nope" does not exist'))
spare = FakeConnection()
use_connections(bad_sql, spare)
try:
    database.run(lambda cur: cur.execute("SELECT * FROM nope"))
    check("a SQL error is not retried", False)
except psycopg2.ProgrammingError:
    check("a SQL error is not retried", True)
check("the second connection was never touched", spare.executed == 0)
check("the failed transaction is rolled back", bad_sql.rollbacks == 1)
check("and the connection is still returned", bad_sql.closes == 1)

# The important one: a commit may have landed even though it reported failure,
# so re-running the work could apply the write twice.
committing = FakeConnection(commit_fails=True)
spare = FakeConnection()
use_connections(committing, spare)
try:
    database.run(lambda cur: cur.execute("INSERT INTO notes VALUES (1)"))
    check("a failed commit is not retried", False)
except psycopg2.OperationalError:
    check("a failed commit is not retried", True)
check("the work is not run a second time", committing.executed == 1 and spare.executed == 0)
check("the connection is still returned after a failed commit", committing.closes == 1)


# --- Errors raised by the caller's own code ----------------------------------

print("\nErrors raised by the caller's own code")

conn = FakeConnection()
use_connections(conn)


def work_that_raises(cur):
    cur.execute("SELECT 1")
    raise ValueError("bug in the route handler")


try:
    database.run(work_that_raises)
    check("an error from the work propagates", False)
except ValueError:
    check("an error from the work propagates", True)
check("it is rolled back, not committed", conn.rollbacks == 1 and conn.commits == 0)
check("and the connection is returned", conn.closes == 1)


database.get_connection = real_get_connection

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
