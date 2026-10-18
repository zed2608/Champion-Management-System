"""Paging: the SQL helper, the recycling PagedTable widget, and every real screen that now shows one page at a time."""
import time

import pytest

from services import paging
from services.paging import PageInfo, clamp_page, fetch_page


# ---- pure helpers -------------------------------------------------------------------------------------------------------------
def test_page_info_arithmetic():
    i = PageInfo(page=2, size=25, total=130)
    assert (i.pages, i.offset, i.first, i.last) == (6, 50, 51, 75)
    assert i.label() == "Showing 51-75 of 130"
    assert PageInfo(5, 25, 130).last == 130
    assert PageInfo(0, 25, 0).label() == "No records" and PageInfo(0, 25, 0).pages == 1


@pytest.mark.parametrize("page,size,total,expected", [(0, 25, 0, 0), (3, 25, 10, 0), (99, 25, 130, 5), (-4, 25, 130, 0), ("x", 25, 130, 0), (2, 25, 130, 2)])
def test_clamp_page(page, size, total, expected):
    assert clamp_page(page, size, total) == expected


@pytest.mark.parametrize("raw,expected", [(10, 10), ("50", 50), (0, 1), (-5, 1), (10 ** 6, 500), (None, 25), ("abc", 25)])
def test_clean_size(raw, expected):
    assert paging.clean_size(raw) == expected


pytestmark_db = pytest.mark.db


def run(db, sql, params=()):
    with db.transaction() as cur:
        cur.execute(sql, params)
        return cur.lastrowid


def add_tools(db, n):
    with db.transaction() as cur:
        for i in range(n):
            cur.execute("INSERT INTO tool (name, item_type, unit_of_measure) VALUES (%s,'Equipment','pcs')", (f"tool {i:03d}",))


@pytest.mark.db
def test_fetch_page_counts_and_slices(svc):
    add_tools(svc, 130)
    with svc.read() as cur:
        rows, info = fetch_page(cur, "SELECT tool_id, name", "FROM tool WHERE name LIKE %s", ["tool %"], "ORDER BY name ASC, tool_id ASC", 0, 25)
        assert info.total == 130 and len(rows) == 25 and rows[0]["name"] == "tool 000"
        rows, info = fetch_page(cur, "SELECT tool_id, name", "FROM tool WHERE name LIKE %s", ["tool %"], "ORDER BY name ASC, tool_id ASC", 5, 25)
        assert len(rows) == 5 and rows[0]["name"] == "tool 125" and info.page == 5
        rows, info = fetch_page(cur, "SELECT tool_id, name", "FROM tool WHERE name LIKE %s", ["tool %"], "ORDER BY name ASC, tool_id ASC", 99, 25)
        assert info.page == 5 and len(rows) == 5                                  # a page past the end lands on the last one
        rows, info = fetch_page(cur, "SELECT tool_id", "FROM tool WHERE name = %s", ["nothing"], "ORDER BY tool_id", 3, 25)
        assert rows == [] and info.total == 0 and info.page == 0


@pytest.mark.db
def test_pages_never_repeat_or_skip_rows(svc):
    add_tools(svc, 60)
    seen = []
    with svc.read() as cur:
        for page in range(3):
            rows, _ = fetch_page(cur, "SELECT tool_id", "FROM tool", [], "ORDER BY tool_id", page, 25)
            seen += [r["tool_id"] for r in rows]
    assert len(seen) == 60 == len(set(seen))


# ---- the widget ---------------------------------------------------------------------------------------------------------------
def pump(root, until, timeout=25.0):
    end = time.time() + timeout
    while time.time() < end:
        root.update()
        if until():
            return True
        time.sleep(0.01)
    return until()


@pytest.fixture
def window():
    import customtkinter as ctk
    from conftest import make_window
    root = make_window(ctk.CTk)
    root.geometry("900x600+0+0")
    yield root
    root.destroy()


def make_table(root, data, page_size=25, **kw):
    from views.paged_table import PagedTable

    def fetch(page, size):
        total = len(data)
        page = clamp_page(page, size, total)
        return data[page * size:(page + 1) * size], PageInfo(page, size, total)
    t = PagedTable(root, [("ID", 1, 50), ("Name", 3, 100)], fetch=fetch, cells=lambda r: [r["id"], r["name"]], page_size=page_size, **kw)
    t.pack(fill="both", expand=True)
    return t


def shown(t):
    return [s["labels"][1].cget("text") for s in t._slots if s["row"] is not None]


