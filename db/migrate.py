"""Idempotent schema migration:  python -m db.migrate [--status | --dry-run | --make-backup | --backup-file F]

Brings ANY previous shape of the Champion database (fresh, create_tables.py-era, patched, runtime-patched) to the
shape described by db/schema.sql + db/triggers.sql, without deleting data.

Safety rules (enforced in code, not just documented):
  * REFUSES to touch a host on aivencloud.com. Develop and test against a local/LAN MySQL only.
  * REFUSES to apply anything unless a fresh mysqldump backup of THIS database exists
    (--backup-file F, or --make-backup to create one). A run with nothing pending needs no backup and changes nothing.
  * Re-runnable: every change checks information_schema first; finished steps are recorded in schema_migrations.
  * Constraints (CHECK / UNIQUE / FK) are only added when existing rows already satisfy them. Otherwise the step
    records "skipped: N rows violate ..." in schema_migrations.notes and carries on, so data is never silently altered
    to fit a rule and a bad row never blocks the whole upgrade.
  * DDL auto-commits in MySQL, so a step cannot be rolled back; that is why a backup is mandatory.
"""
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from db.pool import Database, config_from_env

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCHEMA_SQL = HERE / "schema.sql"
TRIGGERS_SQL = HERE / "triggers.sql"
BACKUP_DIR = ROOT / "backups"

EMP_ID_RE = re.compile(r"^(ADM|STF|WKR)-(\d{4})-(\d+)$")


class MigrationRefused(Exception):
    """A safety rule stopped the migration before anything was changed."""


# ----------------------------------------------------------------------------------------------
# SQL file helpers
# ----------------------------------------------------------------------------------------------
def _strip_comments(text: str) -> str:
    return re.sub(r"--[^\n]*", "", text)


def split_schema_statements(text: str):
    """schema.sql: statements end with ';' at end of line."""
    text = _strip_comments(text)
    return [s.strip() for s in re.split(r";[ \t]*(?:\r?\n|$)", text) if s.strip()]


def split_trigger_statements(text: str):
    """triggers.sql: statements are separated by a line holding only `-- //`."""
    chunks = re.split(r"(?m)^-- //[ \t]*\r?$", text)
    return [c for c in (_strip_comments(x).strip() for x in chunks) if c]


def parse_schema(text: str):
    """Extract columns, keys and CHECK constraints from schema.sql CREATE TABLE blocks."""
    text = _strip_comments(text)
    tables = {}
    for m in re.finditer(r"CREATE TABLE IF NOT EXISTS\s+`?(\w+)`?\s*\((.*?)\)\s*ENGINE=", text, re.S):
        name, body = m.group(1), m.group(2)
        info = {"columns": [], "keys": [], "checks": []}
        for raw in body.split("\n"):
            line = raw.strip().rstrip(",").strip()
            if not line:
                continue
            up = line.upper()
            km = re.match(r"(UNIQUE\s+)?KEY\s+(\w+)\s*\(([^)]*)\)$", line, re.I)
            cm = re.match(r"CONSTRAINT\s+(\w+)\s+CHECK\s*\((.*)\)$", line, re.I)
            if km:
                cols = [c.strip().strip("`") for c in km.group(3).split(",")]
                info["keys"].append({"name": km.group(2), "unique": bool(km.group(1)), "cols": cols})
            elif cm:
                info["checks"].append({"name": cm.group(1), "expr": cm.group(2)})
            elif up.startswith(("PRIMARY", "CONSTRAINT", "INDEX", "FOREIGN", "CHECK")):
                continue
            else:
                col = line.split()[0].strip("`")
                info["columns"].append({"name": col, "ddl": line, "pk": "PRIMARY KEY" in up})
        tables[name] = info
    return tables


