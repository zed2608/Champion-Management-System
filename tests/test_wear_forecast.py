"""[PANEL-AWE] Wear forecast: fixed fake data with hand-computed answers, then the same rules through the database."""
from datetime import datetime, timedelta

import pytest

from services import wear_forecast as wf
from services.errors import PermissionDenied
from services.validators import ValidationError

NOW = datetime(2026, 6, 30, 12, 0, 0)
DEFAULTS = {"*": 500, "Drills": 100}


def tx(tid, tool, start, end=None, qty=1, cond=None):
    return {"transaction_id": tid, "tool_id": tool, "quantity": qty, "borrow_date": start, "return_date": end, "condition_at_return": cond}


def tool(tid, name, category="Drills", interval=None, serviced=None, units=1, price=1000):
    return {"tool_id": tid, "name": name, "category": category, "price": price, "interval": interval, "last_serviced_at": serviced, "units": units}


def by_id(rows):
    return {r["tool_id"]: r for r in rows}


# ---- hours, intervals and the "due in N days" prediction ------------------------------------------------------------------------------
def test_hours_percent_rate_and_days_to_due_for_known_data():
    tools = [tool(1, "Drill A")]
    txns = [tx(1, 1, datetime(2026, 5, 1, 8), datetime(2026, 5, 1, 18)),          # 10 h, outside the last 30 days
            tx(2, 1, datetime(2026, 6, 10, 8), datetime(2026, 6, 10, 18)),        # 10 h, inside
            tx(3, 1, datetime(2026, 6, 29, 12), None)]                             # still out: 24 h up to NOW
    a = by_id(wf.compute_forecast(tools, txns, [], DEFAULTS, NOW))[1]
    assert a["total_hours"] == 44.0 and a["hours_since_service"] == 44.0
    assert a["interval"] == 100.0 and a["pct_used"] == 44.0
    assert a["rate_per_day"] == pytest.approx(34 / 30, abs=0.001)                  # (10 + 24) hours in the last 30 days
    assert a["days_to_due"] == 49.4                                                # (100 - 44) / (34/30)
    assert a["flags"] == []


def test_over_90_percent_is_flagged_and_overdue_is_flagged_differently():
    tools = [tool(2, "Drill B"), tool(3, "Drill C")]
    txns = [tx(1, 2, datetime(2026, 6, 1, 0), datetime(2026, 6, 4, 18)),           # 90 h, all in the window
            tx(2, 3, datetime(2026, 4, 1, 0), datetime(2026, 4, 6, 0))]            # 120 h, long ago
    r = by_id(wf.compute_forecast(tools, txns, [], DEFAULTS, NOW))
    assert r[2]["pct_used"] == 90.0 and r[2]["flags"] == ["service due soon"]
    assert r[2]["rate_per_day"] == 3.0 and r[2]["days_to_due"] == 3.3               # 10 h left at 3 h/day
    assert r[3]["pct_used"] == 120.0 and r[3]["flags"] == ["overdue for service"]
    assert r[3]["days_to_due"] == 0.0 and r[3]["rate_per_day"] == 0.0


def test_just_under_90_percent_is_not_flagged():
    r = wf.compute_forecast([tool(1, "x")], [tx(1, 1, datetime(2026, 6, 1, 0), datetime(2026, 6, 4, 17))], [], DEFAULTS, NOW)[0]
    assert r["pct_used"] == 89.0 and r["flags"] == []


def test_servicing_restarts_the_clock_but_lifetime_hours_stay():
    t = tool(4, "Drill D", serviced=datetime(2026, 6, 1, 0))
    txn = tx(1, 4, datetime(2026, 5, 30, 0), datetime(2026, 6, 3, 0))               # 96 h in total, 48 h after the service
    r = wf.compute_forecast([t], [txn], [], DEFAULTS, NOW)[0]
    assert r["total_hours"] == 96.0 and r["hours_since_service"] == 48.0 and r["pct_used"] == 48.0


