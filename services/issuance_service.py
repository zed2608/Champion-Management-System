"""Issuance & Retrieval business logic. The view collects input and shows results; every rule lives here.

[CONCURRENCY] ``issue()`` and ``retrieve()`` are each ONE ACID transaction:
    lock inventory rows (ascending tool_id) -> lock the project's requirement rows -> re-validate everything from the
    locked, fresh rows -> guarded stock UPDATE -> history rows -> COMMIT, or ROLLBACK (and one retry on deadlock / lock timeout).
The tool cache and anything the screen showed are only hints; nothing is trusted at commit time.

[4-DATE] Issuance and retrieval times are the server's ``NOW()`` (the triggers fill ``borrow_date`` and the project start/end
snapshot). Issuing to a project whose end date has passed is refused; issuing BEFORE its start date is allowed ("staged early")
because a literal "Issuance <= Start" rule would block every top-up issuance once a project has started.
"""
from dataclasses import dataclass, field
from decimal import Decimal

from db import db
from services import validators as v
from services.errors import Conflict, NotFound, ServiceError
from services.security import require_role
from services.stock_ledger import (InsufficientStock, lock_inventory, refresh_tool_condition, return_units, take_stock)
from services.tool_cache import tool_cache

STAFF = ("Admin", "Staff")
CONDITIONS = ("Good", "Needs Repair", "Damaged", "Lost")
ISSUABLE_PROJECT_STATUSES = ("Approved", "Ongoing")


def _is_whole_only(item_type) -> bool:
    """Equipment is counted in whole units; only consumables may be fractional."""
    return (item_type or "Equipment") != "Consumable"


def _num(x) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


# =====================================================================================================================
# Issuance
# =====================================================================================================================
@require_role(*STAFF)
def verify_borrower(actor, employee_id) -> dict:
    """Who is receiving the tools, and which of their projects still need tools?
    Archived / inactive / locked accounts are refused (they used to be accepted)."""
    emp = v.clean_text(employee_id, max_len=50, field="Employee ID")
    with db.read() as cur:
        cur.execute("SELECT user_id, full_name, role, status FROM `user` WHERE employee_id = %s", (emp,))
        u = cur.fetchone()
        if not u:
            raise NotFound("Employee ID not found.")
        if u["status"] != "Active":
            raise Conflict(f"This account is {u['status']}, so it cannot receive tools.")
        # exact membership through the project_workers junction (the old LIKE '%WKR-2026-001%' also matched WKR-2026-0011)
        cur.execute("""
            SELECT p.project_id, p.name, p.client, p.status, p.end_date, CURDATE() AS today,
                   EXISTS (SELECT 1 FROM project_requirements pr WHERE pr.project_id = p.project_id AND pr.status <> 'Fulfilled') AS needs_tools
            FROM projects p JOIN project_workers pw ON pw.project_id = p.project_id AND pw.user_id = %s
            WHERE p.archived_at IS NULL AND p.status IN ('Pending', 'Approved', 'Ongoing')
            ORDER BY p.project_id""", (u["user_id"],))
        u["projects"], u["notices"] = [], []
        for p in cur.fetchall():
            if p["status"] == "Pending":
                u["notices"].append(f"'{p['name']}' is still waiting for approval.")
            elif p["end_date"] is not None and p["end_date"] < p["today"]:
                u["notices"].append(f"'{p['name']}' ended on {p['end_date']}, so tools can no longer be issued to it.")
            elif not p["needs_tools"]:
                u["notices"].append(f"'{p['name']}': all of its required tools have already been issued.")
            else:
                u["projects"].append({"project_id": p["project_id"], "name": p["name"], "client": p["client"]})
        if not u["projects"] and not u["notices"]:
            u["notices"].append("This employee is not assigned to any active project.")
    return u


