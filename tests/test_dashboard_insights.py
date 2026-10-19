"""[PANEL-AWE] Admin dashboard cards: last backup age, audit-chain status, top wear forecasts, top recommendations. Admin only; loaded off the Tk thread."""
import threading
import time
from datetime import datetime, timedelta

import pytest

from services import dashboard_service as ds
from services.errors import PermissionDenied


def texts(result):
    import dashboard
    return dashboard.DashboardApp.insight_texts(result)


# ---- the words on the cards (pure) -----------------------------------------------------------------------------------------------------------------
def test_backup_card_is_green_when_recent_and_red_after_seven_days_or_when_missing():
    when = datetime(2026, 6, 20, 9, 30)
    ok = texts({"backup": {"data": {"last": when, "filename": "x.sql", "age_days": 3.0, "warn": False, "warn_after_days": 7}}})["backup"]
    assert ok == ("OK: 3 days ago (Jun 20, 2026 09:30 AM)", "#1E4528")
    old = texts({"backup": {"data": {"last": when, "filename": "x.sql", "age_days": 9.0, "warn": True, "warn_after_days": 7}}})["backup"]
    assert old[1] == "#D8000C" and "WARNING" in old[0] and "9 days ago" in old[0] and "7 days" in old[0]
    none = texts({"backup": {"data": {"last": None, "filename": None, "age_days": None, "warn": True, "warn_after_days": 7}}})["backup"]
    assert none[1] == "#D8000C" and "No backup" in none[0]


def test_audit_card_states():
    base = {"head_hash": "ab" * 32, "live": 10, "archived": 5, "last_log_id": 15}
    intact = texts({"audit": {"data": {**base, "verified": True, "intact": True, "checked": 15, "first_broken_log_id": None, "reason": ""}}})["audit"]
    assert intact == ("INTACT: 15 entries checked, head abababababab...", "#1E4528")
    broken = texts({"audit": {"data": {**base, "verified": True, "intact": False, "checked": 3, "first_broken_log_id": 4, "reason": "edited"}}})["audit"]
    assert broken == ("BROKEN at entry #4: edited", "#D8000C")
    big = texts({"audit": {"data": {**base, "verified": False, "intact": None, "checked": 0, "first_broken_log_id": None, "reason": ""}}})["audit"]
    assert "15 entries" in big[0] and "Verify" in big[0] and big[1] == "gray"


def test_wear_and_recommendation_cards_list_the_numbers():
    row = {"name": "Drill", "pct_used": 96.0, "interval": 100.0, "days_to_due": 1.3, "flags": ["service due soon"]}
    idle = {"name": "Saw", "pct_used": 10.0, "interval": 500.0, "days_to_due": None, "flags": []}
    wear = texts({"wear": {"data": [row, idle]}})["wear"][0].split("\n")
    assert wear == ["Drill: 96% of 100 h used, due in 1.3 days  [service due soon]", "Saw: 10% of 500 h used, not used lately"]
    recs = texts({"recommendations": {"data": [{"text": "Procure 2 more Drill: blocked 9 times..."}, {"text": "Review project X: 6 of 10 units..."}]}})["recommendations"][0]
    assert recs.split("\n") == ["1. Procure 2 more Drill: blocked 9 times...", "2. Review project X: 6 of 10 units..."]
    assert texts({"wear": {"data": []}, "recommendations": {"data": []}})["recommendations"][0] == "Nothing unusual right now."
    assert texts({"wear": {"error": "boom"}})["wear"] == ("boom", "#D8000C")


# ---- the service ---------------------------------------------------------------------------------------------------------------------------------------
pytestmark_db = pytest.mark.db


def run(db, sql, params=()):
    with db.transaction() as cur:
        cur.execute(sql, params)
        return cur.lastrowid


