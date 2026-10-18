"""[RBAC] MySQL itself refuses what the Staff account must not do, even if application code is tampered with."""
import mysql.connector
import pytest

from db import apply_grants

pytestmark = pytest.mark.db

STAFF, ADMIN = "test_champ_staff", "test_champ_admin"
STAFF_PW, ADMIN_PW = "Staff-pass-1234", "Admin-pass-1234"
DENIED = {1142, 1143, 1044, 1045, 1370, 1227}   # table / column / database / routine / missing-privilege denied


@pytest.fixture
def accounts(fresh_db, admin_conn):
    d = fresh_db
    with d.transaction() as cur:
        cur.execute("INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('STF-2026-001','S','Staff','Active'), ('WKR-2026-001','W','Worker','Active')")
        cur.execute("INSERT INTO tool (name, tag_id) VALUES ('Caliper','CAL-001')")
        cur.execute("INSERT INTO inventory (tool_id, quantity_total, quantity_available) VALUES (1, 10, 10)")
        cur.execute("INSERT INTO projects (name, start_date, end_date, status) VALUES ('P', CURDATE() - INTERVAL 1 DAY, CURDATE() + INTERVAL 30 DAY, 'Approved')")
    apply_grants.apply(d, STAFF_PW, ADMIN_PW, staff_user=STAFF, admin_user=ADMIN, host="%")
    cfg = d.config

    def connect(user, pw):
        c = mysql.connector.connect(host=cfg["host"], port=cfg["port"], user=user, password=pw,
                                    database=cfg["database"], autocommit=True)
        return c

    yield connect
    cur = admin_conn.cursor()
    for u in (STAFF, ADMIN):
        cur.execute(f"DROP USER IF EXISTS '{u}'@'%'")
    cur.close()


def denied(conn, sql, params=()):
    cur = conn.cursor()
    with pytest.raises(mysql.connector.Error) as e:
        cur.execute(sql, params)
        cur.fetchall()
    assert e.value.errno in DENIED, f"{sql!r} failed with {e.value.errno}: {e.value}"


def allowed(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    try:
        cur.fetchall()
    except mysql.connector.Error:
        pass
    cur.close()


def test_staff_can_do_the_daily_work(accounts):
    s = accounts(STAFF, STAFF_PW)
    allowed(s, "SELECT * FROM tool")
    allowed(s, "SELECT * FROM `transaction`")
    allowed(s, "INSERT INTO `transaction` (tool_id, user_id, project_id, type, status, quantity) VALUES (1, 2, 1, 'Issue', 'Active', 1)")
    allowed(s, "UPDATE inventory SET quantity_available = quantity_available - 1 WHERE tool_id = 1")
    allowed(s, "UPDATE `transaction` SET status = 'Returned', type = 'Retrieval' WHERE transaction_id = 1")
    allowed(s, "UPDATE tool SET `condition` = 'Damaged' WHERE tool_id = 1")
    allowed(s, "UPDATE tool SET tag_id = 'CAL-002' WHERE tool_id = 1")                    # tag printing
    allowed(s, "UPDATE projects SET status = 'Ongoing' WHERE project_id = 1")             # first issuance
    allowed(s, "INSERT INTO tool_issues (tool_id, condition_flag) VALUES (1, 'Damaged')")
    allowed(s, "INSERT INTO help_tickets (user_id, subject, message) VALUES (1, 's', 'm')")
    allowed(s, "UPDATE `user` SET full_name = 'Stacy', failed_attempts = 1 WHERE employee_id = 'STF-2026-001'")   # profile + lockout bookkeeping
    allowed(s, "INSERT INTO system_logs (user_id, action_type, module, details) VALUES (1, 'Viewed', 'X', 'y')")


def test_staff_cannot_escalate_or_destroy(accounts):
    s = accounts(STAFF, STAFF_PW)
    denied(s, "UPDATE `user` SET role = 'Admin' WHERE employee_id = 'STF-2026-001'")           # no self-promotion
    denied(s, "UPDATE `user` SET employee_id = 'ADM-2026-999' WHERE employee_id = 'STF-2026-001'")
    denied(s, "INSERT INTO `user` (employee_id, full_name, role) VALUES ('ADM-2026-777', 'X', 'Admin')")
    for table in ("tool", "inventory", "`transaction`", "projects", "`user`", "help_faqs", "project_requirements"):
        denied(s, f"DELETE FROM {table}")                                                       # nothing is ever deleted by Staff
    denied(s, "UPDATE tool SET name = 'renamed' WHERE tool_id = 1")
    denied(s, "UPDATE tool SET price = 0 WHERE tool_id = 1")
    denied(s, "UPDATE inventory SET quantity_total = 999 WHERE tool_id = 1")
    denied(s, "UPDATE projects SET name = 'x', end_date = '2099-01-01' WHERE project_id = 1")   # Project Management is read-only
    denied(s, "INSERT INTO projects (name) VALUES ('draft by staff')")
    denied(s, "INSERT INTO tool (name, tag_id) VALUES ('new', 'NEW-001')")
    denied(s, "SELECT * FROM id_sequences")
    denied(s, "SELECT * FROM backup_logs")


def test_staff_can_only_append_to_the_audit_log(accounts):
    s = accounts(STAFF, STAFF_PW)
    allowed(s, "INSERT INTO system_logs (user_id, action_type, module, details) VALUES (1, 'A', 'B', 'C')")
    denied(s, "SELECT * FROM system_logs")
    denied(s, "UPDATE system_logs SET details = 'tampered'")
    denied(s, "DELETE FROM system_logs")


def test_staff_has_no_ddl(accounts):
    s = accounts(STAFF, STAFF_PW)
    denied(s, "CREATE TABLE evil (id INT)")
    denied(s, "ALTER TABLE tool ADD COLUMN x INT")
    denied(s, "DROP TABLE tool")
    denied(s, "TRUNCATE TABLE `transaction`")
    denied(s, "DROP TRIGGER trg_txn_bi")
    denied(s, "CREATE USER 'evil'@'%' IDENTIFIED BY 'x'")


def test_admin_has_the_application_database_and_nothing_else(accounts):
    a = accounts(ADMIN, ADMIN_PW)
    allowed(a, "DELETE FROM help_faqs")
    allowed(a, "UPDATE `user` SET role = 'Staff' WHERE employee_id = 'WKR-2026-001'")
    allowed(a, "CREATE TABLE scratch_t (id INT)")           # restore needs DDL
    allowed(a, "DROP TABLE scratch_t")
    denied(a, "SELECT * FROM mysql.user")
    denied(a, "CREATE USER 'evil'@'%' IDENTIFIED BY 'x'")
    denied(a, "CREATE DATABASE other_db")


def test_template_rejects_unsafe_input():
    with pytest.raises(ValueError):
        apply_grants.render("db`; DROP", "longenough1", "longenough2")
    with pytest.raises(ValueError):
        apply_grants.render("db", "short", "longenough2")
    stmts = apply_grants.render("db", "p--w;d'x", "longenough2")                # tricky characters survive intact, escaped
    assert any("p--w;d\\'x" in s for s in stmts)