def test_widget_shows_one_page_and_recycles_its_rows(window):
    data = [{"id": i, "name": f"row {i}"} for i in range(60)]
    t = make_table(window, data)
    t.reload(0)
    assert pump(window, lambda: len(shown(t)) == 25)
    assert shown(t)[0] == "row 0" and t.info_lbl.cget("text") == "Showing 1-25 of 60" and t.page_lbl.cget("text") == "Page 1 of 3"
    assert t.prev_btn.cget("state") == "disabled" and t.next_btn.cget("state") == "normal"
    first_cells = [id(s["cells"][1]) for s in t._slots]
    t.goto(1)
    assert pump(window, lambda: shown(t) and shown(t)[0] == "row 25")
    t.goto(2)
    assert pump(window, lambda: len(shown(t)) == 10 and shown(t)[0] == "row 50")       # last page: 10 rows, the other 15 are hidden
    assert t.next_btn.cget("state") == "disabled" and t.prev_btn.cget("state") == "normal"
    assert len(t._slots) == 25 and [id(s["cells"][1]) for s in t._slots] == first_cells   # NO new widgets were created: they were recycled


def test_widget_changing_page_size_and_empty_and_error(window):
    data = [{"id": i, "name": f"row {i}"} for i in range(60)]
    t = make_table(window, data)
    t.reload(0)
    pump(window, lambda: len(shown(t)) == 25)
    t.size_menu.set("10")
    t._size_changed("10")
    assert pump(window, lambda: len(shown(t)) == 10 and t.page_lbl.cget("text") == "Page 1 of 6")
    empty = make_table(window, [], empty_text="Nothing here")
    empty.reload(0)
    assert pump(window, lambda: empty.message.cget("text") == "Nothing here")

    from views.paged_table import PagedTable

    def boom(page, size):
        raise RuntimeError("secret SELECT * FROM user")
    bad = PagedTable(window, [("A", 1, 50)], fetch=boom, cells=lambda r: [""])
    bad.pack()
    bad.reload(0)
    assert pump(window, lambda: "ERR-" in bad.message.cget("text"))                   # coded message, no SQL / driver text
    assert "SELECT" not in bad.message.cget("text")


def test_only_the_newest_request_is_drawn(window):
    from views.paged_table import PagedTable
    import threading
    gate = threading.Event()

    def fetch(page, size):
        if page == 0:
            gate.wait(3)                                                               # the slow, OLD request
            return [{"id": 0, "name": "OLD"}], PageInfo(0, size, 1)
        return [{"id": 1, "name": "NEW"}], PageInfo(0, size, 1)
    t = PagedTable(window, [("ID", 1, 50), ("Name", 3, 100)], fetch=fetch, cells=lambda r: [r["id"], r["name"]])
    t.pack()
    t.reload(0)
    t.reload(1)
    assert pump(window, lambda: shown(t) == ["NEW"])
    gate.set()
    pump(window, lambda: False, timeout=0.5)
    assert shown(t) == ["NEW"]                                                          # the late OLD answer was dropped


def test_destroying_the_table_cancels_its_timer(window):
    t = make_table(window, [{"id": 1, "name": "a"}])
    t.reload(0)
    t.destroy()
    assert t._poll_job is None
    pump(window, lambda: False, timeout=0.3)                                             # nothing blows up after destroy


