"""[RBAC] The sidebar for Admin and Staff and the read-only Staff Project screen, driving the REAL screens against a throwaway database.
Skipped without a display."""
import pytest

pytestmark = pytest.mark.db


def run(db, sql, params=()):
    with db.transaction() as cur:
        cur.execute(sql, params)
        return cur.lastrowid


def all_buttons(widget):
    out = []
    for child in widget.winfo_children():
        if hasattr(child, "_command") and hasattr(child, "_text"):
            out.append(child)
        out.extend(all_buttons(child))
    return out


def button(widget, text):
    return next((b for b in all_buttons(widget) if b._text == text), None)


@pytest.fixture
def world(svc):
    d = svc
    admin = run(d, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('ADM-2026-001','Admin','Admin','Active')")
    staff = run(d, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('STF-2026-001','Stacy','Staff','Active')")
    admin_s = {"user_id": admin, "employee_id": "ADM-2026-001", "role": "Admin", "full_name": "Admin", "email": None, "status": "Active"}
    staff_s = {"user_id": staff, "employee_id": "STF-2026-001", "role": "Staff", "full_name": "Stacy", "email": None, "status": "Active"}
    return d, admin_s, staff_s                                   # the same keys a real login puts in the session


@pytest.mark.parametrize("role,visible,hidden", [
    ("Admin", ["Dashboard", "Project Management", "Inventory", "Issuance & Retrieval", "Reports", "Maintenance", "Role Management", "Help"], []),
    ("Staff", ["Dashboard", "Project Management", "Inventory", "Issuance & Retrieval", "Help"], ["Reports", "Maintenance", "Role Management"]),
])
def test_sidebar_for_each_role(world, monkeypatch, role, visible, hidden):
    import customtkinter as ctk
    from conftest import make_window
    import database
    import dashboard as dash
    d, admin, staff = world
    monkeypatch.setattr(dash, "get_connection", database.get_connection)
    root = make_window(ctk.CTk)
    root.withdraw()
    try:
        app = dash.DashboardApp(root, user_info=admin if role == "Admin" else staff)
        names = set(app.nav_buttons)
        assert set(visible) <= names and not (set(hidden) & names), names
        assert "Tagging" not in names                            # tag management lives inside Inventory
        shown = []
        monkeypatch.setattr(dash.messagebox, "showerror", lambda title, msg, **k: shown.append((title, msg)))
        app.show_frame("Project Management")
        assert app.current_frame.__class__.__name__ == "ProjectsView"
        if role == "Staff":
            app.show_frame("Reports")                            # hidden AND refused
            assert shown and shown[-1][0] == "Access Denied"
        app.destroy()
    finally:
        root.destroy()


def test_staff_project_screen_is_read_only(world, monkeypatch):
    import customtkinter as ctk
    from conftest import make_window
    import database
    import views.projects as vp
    d, admin, staff = world
    monkeypatch.setattr(vp, "get_connection", database.get_connection)
    monkeypatch.setattr(vp.ProjectsView, "load_projects", lambda self, *a, **k: None)
    root = make_window(ctk.CTk)
    root.geometry("400x300+0+0")
    root.update()
    try:
        assert button(vp.ProjectsView(root, staff), "+ Add Project") is None
        assert button(vp.ProjectsView(root, admin), "+ Add Project") is not None
    finally:
        root.destroy()
