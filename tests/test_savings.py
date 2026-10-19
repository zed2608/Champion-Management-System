"""[PANEL-AWE] Savings KPI: logged lost-tool value per month against the P10,000 monthly baseline of the cost-benefit analysis."""
from datetime import date

import pytest

from services import savings as sv
from services.errors import PermissionDenied


def test_months_run_oldest_first_and_cross_the_new_year():
    assert sv.last_months(date(2026, 2, 10), 4) == ["2025-11", "2025-12", "2026-01", "2026-02"]
    assert sv.last_months(date(2026, 6, 15), 1) == ["2026-06"]


def test_kpi_for_known_months():
    k = sv.kpi({"2026-06": 4000, "2026-05": 12500, "2026-04": 10000, "2025-01": 99999}, date(2026, 6, 15), months=3)
    assert [(r["month"], r["lost"], r["saved"]) for r in k["months"]] == [("2026-04", 10000.0, 0.0), ("2026-05", 12500.0, -2500.0), ("2026-06", 4000.0, 6000.0)]
    assert k["total_saved"] == 3500.0 and k["average_saved"] == pytest.approx(1166.67) and k["this_month"]["saved"] == 6000.0
    assert sv.describe(k) == ("This month (2026-06): P4,000.00 of tools lost against the P10,000 baseline, a saving of P6,000.00. "
                              "Last 3 months: saved P3,500.00 in total.")


def test_a_month_over_the_baseline_is_called_an_overrun_not_a_saving():
    k = sv.kpi({"2026-06": 12500}, date(2026, 6, 15), months=2)
    assert sv.describe(k) == ("This month (2026-06): P12,500.00 of tools lost, P2,500.00 OVER the P10,000 baseline. "
                              "Last 2 months: saved P7,500.00 in total.")
    assert "over by" in sv.describe(sv.kpi({"2026-06": 30000, "2026-05": 30000}, date(2026, 6, 1), months=2))


def run(db, sql, params=()):
    with db.transaction() as cur:
        cur.execute(sql, params)
        return cur.lastrowid


@pytest.mark.db
def test_lost_and_stolen_tickets_are_valued_by_price_and_month(svc):
    admin = {"user_id": run(svc, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('ADM-2026-001','Admin','Admin','Active')")}
    staff = {"user_id": run(svc, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('STF-2026-001','S','Staff','Active')")}
    t = run(svc, "INSERT INTO tool (name, item_type, unit_of_measure, price) VALUES ('Level','Equipment','pcs',1500)")
    run(svc, "INSERT INTO inventory (tool_id, quantity_total, quantity_available) VALUES (%s,10,10)", (t,))
    ins = "INSERT INTO tool_issues (tool_id, condition_flag, quantity, flagged_at) VALUES (%s,%s,%s,{})"
    run(svc, ins.format("NOW()"), (t, "Lost", 2))                                             # 3000 this month
    run(svc, ins.format("NOW()"), (t, "Stolen", 1))                                           # 1500 this month
    run(svc, ins.format("NOW()"), (t, "Damaged", 5))                                          # damaged is not lost: ignored
    run(svc, ins.format("DATE_SUB(NOW(), INTERVAL 1 MONTH)"), (t, "Lost", 8))                 # 12000 last month: over the baseline
    k = sv.monthly_savings(admin, months=2)
    assert k["this_month"]["lost"] == 4500.0 and k["this_month"]["saved"] == 5500.0
    assert k["months"][0]["lost"] == 12000.0 and k["months"][0]["saved"] == -2000.0 and k["total_saved"] == 3500.0
    with pytest.raises(PermissionDenied):
        sv.monthly_savings(staff)
