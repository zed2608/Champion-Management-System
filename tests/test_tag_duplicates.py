"""A tag that another tool already owns must be refused in plain words, and NOTHING may change, both on Inventory > Update and on
Save Tag Link. Drives the real Inventory modal handlers (the methods the buttons call) against a throwaway database."""
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


def walk(widget):
    for child in widget.winfo_children():
        yield child
        yield from walk(child)


def entry_with(modal, text):
    return next(w for w in walk(modal) if w.winfo_class() == "Entry" and w.get() == text)


def button(modal, text):
    return next(w for w in walk(modal) if getattr(w, "_text", None) == text)


def snapshot(d):
    return (rows(d, "SELECT tool_id, name, tag_id, price FROM tool ORDER BY tool_id"),
            rows(d, "SELECT tool_id, quantity_total, quantity_available FROM inventory ORDER BY tool_id"))


@pytest.fixture
def world(svc, monkeypatch):
    import customtkinter as ctk
    from conftest import make_window
    import database
    import views.inventory as vi
    root = make_window(ctk.CTk)
    root.geometry("400x300+0+0")
    root.update()
    monkeypatch.setattr(vi, "get_connection", database.get_connection)
    monkeypatch.setattr(vi.InventoryView, "load_inventory_data", lambda self, *a, **k: None)
    d = svc
    admin = run(d, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('ADM-2026-001','Admin','Admin','Active')")
    staff = run(d, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('STF-2026-001','Stacy','Staff','Active')")
    cal = run(d, "INSERT INTO tool (name, tag_id, item_type, category) VALUES ('Caliper','CAL-001','Equipment','Measuring')")
    ham = run(d, "INSERT INTO tool (name, tag_id, item_type, category) VALUES ('Hammer','HAM-002','Equipment','Hand')")
    bare = run(d, "INSERT INTO tool (name, item_type, category) VALUES ('Chisel','Equipment','Hand')")
    for t in (cal, ham, bare):
        run(d, "INSERT INTO inventory (tool_id, quantity_total, quantity_available) VALUES (%s,5,5)", (t,))
    shown = []
    for name in ("showinfo", "showerror", "showwarning"):
        monkeypatch.setattr(vi.messagebox, name, lambda title, msg, _n=name, **k: shown.append((_n, title, msg)))
    monkeypatch.setattr(vi.messagebox, "askyesno", lambda *a, **k: True)
    ids = {"admin": admin, "staff": staff, "cal": cal, "ham": ham, "bare": bare}
    yield root, d, vi, ids, shown
    root.destroy()


def open_modal(vi, root, info, tool_id):
    view = vi.InventoryView(root, info)
    view.open_tool_modal(tool_id)
    modal = [w for w in view.winfo_children() if w.winfo_class() == "Toplevel"][-1]
    return view, modal


def test_update_with_a_tag_another_tool_has_is_refused_and_nothing_changes(world):
    root, d, vi, ids, shown = world
    view, modal = open_modal(vi, root, {"user_id": ids["admin"], "role": "Admin", "full_name": "Admin"}, ids["ham"])
    before = snapshot(d)
    tag, name = entry_with(modal, "HAM-002"), entry_with(modal, "Hammer")
    name.delete(0, "end")                                            # also change the name, to prove the whole save is rolled back
    name.insert(0, "Hammer Renamed")
    tag.delete(0, "end")
    tag.insert(0, "cal-001")                                         # lower case on purpose: the match must not depend on case
    button(modal, "Update").invoke()
    kinds = [m for m in shown if m[0] == "showerror"]
    assert kinds and "already used by another tool" in kinds[-1][2], shown
    assert "Traceback" not in kinds[-1][2] and "1062" not in kinds[-1][2]
    assert snapshot(d) == before
    modal.destroy()


def test_save_tag_link_with_a_tag_another_tool_has_is_refused_for_admin(world):
    root, d, vi, ids, shown = world
    view, modal = open_modal(vi, root, {"user_id": ids["admin"], "role": "Admin", "full_name": "Admin"}, ids["ham"])
    before = snapshot(d)
    tag = entry_with(modal, "HAM-002")
    tag.delete(0, "end")
    tag.insert(0, "CAL-001")
    button(modal, "Save Tag Link").invoke()
    errs = [m for m in shown if m[0] == "showerror"]
    assert errs and errs[-1][1] == "Tag not saved" and "already used by another tool" in errs[-1][2], shown
    assert not [m for m in shown if m[0] == "showinfo"]             # no "Tag successfully linked" message
    assert snapshot(d) == before
    modal.destroy()


def test_save_tag_link_with_a_tag_another_tool_has_is_refused_for_staff(world):
    root, d, vi, ids, shown = world
    view, modal = open_modal(vi, root, {"user_id": ids["staff"], "role": "Staff", "full_name": "Stacy"}, ids["bare"])
    before = snapshot(d)
    tag = next(w for w in walk(modal) if w.winfo_class() == "Entry" and w.get() == "" and str(w.cget("state")) == "normal")
    tag.insert(0, "HAM-002")
    button(modal, "Save Tag Link").invoke()
    errs = [m for m in shown if m[0] == "showerror"]
    assert errs and "already used by another tool" in errs[-1][2], shown
    assert snapshot(d) == before
    modal.destroy()


def test_services_refuse_the_same_way_without_any_screen(svc):
    from services import inventory_service as inv
    from services.errors import Conflict
    d = svc
    admin = {"user_id": run(d, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('ADM-2026-001','Admin','Admin','Active')"),
             "role": "Admin"}
    a = run(d, "INSERT INTO tool (name, tag_id, item_type) VALUES ('A','AAA-001','Equipment')")
    b = run(d, "INSERT INTO tool (name, tag_id, item_type) VALUES ('B','BBB-002','Equipment')")
    for t in (a, b):
        run(d, "INSERT INTO inventory (tool_id, quantity_total, quantity_available) VALUES (%s,5,5)", (t,))
    before = snapshot(d)
    with pytest.raises(Conflict, match="already used"):
        inv.assign_tag(admin, b, "aaa-001")
    with pytest.raises(Conflict, match="already used"):
        inv.update_item(admin, b, name="B", category="Hand", supplier="Acme", description="d", location="Shelf", item_type="Equipment",
                        unit_of_measure="pcs", price="0", quantity="5", min_stock="0", tag_id="AAA-001")
    assert snapshot(d) == before