def _requirements(cur, project_id):
    cur.execute("""
        SELECT pr.req_id, pr.tool_id, t.name, t.item_type, pr.quantity AS req_qty, pr.status,
               COALESCE((SELECT SUM(tr.quantity) FROM `transaction` tr
                         WHERE tr.project_id = pr.project_id AND tr.tool_id = pr.tool_id
                           AND tr.type = 'Issue' AND tr.status = 'Active'), 0) AS issued_qty
        FROM project_requirements pr JOIN tool t ON t.tool_id = pr.tool_id
        WHERE pr.project_id = %s ORDER BY pr.req_id""", (project_id,))
    return cur.fetchall()


@require_role(*STAFF)
def project_requirements(actor, project_id) -> dict:
    """Header + requirement lines (with how many units are deployed right now) for the issuance screen."""
    with db.read() as cur:
        cur.execute("SELECT project_id, name, client, location, status FROM projects WHERE project_id = %s", (project_id,))
        p = cur.fetchone()
        if not p:
            raise NotFound("Project not found.")
        p["reqs"] = _requirements(cur, project_id)
    return p


@dataclass
class ToolInfo:
    tool_id: int
    name: str
    tag_id: str
    item_type: str
    condition: str
    available: Decimal
    in_maintenance: Decimal


def _tool_from_db(tag):
    with db.read() as cur:
        cur.execute("""SELECT t.tool_id, t.name, t.tag_id, t.item_type, t.`condition` AS tool_condition, t.is_archived,
                              COALESCE(i.quantity_available, 0) AS av, COALESCE(i.quantity_in_maintenance, 0) AS maint
                       FROM tool t LEFT JOIN inventory i ON i.tool_id = t.tool_id WHERE t.tag_id = %s""", (tag,))
        r = cur.fetchone()
    if not r:
        return None
    return ToolInfo(r["tool_id"], r["name"], r["tag_id"], r["item_type"], r["tool_condition"], r["av"], r["maint"]), bool(r["is_archived"])


@require_role(*STAFF)
def lookup_tool(actor, scanned) -> ToolInfo:
    """Resolve a scanned/typed tag for the cart. O(1) from the tool cache; falls back to the database when the cache
    has not loaded yet or the tag is new. The answer is a hint: ``issue()`` re-checks stock and condition under lock."""
    scan = v.parse_scan(scanned)
    if scan.kind == "worker":
        raise ServiceError("That is an employee badge, not a tool tag.")
    tag = scan.value if scan.kind == "tool" else v.clean_text(scanned, max_len=100, field="Tag ID")
    rec = tool_cache.by_tag(tag)
    if rec is not None:
        info, archived = ToolInfo(rec.tool_id, rec.name, rec.tag_id, rec.item_type, rec.condition,
                                  rec.quantity_available, rec.quantity_in_maintenance), rec.is_archived
    else:
        found = _tool_from_db(tag)
        if not found:
            raise NotFound("Invalid or unassigned Tag ID.")
        info, archived = found
    if archived:
        raise Conflict(f"'{info.name}' is archived and cannot be issued.")
    if info.available <= 0:
        if info.in_maintenance > 0:
            raise Conflict(f"'{info.name}' cannot be issued: all remaining units are in maintenance.")
        raise Conflict(f"'{info.name}' is currently out of stock.")
    return info


@dataclass
class IssueResult:
    transaction_ids: list = field(default_factory=list)
    receipt_lines: list = field(default_factory=list)          # [(tool name, Decimal qty)]
    all_fulfilled: bool = False
    project_now_ongoing: bool = False
    issued_at: object = None                                    # server NOW() as stored on the first row


