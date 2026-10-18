"""Thread-safe MySQL connection pool and transaction helpers.

Usage::

    from db import db
    with db.read() as cur:                 # read-only, always returns the connection
        cur.execute("SELECT ...")
        rows = cur.fetchall()
    with db.transaction() as cur:          # COMMIT on success, ROLLBACK on any exception
        cur.execute("UPDATE ...")
    db.run_in_transaction(fn)              # same, but re-runs fn ONCE on deadlock (1213) / lock timeout (1205)

[CONCURRENCY] Design notes (the panel will ask):
  * One lazily created pool per Database object, guarded by a lock, so two threads cannot create two pools.
  * Every checkout pings (reconnecting if the server dropped us) and re-applies the session settings,
    because ``pool_reset_session=True`` wipes session variables each time a connection is returned.
  * autocommit is OFF: nothing is written unless a transaction block finishes cleanly.
  * Session time zone is fixed to +08:00 and sql_mode is STRICT, so timestamps and bad data behave the same
    on every terminal and the old hard-coded ``DATE_ADD(..., INTERVAL 8 HOUR)`` hacks are not needed.
"""
import os
import random
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv
from mysql.connector import errors as mysql_errors
from mysql.connector import pooling

from db.errors import (DatabaseOffline, PoolExhausted, is_connection_error,
                       is_retryable)

SESSION_TIME_ZONE = "+08:00"
STRICT_SQL_MODE = ("STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,"
                   "ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION")
_SESSION_SQL = f"SET SESSION time_zone='{SESSION_TIME_ZONE}', SESSION sql_mode='{STRICT_SQL_MODE}'"

_MAX_POOL = 32  # mysql-connector hard limit


def _load_env():
    """Load .env from the project root (or next to the .exe) regardless of the working directory."""
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    load_dotenv(base / ".env", override=False)


def config_from_env(prefix: str = "DB_") -> dict:
    """Read connection settings from environment variables. Values are never logged."""
    _load_env()
    g = lambda k, d=None: os.getenv(prefix + k, d)
    return {
        "host": g("HOST", "localhost"),
        "port": int(g("PORT") or 3306),
        "user": g("USER", "root"),
        "password": g("PASS", ""),
        "database": g("NAME", "champion_db"),
        "pool_size": max(1, min(int(g("POOL_SIZE") or 16), _MAX_POOL)),
        "connection_timeout": int(g("CONNECT_TIMEOUT") or 5),
        "pool_wait": float(g("POOL_WAIT") or 5),
    }


