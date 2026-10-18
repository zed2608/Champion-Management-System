"""[QUANTITIES][HISTORY][4-DATE][RBAC] Reports count UNITS (sum of quantity), never rows; ABC is 20/30/50 by rank; archived tools stay in history."""
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from services import issuance_service as iss
from services import project_service as ps
from services import report_service as rs
from services.errors import PermissionDenied
from services.validators import ValidationError

TODAY = date.today()


# ---- ABC classification (pure) -------------------------------------------------------------------------------------
def ranked(*usages):
    return rs.classify_abc([{"usage": Decimal(str(u))} for u in usages])


def cats(*usages):
    return "".join(r["category"] for r in ranked(*usages))


def test_abc_split_is_20_30_50_by_rank():
    assert cats(*range(10, 0, -1)) == "AABBBCCCCC"                 # N=10 -> 2 A, 3 B, 5 C
    assert cats(*range(20, 0, -1)) == "AAAA" + "B" * 6 + "C" * 10  # N=20 -> 4 A, 6 B, 10 C
    assert cats(5, 4, 3, 2, 1) == "ABBCC"                          # N=5: ceil(1.0)=1 A, up to ceil(2.5)=3 for B
    assert cats(7) == "A"                                          # a single tool is A
    assert cats(7, 6) == "AC"
    assert cats() == ""


def test_never_issued_tools_are_always_c_even_when_few_tools_were_used():
    assert cats(9, 0, 0, 0, 0, 0, 0, 0, 0, 0) == "ACCCCCCCCC"      # rank 2 would be 'A' by rank alone; it was never issued
    assert cats(0, 0, 0) == "CCC"


def test_ranks_are_consecutive_and_follow_the_order_given():
    r = ranked(3, 3, 1)
    assert [x["rank"] for x in r] == [1, 2, 3]


# ---- database-backed ------------------------------------------------------------------------------------------------
def run(db, sql, params=()):
    with db.transaction() as cur:
        cur.execute(sql, params)
        return cur.lastrowid


def rows(db, sql, params=()):
    with db.read() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


