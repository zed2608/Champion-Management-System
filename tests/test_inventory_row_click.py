"""REGRESSION for the real "Could not update: Something went wrong" failure.

Cause: clicking a table row hands the panel the item id as TEXT ('1'); the service looked it up in a dict keyed by the NUMBER 1 and raised
KeyError('1'), so EVERY Update (and Archive, Restore, tag Save/Unlink) from the Inventory panel failed with a generic message. Earlier tests
opened the panel with an int id and never exercised the real path.

This test reproduces the user's exact row and path: the real table loader runs, the row is "clicked" with its text id, nothing is edited,
and Update is pressed.
"""
from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.db
TODAY = date.today()
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


def button(widget, text):
    return next((w for w in walk(widget) if hasattr(w, "_text") and hasattr(w, "_command") and w._text == text), None)


@pytest.fixture
def real_screen(svc, monkeypatch):
    """The user's data: one tool 'nails' (Equipment, pcs, 2 of 2, price 12, no location/tag), a project that ended long ago
    needing 4 of them, an Admin who is also its worker, plus a pile of audit rows."""
    import customtkinter as ctk
    from conftest import make_window
    import database
    import views.inventory as vi
    d = svc
    admin = run(d, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('ADM-2026-001','System Admin','Admin','Active')")
    tool = run(d, "INSERT INTO tool (name, description, category, supplier, item_type, unit_of_measure, price) "
                  "VALUES ('nails','yes','another','petron','Equipment','pcs',12)")
    run(d, "INSERT INTO inventory (tool_id, quantity_total, quantity_available) VALUES (%s,2,2)", (tool,))
    pid = run(d, "INSERT INTO projects (name, start_date, end_date, status, workers_assigned) VALUES ('project 2',%s,%s,'Approved','ADM-2026-001')",
              (TODAY - timedelta(days=70), TODAY - timedelta(days=34)))
    run(d, "INSERT INTO project_requirements (project_id, tool_id, quantity) VALUES (%s,%s,4)", (pid, tool))
    run(d, "UPDATE projects SET status='Ongoing' WHERE project_id=%s", (pid,))
    for i in range(19):
        run(d, "INSERT INTO system_logs (user_id, action_type, module, details) VALUES (%s,'Edited','Inventory','probe')", (admin,))
    root = make_window(ctk.CTk)
    root.geometry("1100x700+0+0")
    monkeypatch.setattr(vi, "get_connection", database.get_connection)
    shown = []
    for name in ("showinfo", "showerror", "showwarning"):
        monkeypatch.setattr(vi.messagebox, name, lambda title, msg, _n=name, **k: shown.append((_n, title, msg)))
    monkeypatch.setattr(vi.messagebox, "askyesno", lambda *a, **k: True)
    session = {"user_id": admin, "employee_id": "ADM-2026-001", "role": "Admin", "full_name": "System Admin", "email": None, "status": "Active"}
    view = vi.InventoryView(root, session)                 # starts the REAL background table loader
    view.pack(fill="both", expand=True)
    root.after(2500, root.quit)
    root.mainloop()                                        # table rendered, hash table filled
    assert "1" in view.tool_hash_table or str(tool) in view.tool_hash_table, "the table did not load"
    yield view, d, tool, shown, ctk, root
    root.destroy()


def open_row(view, tool, ctk):
    view.open_tool_modal(str(tool))                        # the real row click: the id arrives as TEXT
    modal = [w for w in view.winfo_children() if w.winfo_class() == "Toplevel"][-1]
    entries = dict(zip(FIELDS, [w for w in walk(modal) if isinstance(w, ctk.CTkEntry)]))
    return modal, entries


def set_text(entry, text):
    entry.configure(state="normal")
    entry.delete(0, "end")
    entry.insert(0, text)


def test_update_with_nothing_edited_works_from_a_clicked_row(real_screen):
    view, d, tool, shown, ctk, root = real_screen
    before = rows(d, "SELECT name, category, supplier, description, location, price, tag_id FROM tool WHERE tool_id=%s", (tool,))[0]
    modal, e = open_row(view, tool, ctk)
    button(modal, "Update").invoke()
    assert shown == [], shown                              # used to be: 'Something went wrong and nothing was saved'
    after = rows(d, "SELECT name, category, supplier, description, location, price, tag_id FROM tool WHERE tool_id=%s", (tool,))[0]
    assert after == before                                 # nothing changed, and the display text 'N/A' was not stored
    inv = rows(d, "SELECT quantity_total, quantity_available FROM inventory WHERE tool_id=%s", (tool,))[0]
    assert (inv["quantity_total"], inv["quantity_available"]) == (2, 2)


@pytest.mark.parametrize("field,value,column,expected", [
    ("name", "nails (box)", "name", "nails (box)"), ("price", "20", "price", 20), ("description", "", "description", None),
    ("supplier", "", "supplier", None), ("tag", "NAI-001", "tag_id", "NAI-001"),
])
def test_each_edit_works_from_a_clicked_row(real_screen, field, value, column, expected):
    view, d, tool, shown, ctk, root = real_screen
    modal, e = open_row(view, tool, ctk)
    set_text(e[field], value)
    button(modal, "Update").invoke()
    assert shown == [], shown
    got = rows(d, f"SELECT `{column}` AS v FROM tool WHERE tool_id=%s", (tool,))[0]["v"]
    assert got == expected or (expected is not None and str(got) in (str(expected), f"{expected}.00"))


def test_quantity_edits_from_a_clicked_row(real_screen):
    view, d, tool, shown, ctk, root = real_screen
    modal, e = open_row(view, tool, ctk)
    set_text(e["total"], "5")
    set_text(e["min_stock"], "1")
    button(modal, "Update").invoke()
    assert shown == [], shown
    inv = rows(d, "SELECT quantity_total, quantity_available, minimum_stock FROM inventory WHERE tool_id=%s", (tool,))[0]
    assert (inv["quantity_total"], inv["quantity_available"], inv["minimum_stock"]) == (5, 5, 1)


def test_archive_restore_and_tag_buttons_also_work_from_a_clicked_row(real_screen):
    view, d, tool, shown, ctk, root = real_screen
    modal, e = open_row(view, tool, ctk)
    set_text(e["tag"], "NAI-777")
    button(modal, "Save Tag Link").invoke()
    assert [s[0] for s in shown] == ["showinfo"], shown
    assert rows(d, "SELECT tag_id FROM tool WHERE tool_id=%s", (tool,))[0]["tag_id"] == "NAI-777"
    shown.clear()
    button(modal, "Unlink Current Tag").invoke()
    assert rows(d, "SELECT tag_id FROM tool WHERE tool_id=%s", (tool,))[0]["tag_id"] is None
    shown.clear()
    button(modal, "Archive").invoke()
    assert not [s for s in shown if s[0] == "showerror"], shown
    assert rows(d, "SELECT is_archived FROM tool WHERE tool_id=%s", (tool,))[0]["is_archived"] == 1


def test_dates_shown_in_the_item_panel_are_real_dates_not_format_codes(real_screen):
    """REGRESSION: with query parameters the driver does not collapse '%%', so the dates came back as the literal text '%Y-%m-%d'."""
    view, d, tool, shown, ctk, root = real_screen
    run(d, "UPDATE tool SET date_acquired = '2025-03-04 10:00:00' WHERE tool_id = %s", (tool,))
    run(d, "INSERT INTO tool_issues (tool_id, condition_flag, quantity, flagged_at) VALUES (%s, 'Damaged', 1, '2026-02-05 09:00:00')", (tool,))
    rows_, info = view._fetch_inventory_page(0, 25)
    row = next(r for r in rows_ if r["tool_id"] == tool)
    assert row["date_acquired"] == "2025-03-04" and row["last_checked_date"] == "2026-02-05"
