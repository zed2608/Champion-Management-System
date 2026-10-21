"""Start the program against the DEMO database, without touching your real .env.

    python scripts/run_demo.py

It reads ``.env.demo`` (copy ``.env.demo.example`` and fill in the connection), checks that DB_NAME is a champion_demo... database, and then runs
main.py exactly as ``python main.py`` would. It refuses to start if .env.demo points at champion_db or at an Aiven host, so the demo can
never be mistaken for the real system. Your real .env is not read for the database name (settings already in the environment win over .env).
"""
import os
import re
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWED = re.compile(r"^champion_demo[a-z0-9_]*$")


def check_env(values):
    """Raise SystemExit with a plain sentence unless these settings are safe for the demo."""
    name = str(values.get("DB_NAME") or "").strip().lower()
    host = str(values.get("DB_HOST") or "").strip().lower()
    if not ALLOWED.match(name):
        raise SystemExit(f"Refusing to start: DB_NAME in .env.demo is {values.get('DB_NAME')!r}. The demo only runs against a database named champion_demo...")
    if "aiven" in host:
        raise SystemExit("Refusing to start: .env.demo points at an Aiven host.")
    if not values.get("DB_USER"):
        raise SystemExit("Refusing to start: .env.demo has no DB_USER.")
    return name


def main(argv=None):
    from dotenv import dotenv_values
    args = list(sys.argv[1:] if argv is None else argv)
    env_file = Path(args[0]) if args else ROOT / ".env.demo"
    if not env_file.exists():
        raise SystemExit(f"{env_file.name} not found. Copy .env.demo.example to .env.demo and fill in your MySQL settings (see docs/DEMO_SETUP.md).")
    values = dotenv_values(env_file)
    check_env(values)
    os.environ.update({k: v for k, v in values.items() if v is not None})
    os.environ["DB_NAME"] = str(values["DB_NAME"]).strip()
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    runpy.run_path(str(ROOT / "main.py"), run_name="__main__")


if __name__ == "__main__":
    main()
