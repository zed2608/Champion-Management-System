"""[PANEL-AWE] Anomaly and bottleneck detector: fixed fake data with hand-computed answers, then the real refusal paths through the database."""
from datetime import date, timedelta

import pytest

from services import anomaly as an
from services.errors import Conflict, PermissionDenied
from services.stock_ledger import InsufficientStock


def bad_row(i, project, qty, bad, price=100, client=None, worker="W"):
    return {"transaction_id": i, "tool_id": 1, "quantity": qty, "price": price, "project_id": project, "project_name": f"Project {project}",
            "client": client, "user_id": project, "worker": f"{worker}{project}", "bad": bad}


def projects_with_bad_units(bad_units, issued=10):
    rows, n = [], 0
    for p, bad in enumerate(bad_units, start=1):
        for k in range(issued):
            n += 1
            rows.append(bad_row(n, p, 1, k < bad))
    return rows


# ---- (a) damage and loss outliers ----------------------------------------------------------------------------------------------------------------
def test_one_project_far_above_its_peers_is_the_only_damage_outlier():
    rows = projects_with_bad_units([0, 1, 1, 1, 1, 6])                          # rates 0, .1, .1, .1, .1, .6 -> fence = .1 (IQR is 0)
    found = an.damage_outliers(rows)
    projects = [f for f in found if f["dimension"] == "project"]
    assert [f["label"] for f in projects] == ["Project 6"]
    f = projects[0]
    assert (f["issued"], f["bad"], f["rate"], f["peers"]) == (10, 6, 0.6, 6)
    assert f["fence"] == pytest.approx(0.1) and f["peer_median"] == pytest.approx(0.1) and f["value"] == 600.0
    assert {x["dimension"] for x in found} == {"project", "worker"}               # the same people show up as workers; no client was recorded


def test_a_rate_equal_to_the_fence_or_too_little_volume_is_not_an_outlier():
    assert not an.damage_outliers(projects_with_bad_units([1, 1, 1, 1, 1, 1]))                 # everyone alike
    rows = projects_with_bad_units([0, 0, 0, 0, 0])
    rows += [bad_row(900 + i, 7, 1, True) for i in range(2)]                                    # 2 of 2 broken, but only 2 units issued
    assert not an.damage_outliers(rows)
    assert not an.damage_outliers(projects_with_bad_units([0, 0, 9]))                           # fewer than 4 peers: no fence worth trusting


def test_clients_are_compared_too():
    rows = []
    n = 0
    for c, bad in enumerate([0, 1, 1, 1, 1, 6], start=1):
        for k in range(10):
            n += 1
            rows.append(bad_row(n, project=c, qty=1, bad=k < bad, client=f"Client {c}"))
    dims = {(f["dimension"], f["label"]) for f in an.damage_outliers(rows)}
    assert ("client", "Client 6") in dims and ("project", "Project 6") in dims


def test_iqr_fence_matches_a_hand_calculation():
    q1, q3, fence = an.iqr_fence([1, 2, 3, 4, 5, 6, 7, 8])                                      # numpy linear: q1 = 2.75, q3 = 6.25
    assert (q1, q3) == (2.75, 6.25) and fence == pytest.approx(6.25 + 1.5 * 3.5)


# ---- (b) Category A bottlenecks ---------------------------------------------------------------------------------------------------------------------
ABC = [{"tool_id": 1, "name": "Drill", "category": "A"}, {"tool_id": 2, "name": "Saw", "category": "A"}, {"tool_id": 3, "name": "Hammer", "category": "B"}]
TOOLS = {1: {"name": "Drill", "price": 500, "stock": 7}, 2: {"name": "Saw", "price": 100, "stock": 5}, 3: {"name": "Hammer", "price": 50, "stock": 1}}


def attempts(tool, reason, n):
    return [{"tool_id": tool, "reason": reason} for _ in range(n)]


