"""Test fixtures.

DB tests run against a THROWAWAY MySQL database and are skipped unless TEST_DB_USER is set:

    TEST_DB_HOST=localhost TEST_DB_PORT=3306 TEST_DB_USER=root TEST_DB_PASS=... [TEST_DB_NAME=test_champion] pytest -q

The user needs CREATE/DROP on `test%` databases. Database names MUST start with "test": the fixtures drop and recreate
them, so anything else aborts the run. The application's own DB_* settings are never used here.
"""
import itertools
import os
import sys
from pathlib import Path

import mysql.connector
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import migrate                      # noqa: E402
from db.pool import Database               # noqa: E402

BASE_NAME = os.getenv("TEST_DB_NAME", "test_champion")
_counter = itertools.count(1)


def _cfg(dbname):
    if not os.getenv("TEST_DB_USER"):
        return None
    return {"host": os.getenv("TEST_DB_HOST", "localhost"), "port": int(os.getenv("TEST_DB_PORT") or 3306),
            "user": os.environ["TEST_DB_USER"], "password": os.getenv("TEST_DB_PASS", ""),
            "database": dbname, "pool_size": 8, "connection_timeout": 5, "pool_wait": 5}


def pytest_configure(config):
    config.addinivalue_line("markers", "db: needs a throwaway MySQL (TEST_DB_* env vars)")
    if not BASE_NAME.lower().startswith("test"):
        pytest.exit(f"TEST_DB_NAME must start with 'test' (got {BASE_NAME!r}); refusing to drop it.", returncode=3)


def pytest_collection_modifyitems(config, items):
    if os.getenv("TEST_DB_USER"):
        return
    skip = pytest.mark.skip(reason="TEST_DB_USER not set: database tests skipped")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def admin_conn():
    cfg = _cfg(None)
    if cfg is None:
        pytest.skip("TEST_DB_USER not set")
    c = mysql.connector.connect(host=cfg["host"], port=cfg["port"], user=cfg["user"], password=cfg["password"], autocommit=True)
    yield c
    c.close()


def _recreate(admin_conn, name):
    assert name.lower().startswith("test"), name
    cur = admin_conn.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS `{name}`")
    cur.execute(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4")
    cur.close()


@pytest.fixture
def make_db(admin_conn):
    """Factory: make_db(suffix) -> fresh empty Database. Everything is dropped at teardown."""
    made = []

    def factory(suffix=""):
        name = f"{BASE_NAME}{suffix}"
        _recreate(admin_conn, name)
        d = Database(_cfg(name), pool_name=f"t{next(_counter)}")
        made.append((d, name))
        return d

    yield factory
    for d, name in made:
        d.close()
        cur = admin_conn.cursor()
        cur.execute(f"DROP DATABASE IF EXISTS `{name}`")
        cur.close()


@pytest.fixture
def fresh_db(make_db):
    """Empty database migrated from scratch to the canonical schema."""
    d = make_db()
    migrate.run(d, require_backup=False, log=lambda *_: None)
    return d


@pytest.fixture
def legacy_db(make_db):
    """Database in the pre-refactor shape, with awkward data, NOT yet migrated."""
    d = make_db("_legacy")
    sql = (Path(__file__).parent / "fixtures" / "legacy_schema.sql").read_text(encoding="utf-8")
    conn = d.raw_connection()
    cur = conn.cursor()
    cur.execute("SET SESSION autocommit = 1")
    cur.execute("SET SESSION sql_mode = ''")      # the legacy data deliberately breaks the new rules
    for stmt in migrate.split_schema_statements(sql):
        cur.execute(stmt)
    cur.close()
    conn.close()
    return d