def test_unused_tool_has_no_prediction_not_a_made_up_one():
    r = wf.compute_forecast([tool(5, "Drill E")], [], [], DEFAULTS, NOW)[0]
    assert r["total_hours"] == 0 and r["days_to_due"] is None and r["damage_rate"] is None


def test_interval_comes_from_the_tool_then_the_category_then_the_global_default():
    tools = [tool(1, "own", interval=250), tool(2, "cat"), tool(3, "other", category="Saws"), tool(4, "none", category=None)]
    r = by_id(wf.compute_forecast(tools, [], [], DEFAULTS, NOW))
    assert (r[1]["interval"], r[2]["interval"], r[3]["interval"], r[4]["interval"]) == (250, 100, 500, 500)


def test_hours_are_weighted_by_quantity_and_shared_across_units():
    t = tool(1, "set of 2", units=2)
    r = wf.compute_forecast([t], [tx(1, 1, datetime(2026, 6, 1, 0), datetime(2026, 6, 2, 0), qty=2)], [], DEFAULTS, NOW)[0]
    assert r["total_hours"] == 48.0                                                  # 2 units x 24 h
    assert r["hours_since_service"] == 24.0                                          # per unit, which is what the interval measures


# ---- damage rate against the category ----------------------------------------------------------------------------------------------------
def saws(events):
    tools = [tool(10 + i, f"Saw {i}", category="Saws") for i in range(len(events))]
    txns = [tx(100 + i, 10 + i, datetime(2026, 4, 1, 0), datetime(2026, 4, 5, 4)) for i in range(len(events))]       # 100 h each
    issues = [{"tool_id": 10 + i, "transaction_id": None} for i, n in enumerate(events) for _ in range(n)]
    return tools, txns, issues


def test_one_tool_that_breaks_far_more_than_its_category_is_flagged():
    tools, txns, issues = saws([0, 0, 0, 0, 0, 6])
    rows = wf.compute_forecast(tools, txns, issues, DEFAULTS, NOW)
    r = by_id(rows)
    assert r[15]["damage_rate"] == 6.0 and r[15]["category_mean"] == 1.0
    assert r[15]["category_std"] == pytest.approx(2.236, abs=0.001) and r[15]["z"] == pytest.approx(2.24, abs=0.01)
    assert "breaks more than its category" in r[15]["flags"]
    assert all(not r[i]["flags"] for i in range(10, 15))
    assert rows[0]["tool_id"] == 15                                                  # flagged tools are listed first


def test_exactly_two_standard_deviations_is_not_flagged_and_small_categories_are_not_judged():
    tools, txns, issues = saws([0, 0, 0, 0, 10])                                       # z = 2.0 exactly with five tools
    assert not any(r["flags"] for r in wf.compute_forecast(tools, txns, issues, DEFAULTS, NOW))
    tools, txns, issues = saws([0, 9])                                                 # two tools: no category average worth trusting
    assert all(r["z"] is None for r in wf.compute_forecast(tools, txns, issues, DEFAULTS, NOW))


def test_damaged_return_without_a_ticket_counts_once_and_with_a_ticket_not_twice():
    tools = [tool(1, "A", category="Saws"), tool(2, "B", category="Saws")]
    txns = [tx(1, 1, datetime(2026, 4, 1, 0), datetime(2026, 4, 5, 4), cond="Damaged"),      # no ticket -> counted from the return
            tx(2, 2, datetime(2026, 4, 1, 0), datetime(2026, 4, 5, 4), cond="Damaged")]      # has a ticket -> counted once, from the ticket
    issues = [{"tool_id": 2, "transaction_id": 2}]
    r = by_id(wf.compute_forecast(tools, txns, issues, DEFAULTS, NOW))
    assert r[1]["damage_events"] == 1 and r[2]["damage_events"] == 1