@require_role(*STAFF)
def issue(actor, borrower_id, project_id, cart, purpose) -> IssueResult:
    """Issue ``cart`` ([{"tool_id": int, "qty": number}, ...]) to ``borrower_id`` for ``project_id`` atomically."""
    merged = {}
    for item in cart or []:
        tid = int(item["tool_id"])
        merged[tid] = merged.get(tid, Decimal(0)) + v.parse_quantity(item["qty"], field="Quantity")
    if not merged:
        raise v.ValidationError("The cart is empty. Scan at least one tool.")
    purpose = v.clean_text(purpose, max_len=255, field="Project")
    tool_ids = sorted(merged)

    def work(cur):
        res = IssueResult()                                     # fresh on every attempt (retry-safe)

        # -- who and where (read under shared lock so they cannot be archived / edited while we issue)
        cur.execute("SELECT user_id, full_name, status FROM `user` WHERE user_id = %s FOR SHARE", (borrower_id,))
        borrower = cur.fetchone()
        if not borrower:
            raise NotFound("Employee not found.")
        if borrower["status"] != "Active":
            raise Conflict(f"This account is {borrower['status']}, so it cannot receive tools.")
        cur.execute("SELECT project_id, name, status, archived_at, end_date, CURDATE() AS today "
                    "FROM projects WHERE project_id = %s FOR SHARE", (project_id,))
        proj = cur.fetchone()
        if not proj or proj["archived_at"] is not None:
            raise NotFound("Project not found.")
        if proj["status"] not in ISSUABLE_PROJECT_STATUSES:
            raise Conflict(f"Project is {proj['status']}; tools can only be issued to Approved or Ongoing projects.")
        if proj["end_date"] is not None and proj["end_date"] < proj["today"]:
            raise Conflict("This project has ended; tools cannot be issued to it.")
        cur.execute("SELECT 1 AS x FROM project_workers WHERE project_id = %s AND user_id = %s", (project_id, borrower_id))
        if not cur.fetchone():
            raise Conflict("This employee is not assigned to the selected project.")

        # -- locks: inventory first (ascending tool_id), then the project's requirement rows (ascending req_id)
        inv = lock_inventory(cur, tool_ids)
        cur.execute("SELECT req_id, tool_id, quantity, status FROM project_requirements "
                    "WHERE project_id = %s ORDER BY req_id FOR UPDATE", (project_id,))
        reqs = {r["tool_id"]: r for r in cur.fetchall()}

        # -- re-validate each line from the locked rows
        for tid in tool_ids:
            row, qty = inv[tid], merged[tid]
            if row["is_archived"]:
                raise Conflict(f"'{row['name']}' is archived and cannot be issued.")
            if _is_whole_only(row["item_type"]) and qty != qty.to_integral_value():
                raise v.ValidationError(f"'{row['name']}' is equipment and must be issued in whole numbers.")
            if tid not in reqs:
                raise Conflict(f"'{row['name']}' is not approved for this project.")
            cur.execute("SELECT COALESCE(SUM(quantity), 0) AS d FROM `transaction` WHERE project_id = %s AND tool_id = %s "
                        "AND type = 'Issue' AND status = 'Active'", (project_id, tid))
            deployed = _num(cur.fetchone()["d"])
            if deployed + qty > reqs[tid]["quantity"]:
                raise Conflict(f"Cannot issue {v.fmt_qty(qty)} x '{row['name']}': approved {v.fmt_qty(reqs[tid]['quantity'])}, "
                               f"already deployed {v.fmt_qty(deployed)}.")
            if qty > row["quantity_available"]:
                if row["quantity_in_maintenance"] > 0 and row["quantity_available"] <= 0:
                    raise Conflict(f"'{row['name']}': all remaining units are in maintenance.")
                raise InsufficientStock(tid, qty, row["quantity_available"])

        # -- writes
        for tid in tool_ids:
            row, qty = inv[tid], merged[tid]
            take_stock(cur, tid, qty)
            # equipment: one row per unit (per-unit condition at return); consumables: ONE row with the exact quantity
            pieces = [Decimal(1)] * int(qty) if _is_whole_only(row["item_type"]) else [qty]
            for piece in pieces:
                cur.execute("""INSERT INTO `transaction`
                                 (user_id, tool_id, project_id, type, purpose, quantity, status, condition_at_borrow, issued_by)
                               VALUES (%s, %s, %s, 'Issue', %s, %s, 'Active', %s, %s)""",
                            (borrower_id, tid, project_id, purpose, piece, row["tool_condition"], actor["user_id"]))
                res.transaction_ids.append(cur.lastrowid)
            res.receipt_lines.append((row["name"], qty))

        cur.execute("SELECT borrow_date FROM `transaction` WHERE transaction_id = %s", (res.transaction_ids[0],))
        res.issued_at = cur.fetchone()["borrow_date"]

        # -- requirement lines fulfilled? project becomes Ongoing when every line is
        all_done = True
        for tid, r in reqs.items():
            cur.execute("SELECT COALESCE(SUM(quantity), 0) AS d FROM `transaction` WHERE project_id = %s AND tool_id = %s "
                        "AND type = 'Issue' AND status = 'Active'", (project_id, tid))
            if _num(cur.fetchone()["d"]) >= r["quantity"]:
                if r["status"] != "Fulfilled":
                    cur.execute("UPDATE project_requirements SET status = 'Fulfilled' WHERE req_id = %s", (r["req_id"],))
            else:
                all_done = False
        res.all_fulfilled = all_done
        if all_done:
            cur.execute("UPDATE projects SET status = 'Ongoing' WHERE project_id = %s AND status = 'Approved'", (project_id,))
            res.project_now_ongoing = cur.rowcount == 1
        return res

    return db.run_in_transaction(work)


