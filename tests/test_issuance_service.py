"""[CONCURRENCY][4-DATE][RBAC][UNHAPPY-PATH] Issuance and retrieval through the service layer, against a real MySQL."""
import threading
from datetime import date, timedelta
from decimal import Decimal

import mysql.connector
import pytest

from services import issuance_service as iss
from services import security, validators as v
from services.errors import Conflict, NotFound, PermissionDenied, ServiceError, friendly_message
from services.stock_ledger import InsufficientStock

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
def w(svc):
    """staff + admin sessions, two workers, an equipment tool (10), a consumable (5.00) and an Approved project that needs
    3 calipers + 2.5 kg grease, with W1 assigned (W2 = WKR-2026-0011 is not)."""
    d = svc
    u = {}
    for key, eid, name, role in [("admin", "ADM-2026-001", "Admin", "Admin"), ("staff", "STF-2026-001", "Stacy", "Staff"),
                                 ("w1", "WKR-2026-001", "Wally", "Worker"), ("w2", "WKR-2026-0011", "Willa", "Worker")]:
        u[key] = run(d, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES (%s,%s,%s,'Active')", (eid, name, role))
    cal = run(d, "INSERT INTO tool (name, tag_id, item_type, `condition`) VALUES ('Caliper','CAL-001','Equipment','Good')")
    grs = run(d, "INSERT INTO tool (name, tag_id, item_type, unit_of_measure) VALUES ('Grease','GRS-001','Consumable','kg')")
    run(d, "INSERT INTO inventory (tool_id, quantity_total, quantity_available) VALUES (%s,10,10), (%s,5,5)", (cal, grs))
    pid = run(d, "INSERT INTO projects (name, client, start_date, end_date, status, workers_assigned) "
                 "VALUES ('Alpha','ACME',%s,%s,'Approved','WKR-2026-001')", (TODAY - timedelta(days=3), TODAY + timedelta(days=30)))
    run(d, "INSERT INTO project_requirements (project_id, tool_id, quantity) VALUES (%s,%s,3), (%s,%s,2.5)", (pid, cal, pid, grs))
    staff = {"user_id": u["staff"]}
    return d, u, staff, cal, grs, pid


def avail(d, tool):
    return rows(d, "SELECT quantity_available AS a FROM inventory WHERE tool_id=%s", (tool,))[0]["a"]


# ---- verify borrower -----------------------------------------------------------------------------------------------
def test_verify_borrower_lists_only_projects_the_worker_is_assigned_to(w):
    d, u, staff, cal, grs, pid = w
    b = iss.verify_borrower(staff, "WKR-2026-001")
    assert b["full_name"] == "Wally" and [p["project_id"] for p in b["projects"]] == [pid]
    # WKR-2026-0011 contains "WKR-2026-001" as a substring: the old LIKE matched it, the junction must not
    assert iss.verify_borrower(staff, "WKR-2026-0011")["projects"] == []


@pytest.mark.parametrize("status", ["Archived", "Inactive", "Locked"])
def test_verify_borrower_rejects_non_active_accounts(w, status):
    d, u, staff, *_ = w
    run(d, "UPDATE `user` SET status=%s WHERE user_id=%s", (status, u["w1"]))
    with pytest.raises(Conflict, match=status):
        iss.verify_borrower(staff, "WKR-2026-001")


def test_verify_borrower_unknown_id(w):
    with pytest.raises(NotFound):
        iss.verify_borrower(w[2], "WKR-2099-999")


# ---- issue: happy path ---------------------------------------------------------------------------------------------
def test_issue_equipment_and_consumable_in_one_transaction(w):
    d, u, staff, cal, grs, pid = w
    res = iss.issue(staff, u["w1"], pid, [{"tool_id": cal, "qty": 3}, {"tool_id": grs, "qty": "2.5"}], "Proj 1: Alpha (ACME)")
    assert len(res.transaction_ids) == 4                          # 3 equipment units + ONE consumable row
    assert res.all_fulfilled and res.project_now_ongoing
    assert avail(d, cal) == 7 and str(avail(d, grs)) == "2.50"
    t = rows(d, "SELECT * FROM `transaction` WHERE tool_id=%s", (grs,))
    assert len(t) == 1 and str(t[0]["quantity"]) == "2.50"         # exact, not rounded up to 3 rows
    cal_rows = rows(d, "SELECT * FROM `transaction` WHERE tool_id=%s", (cal,))
    assert len(cal_rows) == 3 and all(r["quantity"] == 1 and r["issued_by"] == u["staff"] for r in cal_rows)
    assert all(r["due_date"] == TODAY + timedelta(days=30) and r["project_start_date"] == TODAY - timedelta(days=3) for r in cal_rows)
    assert rows(d, "SELECT status FROM projects WHERE project_id=%s", (pid,))[0]["status"] == "Ongoing"
    assert {r["status"] for r in rows(d, "SELECT status FROM project_requirements")} == {"Fulfilled"}


def test_partial_issue_keeps_project_approved_and_requirement_open(w):
    d, u, staff, cal, grs, pid = w
    res = iss.issue(staff, u["w1"], pid, [{"tool_id": cal, "qty": 1}], "p")
    assert not res.all_fulfilled and not res.project_now_ongoing
    assert rows(d, "SELECT status FROM projects")[0]["status"] == "Approved"
    pr = iss.project_requirements(staff, pid)
    assert {r["name"]: (r["req_qty"], r["issued_qty"]) for r in pr["reqs"]}["Caliper"] == (3, 1)


# ---- issue: rules ----------------------------------------------------------------------------------------------
def test_cannot_exceed_approved_quantity(w):
    d, u, staff, cal, grs, pid = w
    iss.issue(staff, u["w1"], pid, [{"tool_id": cal, "qty": 2}], "p")
    with pytest.raises(Conflict, match="approved 3"):
        iss.issue(staff, u["w1"], pid, [{"tool_id": cal, "qty": 2}], "p")
    assert avail(d, cal) == 8


def test_tool_not_on_the_project_is_refused(w):
    d, u, staff, cal, grs, pid = w
    other = run(d, "INSERT INTO tool (name, tag_id) VALUES ('Saw','SAW-001')")
    run(d, "INSERT INTO inventory (tool_id, quantity_total, quantity_available) VALUES (%s,5,5)", (other,))
    with pytest.raises(Conflict, match="not approved"):
        iss.issue(staff, u["w1"], pid, [{"tool_id": other, "qty": 1}], "p")


def test_equipment_must_be_whole_numbers(w):
    d, u, staff, cal, grs, pid = w
    with pytest.raises(v.ValidationError, match="whole"):
        iss.issue(staff, u["w1"], pid, [{"tool_id": cal, "qty": "1.5"}], "p")


def test_worker_not_assigned_to_project_is_refused(w):
    d, u, staff, cal, grs, pid = w
    with pytest.raises(Conflict, match="not assigned"):
        iss.issue(staff, u["w2"], pid, [{"tool_id": cal, "qty": 1}], "p")


def test_archived_borrower_archived_tool_and_closed_project_are_refused(w):
    d, u, staff, cal, grs, pid = w
    run(d, "UPDATE tool SET is_archived=1 WHERE tool_id=%s", (cal,))
    with pytest.raises(Conflict, match="archived"):
        iss.issue(staff, u["w1"], pid, [{"tool_id": cal, "qty": 1}], "p")
    run(d, "UPDATE tool SET is_archived=0 WHERE tool_id=%s", (cal,))
    run(d, "UPDATE `user` SET status='Archived' WHERE user_id=%s", (u["w1"],))
    with pytest.raises(Conflict, match="Archived"):
        iss.issue(staff, u["w1"], pid, [{"tool_id": cal, "qty": 1}], "p")
    run(d, "UPDATE `user` SET status='Active' WHERE user_id=%s", (u["w1"],))
    run(d, "UPDATE projects SET status='Cancelled' WHERE project_id=%s", (pid,))     # a legal edge (Approved -> Cancelled)
    with pytest.raises(Conflict, match="Cancelled"):
        iss.issue(staff, u["w1"], pid, [{"tool_id": cal, "qty": 1}], "p")


def test_project_that_has_ended_refuses_but_staged_early_is_allowed(w):
    d, u, staff, cal, grs, pid = w
    ended = run(d, "INSERT INTO projects (name, start_date, end_date, status, workers_assigned) VALUES ('Old',%s,%s,'Approved','WKR-2026-001')",
                (TODAY - timedelta(days=30), TODAY - timedelta(days=1)))
    run(d, "INSERT INTO project_requirements (project_id, tool_id, quantity) VALUES (%s,%s,1)", (ended, cal))
    with pytest.raises(Conflict, match="ended"):
        iss.issue(staff, u["w1"], ended, [{"tool_id": cal, "qty": 1}], "p")
    future = run(d, "INSERT INTO projects (name, start_date, end_date, status, workers_assigned) VALUES ('Soon',%s,%s,'Approved','WKR-2026-001')",
                 (TODAY + timedelta(days=10), TODAY + timedelta(days=40)))
    run(d, "INSERT INTO project_requirements (project_id, tool_id, quantity) VALUES (%s,%s,1)", (future, cal))
    assert iss.issue(staff, u["w1"], future, [{"tool_id": cal, "qty": 1}], "p").transaction_ids      # staged early


def test_failure_in_the_middle_rolls_everything_back(w):
    d, u, staff, cal, grs, pid = w
    run(d, "UPDATE inventory SET quantity_available = 0, quantity_total = 0 WHERE tool_id=%s", (grs,))
    with pytest.raises(ServiceError):         # line 1 (caliper) is fine, line 2 (grease) has no stock
        iss.issue(staff, u["w1"], pid, [{"tool_id": cal, "qty": 2}, {"tool_id": grs, "qty": "1"}], "p")
    assert avail(d, cal) == 10
    assert rows(d, "SELECT COUNT(*) AS n FROM `transaction`")[0]["n"] == 0


# ---- the race ------------------------------------------------------------------------------------------------------
def test_two_terminals_cannot_issue_the_last_unit_through_the_service(w):
    d, u, staff, cal, grs, pid = w
    run(d, "UPDATE inventory SET quantity_available = 1 WHERE tool_id=%s", (cal,))
    out, barrier = [], threading.Barrier(2, timeout=10)

    def terminal():
        barrier.wait()
        try:
            iss.issue(staff, u["w1"], pid, [{"tool_id": cal, "qty": 1}], "p")
            out.append("issued")
        except (InsufficientStock, Conflict):
            out.append("refused")

    ts = [threading.Thread(target=terminal) for _ in range(2)]
    [t.start() for t in ts]
    [t.join(30) for t in ts]
    assert sorted(out) == ["issued", "refused"], out
    assert avail(d, cal) == 0 and rows(d, "SELECT COUNT(*) AS n FROM `transaction`")[0]["n"] == 1


def test_two_terminals_cannot_together_exceed_the_project_quota(w):
    d, u, staff, cal, grs, pid = w                      # quota is 3 calipers; each terminal asks for 2
    out, barrier = [], threading.Barrier(2, timeout=10)

    def terminal():
        barrier.wait()
        try:
            iss.issue(staff, u["w1"], pid, [{"tool_id": cal, "qty": 2}], "p")
            out.append("issued")
        except Conflict:
            out.append("refused")

    ts = [threading.Thread(target=terminal) for _ in range(2)]
    [t.start() for t in ts]
    [t.join(30) for t in ts]
    assert sorted(out) == ["issued", "refused"], out
    assert rows(d, "SELECT COALESCE(SUM(quantity),0) AS q FROM `transaction`")[0]["q"] == 2


# ---- RBAC ----------------------------------------------------------------------------------------------------------
def test_workers_and_inactive_staff_have_no_session_rights(w):
    d, u, staff, cal, grs, pid = w
    with pytest.raises(PermissionDenied):
        iss.verify_borrower({"user_id": u["w1"]}, "WKR-2026-001")           # a Worker can never act
    run(d, "UPDATE `user` SET status='Archived' WHERE user_id=%s", (u["staff"],))
    with pytest.raises(PermissionDenied, match="not active"):
        iss.verify_borrower(staff, "WKR-2026-001")                          # archived after login: refused on the next call
    with pytest.raises(PermissionDenied):
        iss.verify_borrower({"user_id": 999999}, "WKR-2026-001")
    with pytest.raises(PermissionDenied):
        iss.verify_borrower({}, "WKR-2026-001")


def test_role_is_reread_from_the_database_not_trusted_from_the_session(w):
    d, u, staff, *_ = w

    @security.require_role("Admin")
    def admin_only(actor):
        return actor["role"]

    assert admin_only({"user_id": u["admin"], "role": "Staff"}) == "Admin"     # DB says Admin: allowed whatever the dict says
    with pytest.raises(PermissionDenied):
        admin_only({"user_id": u["staff"], "role": "Admin"})                   # dict claims Admin, DB says Staff: refused
    denied = rows(d, "SELECT action_type, module, details FROM system_logs WHERE action_type='Denied'")
    assert denied and denied[0]["module"] == "Security" and "admin_only" in denied[0]["details"]


# ---- retrieval -----------------------------------------------------------------------------------------------------
@pytest.fixture
def issued(w):
    d, u, staff, cal, grs, pid = w
    iss.issue(staff, u["w1"], pid, [{"tool_id": cal, "qty": 3}, {"tool_id": grs, "qty": "2.5"}], "p")
    return w


def test_find_deployed_by_tag_trn_and_number(issued):
    d, u, staff, cal, grs, pid = issued
    assert iss.find_deployed(staff, u["w1"], "cal-001")["deployed"] == 3
    first = rows(d, "SELECT MIN(transaction_id) AS t FROM `transaction`")[0]["t"]
    assert iss.find_deployed(staff, u["w1"], f"TRN-{first}-{first + 2}")["tool_id"] == cal
    assert iss.find_deployed(staff, u["w1"], str(first))["tool_id"] == cal
    with pytest.raises(NotFound):
        iss.find_deployed(staff, u["w2"], "CAL-001")                       # w2 holds nothing
    with pytest.raises(ServiceError, match="badge"):
        iss.find_deployed(staff, u["w1"], "WKR-2026-001")


def test_good_return_restocks(issued):
    d, u, staff, cal, grs, pid = issued
    res = iss.retrieve(staff, u["w1"], cal, 2, "Good", "")
    assert len(res.closed_ids) == 2 and res.ticket_id is None
    assert avail(d, cal) == 9
    ret = rows(d, "SELECT * FROM `transaction` WHERE status='Returned'")
    assert len(ret) == 2 and all(r["return_date"] >= r["borrow_date"] and r["received_by"] == u["staff"] for r in ret)


def test_damaged_return_creates_the_ticket_inside_the_transaction_and_other_units_stay_issuable(issued):
    d, u, staff, cal, grs, pid = issued
    res = iss.retrieve(staff, u["w1"], cal, 1, "Damaged", "Chuck cracked on first use")
    inv = rows(d, "SELECT * FROM inventory WHERE tool_id=%s", (cal,))[0]
    assert (inv["quantity_total"], inv["quantity_available"], inv["quantity_in_maintenance"]) == (10, 7, 1)
    t = rows(d, "SELECT * FROM tool_issues WHERE issue_id=%s", (res.ticket_id,))[0]
    assert (t["status"], t["condition_flag"], t["quantity"], t["reported_by_user_id"]) == ("Open", "Damaged", 1, u["staff"])
    assert t["transaction_id"] == res.closed_ids[0] and "cracked" in t["notes"]
    assert rows(d, "SELECT `condition` AS c FROM tool WHERE tool_id=%s", (cal,))[0]["c"] == "Damaged"      # display flag
    # one damaged unit must NOT block the others: a second project can still draw from the remaining 7
    p2 = run(d, "INSERT INTO projects (name, start_date, end_date, status, workers_assigned) VALUES ('B',%s,%s,'Approved','WKR-2026-001')",
             (TODAY, TODAY + timedelta(days=9)))
    run(d, "INSERT INTO project_requirements (project_id, tool_id, quantity) VALUES (%s,%s,2)", (p2, cal))
    assert iss.issue(staff, u["w1"], p2, [{"tool_id": cal, "qty": 2}], "p").transaction_ids
    assert iss.lookup_tool(staff, "CAL-001").available == 5
    # a later GOOD return must not hide the damaged unit
    iss.retrieve(staff, u["w1"], cal, 1, "Good", "")
    assert rows(d, "SELECT `condition` AS c FROM tool WHERE tool_id=%s", (cal,))[0]["c"] == "Damaged"


def test_lost_return_leaves_the_total_and_counts_the_loss(issued):
    d, u, staff, cal, grs, pid = issued
    res = iss.retrieve(staff, u["w1"], cal, 1, "Lost", "Left on site B")
    inv = rows(d, "SELECT * FROM inventory WHERE tool_id=%s", (cal,))[0]
    assert (inv["quantity_total"], inv["quantity_available"], inv["quantity_lost"]) == (9, 7, 1)
    assert rows(d, "SELECT condition_flag FROM tool_issues WHERE issue_id=%s", (res.ticket_id,))[0]["condition_flag"] == "Lost"


@pytest.mark.parametrize("cond", ["Damaged", "Needs Repair", "Lost"])
def test_condition_details_are_required_for_anything_but_good(issued, cond):
    d, u, staff, cal, *_ = issued
    for notes in ("", "   ", None):
        with pytest.raises(v.ValidationError, match="required"):
            iss.retrieve(staff, u["w1"], cal, 1, cond, notes)
    assert rows(d, "SELECT COUNT(*) AS n FROM `transaction` WHERE status='Returned'")[0]["n"] == 0


def test_invalid_condition_and_quantities(issued):
    d, u, staff, cal, grs, pid = issued
    with pytest.raises(v.ValidationError):
        iss.retrieve(staff, u["w1"], cal, 1, "Broken-ish", "x")
    with pytest.raises(Conflict, match="only 3"):
        iss.retrieve(staff, u["w1"], cal, 4, "Good", "")
    with pytest.raises(v.ValidationError, match="whole"):
        iss.retrieve(staff, u["w1"], cal, "1.5", "Good", "")
    with pytest.raises(v.ValidationError):
        iss.retrieve(staff, u["w1"], cal, 0, "Good", "")


def test_partial_consumable_return_splits_the_line_and_keeps_exact_stock(issued):
    d, u, staff, cal, grs, pid = issued                       # 2.5 kg issued in ONE row
    iss.retrieve(staff, u["w1"], grs, "1.25", "Good", "")
    assert str(avail(d, grs)) == "3.75"
    t = rows(d, "SELECT quantity, status FROM `transaction` WHERE tool_id=%s ORDER BY transaction_id", (grs,))
    assert [(str(r["quantity"]), r["status"]) for r in t] == [("1.25", "Active"), ("1.25", "Returned")]
    assert iss.find_deployed(staff, u["w1"], "GRS-001")["deployed"] == Decimal("1.25")
    iss.retrieve(staff, u["w1"], grs, "1.25", "Good", "")
    assert str(avail(d, grs)) == "5.00"


def test_return_failure_rolls_back_rows_stock_and_ticket(issued, monkeypatch):
    d, u, staff, cal, grs, pid = issued

    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(iss, "refresh_tool_condition", boom)
    with pytest.raises(RuntimeError):
        iss.retrieve(staff, u["w1"], cal, 2, "Damaged", "chipped")
    assert avail(d, cal) == 7
    assert rows(d, "SELECT COUNT(*) AS n FROM `transaction` WHERE status='Returned'")[0]["n"] == 0
    assert rows(d, "SELECT COUNT(*) AS n FROM tool_issues")[0]["n"] == 0
    assert rows(d, "SELECT quantity_in_maintenance AS m FROM inventory WHERE tool_id=%s", (cal,))[0]["m"] == 0


def test_returning_after_the_project_ended_still_works(w):
    """The end-date rule applies to ISSUING only: a tool still out on a project that ended 5 days ago must always be returnable."""
    d, u, staff, cal, grs, pid = w
    ended = run(d, "INSERT INTO projects (name, start_date, end_date, status, workers_assigned) VALUES ('Ended',%s,%s,'Ongoing','WKR-2026-001')",
                (TODAY - timedelta(days=30), TODAY - timedelta(days=5)))
    run(d, "INSERT INTO `transaction` (tool_id, user_id, project_id, type, status, quantity, borrow_date) "
           "VALUES (%s,%s,%s,'Issue','Active',1, NOW() - INTERVAL 10 DAY)", (cal, u["w1"], ended))
    run(d, "UPDATE inventory SET quantity_available = 9 WHERE tool_id=%s", (cal,))
    res = iss.retrieve(staff, u["w1"], cal, 1, "Good", "")
    assert res.closed_ids and avail(d, cal) == 10
    t = rows(d, "SELECT status, due_date FROM `transaction` WHERE transaction_id=%s", (res.closed_ids[0],))[0]
    assert t["status"] == "Returned" and t["due_date"] == TODAY - timedelta(days=5)      # the snapshot is kept; it was returned late


def test_friendly_messages_never_leak_driver_text(w):
    d, u, staff, cal, grs, pid = w
    iss.issue(staff, u["w1"], pid, [{"tool_id": cal, "qty": 1}], "p")
    for sql, arg, expect in [("UPDATE projects SET end_date = end_date + INTERVAL 5 DAY WHERE project_id = %s", pid, "locked"),
                             ("DELETE FROM `user` WHERE user_id = %s", u["w1"], "linked")]:
        with pytest.raises(mysql.connector.Error) as e:
            run(d, sql, (arg,))
        msg = friendly_message(e.value)
        assert expect in msg and "CHAMPION" not in msg and "1451" not in msg and "(23000)" not in msg
    assert "nothing was saved" in friendly_message(RuntimeError("x")).lower()


# ---- "No projects needing tools" must say WHY --------------------------------------------------------------------------
def test_verify_borrower_explains_why_a_project_is_not_offered(w):
    d, u, staff, cal, grs, pid = w
    ended = run(d, "INSERT INTO projects (name, start_date, end_date, status, workers_assigned) VALUES ('Old Job',%s,%s,'Ongoing','WKR-2026-0011')",
                (TODAY - timedelta(days=60), TODAY - timedelta(days=30)))
    pending = run(d, "INSERT INTO projects (name, start_date, end_date, status, workers_assigned) VALUES ('Draft Job',%s,%s,'Pending','WKR-2026-0011')",
                  (TODAY, TODAY + timedelta(days=9)))
    done = run(d, "INSERT INTO projects (name, start_date, end_date, status, workers_assigned) VALUES ('Done Job',%s,%s,'Approved','WKR-2026-0011')",
               (TODAY - timedelta(days=2), TODAY + timedelta(days=9)))
    run(d, "INSERT INTO project_requirements (project_id, tool_id, quantity, status) VALUES (%s,%s,1,'Fulfilled')", (done, cal))
    run(d, "UPDATE projects SET status='Ongoing' WHERE project_id=%s", (done,))                 # lines are locked once it is Ongoing
    b = iss.verify_borrower(staff, "WKR-2026-0011")
    assert b["projects"] == []
    text = " | ".join(b["notices"])
    assert f"'Old Job' ended on {TODAY - timedelta(days=30)}" in text
    assert "'Draft Job' is still waiting for approval" in text
    assert "'Done Job': all of its required tools have already been issued" in text


def test_verify_borrower_for_someone_on_no_project_at_all(w):
    d, u, staff, cal, grs, pid = w
    run(d, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('WKR-2026-077','Nobody','Worker','Active')")
    b = iss.verify_borrower(staff, "WKR-2026-077")
    assert b["projects"] == [] and b["notices"] == ["This employee is not assigned to any active project."]
