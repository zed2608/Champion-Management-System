import os
import time

import mysql.connector
import pytest

from db import migrate
from db.migrate import MigrationRefused
from db.pool import Database

pytestmark = pytest.mark.db

EXPECTED_TABLES = {
    "user", "id_sequences", "tool", "inventory", "projects", "project_transitions", "project_requirements",
    "project_workers", "transaction", "tool_issues", "system_logs", "backup_logs", "help_guides", "help_faqs",
    "system_requirements", "help_tickets", "schema_migrations", "schema_meta", "v_activity_feed", "audit_chain_head", "system_logs_archive", "category_service_defaults"}
QUIET = dict(log=lambda *_: None)


def _q(db, sql, params=None):
    with db.read() as cur:
        cur.execute(sql, params or ())
        return cur.fetchall()


def _columns(db):
    rows = _q(db, "SELECT table_name AS t, column_name AS c, data_type AS d FROM information_schema.columns "
                  "WHERE table_schema = DATABASE()")
    return {(r["t"], r["c"], r["d"]) for r in rows}


def _good_backup(path, dbname, size=700):
    path.write_text(f"-- MySQL dump 10.13\n-- Host: localhost    Database: {dbname}\n" + "-- filler\n" * (size // 9)
                    + "\n-- Dump completed on 2026-10-18 10:00:00\n", encoding="utf-8")
    return path


# ---- fresh install ---------------------------------------------------------------------------------------------
def test_fresh_install_creates_everything_and_rerun_is_a_noop(make_db):
    d = make_db()
    report = migrate.run(d, require_backup=False, **QUIET)
    assert {n for n, _ in report} >= {"baseline_tables", "triggers"}
    assert {r["t"] for r in _q(d, "SELECT table_name AS t FROM information_schema.tables WHERE table_schema = DATABASE()")} == EXPECTED_TABLES
    assert len(_q(d, "SELECT 1 FROM information_schema.triggers WHERE trigger_schema = DATABASE()")) == 14
    assert migrate.run(d, require_backup=False, **QUIET) == []          # nothing pending: nothing touched
    assert migrate.check_schema_current(d) == (True, "")
    assert len(_q(d, "SELECT * FROM project_transitions")) == len(migrate.TRANSITIONS)


def test_check_schema_current_detects_unmigrated_database(make_db):
    ok, msg = migrate.check_schema_current(make_db())
    assert ok is False and "migrate" in msg


# ---- safety rules ----------------------------------------------------------------------------------------------
def test_refuses_without_backup_and_changes_nothing(legacy_db):
    before = _columns(legacy_db)
    with pytest.raises(MigrationRefused, match="backup"):
        migrate.run(legacy_db, **QUIET)
    assert _columns(legacy_db) == before


def test_dry_run_changes_nothing_and_needs_no_backup(legacy_db):
    before = _columns(legacy_db)
    lines = []
    migrate.run(legacy_db, dry_run=True, log=lines.append)
    assert any("would apply" in l for l in lines)
    assert _columns(legacy_db) == before


def test_never_touches_aiven():
    d = Database({"host": "mysql-36ba029b-x.b.aivencloud.com", "port": 23597, "user": "u", "password": "p",
                  "database": "defaultdb", "pool_size": 1, "connection_timeout": 1, "pool_wait": 0.1}, "aiven_t")
    with pytest.raises(MigrationRefused, match="Aiven"):
        migrate.run(d, require_backup=False, **QUIET)
    with pytest.raises(MigrationRefused, match="Aiven"):
        migrate.run(d, dry_run=True, **QUIET)


def test_require_backup_false_only_for_test_databases(make_db):
    d = make_db()
    d.config["database"] = "champion_db"          # pretend it is a real database name
    with pytest.raises(MigrationRefused, match="test"):
        migrate.run(d, require_backup=False, **QUIET)


def test_backup_verification_rules(tmp_path):
    good = _good_backup(tmp_path / "ok.sql", "test_champion")
    migrate.verify_backup(good, "test_champion", 60)                                   # accepted
    with pytest.raises(MigrationRefused, match="missing"):
        migrate.verify_backup(tmp_path / "nope.sql", "test_champion", 60)
    with pytest.raises(MigrationRefused, match="too small"):
        tiny = tmp_path / "tiny.sql"; tiny.write_text("x"); migrate.verify_backup(tiny, "test_champion", 60)
    trunc = tmp_path / "trunc.sql"                                                      # interrupted dump: no trailer
    trunc.write_text(good.read_text().replace("-- Dump completed on 2026-10-18 10:00:00", ""), encoding="utf-8")
    with pytest.raises(MigrationRefused, match="truncated"):
        migrate.verify_backup(trunc, "test_champion", 60)
    with pytest.raises(MigrationRefused, match="database"):
        migrate.verify_backup(good, "some_other_db", 60)
    old = time.time() - 3 * 3600
    os.utime(good, (old, old))
    with pytest.raises(MigrationRefused, match="old"):
        migrate.verify_backup(good, "test_champion", 60)


def test_stale_backup_blocks_migration(legacy_db, tmp_path):
    f = _good_backup(tmp_path / "b.sql", legacy_db.config["database"])
    old = time.time() - 5 * 3600
    os.utime(f, (old, old))
    with pytest.raises(MigrationRefused, match="old"):
        migrate.run(legacy_db, backup_file=f, **QUIET)


# ---- upgrading a legacy database -----------------------------------------------------------------------------------
@pytest.fixture
def migrated_legacy(legacy_db, tmp_path, monkeypatch):
    if migrate.find_mysqldump() is None:
        pytest.skip("mysqldump not installed")
    monkeypatch.setattr(migrate, "BACKUP_DIR", tmp_path)
    counts_before = {t: _q(legacy_db, f"SELECT COUNT(*) AS n FROM `{t}`")[0]["n"]
                     for t in ("user", "tool", "inventory", "projects", "transaction", "tool_issues", "system_logs")}
    report = migrate.run(legacy_db, make_backup_now=True, **QUIET)       # real mysqldump + verification
    assert any(tmp_path.glob("premigrate_*.sql")), "a verified backup must have been written first"
    return legacy_db, counts_before, dict(report)


def test_legacy_upgrade_keeps_every_row(migrated_legacy):
    d, before, _ = migrated_legacy
    for t, n in before.items():
        now = _q(d, f"SELECT COUNT(*) AS n FROM `{t}`")[0]["n"]
        # nothing is ever lost; the only table the upgrade adds rows to is tool_issues (tickets for tools the old screens flagged)
        assert (now >= n) if t == "tool_issues" else (now == n), t


def test_legacy_requirement_key_renamed_and_status_added(migrated_legacy):
    d, _, _ = migrated_legacy
    cols = {r["c"] for r in _q(d, "SELECT column_name AS c FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'project_requirements'")}
    assert "req_id" in cols and "requirement_id" not in cols and "status" in cols
    assert {r["status"] for r in _q(d, "SELECT status FROM project_requirements")} == {"Pending"}


def test_legacy_inventory_became_exact_decimal_not_null(migrated_legacy):
    d, _, _ = migrated_legacy
    info = {r["c"]: r for r in _q(d, "SELECT column_name AS c, data_type AS dt, is_nullable AS n, numeric_scale AS s FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'inventory'")}
    for c in ("quantity_total", "quantity_available", "minimum_stock"):
        assert (info[c]["dt"], info[c]["n"], info[c]["s"]) == ("decimal", "NO", 2)
    inv = {r["tool_id"]: r for r in _q(d, "SELECT * FROM inventory")}
    assert inv[2]["minimum_stock"] == 0                       # NULL became 0
    assert str(inv[3]["quantity_total"]) == "2.50"            # fractional consumable preserved exactly


def test_legacy_project_workers_use_exact_match(migrated_legacy):
    d, _, report = migrated_legacy
    links = {(r["project_id"], r["employee_id"]) for r in _q(d, "SELECT pw.project_id, u.employee_id FROM project_workers pw JOIN `user` u USING (user_id)")}
    assert links == {(1, "WKR-2026-001"), (1, "WKR-2026-0011"), (2, "WKR-2025-099")}
    assert "1 entries" in report["backfill_data"] or "matched no employee_id" in report["backfill_data"]   # 'Juan Dela Cruz' reported
    # the legacy text is untouched
    assert "Juan Dela Cruz" in _q(d, "SELECT workers_assigned AS w FROM projects WHERE project_id = 1")[0]["w"]


def test_legacy_archive_flag_unified(migrated_legacy):
    d, _, _ = migrated_legacy
    p = _q(d, "SELECT archived_at, status_before_archive AS sba FROM projects WHERE project_id = 2")[0]
    assert p["archived_at"] is not None and p["sba"] == "Completed"
    assert _q(d, "SELECT archived_at FROM projects WHERE project_id = 1")[0]["archived_at"] is None


def test_legacy_transactions_get_date_snapshots(migrated_legacy):
    d, _, _ = migrated_legacy
    rows = _q(d, "SELECT project_start_date AS s, due_date AS e FROM `transaction` WHERE project_id = 1")
    assert rows and all(str(r["s"]) == "2026-01-01" and str(r["e"]) == "2026-12-31" for r in rows)


def test_legacy_issue_status_and_unit_condition_backfill(migrated_legacy):
    d, _, _ = migrated_legacy
    issues = {r["issue_id"]: r for r in _q(d, "SELECT * FROM tool_issues")}
    assert issues[1]["status"] == "Open" and issues[1]["resolved_at"] is None
    assert issues[2]["status"] == "Resolved" and issues[2]["resolved_at"] is not None
    inv = {r["tool_id"]: r for r in _q(d, "SELECT * FROM inventory")}
    # drill: total 5, available 3, 1 deployed, open 'Damaged' issue -> exactly the 1 missing unit is in maintenance
    assert inv[2]["quantity_in_maintenance"] == 1 and inv[2]["quantity_lost"] == 0
    # caliper: total 10, available 7, 3 deployed -> nothing missing, nothing reclassified
    assert inv[1]["quantity_in_maintenance"] == 0
    # old saw: flagged 'Needs Repair' by the old screens with no ticket -> a real ticket is created once, and its 1 missing unit is held
    saw = _q(d, "SELECT * FROM tool_issues WHERE tool_id = 4")
    assert len(saw) == 1 and saw[0]["status"] == "Open" and saw[0]["reported_by"] == "Migration"
    assert inv[4]["quantity_in_maintenance"] == 1


def test_legacy_id_sequences_seeded_from_existing_ids(migrated_legacy):
    d, _, _ = migrated_legacy
    seq = {(r["prefix"], r["yr"]): r["last_seq"] for r in _q(d, "SELECT * FROM id_sequences")}
    assert seq == {("ADM", 2026): 1, ("STF", 2026): 14, ("WKR", 2026): 11, ("WKR", 2025): 99}


def test_legacy_history_can_no_longer_be_cascade_deleted(migrated_legacy):
    d, _, _ = migrated_legacy
    rules = {(r["t"], r["col"]): r["rule"] for r in _q(d, """
        SELECT k.table_name AS t, k.column_name AS col, r.delete_rule AS rule
        FROM information_schema.key_column_usage k JOIN information_schema.referential_constraints r
          ON r.constraint_schema = k.constraint_schema AND r.constraint_name = k.constraint_name
        WHERE k.table_schema = DATABASE() AND k.referenced_table_name IS NOT NULL""")}
    assert rules[("transaction", "tool_id")] in ("RESTRICT", "NO ACTION")
    assert rules[("transaction", "user_id")] in ("RESTRICT", "NO ACTION")
    with pytest.raises(mysql.connector.IntegrityError):
        with d.transaction() as cur:
            cur.execute("DELETE FROM `user` WHERE user_id = 3")          # worker with issued tools


def test_legacy_constraints_only_added_when_data_allows(migrated_legacy):
    d, _, report = migrated_legacy
    checks = {r["n"] for r in _q(d, "SELECT constraint_name AS n FROM information_schema.table_constraints WHERE table_schema = DATABASE() AND constraint_type = 'CHECK'")}
    assert "chk_inv_avail_le_total" in checks and "chk_txn_quantity_pos" in checks
    assert "chk_projects_dates" not in checks                           # project 3 starts after it ends
    assert "chk_projects_dates" in report["check_constraints"] and "violate" in report["check_constraints"]
    assert _q(d, "SELECT COUNT(*) AS n FROM projects")[0]["n"] == 3     # the bad row was reported, not deleted or altered


def test_legacy_upgrade_matches_fresh_install_and_is_rerunnable(migrated_legacy, make_db):
    d, _, _ = migrated_legacy
    fresh = make_db("_parity")
    migrate.run(fresh, require_backup=False, **QUIET)
    assert _columns(d) == _columns(fresh), "an upgraded database must have exactly the shape of a fresh one"
    assert migrate.run(d, require_backup=False, **QUIET) == []
    assert len(_q(d, "SELECT 1 FROM information_schema.triggers WHERE trigger_schema = DATABASE()")) == 14


def test_editing_schema_sql_reaches_already_migrated_databases(fresh_db, monkeypatch, tmp_path):
    """Structural steps re-run when schema.sql's hash changes (one-shot backfills do not)."""
    extra = tmp_path / "schema.sql"
    extra.write_text(migrate.SCHEMA_SQL.read_text(encoding="utf-8").replace(
        "  minimum_stock            DECIMAL(10,2) NOT NULL DEFAULT 0,",
        "  minimum_stock            DECIMAL(10,2) NOT NULL DEFAULT 0,\n  shelf_code               VARCHAR(10) NULL,"), encoding="utf-8")
    monkeypatch.setattr(migrate, "SCHEMA_SQL", extra)
    assert migrate.check_schema_current(fresh_db)[0] is False
    migrate.run(fresh_db, require_backup=False, **QUIET)
    assert ("inventory", "shelf_code", "varchar") in _columns(fresh_db)
    assert migrate.check_schema_current(fresh_db)[0] is True
