"""A connection pool for Lakebase/Postgres, aged for OAuth credentials.

Opening a Lakebase connection is expensive. The TCP, TLS, and auth handshake is
several round trips — roughly 650ms from outside the workspace, tens of
milliseconds from inside it — while the queries an app like this runs take one.
Without pooling, a page that fires a handful of requests spends almost all of
its time connecting.

**Why not `psycopg2.pool` or pgbouncer.** Lakebase passwords are minted OAuth
tokens that expire. `psycopg2.pool` holds one connection string for its
lifetime, so once the token behind it expires, every new connection it opens
fails and the pool has no way to learn. Here each connection records the
*credential generation* it was opened under, and `invalidate()` retires them all
together when credentials are re-resolved.

**The pool never blocks.** Past `LAKEBASE_POOL_MAX_SIZE` it opens an unpooled
connection that really closes on release. A burst degrades to the un-pooled
behaviour instead of deadlocking behind a queue.

**Connections come back even when a caller forgets.** `PooledConnection.close()`
returns the connection rather than closing it, and `__del__` does the same when
the last reference is dropped — so the error path that returns early without a
`close()` still gives its connection back.

Each uvicorn worker holds its own pool, so a deployment's ceiling is
`workers x LAKEBASE_POOL_MAX_SIZE`.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable, Optional

from psycopg2.extensions import TRANSACTION_STATUS_IDLE

logger = logging.getLogger(__name__)

#: Connections one worker may hold at once. Sized for a burst — sync handlers run
#: in a thread pool, so a page's requests arrive genuinely in parallel — while
#: staying well under the instance's connection limit across several workers.
MAX_SIZE = int(os.environ.get("LAKEBASE_POOL_MAX_SIZE", "16"))

#: Idle connections are closed after this long, but never below MIN_IDLE. A hard
#: idle *cap* was tried first and made repeated bursts churn: every page load
#: opened connections above the cap and closed them moments later. A timeout lets
#: a burst's connections stay warm for the next one.
IDLE_TIMEOUT_SECONDS = float(os.environ.get("LAKEBASE_POOL_IDLE_TIMEOUT_SECONDS", "300"))
MIN_IDLE = int(os.environ.get("LAKEBASE_POOL_MIN_IDLE", "2"))

#: Connections are reopened once they reach this age. Postgres authenticates at
#: connect time only, so an expired token does NOT drop a live connection —
#: recycling instead keeps the pool from hoarding sessions that the managed
#: service may decide to terminate on its own.
MAX_AGE_SECONDS = float(os.environ.get("LAKEBASE_POOL_MAX_AGE_SECONDS", "1500"))

#: A connection idle longer than this gets a one-round-trip ping before being
#: handed out. This is the keepalive: the far end can go away without telling us,
#: and discovering that inside a user's request is much worse than here.
PING_AFTER_SECONDS = float(os.environ.get("LAKEBASE_POOL_PING_AFTER_SECONDS", "30"))

_ENABLED = os.environ.get("LAKEBASE_POOL", "1").strip().lower() not in ("0", "false", "no")


class _Entry:
    """A pooled connection plus the bookkeeping that decides its fate."""

    __slots__ = ("conn", "opened_at", "idle_since", "generation")

    def __init__(self, conn: Any, generation: int):
        self.conn = conn
        self.opened_at = time.monotonic()
        self.idle_since = self.opened_at
        self.generation = generation


class PooledConnection:
    """Stands in for a psycopg2 connection, returning it to the pool on close.

    Everything except `close` forwards to the real connection, so callers use
    `cursor()`, `commit()`, and `rollback()` unchanged.
    """

    __slots__ = ("_entry", "_pool", "_pooled", "_released")

    def __init__(self, entry: _Entry, pool: "_Pool", pooled: bool):
        object.__setattr__(self, "_entry", entry)
        object.__setattr__(self, "_pool", pool)
        object.__setattr__(self, "_pooled", pooled)
        object.__setattr__(self, "_released", False)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._entry.conn, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._entry.conn, name, value)

    def close(self) -> None:
        """Return the connection to the pool. Safe to call more than once."""
        self._release(reason="close")

    def _release(self, reason: str) -> None:
        if self._released:
            return
        object.__setattr__(self, "_released", True)
        self._pool.release(self._entry, pooled=self._pooled, reason=reason)

    def __del__(self) -> None:
        # The safety net for call sites that only close on success.
        try:
            self._release(reason="gc")
        except Exception:  # noqa: BLE001 — never raise from a finalizer
            pass

    def __enter__(self) -> "PooledConnection":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


class _Pool:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._idle: list[_Entry] = []
        self._leased = 0
        self._generation = 0
        # Counters, surfaced by /api/health.
        self.opened = 0
        self.reused = 0
        self.discarded = 0
        self.overflow = 0
        self.gc_released = 0

    def acquire(self, factory: Callable[[], Any]) -> PooledConnection:
        self._reap()
        while True:
            with self._lock:
                entry = self._idle.pop() if self._idle else None
                generation = self._generation
                if entry is None:
                    # Count the lease before releasing the lock, or parallel
                    # callers all decide there is room for one more.
                    pooled = self._leased + len(self._idle) < MAX_SIZE
                    self._leased += 1
                    if not pooled:
                        self.overflow += 1
                else:
                    self._leased += 1
                    pooled = True

            if entry is None:
                try:
                    conn = factory()
                except Exception:
                    with self._lock:
                        self._leased -= 1
                    raise
                with self._lock:
                    self.opened += 1
                return PooledConnection(_Entry(conn, generation), self, pooled)

            if self._usable(entry, generation):
                with self._lock:
                    self.reused += 1
                return PooledConnection(entry, self, True)

            # Unusable: drop it and go round again.
            self._discard(entry)
            with self._lock:
                self._leased -= 1

    def _usable(self, entry: _Entry, generation: int) -> bool:
        conn = entry.conn
        if getattr(conn, "closed", 1):
            return False
        # Opened under credentials that have since been replaced.
        if entry.generation != generation:
            return False
        now = time.monotonic()
        if now - entry.opened_at >= MAX_AGE_SECONDS:
            return False
        if now - entry.idle_since < PING_AFTER_SECONDS:
            return True
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            cur.close()
            return True
        except Exception as e:  # noqa: BLE001
            logger.info("Discarding a dead idle connection: %s", e)
            return False

    def release(self, entry: _Entry, pooled: bool, reason: str) -> None:
        with self._lock:
            self._leased -= 1
            generation = self._generation
            if reason == "gc":
                self.gc_released += 1

        if reason == "gc":
            logger.debug("A connection was reclaimed by garbage collection; a caller did not close it.")

        keep = pooled and entry.generation == generation and not getattr(entry.conn, "closed", 1)
        if keep:
            keep = self._reset(entry.conn)
        if not keep:
            self._discard(entry)
            return

        entry.idle_since = time.monotonic()
        with self._lock:
            self._idle.append(entry)
        self._reap()

    def _reap(self) -> None:
        """Close connections that have sat unused, keeping a few warm."""
        if IDLE_TIMEOUT_SECONDS <= 0:
            return
        now = time.monotonic()
        with self._lock:
            # `_idle` is used as a stack, so the front is least recently returned.
            spare = len(self._idle) - MIN_IDLE
            victims = []
            while spare > 0 and self._idle and now - self._idle[0].idle_since >= IDLE_TIMEOUT_SECONDS:
                victims.append(self._idle.pop(0))
                spare -= 1
        for entry in victims:
            self._discard(entry)

    @staticmethod
    def _reset(conn: Any) -> bool:
        """Leave the session clean for the next caller.

        A caller that raised part-way through leaves an open or aborted
        transaction behind, which holds locks and makes the *next* caller's first
        statement fail for no reason it can see.
        """
        try:
            if conn.info.transaction_status != TRANSACTION_STATUS_IDLE:
                conn.rollback()
            return True
        except Exception as e:  # noqa: BLE001
            logger.info("Could not reset a connection: %s", e)
            return False

    def _discard(self, entry: _Entry) -> None:
        with self._lock:
            self.discarded += 1
        try:
            entry.conn.close()
        except Exception:  # noqa: BLE001
            pass

    def invalidate(self) -> None:
        """Retire every connection opened under the current credentials."""
        with self._lock:
            self._generation += 1
            stale, self._idle = self._idle, []
        for entry in stale:
            self._discard(entry)

    def stats(self) -> dict:
        with self._lock:
            return {
                "idle": len(self._idle),
                "leased": self._leased,
                "opened": self.opened,
                "reused": self.reused,
                "discarded": self.discarded,
                "overflow": self.overflow,
                "gc_released": self.gc_released,
            }


_pool = _Pool()


def acquire(factory: Callable[[], Any]) -> Any:
    """Hand out a connection, opening one with `factory` if none is idle."""
    if not _ENABLED:
        return factory()
    return _pool.acquire(factory)


def invalidate() -> None:
    """Retire pooled connections, e.g. after credentials were re-resolved."""
    _pool.invalidate()


def close_all() -> None:
    """Close every idle connection. Called at shutdown."""
    _pool.invalidate()


def stats() -> dict:
    """Counters for /api/health.

    `reused` far above `opened` means the pool is doing its job. A climbing
    `overflow` means bursts exceed MAX_SIZE. A climbing `gc_released` means
    routes are leaking connections instead of closing them — find and fix them,
    since the reclaim only happens whenever CPython gets round to it.
    """
    return _pool.stats()


def _reset_for_tests() -> None:
    """Replace the module-level pool. Used by the tests only."""
    global _pool
    _pool = _Pool()
