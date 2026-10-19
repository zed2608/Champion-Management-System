"""[PANEL-AWE] Printed report sections for the wear forecast and the anomalies come from the SAME functions as the screens."""
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from services import anomaly as an
from services import wear_forecast as wf
from utils.pdf_table import render_pdf


def sample_result():
    rows = []
    n = 0
    for p, bad in enumerate([0, 1, 1, 1, 1, 6], start=1):
        for k in range(10):
            n += 1
            rows.append({"transaction_id": n, "tool_id": 1, "quantity": 1, "price": 100, "project_id": p, "project_name": f"Project {p}", "client": None,
                         "user_id": p, "worker": f"W{p}", "bad": k < bad})
    damage = an.damage_outliers(rows)
    bottle = an.blocked_demand([{"tool_id": 1, "name": "Drill", "category": "A"}], {1: {"name": "Drill", "price": 500, "stock": 7}},
                               [{"tool_id": 1, "reason": "out_of_stock"}] * 9)
    cluster = an.overdue_clusters([{"transaction_id": i, "project_id": 1, "project_name": "Project 1", "user_id": 10 + i, "worker": f"W{i}", "tool_name": "x",
                                    "price": 200, "quantity": 1, "days_overdue": 4 + i} for i in range(3)])
    return {"damage": damage, "bottlenecks": bottle, "clusters": cluster, "recommendations": an.recommendations(damage, bottle, cluster)}


COUNTS = {"out_of_stock": 9, "over_quota": 0, "past_end": 0}


def test_anomaly_pdf_has_every_recommendation_with_its_numbers():
    result = sample_result()
    notes, sections = an.pdf_sections(result, COUNTS)
    headings = [s[0] for s in sections]
    assert headings[0].startswith("Recommendations") and headings[1].startswith("The numbers behind") and len(sections) == 5
    recs = sections[0][2]
    assert len(recs) == len(result["recommendations"]) and recs[0][1].startswith("Procure 2 more Drill") and recs[0][2] == "P1,000.00"
    evidence = sections[1][2]
    assert len(evidence) == sum(len(r["evidence"]) for r in result["recommendations"])
    assert ["1", "blocked attempts (30 days): 9"] in evidence
    assert "9 out of stock" in notes[0]
    damage_rows = sections[2][2]
    assert any(r[0] == "project" and r[1] == "Project 6" and r[3] == "6" and r[4] == "60.0%" for r in damage_rows)
    assert sections[3][2][0][:4] == ["Drill", "9", "7", "2"]
    assert sections[4][2][0][:3] == ["project", "Project 1", "3"]


def test_empty_findings_print_a_plain_none_not_a_blank_page():
    notes, sections = an.pdf_sections({"damage": [], "bottlenecks": [], "clusters": [], "recommendations": []}, COUNTS)
    assert sections[0][2] == [["-", "Nothing unusual was found.", "-"]] and len(sections) == 4
    assert all(s[2] for s in sections)


def test_wear_pdf_table_matches_the_numbers_on_the_screen():
    from datetime import datetime
    now = datetime(2026, 6, 30, 12)
    tools = [{"tool_id": 1, "name": "Drill B", "category": "Drills", "price": 1, "interval": None, "last_serviced_at": None, "units": 1}]
    txns = [{"transaction_id": 1, "tool_id": 1, "quantity": 1, "borrow_date": datetime(2026, 6, 1), "return_date": datetime(2026, 6, 4, 18), "condition_at_return": None}]
    rows = wf.compute_forecast(tools, txns, [], {"*": 500, "Drills": 100}, now)
    labels, body, notes = wf.pdf_table(rows)
    assert labels[2] == "Hours since service" and body == [["Drill B", "Drills", "90", "100", "90%", "3.3 days", "0", "service due soon"]]
    assert notes[0].startswith("1 of 1 tools flagged")


def test_the_pdf_writer_handles_weighted_sections(tmp_path):
    notes, sections = an.pdf_sections(sample_result(), COUNTS)
    out = render_pdf("Anomalies & Recommendations", "Period: current", sections, str(tmp_path / "a.pdf"), notes)
    assert (tmp_path / "a.pdf").stat().st_size > 5000 and out.endswith("a.pdf")
    labels, body, wnotes = wf.pdf_table([])
    render_pdf("Wear", "x", [(None, labels, body or [["none"] + [""] * 7], [4, 3, 2, 2, 2, 3, 2, 4])], str(tmp_path / "w.pdf"), wnotes)
    assert (tmp_path / "w.pdf").exists()


# ---- through the Reports screen's own export function -------------------------------------------------------------------------------------------
def run(db, sql, params=()):
    with db.transaction() as cur:
        cur.execute(sql, params)
        return cur.lastrowid


@pytest.mark.db
def test_reports_export_document_uses_the_same_queries_as_the_screens(svc):
    from views.reports import ReportsView
    admin = {"user_id": run(svc, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('ADM-2026-001','Admin','Admin','Active')")}
    worker = run(svc, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('WKR-2026-001','Wally','Worker','Active')")
    t = run(svc, "INSERT INTO tool (name, category, item_type, unit_of_measure, price) VALUES ('Impact Drill','Drills','Equipment','pcs',500)")
    run(svc, "INSERT INTO inventory (tool_id, quantity_total, quantity_available) VALUES (%s,1,1)", (t,))
    run(svc, "INSERT INTO `transaction` (tool_id, user_id, type, status, quantity, borrow_date, return_date) VALUES (%s,%s,'Retrieval','Returned',1,NOW() - INTERVAL 600 HOUR, NOW() - INTERVAL 10 HOUR)", (t, worker))
    fake = SimpleNamespace(user_info=admin, _export_rows=lambda *a: None)
    title, sections, notes = ReportsView._export_document(fake, "wear", None, None)
    assert title.startswith("Wear") and sections[0][2][0][0] == "Impact Drill" and sections[0][2][0][7] == "overdue for service"
    assert sections[0][2] == wf.pdf_table(wf.forecast(admin))[1]                                       # identical to the screen's rows
    title, sections, notes = ReportsView._export_document(fake, "anomaly", None, None)
    assert title.startswith("Anomalies") and len(sections) >= 4 and "Refused issuances" in notes[0]
