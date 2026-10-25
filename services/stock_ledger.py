"""Stock movements: the only code allowed to change inventory quantities.

[CONCURRENCY] Pattern for every write that touches stock (issuance, retrieval, maintenance, inventory edit):

    def work(cur):
        rows = lock_inventory(cur, tool_ids)        # 1. SELECT ... ORDER BY tool_id FOR UPDATE   (fixed order: no deadlock)
        ...re-validate condition / stock / quota from `rows` (fresh, locked)...      # 2. never trust a cache or a screen
        take_stock(cur, tool_id, qty)               # 3. UPDATE ... WHERE quantity_available >= qty ; rowcount must be 1
        cur.execute("INSERT INTO transaction ...")  # 4. history
    db.run_in_transaction(work)                     # 5. COMMIT, or ROLLBACK + one retry on deadlock/lock timeout

Steps 1 and 3 are belt and braces: the lock makes the re-validation valid, and the guarded UPDATE keeps stock from going
negative even if a caller forgets step 1.

Identity maintained by this module (``quantity_total`` = units the company still owns):
    quantity_available = quantity_total - deployed - quantity_in_maintenance
A LOST unit leaves ``quantity_total`` (exactly as the old screens did, so Inventory, Reports and the dashboard keep showing the
same totals) and is also added to ``quantity_lost``, a running count kept for reports and the wear/anomaly features.
"""
from decimal import Decimal

from services.errors import ServiceError


class StockError(ServiceError):
    """Base class; the message is user-safe."""


class ToolNotFound(StockError):
    pass


class InsufficientStock(StockError):
    def __init__(self, tool_id, requested, available):
        self.tool_id, self.requested, self.available = tool_id, requested, available
        super().__init__(f"Only {available} available (requested {requested}).")


def _d(x) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


def lock_inventory(cur, tool_ids) -> dict:
    """Lock the inventory rows of ``tool_ids`` in ascending tool_id order and return {tool_id: row}.
    Only inventory rows are locked (``FOR UPDATE OF i``), so renaming a tool does not wait behind an issuance."""
    ids = sorted({int(t) for t in tool_ids})
    if not ids:
        return {}
    ph = ",".join(["%s"] * len(ids))
    cur.execute(
        f"""SELECT i.tool_id, i.quantity_total, i.quantity_available, i.quantity_in_maintenance, i.quantity_lost,
                   t.name, t.`condition` AS tool_condition, t.is_archived, t.item_type, t.unit_of_measure
            FROM inventory i JOIN tool t ON t.tool_id = i.tool_id
            WHERE i.tool_id IN ({ph}) ORDER BY i.tool_id FOR UPDATE OF i""", ids)
    rows = {r["tool_id"]: r for r in cur.fetchall()}
    missing = [i for i in ids if i not in rows]
    if missing:
        raise ToolNotFound(f"Tool {missing[0]} was not found in inventory.")
    return rows


def take_stock(cur, tool_id, qty) -> None:
    """Atomically move ``qty`` units out of 'available' (issuance). Raises InsufficientStock if not enough."""
    qty = _d(qty)
    cur.execute("UPDATE inventory SET quantity_available = quantity_available - %s "
                "WHERE tool_id = %s AND quantity_available >= %s", (qty, tool_id, qty))
    if cur.rowcount != 1:
        cur.execute("SELECT quantity_available FROM inventory WHERE tool_id = %s", (tool_id,))
        row = cur.fetchone()
        if row is None:
            raise ToolNotFound(f"Tool {tool_id} was not found in inventory.")
        raise InsufficientStock(tool_id, qty, row["quantity_available"])


def return_units(cur, tool_id, *, good=0, damaged=0, lost=0) -> None:
    """Retrieval, per unit: good units go back to available; damaged units move to in_maintenance; lost units leave the
    total (and are counted in quantity_lost). One damaged unit no longer blocks the other units of the same tool."""
    good, damaged, lost = _d(good), _d(damaged), _d(lost)
    cur.execute("UPDATE inventory SET quantity_available = quantity_available + %s, "
                "quantity_in_maintenance = quantity_in_maintenance + %s, "
                "quantity_total = quantity_total - %s, quantity_lost = quantity_lost + %s "
                "WHERE tool_id = %s", (good, damaged, lost, lost, tool_id))
    if cur.rowcount != 1:
        raise ToolNotFound(f"Tool {tool_id} was not found in inventory.")


