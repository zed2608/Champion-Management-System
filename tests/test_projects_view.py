"""Drives the REAL ProjectsView save/archive handlers against a throwaway database and records every dialog.
Skipped without a display. Calls the methods the buttons call; it does not synthesise mouse clicks."""
from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.db
TODAY = date.today()


def run(db, sql, params=()):
    with db.transaction() as cur:
        cur.execute(sql, params)
        return cur.lastrowid


def rows(db, sql, params=()):
    with db.read() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


@pytest.fixture
def ui(svc, monkeypatch):
    import customtkinter as ctk
    try:
        root = ctk.CTk()
    except Exception as exc:
        pytest.skip(f"Tk unavailable: {exc}")
    root.geometry("400x300+0+0")
    root.update()
    import database
    import views.projects as vp
    monkeypatch.setattr(vp, "get_connection", database.get_connection)
    d = svc
    admin = run(d, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('ADM-2026-001','Admin','Admin','Active')")
    run(d, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('WKR-2026-001','Wally','Worker','Active')")
    cal = run(d, "INSERT INTO tool (name, tag_id, item_type) VALUES ('Caliper','CAL-001','Equipment')")
    run(d, "INSERT INTO inventory (tool_id, quantity_total, quantity_available) VALUES (%s,10,10)", (cal,))
    shown = []
    for name in ("showinfo", "showerror", "showwarning"):
        monkeypatch.setattr(vp.messagebox, name, lambda title, msg, _n=name, **k: shown.append((_n, title, msg)))
    monkeypatch.setattr(vp.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(vp.ProjectsView, "load_projects", lambda self, *a, **k: None)
    view = vp.ProjectsView(root, {"user_id": admin, "role": "Admin", "full_name": "Admin"})
    yield view, d, cal, shown, vp
    root.destroy()


def fill_form(view, cal, name="Alpha Retool", workers=("WKR-2026-001",), qty=3):
    for entry, text in ((view.p_name, name), (view.p_client, "ACME"), (view.p_head, "Pat"), (view.p_location, "Site A"),
                        (view.p_start, str(TODAY - timedelta(days=1))), (view.p_end, str(TODAY + timedelta(days=20)))):
        entry.delete(0, "end")
        entry.insert(0, text)
    view.p_desc.delete("1.0", "end")
    view.p_desc.insert("1.0", "Retool the line")
    view.workers_list[:] = list(workers)
    view.req_cart[:] = [{"tool_id": cal, "name": "Caliper", "uom": "pcs", "qty": qty, "needs_retrieval": False}]


def test_create_edit_and_duplicate_through_the_real_form(ui):
    view, d, cal, shown, vp = ui
    view.open_draft_project_modal()
    fill_form(view, cal)
    view.save_project()
    assert [m[0] for m in shown] == ["showinfo"] and "drafted & approved" in shown[0][2].lower(), shown
    p = rows(d, "SELECT * FROM projects")[0]
    assert p["status"] == "Approved" and p["approved_by"] is not None                    # auto-approved: no approve step
    assert [r["quantity"] for r in rows(d, "SELECT quantity FROM project_requirements")] == [3]

    # a second project with the same name is refused with a plain message
    shown.clear()
    view.open_draft_project_modal()
    fill_form(view, cal)
    view.save_project()
    assert shown[0][0] == "showerror" and "already exists" in shown[0][2]
    assert rows(d, "SELECT COUNT(*) AS n FROM projects")[0]["n"] == 1

    # edit through the form: the unchanged requirement line is not deleted and re-inserted
    run(d, "UPDATE project_requirements SET status='Fulfilled'")
    shown.clear()
    view.editing_project_id = p["project_id"]
    view.editing_project_status = "Approved"
    fill_form(view, cal, name="Alpha Retool v2")
    view.save_project()
    assert [m[0] for m in shown] == ["showinfo"] and "updated" in shown[0][2].lower(), shown
    assert rows(d, "SELECT name FROM projects")[0]["name"] == "Alpha Retool v2"
    assert rows(d, "SELECT status FROM project_requirements")[0]["status"] == "Fulfilled"      # flag survived the edit


def test_stale_edit_and_archive_rules_show_plain_messages(ui):
    view, d, cal, shown, vp = ui
    view.open_draft_project_modal()
    fill_form(view, cal)
    view.save_project()
    pid = rows(d, "SELECT project_id FROM projects")[0]["project_id"]
    run(d, "UPDATE projects SET status='Ongoing' WHERE project_id=%s", (pid,))                 # someone else started it
    shown.clear()
    view.open_draft_project_modal()                                                              # a successful save closed the form
    view.editing_project_id = pid
    view.editing_project_status = "Approved"                                                    # this screen is stale
    fill_form(view, cal, name="Stale")
    view.save_project()
    assert shown[0][0] == "showerror" and "changed by someone else" in shown[0][2], shown
    assert rows(d, "SELECT name FROM projects")[0]["name"] == "Alpha Retool"

    class Modal:
        destroyed = False
        def destroy(self): Modal.destroyed = True
    shown.clear()
    view.archive_project(pid, "Alpha Retool", Modal(), "Ongoing")                               # only finished projects
    assert shown[0][0] == "showerror" and "Only Completed, Declined or Cancelled" in shown[0][2]
    assert not Modal.destroyed
