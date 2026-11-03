"""Maintenance: flagging tools and resolving tickets. Admin only.

[CONCURRENCY][RBAC] Every function is one transaction that locks the tool's inventory row and the ticket row first, so a stale
modal (ticket already resolved by someone else) or two Admins acting together cannot corrupt stock.

Stock rules (see services/stock_ledger.py): ``quantity_total`` = units the company owns.
  * Damaged / Needs Repair / Missing Parts tickets hold units in ``quantity_in_maintenance``.
  * Lost / Stolen tickets record units that already left the total.
  * Discrepancy / Other are records only: no unit moves.
Resolving a repair ticket with condition Good returns the units to stock (total UNCHANGED: the old screen added to total AND
available, inflating stock); any other outcome removes them from service for good. "Restock quantity" is for NEW or FOUND units
and is the only way the total grows.
"""
from decimal import Decimal

from db import db
from services import validators as v
from services.errors import Conflict, NotFound
from services.security import require_role
from services.stock_ledger import (lock_inventory, lose_units_from_stock, quarantine_units, receive_units,
                                   refresh_tool_condition, resolve_maintenance, resolve_maintenance_as_lost)

ISSUE_FLAGS = ("Damaged", "Lost", "Needs Repair", "Discrepancy", "Missing Parts", "Stolen", "Other")
LOSS_FLAGS = ("Lost", "Stolen")
REPAIR_FLAGS = ("Damaged", "Needs Repair", "Missing Parts")
OUTCOMES = ("Good", "Needs Repair", "Damaged", "Lost")


@require_role("Admin")
def flag_tool(actor, tool_ref, reported_by, condition, notes, quantity=1) -> dict:
    """Manually flag ``quantity`` unit(s) of a tool that are physically in stock."""
    ref = v.clean_text(tool_ref, max_len=100, field="Tool PID or Tag ID")
    reporter_text = v.clean_text(reported_by, max_len=100, field="Reported By")
    if condition not in ISSUE_FLAGS:
        raise v.ValidationError("Please choose an issue type.")
    notes = v.clean_text(notes, max_len=v.MAX_NOTES, field="Notes", required=False, multiline=True) or "No additional details."
    qty = v.parse_quantity(quantity, field="Quantity")
    moves_stock = condition in REPAIR_FLAGS or condition in LOSS_FLAGS

    def work(cur):
        if ref.isdigit():
            cur.execute("SELECT tool_id, name, item_type, unit_of_measure FROM tool WHERE tool_id = %s", (ref,))
        else:
            scan = v.parse_scan(ref)
            cur.execute("SELECT tool_id, name, item_type, unit_of_measure FROM tool WHERE tag_id = %s", (scan.value if scan.kind == "tool" else ref,))
        tool = cur.fetchone()
        if not tool:
            raise NotFound("No tool found with that PID or Tag ID.")
        v.item_quantity(qty, tool["item_type"], tool.get("unit_of_measure"), field="Quantity")
        lock_inventory(cur, [tool["tool_id"]])
        cur.execute("SELECT user_id FROM `user` WHERE employee_id = %s", (reporter_text,))
        rep = cur.fetchone()
        if condition in REPAIR_FLAGS:
            quarantine_units(cur, tool["tool_id"], qty)
        elif condition in LOSS_FLAGS:
            lose_units_from_stock(cur, tool["tool_id"], qty)
        cur.execute("""INSERT INTO tool_issues (tool_id, reported_by, reported_by_user_id, condition_flag, notes, quantity)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (tool["tool_id"], reporter_text, rep["user_id"] if rep else None, condition, notes,
                     qty if moves_stock else Decimal(0)))
        issue_id = cur.lastrowid
        refresh_tool_condition(cur, tool["tool_id"])
        return {"issue_id": issue_id, "tool_id": tool["tool_id"], "name": tool["name"], "moved": moves_stock}

    return db.run_in_transaction(work)


@require_role("Admin")
def resolve_issue(actor, issue_id, outcome, restock_quantity, resolution_notes) -> dict:
    """Close a ticket. ``outcome`` is the final condition of the affected unit(s)."""
    if outcome not in OUTCOMES:
        raise v.ValidationError("Please choose the final condition.")
    resolution = v.clean_text(resolution_notes, max_len=500, field="Resolution notes", required=False) or "Marked resolved by Admin."
    raw = str(restock_quantity if restock_quantity is not None else "").strip()
    restock = Decimal(0) if raw in ("", "0", "0.0", "0.00") else v.parse_quantity(raw, field="Restock quantity")

    def work(cur):
        cur.execute("SELECT * FROM tool_issues WHERE issue_id = %s FOR UPDATE", (issue_id,))
        t = cur.fetchone()
        if not t:
            raise NotFound("Issue not found.")
        if t["status"] != "Open":
            raise Conflict("This issue has already been resolved.")           # stale modal / two Admins
        inv = lock_inventory(cur, [t["tool_id"]])[t["tool_id"]]
        v.item_quantity(restock, inv["item_type"], inv.get("unit_of_measure"), field="Restock quantity", allow_zero=True)
        qty = Decimal(str(t["quantity"] or 0))
        effect = "no stock change"
        if t["condition_flag"] in REPAIR_FLAGS and qty > 0:
            movable = min(qty, inv["quantity_in_maintenance"])      # tickets migrated from the old system may predate unit tracking
            if movable > 0:
                if outcome == "Good":
                    resolve_maintenance(cur, t["tool_id"], movable, repaired=True)
                    cur.execute("UPDATE tool SET last_serviced_at = NOW() WHERE tool_id = %s", (t["tool_id"],))   # [PANEL-AWE] a repair restarts the service clock
                    effect = f"{v.fmt_qty(movable)} unit(s) returned to stock"
                elif outcome == "Lost":
                    resolve_maintenance_as_lost(cur, t["tool_id"], movable)
                    effect = f"{v.fmt_qty(movable)} unit(s) written off as lost"
                else:
                    resolve_maintenance(cur, t["tool_id"], movable, repaired=False)
                    effect = f"{v.fmt_qty(movable)} unit(s) removed from stock"
        elif t["condition_flag"] in LOSS_FLAGS and qty > 0 and outcome == "Good":
            receive_units(cur, t["tool_id"], qty)                      # the lost units were found
            effect = f"{v.fmt_qty(qty)} unit(s) found and returned to stock"
        if restock > 0:
            receive_units(cur, t["tool_id"], restock)
            effect += f"; {v.fmt_qty(restock)} new unit(s) added"
        cur.execute("""UPDATE tool_issues SET status = 'Resolved', resolved_by = %s, resolved_at = NOW(),
                              notes = CONCAT(IFNULL(notes, ''), ' | Resolution (', %s, '): ', %s)
                       WHERE issue_id = %s""", (actor["user_id"], outcome, resolution, issue_id))
        refresh_tool_condition(cur, t["tool_id"])
        return {"issue_id": issue_id, "tool_id": t["tool_id"], "outcome": outcome, "effect": effect, "name": inv["name"]}

    return db.run_in_transaction(work)