def test_a_short_history_gives_no_damage_rate():
    r = wf.compute_forecast([tool(1, "new")], [tx(1, 1, datetime(2026, 6, 1, 0), datetime(2026, 6, 1, 3))], [{"tool_id": 1, "transaction_id": None}], DEFAULTS, NOW)[0]
    assert r["damage_events"] == 1 and r["damage_rate"] is None                         # 3 h of use is too little to call a "rate"


def test_the_summary_sentence_carries_the_numbers():
    tools, txns, issues = saws([0, 0, 0, 0, 0, 6])
    flagged = wf.compute_forecast(tools, txns, issues, DEFAULTS, NOW)[0]
    text = wf.summary_line(flagged)
    assert "100 of 500 service hours used (20%)" in text and "z = 2.24" in text and "category average 1" in text


# ---- through the database ----------------------------------------------------------------------------------------------------------------------
pytestmark_db = pytest.mark.db


def run(db, sql, params=()):
    with db.transaction() as cur:
        cur.execute(sql, params)
        return cur.lastrowid


@pytest.fixture
def world(svc):
    admin = run(svc, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('ADM-2026-001','Admin','Admin','Active')")
    staff = run(svc, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('STF-2026-001','Stacy','Staff','Active')")
    worker = run(svc, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('WKR-2026-001','Wally','Worker','Active')")
    return svc, {"user_id": admin}, {"user_id": staff}, worker


def add_tool(db, name, category="Drills", item_type="Equipment"):
    t = run(db, "INSERT INTO tool (name, category, item_type, unit_of_measure) VALUES (%s,%s,%s,'pcs')", (name, category, item_type))
    run(db, "INSERT INTO inventory (tool_id, quantity_total, quantity_available) VALUES (%s,1,1)", (t,))
    return t


@pytest.mark.db
def test_database_forecast_counts_open_transactions_to_now_and_skips_consumables(world):
    d, admin, staff, worker = world
    drill = add_tool(d, "Drill")
    add_tool(d, "Grease", item_type="Consumable")
    run(d, "INSERT INTO `transaction` (tool_id, user_id, type, status, quantity, borrow_date) VALUES (%s,%s,'Issue','Active',1,NOW() - INTERVAL 48 HOUR)", (drill, worker))
    rows = wf.forecast(admin)
    assert [r["name"] for r in rows] == ["Drill"]                                      # the consumable has no wear
    assert rows[0]["total_hours"] == pytest.approx(48, abs=0.1) and rows[0]["interval"] == 500   # the seeded '*' default


@pytest.mark.db
def test_admin_edits_defaults_and_intervals_and_marks_serviced(world):
    d, admin, staff, worker = world
    drill = add_tool(d, "Drill")
    run(d, "INSERT INTO `transaction` (tool_id, user_id, type, status, quantity, borrow_date, return_date) VALUES (%s,%s,'Retrieval','Returned',1,NOW() - INTERVAL 100 HOUR, NOW() - INTERVAL 50 HOUR)", (drill, worker))
    wf.set_category_default(admin, "Drills", "100")
    assert wf.forecast(admin)[0]["interval"] == 100 and wf.forecast(admin)[0]["pct_used"] == pytest.approx(50, abs=0.2)
    wf.set_tool_interval(admin, drill, "200")
    assert wf.forecast(admin)[0]["interval"] == 200
    wf.set_tool_interval(admin, str(drill), "")                                        # back to the category default, id as text
    assert wf.forecast(admin)[0]["interval"] == 100
    wf.mark_serviced(admin, drill)
    assert wf.forecast(admin)[0]["hours_since_service"] == pytest.approx(0, abs=0.1) and wf.forecast(admin)[0]["total_hours"] == pytest.approx(50, abs=0.1)
    assert {r["category"]: r["hours"] for r in wf.list_defaults(admin)} == {"*": 500, "Drills": 100}


@pytest.mark.db
@pytest.mark.parametrize("hours", ["0", "-5", "abc", "100001", ""])
def test_bad_intervals_are_refused(world, hours):
    d, admin, staff, worker = world
    with pytest.raises(ValidationError):
        wf.set_category_default(admin, "Drills", hours)


@pytest.mark.db
def test_only_admin_may_read_or_change_wear_data(world):
    d, admin, staff, worker = world
    t = add_tool(d, "Drill")
    for call in (lambda: wf.forecast(staff), lambda: wf.list_defaults(staff), lambda: wf.set_category_default(staff, "x", 10),
                 lambda: wf.set_tool_interval(staff, t, 10), lambda: wf.mark_serviced(staff, t)):
        with pytest.raises(PermissionDenied):
            call()


@pytest.mark.db
def test_resolving_a_repair_ticket_restarts_the_service_clock(world):
    d, admin, staff, worker = world
    from services import maintenance_service as mnt
    t = add_tool(d, "Drill")
    mnt.flag_tool(admin, str(t), "ADM-2026-001", "Needs Repair", "chuck slips", "1")
    with d.read() as cur:
        cur.execute("SELECT issue_id FROM tool_issues WHERE tool_id=%s", (t,))
        issue = cur.fetchone()["issue_id"]
    mnt.resolve_issue(admin, issue, "Good", "0", "replaced chuck")
    with d.read() as cur:
        cur.execute("SELECT last_serviced_at FROM tool WHERE tool_id=%s", (t,))
        assert cur.fetchone()["last_serviced_at"] is not None


@pytest.mark.db
def test_migration_seeds_the_default_once_and_never_overwrites(world):
    d, admin, staff, worker = world
    wf.set_category_default(admin, "*", "800")
    from db import migrate
    conn = d.raw_connection()                                                         # re-run the step by hand: must not undo the Admin's value
    try:
        ctx = migrate.Ctx(conn)
        migrate.step_seed_service_defaults(ctx)
        conn.commit()
    finally:
        conn.close()
    assert {r["category"]: r["hours"] for r in wf.list_defaults(admin)}["*"] == 800


@pytest.mark.db
def test_wear_tab_on_the_real_maintenance_screen(world, monkeypatch):
    import time
    import customtkinter as ctk
    from conftest import make_window
    import database
    import views.maintenance as vm
    d, admin, staff, worker = world
    session = {**admin, "employee_id": "ADM-2026-001", "role": "Admin", "full_name": "Admin", "email": None, "status": "Active"}
    t = add_tool(d, "Impact Drill")
    run(d, "INSERT INTO `transaction` (tool_id, user_id, type, status, quantity, borrow_date, return_date) VALUES (%s,%s,'Retrieval','Returned',1,NOW() - INTERVAL 600 HOUR, NOW() - INTERVAL 10 HOUR)", (t, worker))
    monkeypatch.setattr(vm, "get_connection", database.get_connection)
    root = make_window(ctk.CTk)
    root.geometry("1300x800+0+0")
    try:
        mv = vm.MaintenanceView(root, session)
        mv.pack(fill="both", expand=True)
        mv.tab_var.set("📈 Wear Forecast")
        mv.switch_tab("📈 Wear Forecast")
        end = time.time() + 25
        while time.time() < end and not (getattr(mv, "_wear_table", None) is not None and mv._wear_table.winfo_exists() and mv._wear_table.rows):
            root.update()
            time.sleep(0.02)
        row = mv._wear_table.rows[0]
        assert row["name"] == "Impact Drill" and "overdue for service" in row["flags"]            # 590 h used of the 500 h default
        cells = [s["labels"][0].cget("text") for s in mv._wear_table._slots if s["row"] is not None]
        assert cells == ["Impact Drill"]
        mv.wear_cat.insert(0, "Drills")
        mv.wear_hours.insert(0, "1000")
        mv.save_wear_default()
        end = time.time() + 25
        while time.time() < end and not (mv._wear_table.winfo_exists() and mv._wear_table.rows and not mv._wear_table.rows[0]["flags"]):
            root.update()
            time.sleep(0.02)
        assert mv._wear_table.rows[0]["interval"] == 1000 and mv._wear_table.rows[0]["flags"] == []
    finally:
        root.destroy()
