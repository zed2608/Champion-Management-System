import datetime

import pytest

import seed_admin
from services.validators import verify_password

pytestmark = pytest.mark.db
EMP = f"ADM-{datetime.datetime.now().year}-001"


def row(db):
    with db.read() as cur:
        cur.execute("SELECT * FROM `user` WHERE employee_id = %s", (EMP,))
        return cur.fetchone()


def test_creates_admin_with_strong_password_and_sequence(fresh_db, monkeypatch):
    monkeypatch.setattr(seed_admin, "db", fresh_db)
    monkeypatch.setenv("ADMIN_INITIAL_PASSWORD", "Str0ng!Admin")
    monkeypatch.setenv("ADMIN_EMAIL", "Admin@Example.com")
    assert seed_admin.seed_admin() == 0
    r = row(fresh_db)
    assert r["role"] == "Admin" and r["status"] == "Active" and r["email"] == "admin@example.com"
    assert verify_password("Str0ng!Admin", r["password_hash"]) and not verify_password("admin123", r["password_hash"])
    with fresh_db.read() as cur:
        cur.execute("SELECT last_seq FROM id_sequences WHERE prefix='ADM'")
        assert cur.fetchone()["last_seq"] == 1


def test_rerun_resets_password_and_unlocks(fresh_db, monkeypatch):
    monkeypatch.setattr(seed_admin, "db", fresh_db)
    monkeypatch.setenv("ADMIN_INITIAL_PASSWORD", "Str0ng!Admin")
    seed_admin.seed_admin()
    with fresh_db.transaction() as cur:
        cur.execute("UPDATE `user` SET status='Locked', failed_attempts=3 WHERE employee_id=%s", (EMP,))
    monkeypatch.setenv("ADMIN_INITIAL_PASSWORD", "An0ther!Pass")
    assert seed_admin.seed_admin() == 0
    r = row(fresh_db)
    assert (r["status"], r["failed_attempts"]) == ("Active", 0) and verify_password("An0ther!Pass", r["password_hash"])


def test_rejects_weak_password_without_touching_the_database(fresh_db, monkeypatch, capsys):
    monkeypatch.setattr(seed_admin, "db", fresh_db)
    monkeypatch.setenv("ADMIN_INITIAL_PASSWORD", "admin123")
    assert seed_admin.seed_admin() == 2
    assert row(fresh_db) is None
    assert "uppercase" in capsys.readouterr().out
