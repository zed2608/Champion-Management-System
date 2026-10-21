"""Issuance, then Return with one Damaged unit, through the real Issuance & Retrieval screen handlers, then the Inventory screen's
own numbers and the receipt's date. Skipped without a display / throwaway MySQL.

Scenario (5 units owned, the project is approved for 4):
    issue 4  -> 1 in stock
    return 1 Good                      -> 2 in stock
    return 1 Damaged, no details       -> refused with a warning, nothing changes
    return 1 Damaged, with details     -> accepted, 1 unit in maintenance, a ticket exists
    Inventory shows  2/5  (2 on the shelf, 2 still out, 1 in maintenance)
"""
from datetime import date, datetime, timedelta, timezone

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


def fill(entry, text):
    entry.configure(state="normal")
    entry.delete(0, "end")
    entry.insert(0, text)


@pytest.fixture
def screen(svc, monkeypatch):
    import customtkinter as ctk
    from conftest import make_window
    import database
    import views.borrowing as vb
    import views.inventory as vi
    root = make_window(ctk.CTk)
    root.geometry("400x300+0+0")
    root.update()
    d = svc
    staff = run(d, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('STF-2026-001','Stacy','Staff','Active')")
    admin = run(d, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('ADM-2026-001','Admin','Admin','Active')")
    run(d, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('WKR-2026-001','Wally','Worker','Active')")
    cal = run(d, "INSERT INTO tool (name, tag_id, item_type, price) VALUES ('Caliper','CAL-001','Equipment',900)")
    run(d, "INSERT INTO inventory (tool_id, quantity_total, quantity_available) VALUES (%s,5,5)", (cal,))
    pid = run(d, "INSERT INTO projects (name, client, location, start_date, end_date, status, workers_assigned) "
                 "VALUES ('Alpha','ACME','Site A',%s,%s,'Approved','WKR-2026-001')", (TODAY - timedelta(days=1), TODAY + timedelta(days=20)))
    run(d, "INSERT INTO project_requirements (project_id, tool_id, quantity) VALUES (%s,%s,4)", (pid, cal))

    shown = []
    for name in ("showinfo", "showerror", "showwarning"):
        monkeypatch.setattr(vb.messagebox, name, lambda title, msg, _n=name, **k: shown.append((_n, title, msg)))
    monkeypatch.setattr(vb.IssuanceView, "load_transaction_history", lambda self: None)
    monkeypatch.setattr(vi.InventoryView, "load_inventory_data", lambda self, *a, **k: None)
    view = vb.IssuanceView(root, user_info={"user_id": staff, "role": "Staff", "full_name": "Stacy"})
    receipts = []
    monkeypatch.setattr(view, "print_master_receipt", lambda *a, **k: receipts.append((a, k)))
    yield view, d, root, shown, receipts, {"admin": admin, "cal": cal}
    for attr in ("issuance_modal", "retrieval_modal"):
        try:
            getattr(view, attr).destroy()
        except Exception:
            pass
    root.destroy()


def issue_four(view, shown):
    view.open_issuance_modal()
    fill(view.b_emp_id, "WKR-2026-001")
    view.verify_borrower()
    choice = [k for k in view.active_projects_map][0]
    view.b_project_menu.set(choice)
    view.on_project_selected(choice)
    for _ in range(4):
        fill(view.b_tag_id, "cal-001")
        view.add_tool_to_cart()
    assert view.borrow_cart[0]["qty_borrowed"] == 4
    shown.clear()
    view.execute_borrow()
    assert [m[0] for m in shown] == ["showinfo"], shown
    return choice


def open_return(view, condition, qty):
    view.open_retrieval_modal()
    fill(view.r_emp_id, "WKR-2026-001")
    view.verify_return_employee()
    fill(view.r_tag_id, "CAL-001")
    view.verify_tool_for_return()
    view.r_condition.set(condition)
    fill(view.r_qty, str(qty))


def inv(d):
    return rows(d, "SELECT * FROM inventory")[0]


def test_issue_four_return_one_good_and_one_damaged(screen):
    view, d, root, shown, receipts, ids = screen
    issue_four(view, shown)
    assert inv(d)["quantity_available"] == 1 and len(receipts) == 1

    shown.clear()
    open_return(view, "Good", 1)
    view.execute_return()
    assert [m[0] for m in shown] == ["showinfo"], shown
    assert inv(d)["quantity_available"] == 2

    # damaged, no details: refused, nothing changes, no ticket
    shown.clear()
    open_return(view, "Damaged", 1)
    view.execute_return()
    assert [m[0] for m in shown] == ["showwarning"] and "describe" in shown[0][2], shown
    assert inv(d)["quantity_available"] == 2 and inv(d)["quantity_in_maintenance"] == 0
    assert rows(d, "SELECT COUNT(*) AS n FROM tool_issues")[0]["n"] == 0

    # damaged, with details: accepted
    shown.clear()
    view.r_condition_desc.insert("1.0", "Jaw cracked")
    view.execute_return()
    assert [m[0] for m in shown] == ["showinfo"] and "ticket" in shown[0][2], shown
    i = inv(d)
    assert (i["quantity_total"], i["quantity_available"], i["quantity_in_maintenance"]) == (5, 2, 1)
    ticket = rows(d, "SELECT * FROM tool_issues")
    assert len(ticket) == 1 and ticket[0]["status"] == "Open" and ticket[0]["tool_id"] == ids["cal"]
    assert str(ticket[0]["issue_id"]) in shown[0][2]                  # the number the user is told is the ticket that exists
    out = rows(d, "SELECT COALESCE(SUM(quantity),0) AS n FROM `transaction` WHERE type='Issue' AND status='Active'")[0]["n"]
    assert out == 2                                                    # 4 issued - 2 retrieved

    # the Inventory screen's own query and cell text
    import customtkinter as ctk
    import views.inventory as vi
    iv = vi.InventoryView(root, {"user_id": ids["admin"], "role": "Admin", "full_name": "Admin"})
    iv._inv_query, iv._inv_sort = "", "Most Recent"
    page, _info = iv._fetch_inventory_page(0, 25)
    assert iv._inventory_cells(page[0])[5].lstrip("⚠ ") == "2/5", iv._inventory_cells(page[0])


def test_receipt_shows_the_server_clock_in_plus_8_not_the_pcs_clock(screen, monkeypatch):
    view, d, root, shown, receipts, ids = screen
    assert rows(d, "SELECT @@session.time_zone AS tz")[0]["tz"] == "+08:00"
    issue_four(view, shown)
    args, kwargs = receipts[0]
    stored = rows(d, "SELECT MIN(borrow_date) AS b FROM `transaction`")[0]["b"]
    assert kwargs["issued_at"] == stored                               # the receipt data IS the stored server time

    # the stored time is "now" in Manila time, whatever time zone this PC is set to
    now_plus_8 = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=8)
    assert abs((stored - now_plus_8).total_seconds()) < 120, (stored, now_plus_8)

    # and the picture of the receipt prints exactly that time
    from PIL import ImageDraw
    printed = []
    real = ImageDraw.ImageDraw.text

    def spy(self, xy, text, *a, **k):
        printed.append(str(text))
        return real(self, xy, text, *a, **k)
    monkeypatch.setattr(ImageDraw.ImageDraw, "text", spy)
    view._build_receipt_image("1-4", "Wally", ["Caliper x4"], "Alpha", issued_at=stored)
    assert stored.strftime("%B %d, %Y  —  %I:%M %p") in printed
