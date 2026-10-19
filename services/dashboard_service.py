"""Read-only data for the home dashboard (Admin and Staff).

[QUANTITIES] Every "how many tools" number is a SUM of ``quantity`` (equipment rows have quantity 1, a consumable is one row with its
exact amount), never a COUNT of rows, so a consumable issued as 2.5 kg counts 2.5, not 1 or 3.
[RBAC] Staff's MySQL account cannot read the audit log. The activity feed therefore reads ``v_activity_feed``, a view that exposes only
project-creation events and no other audit data (db/schema.sql), so the dashboard works for Staff without widening their grants.
"""
from decimal import Decimal

from db import db
from services import validators as v
from services.security import require_role


def _n(x):
    """Whole numbers stay ints; anything fractional is kept exact (to 2 dp) so '2.5 kg' is shown as 2.5."""
    d = Decimal(str(x or 0))
    return int(d) if d == d.to_integral_value() else float(round(d, 2))


def _label(name, qty):
    q = Decimal(str(qty or 1))
    return name if q == 1 else f"{name} x{v.fmt_qty(q)}"


@require_role("Admin", "Staff")
def live_metrics(actor):
    """(metrics, activities, chart_data, deployed_rows, my_issuances) in the shapes the dashboard already renders."""
    with db.read() as cur:
        m = {}
        cur.execute("SELECT COUNT(*) AS n FROM `user` WHERE status = 'Active'")
        m["total_employees"] = int(cur.fetchone()["n"])
        cur.execute("SELECT COUNT(DISTINCT user_id) AS n FROM `transaction` "
                    "WHERE status = 'Active' AND borrow_date >= DATE_SUB(NOW(), INTERVAL 30 DAY)")
        m["active_workforce"] = int(cur.fetchone()["n"])

        cur.execute("""SELECT COALESCE(SUM(i.quantity_available), 0) AS avail, COALESCE(SUM(i.quantity_total), 0) AS total
                       FROM inventory i JOIN tool t ON t.tool_id = i.tool_id WHERE t.is_archived = 0""")
        r = cur.fetchone()
        cur.execute("SELECT COALESCE(SUM(quantity), 0) AS deployed FROM `transaction` WHERE status = 'Active'")
        out = Decimal(str(cur.fetchone()["deployed"]))
        total = Decimal(str(r["total"]))
        m["available_qty"] = _n(r["avail"])
        m["borrowed_qty"] = _n(out)
        m["total_physical"] = _n(total)             # everything the company owns: shelf + deployed + in maintenance
        m["utilization_pct"] = int(out / total * 100) if total > 0 else 0

        cur.execute("SELECT COUNT(*) AS n FROM tool_issues WHERE status = 'Open'")
        m["pending_issues"] = int(cur.fetchone()["n"])
        m["action_items"] = m["pending_issues"]
        cur.execute("""SELECT COUNT(*) AS n FROM projects WHERE status NOT IN ('Completed', 'Cancelled', 'Declined')
                       AND archived_at IS NULL AND end_date < CURDATE()""")
        m["overdue_projects"] = int(cur.fetchone()["n"])
        cur.execute("SELECT COUNT(*) AS n FROM projects WHERE status = 'Pending' AND archived_at IS NULL")
        m["pending_projects"] = m["proj_pending"] = int(cur.fetchone()["n"])
        cur.execute("""SELECT COUNT(*) AS n FROM inventory i JOIN tool t ON t.tool_id = i.tool_id
                       WHERE t.is_archived = 0 AND i.minimum_stock > 0 AND i.quantity_available < i.minimum_stock""")
        m["low_stock"] = int(cur.fetchone()["n"])
        cur.execute("SELECT COUNT(*) AS n FROM projects WHERE status = 'Ongoing' AND archived_at IS NULL")
        m["proj_active"] = int(cur.fetchone()["n"])
        cur.execute("""SELECT COUNT(*) AS n FROM projects WHERE status = 'Completed'
                       AND MONTH(end_date) = MONTH(CURDATE()) AND YEAR(end_date) = YEAR(CURDATE())""")
        m["proj_completed_month"] = int(cur.fetchone()["n"])
        cur.execute("SELECT COUNT(*) AS n FROM `user` WHERE reset_requested = 1")
        m["pwd_resets"] = int(cur.fetchone()["n"])

        # activity feed: one entry per issuance/retrieval batch (same tool, person, moment), quantities summed
        cur.execute("""
            SELECT DATE_FORMAT(raw_date, '%Y-%m-%d %I:%i %p') AS ts, action, item, qty, actor FROM (
                SELECT tr.borrow_date AS raw_date, 'Issued' AS action, t.name AS item, SUM(tr.quantity) AS qty, u.full_name AS actor
                FROM `transaction` tr JOIN tool t ON t.tool_id = tr.tool_id JOIN `user` u ON u.user_id = tr.user_id
                WHERE tr.type = 'Issue' GROUP BY tr.tool_id, tr.user_id, tr.borrow_date
                UNION ALL
                SELECT tr.return_date, 'Retrieved', t.name, SUM(tr.quantity), u.full_name
                FROM `transaction` tr JOIN tool t ON t.tool_id = tr.tool_id JOIN `user` u ON u.user_id = tr.user_id
                WHERE tr.type = 'Retrieval' AND tr.return_date IS NOT NULL GROUP BY tr.tool_id, tr.user_id, tr.return_date
                UNION ALL
                SELECT `timestamp`, 'Project Created', details, 1, actor FROM v_activity_feed
            ) combined ORDER BY raw_date DESC LIMIT 10""")
        activities = [(r["ts"], r["action"], _label(r["item"], r["qty"]) if r["action"] != "Project Created" else r["item"], r["actor"])
                      for r in cur.fetchall()]

        cur.execute("""
            SELECT d.day_label, COALESCE(i.q, 0) AS issued, COALESCE(r.q, 0) AS retrieved FROM (
                SELECT DATE_SUB(CURDATE(), INTERVAL n DAY) AS day_date, DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL n DAY), '%a') AS day_label
                FROM (SELECT 6 n UNION SELECT 5 UNION SELECT 4 UNION SELECT 3 UNION SELECT 2 UNION SELECT 1 UNION SELECT 0) nums) d
            LEFT JOIN (SELECT DATE(borrow_date) AS dd, SUM(quantity) AS q FROM `transaction`
                       WHERE type = 'Issue' AND borrow_date >= DATE_SUB(CURDATE(), INTERVAL 6 DAY) GROUP BY dd) i ON i.dd = d.day_date
            LEFT JOIN (SELECT DATE(return_date) AS dd, SUM(quantity) AS q FROM `transaction`
                       WHERE type = 'Retrieval' AND return_date >= DATE_SUB(CURDATE(), INTERVAL 6 DAY) GROUP BY dd) r ON r.dd = d.day_date
            ORDER BY d.day_date""")
        chart = [(r["day_label"], _n(r["issued"]), _n(r["retrieved"])) for r in cur.fetchall()]

        cur.execute("""SELECT p.name AS project_name, SUM(tr.quantity) AS tool_count FROM `transaction` tr
                       JOIN projects p ON p.project_id = tr.project_id WHERE tr.status = 'Active'
                       GROUP BY p.project_id, p.name ORDER BY tool_count DESC LIMIT 5""")
        deployed = [(r["project_name"], _n(r["tool_count"])) for r in cur.fetchall()]

        cur.execute("""SELECT t.name AS tool_name, SUM(tr.quantity) AS qty, DATE_FORMAT(tr.borrow_date, '%b %d, %Y') AS issued_date,
                              IFNULL(p.name, '—') AS project_name
                       FROM `transaction` tr JOIN tool t ON t.tool_id = tr.tool_id LEFT JOIN projects p ON p.project_id = tr.project_id
                       WHERE tr.user_id = %s AND tr.status = 'Active'
                       GROUP BY t.tool_id, t.name, tr.borrow_date, p.name ORDER BY tr.borrow_date DESC LIMIT 8""", (actor["user_id"],))
        mine = [(_label(r["tool_name"], r["qty"]), r["issued_date"], r["project_name"]) for r in cur.fetchall()]
    return m, activities, chart, deployed, mine


@require_role("Admin")
def admin_insights(actor):
    """[PANEL-AWE] The Admin-only dashboard cards. Each part is computed on its own, so one failing part (say, a missing table on a
    database that has not been upgraded yet) shows its own error and never hides the others. {"backup"|"audit"|"wear"|"recommendations": {"data"|"error"}}."""
    from services import anomaly, audit_chain, backup_service, savings, wear_forecast
    from services.errors import friendly_message
    parts = (("backup", lambda: backup_service.last_backup_status(actor)),
             ("audit", lambda: audit_chain.quick_status(actor)),
             ("wear", lambda: wear_forecast.forecast(actor, limit=5)),
             ("recommendations", lambda: anomaly.top_recommendations(actor, 5)),
             ("savings", lambda: savings.monthly_savings(actor)))
    out = {}
    for key, fn in parts:
        try:
            out[key] = {"data": fn()}
        except Exception as e:
            out[key] = {"error": friendly_message(e)}
    return out
