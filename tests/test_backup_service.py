"""Backup / restore hardening, against a throwaway database and the real mysqldump / mysql programs."""
import os
import subprocess
from pathlib import Path

import pytest

from services import backup_service as bs
from services.errors import PermissionDenied

pytestmark = pytest.mark.db

needs_mysql = pytest.mark.skipif(not (bs._find_mysqldump() and bs._find_mysql()), reason="mysql client programs not installed")


def run(db, sql, params=()):
    with db.transaction() as cur:
        cur.execute(sql, params)
        return cur.lastrowid


def rows(db, sql, params=()):
    with db.read() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


@pytest.fixture
def admin(svc):
    uid = run(svc, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('ADM-2026-001','Admin One','Admin','Active')")
    return {"user_id": uid}


@pytest.fixture(autouse=True)
def safety(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, "SAFETY_DIR", tmp_path / "safety")


class Proc:
    def __init__(self, code=0, err=b""):
        self.returncode, self.stderr, self.stdout = code, err, b""


# ---- backup -------------------------------------------------------------------------------------------------------------------
@needs_mysql
def test_backup_writes_a_verified_file_and_records_the_checksum(svc, admin, tmp_path):
    out = bs.create_backup(admin, str(tmp_path), "before update", "note")
    p = Path(out["path"])
    assert p.exists() and not list(tmp_path.glob("*.part")) and bs.TRAILER in p.read_text(encoding="utf-8")
    assert p.name.startswith("before_update_")
    log = rows(svc, "SELECT status, type, sha256, file_size FROM backup_logs")[0]
    assert (log["status"], log["type"]) == ("Success", "Backup") and log["sha256"] == bs._sha256_of(p) == out["sha256"]


@needs_mysql
def test_password_never_appears_on_the_command_line_and_temp_file_is_deleted(svc, admin, tmp_path):
    seen = {}
    real = subprocess.run

    def spy(cmd, **kw):
        seen["cmd"] = list(cmd)
        cnf = [a.split("=", 1)[1] for a in cmd if a.startswith("--defaults-extra-file=")][0]
        seen["cnf"] = cnf
        seen["existed"] = os.path.exists(cnf)
        return real(cmd, **kw)
    bs.create_backup(admin, str(tmp_path), run=spy)
    pw = svc.config.get("password")
    assert seen["existed"] and not os.path.exists(seen["cnf"])
    if pw:
        assert not any(pw in a for a in seen["cmd"])
    assert not any(a.startswith("--password") for a in seen["cmd"])


def test_any_nonzero_exit_is_a_failure_even_if_a_big_file_was_written(svc, admin, tmp_path):
    def fake(cmd, **kw):
        part = [a.split("=", 1)[1] for a in cmd if a.startswith("--result-file=")][0]
        Path(part).write_text("-- MySQL dump\n" + "x" * 5000 + "\n-- Dump completed\n")        # looks fine, but the exit code says no
        return Proc(2, b"mysqldump: Got error 1045")
    with pytest.raises(bs.BackupError):
        bs.create_backup(admin, str(tmp_path), exe="mysqldump", run=fake)
    assert not list(tmp_path.glob("*.sql")) and not list(tmp_path.glob("*.part"))
    assert rows(svc, "SELECT status FROM backup_logs")[0]["status"] == "Failed"


def test_file_without_trailer_is_never_renamed(svc, admin, tmp_path):
    def fake(cmd, **kw):
        part = [a.split("=", 1)[1] for a in cmd if a.startswith("--result-file=")][0]
        Path(part).write_text("-- MySQL dump\n-- Database: x\n" + "x" * 5000)                  # cut short
        return Proc(0)
    with pytest.raises(bs.BackupError, match="incomplete"):
        bs.create_backup(admin, str(tmp_path), exe="mysqldump", run=fake)
    assert not list(tmp_path.iterdir())


def test_not_enough_disk_space_is_refused_before_dumping(svc, admin, tmp_path, monkeypatch):
    class U:
        free = 1000
    monkeypatch.setattr(bs.shutil, "disk_usage", lambda p: U)
    called = []
    with pytest.raises(bs.BackupError, match="free disk space"):
        bs.create_backup(admin, str(tmp_path), exe="mysqldump", run=lambda *a, **k: called.append(1))
    assert not called


def test_only_admin_may_back_up_or_restore(svc, tmp_path):
    uid = run(svc, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('STF-2026-001','S','Staff','Active')")
    with pytest.raises(PermissionDenied):
        bs.create_backup({"user_id": uid}, str(tmp_path))
    with pytest.raises(PermissionDenied):
        bs.restore_backup({"user_id": uid}, str(tmp_path / "x.sql"))


# ---- validating dumps ----------------------------------------------------------------------------------------------------------
GOOD = "-- MySQL dump 10.13  Distrib 8.0\n--\n-- Host: 127.0.0.1    Database: {db}\n" + "-- filler\n" * 80 + "\n-- Dump completed on 2026-01-01\n"


def test_validate_dump_catches_bad_files(tmp_path):
    f = tmp_path / "a.sql"
    f.write_text(GOOD.format(db="d1"))
    assert bs._validate_dump(f, "d1")
    with pytest.raises(bs.BackupError, match="different database"):
        bs._validate_dump(f, "other")
    f.write_text(GOOD.format(db="d1").replace("-- Dump completed", "-- Dump aborted"))
    with pytest.raises(bs.BackupError, match="incomplete"):
        bs._validate_dump(f, "d1")
    f.write_text("hello")
    with pytest.raises(bs.BackupError, match="too small"):
        bs._validate_dump(f, "d1")
    f.write_text("SELECT 1;\n" * 200)
    with pytest.raises(bs.BackupError, match="not a database backup"):
        bs._validate_dump(f, "d1")
    f.write_text(GOOD.format(db="d1"))
    with pytest.raises(bs.BackupError, match="checksum"):
        bs._validate_dump(f, "d1", expected_sha256="0" * 64)
    with pytest.raises(bs.BackupError, match="does not exist"):
        bs._validate_dump(tmp_path / "missing.sql", "d1")


# ---- restore ------------------------------------------------------------------------------------------------------------------
@needs_mysql
def test_restore_round_trip_keeps_history_and_makes_a_safety_backup(svc, admin, tmp_path):
    run(svc, "INSERT INTO tool (name, item_type, unit_of_measure) VALUES ('hammer','Equipment','pcs')")
    out = bs.create_backup(admin, str(tmp_path), "base")
    run(svc, "INSERT INTO tool (name, item_type, unit_of_measure) VALUES ('later tool','Equipment','pcs')")
    res = bs.restore_backup(admin, out["path"], "rollback test", expected_sha256=out["sha256"])
    assert [r["name"] for r in rows(svc, "SELECT name FROM tool ORDER BY name")] == ["hammer"]            # the later tool is gone
    assert Path(res["safety_backup"]).exists() and bs.TRAILER in Path(res["safety_backup"]).read_text(encoding="utf-8")
    types = [(r["type"], r["status"]) for r in rows(svc, "SELECT type, status FROM backup_logs ORDER BY backup_id")]
    assert ("Backup", "Success") in types and ("Restore", "Success") in types and len(types) == 3         # base + safety + restore
    # and the safety copy really holds the state from just before the restore
    bs.restore_backup(admin, res["safety_backup"])
    assert sorted(r["name"] for r in rows(svc, "SELECT name FROM tool")) == ["hammer", "later tool"]


@needs_mysql
def test_truncated_or_corrupt_dump_is_refused_and_nothing_changes(svc, admin, tmp_path):
    run(svc, "INSERT INTO tool (name, item_type, unit_of_measure) VALUES ('hammer','Equipment','pcs')")
    out = bs.create_backup(admin, str(tmp_path), "base")
    text = Path(out["path"]).read_text(encoding="utf-8")
    cut = tmp_path / "cut.sql"
    cut.write_text(text[: len(text) // 2], encoding="utf-8")
    junk = tmp_path / "junk.sql"
    junk.write_text("DROP DATABASE nothing;\n" * 100, encoding="utf-8")
    run(svc, "INSERT INTO tool (name, item_type, unit_of_measure) VALUES ('keep me','Equipment','pcs')")
    before = len(list((tmp_path / "safety").glob("*"))) if (tmp_path / "safety").exists() else 0
    for bad in (cut, junk):
        with pytest.raises(bs.BackupError):
            bs.restore_backup(admin, str(bad))
    assert sorted(r["name"] for r in rows(svc, "SELECT name FROM tool")) == ["hammer", "keep me"]
    after = len(list((tmp_path / "safety").glob("*"))) if (tmp_path / "safety").exists() else 0
    assert after == before                                                                                 # refused BEFORE any safety backup


@needs_mysql
def test_failed_mysql_load_says_where_the_safety_backup_is_and_keeps_history(svc, admin, tmp_path):
    out = bs.create_backup(admin, str(tmp_path), "base")
    real = subprocess.run

    def fail_on_load(cmd, **kw):
        if "stdin" in kw:
            return Proc(1, b"ERROR 1064 syntax")
        return real(cmd, **kw)
    with pytest.raises(bs.BackupError, match="safety backup"):
        bs.restore_backup(admin, out["path"], run=fail_on_load)
    assert len(rows(svc, "SELECT 1 FROM backup_logs")) >= 2                                               # history still there


@needs_mysql
def test_restore_is_stopped_if_the_safety_backup_fails(svc, admin, tmp_path):
    out = bs.create_backup(admin, str(tmp_path), "base")
    with pytest.raises(bs.BackupError, match="NOT started"):
        bs.restore_backup(admin, out["path"], run=lambda *a, **k: Proc(2, b"boom"))


@needs_mysql
def test_history_paging(svc, admin, tmp_path):
    for i in range(3):
        run(svc, "INSERT INTO backup_logs (filename, status, type) VALUES (%s,'Success','Backup')", (f"f{i}.sql",))
    page, total = bs.history_page(admin, limit=2, offset=0)
    assert total == 3 and len(page) == 2
    page2, _ = bs.history_page(admin, limit=2, offset=2)
    assert len(page2) == 1
