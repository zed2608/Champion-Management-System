"""[PANEL-AWE] Tamper-evident audit log: concurrent writers, tamper detection, append-only triggers, archive and backfill."""
import threading

import mysql.connector
import pytest

import database
from db import audit_core, migrate
from services import audit_chain as ac
from services.errors import PermissionDenied

pytestmark = pytest.mark.db


def run(db, sql, params=()):
    with db.transaction() as cur:
        cur.execute(sql, params)
        return cur.lastrowid


def rows(db, sql, params=()):
    with db.read() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def raw(db, sql, params=()):
    """A statement outside the application (no pooling helpers, autocommit)."""
    conn = db.raw_connection()
    cur = conn.cursor()
    try:
        cur.execute("SET SESSION autocommit = 1")
        cur.execute(sql, params)
    finally:
        cur.close()
        conn.close()


def verify(db):
    with db.read() as cur:
        return audit_core.verify(cur)


@pytest.fixture
def admin(svc):
    uid = run(svc, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('ADM-2026-001','Admin','Admin','Active')")
    return {"user_id": uid}


def write(n, user=None, prefix="entry"):
    for i in range(n):
        ac.record(user, "Viewed", "Test", f"{prefix} {i}")


# ---- writing ------------------------------------------------------------------------------------------------------------------------
def test_each_row_links_to_the_one_before(svc):
    write(5)
    got = rows(svc, "SELECT log_id, prev_hash, row_hash FROM system_logs ORDER BY log_id")
    assert len(got) == 5 and got[0]["prev_hash"] == audit_core.GENESIS
    for a, b in zip(got, got[1:]):
        assert b["prev_hash"] == a["row_hash"] and len(b["row_hash"]) == 64
    r = verify(svc)
    assert r["intact"], r["reason"]
    assert r["checked"] == 5 and r["head_hash"] == got[-1]["row_hash"]


def test_known_digest_matches_the_sql_procedure(svc):
    ac.record(None, "Login", "Authentication", "héllo — 日本語", "sess-1")
    r = rows(svc, "SELECT * FROM system_logs")[0]
    with svc.read() as cur:
        cur.execute(f"SELECT {audit_core.TS_UTC_SQL} AS t FROM system_logs")
        ts = cur.fetchone()["t"]
    assert audit_core.row_digest(audit_core.GENESIS, r["log_id"], None, "Login", "Authentication", "héllo — 日本語", ts, "sess-1") == r["row_hash"]


def test_two_terminals_writing_at_once_cannot_fork_the_chain(svc):
    errors = []

    def worker(tag):
        try:
            write(40, prefix=tag)
        except Exception as e:                                   # record() never raises, but be loud if something else does
            errors.append(e)
    threads = [threading.Thread(target=worker, args=(t,)) for t in ("A", "B")]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    got = rows(svc, "SELECT log_id, prev_hash, row_hash FROM system_logs ORDER BY log_id")
    assert len(got) == 80
    assert len({g["prev_hash"] for g in got}) == 80                              # nobody shares a parent: a single line, no fork
    r = verify(svc)
    assert r["intact"] and r["checked"] == 80


# ---- tamper detection ----------------------------------------------------------------------------------------------------------------
def drop_guards(db):
    raw(db, "DROP TRIGGER IF EXISTS trg_system_logs_bu")
    raw(db, "DROP TRIGGER IF EXISTS trg_system_logs_bd")


def test_editing_a_row_is_reported_at_that_row(svc):
    write(6)
    ids = [r["log_id"] for r in rows(svc, "SELECT log_id FROM system_logs ORDER BY log_id")]
    drop_guards(svc)
    raw(svc, "UPDATE system_logs SET details = 'I did not do that' WHERE log_id = %s", (ids[2],))
    r = verify(svc)
    assert not r["intact"] and r["first_broken_log_id"] == ids[2] and "edited" in r["reason"]
    assert r["checked"] == 2


def test_editing_a_row_and_its_hash_is_caught_at_the_next_row(svc):
    write(6)
    ids = [r["log_id"] for r in rows(svc, "SELECT log_id FROM system_logs ORDER BY log_id")]
    drop_guards(svc)
    with svc.read() as cur:
        cur.execute(f"SELECT {audit_core.COLUMNS} FROM system_logs WHERE log_id = %s", (ids[2],))
        r = cur.fetchone()
    forged = audit_core.row_digest(r["prev_hash"], r["log_id"], r["user_id"], r["action_type"], r["module"], "forged", r["ts_utc"], r["session_id"])
    raw(svc, "UPDATE system_logs SET details = 'forged', row_hash = %s WHERE log_id = %s", (forged, ids[2]))
    res = verify(svc)
    assert not res["intact"] and res["first_broken_log_id"] == ids[3]


def test_deleting_a_middle_row_is_reported_at_the_row_after_it(svc):
    write(6)
    ids = [r["log_id"] for r in rows(svc, "SELECT log_id FROM system_logs ORDER BY log_id")]
    drop_guards(svc)
    raw(svc, "DELETE FROM system_logs WHERE log_id = %s", (ids[3],))
    res = verify(svc)
    assert not res["intact"] and res["first_broken_log_id"] == ids[4] and "removed" in res["reason"]


def test_deleting_the_newest_rows_is_caught_by_the_chain_head(svc):
    write(6)
    ids = [r["log_id"] for r in rows(svc, "SELECT log_id FROM system_logs ORDER BY log_id")]
    drop_guards(svc)
    raw(svc, "DELETE FROM system_logs WHERE log_id >= %s", (ids[4],))
    res = verify(svc)
    assert not res["intact"] and "end of the log" in res["reason"] and res["first_broken_log_id"] == ids[3] + 1


def test_a_row_inserted_behind_the_applications_back_is_reported(svc):
    write(3)
    raw(svc, "INSERT INTO system_logs (action_type, module, details) VALUES ('Edited','Sneaky','no hash')")
    res = verify(svc)
    assert not res["intact"] and "outside the application" in res["reason"]


# ---- append-only triggers --------------------------------------------------------------------------------------------------------------
def test_update_and_delete_are_refused_by_the_database(svc):
    write(2)
    for sql in ("UPDATE system_logs SET details = 'x'", "UPDATE system_logs SET row_hash = 'f'", "DELETE FROM system_logs"):
        with pytest.raises(mysql.connector.Error) as e:
            raw(svc, sql)
        assert "append-only" in str(e.value), sql
    assert verify(svc)["intact"]


def test_staff_dashboard_feed_still_works_through_the_view(svc):
    uid = run(svc, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('STF-2026-001','Stacy','Staff','Active')")
    ac.record(uid, "Submitted", "Projects", "Stacy submitted project X")
    ac.record(uid, "Login", "Authentication", "secret")
    feed = rows(svc, "SELECT details FROM v_activity_feed")
    assert [f["details"] for f in feed] == ["Stacy submitted project X"]


# ---- archive -----------------------------------------------------------------------------------------------------------------------------
def test_old_rows_move_to_the_archive_and_the_chain_stays_intact(svc):
    write(30)
    ac.archive_old(keep=10)
    live = rows(svc, "SELECT COUNT(*) AS n FROM system_logs")[0]["n"]
    arch = rows(svc, "SELECT COUNT(*) AS n FROM system_logs_archive")[0]["n"]
    assert (live, arch) == (10, 20)                                             # nothing lost: 30 = 10 + 20
    res = verify(svc)
    assert res["intact"] and res["checked"] == 30
    write(2)                                                                     # new rows still chain onto the head
    assert verify(svc)["checked"] == 32


def test_archive_refuses_edits_and_a_live_row_cannot_be_deleted_unless_archived(svc):
    write(15)
    ac.archive_old(keep=5)
    for sql in ("UPDATE system_logs_archive SET details = 'x'", "DELETE FROM system_logs_archive"):
        with pytest.raises(mysql.connector.Error):
            raw(svc, sql)
    with pytest.raises(mysql.connector.Error):
        raw(svc, "DELETE FROM system_logs")


def test_writing_never_prunes(svc, monkeypatch):
    monkeypatch.setattr(ac, "ARCHIVE_EVERY", 10 ** 9)
    write(25)
    assert rows(svc, "SELECT COUNT(*) AS n FROM system_logs")[0]["n"] == 25


# ---- backfill and migration ---------------------------------------------------------------------------------------------------------------
def test_backfill_chains_existing_rows_once_in_order(svc):
    for i in range(5):
        raw(svc, "INSERT INTO system_logs (user_id, action_type, module, details) VALUES (NULL, 'Viewed', 'Old', %s)", (f"old {i}",))
    assert not verify(svc)["intact"]                                            # raw rows have no hashes yet
    with svc.transaction() as cur:
        assert audit_core.backfill(cur) == 5
    with svc.transaction() as cur:
        assert audit_core.backfill(cur) == 0                                    # running again changes nothing
    assert verify(svc)["intact"] and verify(svc)["checked"] == 5
    write(2)
    assert verify(svc) == {**verify(svc), "intact": True, "checked": 7}


def test_migration_chains_the_logs_of_an_old_database_and_is_safe_to_rerun(legacy_db):
    d = legacy_db
    migrate.run(d, require_backup=False, log=lambda *_: None)
    n1 = rows(d, "SELECT COUNT(*) AS n FROM system_logs")[0]["n"]
    res = verify(d)
    assert res["intact"] and res["checked"] == n1
    assert migrate.run(d, require_backup=False, log=lambda *_: None) == []                  # nothing pending the second time
    head = rows(d, "SELECT head_hash FROM audit_chain_head")[0]["head_hash"]
    assert head == res["head_hash"]


# ---- sessions and permission -------------------------------------------------------------------------------------------------------------------
def test_every_entry_of_a_login_carries_the_same_session_id(svc, admin):
    sid = database.start_session(admin["user_id"])
    try:
        database.log_action(admin["user_id"], "Login", "Authentication", "in")
        database.log_action(admin["user_id"], "Viewed", "Inventory", "looked")
        database.log_action(None, "Denied", "Security", "someone else")           # a different actor does not borrow this session
    finally:
        database.end_session()
    database.log_action(admin["user_id"], "Logout", "Authentication", "out")
    got = rows(svc, "SELECT action_type, session_id FROM system_logs ORDER BY log_id")
    assert [g["session_id"] for g in got] == [sid, sid, None, None]
    assert verify(svc)["intact"]


def test_only_admin_can_verify(svc):
    uid = run(svc, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('STF-2026-001','S','Staff','Active')")
    with pytest.raises(PermissionDenied):
        ac.verify_chain({"user_id": uid})
    with pytest.raises(PermissionDenied):
        ac.chain_status({"user_id": uid})


def test_verify_chain_and_status_for_admin(svc, admin):
    write(4)
    res = ac.verify_chain(admin)
    assert res["intact"] and res["checked"] == 4
    st = ac.chain_status(admin)
    assert st["head_hash"] and st["live"] >= 4 and st["archived"] == 0
    assert any("Audit chain verified" in r["details"] for r in rows(svc, "SELECT details FROM system_logs"))


# ---- screen and printed report ------------------------------------------------------------------------------------------------------------
def pump(root, until, timeout=25.0):
    import time
    end = time.time() + timeout
    while time.time() < end:
        root.update()
        if until():
            return True
        time.sleep(0.01)
    return until()


def test_verify_button_and_pdf_show_the_verdict_and_head_hash(svc, admin, monkeypatch, tmp_path):
    import customtkinter as ctk
    from conftest import make_window
    import views.tracking as vt
    session = {"user_id": admin["user_id"], "employee_id": "ADM-2026-001", "role": "Admin", "full_name": "Admin", "email": None, "status": "Active"}
    write(5, user=admin["user_id"])
    monkeypatch.setattr(vt, "get_connection", database.get_connection)
    root = make_window(ctk.CTk)
    root.geometry("1300x800+0+0")
    try:
        view = vt.TrackingView(root, session)
        view.pack(fill="both", expand=True)
        view.switch_tab("⚙️ Activity Log")
        view.verify_btn.invoke()
        assert pump(root, lambda: "INTACT" in view.chain_lbl.cget("text")), view.chain_lbl.cget("text")
        head = rows(svc, "SELECT head_hash FROM audit_chain_head")[0]["head_hash"]
        # the head moved by one (the 'Verified' entry itself), so compare with a fresh verification
        data = ac.audit_report(admin)
        notes, sections = vt.TrackingView.audit_pdf_sections(data)
        assert "INTACT" in notes[0] and data["verify"]["head_hash"] in sections[0][2][2][1]
        from utils.pdf_table import render_pdf
        out = render_pdf("Audit Trail Report", "x", sections, str(tmp_path / "a.pdf"), notes)
        assert (tmp_path / "a.pdf").stat().st_size > 2000 and out.endswith("a.pdf")
        # tamper, verify again on screen
        drop_guards(svc)
        raw(svc, "UPDATE system_logs SET details = 'forged' WHERE log_id = (SELECT m FROM (SELECT MIN(log_id) AS m FROM system_logs) x)")
        view.verify_btn.invoke()
        assert pump(root, lambda: "BROKEN" in view.chain_lbl.cget("text")), view.chain_lbl.cget("text")
    finally:
        root.destroy()
