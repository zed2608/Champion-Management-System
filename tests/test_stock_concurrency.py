"""[CONCURRENCY] Two terminals must never be able to issue the same last unit."""
import threading
import time

import mysql.connector
import pytest

from services.stock_ledger import (InsufficientStock, StockError, ToolNotFound, lock_inventory, resolve_maintenance,
                                   return_units, take_stock)

pytestmark = pytest.mark.db


@pytest.fixture
def stock(fresh_db):
    d = fresh_db
    with d.transaction() as cur:
        cur.execute("INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('WKR-2026-001','W','Worker','Active')")
        cur.execute("INSERT INTO tool (name, tag_id) VALUES ('A','AAA-001'), ('B','BBB-001')")
        cur.execute("INSERT INTO inventory (tool_id, quantity_total, quantity_available) VALUES (1, 10, 1), (2, 10, 10)")
    return d


def available(d, tool_id=1):
    with d.read() as cur:
        cur.execute("SELECT quantity_available AS a FROM inventory WHERE tool_id=%s", (tool_id,))
        return cur.fetchone()["a"]


def txn_count(d):
    with d.read() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM `transaction`")
        return cur.fetchone()["n"]


def issue(d, tool_id, qty=1, hold=0.0, uid=1):
    """What issuance_service will do: lock -> re-validate -> guarded decrement -> history, all in one transaction."""
    def work(cur):
        rows = lock_inventory(cur, [tool_id])
        if rows[tool_id]["quantity_available"] < qty:
            raise InsufficientStock(tool_id, qty, rows[tool_id]["quantity_available"])
        if hold:
            time.sleep(hold)                          # widen the race window: the other terminal arrives meanwhile
        take_stock(cur, tool_id, qty)
        cur.execute("INSERT INTO `transaction` (tool_id, user_id, type, status, quantity) VALUES (%s,%s,'Issue','Active',%s)",
                    (tool_id, uid, qty))
    return d.run_in_transaction(work)


def test_last_unit_cannot_be_issued_twice(stock):
    results = {}

    def terminal(name, delay):
        time.sleep(delay)
        try:
            issue(stock, 1, hold=0.6)
            results[name] = "issued"
        except InsufficientStock:
            results[name] = "refused"

    ts = [threading.Thread(target=terminal, args=("A", 0)), threading.Thread(target=terminal, args=("B", 0.15))]
    [t.start() for t in ts]
    [t.join(30) for t in ts]
    assert sorted(results.values()) == ["issued", "refused"], results
    assert available(stock) == 0                      # never negative
    assert txn_count(stock) == 1                      # exactly one issuance was recorded


def test_many_terminals_never_oversell(stock):
    with stock.transaction() as cur:
        cur.execute("UPDATE inventory SET quantity_available = 3 WHERE tool_id = 1")
    outcomes, lock = [], threading.Lock()
    barrier = threading.Barrier(8, timeout=10)

    def terminal():
        barrier.wait()
        try:
            issue(stock, 1)
            r = "issued"
        except InsufficientStock:
            r = "refused"
        with lock:
            outcomes.append(r)

    ts = [threading.Thread(target=terminal) for _ in range(8)]
    [t.start() for t in ts]
    [t.join(60) for t in ts]
    assert outcomes.count("issued") == 3 and outcomes.count("refused") == 5
    assert available(stock) == 0 and txn_count(stock) == 3


def test_opposite_request_orders_cannot_deadlock(stock):
    """Two terminals ask for tools (1,2) and (2,1). lock_inventory always locks in ascending tool_id, so the second
    terminal simply waits for the first: both finish, no deadlock, no retry needed."""
    errors = []

    def terminal(order):
        def work(cur):
            lock_inventory(cur, order)
            time.sleep(0.3)                                   # hold the locks so the other terminal must wait
        try:
            stock.run_in_transaction(work, retries=0)         # retries=0: a deadlock would surface as an error
        except Exception as exc:                              # noqa: BLE001
            errors.append(exc)

    t0 = time.time()
    ts = [threading.Thread(target=terminal, args=([1, 2],)), threading.Thread(target=terminal, args=([2, 1],))]
    [t.start() for t in ts]
    [t.join(30) for t in ts]
    assert not errors, errors
    assert time.time() - t0 >= 0.55, "the two terminals should have been serialised, not run in parallel"


def test_unordered_locking_WOULD_deadlock_which_is_why_the_order_is_fixed(stock):
    """Control experiment: the same two terminals locking in the order they were asked for."""
    barrier, errors = threading.Barrier(2, timeout=10), []

    def terminal(order):
        def work(cur):
            for i, tid in enumerate(order):
                cur.execute("SELECT * FROM inventory WHERE tool_id = %s FOR UPDATE", (tid,))
                cur.fetchall()
                if i == 0:
                    barrier.wait()                             # both now hold their first row
        try:
            stock.run_in_transaction(work, retries=0)
        except mysql.connector.Error as exc:
            errors.append(exc.errno)

    ts = [threading.Thread(target=terminal, args=([1, 2],)), threading.Thread(target=terminal, args=([2, 1],))]
    [t.start() for t in ts]
    [t.join(30) for t in ts]
    assert errors == [1213], errors                            # exactly one victim: MySQL "Deadlock found"


