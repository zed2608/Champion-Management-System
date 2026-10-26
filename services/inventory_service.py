"""Inventory writes: add, edit, archive/restore and tag links.

[RBAC] Admin changes inventory. Staff may only assign a tag to a tool that has none (the Tagging module); once a tag is assigned
only an Admin can relink or unlink it. A tool's CONDITION cannot be edited here at all: it is a display flag derived from open
Maintenance tickets, and condition changes go through ``maintenance_service``.
[CONCURRENCY] Edits lock the inventory row and re-check against the locked values, not against what the modal loaded
(a concurrent issuance used to make the "cannot go below deployed" check wrong).
"""
import difflib
from decimal import Decimal

from db import db
from services import validators as v
from services.errors import Conflict, NotFound, PermissionDenied
from services.security import require_role
from services.stock_ledger import lock_inventory

ITEM_TYPES = ("Equipment", "Consumable")


def find_similar_names(name, exclude_tool_id=None):
    """Read-only helper for the "Similar name detected" prompt: (exact_match: bool, similar: list[str])."""
    name = v.clean_named_label(name, max_len=v.MAX_NAME, field="Product Name")
    with db.read() as cur:
        cur.execute("SELECT name FROM tool WHERE is_archived = 0 AND tool_id <> %s", (exclude_tool_id or 0,))
        existing = [r["name"] for r in cur.fetchall() if r["name"]]
    exact = any(n.lower() == name.lower() for n in existing)
    similar = [n for n in existing if n.lower() != name.lower()
               and difflib.SequenceMatcher(None, name.lower(), n.lower()).ratio() > 0.85]
    return exact, similar[:3]


def _blank_if_placeholder(text):
    return None if not text or text.strip().upper() in ("N/A", "NONE", "TYPE OR SELECT...") else text


def _clean_fields(item_type, category, name, description, supplier, location, unit_of_measure, price):
    if item_type not in ITEM_TYPES:
        raise v.ValidationError("Item type must be Equipment or Consumable.")
    uom = v.clean_text(unit_of_measure, max_len=20, field="Unit of measure").lower()
    if uom not in v.UNITS:
        raise v.ValidationError("Choose a unit from the list (pcs, boxes, sets, kg, packs, liters, rolls, meters or feet).")
    return {
        "name": v.clean_named_label(name, max_len=v.MAX_NAME, field="Product Name"),
        "category": v.clean_named_label(category, max_len=100, field="Category"),
        # the item panel DISPLAYS a missing supplier/location as 'N/A'; saving it back must not turn the display text into data
        "supplier": _blank_if_placeholder(v.clean_named_label(supplier, max_len=100, field="Supplier", required=False)),
        "description": v.clean_text(description, max_len=v.MAX_NOTES, field="Description", required=False, multiline=True) or None,
        "location": _blank_if_placeholder(v.clean_text(location, max_len=100, field="Location", required=False)),
        "unit_of_measure": uom,
        "price": v.parse_price(price if str(price or "").strip() else 0),
    }


def _stock_value(raw, item_type, uom, field):
    if str(raw if raw is not None else "").strip() == "":
        raise v.ValidationError(f"{field} is required.")
    return v.item_quantity(raw, item_type, uom, field=field, allow_zero=True)


@require_role("Admin")
def add_item(actor, *, name, category, supplier, description, location, item_type, unit_of_measure, price, quantity) -> dict:
    f = _clean_fields(item_type, category, name, description, supplier, location, unit_of_measure, price)
    qty = _stock_value(quantity, item_type, f["unit_of_measure"], "Quantity")

    def work(cur):
        cur.execute("SELECT 1 AS x FROM tool WHERE is_archived = 0 AND name = %s FOR UPDATE", (f["name"],))
        if cur.fetchone():
            raise Conflict(f"A product named '{f['name']}' already exists in active inventory.")
        cur.execute("""INSERT INTO tool (category, supplier, name, description, price, location, item_type, unit_of_measure,
                                         `condition`, date_acquired, is_archived)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Good', NOW(), 0)""",
                    (f["category"], f["supplier"], f["name"], f["description"], f["price"], f["location"], item_type,
                     f["unit_of_measure"]))
        tool_id = cur.lastrowid
        cur.execute("INSERT INTO inventory (tool_id, quantity_total, quantity_available) VALUES (%s, %s, %s)", (tool_id, qty, qty))
        return {"tool_id": tool_id, "name": f["name"], "quantity": qty}

    return db.run_in_transaction(work)


