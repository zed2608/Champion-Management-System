"""[PANEL-AWE] Anomaly and bottleneck detector.

Three questions, answered from data already in the database, each answer carrying the numbers behind it:

  (a) Who or what loses or damages tools unusually often?  Damaged / lost units as a share of units issued, per PROJECT, per CLIENT and per
      WORKER. An entity is an outlier when its rate is above the upper fence of the group (Tukey: Q3 + 1.5 x IQR) and it has real volume.
  (b) Which Category A tool (the top 20% by units issued) keeps being asked for when none is free?  Blocked issuance attempts in the last
      30 days (``issuance_attempts``) that exceed the tool's total stock mean the stock is too small for the demand.
  (c) Where are overdue tools piling up?  Three or more overdue issuances held by the same project or the same worker.

``recommendations`` turns the findings into plain sentences, ranked by estimated peso impact (``tool.price`` x units). A recommendation is never
produced without its evidence: ``evidence`` lists the numbers, and the sentence repeats them.
"""
import math
from datetime import timedelta
from decimal import Decimal

import numpy as np

from db import db
from services.errors import get_logger
from services.security import require_role

WINDOW_DAYS = 30
DAMAGE_WINDOW_DAYS = 180
MIN_ENTITIES = 4               # a fence needs a few peers to mean anything
MIN_UNITS_ISSUED = 5           # an entity that received 2 tools and broke 1 is not a pattern
MIN_BAD_UNITS = 2
MIN_CLUSTER = 3                # overdue issuances held by one project / worker
IQR_K = 1.5
REASONS = ("out_of_stock", "over_quota", "past_end")
BAD_CONDITIONS = ("Damaged", "Lost", "Needs Repair")
DAMAGE_FLAGS = ("Damaged", "Lost", "Stolen", "Needs Repair", "Missing Parts")


def peso(x):
    return f"P{float(x):,.2f}"


def _q(x):
    return f"{float(x):g}"


# ---- recording blocked attempts -----------------------------------------------------------------------------------------------------------------
def log_attempt(reason, tool_id=None, project_id=None, borrower_id=None, actor_id=None, quantity=None, available=None, detail=None):
    """Remember that an issuance was refused. Never raises: a failing log must not change what the person sees."""
    if reason not in REASONS:
        return
    try:
        with db.transaction() as cur:
            cur.execute("INSERT INTO issuance_attempts (tool_id, project_id, user_id, actor_id, quantity, available, reason, detail) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                        (tool_id, project_id, borrower_id, actor_id, None if quantity is None else Decimal(str(quantity)),
                         None if available is None else Decimal(str(available)), reason, (detail or "")[:255] or None))
    except Exception:
        get_logger().warning("Could not record a blocked issuance attempt", exc_info=True)


# ---- (a) damage and loss rates -----------------------------------------------------------------------------------------------------------------
def iqr_fence(values, k=IQR_K):
    """(q1, q3, upper fence) with NumPy percentiles (linear interpolation)."""
    arr = np.array(values, dtype=float)
    q1, q3 = np.percentile(arr, [25, 75])
    return float(q1), float(q3), float(q3 + k * (q3 - q1))


def damage_outliers(rows):
    """rows: [{transaction_id, tool_id, quantity, price, project_id, project_name, client, user_id, worker, bad}]  (bad = the unit(s) came back
    damaged / lost or got a damage ticket). Returns findings for projects, clients and workers whose damage rate is above the group's fence."""
    findings = []
    for dim, key_of, label_of in (("project", lambda r: r["project_id"], lambda r: r["project_name"] or f"Project {r['project_id']}"),
                                  ("client", lambda r: r["client"], lambda r: r["client"]),
                                  ("worker", lambda r: r["user_id"], lambda r: r["worker"])):
        groups = {}
        for r in rows:
            k = key_of(r)
            if k is None or k == "":
                continue
            g = groups.setdefault(k, {"label": label_of(r), "issued": 0.0, "bad": 0.0, "value": 0.0})
            q = float(r["quantity"] or 0)
            g["issued"] += q
            if r["bad"]:
                g["bad"] += q
                g["value"] += q * float(r["price"] or 0)
        eligible = {k: g for k, g in groups.items() if g["issued"] >= MIN_UNITS_ISSUED}
        if len(eligible) < MIN_ENTITIES:
            continue
        rates = {k: g["bad"] / g["issued"] for k, g in eligible.items()}
        q1, q3, fence = iqr_fence(list(rates.values()))
        for k, g in eligible.items():
            if rates[k] > fence and g["bad"] >= MIN_BAD_UNITS:
                findings.append({"kind": "damage_outlier", "dimension": dim, "key": k, "label": g["label"], "issued": g["issued"], "bad": g["bad"],
                                 "rate": rates[k], "fence": fence, "q1": q1, "q3": q3, "peers": len(eligible), "value": g["value"],
                                 "peer_median": float(np.median(list(rates.values())))})
    return findings