# =====================================================================================================================
# Retrieval
# =====================================================================================================================
@require_role(*STAFF)
def verify_returner(actor, employee_id) -> dict:
    """Who is handing tools back. Archived accounts are still accepted here: someone who left may still owe tools."""
    emp = v.clean_text(employee_id, max_len=50, field="Employee ID")
    with db.read() as cur:
        cur.execute("SELECT user_id, full_name, role, status FROM `user` WHERE employee_id = %s", (emp,))
        u = cur.fetchone()
    if not u:
        raise NotFound("Employee ID not found.")
    return u


@require_role(*STAFF)
def find_deployed(actor, user_id, tag_or_trn) -> dict:
    """Which tool is the borrower returning, and how many units do they hold? Accepts a tag, 'TRN-42' or a bare number."""
    raw = v.clean_text(tag_or_trn, max_len=100, field="Tag ID or TRN")
    scan = v.parse_scan(raw)
    if scan.kind == "worker":
        raise ServiceError("That is an employee badge. Scan the tool's tag instead.")
    key = raw.upper()
    trn = key[4:].split("-")[0] if key.startswith("TRN-") else (key if key.isdigit() else None)
    with db.read() as cur:
        if trn is not None and trn.isdigit():
            cur.execute("SELECT tool_id FROM `transaction` WHERE transaction_id = %s AND user_id = %s AND status = 'Active'",
                        (trn, user_id))
        else:
            cur.execute("SELECT tool_id FROM tool WHERE tag_id = %s", (scan.value if scan.kind == "tool" else raw,))
        target = cur.fetchone()
        if not target:
            raise NotFound("No active records found for this tag / TRN.")
        cur.execute("""SELECT t.tool_id, t.name, IFNULL(t.item_type, 'Equipment') AS item_type,
                              COALESCE(SUM(tr.quantity), 0) AS deployed
                       FROM `transaction` tr JOIN tool t ON t.tool_id = tr.tool_id
                       WHERE tr.tool_id = %s AND tr.user_id = %s AND tr.status = 'Active'
                       GROUP BY t.tool_id, t.name, t.item_type""", (target["tool_id"], user_id))
        rec = cur.fetchone()
    if not rec:
        raise NotFound("This employee has no active records for that tool.")
    return rec


@dataclass
class RetrieveResult:
    closed_ids: list = field(default_factory=list)
    quantity: Decimal = Decimal(0)
    condition: str = "Good"
    ticket_id: int = None
    tool_name: str = ""