@require_role("Admin")
def update_item(actor, tool_id, *, name, category, supplier, description, location, item_type, unit_of_measure, price,
                quantity, min_stock, tag_id) -> dict:
    """Edit an item. The Total Qty may not drop below the units that are deployed or in maintenance (checked under lock)."""
    f = _clean_fields(item_type, category, name, description, supplier, location, unit_of_measure, price)
    new_total = _stock_value(quantity, item_type, f["unit_of_measure"], "Total Qty")
    new_min = v.item_quantity(min_stock if str(min_stock or "").strip() else 0, item_type, f["unit_of_measure"],
                              field="Min Stock", allow_zero=True)
    tag_raw = v.clean_text(tag_id, max_len=100, field="Tag ID", required=False)

    def work(cur):
        inv = lock_inventory(cur, [tool_id])[tool_id]
        cur.execute("SELECT tag_id, unit_of_measure FROM tool WHERE tool_id = %s", (tool_id,))
        current = cur.fetchone() or {}
        current_tag = current.get("tag_id")
        if inv["item_type"] != item_type or (current.get("unit_of_measure") or "pcs").lower() != f["unit_of_measure"]:
            cur.execute("SELECT EXISTS(SELECT 1 FROM `transaction` WHERE tool_id=%s) AS used", (tool_id,))
            used = cur.fetchone()["used"]
            cur.execute("SELECT EXISTS(SELECT 1 FROM project_requirements WHERE tool_id=%s) AS used", (tool_id,))
            if used or cur.fetchone()["used"] or inv["quantity_in_maintenance"] or inv["quantity_total"] != inv["quantity_available"]:
                raise Conflict("This item has project, issue or maintenance records. Its type and unit can no longer be changed.")
        # an unchanged (possibly legacy-format) tag is kept as is; only a NEW tag must match the strict pattern
        if not tag_raw:
            tag = None
        elif current_tag and tag_raw.upper() == current_tag.upper():
            tag = current_tag
        else:
            tag = v.validate_tag_id(tag_raw)
        cur.execute("SELECT 1 AS x FROM tool WHERE is_archived = 0 AND name = %s AND tool_id <> %s", (f["name"], tool_id))
        if cur.fetchone():
            raise Conflict(f"Another product named '{f['name']}' already exists.")
        if tag:
            cur.execute("SELECT 1 AS x FROM tool WHERE tag_id = %s AND tool_id <> %s", (tag, tool_id))
            if cur.fetchone():
                raise Conflict("Tag ID is already used by another tool.")
        held = inv["quantity_total"] - inv["quantity_available"]          # deployed + in maintenance, from the LOCKED row
        if new_total < held:
            maint = inv["quantity_in_maintenance"]
            raise Conflict(f"You cannot lower the Total Quantity to {v.fmt_qty(new_total)}: {v.fmt_qty(held - maint)} unit(s) are deployed "
                           f"and {v.fmt_qty(maint)} are in maintenance (at least {v.fmt_qty(held)} must stay on the books).")
        cur.execute("""UPDATE tool SET name=%s, description=%s, category=%s, supplier=%s, location=%s, item_type=%s,
                              unit_of_measure=%s, price=%s, tag_id=%s WHERE tool_id=%s""",
                    (f["name"], f["description"], f["category"], f["supplier"], f["location"], item_type,
                     f["unit_of_measure"], f["price"], tag, tool_id))
        cur.execute("UPDATE inventory SET quantity_total = %s, quantity_available = quantity_available + %s, minimum_stock = %s "
                    "WHERE tool_id = %s", (new_total, new_total - inv["quantity_total"], new_min, tool_id))
        return {"tool_id": tool_id, "name": f["name"]}

    return db.run_in_transaction(work)


