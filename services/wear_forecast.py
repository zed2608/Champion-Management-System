"""[PANEL-AWE] Wear and maintenance forecast.

For every Equipment tool: how many hours has it been out on a job, how close is it to its service interval, how fast is it being used
lately, and is it breaking more often than the other tools of its category?

Method (plain arithmetic, NumPy only):
  * hours out = for every transaction, quantity x (return_date, or NOW while the tool is still out) - borrow_date), in hours.
    Hours before ``last_serviced_at`` do not count towards the next service (the interval restarts when a tool is serviced).
  * service interval = the tool's own ``service_interval_hours``, else its category default (Admin-editable), else the '*' default.
  * rate = hours out during the last 30 days / 30  (hours per day).  due in N days = (interval - hours since service) / rate.
  * damage events = maintenance tickets for the tool + damaged/lost returns that have no ticket. damage rate = events per 100 hours out.
  * flags: ">= 90% of the interval used" and "damage rate more than 2 standard deviations above its category's average".
"""
from datetime import datetime, timedelta

import numpy as np

from db import db
from services.errors import NotFound
from services.security import require_role
from services.validators import ValidationError, clean_text

DEFAULT_INTERVAL_HOURS = 500
GLOBAL_KEY = "*"
DUE_SOON_PCT = 90.0
RATE_WINDOW_DAYS = 30
MIN_HOURS_FOR_RATE = 10.0          # a tool used for 3 hours with one damage report is noise, not a trend
MIN_TOOLS_FOR_STATS = 3            # a category average needs at least this many tools
Z_FLAG = 2.0
DAMAGED_RETURNS = ("Damaged", "Lost", "Needs Repair")


def _hours(a, b):
    return max(0.0, (b - a).total_seconds() / 3600.0)


def _overlap_hours(start, end, win_start, win_end):
    s, e = max(start, win_start), min(end, win_end)
    return _hours(s, e) if e > s else 0.0


# ---- pure computation (unit tested with fixed fake data) ------------------------------------------------------------------------------------
def compute_forecast(tools, txns, issues, defaults, now):
    """tools: [{tool_id, name, category, price, interval, last_serviced_at, units}]
    txns: [{transaction_id, tool_id, quantity, borrow_date, return_date or None, condition_at_return}]
    issues: [{tool_id, transaction_id or None}]    defaults: {category: hours, '*': hours}.  Returns one dict per tool, worst first."""
    by_tool = {}
    for t in txns:
        if t["borrow_date"] is not None:
            by_tool.setdefault(t["tool_id"], []).append(t)
    tickets_by_tool, ticketed_txns = {}, set()
    for i in issues:
        tickets_by_tool[i["tool_id"]] = tickets_by_tool.get(i["tool_id"], 0) + 1
        if i.get("transaction_id") is not None:
            ticketed_txns.add(i["transaction_id"])
    win_start = now - timedelta(days=RATE_WINDOW_DAYS)
    out = []
    for tool in tools:
        total = since = recent = 0.0
        untracked_damaged = 0
        served = tool.get("last_serviced_at")
        for t in by_tool.get(tool["tool_id"], []):
            end = t["return_date"] or now
            q = float(t["quantity"] or 1)
            total += q * _hours(t["borrow_date"], end)
            since += q * (_overlap_hours(t["borrow_date"], end, served, now) if served else _hours(t["borrow_date"], end))
            recent += q * _overlap_hours(t["borrow_date"], end, win_start, now)
            if (t.get("condition_at_return") in DAMAGED_RETURNS and t["transaction_id"] not in ticketed_txns):
                untracked_damaged += 1
        interval = tool.get("interval") or defaults.get(tool.get("category")) or defaults.get(GLOBAL_KEY) or DEFAULT_INTERVAL_HOURS
        units = max(1.0, float(tool.get("units") or 1))
        per_unit_since = since / units
        pct = 100.0 * per_unit_since / interval
        rate = recent / RATE_WINDOW_DAYS / units                       # hours per day, per unit
        remaining = interval - per_unit_since
        if remaining <= 0:
            days = 0.0
        elif rate > 0:
            days = remaining / rate
        else:
            days = None                                                # not used lately: no honest prediction
        events = tickets_by_tool.get(tool["tool_id"], 0) + untracked_damaged
        out.append({"tool_id": tool["tool_id"], "name": tool["name"], "category": tool.get("category") or "Uncategorized",
                    "price": float(tool.get("price") or 0), "total_hours": round(total, 2), "hours_since_service": round(per_unit_since, 2),
                    "interval": float(interval), "pct_used": round(pct, 1), "rate_per_day": round(rate, 3),
                    "days_to_due": None if days is None else round(days, 1), "damage_events": events,
                    "damage_rate": round(100.0 * events / total, 3) if total >= MIN_HOURS_FOR_RATE else None,
                    "category_mean": None, "category_std": None, "z": None, "flags": []})
    # damage rate against the tool's own category (NumPy mean / standard deviation)
    cats = {}
    for r in out:
        if r["damage_rate"] is not None:
            cats.setdefault(r["category"], []).append(r)
    for rows in cats.values():
        if len(rows) < MIN_TOOLS_FOR_STATS:
            continue
        arr = np.array([r["damage_rate"] for r in rows], dtype=float)
        mean, std = float(arr.mean()), float(arr.std())
        for r in rows:
            r["category_mean"], r["category_std"] = round(mean, 3), round(std, 3)
            if std > 0:
                r["z"] = round((r["damage_rate"] - mean) / std, 2)
    for r in out:
        if r["pct_used"] >= DUE_SOON_PCT:
            r["flags"].append("overdue for service" if r["pct_used"] >= 100 else "service due soon")
        if r["z"] is not None and r["z"] > Z_FLAG:
            r["flags"].append("breaks more than its category")
    out.sort(key=lambda r: (not r["flags"], -(r["pct_used"]), r["name"] or ""))
    return out


