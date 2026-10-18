"""Create/refresh the champion_staff and champion_admin MySQL accounts from db/grants.sql.

    set STAFF_DB_PASS=...  &  set ADMIN_DB_PASS=...      (never commit these)
    python -m db.apply_grants                             (connects with DB_* from .env, which must be a MySQL admin)

Passwords are escaped by the MySQL driver, never printed.
"""
import os
import sys
from pathlib import Path

from mysql.connector.conversion import MySQLConverter

from db.migrate import split_schema_statements
from db.pool import Database, config_from_env

GRANTS_SQL = Path(__file__).resolve().parent / "grants.sql"
_conv = MySQLConverter()


def _lit(value: str) -> str:
    """Escape a value for use INSIDE single quotes in the template."""
    return _conv.escape(value) if isinstance(value, str) else value


def render(db_name: str, staff_pass: str, admin_pass: str, *, staff_user="champion_staff",
           admin_user="champion_admin", host="%") -> list:
    for name, val in (("db name", db_name), ("staff user", staff_user), ("admin user", admin_user), ("host", host)):
        if not val or any(c in val for c in "`'\\\n"):
            raise ValueError(f"unsafe or empty {name}")
    if len(staff_pass) < 8 or len(admin_pass) < 8:
        raise ValueError("passwords must be at least 8 characters")
    # Split the TEMPLATE first, substitute afterwards: a password containing "--" or ";" must never be re-parsed.
    stmts = split_schema_statements(GRANTS_SQL.read_text(encoding="utf-8"))
    subs = {"{{DB}}": db_name, "{{STAFF_USER}}": staff_user, "{{ADMIN_USER}}": admin_user, "{{HOST}}": host,
            "{{STAFF_PASSWORD}}": _lit(staff_pass), "{{ADMIN_PASSWORD}}": _lit(admin_pass)}
    out = []
    for stmt in stmts:
        for k, v in subs.items():
            stmt = stmt.replace(k, v)
        out.append(stmt)
    return out


def apply(database: Database, staff_pass: str, admin_pass: str, **kw) -> int:
    stmts = render(database.config["database"], staff_pass, admin_pass, **kw)
    conn = database.raw_connection()
    cur = conn.cursor()
    try:
        cur.execute("SET SESSION autocommit = 1")
        for s in stmts:
            cur.execute(s)
        cur.execute("FLUSH PRIVILEGES")
    finally:
        cur.close()
        conn.close()
    return len(stmts)


def main():
    sp, ap = os.getenv("STAFF_DB_PASS", ""), os.getenv("ADMIN_DB_PASS", "")
    if not sp or not ap:
        print("Set STAFF_DB_PASS and ADMIN_DB_PASS first.", file=sys.stderr)
        return 2
    database = Database(config_from_env())
    n = apply(database, sp, ap, staff_user=os.getenv("STAFF_DB_USER", "champion_staff"),
              admin_user=os.getenv("ADMIN_DB_USER", "champion_admin"), host=os.getenv("GRANT_HOST", "%"))
    print(f"Applied {n} statements to database '{database.config['database']}'.")
    database.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