@require_role(*STAFF)
def retrieve(actor, user_id, tool_id, qty, condition, notes) -> RetrieveResult:
    """Take ``qty`` units of ``tool_id`` back from ``user_id``, oldest issuance first, all in one transaction.
    Good units return to stock; Damaged / Needs Repair units go to maintenance; Lost units leave the total. For anything
    that is not Good the maintenance ticket is created INSIDE this transaction and condition details are required."""
    if condition not in CONDITIONS:
        raise v.ValidationError("Please choose a return condition.")
    notes = v.clean_text(notes, max_len=v.MAX_NOTES, field="Condition details", required=(condition != "Good"), multiline=True)
    want = v.parse_quantity(qty, field="Quantity")

    def work(cur):
        res = RetrieveResult(condition=condition)
        inv = lock_inventory(cur, [tool_id])[tool_id]
        res.tool_name = inv["name"]
        if _is_whole_only(inv["item_type"]) and want != want.to_integral_value():
            raise v.ValidationError("Equipment items must be returned in whole numbers.")
        cur.execute("SELECT * FROM `transaction` WHERE tool_id = %s AND user_id = %s AND status = 'Active' "
                    "ORDER BY borrow_date, transaction_id FOR UPDATE", (tool_id, user_id))
        rows = cur.fetchall()
        held = sum((_num(r["quantity"]) for r in rows), Decimal(0))
        if want > held:
            raise Conflict(f"Cannot retrieve {v.fmt_qty(want)}: only {v.fmt_qty(held)} deployed to this employee.")

        remaining = want
        for r in rows:
            if remaining <= 0:
                break
            take = min(_num(r["quantity"]), remaining)
            if take == _num(r["quantity"]):                    # whole line comes back
                cur.execute("""UPDATE `transaction` SET status = 'Returned', type = 'Retrieval', return_date = NOW(),
                                      condition_at_return = %s, condition_return_notes = %s, received_by = %s
                               WHERE transaction_id = %s""",
                            (condition, notes or None, actor["user_id"], r["transaction_id"]))
                res.closed_ids.append(r["transaction_id"])
            else:                                              # partial (consumable): split the line, history keeps both parts
                cur.execute("UPDATE `transaction` SET quantity = quantity - %s WHERE transaction_id = %s", (take, r["transaction_id"]))
                cur.execute("""INSERT INTO `transaction`
                                 (user_id, tool_id, project_id, type, purpose, quantity, borrow_date, return_date, project_start_date,
                                  due_date, status, condition_at_borrow, condition_at_return, condition_return_notes, issued_by, received_by)
                               VALUES (%s, %s, %s, 'Retrieval', %s, %s, %s, NOW(), %s, %s, 'Returned', %s, %s, %s, %s, %s)""",
                            (r["user_id"], r["tool_id"], r["project_id"], r["purpose"], take, r["borrow_date"],
                             r["project_start_date"], r["due_date"], r["condition_at_borrow"], condition, notes or None,
                             r["issued_by"], actor["user_id"]))
                res.closed_ids.append(cur.lastrowid)
            remaining -= take
        res.quantity = want

        if condition == "Good":
            return_units(cur, tool_id, good=want)
        elif condition == "Lost":
            return_units(cur, tool_id, lost=want)
        else:
            return_units(cur, tool_id, damaged=want)
        if condition != "Good":                                # [UNHAPPY-PATH] ticket inside the same transaction
            cur.execute("""INSERT INTO tool_issues (tool_id, transaction_id, reported_by, reported_by_user_id, condition_flag,
                                                    notes, quantity)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                        (tool_id, res.closed_ids[0], actor["full_name"], actor["user_id"], condition, notes, want))
            res.ticket_id = cur.lastrowid
        refresh_tool_condition(cur, tool_id)
        return res

    return db.run_in_transaction(work)
