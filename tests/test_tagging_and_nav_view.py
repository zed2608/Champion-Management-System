"""[RBAC] Tagging module rules and the sidebar for Admin and Staff, driving the REAL screens against a throwaway database.
Skipped without a display. Calls the methods the buttons call; it does not synthesise mouse clicks."""
import pytest

pytestmark = pytest.mark.db


def run(db, sql, params=()):
    with db.transaction() as cur:
        cur.execute(sql, params)
        return cur.lastrowid


def rows(db, sql, params=()):
    with db.read() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


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
    bare = run(d, "INSERT INTO tool (name, item_type, category, supplier) VALUES ('Saw','Equipment','Cutting','Bosch')")
    tagged = run(d, "INSERT INTO tool (name, tag_id, item_type, category) VALUES ('Caliper','CAL-001','Equipment','Measuring')")
    for t in (bare, tagged):
        run(d, "INSERT INTO inventory (tool_id, quantity_total, quantity_available) VALUES (%s,5,5)", (t,))
    admin_s = {"user_id": admin, "employee_id": "ADM-2026-001", "role": "Admin", "full_name": "Admin", "email": None, "status": "Active"}
    staff_s = {"user_id": staff, "employee_id": "STF-2026-001", "role": "Staff", "full_name": "Stacy", "email": None, "status": "Active"}
    return d, admin_s, staff_s, bare, tagged                                       # the same keys a real login puts in the session


