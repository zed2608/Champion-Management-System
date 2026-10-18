"""Drives the REAL Maintenance and Inventory screen handlers against a throwaway database and records every dialog.
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


@pytest.fixture
def ui(svc, monkeypatch):
    import customtkinter as ctk
    from conftest import make_window
    root = make_window(ctk.CTk)
    root.geometry("400x300+0+0")
    root.update()
    import database
    import views.inventory as vi
    import views.maintenance as vm
    for mod in (vi, vm):
        monkeypatch.setattr(mod, "get_connection", database.get_connection)
    d = svc
    admin = run(d, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('ADM-2026-001','Admin','Admin','Active')")
    run(d, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('STF-2026-001','Stacy','Staff','Active')")
    cal = run(d, "INSERT INTO tool (name, tag_id, item_type, category) VALUES ('Caliper','CAL-001','Equipment','Measuring')")
    run(d, "INSERT INTO inventory (tool_id, quantity_total, quantity_available) VALUES (%s,10,10)", (cal,))
    shown = []
    for mod in (vi, vm):
        for name in ("showinfo", "showerror", "showwarning"):
            monkeypatch.setattr(mod.messagebox, name, lambda title, msg, _n=name, **k: shown.append((_n, title, msg)))
        monkeypatch.setattr(mod.messagebox, "askyesno", lambda *a, **k: True)
    for cls in (vi.InventoryView, vm.MaintenanceView):
        for meth in ("load_inventory_data", "load_issues", "load_archived_tools", "load_archived_employees", "load_archived_projects"):
            if hasattr(cls, meth):
                monkeypatch.setattr(cls, meth, lambda self, *a, **k: None)      # their worker threads need a running mainloop
    info = {"user_id": admin, "role": "Admin", "full_name": "Admin"}
    yield root, d, info, cal, shown, vi, vm
    root.destroy()


def fill(entry, text):
    entry.delete(0, "end")
    entry.insert(0, text)


def test_maintenance_flag_and_restore_through_the_real_screen(ui):
    root, d, info, cal, shown, vi, vm = ui
    view = vm.MaintenanceView(root, info)
    fill(view.flag_tool_id, "CAL-001")
    fill(view.flag_reported_by, "STF-2026-001")
    view.flag_condition.set("Damaged")
    fill(view.flag_qty, "2")
    fill(view.flag_notes, "Dropped on concrete")
    view.submit_flag()
    assert [m[0] for m in shown] == ["showinfo"] and "2 unit(s) were taken out" in shown[0][2], shown
    i = rows(d, "SELECT * FROM inventory")[0]
    assert (i["quantity_available"], i["quantity_in_maintenance"]) == (8, 2)
    assert view.flag_qty.get() == "1"                                          # form resets

    shown.clear()
    fill(view.flag_tool_id, "CAL-001"); fill(view.flag_reported_by, "x"); fill(view.flag_qty, "99")
    view.submit_flag()                                                         # more than are in stock
    assert shown[0][0] == "showerror" and "stock" in shown[0][2].lower() and "Traceback" not in shown[0][2]



def test_inventory_add_and_archive_rules_through_the_real_screen(ui):
    root, d, info, cal, shown, vi, vm = ui
    view = vi.InventoryView(root, info)
    view.open_add_item_modal()
    view.type_menu.set("Equipment"); view.uom_menu.set("pcs")
    view.cat_menu.set("Measuring"); view.sup_menu.set("Type or select...")
    fill(view.name_entry, "Micrometer"); fill(view.price_entry, "3500"); fill(view.qty_entry, "2.5")
    view.validate_and_save()
    assert shown[-1][0] == "showerror" and "whole" in shown[-1][2]                       # equipment must be whole units
    assert rows(d, "SELECT COUNT(*) AS n FROM tool WHERE name='Micrometer'")[0]["n"] == 0

    shown.clear()
    fill(view.qty_entry, "4")
    view.validate_and_save()
    assert [m[0] for m in shown] == ["showinfo"], shown
    t = rows(d, "SELECT t.tool_id, i.quantity_total FROM tool t JOIN inventory i USING (tool_id) WHERE t.name='Micrometer'")
    assert len(t) == 1 and t[0]["quantity_total"] == 4

    # archive refused while a unit is in maintenance, with a plain sentence
    from services import maintenance_service as mnt
    mnt.flag_tool(info, "CAL-001", "x", "Damaged", "chipped", 1)
    shown.clear()
    view.open_tool_modal(cal)
    modal = [w for w in view.winfo_children() if w.winfo_class() == "Toplevel"][-1]
    buttons = []

    def walk(w):
        for c in w.winfo_children():
            if c.winfo_class() in ("Button",) or hasattr(c, "_command"):
                buttons.append(c)
            walk(c)
    walk(modal)
    archive_btn = next(b for b in buttons if getattr(b, "_text", "") == "Archive")
    archive_btn.invoke()
    assert shown and shown[-1][0] == "showerror" and "in maintenance" in shown[-1][2], shown
    assert rows(d, "SELECT is_archived FROM tool WHERE tool_id=%s", (cal,))[0]["is_archived"] == 0
    modal.destroy()