def summary_line(r):
    """The numbers behind a flag, in one plain sentence."""
    bits = [f"{r['hours_since_service']:g} of {r['interval']:g} service hours used ({r['pct_used']:g}%)"]
    if r["days_to_due"] is None:
        bits.append("not used in the last 30 days")
    elif r["days_to_due"] <= 0:
        bits.append("service is overdue")
    else:
        bits.append(f"due in about {r['days_to_due']:g} days at {r['rate_per_day']:g} h/day")
    if r["z"] is not None and r["z"] > Z_FLAG:
        bits.append(f"damage rate {r['damage_rate']:g} per 100 h vs category average {r['category_mean']:g} (z = {r['z']:g})")
    return "; ".join(bits)


# ---- database access ------------------------------------------------------------------------------------------------------------------------
def _load(cur):
    cur.execute("SELECT NOW() AS now")
    now = cur.fetchone()["now"]
    cur.execute("SELECT category, service_interval_hours AS hours FROM category_service_defaults")
    defaults = {r["category"]: r["hours"] for r in cur.fetchall()}
    cur.execute("SELECT t.tool_id, t.name, t.category, t.price, t.service_interval_hours AS `interval`, t.last_serviced_at, "
                "IFNULL(i.quantity_total, 1) AS units FROM tool t LEFT JOIN inventory i ON i.tool_id = t.tool_id "
                "WHERE t.is_archived = 0 AND IFNULL(t.item_type, 'Equipment') = 'Equipment'")
    tools = cur.fetchall()
    cur.execute("SELECT transaction_id, tool_id, quantity, borrow_date, return_date, condition_at_return FROM `transaction` "
                "WHERE borrow_date IS NOT NULL")
    txns = cur.fetchall()
    cur.execute("SELECT tool_id, transaction_id FROM tool_issues")
    issues = cur.fetchall()
    return tools, txns, issues, defaults, now