# ---- (b) Category A tools that are asked for when none is free ---------------------------------------------------------------------------------
def blocked_demand(abc_rows, tools, attempts):
    """abc_rows: [{tool_id, name, category}], tools: {tool_id: {name, price, stock}}, attempts: [{tool_id, reason}] (already limited to the window).
    A Category A tool whose blocked attempts exceed its total stock is a bottleneck."""
    cat_a = {r["tool_id"] for r in abc_rows if r["category"] == "A"}
    counts = {}
    for a in attempts:
        if a["tool_id"] in cat_a and a["reason"] in ("out_of_stock", "over_quota"):
            counts[a["tool_id"]] = counts.get(a["tool_id"], 0) + 1
    findings = []
    for tid, n in counts.items():
        t = tools.get(tid)
        if t is None:
            continue
        stock = float(t["stock"])
        if n > stock:
            shortfall = int(math.ceil(n - stock))
            findings.append({"kind": "bottleneck", "tool_id": tid, "name": t["name"], "blocked": n, "stock": stock, "shortfall": shortfall,
                             "price": float(t["price"] or 0), "value": shortfall * float(t["price"] or 0)})
    return findings


# ---- (c) overdue clusters -----------------------------------------------------------------------------------------------------------------------
def overdue_clusters(rows):
    """rows: overdue issuances [{transaction_id, project_id, project_name, user_id, worker, tool_name, price, quantity, days_overdue}]."""
    findings = []
    for dim, key_of, label_of in (("project", lambda r: r["project_id"], lambda r: r["project_name"] or f"Project {r['project_id']}"),
                                  ("worker", lambda r: r["user_id"], lambda r: r["worker"])):
        groups = {}
        for r in rows:
            k = key_of(r)
            if k is None:
                continue
            g = groups.setdefault(k, {"label": label_of(r), "n": 0, "units": 0.0, "value": 0.0, "max_days": 0, "workers": set(), "tools": set()})
            g["n"] += 1
            g["units"] += float(r["quantity"] or 0)
            g["value"] += float(r["quantity"] or 0) * float(r["price"] or 0)
            g["max_days"] = max(g["max_days"], int(r["days_overdue"] or 0))
            g["workers"].add(r["worker"])
            g["tools"].add(r["tool_name"])
        for k, g in groups.items():
            if g["n"] >= MIN_CLUSTER:
                findings.append({"kind": "overdue_cluster", "dimension": dim, "key": k, "label": g["label"], "count": g["n"], "units": g["units"],
                                 "value": g["value"], "max_days": g["max_days"], "workers": len(g["workers"]), "tools": len(g["tools"])})
    return findings