def test_only_a_category_a_tool_with_more_blocked_attempts_than_stock_is_a_bottleneck():
    data = attempts(1, "out_of_stock", 6) + attempts(1, "over_quota", 3) + attempts(1, "past_end", 3) + attempts(2, "out_of_stock", 4) + attempts(3, "out_of_stock", 5)
    found = an.blocked_demand(ABC, TOOLS, data)
    assert len(found) == 1
    f = found[0]
    assert (f["name"], f["blocked"], f["stock"], f["shortfall"], f["value"]) == ("Drill", 9, 7.0, 2, 1000.0)    # 9 blocked (past_end not counted) vs 7 in stock
    # Saw: 4 blocked < 5 in stock; Hammer: 5 blocked > 1 in stock but it is Category B


def test_equal_attempts_and_stock_is_not_a_bottleneck():
    assert not an.blocked_demand(ABC, TOOLS, attempts(1, "out_of_stock", 7))


# ---- (c) overdue clusters ---------------------------------------------------------------------------------------------------------------------------
def overdue(i, project, worker_id, days=5, qty=1, price=200):
    return {"transaction_id": i, "project_id": project, "project_name": f"Project {project}", "user_id": worker_id, "worker": f"Worker {worker_id}",
            "tool_name": f"Tool {i}", "price": price, "quantity": qty, "days_overdue": days}


def test_three_overdue_issuances_in_one_project_or_with_one_worker_make_a_cluster():
    rows = [overdue(1, 1, 10, 12), overdue(2, 1, 11, 3), overdue(3, 1, 11, 7), overdue(4, 2, 12), overdue(5, 2, 12)]
    found = an.overdue_clusters(rows)
    by = {(f["dimension"], f["label"]): f for f in found}
    assert set(by) == {("project", "Project 1")}                                  # Project 2 has 2; Worker 11 has 2; Worker 12 has 2
    f = by[("project", "Project 1")]
    assert (f["count"], f["units"], f["value"], f["max_days"], f["workers"]) == (3, 3.0, 600.0, 12, 2)
    rows2 = [overdue(1, 1, 10), overdue(2, 2, 10), overdue(3, 3, 10)]
    assert [(f["dimension"], f["label"], f["count"]) for f in an.overdue_clusters(rows2)] == [("worker", "Worker 10", 3)]


# ---- recommendations ---------------------------------------------------------------------------------------------------------------------------------
def test_recommendations_are_ranked_by_peso_impact_and_always_carry_their_numbers():
    damage = an.damage_outliers(projects_with_bad_units([0, 1, 1, 1, 1, 6]))
    bottle = an.blocked_demand(ABC, TOOLS, attempts(1, "out_of_stock", 9))
    cluster = an.overdue_clusters([overdue(1, 1, 10, 12), overdue(2, 1, 11, 3), overdue(3, 1, 11, 7)])
    recs = an.recommendations(damage, bottle, cluster)
    impacts = [r["peso_impact"] for r in recs]
    assert impacts == sorted(impacts, reverse=True) and impacts[0] == 1000.0
    assert recs[0]["text"] == "Procure 2 more Drill: blocked 9 times in the last 30 days against 7 in stock, Category A. Estimated cost P1,000.00."
    assert recs[0]["evidence"][0] == "blocked attempts (30 days): 9"
    for r in recs:
        assert len(r["evidence"]) >= 3 and sum(any(ch.isdigit() for ch in e) for e in r["evidence"]) >= 3
        assert any(ch.isdigit() for ch in r["text"])
    damage_rec = next(r for r in recs if r["kind"] == "damage" and "Project 6" in r["title"])
    assert "6 of 10 units" in damage_rec["text"] and "60%" in damage_rec["text"] and "P600.00" in damage_rec["text"]
    overdue_rec = next(r for r in recs if r["kind"] == "overdue")
    assert "3 overdue issuances" in overdue_rec["text"] and "P600.00" in overdue_rec["text"] and "12 days" in overdue_rec["text"]


def test_nothing_unusual_gives_no_recommendations():
    assert an.recommendations([], [], []) == []


# ---- through the database ----------------------------------------------------------------------------------------------------------------------------
def run(db, sql, params=()):
    with db.transaction() as cur:
        cur.execute(sql, params)
        return cur.lastrowid


def rows(db, sql, params=()):
    with db.read() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


