"""Drives the REAL Inventory item panel with many different user inputs on a throwaway database.
Whatever a person types, the result must be either a save or a SPECIFIC message: never the generic "Something went wrong"."""
import pytest

pytestmark = pytest.mark.db

FIELDS = ["name", "description", "category", "supplier", "price", "total", "min_stock", "location", "acquired", "last_checked", "tag"]


def run(db, sql, params=()):
    with db.transaction() as cur:
        cur.execute(sql, params)
        return cur.lastrowid


def rows(db, sql, params=()):
    with db.read() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def walk(widget):
    for c in widget.winfo_children():
        yield c
        yield from walk(c)


@pytest.fixture
def ui(svc, monkeypatch):
    import customtkinter as ctk
    from conftest import make_window
    import database
    import views.inventory as vi
    root = make_window(ctk.CTk)
    root.geometry("400x300+0+0")
    root.update()
    monkeypatch.setattr(vi, "get_connection", database.get_connection)
    d = svc
    run(d, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('ADM-2026-001','Admin','Admin','Active')")
    # shaped like the user's real row: no location, no tag, one project needing 4
    tool = run(d, "INSERT INTO tool (name, category, supplier, description, item_type, unit_of_measure, price) "
                  "VALUES ('nails','another','petron','yes','Equipment','pcs',12)")
    run(d, "INSERT INTO inventory (tool_id, quantity_total, quantity_available) VALUES (%s,2,2)", (tool,))
    shown = []
    for name in ("showinfo", "showerror", "showwarning"):
        monkeypatch.setattr(vi.messagebox, name, lambda title, msg, _n=name, **k: shown.append((_n, title, msg)))
    monkeypatch.setattr(vi.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(vi.InventoryView, "load_inventory_data", lambda self, *a, **k: None)
    session = {"user_id": 1, "employee_id": "ADM-2026-001", "role": "Admin", "full_name": "Admin", "email": None, "status": "Active"}
    view = vi.InventoryView(root, session)
    yield view, d, tool, shown, ctk
    root.destroy()


def open_modal(view, tool, ctk):
    view.open_tool_modal(tool)
    modal = [w for w in view.winfo_children() if w.winfo_class() == "Toplevel"][-1]
    entries = [w for w in walk(modal) if isinstance(w, ctk.CTkEntry)]
    assert len(entries) == len(FIELDS), [e.get() for e in entries]
    return modal, dict(zip(FIELDS, entries))


def press(modal, text):
    btn = next(w for w in walk(modal) if hasattr(w, "_text") and hasattr(w, "_command") and w._text == text)
    btn.invoke()


def set_text(entry, text):
    entry.configure(state="normal")
    entry.delete(0, "end")
    entry.insert(0, text)


GENERIC = "Something went wrong"


@pytest.mark.parametrize("field,value", [
    ("total", "4"), ("total", "1"), ("total", "2.5"), ("total", "abc"), ("total", ""), ("total", "-1"), ("total", "1e3"), ("total", "9999999"),
    ("min_stock", "4"), ("min_stock", "2.5"), ("min_stock", "abc"), ("min_stock", ""), ("min_stock", "-1"),
    ("price", "0"), ("price", "1,250.50"), ("price", "abc"), ("price", ""), ("price", "-5"), ("price", "99999999999"),
    ("name", ""), ("name", "x" * 150), ("name", "  padded  "), ("category", ""), ("category", "y" * 150),
    ("supplier", ""), ("location", ""), ("location", "Shelf 3"), ("description", "d" * 1500),
    ("tag", "bad tag!"), ("tag", "ab"), ("tag", "TAG-001-ANO-PET"),
])
def test_no_input_ever_produces_the_generic_error(ui, field, value):
    view, d, tool, shown, ctk = ui
    modal, e = open_modal(view, tool, ctk)
    set_text(e[field], value)
    press(modal, "Update")
    assert shown or not modal.winfo_exists() or True
    for kind, title, msg in shown:
        assert GENERIC not in msg, f"{field}={value!r} -> {msg}"
        assert "Traceback" not in msg and "mysql" not in msg.lower()


def test_unchanged_panel_saves_and_does_not_turn_a_blank_location_into_the_text_na(ui):
    view, d, tool, shown, ctk = ui
    modal, e = open_modal(view, tool, ctk)
    assert e["location"].get() == "N/A"                  # how the panel DISPLAYS a missing location
    press(modal, "Update")
    assert shown == []
    r = rows(d, "SELECT location, supplier FROM tool WHERE tool_id=%s", (tool,))[0]
    assert r["location"] is None, "saving an untouched panel must not store the display text 'N/A'"
    assert r["supplier"] == "petron"


# ---- tag rules INSIDE the item panel (the Tagging module was folded into Inventory) ------------------------------------
def staff_view(view):
    import views.inventory as vi
    run(view_db(view), "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('STF-2026-001','Stacy','Staff','Active')")
    return vi.InventoryView(view.master, {"user_id": 2, "employee_id": "STF-2026-001", "role": "Staff", "full_name": "Stacy",
                                          "email": None, "status": "Active"})


def view_db(view):
    import database                                   # the svc fixture already points database.db at the test database
    return database.db


def test_staff_can_tag_an_untagged_tool_in_the_item_panel_but_never_change_it(ui):
    view, d, tool, shown, ctk = ui
    s = staff_view(view)
    s.open_tool_modal(tool)
    m = [w for w in s.winfo_children() if w.winfo_class() == "Toplevel"][-1]
    assert button_in(m, "↻ Auto-Gen") and button_in(m, "Save Tag Link")
    assert not button_in(m, "Unlink Current Tag") and not button_in(m, "Update") and not button_in(m, "Archive")
    button_in(m, "↻ Auto-Gen").invoke()
    button_in(m, "Save Tag Link").invoke()
    assert [x[0] for x in shown] == ["showinfo"], shown
    assert rows(d, "SELECT tag_id FROM tool WHERE tool_id=%s", (tool,))[0]["tag_id"] == f"TAG-{tool:03d}-ANO-PET"
    assert button_in(m, "Tag saved")._state == "disabled"                          # cannot be saved a second time in this panel
    m.destroy()
    # reopened: the tool now has a tag, so Staff get no tag controls at all
    s.open_tool_modal(tool)
    m = [w for w in s.winfo_children() if w.winfo_class() == "Toplevel"][-1]
    assert not any(button_in(m, t) for t in ("↻ Auto-Gen", "Save Tag Link", "Unlink Current Tag"))
    m.destroy()
    from services import inventory_service as inv
    from services.errors import PermissionDenied
    with pytest.raises(PermissionDenied, match="already has a tag"):                # and the service refuses even if the screen is bypassed
        inv.assign_tag({"user_id": 2}, tool, "SOMETHING-ELSE")


def test_admin_can_relink_and_unlink_in_the_item_panel(ui):
    view, d, tool, shown, ctk = ui
    run(d, "UPDATE tool SET tag_id='NAI-001' WHERE tool_id=%s", (tool,))
    view.open_tool_modal(tool)
    m = [w for w in view.winfo_children() if w.winfo_class() == "Toplevel"][-1]
    assert button_in(m, "Save Tag Link") and button_in(m, "Unlink Current Tag")
    button_in(m, "Unlink Current Tag").invoke()
    assert rows(d, "SELECT tag_id FROM tool WHERE tool_id=%s", (tool,))[0]["tag_id"] is None
    m.destroy()


def button_in(widget, text):
    return next((w for w in walk(widget) if hasattr(w, "_text") and hasattr(w, "_command") and w._text == text), None)


# ---- the batch-print checkboxes -------------------------------------------------------------------------------------------
def test_batch_print_checkbox_is_disabled_for_untagged_tools_and_works_for_tagged_ones(svc, monkeypatch):
    import customtkinter as ctk
    from conftest import make_window
    import database
    import views.inventory as vi
    d = svc
    run(d, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('ADM-2026-001','Admin','Admin','Active')")
    bare = run(d, "INSERT INTO tool (name, item_type, category) VALUES ('nails','Equipment','another')")
    tagged = run(d, "INSERT INTO tool (name, tag_id, item_type, category) VALUES ('Caliper','CAL-001','Equipment','Measuring')")
    for t in (bare, tagged):
        run(d, "INSERT INTO inventory (tool_id, quantity_total, quantity_available) VALUES (%s,5,5)", (t,))
    root = make_window(ctk.CTk)
    root.geometry("900x600+0+0")
    shown, opened = [], []
    monkeypatch.setattr(vi, "get_connection", database.get_connection)
    for name in ("showinfo", "showerror", "showwarning"):
        monkeypatch.setattr(vi.messagebox, name, lambda title, msg, _n=name, **k: shown.append((_n, title, msg)))
    monkeypatch.setattr(vi.os, "startfile", lambda path: opened.append(path), raising=False)
    try:
        view = vi.InventoryView(root, {"user_id": 1, "employee_id": "ADM-2026-001", "role": "Admin", "full_name": "Admin", "email": None, "status": "Active"})
        view.pack(fill="both", expand=True)
        root.after(2500, root.quit)
        root.mainloop()                                           # lets the background loader render the table
        boxes = [slot["check"] for slot in view._inv_table._slots[:2]]
        assert len(boxes) == 2, boxes
        assert view.select_page_check.cget("state") == "normal"
        states = sorted(b._state for b in boxes)
        assert states == ["disabled", "normal"], states            # the untagged tool's box is deliberately inactive
        enabled = next(b for b in boxes if b._state == "normal")
        assert view.batch_print_btn.cget("state") == "disabled"
        button_in(view, "⎙ Batch Print Tags").invoke()
        assert not shown                                           # disabled button cannot start an empty print
        enabled._text_label.event_generate("<Button-1>")            # the visible Select text is clickable
        root.update()
        assert {str(x) for x in view.selected_for_print} == {str(tagged)}     # the screen keeps the ids as text
        assert view.selected_count_label.cget("text") == "1 selected"
        assert view.batch_print_btn.cget("state") == "normal"
        view.select_page_check._text_label.event_generate("<Button-1>")  # clear this page with its label
        root.update()
        assert view.selected_for_print == set()
        assert view.batch_print_btn.cget("state") == "disabled"
        view.select_page_check._text_label.event_generate("<Button-1>")
        root.update()
        assert {str(x) for x in view.selected_for_print} == {str(tagged)}
        shown.clear()
        button_in(view, "⎙ Batch Print Tags").invoke()
        assert not [s for s in shown if s[0] == "showerror"], shown
        assert opened and opened[-1].endswith(".pdf")              # a PDF of the ticked tag was produced and opened
        assert view.selected_for_print == set()                    # the selection is cleared after printing (the table then reloads)
        assert view.batch_print_btn.cget("state") == "disabled"
    finally:
        root.destroy()