class Database:
    def __init__(self, config: dict | None = None, pool_name: str = "champion_pool"):
        self._config = dict(config) if config else None
        self._pool_name = pool_name
        self._pool = None
        self._lock = threading.Lock()
        self._online = None            # None = unknown yet
        self._listeners = []
        self.last_error = None         # last driver error (internal; use db.errors.user_message for UI)

    # ---- configuration / status -------------------------------------------------
    @property
    def config(self) -> dict:
        if self._config is None:
            self._config = config_from_env()
        return self._config

    @property
    def online(self):
        return self._online

    def add_status_listener(self, callback):
        """callback(online: bool). Called from whichever thread noticed the change:
        a Tk UI must hand it to the main thread with ``widget.after(0, ...)``."""
        self._listeners.append(callback)

    def _set_online(self, online: bool, exc: BaseException | None = None):
        self.last_error = None if online else exc
        if online != self._online:
            self._online = online
            for cb in list(self._listeners):
                try:
                    cb(online)
                except Exception:
                    pass

    # ---- pool -------------------------------------------------------------------
    def _get_pool(self):
        if self._pool is not None:
            return self._pool
        with self._lock:
            if self._pool is None:  # double-checked: another thread may have built it
                c = self.config
                self._pool = pooling.MySQLConnectionPool(
                    pool_name=self._pool_name,
                    pool_size=c["pool_size"],
                    pool_reset_session=True,
                    host=c["host"], port=c["port"], user=c["user"], password=c["password"],
                    database=c["database"],
                    connection_timeout=c["connection_timeout"],
                    autocommit=False,
                )
        return self._pool

    def close(self):
        """Drop every pooled connection (tests, app exit, or after a config change)."""
        with self._lock:
            pool, self._pool = self._pool, None
        if pool is not None:
            try:
                pool._remove_connections()
            except Exception:
                pass

    def raw_connection(self):
        """Checked-out, pinged, session-configured connection. Caller MUST ``close()`` it.
        Prefer ``read()`` / ``transaction()``; this exists for legacy code paths."""
        c = self.config
        deadline = time.monotonic() + c["pool_wait"]
        delay = 0.05
        while True:
            try:
                pool = self._get_pool()
            except mysql_errors.Error as exc:       # cannot even open the first connection
                self._set_online(False, exc)
                raise DatabaseOffline(str(exc)) from exc
            try:
                conn = pool.get_connection()
            except mysql_errors.PoolError as exc:    # all connections busy
                if time.monotonic() >= deadline:
                    raise PoolExhausted("connection pool exhausted") from exc
                time.sleep(delay)
                delay = min(delay * 2, 0.5)
                continue
            except mysql_errors.Error as exc:
                self._set_online(False, exc)
                raise DatabaseOffline(str(exc)) from exc
            try:
                conn.ping(reconnect=True, attempts=2, delay=1)
                cur = conn.cursor()
                cur.execute(_SESSION_SQL)
                cur.close()
                conn.autocommit = False
            except mysql_errors.Error as exc:
                try:
                    conn.close()
                except Exception:
                    pass
                self._set_online(False, exc)
                raise DatabaseOffline(str(exc)) from exc
            self._set_online(True)
            return conn

    # ---- context managers ---------------------------------------------------------
    @contextmanager
    def read(self, dictionary: bool = True):
        """Cursor for SELECTs. Anything written inside is rolled back, and the connection is always returned."""
        conn = self.raw_connection()
        try:
            cur = conn.cursor(dictionary=dictionary, buffered=True)  # buffered: an unread result can never break cursor.close()
            try:
                yield cur
            finally:
                cur.close()
        finally:
            try:
                conn.rollback()      # ends the snapshot so a long-lived view cannot read stale data
            except Exception:
                pass
            conn.close()

    @contextmanager
    def transaction(self, dictionary: bool = True, isolation_level: str | None = None):
        """One ACID unit of work: COMMIT if the block finishes, ROLLBACK on any exception (incl. KeyboardInterrupt)."""
        conn = self.raw_connection()
        try:
            conn.start_transaction(isolation_level=isolation_level)
            cur = conn.cursor(dictionary=dictionary, buffered=True)  # buffered: an unread result can never break cursor.close()
            try:
                yield cur
                conn.commit()
            except BaseException as exc:
                try:
                    conn.rollback()   # [UNHAPPY-PATH] on a dropped link the server rolls back by itself
                except Exception:
                    pass
                if is_connection_error(exc):
                    self._set_online(False, exc)
                raise
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def run_in_transaction(self, fn, *, retries: int = 1, dictionary: bool = True):
        """Run ``fn(cursor)`` in a transaction; on deadlock (1213) or lock-wait timeout (1205) rerun it up to
        ``retries`` times. ``fn`` must therefore be safe to run again from the top (no side effects outside the DB)."""
        attempt = 0
        while True:
            try:
                with self.transaction(dictionary=dictionary) as cur:
                    return fn(cur)
            except mysql_errors.Error as exc:
                if is_retryable(exc) and attempt < retries:
                    attempt += 1
                    time.sleep(0.05 * attempt + random.random() * 0.1)
                    continue
                raise

    def ping(self) -> bool:
        try:
            with self.read() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            return True
        except (DatabaseOffline, PoolExhausted, mysql_errors.Error):
            return False


# Process-wide instance used by the application. Tests build their own ``Database(config)``.
db = Database()