# ---- plain-language recommendations ---------------------------------------------------------------------------------------------------------------
def recommendations(damage, bottlenecks, clusters):
    """Findings -> [{title, text, evidence, peso_impact, kind}] ranked by peso impact (largest first)."""
    out = []
    for f in bottlenecks:
        text = (f"Procure {f['shortfall']} more {f['name']}: blocked {f['blocked']} times in the last {WINDOW_DAYS} days against {_q(f['stock'])} in stock, "
                f"Category A. Estimated cost {peso(f['value'])}.")
        out.append({"kind": "procure", "title": f"Procure {f['shortfall']} more {f['name']}", "text": text, "peso_impact": f["value"],
                    "evidence": [f"blocked attempts (30 days): {f['blocked']}", f"total stock: {_q(f['stock'])}", "ABC category: A",
                                 f"unit price: {peso(f['price'])}", f"shortfall: {f['shortfall']} x {peso(f['price'])} = {peso(f['value'])}"]})
    for f in damage:
        who = {"project": "project", "client": "client", "worker": "worker"}[f["dimension"]]
        text = (f"Review the {who} {f['label']}: {_q(f['bad'])} of {_q(f['issued'])} units came back damaged or lost ({f['rate'] * 100:.0f}%), "
                f"while the usual rate among {f['peers']} {who}s is {f['peer_median'] * 100:.0f}% (upper limit {f['fence'] * 100:.0f}%). "
                f"Value of the damaged/lost units: {peso(f['value'])}.")
        out.append({"kind": "damage", "title": f"Review {who} {f['label']}", "text": text, "peso_impact": f["value"],
                    "evidence": [f"damaged/lost units: {_q(f['bad'])} of {_q(f['issued'])} issued ({f['rate'] * 100:.1f}%)",
                                 f"peer median rate: {f['peer_median'] * 100:.1f}% across {f['peers']} {who}s", f"upper fence (Q3 + 1.5 x IQR): {f['fence'] * 100:.1f}%",
                                 f"value lost or damaged: {peso(f['value'])}"]})
    for f in clusters:
        who = "project" if f["dimension"] == "project" else "worker"
        text = (f"Follow up the {who} {f['label']}: {f['count']} overdue issuances ({_q(f['units'])} units, worth {peso(f['value'])}), "
                f"the longest {f['max_days']} days late.")
        out.append({"kind": "overdue", "title": f"Follow up {who} {f['label']}", "text": text, "peso_impact": f["value"],
                    "evidence": [f"overdue issuances: {f['count']}", f"units held: {_q(f['units'])}", f"longest overdue: {f['max_days']} days",
                                 f"value at risk: {peso(f['value'])}"]})
    out.sort(key=lambda r: (-r["peso_impact"], r["title"]))
    return out


# ---- database access ------------------------------------------------------------------------------------------------------------------------------
def _damage_rows(cur):
    flags = ",".join(["%s"] * len(DAMAGE_FLAGS))
    cur.execute(f"""SELECT t.transaction_id, t.tool_id, t.quantity, t.condition_at_return, tl.price, t.project_id, p.name AS project_name, p.client,
                           t.user_id, u.full_name AS worker,
                           EXISTS (SELECT 1 FROM tool_issues ti WHERE ti.transaction_id = t.transaction_id AND ti.condition_flag IN ({flags})) AS ticketed
                    FROM `transaction` t JOIN tool tl ON tl.tool_id = t.tool_id JOIN `user` u ON u.user_id = t.user_id
                    LEFT JOIN projects p ON p.project_id = t.project_id
                    WHERE t.borrow_date >= NOW() - INTERVAL %s DAY""", (*DAMAGE_FLAGS, DAMAGE_WINDOW_DAYS))
    rows = cur.fetchall()
    for r in rows:
        r["bad"] = bool(r["ticketed"]) or r["condition_at_return"] in BAD_CONDITIONS
    return rows


def _overdue_rows(cur):
    cur.execute("""SELECT t.transaction_id, t.project_id, p.name AS project_name, t.user_id, u.full_name AS worker, tl.name AS tool_name, tl.price,
                          t.quantity, DATEDIFF(CURDATE(), COALESCE(t.due_date, p.end_date)) AS days_overdue
                   FROM `transaction` t JOIN tool tl ON tl.tool_id = t.tool_id JOIN `user` u ON u.user_id = t.user_id
                   LEFT JOIN projects p ON p.project_id = t.project_id
                   WHERE t.status = 'Active' AND COALESCE(t.due_date, p.end_date) < CURDATE()""")
    return cur.fetchall()