# ----------------------------------------------------------------------------------------------
# Migration context
# ----------------------------------------------------------------------------------------------
class Ctx:
    def __init__(self, conn):
        self.conn = conn
        self.cur = conn.cursor(dictionary=True, buffered=True)
        self.notes = []
        self.schema = parse_schema(SCHEMA_SQL.read_text(encoding="utf-8"))

    def q(self, sql, params=None):
        self.cur.execute(sql, params or ())
        return self.cur

    def one(self, sql, params=None):
        self.q(sql, params)
        return self.cur.fetchone()

    def all(self, sql, params=None):
        self.q(sql, params)
        return self.cur.fetchall()

    def table_exists(self, t):
        return bool(self.one("SELECT 1 AS x FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=%s", (t,)))

    def col_exists(self, t, c):
        return bool(self.one("SELECT 1 AS x FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=%s AND column_name=%s", (t, c)))

    def col_info(self, t, c):
        return self.one("SELECT data_type AS dt, is_nullable AS nullable FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=%s AND column_name=%s", (t, c))

    def index_exists(self, t, name):
        return bool(self.one("SELECT 1 AS x FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name=%s AND index_name=%s LIMIT 1", (t, name)))

    def check_exists(self, t, name):
        return bool(self.one("SELECT 1 AS x FROM information_schema.table_constraints WHERE table_schema=DATABASE() AND table_name=%s AND constraint_name=%s AND constraint_type='CHECK'", (t, name)))

    def note(self, msg):
        self.notes.append(msg)


# ----------------------------------------------------------------------------------------------
# Steps (each idempotent). Order matters.
# ----------------------------------------------------------------------------------------------
def step_baseline_tables(ctx: Ctx):
    """Create every table that does not exist yet, already in its final shape."""
    for stmt in split_schema_statements(SCHEMA_SQL.read_text(encoding="utf-8")):
        ctx.q(stmt)


def step_rename_requirement_id(ctx: Ctx):
    """create_tables.py named the key requirement_id; every query in the code uses req_id."""
    if ctx.table_exists("project_requirements") and ctx.col_exists("project_requirements", "requirement_id") \
            and not ctx.col_exists("project_requirements", "req_id"):
        ctx.q("ALTER TABLE project_requirements CHANGE COLUMN requirement_id req_id INT NOT NULL AUTO_INCREMENT")
        ctx.note("renamed project_requirements.requirement_id -> req_id")


def step_add_missing_columns(ctx: Ctx):
    """Add every column that schema.sql declares but the live table lacks (user.archived_at, projects.archived_at,
    transaction.condition_return_notes, tool_issues.*, inventory.quantity_in_maintenance, ...)."""
    added = []
    for table, info in ctx.schema.items():
        if not ctx.table_exists(table):
            continue
        for col in info["columns"]:
            if col["pk"] or ctx.col_exists(table, col["name"]):
                continue
            ctx.q(f"ALTER TABLE `{table}` ADD COLUMN {col['ddl']}")
            added.append(f"{table}.{col['name']}")
    if added:
        ctx.note("added columns: " + ", ".join(added))


def step_inventory_decimal(ctx: Ctx):
    """inventory quantities were FLOAT and nullable; fractional consumables need exact DECIMAL(10,2) and NOT NULL."""
    changed = []
    for col in ("quantity_total", "quantity_available", "minimum_stock"):
        info = ctx.col_info("inventory", col)
        if info and (info["dt"] != "decimal" or info["nullable"] == "YES"):
            ctx.q(f"UPDATE inventory SET `{col}` = 0 WHERE `{col}` IS NULL")
            ctx.q(f"ALTER TABLE inventory MODIFY `{col}` DECIMAL(10,2) NOT NULL DEFAULT 0")
            changed.append(col)
    if changed:
        ctx.note("inventory -> DECIMAL(10,2) NOT NULL: " + ", ".join(changed))