@require_role("Admin")
def forecast(actor, limit=None):
    """Every active Equipment tool with its wear numbers; flagged tools first. ``limit`` keeps only the first N."""
    with db.read() as cur:
        tools, txns, issues, defaults, now = _load(cur)
    rows = compute_forecast(tools, txns, issues, defaults, now)
    return rows[:limit] if limit else rows


@require_role("Admin")
def list_defaults(actor):
    with db.read() as cur:
        cur.execute("SELECT category, service_interval_hours AS hours FROM category_service_defaults ORDER BY category = '*' DESC, category")
        return cur.fetchall()


@require_role("Admin")
def set_category_default(actor, category, hours):
    category = GLOBAL_KEY if str(category).strip() == GLOBAL_KEY else clean_text(category, max_len=100, field="Category")
    hours = _interval(hours)
    with db.transaction() as cur:
        cur.execute("INSERT INTO category_service_defaults (category, service_interval_hours) VALUES (%s,%s) "
                    "ON DUPLICATE KEY UPDATE service_interval_hours = VALUES(service_interval_hours)", (category, hours))
    return {"category": category, "hours": hours}


@require_role("Admin")
def set_tool_interval(actor, tool_id, hours):
    """A tool's own interval; None or empty goes back to the category default."""
    value = None if hours in (None, "") else _interval(hours)
    with db.transaction() as cur:
        cur.execute("UPDATE tool SET service_interval_hours = %s WHERE tool_id = %s", (value, tool_id))
        if cur.rowcount == 0:
            cur.execute("SELECT 1 FROM tool WHERE tool_id = %s", (tool_id,))
            if cur.fetchone() is None:
                raise NotFound("That tool no longer exists.")
    return {"tool_id": tool_id, "interval": value}


@require_role("Admin")
def mark_serviced(actor, tool_id, when=None):
    """Restart the service clock of a tool (``when``: datetime, default now)."""
    with db.transaction() as cur:
        if when is None:
            cur.execute("UPDATE tool SET last_serviced_at = NOW() WHERE tool_id = %s", (tool_id,))
        else:
            cur.execute("UPDATE tool SET last_serviced_at = %s WHERE tool_id = %s", (when, tool_id))
        if cur.rowcount == 0:
            cur.execute("SELECT 1 FROM tool WHERE tool_id = %s", (tool_id,))
            if cur.fetchone() is None:
                raise NotFound("That tool no longer exists.")
    from database import log_action
    log_action(actor["user_id"], "Edited", "Maintenance", f"Marked tool PID {tool_id} as serviced")
    return {"tool_id": tool_id}


def _interval(value):
    try:
        n = int(str(value).strip())
    except ValueError:
        raise ValidationError("Service interval must be a whole number of hours.")
    if not 1 <= n <= 100000:
        raise ValidationError("Service interval must be between 1 and 100,000 hours.")
    return n


def pdf_table(rows):
    """[PANEL-AWE] (labels, rows, notes) for the printed report, built from the same rows the screen shows."""
    def due(r):
        if r["days_to_due"] is None:
            return "not used lately"
        return "overdue" if r["days_to_due"] <= 0 else f"{r['days_to_due']:g} days"
    labels = ["Tool", "Category", "Hours since service", "Interval (h)", "% used", "Due in", "Damage / 100 h", "Flags"]
    body = [[r["name"], r["category"], f"{r['hours_since_service']:g}", f"{r['interval']:g}", f"{r['pct_used']:g}%", due(r),
             "-" if r["damage_rate"] is None else f"{r['damage_rate']:g}", ", ".join(r["flags"]) or "-"] for r in rows]
    flagged = sum(1 for r in rows if r["flags"])
    notes = [f"{flagged} of {len(rows)} tools flagged. Hours = quantity-weighted time out on jobs since the last service; due-in uses the last "
             f"{RATE_WINDOW_DAYS} days of use; flagged at {DUE_SOON_PCT:g}% of the interval or a damage rate above 2 standard deviations over the category average."]
    return labels, body, notes
