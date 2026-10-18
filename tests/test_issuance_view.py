"""Drives the REAL IssuanceView handlers (not a mock) against a throwaway database and records every dialog.

Opens real Tk windows briefly, so it is skipped when no display is available. It calls the same methods the buttons call
(verify_borrower, on_project_selected, add_tool_to_cart, execute_borrow, verify_tool_for_return, execute_return); it does
not synthesise mouse clicks.
"""
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
def screen(svc, monkeypatch):
    import customtkinter as ctk
    from conftest import make_window
    root = make_window(ctk.CTk)
    root.geometry("400x300+0+0")
    root.update()

    import views.borrowing as vb
    monkeypatch.setattr(vb, "get_connection", __import__("database").get_connection)
    d = svc
    u = {}
    for key, eid, name, role in [("staff", "STF-2026-001", "Stacy", "Staff"), ("w1", "WKR-2026-001", "Wally", "Worker"),
                                 ("w2", "WKR-2026-0011", "Willa", "Worker")]:
        u[key] = run(d, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES (%s,%s,%s,'Active')", (eid, name, role))
    cal = run(d, "INSERT INTO tool (name, tag_id, item_type) VALUES ('Caliper','CAL-001','Equipment')")
    run(d, "INSERT INTO inventory (tool_id, quantity_total, quantity_available) VALUES (%s,10,10)", (cal,))
    pid = run(d, "INSERT INTO projects (name, client, location, start_date, end_date, status, workers_assigned) "
                 "VALUES ('Alpha','ACME','Site A',%s,%s,'Approved','WKR-2026-001')", (TODAY - timedelta(days=1), TODAY + timedelta(days=20)))
    run(d, "INSERT INTO project_requirements (project_id, tool_id, quantity) VALUES (%s,%s,2)", (pid, cal))

    shown = []
    for name in ("showinfo", "showerror", "showwarning"):
        monkeypatch.setattr(vb.messagebox, name, lambda title, msg, _n=name, **k: shown.append((_n, title, msg)))
    monkeypatch.setattr(vb.IssuanceView, "load_transaction_history", lambda self: None)   # its worker thread needs a running mainloop
    view = vb.IssuanceView(root, user_info={"user_id": u["staff"], "role": "Staff", "full_name": "Stacy"})
    receipts = []
    monkeypatch.setattr(view, "print_master_receipt", lambda *a, **k: receipts.append(a + (k,)))
    yield view, d, u, cal, pid, shown, receipts
    for attr in ("issuance_modal", "retrieval_modal"):
        try:
            getattr(view, attr).destroy()
        except Exception:
            pass
    root.destroy()


def fill(entry, text):
    entry.configure(state="normal")
    entry.delete(0, "end")
    entry.insert(0, text)


def test_issue_then_return_damaged_through_the_real_screen(screen):
    view, d, u, cal, pid, shown, receipts = screen

    # ---- issue
    view.open_issuance_modal()
    fill(view.b_emp_id, "WKR-2026-0011")                     # not assigned to the project: no project offered
    view.verify_borrower()
    assert "Verified: Willa" in view.b_user_name.cget("text") and view.b_project_menu.get() == "No projects needing tools"

    fill(view.b_emp_id, "WKR-2026-001")
    view.verify_borrower()
    assert "Verified: Wally" in view.b_user_name.cget("text")
    choice = [k for k in view.active_projects_map][0]
    view.b_project_menu.set(choice)
    view.on_project_selected(choice)
    assert view.current_project_reqs[0]["req_qty"] == 2

    for _ in range(3):                                       # third scan must hit the approved limit of 2
        fill(view.b_tag_id, "cal-001")
        view.add_tool_to_cart()
    assert view.borrow_cart[0]["qty_borrowed"] == 2
    assert [m for m in shown if m[0] == "showerror"][-1][1] == "Limit Reached"

    shown.clear()
    view.execute_borrow()
    assert [m[0] for m in shown] == ["showinfo"], shown                      # exactly ONE success dialog
    assert len(receipts) == 1 and receipts[0][3] == choice
    stored = rows(d, "SELECT MIN(borrow_date) AS b FROM `transaction`")[0]["b"]
    assert receipts[0][-1]["issued_at"] == stored                    # [4-DATE] receipt time = the stored SERVER time
    assert rows(d, "SELECT quantity_available AS a FROM inventory")[0]["a"] == 8
    t = rows(d, "SELECT * FROM `transaction`")
    assert len(t) == 2 and all(r["due_date"] == TODAY + timedelta(days=20) and r["issued_by"] == u["staff"] for r in t)

    # ---- return one unit damaged
    shown.clear()
    view.open_retrieval_modal()
    fill(view.r_emp_id, "WKR-2026-001")
    view.verify_return_employee()
    fill(view.r_tag_id, "CAL-001")
    view.verify_tool_for_return()
    assert "Currently Deployed Out: 2" in view.r_record_info.cget("text")
    view.r_condition.set("Damaged")
    fill(view.r_qty, "1")
    view.execute_return()                                                    # no details typed
    assert [m[0] for m in shown] == ["showwarning"] and "describe" in shown[0][2]
    assert rows(d, "SELECT COUNT(*) AS n FROM tool_issues")[0]["n"] == 0

    shown.clear()
    view.r_condition_desc.insert("1.0", "Jaw cracked")
    view.execute_return()
    assert [m[0] for m in shown] == ["showinfo"], shown                      # success shown ONCE (it used to show twice)
    assert "ticket" in shown[0][2] and "Damaged" in shown[0][2]
    inv = rows(d, "SELECT * FROM inventory")[0]
    assert (inv["quantity_available"], inv["quantity_in_maintenance"]) == (8, 1)
    issue = rows(d, "SELECT * FROM tool_issues")[0]
    assert issue["status"] == "Open" and issue["reported_by_user_id"] == u["staff"] and issue["transaction_id"]


def test_screen_shows_friendly_text_not_driver_errors(screen, monkeypatch):
    view, d, u, cal, pid, shown, receipts = screen
    view.open_issuance_modal()
    fill(view.b_emp_id, "WKR-2099-999")
    view.verify_borrower()
    assert "not found" in view.b_user_name.cget("text").lower()
    run(d, "UPDATE `user` SET status='Archived' WHERE employee_id='WKR-2026-001'")
    fill(view.b_emp_id, "WKR-2026-001")
    view.verify_borrower()
    assert "Archived" in view.b_user_name.cget("text") and view.active_borrow_user_id is None

    # database goes away in the middle of issuing: user-safe message, nothing saved
    import services.issuance_service as iss
    run(d, "UPDATE `user` SET status='Active' WHERE employee_id='WKR-2026-001'")
    fill(view.b_emp_id, "WKR-2026-001")
    view.verify_borrower()
    choice = [k for k in view.active_projects_map][0]
    view.b_project_menu.set(choice)
    view.on_project_selected(choice)
    fill(view.b_tag_id, "CAL-001")
    view.add_tool_to_cart()

    import mysql.connector
    def dead(*a, **k):
        raise mysql.connector.errors.OperationalError(msg="Lost connection to MySQL server at 10.0.0.5 during query", errno=2013)
    monkeypatch.setattr(iss.db, "run_in_transaction", dead)
    shown.clear()
    view.execute_borrow()
    kind, title, msg = shown[-1]
    assert kind == "showerror" and "Nothing was saved" in msg and "10.0.0.5" not in msg and "2013" not in msg
    assert rows(d, "SELECT COUNT(*) AS n FROM `transaction`")[0]["n"] == 0
