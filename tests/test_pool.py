import threading

import mysql.connector
import pytest

from db import DatabaseOffline, PoolExhausted, user_message
from db.pool import Database

pytestmark = pytest.mark.db


def test_session_settings_applied_on_every_checkout(fresh_db):
    for _ in range(3):  # pool_reset_session wipes settings on return; they must be re-applied each time
        with fresh_db.read() as cur:
            cur.execute("SELECT @@time_zone AS tz, @@sql_mode AS m, @@autocommit AS ac")
            row = cur.fetchone()
        assert row["tz"] == "+08:00"
        assert "STRICT_TRANS_TABLES" in row["m"]
        assert row["ac"] == 0


def test_transaction_commits_and_rolls_back(fresh_db):
    with fresh_db.transaction() as cur:
        cur.execute("INSERT INTO system_logs (action_type, module, details) VALUES ('T','T','committed')")
    with pytest.raises(RuntimeError):
        with fresh_db.transaction() as cur:
            cur.execute("INSERT INTO system_logs (action_type, module, details) VALUES ('T','T','rolled back')")
            raise RuntimeError("boom")
    with fresh_db.read() as cur:
        cur.execute("SELECT details FROM system_logs ORDER BY log_id")
        assert [r["details"] for r in cur.fetchall()] == ["committed"]


def test_read_never_persists_writes(fresh_db):
    with fresh_db.read() as cur:
        cur.execute("INSERT INTO system_logs (action_type, module, details) VALUES ('T','T','sneaky')")
    with fresh_db.read() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM system_logs")
        assert cur.fetchone()["n"] == 0


def test_connections_always_returned_even_on_errors_and_unread_results(fresh_db):
    # pool_size is 8: 60 iterations would exhaust it if any path leaked a connection
    for i in range(60):
        try:
            with fresh_db.read() as cur:
                cur.execute("SELECT 1")                      # result deliberately not fetched
                if i % 3 == 0:
                    cur.execute("SELECT * FROM table_that_does_not_exist")
        except mysql.connector.Error:
            pass
        try:
            with fresh_db.transaction() as cur:
                cur.execute("SELECT 1")
                if i % 4 == 0:
                    raise ValueError("x")
        except ValueError:
            pass
    assert fresh_db.ping()


def test_pool_exhaustion_raises_after_wait_window(make_db):
    d = make_db("_exh")
    d.config["pool_size"] = 2
    d.config["pool_wait"] = 0.4
    held = [d.raw_connection(), d.raw_connection()]
    try:
        with pytest.raises(PoolExhausted):
            d.raw_connection()
        assert "busy" in user_message(PoolExhausted()).lower()
    finally:
        for c in held:
            c.close()
    d.raw_connection().close()      # recovers once connections are returned


def test_reconnects_after_server_drops_the_connection(fresh_db, admin_conn):
    conn = fresh_db.raw_connection()
    cur = conn.cursor()
    cur.execute("SELECT CONNECTION_ID()")
    cid = cur.fetchone()[0]
    cur.close()
    conn.close()                                   # back in the pool
    kc = admin_conn.cursor()
    kc.execute(f"KILL CONNECTION {cid}")
    kc.close()
    with fresh_db.read() as c:                     # checkout pings and reconnects transparently
        c.execute("SELECT 1 AS ok")
        assert c.fetchone()["ok"] == 1


def test_deadlock_is_retried_once(fresh_db):
    with fresh_db.transaction() as cur:
        cur.execute("CREATE TABLE IF NOT EXISTS t_dead (id INT PRIMARY KEY, v INT NOT NULL)")
        cur.execute("INSERT INTO t_dead VALUES (1,0),(2,0)")
    barrier = threading.Barrier(2, timeout=10)
    attempts, errors = [], []

    def worker(first, second):
        n = {"i": 0}

        def work(cur):
            n["i"] += 1
            cur.execute("UPDATE t_dead SET v = v + 1 WHERE id = %s", (first,))
            if n["i"] == 1:
                barrier.wait()                     # both hold their first lock before asking for the second
            cur.execute("UPDATE t_dead SET v = v + 1 WHERE id = %s", (second,))
        try:
            fresh_db.run_in_transaction(work, retries=1)
        except Exception as exc:                   # noqa: BLE001
            errors.append(exc)
        attempts.append(n["i"])

    ts = [threading.Thread(target=worker, args=(1, 2)), threading.Thread(target=worker, args=(2, 1))]
    [t.start() for t in ts]
    [t.join(30) for t in ts]
    assert not errors, errors
    assert sorted(attempts) == [1, 2]              # exactly one transaction was the deadlock victim and ran again
    with fresh_db.read() as cur:
        cur.execute("SELECT id, v FROM t_dead ORDER BY id")
        assert [r["v"] for r in cur.fetchall()] == [2, 2]   # nothing lost, nothing doubled


def test_offline_server_raises_safe_error_and_notifies(admin_conn):
    cfg = {"host": "127.0.0.1", "port": 1, "user": "x", "password": "secret-should-never-leak", "database": "x",
           "pool_size": 2, "connection_timeout": 1, "pool_wait": 0.2}
    d = Database(cfg, pool_name="offline_t")
    seen = []
    d.add_status_listener(seen.append)
    with pytest.raises(DatabaseOffline) as e:
        d.raw_connection()
    assert d.online is False and seen == [False]
    msg = user_message(e.value)
    assert "Nothing was saved" in msg
    for leak in ("127.0.0.1", "secret-should-never-leak", "2003", "HY000"):
        assert leak not in msg
    assert d.ping() is False