_FLAG_RANK = (("Lost", 3), ("Damaged", 2), ("Needs Repair", 1))


def refresh_tool_condition(cur, tool_id) -> str:
    """tool.condition is now a DISPLAY flag derived from OPEN tickets (worst one wins, else 'Good'); it no longer blocks
    issuing, because units are tracked individually. Keeps the dashboard, Inventory and Maintenance screens consistent."""
    cur.execute("SELECT DISTINCT condition_flag AS f FROM tool_issues WHERE tool_id = %s AND status = 'Open'", (tool_id,))
    flags = {r["f"] for r in cur.fetchall()}
    cond = next((name for name, _ in _FLAG_RANK if name in flags), "Good")
    cur.execute("UPDATE tool SET `condition` = %s WHERE tool_id = %s AND (`condition` IS NULL OR `condition` <> %s)",
                (cond, tool_id, cond))
    return cond


def resolve_maintenance(cur, tool_id, qty, *, repaired: bool) -> None:
    """Close out ``qty`` units from maintenance. repaired=True -> back to available (total unchanged: fixes the old bug
    that added to BOTH total and available). repaired=False -> written off (total shrinks)."""
    qty = _d(qty)
    if repaired:
        sql = ("UPDATE inventory SET quantity_in_maintenance = quantity_in_maintenance - %s, "
               "quantity_available = quantity_available + %s WHERE tool_id = %s AND quantity_in_maintenance >= %s")
        args = (qty, qty, tool_id, qty)
    else:
        sql = ("UPDATE inventory SET quantity_in_maintenance = quantity_in_maintenance - %s, "
               "quantity_total = quantity_total - %s WHERE tool_id = %s AND quantity_in_maintenance >= %s")
        args = (qty, qty, tool_id, qty)
    cur.execute(sql, args)
    if cur.rowcount != 1:
        raise StockError("Those units are not in maintenance any more.")


def resolve_maintenance_as_lost(cur, tool_id, qty) -> None:
    """Close out ``qty`` units from maintenance as LOST: they leave the total and are counted in quantity_lost."""
    qty = _d(qty)
    cur.execute("UPDATE inventory SET quantity_in_maintenance = quantity_in_maintenance - %s, "
                "quantity_total = quantity_total - %s, quantity_lost = quantity_lost + %s "
                "WHERE tool_id = %s AND quantity_in_maintenance >= %s", (qty, qty, qty, tool_id, qty))
    if cur.rowcount != 1:
        raise StockError("Those units are not in maintenance any more.")


def quarantine_units(cur, tool_id, qty) -> None:
    """A manual flag on units that are physically in stock: available -> in maintenance (total unchanged)."""
    qty = _d(qty)
    cur.execute("UPDATE inventory SET quantity_available = quantity_available - %s, "
                "quantity_in_maintenance = quantity_in_maintenance + %s "
                "WHERE tool_id = %s AND quantity_available >= %s", (qty, qty, tool_id, qty))
    if cur.rowcount != 1:
        raise StockError("Not enough units are in stock to flag. Units that are deployed must be retrieved first.")


def lose_units_from_stock(cur, tool_id, qty) -> None:
    """A manual 'Lost' / 'Stolen' flag on units that were in stock: they leave the total and are counted as lost."""
    qty = _d(qty)
    cur.execute("UPDATE inventory SET quantity_available = quantity_available - %s, quantity_total = quantity_total - %s, "
                "quantity_lost = quantity_lost + %s WHERE tool_id = %s AND quantity_available >= %s",
                (qty, qty, qty, tool_id, qty))
    if cur.rowcount != 1:
        raise StockError("Not enough units are in stock to flag. Units that are deployed must be retrieved first.")


def receive_units(cur, tool_id, qty) -> None:
    """New or found units: total and available both grow by ``qty`` (replacement bought, lost unit found)."""
    qty = _d(qty)
    cur.execute("UPDATE inventory SET quantity_total = quantity_total + %s, quantity_available = quantity_available + %s "
                "WHERE tool_id = %s", (qty, qty, tool_id))
    if cur.rowcount != 1:
        raise ToolNotFound(f"Tool {tool_id} was not found in inventory.")
