"""The seven reports. Admin only. Each query lives here ONCE and is used by both the screen and the PDF export, so the two cannot disagree.

[QUANTITIES] "Issued", "deployed", "retrieved", "usage" are SUMs of ``transaction.quantity`` (equipment rows have quantity 1, a consumable is
one row holding its exact amount), never COUNT(*) of rows, so 2.5 kg of grease counts 2.5. Loss/damage VALUE is price x quantity.
[HISTORY] History joins tools and people regardless of archive status: archiving a tool or employee never makes past totals shrink.
[4-DATE] Overdue uses the due date SNAPSHOT stored on each transaction at issuance (falling back to the project's date for old rows),
and the server's date.
"""
import math
from decimal import Decimal

from db import db
from services import validators as v
from services.security import require_role

# ABC by RANK (agreed rule): of the N ranked tools, A = the top 20%, B = the next 30%, C = the remaining 50%.
A_SHARE = Decimal("0.20")
AB_SHARE = Decimal("0.50")


def _n(x):
    """Whole numbers stay ints, fractional values stay exact (2 dp): 3.00 -> 3, 2.50 -> 2.5."""
    d = Decimal(str(x or 0))
    return int(d) if d == d.to_integral_value() else float(round(d, 2))


def _range(column, start, end):
    """Validated ' AND column >= ... AND column <= ...' clause. Dates are YYYY-MM-DD; ``end`` is inclusive for the whole day."""
    sd = v.parse_iso_date(start, field="From date", required=False)
    ed = v.parse_iso_date(end, field="To date", required=False)
    if sd and ed and sd > ed:
        raise v.ValidationError("The From date cannot be later than the To date.")
    sql, params = "", []
    if sd:
        sql += f" AND {column} >= %s"
        params.append(sd.isoformat())
    if ed:
        sql += f" AND {column} <= %s"
        params.append(ed.isoformat() + " 23:59:59")
    return sql, params, bool(sd or ed)


# ------------------------------------------------------------------------------------------------------------------------------
# ABC analysis
# ------------------------------------------------------------------------------------------------------------------------------
def classify_abc(ranked):
    """Pure function. ``ranked`` = [{"usage": Decimal, ...}] already sorted best-first. Adds rank/category.
    A = first ceil(20% of N) tools, B = up to ceil(50% of N), C = the rest. Tools that were never issued in the period are always C
    (they cannot be 'high priority' just because few tools were used)."""
    n = len(ranked)
    a_end = math.ceil(Decimal(n) * A_SHARE) if n else 0
    b_end = math.ceil(Decimal(n) * AB_SHARE) if n else 0
    for i, row in enumerate(ranked):
        row["rank"] = i + 1
        if Decimal(str(row["usage"])) <= 0:
            row["category"] = "C"
        elif i < a_end:
            row["category"] = "A"
        elif i < b_end:
            row["category"] = "B"
        else:
            row["category"] = "C"
    return ranked


@require_role("Admin")
def abc_analysis(actor, start=None, end=None) -> dict:
    """Rank ACTIVE tools by quantity issued in the period. Archived tools are left out of the ranking but counted in the historical
    totals, and shares are measured against that historical total, so archiving a tool never changes anyone else's percentage."""
    where, params, _ = _range("tr.borrow_date", start, end)
    with db.read() as cur:
        cur.execute(f"""
            SELECT t.tool_id, t.name, t.is_archived, COALESCE(SUM(tr.quantity), 0) AS usage_qty
            FROM tool t LEFT JOIN `transaction` tr ON tr.tool_id = t.tool_id {where}
            GROUP BY t.tool_id, t.name, t.is_archived""", params)
        tools = cur.fetchall()
    historical = sum((Decimal(str(t["usage_qty"])) for t in tools), Decimal(0))
    archived = sum((Decimal(str(t["usage_qty"])) for t in tools if t["is_archived"]), Decimal(0))
    ranked = sorted(({"tool_id": t["tool_id"], "name": t["name"], "usage": Decimal(str(t["usage_qty"]))}
                     for t in tools if not t["is_archived"]), key=lambda r: (-r["usage"], r["name"] or "", r["tool_id"]))
    classify_abc(ranked)
    cum = Decimal(0)
    for r in ranked:
        cum += r["usage"]
        r["cum_pct"] = float(cum / historical * 100) if historical > 0 else 0.0
        r["usage"] = _n(r["usage"])
    counts = {c: sum(1 for r in ranked if r["category"] == c) for c in "ABC"}
    return {"rows": ranked, "historical_total": _n(historical), "active_total": _n(historical - archived),
            "archived_total": _n(archived), "n_active": len(ranked), "counts": counts}