@pytest.fixture
def w(svc):
    d = svc
    u = {}
    for key, eid, name, role in [("admin", "ADM-2026-001", "Admin", "Admin"), ("staff", "STF-2026-001", "Stacy", "Staff"),
                                 ("w1", "WKR-2026-001", "Wally", "Worker"), ("w2", "WKR-2026-002", "Willa", "Worker")]:
        u[key] = run(d, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES (%s,%s,%s,'Active')", (eid, name, role))
    cal = run(d, "INSERT INTO tool (name, tag_id, item_type, price) VALUES ('Caliper','CAL-001','Equipment', 4500)")
    grs = run(d, "INSERT INTO tool (name, tag_id, item_type, unit_of_measure, price) VALUES ('Grease','GRS-001','Consumable','kg', 350)")
    run(d, "INSERT INTO inventory (tool_id, quantity_total, quantity_available) VALUES (%s,10,10), (%s,5,5)", (cal, grs))
    admin, staff = {"user_id": u["admin"]}, {"user_id": u["staff"]}
    pid = ps.create_project(admin, dict(name="Alpha", client="ACME", start_date=str(TODAY - timedelta(days=1)),
                                        end_date=str(TODAY + timedelta(days=9)), workers=["WKR-2026-001", "WKR-2026-002"],
                                        requirements=[{"tool_id": cal, "qty": 3}, {"tool_id": grs, "qty": "2.5"}]))["project_id"]
    return d, u, admin, staff, cal, grs, pid


@pytest.mark.db
def test_usage_counts_units_not_rows(w):
    d, u, admin, staff, cal, grs, pid = w
    iss.issue(admin, u["w1"], pid, [{"tool_id": cal, "qty": 3}, {"tool_id": grs, "qty": "2.5"}], "p")      # 3 caliper rows + ONE grease row
    by = {r["name"]: r for r in rs.usage_report(admin)}
    assert by["Caliper"]["total_borrowed"] == 3 and by["Grease"]["total_borrowed"] == 2.5                    # a row count says 1 for grease
    assert by["Grease"]["currently_out"] == 2.5 and by["Caliper"]["currently_out"] == 3
    iss.retrieve(admin, u["w1"], grs, "1", "Good", "")
    by = {r["name"]: r for r in rs.usage_report(admin)}
    assert by["Grease"]["total_borrowed"] == 2.5 and by["Grease"]["currently_out"] == 1.5                    # the split row still adds up to 2.5


@pytest.mark.db
def test_currently_out_no_longer_counts_units_waiting_in_maintenance(w):
    d, u, admin, staff, cal, grs, pid = w
    iss.issue(admin, u["w1"], pid, [{"tool_id": cal, "qty": 2}], "p")
    iss.retrieve(admin, u["w1"], cal, 1, "Damaged", "cracked")
    r = {x["name"]: x for x in rs.usage_report(admin)}["Caliper"]
    assert r["currently_out"] == 1                       # old formula (total - available) said 2: it counted the damaged unit as 'out'
    assert r["qty_avail"] == 8


@pytest.mark.db
def test_search_and_validation(w):
    d, u, admin, staff, cal, grs, pid = w
    assert [r["name"] for r in rs.usage_report(admin, search="grea")] == ["Grease"]
    assert rs.usage_report(admin, search="%") == []                         # '%' is matched literally, not as a wildcard
    with pytest.raises(ValidationError, match="YYYY-MM-DD"):
        rs.usage_report(admin, "31/01/2026", None)
    with pytest.raises(ValidationError, match="later than"):
        rs.usage_report(admin, "2026-02-01", "2026-01-01")


@pytest.mark.db
def test_activity_sums_quantities_per_person(w):
    d, u, admin, staff, cal, grs, pid = w
    iss.issue(admin, u["w1"], pid, [{"tool_id": cal, "qty": 3}, {"tool_id": grs, "qty": "2.5"}], "p")
    iss.retrieve(admin, u["w1"], grs, "2.5", "Good", "")
    me = {r["employee_id"]: r for r in rs.activity_report(admin)}["WKR-2026-001"]
    assert (me["total_borrows"], me["active_borrows"], me["total_returned"]) == (5.5, 3, 2.5)


@pytest.mark.db
def test_allocation_issued_and_retrieved_are_quantities(w):
    d, u, admin, staff, cal, grs, pid = w
    iss.issue(admin, u["w1"], pid, [{"tool_id": cal, "qty": 3}, {"tool_id": grs, "qty": "2.5"}], "p")
    iss.retrieve(admin, u["w1"], grs, "1", "Good", "")
    by = {r["tool_name"]: r for r in rs.allocation_report(admin)}
    assert (by["Grease"]["requested"], by["Grease"]["issued"], by["Grease"]["retrieved"]) == (2.5, 2.5, 1)
    assert (by["Caliper"]["requested"], by["Caliper"]["issued"], by["Caliper"]["retrieved"]) == (3, 3, 0)


@pytest.mark.db
def test_damage_and_loss_values_are_price_times_units(w):
    d, u, admin, staff, cal, grs, pid = w
    iss.issue(admin, u["w1"], pid, [{"tool_id": cal, "qty": 3}, {"tool_id": grs, "qty": "2.5"}], "p")
    iss.retrieve(admin, u["w1"], grs, "2.5", "Lost", "spilled in transit")
    iss.retrieve(admin, u["w1"], cal, 2, "Damaged", "bent")
    res = rs.damage_loss_report(admin)
    sm = res["summary"]
    assert sm["count_lost"] == 2.5 and sm["count_damaged"] == 2                         # units, not rows (1 and 2)
    assert float(sm["total_loss"]) == pytest.approx(350 * 2.5) and float(sm["total_damage"]) == pytest.approx(4500 * 2)
    assert {r["units"] for r in res["rows"]} == {2.5, 1}


@pytest.mark.db
def test_overdue_uses_the_due_date_snapshot_and_units(w):
    d, u, admin, staff, cal, grs, pid = w
    run(d, "INSERT INTO `transaction` (tool_id, user_id, project_id, type, status, quantity, borrow_date, due_date) "
           "VALUES (%s,%s,%s,'Issue','Active',2,NOW() - INTERVAL 20 DAY, CURDATE() - INTERVAL 5 DAY)", (cal, u["w1"], pid))
    r = rs.overdue_report(admin)
    assert len(r) == 1 and r[0]["days_overdue"] == 5 and r[0]["units"] == 2         # snapshot says 5 days; the project itself is not overdue
    assert rs.overdue_report(admin, str(TODAY), None) == []                         # filtered by issue date


@pytest.mark.db
def test_reports_are_admin_only(w):
    d, u, admin, staff, cal, grs, pid = w
    for call in (rs.abc_analysis, rs.usage_report, rs.activity_report, rs.allocation_report, rs.damage_loss_report,
                 rs.low_stock_report, rs.overdue_report):
        with pytest.raises(PermissionDenied):
            call(staff)


# ---- ABC with real data, archived tools and the PDF ------------------------------------------------------------------
@pytest.fixture
def abc_world(svc):
    """10 active tools issued 10,9,...,1 units, plus an archived tool issued 20 units, plus one active tool never issued."""
    d = svc
    admin_id = run(d, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('ADM-2026-001','Admin','Admin','Active')")
    w1 = run(d, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('WKR-2026-001','Wally','Worker','Active')")
    ids = {}
    for i in range(1, 12):
        ids[i] = run(d, "INSERT INTO tool (name, tag_id, item_type) VALUES (%s,%s,'Equipment')", (f"Tool {i:02d}", f"T-{i:03d}"))
        run(d, "INSERT INTO inventory (tool_id, quantity_total, quantity_available) VALUES (%s,100,100)", (ids[i],))
    for i in range(1, 11):                                         # Tool 01 = 10 units ... Tool 10 = 1 unit; Tool 11 never issued
        run(d, "INSERT INTO `transaction` (tool_id, user_id, type, status, quantity, borrow_date, return_date) "
               "VALUES (%s,%s,'Retrieval','Returned',%s, NOW() - INTERVAL 5 DAY, NOW() - INTERVAL 4 DAY)", (ids[i], w1, 11 - i))
    arch = run(d, "INSERT INTO tool (name, tag_id, item_type, is_archived) VALUES ('Retired Lathe','LATHE-1','Equipment',1)")
    run(d, "INSERT INTO inventory (tool_id, quantity_total, quantity_available) VALUES (%s,1,1)", (arch,))
    run(d, "INSERT INTO `transaction` (tool_id, user_id, type, status, quantity, borrow_date, return_date) "
           "VALUES (%s,%s,'Retrieval','Returned',20, NOW() - INTERVAL 5 DAY, NOW() - INTERVAL 4 DAY)", (arch, w1))
    return d, {"user_id": admin_id}, ids


@pytest.mark.db
def test_abc_ranks_active_tools_20_30_50_and_keeps_archived_usage_in_the_historical_total(abc_world):
    d, admin, ids = abc_world
    res = rs.abc_analysis(admin)
    assert res["n_active"] == 11                                    # 10 issued + 1 never issued; the archived lathe is NOT ranked
    assert [r["name"] for r in res["rows"][:2]] == ["Tool 01", "Tool 02"]
    assert res["historical_total"] == 55 + 20 and res["archived_total"] == 20 and res["active_total"] == 55
    cat = {r["name"]: r["category"] for r in res["rows"]}
    # N=11: A = ceil(2.2) = 3 tools, B up to ceil(5.5) = 6, rest C; the never-issued Tool 11 is C regardless
    assert [n for n, c in cat.items() if c == "A"] == ["Tool 01", "Tool 02", "Tool 03"]
    assert [n for n, c in cat.items() if c == "B"] == ["Tool 04", "Tool 05", "Tool 06"]
    assert cat["Tool 11"] == "C" and res["counts"] == {"A": 3, "B": 3, "C": 5}
    assert "Retired Lathe" not in cat
    # shares are measured against the HISTORICAL total (75), so archiving a tool can never change another tool's percentage
    assert res["rows"][0]["cum_pct"] == pytest.approx(10 / 75 * 100)


@pytest.mark.db
def test_archiving_a_tool_does_not_change_the_historical_total_or_other_shares(abc_world):
    d, admin, ids = abc_world
    before = rs.abc_analysis(admin)
    run(d, "UPDATE tool SET is_archived = 1 WHERE tool_id = %s", (ids[5],))
    after = rs.abc_analysis(admin)
    assert after["historical_total"] == before["historical_total"]                 # history does not shrink
    assert after["n_active"] == before["n_active"] - 1 and after["archived_total"] == before["archived_total"] + 6


@pytest.mark.db
def test_abc_date_range_is_inclusive_and_filters_history(abc_world):
    d, admin, ids = abc_world
    assert rs.abc_analysis(admin, str(TODAY), None)["historical_total"] == 0        # everything was issued 5 days ago
    full = rs.abc_analysis(admin, str(TODAY - timedelta(days=5)), str(TODAY - timedelta(days=5)))
    assert full["historical_total"] == 75                                           # the whole of the end day counts


@pytest.mark.db
def test_pdf_rows_come_from_the_same_service_as_the_screen(abc_world):
    from views.reports import ReportsView
    d, admin, ids = abc_world
    fake = SimpleNamespace(user_info=admin)
    title, labels, rws = ReportsView._export_rows(fake, "abc", None, None)
    screen = rs.abc_analysis(admin)
    assert title.startswith("Inventory ABC") and labels[3] == "Qty Issued"
    assert [r[2] for r in rws[:-1]] == [x["name"] for x in screen["rows"]]
    assert [r[3] for r in rws[:-1]] == [str(x["usage"]) for x in screen["rows"]]
    assert [r[5][0] for r in rws[:-1]] == [x["category"] for x in screen["rows"]]
    assert "Historical total issued" in rws[-1][2] and "75" in rws[-1][2]
    for kind in ("usage", "activity", "allocation", "damage", "lowstock", "overdue"):
        t, l, r = ReportsView._export_rows(fake, kind, None, None)
        assert t and l and isinstance(r, list)


def test_tracking_shows_the_quantity_of_a_consumable_record():
    from views.tracking import _with_quantity
    rows = _with_quantity([{"tool_name": "Grease", "quantity": Decimal("2.50")}, {"tool_name": "Caliper", "quantity": Decimal("1.00")},
                           {"tool_name": "Oil", "quantity": Decimal("3.00")}, {"tool_name": "Old row without quantity"}])
    assert [r["tool_name"] for r in rows] == ["Grease x2.5", "Caliper", "Oil x3", "Old row without quantity"]