# ---- the real screens, with more rows than one page ------------------------------------------------------------------------------
def admin_session(db):
    uid = run(db, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('ADM-2026-001','Admin','Admin','Active')")
    return {"user_id": uid, "employee_id": "ADM-2026-001", "role": "Admin", "full_name": "Admin", "email": None, "status": "Active"}


def tbl_of(widget, attr):
    return getattr(widget, attr)


@pytest.mark.db
def test_inventory_screen_pages_and_search(svc, monkeypatch):
    import customtkinter as ctk
    from conftest import make_window
    import database
    import views.inventory as vi
    admin = admin_session(svc)
    add_tools(svc, 60)
    for t in range(1, 61):
        run(svc, "INSERT INTO inventory (tool_id, quantity_total, quantity_available) VALUES (%s, 5, 5)", (t,))
    root = make_window(ctk.CTk)
    root.geometry("1100x700+0+0")
    monkeypatch.setattr(vi, "get_connection", database.get_connection)
    try:
        view = vi.InventoryView(root, admin)
        view.pack(fill="both", expand=True)
        t = view._inv_table
        assert pump(root, lambda: len(shown_col(t, 3)) == 25), t.message.cget("text")
        assert t.info_lbl.cget("text") == "Showing 1-25 of 60"
        assert len(view.tool_hash_table) == 25                                           # only the page on screen is held
        t.goto(2)
        assert pump(root, lambda: len(shown_col(t, 3)) == 10 and t.page_lbl.cget("text") == "Page 3 of 3")
        view.search_entry.insert(0, "tool 05")
        view.perform_search()
        assert pump(root, lambda: t.info_lbl.cget("text") == "Showing 1-10 of 10")        # 'tool 050'..'tool 059'
    finally:
        root.destroy()


def shown_col(t, col):
    return [s["labels"][col].cget("text") for s in t._slots if s["row"] is not None]


@pytest.mark.db
def test_tracking_and_issuance_and_maintenance_screens_page(svc, monkeypatch):
    import customtkinter as ctk
    from conftest import make_window
    import database
    import views.tracking as vt
    import views.borrowing as vb
    import views.maintenance as vm
    admin = admin_session(svc)
    worker = run(svc, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('WKR-2026-001','Wally','Worker','Active')")
    run(svc, "INSERT INTO tool (name, item_type, unit_of_measure, tag_id) VALUES ('drill','Equipment','pcs','DRL-001')")
    with svc.read() as cur:
        cur.execute("SELECT tool_id FROM tool WHERE name='drill'")
        tool = cur.fetchone()["tool_id"]
    run(svc, "INSERT INTO inventory (tool_id, quantity_total, quantity_available) VALUES (%s, 90, 90)", (tool,))
    with svc.transaction() as cur:
        for i in range(60):
            cur.execute("INSERT INTO `transaction` (tool_id, user_id, type, status, borrow_date, quantity) VALUES (%s,%s,'Issue','Active',NOW() - INTERVAL %s MINUTE,1)",
                        (tool, worker, i))
            cur.execute("INSERT INTO tool_issues (tool_id, reported_by, condition_flag, notes, is_resolved) VALUES (%s,'ADM-2026-001','Damaged','n',0)", (tool,))
    for mod in (vt, vb, vm):
        monkeypatch.setattr(mod, "get_connection", database.get_connection)
    root = make_window(ctk.CTk)
    root.geometry("1200x800+0+0")
    try:
        tv = vt.TrackingView(root, admin)
        tv.pack(fill="both", expand=True)
        assert pump(root, lambda: getattr(tv, "_log_table", None) is not None and tv._log_table.info.total == 60)
        assert len(shown_col(tv._log_table, 0)) == 25
        tv.switch_tab("🔎 Audit Records")
        assert pump(root, lambda: getattr(tv, "_audit_table", None) is not None and tv._audit_table.info.total == 60)
        assert "Total: 60" in tv.audit_summary.cget("text") and "Active: 60" in tv.audit_summary.cget("text")     # whole result set, not only the page
        tv.switch_tab("⚙️ Activity Log")
        assert pump(root, lambda: "Showing" in tv.act_summary.cget("text") or "entries" in tv.act_summary.cget("text"))
        tv.destroy()

        mv = vm.MaintenanceView(root, admin)
        mv.pack(fill="both", expand=True)
        assert pump(root, lambda: getattr(mv, "_issues_table", None) is not None and mv._issues_table.info.total == 60)
        assert len(shown_col(mv._issues_table, 0)) == 25 and "Open: 60" in mv.issues_summary.cget("text")
        for tab, attr in (("📦 Archived Tools", "_tools_table"), ("👥 Archived Employees", "_emp_table"),
                          ("📋 Archived Projects", "_proj_table"), ("💾 Backup & Restore", "_backup_table")):
            mv.tab_var.set(tab)
            mv.switch_tab(tab)
            assert pump(root, lambda a=attr: getattr(mv, a, None) is not None and "Loading" not in getattr(mv, a).message.cget("text") and getattr(mv, a)._seq >= 1
                        and getattr(mv, a).info_lbl.cget("text") != ""), tab
        mv.destroy()

        iv = vb.IssuanceView(root, admin)
        iv.pack(fill="both", expand=True)
        assert pump(root, lambda: getattr(iv, "_hist_table", None) is not None and iv._hist_table.info.total >= 1), iv._hist_table.message.cget("text")
        assert iv._hist_table.info_lbl.cget("text").startswith("Showing 1-")
    finally:
        root.destroy()


def find_tables(widget):
    from views.paged_table import PagedTable
    out = []
    for c in widget.winfo_children():
        if isinstance(c, PagedTable):
            out.append(c)
        out.extend(find_tables(c))
    return out


@pytest.mark.db
def test_report_tabs_page_their_tables(svc, monkeypatch):
    import customtkinter as ctk
    from conftest import make_window
    import views.reports as vr
    admin = admin_session(svc)
    with svc.transaction() as cur:
        for i in range(60):
            cur.execute("INSERT INTO tool (name, item_type, unit_of_measure) VALUES (%s,'Equipment','pcs')", (f"short {i:03d}",))
    for t in range(1, 61):
        run(svc, "INSERT INTO inventory (tool_id, quantity_total, quantity_available, minimum_stock) VALUES (%s, 10, 1, 5)", (t,))
    root = make_window(ctk.CTk)
    root.geometry("1300x800+0+0")
    try:
        view = vr.ReportsView(root, user_info=admin)
        view.pack(fill="both", expand=True)
        results = {}

        def visit(tab):
            view.tab_var.set(tab)
            view.switch_tab(tab)

        def collect():
            for t in find_tables(view):
                results[t.info_lbl.cget("text") or t.message.cget("text")] = t
            root.quit()
        visit("⭣ Low Stock")
        root.after(2500, collect)
        root.mainloop()
        assert "Showing 1-25 of 60" in results, list(results)
        for tab in ("📋 Project Allocation", "⚠ Damage & Loss", "⧖ Overdue Transactions", "🖹 Employee Activity", "⛭ Tool Usage Report"):
            visit(tab)
            root.after(1500, root.quit)
            root.mainloop()
    finally:
        root.destroy()