def test_guarded_update_protects_even_without_the_lock(stock):
    with stock.transaction() as cur:
        take_stock(cur, 1, 1)
    with pytest.raises(InsufficientStock) as e:
        with stock.transaction() as cur:
            take_stock(cur, 1, 1)                             # caller "forgot" lock_inventory
    assert e.value.available == 0 and available(stock) == 0


def test_unknown_tool(stock):
    with pytest.raises(ToolNotFound):
        with stock.transaction() as cur:
            lock_inventory(cur, [999])


# ---- unhappy path: the link dies in the middle of a multi-statement write ----------------------------------------
def test_connection_drop_mid_transaction_rolls_everything_back(stock, admin_conn):
    conn_id = {}

    with pytest.raises(mysql.connector.Error):
        with stock.transaction() as cur:
            cur.execute("SELECT CONNECTION_ID() AS id")
            conn_id["id"] = cur.fetchone()["id"]
            lock_inventory(cur, [1])
            take_stock(cur, 1, 1)                                         # statement 1 done
            cur.execute("INSERT INTO `transaction` (tool_id, user_id, type, status, quantity) VALUES (1,1,'Issue','Active',1)")
            kc = admin_conn.cursor()                                      # the LAN cable is pulled / server kills us
            kc.execute(f"KILL CONNECTION {conn_id['id']}")
            kc.close()
            cur.execute("INSERT INTO `transaction` (tool_id, user_id, type, status, quantity) VALUES (1,1,'Issue','Active',1)")
    assert available(stock) == 1, "stock must be unchanged"
    assert txn_count(stock) == 0, "no half-written history"
    assert stock.ping()                                                   # and the pool recovers


def test_error_after_first_statement_rolls_back_stock_too(stock):
    with pytest.raises(mysql.connector.Error):
        with stock.transaction() as cur:
            take_stock(cur, 1, 1)
            cur.execute("INSERT INTO `transaction` (tool_id, user_id, type, quantity) VALUES (1, 999, 'Issue', 1)")   # FK violation
    assert available(stock) == 1 and txn_count(stock) == 0


# ---- per-unit condition model --------------------------------------------------------------------------------------
def inv(d, tool_id=2):
    with d.read() as cur:
        cur.execute("SELECT * FROM inventory WHERE tool_id=%s", (tool_id,))
        return cur.fetchone()


def test_one_damaged_unit_does_not_block_the_others(stock):
    with stock.transaction() as cur:
        take_stock(cur, 2, 3)                                             # 3 of 10 deployed -> 7 available
    with stock.transaction() as cur:
        return_units(cur, 2, good=2, damaged=1)                           # one comes back damaged
    row = inv(stock)
    assert (row["quantity_total"], row["quantity_available"], row["quantity_in_maintenance"]) == (10, 9, 1)
    with stock.transaction() as cur:
        take_stock(cur, 2, 9)                                             # the 9 good units are still issuable


def test_resolving_maintenance_does_not_inflate_stock(stock):
    with stock.transaction() as cur:
        take_stock(cur, 2, 1)
        return_units(cur, 2, damaged=1)
    with stock.transaction() as cur:
        resolve_maintenance(cur, 2, 1, repaired=True)
    row = inv(stock)
    assert (row["quantity_total"], row["quantity_available"], row["quantity_in_maintenance"]) == (10, 10, 0)   # old bug: total became 11


def test_written_off_and_lost_units_leave_the_total_and_lost_is_counted(stock):
    with stock.transaction() as cur:
        take_stock(cur, 2, 2)
        return_units(cur, 2, damaged=1, lost=1)
    with stock.transaction() as cur:
        resolve_maintenance(cur, 2, 1, repaired=False)
    row = inv(stock)
    # 10 owned, 2 deployed. One came back lost (leaves the total, counted in quantity_lost), one damaged then written off.
    assert (row["quantity_total"], row["quantity_available"], row["quantity_in_maintenance"], row["quantity_lost"]) == (8, 8, 0, 1)
    with pytest.raises(StockError):
        with stock.transaction() as cur:
            resolve_maintenance(cur, 2, 1, repaired=True)                 # nothing left in maintenance


def test_fractional_consumables_are_exact(stock):
    with stock.transaction() as cur:
        cur.execute("UPDATE inventory SET quantity_total = 2.5, quantity_available = 2.5 WHERE tool_id = 2")
        take_stock(cur, 2, "0.75")
        take_stock(cur, 2, "0.75")
    assert str(inv(stock)["quantity_available"]) == "1.00"