@pytest.fixture
def tag_screen(world, monkeypatch):
    import customtkinter as ctk
    from conftest import make_window
    root = make_window(ctk.CTk)
    root.geometry("400x300+0+0")
    root.update()
    import database
    import views.tagging as vt
    monkeypatch.setattr(vt, "get_connection", database.get_connection)
    shown = []
    for name in ("showinfo", "showerror", "showwarning"):
        monkeypatch.setattr(vt.messagebox, name, lambda title, msg, _n=name, **k: shown.append((_n, title, msg)))
    monkeypatch.setattr(vt.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(vt.TaggingView, "load_tagging_data", lambda self, *a, **k: None)
    yield root, vt, shown, world
    root.destroy()


def data_row(tool_id, name, tag, category="Cutting", supplier="Bosch"):
    return (tool_id, name, "", "", "", "Shelf A", "Good", tag or "Unassigned", category, supplier)


def modal_of(view):
    return [w for w in view.winfo_children() if w.winfo_class() == "Toplevel"][-1]


def test_staff_can_tag_an_untagged_tool_once_but_cannot_change_it_afterwards(tag_screen):
    root, vt, shown, (d, admin, staff, bare, tagged) = tag_screen
    view = vt.TaggingView(root, staff)
    view.open_tag_manager(data_row(bare, "Saw", None))
    m = modal_of(view)
    assert button(m, "↻ Auto-Gen") is not None and button(m, "Save Tag Link to Database") is not None
    assert button(m, "Unlink Current Tag") is None                                   # unlinking is Admin only
    button(m, "↻ Auto-Gen").invoke()
    button(m, "Save Tag Link to Database").invoke()
    assert [x[0] for x in shown] == ["showinfo"], shown
    tag = rows(d, "SELECT tag_id FROM tool WHERE tool_id=%s", (bare,))[0]["tag_id"]
    assert tag == f"TAG-{bare:03d}-CUT-BOS"                                          # generated from category + supplier
    assert button(m, "Tag saved")._state == "disabled"                               # the button now says so and cannot be pressed again
    m.destroy()

    shown.clear()
    view.open_tag_manager(data_row(bare, "Saw", tag))                                # reopened: the tool now has a tag
    m = modal_of(view)
    assert button(m, "↻ Auto-Gen") is None and button(m, "Save Tag Link to Database") is None and button(m, "Unlink Current Tag") is None
    m.destroy()
    # and the service refuses even if the screen were bypassed
    from services import inventory_service as inv
    from services.errors import PermissionDenied
    with pytest.raises(PermissionDenied, match="already has a tag"):
        inv.assign_tag(staff, bare, "SAW-NEW")
    assert rows(d, "SELECT tag_id FROM tool WHERE tool_id=%s", (bare,))[0]["tag_id"] == tag


def test_admin_can_relink_and_unlink(tag_screen):
    root, vt, shown, (d, admin, staff, bare, tagged) = tag_screen
    view = vt.TaggingView(root, admin)
    view.open_tag_manager(data_row(tagged, "Caliper", "CAL-001", "Measuring", ""))
    m = modal_of(view)
    assert button(m, "Save Tag Link to Database") is not None and button(m, "Unlink Current Tag") is not None
    from services import inventory_service as inv
    inv.assign_tag(admin, tagged, "CAL-777")                                          # Admin relink through the service the button calls
    assert rows(d, "SELECT tag_id FROM tool WHERE tool_id=%s", (tagged,))[0]["tag_id"] == "CAL-777"
    button(m, "Unlink Current Tag").invoke()
    assert rows(d, "SELECT tag_id FROM tool WHERE tool_id=%s", (tagged,))[0]["tag_id"] is None
    assert shown[-1][0] == "showinfo" and "Tag removed" in shown[-1][2]
    m.destroy()


def test_auto_generated_tags_always_pass_the_tag_rules(tag_screen):
    root, vt, shown, (d, admin, staff, bare, tagged) = tag_screen
    view = vt.TaggingView(root, admin)
    view.open_tag_manager(data_row(bare, "Odd", None, category="N/A & more", supplier="  "))
    m = modal_of(view)
    button(m, "↻ Auto-Gen").invoke()
    button(m, "Save Tag Link to Database").invoke()
    assert shown[-1][0] == "showinfo", shown                                         # 'N/A & more' had illegal characters: cleaned
    assert rows(d, "SELECT tag_id FROM tool WHERE tool_id=%s", (bare,))[0]["tag_id"] == f"TAG-{bare:03d}-NAM-UNK"
    m.destroy()


@pytest.mark.parametrize("role,visible,hidden", [
    ("Admin", ["Dashboard", "Project Management", "Inventory", "Tagging", "Issuance & Retrieval", "Reports", "Maintenance", "Role Management", "Help"], []),
    ("Staff", ["Dashboard", "Project Management", "Inventory", "Tagging", "Issuance & Retrieval", "Help"], ["Reports", "Maintenance", "Role Management"]),
])
def test_sidebar_for_each_role_and_the_tagging_route(world, monkeypatch, role, visible, hidden):
    import customtkinter as ctk
    from conftest import make_window
    import database
    import dashboard as dash
    d, admin, staff, bare, tagged = world
    monkeypatch.setattr(dash, "get_connection", database.get_connection)
    root = make_window(ctk.CTk)
    root.withdraw()
    errors = []
    root.report_callback_exception = lambda *a: errors.append(a)
    try:
        app = dash.DashboardApp(root, user_info=admin if role == "Admin" else staff)
        names = set(app.nav_buttons)
        assert set(visible) <= names and not (set(hidden) & names), names
        shown = []
        monkeypatch.setattr(dash.messagebox, "showerror", lambda title, msg, **k: shown.append((title, msg)))
        app.show_frame("Tagging")
        assert app.current_frame.__class__.__name__ == "TaggingView"
        app.show_frame("Project Management")
        assert app.current_frame.__class__.__name__ == "ProjectsView"
        if role == "Staff":
            app.show_frame("Reports")                                                # hidden AND refused
            assert shown and shown[-1][0] == "Access Denied"
        app.destroy()
    finally:
        root.destroy()


def test_staff_project_screen_is_read_only(world, monkeypatch):
    import customtkinter as ctk
    from conftest import make_window
    import database
    import views.projects as vp
    d, admin, staff, bare, tagged = world
    monkeypatch.setattr(vp, "get_connection", database.get_connection)
    monkeypatch.setattr(vp.ProjectsView, "load_projects", lambda self, *a, **k: None)
    root = make_window(ctk.CTk)
    root.geometry("400x300+0+0")
    root.update()
    try:
        staff_view = vp.ProjectsView(root, staff)
        assert button(staff_view, "+ Add Project") is None
        admin_view = vp.ProjectsView(root, admin)
        assert button(admin_view, "+ Add Project") is not None
    finally:
        root.destroy()