def step_backfill(ctx: Ctx):
    # (a) 4-date snapshot on old transactions, taken from the project as it is NOW (best information available).
    n = ctx.q("""UPDATE `transaction` t JOIN projects p ON p.project_id = t.project_id
                 SET t.project_start_date = COALESCE(t.project_start_date, p.start_date),
                     t.due_date           = COALESCE(t.due_date, p.end_date)
                 WHERE t.project_id IS NOT NULL AND (t.project_start_date IS NULL OR t.due_date IS NULL)""").rowcount
    if n:
        ctx.note(f"snapshotted project dates onto {n} transactions")

    # (b) tool_issues: legacy is_resolved -> status / resolved_at
    n = ctx.q("""UPDATE tool_issues
                 SET status = IF(is_resolved = 1, 'Resolved', 'Open'),
                     resolved_at = IF(is_resolved = 1, COALESCE(resolved_at, flagged_at), NULL)
                 WHERE status <> IF(is_resolved = 1, 'Resolved', 'Open')""").rowcount
    if n:
        ctx.note(f"synced status on {n} tool_issues")

    # (c) projects: archived_at is canonical; remember the status each archived project had
    n = ctx.q("UPDATE projects SET archived_at = NOW() WHERE is_archived = 1 AND archived_at IS NULL").rowcount
    if n:
        ctx.note(f"set archived_at on {n} projects flagged only by is_archived")
    ctx.q("UPDATE projects SET status_before_archive = status WHERE archived_at IS NOT NULL AND status_before_archive IS NULL")

    # (d) project_workers from the comma list: EXACT employee_id match only.
    if ctx.one("SELECT COUNT(*) AS c FROM project_workers")["c"] == 0:
        users = {r["employee_id"]: r["user_id"] for r in ctx.all("SELECT employee_id, user_id FROM `user` WHERE employee_id IS NOT NULL")}
        linked = unmatched = 0
        for p in ctx.all("SELECT project_id, workers_assigned FROM projects WHERE workers_assigned IS NOT NULL AND workers_assigned <> ''"):
            for tok in {t.strip() for t in p["workers_assigned"].split(",") if t.strip()}:
                uid = users.get(tok)
                if uid:
                    ctx.q("INSERT IGNORE INTO project_workers (project_id, user_id) VALUES (%s, %s)", (p["project_id"], uid))
                    linked += 1
                else:
                    unmatched += 1
        if linked or unmatched:
            ctx.note(f"project_workers: {linked} links created; {unmatched} entries in the old text column matched no employee_id (left in workers_assigned)")

    # (e) id_sequences from existing employee ids
    seq = {}
    for r in ctx.all("SELECT employee_id FROM `user` WHERE employee_id IS NOT NULL"):
        m = EMP_ID_RE.match(r["employee_id"])
        if m:
            key = (m.group(1), int(m.group(2)))
            seq[key] = max(seq.get(key, 0), int(m.group(3)))
    for (prefix, yr), last in seq.items():
        ctx.q("INSERT INTO id_sequences (prefix, yr, last_seq) VALUES (%s, %s, %s) "
              "ON DUPLICATE KEY UPDATE last_seq = GREATEST(last_seq, VALUES(last_seq))", (prefix, yr, last))

    # (f) Per-unit condition model. Old behaviour kept damaged/lost units inside quantity_total but out of
    # quantity_available, so  total - available - deployed  = units that are out of service. Only tools that still have an
    # OPEN issue are reclassified (all-'Lost' issues -> quantity_lost, otherwise quantity_in_maintenance);
    # anything else is only reported, never guessed.
    moved = anomalies = 0
    rows = ctx.all("""
        SELECT i.tool_id, i.quantity_total AS tot, i.quantity_available AS av,
               COALESCE((SELECT SUM(t.quantity) FROM `transaction` t
                         WHERE t.tool_id = i.tool_id AND t.status = 'Active'), 0) AS deployed,
               (SELECT COUNT(*) FROM tool_issues s WHERE s.tool_id = i.tool_id AND s.status = 'Open') AS open_issues,
               (SELECT COUNT(*) FROM tool_issues s WHERE s.tool_id = i.tool_id AND s.status = 'Open'
                    AND s.condition_flag <> 'Lost') AS open_not_lost
        FROM inventory i
        WHERE i.quantity_in_maintenance = 0 AND i.quantity_lost = 0""")
    for r in rows:
        residual = r["tot"] - r["av"] - r["deployed"]
        if residual <= 0:
            continue
        if r["open_issues"] == 0:
            anomalies += 1
            continue
        col = "quantity_in_maintenance" if r["open_not_lost"] else "quantity_lost"
        ctx.q(f"UPDATE inventory SET `{col}` = %s WHERE tool_id = %s", (residual, r["tool_id"]))
        moved += 1
    if moved or anomalies:
        ctx.note(f"unit-condition backfill: {moved} tools reclassified; {anomalies} tools have unexplained missing units but no open issue (review manually)")


