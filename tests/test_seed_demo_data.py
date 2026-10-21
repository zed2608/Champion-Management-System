"""The demo-data seeder: refuses the real database, builds a throwaway database, is re-runnable, and its data makes every insight screen show something.
The seeder runs as a separate program (as it will for you); the checks then read the database through the real services."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "seed_demo_data.py"


def run_seeder(database, extra_env=None, args=()):
    env = dict(os.environ, DB_HOST=os.getenv("TEST_DB_HOST", "localhost"), DB_USER=os.environ.get("TEST_DB_USER", "x"),
               DB_PASS=os.getenv("TEST_DB_PASS", ""), DB_PORT="3306", DEMO_ADMIN_PASSWORD="Demo-Admin1!", DEMO_STAFF_PASSWORD="Demo-Staff1!",
               CHAMPION_LOG_DIR=str(ROOT / "logs"))
    env.update(extra_env or {})
    return subprocess.run([sys.executable, str(SCRIPT), "--database", database, "--env-file", "NONE", *args],
                          env=env, capture_output=True, text=True, timeout=300)


def test_the_real_database_and_odd_names_are_refused_before_anything_connects():
    for bad in ("champion_db", "CHAMPION_DB", "defaultdb", "champion_demo; DROP DATABASE x", "production"):
        r = run_seeder(bad, {"DB_HOST": "127.0.0.1", "DB_USER": "nobody"})
        assert r.returncode != 0 and "Refusing" in (r.stderr + r.stdout), (bad, r.stderr[-300:])


def test_an_aiven_host_is_refused():
    r = run_seeder("champion_demo", {"DB_HOST": "mysql-1.b.aivencloud.com"})
    assert r.returncode != 0 and "Aiven" in (r.stderr + r.stdout)


def test_no_password_is_ever_printed_or_hard_coded():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "Demo-Admin1!" not in text and "password=\"" not in text
    assert "getpass" in text and "DEMO_ADMIN_PASSWORD" in text


@pytest.mark.db
def test_seeded_database_is_complete_rerunnable_and_makes_every_insight_show_something(admin_conn, monkeypatch):
    import mysql.connector
    from conftest import _cfg, wire_services
    from db.pool import Database
    name = "test_demo_seed"
    try:
        r = run_seeder(name)
        assert r.returncode == 0, r.stderr[-1500:] + r.stdout[-500:]
        assert "Demo-Admin1!" not in r.stdout + r.stderr
        r2 = run_seeder(name)                                          # drops and re-creates only this database
        assert r2.returncode == 0, r2.stderr[-1500:]

        d = Database(_cfg(name), pool_name="demoseed")
        wire_services(monkeypatch, d)
        try:
            def one(sql, p=()):
                with d.read() as cur:
                    cur.execute(sql, p)
                    return cur.fetchone()
            assert one("SELECT SUM(role='Admin') a, SUM(role='Staff') s, SUM(role='Worker') w FROM `user`") == {"a": 1, "s": 1, "w": 6}
            assert 35 <= one("SELECT COUNT(*) n FROM tool")["n"] <= 45
            assert one("SELECT COUNT(DISTINCT category) n FROM tool")["n"] >= 5
            assert one("SELECT COUNT(*) n FROM inventory WHERE quantity_total = 1 AND quantity_available <= 1 AND quantity_in_maintenance = 0")["n"] >= 1
            assert one("SELECT COUNT(*) n FROM inventory WHERE quantity_total <> FLOOR(quantity_total)")["n"] >= 1       # fractional consumable
            assert one("SELECT SUM(tag_id IS NULL) u, SUM(tag_id IS NOT NULL) t FROM tool")["u"] >= 1
            assert {r for r in (one("SELECT GROUP_CONCAT(status) s FROM projects")["s"].split(","))} == {"Approved", "Ongoing", "Completed"}
            # the stock identity holds for every tool: available = total - deployed - in maintenance
            bad = one("""SELECT COUNT(*) n FROM inventory i
                         LEFT JOIN (SELECT tool_id, SUM(quantity) q FROM `transaction` WHERE status='Active' GROUP BY tool_id) a ON a.tool_id=i.tool_id
                         WHERE i.quantity_available <> i.quantity_total - COALESCE(a.q,0) - i.quantity_in_maintenance""")["n"]
            assert bad == 0
            assert one("SELECT COUNT(*) n FROM `transaction` WHERE status='Active' AND due_date < CURDATE()")["n"] >= 3         # overdue items
            assert one("SELECT COUNT(*) n FROM issuance_attempts")["n"] >= 5
            assert one("SELECT SUM(condition_flag='Lost') l, SUM(condition_flag='Damaged') d FROM tool_issues")["l"] >= 1

            admin = {"user_id": one("SELECT user_id FROM `user` WHERE role='Admin'")["user_id"], "role": "Admin"}
            from services import anomaly, audit_chain, report_service, savings, wear_forecast
            assert audit_chain.verify_chain(admin)["intact"] is True
            assert any(r["flags"] for r in wear_forecast.forecast(admin))
            found = anomaly.analyse(admin)
            assert found["recommendations"] and found["bottlenecks"] and found["clusters"]
            assert any(r["category"] == "A" for r in report_service.abc_analysis(admin, None, None)["rows"])
            assert len(report_service.overdue_report(admin, None, None)) >= 3
            assert savings.monthly_savings(admin)["months"]
        finally:
            d.close()
    finally:
        cur = admin_conn.cursor()
        cur.execute(f"DROP DATABASE IF EXISTS `{name}`")
        cur.close()
