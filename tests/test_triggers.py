"""Database-side business rules, exercised with raw SQL exactly as a stale terminal or a DBA could run it."""
from datetime import date, timedelta

import mysql.connector
import pytest

pytestmark = pytest.mark.db

TODAY = date.today()


def fail(db, sql, params=(), match="CHAMPION"):
    """Run sql in its own transaction and assert the database refuses it with a CHAMPION: message."""
    with pytest.raises(mysql.connector.Error) as e:
        with db.transaction() as cur:
            cur.execute(sql, params)
    assert match in str(e.value), str(e.value)


def run(db, sql, params=()):
    with db.transaction() as cur:
        cur.execute(sql, params)
        try:
            return cur.lastrowid
        except Exception:
            return None


def one(db, sql, params=()):
    with db.read() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


@pytest.fixture
def world(fresh_db):
    """admin, two workers, one tool with stock, and helpers to create projects."""
    d = fresh_db
    uid = {}
    for eid, name, role in [("ADM-2026-001", "Admin", "Admin"), ("WKR-2026-001", "Wally", "Worker"), ("WKR-2026-0011", "Willa", "Worker")]:
        uid[eid] = run(d, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES (%s,%s,%s,'Active')", (eid, name, role))
    tool = run(d, "INSERT INTO tool (name, tag_id, item_type) VALUES ('Caliper','CAL-001','Equipment')")
    run(d, "INSERT INTO inventory (tool_id, quantity_total, quantity_available) VALUES (%s, 10, 10)", (tool,))

    def project(status="Approved", start=None, end=None, workers=None):
        start = start or TODAY - timedelta(days=5)
        end = end or TODAY + timedelta(days=30)
        return run(d, "INSERT INTO projects (name, start_date, end_date, status, workers_assigned) VALUES ('P',%s,%s,%s,%s)",
                   (start, end, status, workers))

    def issue(pid, user="WKR-2026-001", **kw):
        cols = {"tool_id": tool, "user_id": uid[user], "project_id": pid, "type": "Issue", "status": "Active"}
        cols.update(kw)
        keys = ",".join(cols)
        return run(d, f"INSERT INTO `transaction` ({keys}) VALUES ({','.join(['%s'] * len(cols))})", tuple(cols.values()))

    return d, uid, tool, project, issue


# ---- project dates / state machine --------------------------------------------------------------------------------
def test_project_start_after_end_is_rejected(world):
    d, _, _, project, _ = world
    with pytest.raises(mysql.connector.Error):
        project(start=TODAY + timedelta(days=2), end=TODAY)


def test_allowed_and_forbidden_status_transitions(world):
    d, _, _, project, _ = world
    pid = project(status="Pending")
    fail(d, "UPDATE projects SET status='Ongoing' WHERE project_id=%s", (pid,), "not allowed")      # skipping Approved
    run(d, "UPDATE projects SET status='Approved' WHERE project_id=%s", (pid,))
    run(d, "UPDATE projects SET status='Ongoing' WHERE project_id=%s", (pid,))
    fail(d, "UPDATE projects SET status='Pending' WHERE project_id=%s", (pid,), "not allowed")      # no way back
    run(d, "UPDATE projects SET status='Completed' WHERE project_id=%s", (pid,))
    fail(d, "UPDATE projects SET status='Approved' WHERE project_id=%s", (pid,), "not allowed")     # Completed is final
    assert one(d, "SELECT status FROM projects WHERE project_id=%s", (pid,))["status"] == "Completed"


def test_decline_and_cancel_paths(world):
    d, _, _, project, _ = world
    a = project(status="Pending")
    run(d, "UPDATE projects SET status='Declined' WHERE project_id=%s", (a,))
    b = project(status="Approved")
    run(d, "UPDATE projects SET status='Cancelled' WHERE project_id=%s", (b,))
    c = project(status="Ongoing")
    run(d, "UPDATE projects SET status='Cancelled' WHERE project_id=%s", (c,))      # existing Admin feature is kept


def test_archive_only_finished_projects_and_restore_returns_prior_status(world):
    d, _, _, project, _ = world
    active = project(status="Approved")
    fail(d, "UPDATE projects SET archived_at=NOW() WHERE project_id=%s", (active,), "archived")
    done = project(status="Ongoing")
    run(d, "UPDATE projects SET status='Completed' WHERE project_id=%s", (done,))
    run(d, "UPDATE projects SET archived_at=NOW() WHERE project_id=%s", (done,))
    row = one(d, "SELECT status, status_before_archive AS sba, is_archived FROM projects WHERE project_id=%s", (done,))
    assert (row["status"], row["sba"], row["is_archived"]) == ("Completed", "Completed", 1)
    # the OLD Maintenance screen restores with exactly this statement (bug: it reopened projects as Approved)
    run(d, "UPDATE projects SET status='Approved', archived_at=NULL WHERE project_id=%s", (done,))
    row = one(d, "SELECT status, archived_at, is_archived FROM projects WHERE project_id=%s", (done,))
    assert row["status"] == "Completed" and row["archived_at"] is None and row["is_archived"] == 0


# ---- locks --------------------------------------------------------------------------------------------------------
def test_dates_and_workers_editable_while_approved_without_issuance(world):
    d, _, _, project, _ = world
    pid = project(status="Approved")
    run(d, "UPDATE projects SET end_date=%s, workers_assigned='WKR-2026-001' WHERE project_id=%s", (TODAY + timedelta(days=60), pid))


@pytest.mark.parametrize("status", ["Ongoing", "Completed"])
def test_dates_and_workers_locked_for_ongoing_and_completed(world, status):
    d, _, _, project, _ = world
    pid = project(status=status)
    fail(d, "UPDATE projects SET end_date=%s WHERE project_id=%s", (TODAY + timedelta(days=99), pid), "locked")
    fail(d, "UPDATE projects SET start_date=%s WHERE project_id=%s", (TODAY - timedelta(days=99), pid), "locked")
    fail(d, "UPDATE projects SET workers_assigned='WKR-2026-001' WHERE project_id=%s", (pid,), "locked")
    run(d, "UPDATE projects SET name='Renamed' WHERE project_id=%s", (pid,))        # non-schedule fields stay editable


def test_dates_locked_once_any_tool_was_issued_even_if_status_is_approved(world):
    d, _, _, project, issue = world
    pid = project(status="Approved")
    issue(pid)
    fail(d, "UPDATE projects SET end_date=%s WHERE project_id=%s", (TODAY + timedelta(days=99), pid), "locked")


def test_requirements_frozen_for_ongoing_and_issued_projects_but_fulfilled_flag_still_works(world):
    d, _, tool, project, issue = world
    pid = project(status="Approved")
    rid = run(d, "INSERT INTO project_requirements (project_id, tool_id, quantity) VALUES (%s,%s,2)", (pid, tool))
    run(d, "UPDATE project_requirements SET quantity=3 WHERE req_id=%s", (rid,))                     # still editable
    issue(pid)                                                                                        # first issuance
    fail(d, "UPDATE project_requirements SET quantity=9 WHERE req_id=%s", (rid,), "locked")
    fail(d, "DELETE FROM project_requirements WHERE project_id=%s", (pid,), "locked")                # old delete-and-reinsert edit
    fail(d, "INSERT INTO project_requirements (project_id, tool_id, quantity) VALUES (%s,%s,1)", (pid, tool), "locked")
    run(d, "UPDATE project_requirements SET status='Fulfilled' WHERE req_id=%s", (rid,))             # issuance still marks lines done
    assert one(d, "SELECT status, quantity FROM project_requirements WHERE req_id=%s", (rid,)) == {"status": "Fulfilled", "quantity": 3}


def test_requirements_frozen_by_status_alone(world):
    d, _, tool, project, _ = world
    pid = project(status="Ongoing")
    fail(d, "INSERT INTO project_requirements (project_id, tool_id, quantity) VALUES (%s,%s,1)", (pid, tool), "locked")


# ---- the four dates --------------------------------------------------------------------------------------------
def test_issuance_copies_project_dates_and_uses_server_clock(world):
    d, _, _, project, issue = world
    pid = project(status="Ongoing")
    tid = issue(pid)
    t = one(d, "SELECT project_start_date AS s, due_date AS e, borrow_date AS b, NOW() AS now FROM `transaction` WHERE transaction_id=%s", (tid,))
    assert t["s"] == TODAY - timedelta(days=5) and t["e"] == TODAY + timedelta(days=30)
    assert abs((t["now"] - t["b"]).total_seconds()) < 5


def test_cannot_issue_to_a_project_that_has_ended(world):
    d, _, _, project, issue = world
    pid = project(status="Ongoing", start=TODAY - timedelta(days=30), end=TODAY - timedelta(days=1))
    with pytest.raises(mysql.connector.Error) as e:
        issue(pid)
    assert "ended" in str(e.value)


def test_early_staging_before_start_date_is_allowed(world):
    d, _, _, project, issue = world
    pid = project(status="Approved", start=TODAY + timedelta(days=10), end=TODAY + timedelta(days=40))
    assert issue(pid)          # Issuance < Start is deliberately allowed ("staged early"); a literal rule would block top-ups


def test_snapshots_survive_a_later_project_edit_and_cannot_be_rewritten(world):
    d, _, _, project, issue = world
    pid = project(status="Approved")
    tid = issue(pid)
    snap = one(d, "SELECT due_date FROM `transaction` WHERE transaction_id=%s", (tid,))["due_date"]
    fail(d, "UPDATE `transaction` SET due_date=%s WHERE transaction_id=%s", (TODAY + timedelta(days=500), tid), "snapshot")
    fail(d, "UPDATE `transaction` SET project_start_date=%s WHERE transaction_id=%s", (TODAY, tid), "snapshot")
    fail(d, "UPDATE `transaction` SET borrow_date=%s WHERE transaction_id=%s", (TODAY - timedelta(days=9), tid), "issuance date")
    assert one(d, "SELECT due_date FROM `transaction` WHERE transaction_id=%s", (tid,))["due_date"] == snap


def test_return_gets_server_time_and_cannot_precede_issuance(world):
    d, _, _, project, issue = world
    pid = project(status="Ongoing")
    tid = issue(pid)
    fail(d, "UPDATE `transaction` SET return_date = borrow_date - INTERVAL 1 DAY, status='Returned' WHERE transaction_id=%s", (tid,), "earlier")
    run(d, "UPDATE `transaction` SET status='Returned', type='Retrieval' WHERE transaction_id=%s", (tid,))
    t = one(d, "SELECT return_date, borrow_date FROM `transaction` WHERE transaction_id=%s", (tid,))
    assert t["return_date"] is not None and t["return_date"] >= t["borrow_date"]


def test_non_positive_quantity_rejected(world):
    d, _, _, project, issue = world
    pid = project(status="Ongoing")
    with pytest.raises(mysql.connector.Error):
        issue(pid, quantity=0)


# ---- history is protected --------------------------------------------------------------------------------------
def test_users_and_tools_with_history_cannot_be_hard_deleted(world):
    d, uid, tool, project, issue = world
    issue(project(status="Ongoing"))
    for sql, params in [("DELETE FROM `user` WHERE user_id=%s", (uid["WKR-2026-001"],)), ("DELETE FROM tool WHERE tool_id=%s", (tool,))]:
        with pytest.raises(mysql.connector.IntegrityError):
            run(d, sql, params)


def test_inventory_check_constraints(world):
    d, _, tool, _, _ = world
    for sql in ["UPDATE inventory SET quantity_available = 11 WHERE tool_id=%s",        # more available than owned
                "UPDATE inventory SET quantity_available = -1 WHERE tool_id=%s",
                "UPDATE inventory SET quantity_in_maintenance = -1 WHERE tool_id=%s"]:
        with pytest.raises(mysql.connector.Error):
            run(d, sql, (tool,))


# ---- worker junction and issue sync ---------------------------------------------------------------------------------
def test_worker_junction_follows_the_legacy_list_with_exact_matching(world):
    d, uid, _, project, _ = world
    pid = project(status="Pending", workers="WKR-2026-0011")
    rows = {r["employee_id"] for r in _rows(d, "SELECT u.employee_id FROM project_workers pw JOIN `user` u USING (user_id) WHERE pw.project_id=%s", (pid,))}
    assert rows == {"WKR-2026-0011"}                    # the old LIKE '%WKR-2026-001%' would also have matched this worker
    run(d, "UPDATE projects SET workers_assigned='WKR-2026-001, nobody' WHERE project_id=%s", (pid,))
    rows = {r["employee_id"] for r in _rows(d, "SELECT u.employee_id FROM project_workers pw JOIN `user` u USING (user_id) WHERE pw.project_id=%s", (pid,))}
    assert rows == {"WKR-2026-001"}


def _rows(db, sql, params=()):
    with db.read() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def test_issue_resolved_flag_and_status_stay_in_sync(world):
    d, _, tool, _, _ = world
    a = run(d, "INSERT INTO tool_issues (tool_id, condition_flag) VALUES (%s,'Damaged')", (tool,))
    b = run(d, "INSERT INTO tool_issues (tool_id, condition_flag) VALUES (%s,'Damaged')", (tool,))
    run(d, "UPDATE tool_issues SET is_resolved=1 WHERE issue_id=%s", (a,))                # old screen
    run(d, "UPDATE tool_issues SET status='Resolved', resolved_by=NULL WHERE issue_id=%s", (b,))   # new service
    for i in (a, b):
        r = one(d, "SELECT status, is_resolved, resolved_at FROM tool_issues WHERE issue_id=%s", (i,))
        assert (r["status"], r["is_resolved"]) == ("Resolved", 1) and r["resolved_at"] is not None


def test_cache_columns_move_on_change(world):
    d, _, tool, _, _ = world
    before = one(d, "SELECT updated_at FROM inventory WHERE tool_id=%s", (tool,))["updated_at"]
    import time; time.sleep(0.01)
    run(d, "UPDATE inventory SET quantity_available = quantity_available - 1 WHERE tool_id=%s", (tool,))
    assert one(d, "SELECT updated_at FROM inventory WHERE tool_id=%s", (tool,))["updated_at"] > before