@require_role("Admin")
def archive_tool(actor, tool_id) -> dict:
    """Archive a tool. Refused while any unit is deployed or in maintenance (the database trigger enforces the same rule)."""
    def work(cur):
        inv = lock_inventory(cur, [tool_id])[tool_id]
        if inv["is_archived"]:
            raise Conflict("This item is already archived.")
        cur.execute("SELECT COALESCE(SUM(quantity), 0) AS d FROM `transaction` WHERE tool_id = %s AND status = 'Active'", (tool_id,))
        deployed = Decimal(str(cur.fetchone()["d"]))
        maint = inv["quantity_in_maintenance"]
        if deployed > 0 or maint > 0:
            parts = []
            if deployed > 0:
                parts.append(f"{v.fmt_qty(deployed)} unit(s) are still deployed")
            if maint > 0:
                parts.append(f"{v.fmt_qty(maint)} are in maintenance")
            raise Conflict("This item cannot be archived: " + " and ".join(parts) + ". Retrieve or resolve them first.")
        cur.execute("UPDATE tool SET is_archived = 1, archived_at = NOW() WHERE tool_id = %s", (tool_id,))
        return {"tool_id": tool_id, "name": inv["name"]}

    return db.run_in_transaction(work)


@require_role("Admin")
def restore_tool(actor, tool_id) -> dict:
    def work(cur):
        cur.execute("SELECT name, is_archived FROM tool WHERE tool_id = %s FOR UPDATE", (tool_id,))
        t = cur.fetchone()
        if not t:
            raise NotFound("Item not found.")
        if not t["is_archived"]:
            raise Conflict("This item is already active.")
        cur.execute("UPDATE tool SET is_archived = 0, archived_at = NULL WHERE tool_id = %s", (tool_id,))
        return {"tool_id": tool_id, "name": t["name"]}

    return db.run_in_transaction(work)


@require_role("Admin", "Staff")
def assign_tag(actor, tool_id, tag_id) -> dict:
    """Give a tool its QR tag id. Staff may do this only while the tool has NO tag; an Admin may also relink.
    Raises PermissionDenied for Staff trying to change an assigned tag."""
    tag = v.validate_tag_id(tag_id)

    def work(cur):
        cur.execute("SELECT name, tag_id FROM tool WHERE tool_id = %s FOR UPDATE", (tool_id,))
        t = cur.fetchone()
        if not t:
            raise NotFound("Item not found.")
        if t["tag_id"] and t["tag_id"].upper() == tag:
            return {"tool_id": tool_id, "tag_id": tag, "name": t["name"], "changed": False}
        if t["tag_id"] and actor["role"] != "Admin":
            raise PermissionDenied("This tool already has a tag. Only an administrator can change an assigned tag.")
        cur.execute("SELECT 1 AS x FROM tool WHERE tag_id = %s AND tool_id <> %s", (tag, tool_id))
        if cur.fetchone():
            raise Conflict(f"Tag '{tag}' is already used by another tool.")
        cur.execute("UPDATE tool SET tag_id = %s WHERE tool_id = %s", (tag, tool_id))
        return {"tool_id": tool_id, "tag_id": tag, "name": t["name"], "changed": True}

    return db.run_in_transaction(work)


@require_role("Admin")
def unlink_tag(actor, tool_id) -> dict:
    def work(cur):
        cur.execute("SELECT name, tag_id FROM tool WHERE tool_id = %s FOR UPDATE", (tool_id,))
        t = cur.fetchone()
        if not t:
            raise NotFound("Item not found.")
        cur.execute("UPDATE tool SET tag_id = NULL WHERE tool_id = %s", (tool_id,))
        return {"tool_id": tool_id, "name": t["name"], "old_tag": t["tag_id"]}

    return db.run_in_transaction(work)
