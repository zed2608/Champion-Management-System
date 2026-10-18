"""[STATE-MACHINE][4-DATE][RBAC][CONCURRENCY] Project lifecycle through the service layer, against a real MySQL."""
import threading
from datetime import date, timedelta

import mysql.connector
import pytest

from services import issuance_service as iss
from services import project_service as ps
from services import validators as v
from services.errors import Conflict, NotFound, PermissionDenied, friendly_message

pytestmark = pytest.mark.db
TODAY = date.today()
S = lambda d: d.isoformat()


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
                                 ("w1", "WKR-2026-001", "Wally", "Worker"), ("w2", "WKR-2026-0011", "Willa", "Worker")]:
        u[key] = run(d, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES (%s,%s,%s,'Active')", (eid, name, role))
    cal = run(d, "INSERT INTO tool (name, tag_id, item_type) VALUES ('Caliper','CAL-001','Equipment')")
    grs = run(d, "INSERT INTO tool (name, tag_id, item_type, unit_of_measure) VALUES ('Grease','GRS-001','Consumable','kg')")
    run(d, "INSERT INTO inventory (tool_id, quantity_total, quantity_available) VALUES (%s,10,10), (%s,5,5)", (cal, grs))
    admin, staff = {"user_id": u["admin"]}, {"user_id": u["staff"]}

    def data(**over):
        base = dict(name="Alpha Retool", client="ACME", project_head="Pat", location="Site A", description="d",
                    start_date=S(TODAY - timedelta(days=2)), end_date=S(TODAY + timedelta(days=30)), workers=["WKR-2026-001"],
                    requirements=[{"tool_id": cal, "qty": 3}, {"tool_id": grs, "qty": "2.5"}])
        base.update(over)
        return base
    return d, u, admin, staff, cal, grs, data


def status(d, pid):
    return rows(d, "SELECT status FROM projects WHERE project_id=%s", (pid,))[0]["status"]


# ---- create ---------------------------------------------------------------------------------------------------------
def test_admin_created_project_is_auto_approved_with_workers_and_lines(w):
    d, u, admin, staff, cal, grs, data = w
    r = ps.create_project(admin, data(requirements=[{"tool_id": cal, "qty": 3, "needs_retrieval": True}, {"tool_id": grs, "qty": "2.5"}]))
    assert r["status"] == "Approved"                                              # no separate approve step
    p = rows(d, "SELECT * FROM projects WHERE project_id=%s", (r["project_id"],))[0]
    assert (p["status"], p["approved_by"], p["manager_id"], p["workers_assigned"]) == ("Approved", u["admin"], u["admin"], "WKR-2026-001")
    assert [x["user_id"] for x in rows(d, "SELECT user_id FROM project_workers WHERE project_id=%s", (r["project_id"],))] == [u["w1"]]
    lines = {x["tool_id"]: (str(x["quantity"]), x["status"]) for x in rows(d, "SELECT * FROM project_requirements")}
    assert lines == {cal: ("3.00", "Warning"), grs: ("2.50", "Clear")}


def test_staff_have_read_only_project_management(w):
    d, u, admin, staff, cal, grs, data = w
    with pytest.raises(PermissionDenied):
        ps.create_project(staff, data())
    pid = ps.create_project(admin, data())["project_id"]
    for call in (lambda: ps.update_project(staff, pid, data(), "Approved"), lambda: ps.transition(staff, pid, "Ongoing", "Approved"),
                 lambda: ps.archive_project(staff, pid, "Approved"), lambda: ps.restore_project(staff, pid)):
        with pytest.raises(PermissionDenied):
            call()
    assert status(d, pid) == "Approved"


def test_create_validation(w):
    d, u, admin, staff, cal, grs, data = w
    cases = [
        (dict(start_date=S(TODAY + timedelta(days=5)), end_date=S(TODAY)), "on or before"),
        (dict(start_date="05/01/2026"), "YYYY-MM-DD"),
        (dict(name="  "), "required"),
        (dict(client=""), "required"),
        (dict(workers=["WKR-2099-999"]), "not found"),
        (dict(requirements=[]), "at least one"),
        (dict(requirements=[{"tool_id": cal, "qty": "1.5"}]), "whole"),
        (dict(requirements=[{"tool_id": cal, "qty": "0"}]), "greater than zero"),
        (dict(requirements=[{"tool_id": 9999, "qty": 1}]), "no longer exists"),
    ]
    for over, text in cases:
        with pytest.raises(v.ValidationError, match=text):
            ps.create_project(admin, data(**over))
    assert rows(d, "SELECT COUNT(*) AS n FROM projects")[0]["n"] == 0                   # nothing half-created
    run(d, "UPDATE `user` SET status='Archived' WHERE user_id=%s", (u["w1"],))
    with pytest.raises(v.ValidationError, match="Archived"):
        ps.create_project(admin, data())
    run(d, "UPDATE `user` SET status='Active' WHERE user_id=%s", (u["w1"],))
    run(d, "UPDATE tool SET is_archived=1 WHERE tool_id=%s", (grs,))
    with pytest.raises(v.ValidationError, match="archived"):
        ps.create_project(admin, data())


def test_duplicate_names_and_similar_name_helper(w):
    d, u, admin, staff, cal, grs, data = w
    ps.create_project(admin, data())
    with pytest.raises(Conflict, match="already exists"):
        ps.create_project(admin, data(name="alpha retool"))
    exact, similar = ps.find_similar_names("Alpha Retoool")
    assert not exact and similar == ["Alpha Retool"]


def test_duplicate_workers_and_merged_lines(w):
    d, u, admin, staff, cal, grs, data = w
    r = ps.create_project(admin, data(workers=["WKR-2026-001", "wkr-2026-001"], requirements=[{"tool_id": cal, "qty": 1}, {"tool_id": cal, "qty": 2}]))
    assert len(rows(d, "SELECT * FROM project_workers WHERE project_id=%s", (r["project_id"],))) == 1
    assert str(rows(d, "SELECT quantity FROM project_requirements")[0]["quantity"]) == "3.00"


# ---- edit -------------------------------------------------------------------------------------------------------------
def test_edit_diffs_lines_and_keeps_the_fulfilled_flag(w):
    d, u, admin, staff, cal, grs, data = w
    pid = ps.create_project(admin, data())["project_id"]
    run(d, "UPDATE project_requirements SET status='Fulfilled' WHERE tool_id=%s", (cal,))     # as if the caliper line were done
    ps.update_project(admin, pid, data(name="Alpha Retool v2", requirements=[{"tool_id": cal, "qty": 3}, {"tool_id": grs, "qty": "4"}]), "Approved")
    lines = {x["tool_id"]: (str(x["quantity"]), x["status"]) for x in rows(d, "SELECT * FROM project_requirements")}
    assert lines[cal] == ("3.00", "Fulfilled")                    # unchanged line untouched (the old delete-and-reinsert reset it)
    assert lines[grs] == ("4.00", "Clear")
    assert rows(d, "SELECT name FROM projects")[0]["name"] == "Alpha Retool v2"


def test_edit_adds_and_removes_lines_and_workers(w):
    d, u, admin, staff, cal, grs, data = w
    pid = ps.create_project(admin, data())["project_id"]
    ps.update_project(admin, pid, data(workers=["WKR-2026-0011"], requirements=[{"tool_id": grs, "qty": 1}]), "Approved")
    assert [x["tool_id"] for x in rows(d, "SELECT tool_id FROM project_requirements")] == [grs]
    assert [x["user_id"] for x in rows(d, "SELECT user_id FROM project_workers WHERE project_id=%s", (pid,))] == [u["w2"]]
    assert rows(d, "SELECT workers_assigned AS w FROM projects")[0]["w"] == "WKR-2026-0011"


def test_stale_screen_cannot_overwrite_a_newer_state(w):
    d, u, admin, staff, cal, grs, data = w
    pid = ps.create_project(admin, data())["project_id"]
    ps.transition(admin, pid, "Ongoing", "Approved")                                   # another admin moves it on
    with pytest.raises(Conflict, match="changed by someone else.*Ongoing"):
        ps.update_project(admin, pid, data(name="Stale edit"), "Approved")             # this screen still thinks it is Approved
    with pytest.raises(Conflict, match="changed by someone else"):
        ps.transition(admin, pid, "Cancelled", "Approved")
    assert status(d, pid) == "Ongoing" and rows(d, "SELECT name FROM projects")[0]["name"] == "Alpha Retool"


def test_after_issuing_only_descriptive_fields_can_change(w):
    d, u, admin, staff, cal, grs, data = w
    pid = ps.create_project(admin, data())["project_id"]
    iss.issue(admin, u["w1"], pid, [{"tool_id": cal, "qty": 1}], "p")                  # one tool out: still Approved, but issued
    assert status(d, pid) == "Approved"
    for over in (dict(end_date=S(TODAY + timedelta(days=60))), dict(workers=["WKR-2026-001", "WKR-2026-0011"]),
                 dict(requirements=[{"tool_id": cal, "qty": 9}, {"tool_id": grs, "qty": "2.5"}])):
        with pytest.raises(Conflict, match="already been issued"):
            ps.update_project(admin, pid, data(**over), "Approved")
    ps.update_project(admin, pid, data(name="Renamed", client="New client", description="x"), "Approved")
    assert rows(d, "SELECT name, client FROM projects")[0] == {"name": "Renamed", "client": "New client"}
    assert len(rows(d, "SELECT * FROM project_requirements")) == 2                    # lines intact


def test_ongoing_and_finished_projects_cannot_be_edited(w):
    d, u, admin, staff, cal, grs, data = w
    pid = ps.create_project(admin, data())["project_id"]
    ps.transition(admin, pid, "Ongoing", "Approved")
    with pytest.raises(Conflict, match="This project is Ongoing and can no longer be edited"):
        ps.update_project(admin, pid, data(), "Ongoing")


def test_trigger_message_for_editing_dates_of_an_ongoing_project_is_a_plain_sentence(w):
    """The same rule when someone bypasses the service with raw SQL."""
    d, u, admin, staff, cal, grs, data = w
    pid = ps.create_project(admin, data())["project_id"]
    ps.transition(admin, pid, "Ongoing", "Approved")
    with pytest.raises(mysql.connector.Error) as e:
        run(d, "UPDATE projects SET end_date = end_date + INTERVAL 9 DAY WHERE project_id=%s", (pid,))
    assert friendly_message(e.value) == "Dates and workers are locked once a project is Ongoing or Completed, or has issued tools."


# ---- state machine ---------------------------------------------------------------------------------------------------
def test_status_machine_allowed_and_refused_edges(w):
    d, u, admin, staff, cal, grs, data = w
    pid = ps.create_project(admin, data())["project_id"]
    with pytest.raises(Conflict, match="cannot be changed to Pending"):
        ps.transition(admin, pid, "Pending", "Approved")                               # no way back
    with pytest.raises(Conflict, match="cannot be changed to Completed"):
        ps.transition(admin, pid, "Completed", "Approved")                             # must go through Ongoing
    assert ps.transition(admin, pid, "Ongoing", "Approved")["status"] == "Ongoing"
    assert ps.transition(admin, pid, "Completed", "Ongoing")["was"] == "Ongoing"
    with pytest.raises(Conflict):
        ps.transition(admin, pid, "Ongoing", "Completed")
    with pytest.raises(NotFound):
        ps.transition(admin, 9999, "Ongoing", "Approved")


def test_pending_can_be_approved_or_declined_and_declined_is_a_real_status(w):
    d, u, admin, staff, cal, grs, data = w
    a = run(d, "INSERT INTO projects (name, client, status) VALUES ('Draft A','x','Pending')")
    b = run(d, "INSERT INTO projects (name, client, status) VALUES ('Draft B','x','Pending')")
    assert ps.transition(admin, a, "Approved", "Pending")["status"] == "Approved"
    assert rows(d, "SELECT approved_by FROM projects WHERE project_id=%s", (a,))[0]["approved_by"] == u["admin"]
    assert ps.transition(admin, b, "Declined", "Pending")["status"] == "Declined"        # no longer stored as Cancelled
    with pytest.raises(Conflict, match="cannot be changed to Cancelled"):
        ps.transition(admin, run(d, "INSERT INTO projects (name, client, status) VALUES ('Draft C','x','Pending')"), "Cancelled", "Pending")


def test_cannot_cancel_or_complete_while_tools_are_deployed(w):
    d, u, admin, staff, cal, grs, data = w
    pid = ps.create_project(admin, data())["project_id"]
    iss.issue(admin, u["w1"], pid, [{"tool_id": cal, "qty": 2}], "p")
    ps.transition(admin, pid, "Ongoing", "Approved")
    for target in ("Cancelled", "Completed"):
        with pytest.raises(Conflict, match="2 tool.*deployed"):
            ps.transition(admin, pid, target, "Ongoing")
    iss.retrieve(admin, u["w1"], cal, 2, "Good", "")
    assert ps.transition(admin, pid, "Cancelled", "Ongoing")["status"] == "Cancelled"


def test_two_admins_changing_status_at_once_one_wins(w):
    d, u, admin, staff, cal, grs, data = w
    pid = ps.create_project(admin, data())["project_id"]
    out, barrier = [], threading.Barrier(2, timeout=10)

    def go(target):
        barrier.wait()
        try:
            ps.transition(admin, pid, target, "Approved")
            out.append(target)
        except Conflict:
            out.append("refused")

    ts = [threading.Thread(target=go, args=(t,)) for t in ("Ongoing", "Cancelled")]
    [t.start() for t in ts]
    [t.join(30) for t in ts]
    assert out.count("refused") == 1 and (set(out) - {"refused"}) <= {"Ongoing", "Cancelled"} and len(out) == 2, out
    winner = [o for o in out if o != "refused"][0]
    assert status(d, pid) == winner                               # the stored status is exactly the one that won


# ---- archive / restore -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("path", [("Completed", ["Ongoing", "Completed"]), ("Cancelled", ["Cancelled"]), ("Declined", None)])
def test_restore_returns_to_the_status_before_archiving(w, path):
    d, u, admin, staff, cal, grs, data = w
    final, steps = path
    if final == "Declined":
        pid = run(d, "INSERT INTO projects (name, client, status) VALUES ('Draft','x','Pending')")
        ps.transition(admin, pid, "Declined", "Pending")
    else:
        pid = ps.create_project(admin, data())["project_id"]
        cur_status = "Approved"
        for st in steps:
            ps.transition(admin, pid, st, cur_status)
            cur_status = st
    ps.archive_project(admin, pid, final)
    assert rows(d, "SELECT archived_at FROM projects WHERE project_id=%s", (pid,))[0]["archived_at"] is not None
    restored = ps.restore_project(admin, pid)
    assert restored["status"] == final                                     # the old screen always set 'Approved' and re-opened it
    assert status(d, pid) == final
    with pytest.raises(Conflict, match="not archived"):
        ps.restore_project(admin, pid)


def test_only_finished_projects_can_be_archived_and_archived_ones_are_frozen(w):
    d, u, admin, staff, cal, grs, data = w
    pid = ps.create_project(admin, data())["project_id"]
    with pytest.raises(Conflict, match="Only Completed, Declined or Cancelled"):
        ps.archive_project(admin, pid, "Approved")
    ps.transition(admin, pid, "Cancelled", "Approved")
    ps.archive_project(admin, pid, "Cancelled")
    with pytest.raises(Conflict, match="archived"):
        ps.update_project(admin, pid, data(), "Cancelled")
    with pytest.raises(Conflict, match="archived"):
        ps.transition(admin, pid, "Ongoing", "Cancelled")
    with pytest.raises(NotFound):
        ps.restore_project(admin, 9999)
