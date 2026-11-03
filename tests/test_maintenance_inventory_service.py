"""[RBAC][CONCURRENCY][UNHAPPY-PATH] Maintenance and Inventory writes through the service layer."""
from datetime import date, timedelta
from decimal import Decimal

import mysql.connector
import pytest

from services import inventory_service as inv_svc
from services import issuance_service as iss
from services import maintenance_service as mnt
from services import validators as v
from services.errors import Conflict, NotFound, PermissionDenied, friendly_message

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
    d = svc
    u = {}
    for key, eid, name, role in [("admin", "ADM-2026-001", "Admin", "Admin"), ("staff", "STF-2026-001", "Stacy", "Staff"),
                                 ("w1", "WKR-2026-001", "Wally", "Worker")]:
        u[key] = run(d, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES (%s,%s,%s,'Active')", (eid, name, role))
    cal = run(d, "INSERT INTO tool (name, tag_id, item_type, category) VALUES ('Caliper','CAL-001','Equipment','Measuring')")
    grs = run(d, "INSERT INTO tool (name, tag_id, item_type, unit_of_measure) VALUES ('Grease','GRS-001','Consumable','kg')")
    run(d, "INSERT INTO inventory (tool_id, quantity_total, quantity_available) VALUES (%s,10,10), (%s,5,5)", (cal, grs))
    return d, {"admin": {"user_id": u["admin"]}, "staff": {"user_id": u["staff"]}}, u, cal, grs


def inv(d, tool):
    return rows(d, "SELECT * FROM inventory WHERE tool_id=%s", (tool,))[0]


# ---- flagging ---------------------------------------------------------------------------------------------------
def test_flag_damaged_holds_only_those_units(w):
    d, s, u, cal, grs = w
    r = mnt.flag_tool(s["admin"], "CAL-001", "STF-2026-001", "Damaged", "Dropped", 2)
    i = inv(d, cal)
    assert (i["quantity_total"], i["quantity_available"], i["quantity_in_maintenance"]) == (10, 8, 2)
    t = rows(d, "SELECT * FROM tool_issues WHERE issue_id=%s", (r["issue_id"],))[0]
    assert (t["quantity"], t["status"], t["reported_by_user_id"]) == (2, "Open", u["staff"])      # reporter resolved from the employee id
    assert rows(d, "SELECT `condition` AS c FROM tool WHERE tool_id=%s", (cal,))[0]["c"] == "Damaged"


def test_flag_by_pid_and_lost_units_leave_the_total(w):
    d, s, u, cal, grs = w
    mnt.flag_tool(s["admin"], str(cal), "someone", "Lost", "", 1)
    i = inv(d, cal)
    assert (i["quantity_total"], i["quantity_available"], i["quantity_lost"]) == (9, 9, 1)


def test_flag_discrepancy_moves_no_stock(w):
    d, s, u, cal, grs = w
    r = mnt.flag_tool(s["admin"], "CAL-001", "x", "Discrepancy", "count is off", 1)
    assert inv(d, cal)["quantity_available"] == 10
    assert rows(d, "SELECT quantity FROM tool_issues WHERE issue_id=%s", (r["issue_id"],))[0]["quantity"] == 0


def test_flag_cannot_flag_more_units_than_are_in_stock(w):
    d, s, u, cal, grs = w
    run(d, "UPDATE inventory SET quantity_available = 1 WHERE tool_id=%s", (cal,))         # 9 are out on projects
    with pytest.raises(Exception, match="stock"):
        mnt.flag_tool(s["admin"], "CAL-001", "x", "Damaged", "n", 2)
    assert inv(d, cal)["quantity_in_maintenance"] == 0 and rows(d, "SELECT COUNT(*) AS n FROM tool_issues")[0]["n"] == 0


def test_flag_validation(w):
    d, s, u, cal, grs = w
    with pytest.raises(NotFound):
        mnt.flag_tool(s["admin"], "NOPE-1", "x", "Damaged", "n", 1)
    with pytest.raises(v.ValidationError, match="whole"):
        mnt.flag_tool(s["admin"], "CAL-001", "x", "Damaged", "n", "1.5")
    with pytest.raises(v.ValidationError):
        mnt.flag_tool(s["admin"], "CAL-001", "x", "Exploded", "n", 1)
    with pytest.raises(v.ValidationError):
        mnt.flag_tool(s["admin"], "CAL-001", "", "Damaged", "n", 1)
    assert mnt.flag_tool(s["admin"], "GRS-001", "x", "Damaged", "spilled", "0.5")["moved"]           # consumables may be fractional


# ---- resolving: the stock-inflation bug ------------------------------------------------------------------------
def test_repair_returns_units_to_stock_without_inflating_the_total(w):
    d, s, u, cal, grs = w
    r = mnt.flag_tool(s["admin"], "CAL-001", "x", "Damaged", "n", 1)
    out = mnt.resolve_issue(s["admin"], r["issue_id"], "Good", "", "Replaced the jaw")
    i = inv(d, cal)
    assert (i["quantity_total"], i["quantity_available"], i["quantity_in_maintenance"]) == (10, 10, 0)   # the old screen made total 11
    assert "returned to stock" in out["effect"]
    t = rows(d, "SELECT * FROM tool_issues WHERE issue_id=%s", (r["issue_id"],))[0]
    assert (t["status"], t["is_resolved"], t["resolved_by"], t["condition_flag"]) == ("Resolved", 1, u["admin"], "Damaged")
    assert "Replaced the jaw" in t["notes"]
    assert rows(d, "SELECT `condition` AS c FROM tool WHERE tool_id=%s", (cal,))[0]["c"] == "Good"


def test_unrepairable_units_are_removed_and_replacements_are_added_once(w):
    d, s, u, cal, grs = w
    r = mnt.flag_tool(s["admin"], "CAL-001", "x", "Damaged", "n", 1)
    mnt.resolve_issue(s["admin"], r["issue_id"], "Damaged", "1", "Scrapped, bought a replacement")
    i = inv(d, cal)
    assert (i["quantity_total"], i["quantity_available"], i["quantity_in_maintenance"]) == (10, 10, 0)   # -1 scrapped, +1 bought


def test_written_off_as_lost_and_found_lost_units(w):
    d, s, u, cal, grs = w
    r1 = mnt.flag_tool(s["admin"], "CAL-001", "x", "Needs Repair", "n", 1)
    mnt.resolve_issue(s["admin"], r1["issue_id"], "Lost", "", "Cannot be found")
    i = inv(d, cal)
    assert (i["quantity_total"], i["quantity_available"], i["quantity_lost"]) == (9, 9, 1)
    r2 = mnt.flag_tool(s["admin"], "CAL-001", "x", "Lost", "n", 1)
    assert inv(d, cal)["quantity_total"] == 8
    out = mnt.resolve_issue(s["admin"], r2["issue_id"], "Good", "", "Found in van")
    assert "found" in out["effect"] and (inv(d, cal)["quantity_total"], inv(d, cal)["quantity_available"]) == (9, 9)


def test_resolving_twice_is_refused_for_a_stale_modal(w):
    d, s, u, cal, grs = w
    r = mnt.flag_tool(s["admin"], "CAL-001", "x", "Damaged", "n", 1)
    mnt.resolve_issue(s["admin"], r["issue_id"], "Good", "", "")
    with pytest.raises(Conflict, match="already"):
        mnt.resolve_issue(s["admin"], r["issue_id"], "Good", "", "")
    assert inv(d, cal)["quantity_available"] == 10


def test_ticket_from_the_old_system_with_no_tracked_units_still_resolves(w):
    d, s, u, cal, grs = w
    tid = run(d, "INSERT INTO tool_issues (tool_id, reported_by, condition_flag, quantity) VALUES (%s,'Migration','Damaged',1)", (cal,))
    assert inv(d, cal)["quantity_in_maintenance"] == 0
    assert "no stock change" in mnt.resolve_issue(s["admin"], tid, "Good", "", "")["effect"]
    assert inv(d, cal)["quantity_total"] == 10


def test_resolve_validation(w):
    d, s, u, cal, grs = w
    r = mnt.flag_tool(s["admin"], "CAL-001", "x", "Damaged", "n", 1)
    for bad in ("-1", "abc", "1.5"):
        with pytest.raises(v.ValidationError):
            mnt.resolve_issue(s["admin"], r["issue_id"], "Good", bad, "")
    with pytest.raises(v.ValidationError):
        mnt.resolve_issue(s["admin"], r["issue_id"], "Whatever", "", "")
    with pytest.raises(NotFound):
        mnt.resolve_issue(s["admin"], 9999, "Good", "", "")


def test_maintenance_is_admin_only(w):
    d, s, u, cal, grs = w
    with pytest.raises(PermissionDenied):
        mnt.flag_tool(s["staff"], "CAL-001", "x", "Damaged", "n", 1)
    r = mnt.flag_tool(s["admin"], "CAL-001", "x", "Damaged", "n", 1)
    with pytest.raises(PermissionDenied):
        mnt.resolve_issue(s["staff"], r["issue_id"], "Good", "", "")
    assert inv(d, cal)["quantity_in_maintenance"] == 1


# ---- inventory: add / edit -------------------------------------------------------------------------------------
ADD = dict(name="Micrometer", category="Measuring", supplier="Mitutoyo", description="0-25mm", location="A1",
           item_type="Equipment", unit_of_measure="pcs", price="3500", quantity="4")


def test_add_item_creates_tool_and_stock(w):
    d, s, u, cal, grs = w
    r = inv_svc.add_item(s["admin"], **ADD)
    i = inv(d, r["tool_id"])
    assert (i["quantity_total"], i["quantity_available"]) == (4, 4)
    t = rows(d, "SELECT * FROM tool WHERE tool_id=%s", (r["tool_id"],))[0]
    assert (t["condition"], t["is_archived"], t["price"]) == ("Good", 0, Decimal("3500.00")) and t["date_acquired"] is not None


def test_add_item_rules(w):
    d, s, u, cal, grs = w
    with pytest.raises(Conflict, match="already exists"):
        inv_svc.add_item(s["admin"], **{**ADD, "name": "caliper"})                  # case-insensitive duplicate
    with pytest.raises(v.ValidationError, match="whole"):
        inv_svc.add_item(s["admin"], **{**ADD, "quantity": "2.5"})
    with pytest.raises(v.ValidationError):
        inv_svc.add_item(s["admin"], **{**ADD, "price": "-1"})
    with pytest.raises(v.ValidationError):
        inv_svc.add_item(s["admin"], **{**ADD, "name": "  "})
    with pytest.raises(v.ValidationError):
        inv_svc.add_item(s["admin"], **{**ADD, "item_type": "Gadget"})
    assert inv_svc.add_item(s["admin"], **{**ADD, "name": "Oil", "item_type": "Consumable", "quantity": "2.5", "unit_of_measure": "liters"})
    assert inv_svc.add_item(s["admin"], **{**ADD, "name": "Empty shelf item", "quantity": "0"})        # zero stock is allowed
    with pytest.raises(PermissionDenied):
        inv_svc.add_item(s["staff"], **{**ADD, "name": "Nope"})
    exact, similar = inv_svc.find_similar_names("Calliper")
    assert not exact and similar == ["Caliper"]


def _edit(**over):
    base = dict(name="Caliper", category="Measuring", supplier="", description="", location="", item_type="Equipment",
                unit_of_measure="pcs", price="0", quantity="10", min_stock="0", tag_id="CAL-001")
    base.update(over)
    return base


def test_edit_cannot_lower_total_below_units_that_are_out(w):
    d, s, u, cal, grs = w
    run(d, "UPDATE inventory SET quantity_available = 5, quantity_in_maintenance = 1 WHERE tool_id=%s", (cal,))     # 4 deployed, 1 in maintenance
    with pytest.raises(Conflict, match="4 unit.*deployed.*1 are in maintenance"):
        inv_svc.update_item(s["admin"], cal, **_edit(quantity="4"))
    inv_svc.update_item(s["admin"], cal, **_edit(quantity="5"))        # exactly the held units is legal: nothing left available
    inv_svc.update_item(s["admin"], cal, **_edit(quantity="7", min_stock="2"))                                     # 7 - 5 held = 2 available
    i = inv(d, cal)
    assert (i["quantity_total"], i["quantity_available"], i["minimum_stock"]) == (7, 2, 2)


def test_edit_uses_locked_values_not_the_modals_stale_copy(w):
    d, s, u, cal, grs = w
    # the modal loaded available=10; meanwhile 6 were issued. Lowering to 5 must now be refused (6 are out).
    run(d, "UPDATE inventory SET quantity_available = 4 WHERE tool_id=%s", (cal,))
    with pytest.raises(Conflict):
        inv_svc.update_item(s["admin"], cal, **_edit(quantity="5"))
    inv_svc.update_item(s["admin"], cal, **_edit(quantity="6"))
    assert inv(d, cal)["quantity_available"] == 0


def test_edit_kg_to_fraction_updates_both_total_and_available(w):
    d, s, u, cal, grs = w
    # Keep the kilogram already out; only the change in owned total is available.
    run(d, "UPDATE inventory SET quantity_available = 4 WHERE tool_id=%s", (grs,))
    inv_svc.update_item(s["admin"], str(grs), **_edit(
        name="Grease", item_type="Consumable", unit_of_measure="kg",
        quantity="5.75", min_stock="1.25", tag_id="GRS-001"))
    i = inv(d, grs)
    assert (i["quantity_total"], i["quantity_available"], i["minimum_stock"]) == (
        Decimal("5.75"), Decimal("4.75"), Decimal("1.25"))


def test_edit_duplicates_condition_and_legacy_tags(w):
    d, s, u, cal, grs = w
    with pytest.raises(Conflict, match="already exists"):
        inv_svc.update_item(s["admin"], cal, **_edit(name="grease"))
    with pytest.raises(Conflict, match="Tag"):
        inv_svc.update_item(s["admin"], cal, **_edit(tag_id="GRS-001"))
    run(d, "UPDATE tool SET tag_id='cal_legacy_001' WHERE tool_id=%s", (cal,))                   # legacy format that fails the strict pattern
    inv_svc.update_item(s["admin"], cal, **_edit(tag_id="cal_legacy_001", price="12.5"))           # unchanged legacy tag is kept
    assert rows(d, "SELECT tag_id, price FROM tool WHERE tool_id=%s", (cal,))[0] == {"tag_id": "cal_legacy_001", "price": Decimal("12.50")}
    with pytest.raises(v.ValidationError):
        inv_svc.update_item(s["admin"], cal, **_edit(tag_id="bad tag!"))                         # a NEW tag must match the pattern
    import inspect
    assert "condition" not in inspect.signature(inv_svc.update_item.__wrapped__).parameters      # condition cannot be edited here


# ---- archive ---------------------------------------------------------------------------------------------------
def test_archive_refused_while_units_are_deployed_or_in_maintenance(w):
    d, s, u, cal, grs = w
    pid = run(d, "INSERT INTO projects (name, start_date, end_date, status, workers_assigned) VALUES ('P',%s,%s,'Approved','WKR-2026-001')",
              (TODAY, TODAY + timedelta(days=9)))
    run(d, "INSERT INTO project_requirements (project_id, tool_id, quantity) VALUES (%s,%s,2)", (pid, cal))
    iss.issue(s["admin"], u["w1"], pid, [{"tool_id": cal, "qty": 2}], "p")
    with pytest.raises(Conflict, match="2 unit.*deployed"):
        inv_svc.archive_tool(s["admin"], cal)
    iss.retrieve(s["admin"], u["w1"], cal, 1, "Damaged", "chipped")
    iss.retrieve(s["admin"], u["w1"], cal, 1, "Good", "")
    with pytest.raises(Conflict, match="1 are in maintenance"):
        inv_svc.archive_tool(s["admin"], cal)
    r = mnt.flag_tool(s["admin"], "CAL-001", "x", "Discrepancy", "n", 1)
    open_issue = rows(d, "SELECT issue_id FROM tool_issues WHERE condition_flag='Damaged'")[0]["issue_id"]
    mnt.resolve_issue(s["admin"], open_issue, "Good", "", "")
    assert inv_svc.archive_tool(s["admin"], cal)["name"] == "Caliper"
    assert rows(d, "SELECT is_archived, archived_at FROM tool WHERE tool_id=%s", (cal,))[0]["is_archived"] == 1
    with pytest.raises(Conflict, match="archived"):
        iss.lookup_tool(s["admin"], "CAL-001")
    inv_svc.restore_tool(s["admin"], cal)
    assert rows(d, "SELECT is_archived, archived_at FROM tool WHERE tool_id=%s", (cal,))[0] == {"is_archived": 0, "archived_at": None}
    with pytest.raises(Conflict, match="already active"):
        inv_svc.restore_tool(s["admin"], cal)


def test_database_trigger_also_refuses_archiving_a_tool_with_units_out(w):
    """Even raw SQL (a stale screen, a DBA) cannot archive a tool whose units are out, and the user sees a plain sentence."""
    d, s, u, cal, grs = w
    run(d, "UPDATE inventory SET quantity_available = 9, quantity_in_maintenance = 1 WHERE tool_id=%s", (cal,))
    with pytest.raises(mysql.connector.Error) as e:
        run(d, "UPDATE tool SET is_archived = 1 WHERE tool_id=%s", (cal,))
    assert friendly_message(e.value) == "A tool cannot be archived while units are deployed or in maintenance."


# ---- tags: Staff cannot change an assigned tag --------------------------------------------------------------------
def test_staff_can_tag_an_untagged_tool_but_only_admin_can_relink_or_unlink(w):
    d, s, u, cal, grs = w
    bare = run(d, "INSERT INTO tool (name, item_type) VALUES ('Saw','Equipment')")
    run(d, "INSERT INTO inventory (tool_id, quantity_total, quantity_available) VALUES (%s,1,1)", (bare,))
    assert inv_svc.assign_tag(s["staff"], bare, "saw-001")["tag_id"] == "SAW-001"                # Staff: allowed while untagged
    with pytest.raises(PermissionDenied, match="already has a tag"):
        inv_svc.assign_tag(s["staff"], bare, "SAW-002")                                           # Staff: cannot change it
    with pytest.raises(PermissionDenied):
        inv_svc.unlink_tag(s["staff"], bare)
    assert rows(d, "SELECT tag_id FROM tool WHERE tool_id=%s", (bare,))[0]["tag_id"] == "SAW-001"
    assert inv_svc.assign_tag(s["staff"], bare, "SAW-001")["changed"] is False                    # same tag again is harmless
    assert inv_svc.assign_tag(s["admin"], bare, "SAW-002")["changed"] is True                    # Admin: relink
    assert inv_svc.unlink_tag(s["admin"], bare)["old_tag"] == "SAW-002"
    with pytest.raises(Conflict, match="already used"):
        inv_svc.assign_tag(s["admin"], bare, "CAL-001")
    with pytest.raises(v.ValidationError):
        inv_svc.assign_tag(s["admin"], bare, "x")
