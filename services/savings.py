"""[PANEL-AWE] Savings KPI: how much tool value is being lost each month compared with the cost-benefit analysis baseline of P10,000 per month.

"Lost" means units written up as Lost or Stolen on a maintenance ticket (returns marked Lost create such a ticket automatically), valued at
``tool.price`` x units, in the month the ticket was raised. A month under the baseline is a saving (baseline - actual); a month over it is an overrun.
"""
from datetime import date

from db import db
from services.security import require_role

BASELINE_PER_MONTH = 10_000.0
LOSS_FLAGS = ("Lost", "Stolen")


def month_key(d):
    return f"{d.year:04d}-{d.month:02d}"


def last_months(today, n):
    """['2026-01', ..., '2026-06'] ending with the month of ``today`` (oldest first)."""
    y, m, out = today.year, today.month, []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out[::-1]


def kpi(monthly_loss, today, months=6, baseline=BASELINE_PER_MONTH):
    """monthly_loss: {'YYYY-MM': lost value}. Returns {"months": [{month, lost, baseline, saved}], "this_month", "average_saved", "total_saved"}.
    ``saved`` is negative when the month went over the baseline."""
    rows = []
    for key in last_months(today, months):
        lost = float(monthly_loss.get(key, 0.0))
        rows.append({"month": key, "lost": round(lost, 2), "baseline": baseline, "saved": round(baseline - lost, 2)})
    total = round(sum(r["saved"] for r in rows), 2)
    return {"months": rows, "this_month": rows[-1], "average_saved": round(total / len(rows), 2), "total_saved": total, "baseline": baseline}


def describe(k):
    """One plain sentence with the numbers."""
    m = k["this_month"]
    if m["saved"] >= 0:
        head = f"This month ({m['month']}): P{m['lost']:,.2f} of tools lost against the P{m['baseline']:,.0f} baseline, a saving of P{m['saved']:,.2f}."
    else:
        head = f"This month ({m['month']}): P{m['lost']:,.2f} of tools lost, P{-m['saved']:,.2f} OVER the P{m['baseline']:,.0f} baseline."
    return head + f" Last {len(k['months'])} months: {'saved' if k['total_saved'] >= 0 else 'over by'} P{abs(k['total_saved']):,.2f} in total."


@require_role("Admin")
def monthly_savings(actor, months=6, baseline=BASELINE_PER_MONTH):
    with db.read() as cur:
        cur.execute("SELECT CURDATE() AS today")
        today = cur.fetchone()["today"]
        flags = ",".join(["%s"] * len(LOSS_FLAGS))
        cur.execute(f"SELECT CONCAT(YEAR(ti.flagged_at), '-', LPAD(MONTH(ti.flagged_at), 2, '0')) AS ym, SUM(ti.quantity * IFNULL(t.price, 0)) AS lost "
                    f"FROM tool_issues ti JOIN tool t ON t.tool_id = ti.tool_id WHERE ti.condition_flag IN ({flags}) "
                    f"AND ti.flagged_at >= DATE_SUB(DATE_SUB(CURDATE(), INTERVAL DAYOFMONTH(CURDATE()) - 1 DAY), INTERVAL %s MONTH) GROUP BY ym",
                    (*LOSS_FLAGS, max(1, int(months)) - 1))
        monthly = {r["ym"]: float(r["lost"] or 0) for r in cur.fetchall()}
    return kpi(monthly, today, max(1, int(months)), baseline)