# ------------------------------------------------------------------------------------------------------------------------------
# the other reports
# ------------------------------------------------------------------------------------------------------------------------------
@require_role("Admin")
def usage_report(actor, start=None, end=None, search="") -> list:
    where, params, _ = _range("tr.borrow_date", start, end)
    like = v.like_pattern(search) if v.clean_search(search) else None
    extra = ""
    if like:
        extra = " AND (t.name LIKE %s OR CAST(t.tool_id AS CHAR) LIKE %s OR IFNULL(t.tag_id, '') LIKE %s OR t.`condition` LIKE %s)"
        params = params + [like] * 4
    with db.read() as cur:
        cur.execute(f"""
            SELECT t.tool_id, t.name, IFNULL(t.tag_id, 'Unassigned') AS tag_id,
                   COALESCE(SUM(tr.quantity), 0) AS total_borrowed,
                   COALESCE((SELECT SUM(x.quantity) FROM `transaction` x WHERE x.tool_id = t.tool_id AND x.status = 'Active'), 0) AS currently_out,
                   IFNULL(i.quantity_available, 0) AS qty_avail, t.`condition`
            FROM tool t LEFT JOIN inventory i ON i.tool_id = t.tool_id
            LEFT JOIN `transaction` tr ON tr.tool_id = t.tool_id {where}
            WHERE t.is_archived = 0 {extra}
            GROUP BY t.tool_id, t.name, t.tag_id, i.quantity_available, t.`condition`
            ORDER BY total_borrowed DESC, t.name""", params)
        rows = cur.fetchall()
    for r in rows:
        r["total_borrowed"], r["currently_out"], r["qty_avail"] = _n(r["total_borrowed"]), _n(r["currently_out"]), _n(r["qty_avail"])
    return rows


@require_role("Admin")
def activity_report(actor, start=None, end=None) -> list:
    where, params, _ = _range("tr.borrow_date", start, end)
    with db.read() as cur:
        cur.execute(f"""
            SELECT u.employee_id, u.full_name, u.role,
                   COALESCE(SUM(tr.quantity), 0) AS total_borrows,
                   COALESCE(SUM(CASE WHEN tr.status = 'Active' THEN tr.quantity ELSE 0 END), 0) AS active_borrows,
                   COALESCE(SUM(CASE WHEN tr.status = 'Returned' THEN tr.quantity ELSE 0 END), 0) AS total_returned
            FROM `user` u LEFT JOIN `transaction` tr ON tr.user_id = u.user_id {where}
            WHERE IFNULL(u.status, 'Active') <> 'Archived'
            GROUP BY u.user_id, u.employee_id, u.full_name, u.role
            ORDER BY total_borrows DESC, u.full_name""", params)
        rows = cur.fetchall()
    for r in rows:
        for k in ("total_borrows", "active_borrows", "total_returned"):
            r[k] = _n(r[k])
    return rows


@require_role("Admin")
def allocation_report(actor, start=None, end=None) -> list:
    where, params, filtered = _range("tr.borrow_date", start, end)
    having = " HAVING issued > 0 OR retrieved > 0" if filtered else ""
    with db.read() as cur:
        cur.execute(f"""
            SELECT p.name AS project_name, p.client, p.location, p.status, t.name AS tool_name, pr.quantity AS requested,
                   COALESCE(SUM(tr.quantity), 0) AS issued,
                   COALESCE(SUM(CASE WHEN tr.status = 'Returned' THEN tr.quantity ELSE 0 END), 0) AS retrieved,
                   pr.status AS req_status
            FROM projects p
            JOIN project_requirements pr ON pr.project_id = p.project_id
            JOIN tool t ON t.tool_id = pr.tool_id
            LEFT JOIN `transaction` tr ON tr.project_id = p.project_id AND tr.tool_id = t.tool_id {where}
            WHERE p.archived_at IS NULL
            GROUP BY p.project_id, p.name, p.client, p.location, p.status, t.tool_id, t.name, pr.quantity, pr.status
            {having}
            ORDER BY p.status ASC, p.name ASC, t.name ASC""", params)
        rows = cur.fetchall()
    for r in rows:
        for k in ("requested", "issued", "retrieved"):
            r[k] = _n(r[k])
    return rows


