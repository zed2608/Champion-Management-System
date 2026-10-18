"""15-minute inactivity logout with a 30-second warning, and the "No" on the logout question must not stop the timers."""
import pytest

from services import session_settings as ss


def test_defaults_are_15_minutes_and_30_seconds(monkeypatch):
    monkeypatch.delenv("CHAMPION_IDLE_MINUTES", raising=False)
    monkeypatch.delenv("CHAMPION_IDLE_WARNING_SECONDS", raising=False)
    assert (ss.idle_minutes(), ss.warning_seconds()) == (15, 30)


@pytest.mark.parametrize("raw,expected", [("20", 20), (" 5 ", 5), ("0", 15), ("-3", 15), ("abc", 15), ("", 15), ("9999", 15), ("1", 1), ("240", 240)])
def test_idle_minutes_is_configurable_but_never_unsafe(monkeypatch, raw, expected):
    monkeypatch.setenv("CHAMPION_IDLE_MINUTES", raw)
    assert ss.idle_minutes() == expected


@pytest.mark.parametrize("raw,expected", [("45", 45), ("2", 30), ("x", 30)])
def test_warning_seconds(monkeypatch, raw, expected):
    monkeypatch.setenv("CHAMPION_IDLE_WARNING_SECONDS", raw)
    assert ss.warning_seconds() == expected


# ---- the real dashboard window --------------------------------------------------------------------------------------------------
pytestmark_db = pytest.mark.db


def run(db, sql, params=()):
    with db.transaction() as cur:
        cur.execute(sql, params)
        return cur.lastrowid


@pytest.fixture
def app(svc, monkeypatch):
    import customtkinter as ctk
    from conftest import make_window
    import database
    import dashboard as dash
    uid = run(svc, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('ADM-2026-001','Admin','Admin','Active')")
    session = {"user_id": uid, "employee_id": "ADM-2026-001", "role": "Admin", "full_name": "Admin", "email": None, "status": "Active"}
    monkeypatch.setattr(dash, "get_connection", database.get_connection)
    monkeypatch.setenv("CHAMPION_IDLE_MINUTES", "15")
    root = make_window(ctk.CTk)
    root.withdraw()
    a = dash.DashboardApp(root, user_info=session)
    clock = {"t": 1000.0}
    monkeypatch.setattr(dash.time, "monotonic", lambda: clock["t"])
    a._last_activity = clock["t"]
    yield a, dash, clock, root
    try:
        a.destroy()
    except Exception:
        pass
    root.destroy()


def pump(widget, ms=60):
    widget.update_idletasks()
    widget.update()


@pytest.mark.db
def test_warning_after_15_minutes_not_before(app):
    a, dash, clock, root = app
    assert a._idle_limit_s == 15 * 60 and a._warn_s == 30
    clock["t"] += 14 * 60 + 59
    a._idle_check()
    assert a._warning_dialog is None
    clock["t"] += 2
    a._idle_check()
    assert a._warning_dialog is not None and a._warning_dialog.winfo_exists()


@pytest.mark.db
def test_activity_resets_the_clock_but_not_while_the_warning_is_open(app):
    a, dash, clock, root = app
    clock["t"] += 14 * 60
    a._on_activity()
    clock["t"] += 14 * 60
    a._idle_check()
    assert a._warning_dialog is None                                  # activity 14 min ago: still fine
    clock["t"] += 2 * 60
    a._idle_check()
    assert a._warning_dialog is not None
    a._on_activity()                                                  # a stray mouse move must not hide the warning or extend the session
    assert a._warning_dialog is not None


@pytest.mark.db
def test_warning_ends_in_logout_after_30_seconds_and_stay_logged_in_cancels(app, monkeypatch):
    a, dash, clock, root = app
    logged = []
    monkeypatch.setattr(a, "_force_logout", lambda: logged.append(1))
    clock["t"] += 15 * 60 + 1
    a._idle_check()
    clock["t"] += 29
    a._warning_check()
    assert not logged
    clock["t"] += 2
    a._warning_check()
    assert logged == [1]
    # second scenario: the person answers in time
    logged.clear()
    clock["t"] += 100
    a._idle_check()
    # (a new warning needs a new idle period)
    clock["t"] += 15 * 60 + 1
    a._warning_dialog = None
    a._idle_check()
    clock["t"] += 10
    a._stay_logged_in()
    assert a._warning_dialog is None
    clock["t"] += 40
    a._warning_check()
    assert not logged


@pytest.mark.db
def test_saying_no_to_logout_keeps_every_timer_running(app, monkeypatch):
    a, dash, clock, root = app
    monkeypatch.setattr(dash.messagebox, "askyesno", lambda *x, **k: False)
    before = (a._idle_job, a.dashboard_refresh_job, getattr(a, "_clock_job", None))
    assert all(before[:2])
    a.confirm_logout()
    after = (a._idle_job, a.dashboard_refresh_job, getattr(a, "_clock_job", None))
    assert after == before                                            # nothing cancelled, so the session still times out and the dashboard refreshes
    assert a.winfo_exists()
    clock["t"] += 15 * 60 + 1
    a._idle_check()
    assert a._warning_dialog is not None                              # and the inactivity logout still works afterwards


@pytest.mark.db
def test_saying_yes_logs_out_and_leaves_no_timers(app, monkeypatch):
    a, dash, clock, root = app
    monkeypatch.setattr(dash.messagebox, "askyesno", lambda *x, **k: True)
    returned = []
    monkeypatch.setattr(a, "_return_to_login", lambda: returned.append(1))
    a.confirm_logout()
    assert returned == [1]
    assert not (a._idle_job or a._warning_job or a.dashboard_refresh_job or a._clock_job)