@pytest.fixture
def world(svc):
    admin = run(svc, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('ADM-2026-001','Admin','Admin','Active')")
    staff = run(svc, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('STF-2026-001','Stacy','Staff','Active')")
    return svc, {"user_id": admin}, {"user_id": staff}


@pytest.mark.db
def test_backup_age_uses_the_newest_successful_backup(world):
    d, admin, staff = world
    from services import backup_service as bs
    assert bs.last_backup_status(admin)["warn"] is True and bs.last_backup_status(admin)["last"] is None
    run(d, "INSERT INTO backup_logs (filename, status, type, created_at) VALUES ('old.sql','Success','Backup', NOW() - INTERVAL 10 DAY)")
    run(d, "INSERT INTO backup_logs (filename, status, type, created_at) VALUES ('failed.sql','Failed','Backup', NOW() - INTERVAL 1 DAY)")
    run(d, "INSERT INTO backup_logs (filename, status, type, created_at) VALUES ('restore.sql','Success','Restore', NOW() - INTERVAL 1 DAY)")
    s = bs.last_backup_status(admin)
    assert s["filename"] == "old.sql" and s["age_days"] == pytest.approx(10, abs=0.1) and s["warn"] is True
    run(d, "INSERT INTO backup_logs (filename, status, type, created_at) VALUES ('new.sql','Success','Backup', NOW() - INTERVAL 2 DAY)")
    s = bs.last_backup_status(admin)
    assert s["filename"] == "new.sql" and s["warn"] is False


@pytest.mark.db
def test_admin_insights_collects_all_four_parts(world):
    d, admin, staff = world
    from services import audit_chain
    audit_chain.record(admin["user_id"], "Viewed", "Test", "one")
    out = ds.admin_insights(admin)
    assert set(out) == {"backup", "audit", "wear", "recommendations"}
    assert all("data" in v for v in out.values()), out
    assert out["audit"]["data"]["verified"] and out["audit"]["data"]["intact"] and out["audit"]["data"]["checked"] >= 1


@pytest.mark.db
def test_one_failing_part_does_not_hide_the_others(world):
    d, admin, staff = world
    with d.transaction() as cur:
        cur.execute("DROP TABLE issuance_attempts")
    out = ds.admin_insights(admin)
    assert "error" in out["recommendations"] and "data" in out["backup"] and "data" in out["audit"] and "data" in out["wear"]
    assert "SELECT" not in out["recommendations"]["error"]                               # a short coded message, not SQL


@pytest.mark.db
def test_staff_may_not_load_the_insights(world):
    d, admin, staff = world
    with pytest.raises(PermissionDenied):
        ds.admin_insights(staff)


# ---- the real dashboard window --------------------------------------------------------------------------------------------------------------------------
def build(svc, role_session, monkeypatch):
    import customtkinter as ctk
    from conftest import make_window
    import database
    import dashboard as dash
    monkeypatch.setattr(dash, "get_connection", database.get_connection)
    root = make_window(ctk.CTk)
    root.withdraw()
    return root, dash.DashboardApp(root, user_info=role_session)


def pump(root, until, timeout=25.0):
    end = time.time() + timeout
    while time.time() < end:
        root.update()
        if until():
            return True
        time.sleep(0.02)
    return until()


@pytest.mark.db
def test_admin_dashboard_shows_the_cards_and_never_waits_for_them(world, monkeypatch):
    d, admin, staff = world
    session = {**admin, "employee_id": "ADM-2026-001", "role": "Admin", "full_name": "Admin", "email": None, "status": "Active"}
    gate = threading.Event()
    real = ds.admin_insights
    seen = {}

    def slow(actor):
        seen["thread"] = threading.current_thread() is not threading.main_thread()
        gate.wait(10)
        return real(actor)
    monkeypatch.setattr(ds, "admin_insights", slow)
    root, app = build(d, session, monkeypatch)
    try:
        assert set(app.ins_labels) == {"backup", "audit", "wear", "recommendations"}
        assert all(l.cget("text") == "Loading..." for l in app.ins_labels.values())       # the dashboard is up although the data is still being computed
        gate.set()
        assert pump(root, lambda: app.ins_labels["backup"].cget("text") != "Loading...")
        assert seen["thread"] is True                                                      # it ran on a worker thread
        assert "No backup" in app.ins_labels["backup"].cget("text")
        assert app.ins_labels["audit"].cget("text").startswith("INTACT")
        assert app.ins_labels["recommendations"].cget("text") == "Nothing unusual right now."
    finally:
        gate.set()
        app.destroy()
        root.destroy()


@pytest.mark.db
def test_staff_dashboard_has_no_admin_cards_and_never_calls_the_service(world, monkeypatch):
    d, admin, staff = world
    session = {**staff, "employee_id": "STF-2026-001", "role": "Staff", "full_name": "Stacy", "email": None, "status": "Active"}
    calls = []
    monkeypatch.setattr(ds, "admin_insights", lambda actor: calls.append(1))
    root, app = build(d, session, monkeypatch)
    try:
        pump(root, lambda: False, timeout=1.0)
        assert not hasattr(app, "ins_labels") and calls == []
    finally:
        app.destroy()
        root.destroy()
