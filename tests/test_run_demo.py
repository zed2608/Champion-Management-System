"""scripts/run_demo.py must never start the program against the real database."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import run_demo  # noqa: E402


def test_only_champion_demo_databases_are_accepted():
    assert run_demo.check_env({"DB_NAME": "champion_demo", "DB_HOST": "127.0.0.1", "DB_USER": "root"}) == "champion_demo"
    assert run_demo.check_env({"DB_NAME": "champion_demo_friday", "DB_HOST": "localhost", "DB_USER": "root"})


@pytest.mark.parametrize("name", ["champion_db", "CHAMPION_DB", "defaultdb", "", None, "champion_demo; DROP DATABASE champion_db", "test_champion"])
def test_the_real_database_and_odd_names_are_refused(name):
    with pytest.raises(SystemExit, match="Refusing"):
        run_demo.check_env({"DB_NAME": name, "DB_HOST": "127.0.0.1", "DB_USER": "root"})


def test_aiven_and_missing_user_are_refused():
    with pytest.raises(SystemExit, match="Aiven"):
        run_demo.check_env({"DB_NAME": "champion_demo", "DB_HOST": "x.b.aivencloud.com", "DB_USER": "u"})
    with pytest.raises(SystemExit, match="DB_USER"):
        run_demo.check_env({"DB_NAME": "champion_demo", "DB_HOST": "127.0.0.1"})


def test_a_missing_env_file_explains_what_to_do(tmp_path):
    with pytest.raises(SystemExit, match="Copy .env.demo.example"):
        run_demo.main([str(tmp_path / "nope.env")])


def test_a_file_that_points_at_the_real_database_stops_before_main_runs(tmp_path, monkeypatch):
    f = tmp_path / "bad.env"
    f.write_text("DB_HOST=127.0.0.1\nDB_USER=root\nDB_PASS=x\nDB_NAME=champion_db\n", encoding="utf-8")
    ran = []
    monkeypatch.setattr(run_demo.runpy, "run_path", lambda *a, **k: ran.append(a))
    with pytest.raises(SystemExit, match="Refusing"):
        run_demo.main([str(f)])
    assert not ran