def step_indexes(ctx: Ctx):
    added, skipped = [], []
    for table, info in ctx.schema.items():
        if not ctx.table_exists(table):
            continue
        for k in info["keys"]:
            if ctx.index_exists(table, k["name"]):
                continue
            if not all(ctx.col_exists(table, c) for c in k["cols"]):
                continue
            cols = ", ".join(f"`{c}`" for c in k["cols"])
            if k["unique"]:
                nn = " AND ".join(f"`{c}` IS NOT NULL" for c in k["cols"])
                dup = ctx.one(f"SELECT 1 AS x FROM `{table}` WHERE {nn} GROUP BY {cols} HAVING COUNT(*) > 1 LIMIT 1")
                if dup:
                    skipped.append(f"{table}.{k['name']} (duplicate values exist)")
                    continue
            ctx.q(f"ALTER TABLE `{table}` ADD {'UNIQUE ' if k['unique'] else ''}KEY `{k['name']}` ({cols})")
            added.append(f"{table}.{k['name']}")
    if added:
        ctx.note("indexes added: " + ", ".join(added))
    if skipped:
        ctx.note("indexes SKIPPED: " + ", ".join(skipped))


# (table, column, referenced table, referenced column, ON DELETE, canonical constraint name)
FK_TARGETS = [
    ("transaction", "tool_id", "tool", "tool_id", "RESTRICT", "transaction_ibfk_1"),
    ("transaction", "user_id", "user", "user_id", "RESTRICT", "transaction_ibfk_2"),
    ("project_requirements", "tool_id", "tool", "tool_id", "RESTRICT", "project_requirements_ibfk_2"),
    ("tool_issues", "tool_id", "tool", "tool_id", "RESTRICT", "tool_issues_ibfk_1"),
    ("tool_issues", "transaction_id", "transaction", "transaction_id", "SET NULL", "fk_issue_txn"),
]


def step_foreign_keys(ctx: Ctx):
    """History must never be deleted: FKs from transaction -> tool/user become RESTRICT (were CASCADE)."""
    changed, failed = [], []
    for table, col, rtable, rcol, rule, name in FK_TARGETS:
        if not (ctx.table_exists(table) and ctx.col_exists(table, col)):
            continue
        cur = ctx.one("""SELECT k.constraint_name AS cname, r.delete_rule AS rule
                         FROM information_schema.key_column_usage k
                         JOIN information_schema.referential_constraints r
                           ON r.constraint_schema = k.constraint_schema AND r.constraint_name = k.constraint_name
                         WHERE k.table_schema = DATABASE() AND k.table_name = %s AND k.column_name = %s
                           AND k.referenced_table_name IS NOT NULL LIMIT 1""", (table, col))
        wanted = {"RESTRICT": ("RESTRICT", "NO ACTION"), "SET NULL": ("SET NULL",)}[rule]
        if cur and cur["rule"] in wanted:
            continue
        rt = f"`{rtable}`"
        add = f"ADD CONSTRAINT `{name}` FOREIGN KEY (`{col}`) REFERENCES {rt} (`{rcol}`) ON DELETE {rule}"
        drop = f"DROP FOREIGN KEY `{cur['cname']}`, " if cur else ""
        try:
            ctx.q(f"ALTER TABLE `{table}` {drop}{add}")
            changed.append(f"{table}.{col}->{rule}")
        except Exception as exc:  # orphan rows etc.: report, never fail the whole upgrade
            failed.append(f"{table}.{col}: {exc}")
    if changed:
        ctx.note("foreign keys set: " + ", ".join(changed))
    if failed:
        ctx.note("foreign keys SKIPPED: " + " | ".join(failed))