@pytest.fixture
def world(svc):
    admin = run(svc, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('ADM-2026-001','Admin','Admin','Active')")
    staff = run(svc, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('STF-2026-001','Stacy','Staff','Active')")
    worker = run(svc, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('WKR-2026-001','Wally','Worker','Active')")
    return svc, {"user_id": admin}, {"user_id": staff}, worker


def make_tool(db, name, tag, qty, price=100):
    t = run(db, "INSERT INTO tool (name, tag_id, category, item_type, unit_of_measure, price) VALUES (%s,%s,'Drills','Equipment','pcs',%s)", (name, tag, price))
    run(db, "INSERT INTO inventory (tool_id, quantity_total, quantity_available) VALUES (%s,%s,%s)", (t, qty, qty))
    return t


def make_project(db, worker, end_offset_days=30, status="Approved", tool=None, req=5):
    today = date.today()
    p = run(db, "INSERT INTO projects (name, start_date, end_date, status, workers_assigned) VALUES ('Job',%s,%s,'Approved','WKR-2026-001')",
            (today - timedelta(days=5), today + timedelta(days=end_offset_days)))
    if tool:
        run(db, "INSERT INTO project_requirements (project_id, tool_id, quantity) VALUES (%s,%s,%s)", (p, tool, req))
    return p


@pytest.mark.db
def test_refused_issuances_are_recorded_with_their_reason(world):
    from services import issuance_service as iss
    d, admin, staff, worker = world
    scarce = make_tool(d, "Scarce", "SCR-001", 1)
    other = make_tool(d, "Plenty", "PLN-001", 10)
    p = make_project(d, worker, tool=scarce, req=2)
    run(d, "INSERT INTO project_requirements (project_id, tool_id, quantity) VALUES (%s,%s,3)", (p, other))
    # out of stock at the scan
    iss.issue(admin, worker, p, [{"tool_id": scarce, "qty": 1}], "Job")
    with pytest.raises(Conflict):
        iss.lookup_tool(staff, "SCR-001")
    # over the approved quantity (3 approved, 4 asked)
    with pytest.raises(Conflict):
        iss.issue(staff, worker, p, [{"tool_id": other, "qty": 4}], "Job")
    # out of stock inside the transaction (2 approved, only 0 free)
    with pytest.raises((Conflict, InsufficientStock)):
        iss.issue(staff, worker, p, [{"tool_id": scarce, "qty": 1}], "Job")
    # project ended
    ended = make_project(d, worker, end_offset_days=-1, tool=other, req=2)
    with pytest.raises(Conflict):
        iss.issue(staff, worker, ended, [{"tool_id": other, "qty": 1}], "Job")
    got = rows(d, "SELECT reason, tool_id, project_id, user_id, actor_id, quantity FROM issuance_attempts ORDER BY attempt_id")
    assert [g["reason"] for g in got] == ["out_of_stock", "over_quota", "out_of_stock", "past_end"]
    assert got[1]["tool_id"] == other and got[1]["quantity"] == 4 and got[1]["user_id"] == worker and got[1]["actor_id"] == staff["user_id"]
    assert got[3]["project_id"] == ended and got[3]["tool_id"] is None
    assert an.blocked_attempts_summary(admin) == {"out_of_stock": 2, "over_quota": 1, "past_end": 1}


@pytest.mark.db
def test_a_successful_issue_records_nothing(world):
    from services import issuance_service as iss
    d, admin, staff, worker = world
    t = make_tool(d, "Drill", "DRL-001", 3)
    p = make_project(d, worker, tool=t, req=2)
    iss.issue(staff, worker, p, [{"tool_id": t, "qty": 1}], "Job")
    assert rows(d, "SELECT COUNT(*) AS n FROM issuance_attempts")[0]["n"] == 0


@pytest.mark.db
def test_analyse_end_to_end_recommends_procurement_for_a_category_a_tool(world):
    d, admin, staff, worker = world
    star = make_tool(d, "Star Drill", "STR-001", 7, price=500)
    others = [make_tool(d, f"Minor {i}", f"MNR-00{i}", 5, price=10) for i in range(4)]
    with d.transaction() as cur:
        for i in range(10):                                                       # the busiest tool: Category A
            cur.execute("INSERT INTO `transaction` (tool_id, user_id, type, status, borrow_date, return_date, quantity) VALUES (%s,%s,'Retrieval','Returned',"
                        "NOW() - INTERVAL 5 DAY, NOW() - INTERVAL 4 DAY, 1)", (star, worker))
        cur.execute("INSERT INTO `transaction` (tool_id, user_id, type, status, borrow_date, return_date, quantity) VALUES (%s,%s,'Retrieval','Returned',"
                    "NOW() - INTERVAL 5 DAY, NOW() - INTERVAL 4 DAY, 1)", (others[0], worker))
        for _ in range(9):
            cur.execute("INSERT INTO issuance_attempts (tool_id, reason) VALUES (%s,'out_of_stock')", (star,))
        cur.execute("INSERT INTO issuance_attempts (tool_id, reason) VALUES (%s,'out_of_stock')", (others[1],))
    result = an.analyse(admin)
    assert [b["name"] for b in result["bottlenecks"]] == ["Star Drill"]
    top = result["recommendations"][0]
    assert top["text"].startswith("Procure 2 more Star Drill: blocked 9 times") and top["peso_impact"] == 1000.0
    assert an.top_recommendations(admin, 1) == [top]


@pytest.mark.db
def test_only_admin_may_analyse(world):
    d, admin, staff, worker = world
    for call in (lambda: an.analyse(staff), lambda: an.top_recommendations(staff), lambda: an.blocked_attempts_summary(staff)):
        with pytest.raises(PermissionDenied):
            call()


def test_unknown_reason_is_ignored_and_a_broken_log_never_raises(monkeypatch):
    an.log_attempt("nonsense", tool_id=1)                                          # silently ignored

    class Boom:
        def transaction(self):
            raise RuntimeError("database gone")
    monkeypatch.setattr(an, "db", Boom())
    an.log_attempt("out_of_stock", tool_id=1)                                      # must not raise


@pytest.mark.db
def test_anomalies_tab_on_the_real_reports_screen(world, monkeypatch):
    import time
    import customtkinter as ctk
    from conftest import make_window
    import views.reports as vr
    d, admin, staff, worker = world
    star = make_tool(d, "Star Drill", "STR-001", 7, price=500)
    for i in range(4):
        make_tool(d, f"Minor {i}", f"MNR-00{i}", 5, price=10)
    with d.transaction() as cur:
        for i in range(10):
            cur.execute("INSERT INTO `transaction` (tool_id, user_id, type, status, borrow_date, return_date, quantity) VALUES (%s,%s,'Retrieval','Returned',"
                        "NOW() - INTERVAL 5 DAY, NOW() - INTERVAL 4 DAY, 1)", (star, worker))
        for _ in range(9):
            cur.execute("INSERT INTO issuance_attempts (tool_id, reason) VALUES (%s,'out_of_stock')", (star,))
    session = {**admin, "employee_id": "ADM-2026-001", "role": "Admin", "full_name": "Admin", "email": None, "status": "Active"}
    root = make_window(ctk.CTk)
    root.geometry("1300x800+0+0")
    try:
        view = vr.ReportsView(root, user_info=session)
        view.pack(fill="both", expand=True)
        view.tab_var.set("🔎 Anomalies")
        view.switch_tab("🔎 Anomalies")
        end = time.time() + 25
        while time.time() < end and not getattr(view, "_anomaly_data", None):
            root.update()
            time.sleep(0.02)
        assert view._anomaly_data["recommendations"][0]["title"] == "Procure 2 more Star Drill"
        texts = []

        def walk(w):
            for c in w.winfo_children():
                if hasattr(c, "cget"):
                    try:
                        texts.append(c.cget("text"))
                    except Exception:
                        pass
                walk(c)
        walk(view)
        joined = " | ".join(str(t) for t in texts)
        assert "blocked 9 times" in joined and "blocked attempts (30 days): 9" in joined and "9 out of stock" in joined
    finally:
        root.destroy()