@require_role("Admin")
def analyse(actor):
    """All findings and the ranked recommendations. {"damage", "bottlenecks", "clusters", "recommendations"}."""
    from services import report_service
    abc = report_service.abc_analysis(actor, None, None)["rows"]
    with db.read() as cur:
        damage = damage_outliers(_damage_rows(cur))
        cur.execute("SELECT t.tool_id, t.name, t.price, IFNULL(i.quantity_total, 0) AS stock FROM tool t LEFT JOIN inventory i ON i.tool_id = t.tool_id")
        tools = {r["tool_id"]: r for r in cur.fetchall()}
        cur.execute("SELECT tool_id, reason FROM issuance_attempts WHERE tool_id IS NOT NULL AND attempted_at >= NOW() - INTERVAL %s DAY", (WINDOW_DAYS,))
        attempts = cur.fetchall()
        clusters = overdue_clusters(_overdue_rows(cur))
    bottlenecks = blocked_demand(abc, tools, attempts)
    return {"damage": damage, "bottlenecks": bottlenecks, "clusters": clusters, "recommendations": recommendations(damage, bottlenecks, clusters)}


@require_role("Admin")
def top_recommendations(actor, n=5):
    return analyse.__wrapped__(actor)["recommendations"][:n]


@require_role("Admin")
def blocked_attempts_summary(actor):
    """How many refusals of each kind in the last 30 days (for the report page)."""
    with db.read() as cur:
        cur.execute("SELECT reason, COUNT(*) AS n FROM issuance_attempts WHERE attempted_at >= NOW() - INTERVAL %s DAY GROUP BY reason", (WINDOW_DAYS,))
        got = {r["reason"]: r["n"] for r in cur.fetchall()}
    return {r: got.get(r, 0) for r in REASONS}


def pdf_sections(result, counts):
    """[PANEL-AWE] (notes, sections) for the printed report: recommendations, the numbers behind them, then each raw finding table.
    Built from the same ``analyse`` result the screen shows."""
    recs = result["recommendations"]
    sections = [("Recommendations (largest estimated peso impact first)", ["#", "Recommendation", "Peso impact"],
                 [[str(i), r["text"], peso(r["peso_impact"])] for i, r in enumerate(recs, start=1)] or [["-", "Nothing unusual was found.", "-"]], [1, 9, 2])]
    if recs:
        sections.append(("The numbers behind each recommendation", ["#", "Evidence"],
                         [[str(i), line] for i, r in enumerate(recs, start=1) for line in r["evidence"]], [1, 11]))
    sections.append(("Damage and loss outliers (above Q3 + 1.5 x IQR of their group)",
                     ["Group", "Name", "Issued", "Damaged/lost", "Rate", "Peer median", "Upper limit", "Value"],
                     [[f["dimension"], str(f["label"]), _q(f["issued"]), _q(f["bad"]), f"{f['rate'] * 100:.1f}%", f"{f['peer_median'] * 100:.1f}%",
                       f"{f['fence'] * 100:.1f}%", peso(f["value"])] for f in result["damage"]] or [["-", "none", "", "", "", "", "", ""]]))
    sections.append((f"Category A bottlenecks (blocked attempts, last {WINDOW_DAYS} days, above stock)", ["Tool", "Blocked", "Stock", "Shortfall", "Unit price", "Cost"],
                     [[f["name"], str(f["blocked"]), _q(f["stock"]), str(f["shortfall"]), peso(f["price"]), peso(f["value"])] for f in result["bottlenecks"]]
                     or [["none", "", "", "", "", ""]]))
    sections.append(("Overdue clusters (3 or more overdue issuances)", ["Group", "Name", "Overdue", "Units", "Value at risk", "Longest (days)"],
                     [[f["dimension"], str(f["label"]), str(f["count"]), _q(f["units"]), peso(f["value"]), str(f["max_days"])] for f in result["clusters"]]
                     or [["none", "", "", "", "", ""]]))
    notes = [f"Refused issuances in the last {WINDOW_DAYS} days: {counts['out_of_stock']} out of stock, {counts['over_quota']} over the approved quantity, "
             f"{counts['past_end']} after the project ended."]
    return notes, sections