def step_check_constraints(ctx: Ctx):
    added, skipped = [], []
    for table, info in ctx.schema.items():
        if not ctx.table_exists(table):
            continue
        for c in info["checks"]:
            if ctx.check_exists(table, c["name"]):
                continue
            bad = ctx.one(f"SELECT COUNT(*) AS n FROM `{table}` WHERE NOT ({c['expr']})")["n"]
            if bad:
                skipped.append(f"{c['name']} ({bad} existing rows violate it)")
                continue
            ctx.q(f"ALTER TABLE `{table}` ADD CONSTRAINT `{c['name']}` CHECK ({c['expr']})")
            added.append(c["name"])
    if added:
        ctx.note("checks added: " + ", ".join(added))
    if skipped:
        ctx.note("checks SKIPPED: " + ", ".join(skipped))


# Allowed project status edges. legacy=1 rows are tolerated only until project_service owns every write.
TRANSITIONS = [
    ("Pending", "Approved", 0), ("Pending", "Declined", 0),
    ("Approved", "Ongoing", 0), ("Approved", "Cancelled", 0),
    ("Ongoing", "Completed", 0),
    ("Ongoing", "Cancelled", 0),     # existing Admin feature "Cancel Project" on a running project: kept, not removed
    ("Pending", "Cancelled", 1),     # old UI stores "Declined" as Cancelled
    ("Approved", "Pending", 1),      # old UI: a Staff edit of an Approved project sends it back to Pending
]


def step_seed_transitions(ctx: Ctx):
    for f, t, legacy in TRANSITIONS:
        ctx.q("INSERT IGNORE INTO project_transitions (from_status, to_status, legacy) VALUES (%s, %s, %s)", (f, t, legacy))


# (version, name, function, reconcile)
#   reconcile=True  : structural + idempotent, re-run whenever schema.sql changes (so editing schema.sql reaches
#                     databases that were migrated earlier).
#   reconcile=False : one-shot data work (backfills). Never repeated.
STEPS = [
    (1, "baseline_tables", step_baseline_tables, True),
    (2, "rename_requirement_id", step_rename_requirement_id, True),
    (3, "add_missing_columns", step_add_missing_columns, True),
    (4, "inventory_decimal", step_inventory_decimal, True),
    (5, "backfill_data", step_backfill, False),
    (6, "indexes", step_indexes, True),
    (7, "foreign_keys_restrict", step_foreign_keys, True),
    (8, "check_constraints", step_check_constraints, True),
    (9, "seed_project_transitions", step_seed_transitions, True),
]


# ----------------------------------------------------------------------------------------------
# Triggers (re-applied whenever triggers.sql changes)
# ----------------------------------------------------------------------------------------------
def triggers_hash() -> str:
    return hashlib.sha256(TRIGGERS_SQL.read_bytes()).hexdigest()


def schema_hash() -> str:
    return hashlib.sha256(SCHEMA_SQL.read_bytes()).hexdigest()


def _meta_get(ctx, key):
    row = ctx.one("SELECT meta_value AS v FROM schema_meta WHERE meta_key = %s", (key,))
    return row["v"] if row else None


def _meta_set(ctx, key, value):
    ctx.q("INSERT INTO schema_meta (meta_key, meta_value) VALUES (%s, %s) "
          "ON DUPLICATE KEY UPDATE meta_value = VALUES(meta_value)", (key, value))


def apply_triggers(ctx: Ctx):
    for stmt in split_trigger_statements(TRIGGERS_SQL.read_text(encoding="utf-8")):
        ctx.q(stmt)
    _meta_set(ctx, "triggers_sha256", triggers_hash())


# ----------------------------------------------------------------------------------------------
# Backup guard
# ----------------------------------------------------------------------------------------------
def find_mysqldump():
    exe = shutil.which("mysqldump")
    if exe:
        return exe
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
        for hit in sorted(Path(base, "MySQL").glob("MySQL Server */bin/mysqldump.exe"), reverse=True):
            return str(hit)
    return None


