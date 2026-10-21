"""One story, start to finish, with the real mysqldump / mysql programs and throwaway databases:
a backup made seconds earlier is restored; then a truncated file is refused; then a file from a different database is refused.
After every step the data must be exactly what the story says."""
from pathlib import Path

import pytest

from services import backup_service as bs

pytestmark = pytest.mark.db

needs_mysql = pytest.mark.skipif(not (bs._find_mysqldump() and bs._find_mysql()), reason="mysql client programs not installed")


def run(db, sql, params=()):
    with db.transaction() as cur:
        cur.execute(sql, params)
        return cur.lastrowid


def names(db):
    with db.read() as cur:
        cur.execute("SELECT name FROM tool ORDER BY name")
        return [r["name"] for r in cur.fetchall()]


@needs_mysql
def test_restore_story_good_file_then_truncated_then_wrong_database(svc, make_db, tmp_path, monkeypatch):
    monkeypatch.setattr(bs, "SAFETY_DIR", tmp_path / "safety")
    admin = {"user_id": run(svc, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('ADM-2026-001','Admin One','Admin','Active')")}
    run(svc, "INSERT INTO tool (name, item_type) VALUES ('hammer','Equipment')")

    # 1. back up, change the data, restore the backup made seconds ago
    out = bs.create_backup(admin, str(tmp_path), "seconds-ago")
    run(svc, "INSERT INTO tool (name, item_type) VALUES ('added after the backup','Equipment')")
    assert names(svc) == ["added after the backup", "hammer"]
    res = bs.restore_backup(admin, out["path"], "round trip", expected_sha256=out["sha256"])
    assert names(svc) == ["hammer"]
    assert Path(res["safety_backup"]).exists()

    # 2. a cut-short copy of the same backup is refused and the data is untouched
    run(svc, "INSERT INTO tool (name, item_type) VALUES ('keep me','Equipment')")
    text = Path(out["path"]).read_text(encoding="utf-8")
    cut = tmp_path / "cut.sql"
    cut.write_text(text[: int(len(text) * 0.6)], encoding="utf-8")
    with pytest.raises(bs.BackupError, match="incomplete"):
        bs.restore_backup(admin, str(cut))
    assert names(svc) == ["hammer", "keep me"]

    # 3. a perfectly good backup of a DIFFERENT database is refused and the data is untouched
    other = make_db("_other")
    with other.transaction() as cur:
        cur.execute("CREATE TABLE tool (tool_id INT PRIMARY KEY AUTO_INCREMENT, name VARCHAR(100))")
        cur.execute("INSERT INTO tool (name) VALUES ('from another database')")
        for i in range(60):                                     # make the dump comfortably bigger than the 512-byte minimum
            cur.execute("INSERT INTO tool (name) VALUES (%s)", (f"filler {i} " + "x" * 40,))
    foreign = tmp_path / "foreign.sql"
    bs._dump_to_file(foreign, cfg={**bs._cfg(), "database": other.config["database"]})
    assert foreign.stat().st_size > 512
    with pytest.raises(bs.BackupError, match="different database"):
        bs.restore_backup(admin, str(foreign))
    assert names(svc) == ["hammer", "keep me"]