@require_role("Admin")
def damage_loss_report(actor, start=None, end=None) -> dict:
    """Detail rows plus a summary. Counts are UNITS and values are price x units (the old report counted rows and ignored quantity)."""
    where, params, _ = _range("tr.return_date", start, end)
    with db.read() as cur:
        cur.execute(f"""
            SELECT t.tool_id, t.name, IFNULL(t.price, 0) AS price, tr.quantity AS units, tr.condition_at_return AS cond_flag,
                   u.full_name AS returned_by, DATE_FORMAT(tr.return_date, '%Y-%m-%d') AS return_date,
                   IFNULL(tr.condition_return_notes, '—') AS notes
            FROM `transaction` tr JOIN tool t ON t.tool_id = tr.tool_id LEFT JOIN `user` u ON u.user_id = tr.user_id
            WHERE tr.type = 'Retrieval' AND tr.condition_at_return IN ('Damaged', 'Lost', 'Needs Repair') {where}
            ORDER BY tr.return_date DESC""", params)
        rows = cur.fetchall()
        cur.execute(f"""
            SELECT COALESCE(SUM(CASE WHEN tr.condition_at_return = 'Lost' THEN IFNULL(t.price, 0) * tr.quantity ELSE 0 END), 0) AS total_loss,
                   COALESCE(SUM(CASE WHEN tr.condition_at_return = 'Damaged' THEN IFNULL(t.price, 0) * tr.quantity ELSE 0 END), 0) AS total_damage,
                   COALESCE(SUM(CASE WHEN tr.condition_at_return = 'Lost' THEN tr.quantity ELSE 0 END), 0) AS count_lost,
                   COALESCE(SUM(CASE WHEN tr.condition_at_return = 'Damaged' THEN tr.quantity ELSE 0 END), 0) AS count_damaged,
                   COALESCE(SUM(CASE WHEN tr.condition_at_return = 'Needs Repair' THEN tr.quantity ELSE 0 END), 0) AS count_repair
            FROM `transaction` tr JOIN tool t ON t.tool_id = tr.tool_id
            WHERE tr.type = 'Retrieval' AND tr.condition_at_return IN ('Damaged', 'Lost', 'Needs Repair') {where}""", params)
        summary = cur.fetchone()
    for r in rows:
        r["units"] = _n(r["units"])
    for k in ("count_lost", "count_damaged", "count_repair"):
        summary[k] = _n(summary[k])
    return {"rows": rows, "summary": summary}


@require_role("Admin")
def low_stock_report(actor) -> list:
    with db.read() as cur:
        cur.execute("""
            SELECT t.tool_id, t.name, t.item_type, t.category, IFNULL(t.supplier, '—') AS supplier,
                   IFNULL(t.unit_of_measure, 'pcs') AS uom, IFNULL(i.quantity_available, 0) AS qty_avail,
                   IFNULL(i.quantity_total, 0) AS qty_total, IFNULL(i.minimum_stock, 0) AS minimum_stock, IFNULL(t.price, 0) AS price
            FROM tool t JOIN inventory i ON i.tool_id = t.tool_id
            WHERE t.is_archived = 0 AND i.minimum_stock > 0 AND i.quantity_available < i.minimum_stock
            ORDER BY (i.quantity_available / NULLIF(i.minimum_stock, 0)) ASC""")
        rows = cur.fetchall()
    for r in rows:
        r["qty_avail"], r["qty_total"], r["minimum_stock"] = _n(r["qty_avail"]), _n(r["qty_total"]), _n(r["minimum_stock"])
    return rows


@require_role("Admin")
def overdue_report(actor, start=None, end=None) -> list:
    """Active issuances past their DUE DATE SNAPSHOT (taken at issuance; falls back to the project's end date for old rows)."""
    where, params, _ = _range("tr.borrow_date", start, end)
    with db.read() as cur:
        cur.execute(f"""
            SELECT u.employee_id, u.full_name, t.name AS tool_name, IFNULL(p.name, '—') AS project_name,
                   COALESCE(tr.due_date, p.end_date) AS due_date, tr.quantity AS units,
                   DATEDIFF(CURDATE(), COALESCE(tr.due_date, p.end_date)) AS days_overdue,
                   tr.borrow_date, IFNULL(t.price, 0) AS price
            FROM `transaction` tr JOIN `user` u ON u.user_id = tr.user_id JOIN tool t ON t.tool_id = tr.tool_id
            LEFT JOIN projects p ON p.project_id = tr.project_id
            WHERE tr.status = 'Active' AND COALESCE(tr.due_date, p.end_date) < CURDATE() {where}
            ORDER BY days_overdue DESC, tr.borrow_date""", params)
        rows = cur.fetchall()
    for r in rows:
        r["units"] = _n(r["units"])
    return rows