def verify_backup(path: Path, dbname: str, max_age_min: int):
    """A backup counts only if it is recent, complete (trailer present) and for THIS database."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size < 512:
        raise MigrationRefused(f"Backup file missing or too small: {path}")
    age = (time.time() - path.stat().st_mtime) / 60
    if age > max_age_min:
        raise MigrationRefused(f"Backup is {age:.0f} min old (limit {max_age_min}). Make a fresh one with --make-backup.")
    with open(path, "rb") as f:
        head = f.read(4096).decode("utf-8", "replace")
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - 2048))
        tail = f.read().decode("utf-8", "replace")
    if "Dump completed" not in tail:
        raise MigrationRefused("Backup has no 'Dump completed' trailer: it is truncated.")
    if f"Database: {dbname}" not in head:
        raise MigrationRefused(f"Backup header does not mention database '{dbname}'.")


def make_backup(cfg: dict) -> Path:
    """mysqldump into backups/, credentials via a temporary defaults file (never on the command line)."""
    exe = find_mysqldump()
    if not exe:
        raise MigrationRefused("mysqldump not found. Install MySQL client tools or pass --backup-file.")
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    final = BACKUP_DIR / f"premigrate_{cfg['database']}_{stamp}.sql"
    part = final.with_suffix(".sql.part")
    pw = str(cfg["password"]).replace("\\", "\\\\").replace('"', '\\"')
    fd, cnf = tempfile.mkstemp(suffix=".cnf")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f'[client]\nhost={cfg["host"]}\nport={cfg["port"]}\nuser={cfg["user"]}\npassword="{pw}"\n')
        try:
            os.chmod(cnf, 0o600)
        except OSError:
            pass
        proc = subprocess.run(
            [exe, f"--defaults-extra-file={cnf}", "--single-transaction", "--routines", "--triggers",
             "--no-tablespaces", "--default-character-set=utf8mb4", f"--result-file={part}", cfg["database"]],
            capture_output=True, timeout=900)
    finally:
        try:
            os.remove(cnf)
        except OSError:
            pass
    if proc.returncode != 0:
        part.unlink(missing_ok=True)
        raise MigrationRefused("mysqldump failed: " + proc.stderr.decode("utf-8", "replace").strip()[:300])
    os.replace(part, final)
    return final


# ----------------------------------------------------------------------------------------------
# Runner
# ----------------------------------------------------------------------------------------------
def _ensure_meta_tables(ctx: Ctx):
    ctx.q("""CREATE TABLE IF NOT EXISTS schema_migrations (
               version INT NOT NULL PRIMARY KEY, name VARCHAR(100) NOT NULL,
               applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, notes TEXT NULL
             ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    ctx.q("""CREATE TABLE IF NOT EXISTS schema_meta (
               meta_key VARCHAR(50) NOT NULL PRIMARY KEY, meta_value VARCHAR(255) NULL
             ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")


def _guard_host(cfg):
    host = str(cfg["host"]).lower()
    if "aivencloud.com" in host or host.endswith(".aiven.io"):
        raise MigrationRefused("Refusing to migrate a database hosted on Aiven. Run this only against the local/LAN MySQL.")


def pending(ctx: Ctx):
    """(steps to run, triggers need applying)."""
    _ensure_meta_tables(ctx)
    done = {r["version"] for r in ctx.all("SELECT version FROM schema_migrations")}
    schema_changed = _meta_get(ctx, "schema_sha256") != schema_hash()
    steps = [s for s in STEPS if s[0] not in done or (s[3] and schema_changed)]
    trig = _meta_get(ctx, "triggers_sha256") != triggers_hash()
    return steps, trig


def run(database: Database, *, dry_run=False, backup_file=None, make_backup_now=False,
        max_backup_age_min=60, require_backup=True, log=print):
    """Apply pending migrations. Returns a list of (name, notes). Raises MigrationRefused when a safety rule trips."""
    cfg = database.config
    _guard_host(cfg)
    if not require_backup and not str(cfg["database"]).lower().startswith("test"):
        raise MigrationRefused("require_backup=False is only allowed for databases whose name starts with 'test'.")
    conn = database.raw_connection()
    ctx = Ctx(conn)
    ctx.q("SET SESSION autocommit = 1")   # DDL + bookkeeping must persist step by step
    report = []
    try:
        if not ctx.one("SELECT GET_LOCK('champion_migrate', 10) AS g")["g"]:
            raise MigrationRefused("Another migration is running.")
        steps, trig = pending(ctx)
        if not steps and not trig:
            log("Schema is up to date. Nothing to do.")
            return report
        if dry_run:
            for v, name, *_ in steps:
                log(f"[dry-run] would apply {v}: {name}")
            if trig:
                log("[dry-run] would (re)apply triggers")
            return [(st[1], None) for st in steps]
        if require_backup:
            if make_backup_now:
                backup_file = make_backup(cfg)
                log(f"Backup written: {backup_file}")
            if not backup_file:
                raise MigrationRefused("A fresh backup is required. Re-run with --make-backup (or --backup-file F).")
            verify_backup(Path(backup_file), cfg["database"], max_backup_age_min)
        for v, name, fn, _reconcile in steps:
            ctx.notes = []
            log(f"Applying {v}: {name} ...")
            fn(ctx)
            notes = "; ".join(ctx.notes) or None
            ctx.q("INSERT INTO schema_migrations (version, name, notes) VALUES (%s, %s, %s) "
                  "ON DUPLICATE KEY UPDATE notes = VALUES(notes), applied_at = CURRENT_TIMESTAMP", (v, name, notes))
            report.append((name, notes))
            if notes:
                log(f"   {notes}")
        _meta_set(ctx, "schema_sha256", schema_hash())
        if trig or steps:
            log("Applying triggers ...")
            apply_triggers(ctx)
            report.append(("triggers", None))
        log("Migration complete.")
        return report
    finally:
        try:
            ctx.q("SELECT RELEASE_LOCK('champion_migrate')")
        except Exception:
            pass
        ctx.cur.close()
        conn.close()


def check_schema_current(database: Database):
    """For the app at startup: (ok, message). Replaces the old runtime CREATE/ALTER/DROP TABLE in the views."""
    try:
        with database.read() as cur:
            cur.execute("SELECT version FROM schema_migrations")
            done = {r["version"] for r in cur.fetchall()}
            cur.execute("SELECT meta_key AS k, meta_value AS v FROM schema_meta")
            meta = {r["k"]: r["v"] for r in cur.fetchall()}
    except Exception:
        return False, "The database has not been set up. Ask an administrator to run: python -m db.migrate --make-backup"
    if (not {s[0] for s in STEPS} <= done or meta.get("schema_sha256") != schema_hash()
            or meta.get("triggers_sha256") != triggers_hash()):
        return False, "The database needs an upgrade. Ask an administrator to run: python -m db.migrate --make-backup"
    return True, ""


def main(argv=None):
    ap = argparse.ArgumentParser(description="Upgrade the Champion database schema (idempotent).")
    ap.add_argument("--status", action="store_true", help="show applied/pending steps and exit")
    ap.add_argument("--dry-run", action="store_true", help="list pending steps, change nothing")
    ap.add_argument("--make-backup", action="store_true", help="create a fresh mysqldump first (required unless --backup-file)")
    ap.add_argument("--backup-file", help="path of a mysqldump taken in the last --max-backup-age-min minutes")
    ap.add_argument("--max-backup-age-min", type=int, default=60)
    args = ap.parse_args(argv)

    database = Database(config_from_env())
    _guard_host(database.config)
    try:
        if args.status:
            conn = database.raw_connection()
            ctx = Ctx(conn)
            steps, trig = pending(ctx)
            print(f"Database: {database.config['database']} @ {database.config['host']}")
            print("Pending steps:", ", ".join(f"{st[0]}:{st[1]}" for st in steps) or "none")
            print("Triggers need (re)apply:", trig)
            conn.close()
            return 0
        run(database, dry_run=args.dry_run, backup_file=args.backup_file, make_backup_now=args.make_backup,
            max_backup_age_min=args.max_backup_age_min)
        return 0
    except MigrationRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    finally:
        database.close()


if __name__ == "__main__":
    sys.exit(main())
