"""Tests for the connection pool.

No database in them: a fake connection object is enough to pin every decision
the pool makes — reuse, ping, recycle by age, retire on new credentials, and
reclaim a connection a caller forgot to close. Anything needing a real Lakebase
belongs in a soak test against a running server, not here.

    server/venv/bin/python tests/test_db_pool.py
"""
import gc
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

from psycopg2.extensions import TRANSACTION_STATUS_IDLE, TRANSACTION_STATUS_INTRANS  # noqa: E402

import db_pool  # noqa: E402

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


class FakeInfo:
    def __init__(self):
        self.transaction_status = TRANSACTION_STATUS_IDLE


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, *_args):
        if self.conn.ping_fails:
            raise RuntimeError("connection reset by peer")
        self.conn.pings += 1

    def fetchone(self):
        return (1,)

    def close(self):
        pass


class FakeConnection:
    """Just enough of a psycopg2 connection for the pool to make decisions."""

    def __init__(self):
        self.closed = 0
        self.pings = 0
        self.ping_fails = False
        self.rollbacks = 0
        self.info = FakeInfo()

    def cursor(self):
        return FakeCursor(self)

    def rollback(self):
        self.rollbacks += 1
        self.info.transaction_status = TRANSACTION_STATUS_IDLE

    def close(self):
        self.closed = 1


def fresh_pool():
    """A pool with no history, so counters start at zero."""
    db_pool._reset_for_tests()


def factory_making(created: list):
    def factory():
        conn = FakeConnection()
        created.append(conn)
        return conn
    return factory


# --- Reuse -------------------------------------------------------------------

print("\nReuse")

fresh_pool()
created = []
factory = factory_making(created)

first = db_pool.acquire(factory)
underlying = first._entry.conn
first.close()
second = db_pool.acquire(factory)

check("a closed connection is handed back out, not reopened", second._entry.conn is underlying)
check("only one real connection was opened", len(created) == 1)
check("the counters record one open and one reuse", db_pool.stats()["opened"] == 1 and db_pool.stats()["reused"] == 1)
second.close()

check("attribute access forwards to the real connection", db_pool.acquire(factory).pings >= 0)

# close() must be safe to call twice — plenty of callers do, via a `finally`
# that runs after an explicit close.
fresh_pool()
created = []
conn = db_pool.acquire(factory_making(created))
conn.close()
conn.close()
check("close() twice does not double-release", db_pool.stats()["idle"] == 1)


# --- Session hygiene ---------------------------------------------------------

print("\nSession hygiene")

fresh_pool()
created = []
conn = db_pool.acquire(factory_making(created))
# Simulate a caller that raised part-way through a transaction.
conn._entry.conn.info.transaction_status = TRANSACTION_STATUS_INTRANS
conn.close()
check(
    "an open transaction is rolled back before reuse",
    created[0].rollbacks == 1,
)

fresh_pool()
created = []
conn = db_pool.acquire(factory_making(created))
real = created[0]
real.closed = 1  # the far end went away while it was leased
conn.close()
check("a connection that died while leased is not pooled", db_pool.stats()["idle"] == 0)


# --- Keepalive ---------------------------------------------------------------

print("\nKeepalive")

fresh_pool()
created = []
factory = factory_making(created)
conn = db_pool.acquire(factory)
conn.close()

# Force the idle time past the ping threshold.
entry = db_pool._pool._idle[0]
entry.idle_since -= db_pool.PING_AFTER_SECONDS + 1
conn2 = db_pool.acquire(factory)
check("a long-idle connection is pinged before being handed out", created[0].pings == 1)
check("a healthy ping means the connection is reused", conn2._entry.conn is created[0])
conn2.close()

fresh_pool()
created = []
factory = factory_making(created)
conn = db_pool.acquire(factory)
conn.close()
entry = db_pool._pool._idle[0]
entry.idle_since -= db_pool.PING_AFTER_SECONDS + 1
created[0].ping_fails = True  # the far end is gone
conn2 = db_pool.acquire(factory)
check("a failed ping discards the connection", created[0].closed == 1)
check("and a fresh one is opened in its place", conn2._entry.conn is created[1])
conn2.close()

fresh_pool()
created = []
factory = factory_making(created)
conn = db_pool.acquire(factory)
conn.close()
entry = db_pool._pool._idle[0]
entry.opened_at -= db_pool.MAX_AGE_SECONDS + 1
conn2 = db_pool.acquire(factory)
check("a connection past MAX_AGE is recycled rather than reused", conn2._entry.conn is created[1])
conn2.close()


# --- Credential rotation -----------------------------------------------------

print("\nCredential rotation")

fresh_pool()
created = []
factory = factory_making(created)
conn = db_pool.acquire(factory)
conn.close()
db_pool.invalidate()
check("invalidate() closes idle connections opened under old credentials", created[0].closed == 1)
check("and empties the pool", db_pool.stats()["idle"] == 0)

conn2 = db_pool.acquire(factory)
check("the next acquire opens a fresh connection", conn2._entry.conn is created[1])

# A connection leased ACROSS an invalidation must not go back in the pool: it
# was opened with credentials that are no longer current.
fresh_pool()
created = []
factory = factory_making(created)
leased = db_pool.acquire(factory)
db_pool.invalidate()
leased.close()
check("a connection leased across invalidate() is discarded on release", created[0].closed == 1)
check("and is not pooled", db_pool.stats()["idle"] == 0)


# --- Leak reclamation --------------------------------------------------------

print("\nLeak reclamation")

fresh_pool()
created = []
factory = factory_making(created)


def leak():
    # A caller that never closes — the error path this exists to cover.
    db_pool.acquire(factory)


leak()
gc.collect()
check("a dropped connection is reclaimed by garbage collection", db_pool.stats()["gc_released"] == 1)
check("and returns to the pool rather than leaking", db_pool.stats()["idle"] == 1)
check("the leased count returns to zero", db_pool.stats()["leased"] == 0)


# --- Overflow ----------------------------------------------------------------

print("\nOverflow")

fresh_pool()
created = []
factory = factory_making(created)
held = [db_pool.acquire(factory) for _ in range(db_pool.MAX_SIZE + 2)]
check("the pool never blocks past MAX_SIZE", len(held) == db_pool.MAX_SIZE + 2)
check("the excess is counted as overflow", db_pool.stats()["overflow"] == 2)
for c in held:
    c.close()
check(
    "overflow connections really close instead of growing the pool",
    db_pool.stats()["idle"] <= db_pool.MAX_SIZE,
)


print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
