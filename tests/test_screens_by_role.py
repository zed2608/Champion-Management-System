"""Every screen builds, and its main load finishes without an error dialog, an error in the log or an exception in a Tk callback,
under a Staff session and under an Admin session. Staff must not get any Admin-only control.

Opens real Tk windows (skipped without a display) and PUMPS the event loop for a moment after each screen is opened, so the worker
threads' results are delivered to the screen the way they are in the real program. Database: a throwaway MySQL only."""
import gc
import logging
import threading
import time

import pytest

pytestmark = pytest.mark.db

ADMIN_PAGES = {"Dashboard": None, "Project Management": "ProjectsView", "Inventory": "InventoryView",
               "Issuance & Retrieval": "IssuanceView", "Tracking & Accountability": "TrackingView", "Reports": "ReportsView",
               "Maintenance": "MaintenanceView", "Role Management": "RoleManagementView", "Help": "HelpView", "Profile": "ProfileView"}
STAFF_PAGES = {k: v for k, v in ADMIN_PAGES.items() if k not in ("Reports", "Maintenance", "Role Management")}
# controls only an Admin may have (the services refuse Staff as well; this is the screen not offering them)
ADMIN_ONLY_TEXT = ("+ Add New Item", "+ Add Project", "🔐 Verify Audit Chain", "⎙ Audit Report PDF")


def run(db, sql, params=()):
    with db.transaction() as cur:
        cur.execute(sql, params)
        return cur.lastrowid


def walk(widget):
    try:
        children = widget.winfo_children()
    except Exception:                                                # a widget the screen destroyed while we were looking
        return
    for child in children:
        yield child
        yield from walk(child)


def texts(widget):
    return [w._text for w in walk(widget) if isinstance(getattr(w, "_text", None), str)]


def pump(root, seconds):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.02)


def settle(root, seconds=6.0):
    """Let every worker thread a screen started finish, THEN collect garbage on the main thread. Destroying a window while a loader thread
    still holds Tk objects makes Python free them on that thread, which crashes the whole interpreter on Windows (0x80000003)."""
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        busy = [t for t in threading.enumerate()
                if t is not threading.main_thread() and t.is_alive() and t.name != "tool-cache-poller"
                and not t.name.startswith(("pydevd", "Thread-pool"))]
        if not busy:
            break
        time.sleep(0.05)
    gc.collect()
    pump(root, 0.25)                                                 # one more beat so results queued by the threads reach the screen


class _Collect(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.records = []

    def emit(self, record):
        self.records.append(record.getMessage())


@pytest.fixture
def world(svc, monkeypatch):
    import customtkinter as ctk
    import tkinter.messagebox as mb
    from conftest import make_window
    from services.errors import get_logger
    d = svc
    admin = run(d, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('ADM-2026-001','Admin','Admin','Active')")
    staff = run(d, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('STF-2026-001','Stacy','Staff','Active')")
    worker = run(d, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('WKR-2026-001','Wally','Worker','Active')")
    tool = run(d, "INSERT INTO tool (name, tag_id, item_type, category, price) VALUES ('Caliper','CAL-001','Equipment','Measuring',900)")
    run(d, "INSERT INTO inventory (tool_id, quantity_total, quantity_available) VALUES (%s,5,5)", (tool,))
    run(d, "INSERT INTO projects (name, client, location, start_date, end_date, status, workers_assigned) "
           "VALUES ('Alpha','ACME','Site A', CURDATE() - INTERVAL 1 DAY, CURDATE() + INTERVAL 20 DAY, 'Approved', 'WKR-2026-001')")
    users = {"Admin": {"user_id": admin, "employee_id": "ADM-2026-001", "role": "Admin", "full_name": "Admin", "email": None, "status": "Active"},
             "Staff": {"user_id": staff, "employee_id": "STF-2026-001", "role": "Staff", "full_name": "Stacy", "email": None, "status": "Active"}}
    dialogs = []
    for name in ("showinfo", "showerror", "showwarning"):
        monkeypatch.setattr(mb, name, lambda title=None, msg=None, _n=name, **k: dialogs.append((_n, title, msg)))
    monkeypatch.setattr(mb, "askyesno", lambda *a, **k: False)
    collector = _Collect()
    get_logger().addHandler(collector)
    root = make_window(ctk.CTk)
    root.geometry("1200x800+0+0")
    callback_errors = []
    root.report_callback_exception = lambda exc, val, tb: callback_errors.append(repr(val))
    yield root, users, dialogs, collector, callback_errors
    get_logger().removeHandler(collector)
    try:
        settle(root)
    except Exception:
        pass
    try:
        root.destroy()
    except Exception:
        pass


@pytest.mark.parametrize("role", ["Admin", "Staff"])
def test_every_screen_builds_and_loads_cleanly(world, role):
    import dashboard as dash
    root, users, dialogs, collector, callback_errors = world
    app = dash.DashboardApp(root, user_info=users[role])
    expected = ADMIN_PAGES if role == "Admin" else STAFF_PAGES
    assert set(expected) - {"Profile"} == set(app.nav_buttons), set(app.nav_buttons)
    seen_texts = {}
    for page, cls in expected.items():
        app.show_frame(page)
        pump(root, 0.2)
        settle(root, 6.0)                                            # worker threads deliver their rows
        frame = app.current_frame
        if cls:
            assert frame.__class__.__name__ == cls, f"{role}/{page}: screen did not build (got {frame.__class__.__name__})"
        seen_texts[page] = texts(frame)
        seen_texts[page] += visit_every_tab(root, frame)             # tabs are built lazily: open each one, as a person would
        settle(root)
        assert not [d for d in dialogs if d[0] == "showerror"], f"{role}/{page}: error dialog {dialogs}"
    assert not callback_errors, callback_errors
    assert not collector.records, collector.records

    # the main load really delivered data, not just an empty frame
    assert any("Caliper" in t for t in texts_for(app, root, "Inventory")), "Inventory did not list the seeded tool"

    all_texts = [t for ts in seen_texts.values() for t in ts]
    if role == "Staff":
        for control in ADMIN_ONLY_TEXT:
            assert control not in all_texts, f"Staff screen offers an Admin-only control: {control}"
        assert not any("ADMIN INSIGHTS" in t for t in seen_texts["Dashboard"])
    else:
        assert "+ Add New Item" in seen_texts["Inventory"] and "+ Add Project" in seen_texts["Project Management"]
        assert "🔐 Verify Audit Chain" in seen_texts["Tracking & Accountability"]
        assert any("ADMIN INSIGHTS" in t for t in seen_texts["Dashboard"])
    settle(root)
    app.destroy()


def visit_every_tab(root, frame):
    """Click through every tab of every segmented tab bar on the screen; return the text found on the screens they open."""
    found = []
    for bar in [w for w in walk(frame) if w.__class__.__name__ == "CTkSegmentedButton"]:
        for value in list(bar._value_list):
            bar.set(value)
            if bar._command:
                bar._command(value)
            pump(root, 0.2)
            settle(root, 6.0)
            found += texts(frame)
    return found


def texts_for(app, root, page):
    app.show_frame(page)
    settle(root, 6.0)
    return texts(app.current_frame)


def test_staff_tracking_shows_only_my_history(world):
    import dashboard as dash
    root, users, dialogs, collector, callback_errors = world
    app = dash.DashboardApp(root, user_info=users["Staff"])
    app.show_frame("Tracking & Accountability")
    settle(root, 6.0)
    assert app.current_frame.is_admin is False
    labels = texts(app.current_frame)
    assert not any("Audit" in t or "Activity" in t for t in labels), labels
    app.destroy()
