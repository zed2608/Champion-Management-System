"""[QUANTITIES][RBAC] Dashboard numbers are sums of quantity, not row counts; the feed works for Staff."""
from datetime import date, timedelta

import pytest

from services import dashboard_service as dash
from services import issuance_service as iss
from services import maintenance_service as mnt
from services import project_service as ps
from services.errors import PermissionDenied

pytestmark = pytest.mark.db
TODAY = date.today()


def run(db, sql, params=()):
    with db.transaction() as cur:
        cur.execute(sql, params)
        return cur.lastrowid


@pytest.fixture
def w(svc):
    d = svc
    u = {}
    for key, eid, name, role in [("admin", "ADM-2026-001", "Admin", "Admin"), ("staff", "STF-2026-001", "Stacy", "Staff"),
                                 ("w1", "WKR-2026-001", "Wally", "Worker")]:
        u[key] = run(d, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES (%s,%s,%s,'Active')", (eid, name, role))
    cal = run(d, "INSERT INTO tool (name, tag_id, item_type) VALUES ('Caliper','CAL-001','Equipment')")
    grs = run(d, "INSERT INTO tool (name, tag_id, item_type, unit_of_measure) VALUES ('Grease','GRS-001','Consumable','kg')")
    run(d, "INSERT INTO inventory (tool_id, quantity_total, quantity_available, minimum_stock) VALUES (%s,10,10,0), (%s,5,5,5)", (cal, grs))
    admin, staff = {"user_id": u["admin"]}, {"user_id": u["staff"]}
    pid = ps.create_project(admin, dict(name="Alpha", client="ACME", start_date=str(TODAY - timedelta(days=1)),
                                        end_date=str(TODAY + timedelta(days=9)), workers=["WKR-2026-001"],
                                        requirements=[{"tool_id": cal, "qty": 3}, {"tool_id": grs, "qty": "2.5"}]))["project_id"]
    iss.issue(admin, u["w1"], pid, [{"tool_id": cal, "qty": 3}, {"tool_id": grs, "qty": "2.5"}], "p")
    return d, u, admin, staff, cal, grs, pid


def test_quantities_are_summed_not_counted(w):
    d, u, admin, staff, cal, grs, pid = w
    m, feed, chart, deployed, mine = dash.live_metrics(admin)
    assert m["borrowed_qty"] == 5.5                    # 3 caliper rows + ONE grease row of 2.5: a row count would say 4
    assert m["available_qty"] == 9.5 and m["total_physical"] == 15
    assert m["utilization_pct"] == 36                  # 5.5 / 15
    assert chart[-1][1] == 5.5                         # today's issued, exact
    assert deployed == [("Alpha", 5.5)]
    assert mine == []                                  # the admin holds nothing personally (the borrower view is tested below)
    assert m["proj_active"] == 1                       # project became Ongoing when its lines were fulfilled


def test_feed_groups_a_batch_and_shows_exact_quantities(w):
    d, u, admin, staff, cal, grs, pid = w
    feed = dash.live_metrics(staff)[1]
    items = [a[2] for a in feed if a[1] == "Issued"]
    assert sorted(items) == ["Caliper x3", "Grease x2.5"], items          # one entry per batch, not one per row


def test_partial_consumable_return_counts_exactly(w):
    d, u, admin, staff, cal, grs, pid = w
    iss.retrieve(admin, u["w1"], grs, "1.25", "Good", "")
    m, feed, chart, deployed, mine = dash.live_metrics(admin)
    assert m["borrowed_qty"] == 4.25 and chart[-1][2] == 1.25 and deployed == [("Alpha", 4.25)]
    assert ("Retrieved", "Grease x1.25") in [(a[1], a[2]) for a in feed]


def test_maintenance_and_low_stock_and_archived_items(w):
    d, u, admin, staff, cal, grs, pid = w
    iss.retrieve(admin, u["w1"], cal, 1, "Damaged", "cracked")
    m = dash.live_metrics(admin)[0]
    assert m["pending_issues"] == 1                                       # open tickets, not tools flagged
    assert m["low_stock"] == 1                                            # grease: 2.5 available < minimum 5
    run(d, "UPDATE `user` SET status='Archived' WHERE user_id=%s", (u["w1"],))
    assert dash.live_metrics(admin)[0]["total_employees"] == 2            # archived employees are not counted


def test_borrowers_own_issuances_are_quantity_labelled(w):
    d, u, admin, staff, cal, grs, pid = w
    run(d, "UPDATE `user` SET role='Staff' WHERE user_id=%s", (u["w1"],))      # a Staff member holding tools sees their own list
    mine = dash.live_metrics({"user_id": u["w1"]})[4]
    assert sorted(x[0] for x in mine) == ["Caliper x3", "Grease x2.5"]


def test_project_events_reach_the_feed_for_staff_through_the_view(w):
    d, u, admin, staff, cal, grs, pid = w
    run(d, "INSERT INTO system_logs (user_id, action_type, module, details) VALUES (%s,'Drafted & Approved','Projects',%s)",
        (u["admin"], "Drafted & Approved project 'Beta' (ID: 9)."))
    run(d, "INSERT INTO system_logs (user_id, action_type, module, details) VALUES (%s,'Login','Authentication','secret audit line')", (u["admin"],))
    feed = dash.live_metrics(staff)[1]
    assert any(a[1] == "Project Created" and "Beta" in a[2] for a in feed)
    assert not any("secret audit line" in str(a) for a in feed)           # nothing else from the audit log leaks into the feed


def test_workers_have_no_dashboard(w):
    d, u, *_ = w
    with pytest.raises(PermissionDenied):
        dash.live_metrics({"user_id": u["w1"]})
