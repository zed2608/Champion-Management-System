"""Backup and restore of the whole database, plus the backup history (``backup_logs``).

[UNHAPPY-PATH] The old buttons put the password on the command line, treated a non-zero mysqldump exit as success when the file was
big enough, wrote straight to the final file name (a crash left a half file that looked like a backup), never checked free space,
restored files of any kind without looking, and gave no way back if a restore was wrong. Here:

  * credentials go through a temporary ``--defaults-extra-file`` (mode 600, deleted in ``finally``), never the command line;
  * ANY non-zero mysqldump exit is a failure and the partial file is deleted;
  * the dump is written to ``<name>.sql.part``, must end with the ``-- Dump completed`` trailer, and only then is renamed;
  * free disk space is checked first (database size x 2, at least 50 MB);
  * the SHA-256 of every finished backup is stored in ``backup_logs.sha256`` (and shown in the history);
  * a restore first VALIDATES the file (mysqldump header for THIS database, trailer present, not empty, optional SHA-256 match),
    then takes an automatic safety backup of the current data, and only then loads the file;
  * the backup history survives a restore (the dump replaces ``backup_logs``; the old rows are put back).
"""
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

from db import db
from services.validators import like_pattern
from services.errors import PROJECT_ROOT, ServiceError, get_logger
from services.security import require_role

TRAILER = "-- Dump completed"
MIN_FREE_BYTES = 50 * 1024 * 1024
SAFETY_DIR = PROJECT_ROOT / "backups"
DUMP_TIMEOUT = 900


class BackupError(ServiceError):
    """Message is safe to show."""


# ---- executables -------------------------------------------------------------------------------------------------------------
def _find_exe(name):
    exe = shutil.which(name)
    if exe:
        return exe
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
        for hit in sorted(Path(base, "MySQL").glob(f"MySQL Server */bin/{name}.exe"), reverse=True):
            return str(hit)
    for guess in (rf"C:\xampp\mysql\bin\{name}.exe", rf"C:\wamp64\bin\mysql\mysql8.0\bin\{name}.exe"):
        if os.path.isfile(guess):
            return guess
    return None


def _find_mysqldump():
    return _find_exe("mysqldump")


def _find_mysql():
    return _find_exe("mysql")


# ---- helpers -----------------------------------------------------------------------------------------------------------------
def _cfg():
    c = dict(db.config)
    return {"host": c.get("host", "127.0.0.1"), "port": c.get("port", 3306), "user": c.get("user", "root"),
            "password": c.get("password", ""), "database": c.get("database")}


class _Defaults:
    """Temporary --defaults-extra-file holding the credentials; removed on exit even if the program fails."""

    def __init__(self, cfg):
        self.cfg, self.path = cfg, None

    def __enter__(self):
        fd, self.path = tempfile.mkstemp(suffix=".cnf")
        pw = str(self.cfg["password"]).replace("\\", "\\\\").replace('"', '\\"')
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f'[client]\nhost={self.cfg["host"]}\nport={self.cfg["port"]}\nuser={self.cfg["user"]}\npassword="{pw}"\n')
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        return self.path

    def __exit__(self, *exc):
        try:
            if self.path:
                os.remove(self.path)
        except OSError:
            pass


def _human_size(n):
    if n >= 1_048_576:
        return f"{n / 1_048_576:.2f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


def _sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _database_size_bytes():
    with db.read() as cur:
        cur.execute("SELECT COALESCE(SUM(data_length + index_length), 0) AS n FROM information_schema.tables WHERE table_schema = DATABASE()")
        return int(cur.fetchone()["n"])


def _check_disk_space(folder, needed=None):
    needed = needed if needed is not None else max(MIN_FREE_BYTES, _database_size_bytes() * 2)
    free = shutil.disk_usage(folder).free
    if free < needed:
        raise BackupError(f"Not enough free disk space in that folder ({_human_size(free)} free, about {_human_size(needed)} needed). "
                          "Choose another drive or free some space.")


def _safe_name(custom, stamp, database):
    if custom:
        base = "".join(c if c.isalnum() or c in "-_" else "_" for c in custom.replace(" ", "_"))[:60].strip("_")
        if base:
            return f"{base}_{stamp}.sql"
    return f"{database}_backup_{stamp}.sql"


def _read_head_tail(path, head=4096, tail=2048):
    with open(path, "rb") as f:
        h = f.read(head).decode("utf-8", "replace")
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - tail))
        t = f.read().decode("utf-8", "replace")
    return h, t, size


def _validate_dump(path, database=None, expected_sha256=None):
    """Raise BackupError unless ``path`` looks like a COMPLETE mysqldump (of ``database`` when given)."""
    path = Path(path)
    if not path.is_file():
        raise BackupError("That backup file does not exist.")
    head, tail, size = _read_head_tail(path)
    if size < 512:
        raise BackupError("That file is too small to be a database backup.")
    if "MySQL dump" not in head:
        raise BackupError("That file is not a database backup made by this system (no mysqldump header).")
    if database and not re.search(rf"(?m)^-- (Host:.*\s+)?Database:\s*{re.escape(database)}\s*$", head):
        raise BackupError("That backup was made from a different database, so it will not be restored.")
    if TRAILER not in tail:
        raise BackupError("That backup file is incomplete (the copy was cut short). It will not be restored.")
    if expected_sha256 and _sha256_of(path).lower() != expected_sha256.lower():
        raise BackupError("That backup file has changed since it was made (its checksum does not match). It will not be restored.")
    return size


# ---- backup ------------------------------------------------------------------------------------------------------------------
def _dump_to_file(final_path, cfg=None, exe=None, run=subprocess.run, check_space=True):
    """mysqldump -> ``final_path`` safely. Returns (size_bytes, sha256)."""
    cfg = cfg or _cfg()
    exe = exe or _find_mysqldump()
    if not exe:
        raise BackupError("mysqldump was not found. Install MySQL Server/Workbench or add its 'bin' folder to the PATH, then try again.")
    final_path = Path(final_path)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    if check_space:
        _check_disk_space(final_path.parent)
    part = final_path.with_name(final_path.name + ".part")
    try:
        with _Defaults(cfg) as cnf:
            proc = run([exe, f"--defaults-extra-file={cnf}", "--single-transaction", "--routines", "--triggers", "--no-tablespaces",
                        "--set-gtid-purged=OFF", "--default-character-set=utf8mb4", f"--result-file={part}", cfg["database"]],
                       capture_output=True, timeout=DUMP_TIMEOUT)
        if proc.returncode != 0:
            get_logger().error("mysqldump exit %s: %s", proc.returncode, (proc.stderr or b"").decode("utf-8", "replace")[:500])
            raise BackupError(f"The backup program reported an error (code {proc.returncode}). Nothing was saved. "
                              "Details are in logs\\app.log.")
        _validate_dump(part)                                   # header + trailer: a cut-short file is never renamed
        os.replace(part, final_path)
    except subprocess.TimeoutExpired:
        raise BackupError("The backup took too long and was stopped. Nothing was saved.")
    finally:
        try:
            if part.exists():
                part.unlink()
        except OSError:
            pass
    return final_path.stat().st_size, _sha256_of(final_path)


def _log_row(actor_id, filename, filepath, size_text, note, status, kind, sha):
    with db.transaction() as cur:
        cur.execute("INSERT INTO backup_logs (filename, filepath, file_size, note, created_by, status, type, sha256) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", (filename, str(filepath), size_text, note or None, actor_id, status, kind, sha))


@require_role("Admin")
def create_backup(actor, dest_folder, custom_name="", note="", exe=None, run=subprocess.run):
    """Make a verified backup in ``dest_folder`` and record it. Returns {"path","size","sha256"}."""
    dest = Path(str(dest_folder or "").strip())
    if not str(dest_folder or "").strip() or not dest.is_dir():
        raise BackupError("Please choose a folder that exists to save the backup.")
    cfg = _cfg()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    final = dest / _safe_name(custom_name, stamp, cfg["database"])
    try:
        size, sha = _dump_to_file(final, cfg, exe=exe, run=run)
    except Exception as e:
        _log_row(actor["user_id"], final.name, final, "—", note, "Failed", "Backup", None)
        raise
    _log_row(actor["user_id"], final.name, final, _human_size(size), note, "Success", "Backup", sha)
    from database import log_action
    log_action(actor["user_id"], "Backup", "Maintenance", f"Database backup created: {final.name} ({_human_size(size)})")
    return {"path": str(final), "size": _human_size(size), "sha256": sha}


# ---- restore -----------------------------------------------------------------------------------------------------------------
def _snapshot_history():
    with db.read() as cur:
        cur.execute("SELECT filename, filepath, file_size, note, created_by, created_at, status, type, sha256 FROM backup_logs ORDER BY backup_id")
        return cur.fetchall()


def _restore_history(rows):
    with db.transaction() as cur:
        cur.execute("DELETE FROM backup_logs")
        for r in rows:
            cur.execute("INSERT INTO backup_logs (filename, filepath, file_size, note, created_by, created_at, status, type, sha256) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (r["filename"], r["filepath"], r["file_size"], r["note"], r["created_by"], r["created_at"], r["status"],
                         r["type"] or "Backup", r.get("sha256")))


@require_role("Admin")
def restore_backup(actor, src_file, note="", expected_sha256=None, exe_dump=None, exe_mysql=None, run=subprocess.run, safety_dir=None):
    """Validate, take an automatic safety backup, then load ``src_file`` over the current database.
    Returns {"safety_backup": path}. Other computers using the system must log out first (the UI says so)."""
    cfg = _cfg()
    src = Path(str(src_file or ""))
    _validate_dump(src, cfg["database"], expected_sha256)
    mysql_exe = exe_mysql or _find_mysql()
    if not mysql_exe:
        raise BackupError("The mysql program was not found. Install MySQL Server/Workbench or add its 'bin' folder to the PATH, then try again.")
    # 1. safety copy of what is there NOW
    safety_dir = Path(safety_dir or SAFETY_DIR)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    safety = safety_dir / f"before_restore_{cfg['database']}_{stamp}.sql"
    n = 1
    while safety.exists() or safety == src:                  # two restores in one second must never overwrite each other's safety copy
        n += 1
        safety = safety_dir / f"before_restore_{cfg['database']}_{stamp}_{n}.sql"
    try:
        size, sha = _dump_to_file(safety, cfg, exe=exe_dump, run=run)
    except BackupError as e:
        raise BackupError(f"The restore was NOT started because the safety backup of the current data failed: {e}")
    history = _snapshot_history()
    try:
        history.append({"filename": safety.name, "filepath": str(safety), "file_size": _human_size(size), "note": "Automatic safety backup before a restore",
                        "created_by": actor["user_id"], "created_at": datetime.now(), "status": "Success", "type": "Backup", "sha256": sha})
        # 2. load the file
        try:
            with _Defaults(cfg) as cnf, open(src, "rb") as f:
                proc = run([mysql_exe, f"--defaults-extra-file={cnf}", "--default-character-set=utf8mb4", cfg["database"]],
                           stdin=f, capture_output=True, timeout=DUMP_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise BackupError(f"The restore took too long and was stopped. The data may be incomplete: restore the safety backup {safety.name}.")
        if proc.returncode != 0:
            get_logger().error("mysql restore exit %s: %s", proc.returncode, (proc.stderr or b"").decode("utf-8", "replace")[:500])
            raise BackupError(f"The restore failed part-way (code {proc.returncode}). The data may be incomplete. "
                              f"Restore the safety backup made just before: {safety}")
    finally:
        try:
            history.append({"filename": src.name, "filepath": str(src), "file_size": _human_size(src.stat().st_size), "note": note or None,
                            "created_by": actor["user_id"], "created_at": datetime.now(), "status": "Success", "type": "Restore", "sha256": None})
            _restore_history(history)
        except Exception:
            get_logger().exception("Could not rebuild the backup history after a restore")
    from database import log_action
    log_action(actor["user_id"], "Restore", "Maintenance", f"Database restored from backup: {src.name}")
    return {"safety_backup": str(safety)}


# ---- history -----------------------------------------------------------------------------------------------------------------
@require_role("Admin")
def history_page(actor, limit=50, offset=0, search=""):
    """(rows newest first, total). Server-side paging."""
    limit, offset = max(1, min(int(limit), 500)), max(0, int(offset))
    where = " FROM backup_logs bl LEFT JOIN `user` u ON bl.created_by = u.user_id"
    args = []
    if search:
        where += " WHERE (bl.filename LIKE %s OR bl.note LIKE %s OR u.full_name LIKE %s OR bl.status LIKE %s)"
        args = [like_pattern(search)] * 4
    with db.read() as cur:
        cur.execute("SELECT COUNT(*) AS n" + where, args)
        total = cur.fetchone()["n"]
        cur.execute("SELECT bl.backup_id, IFNULL(bl.type,'Backup') AS type, bl.filename, bl.file_size, IFNULL(bl.note,'—') AS note, "
                    "IFNULL(u.full_name,'System') AS created_by, bl.created_at, bl.status, bl.filepath, bl.sha256 "
                    + where + " ORDER BY bl.created_at DESC, bl.backup_id DESC LIMIT %s OFFSET %s", (*args, limit, offset))
        return cur.fetchall(), total


# ---- dashboard ---------------------------------------------------------------------------------------------------------------------------------
BACKUP_WARN_DAYS = 7


@require_role("Admin")
def last_backup_status(actor):
    """[PANEL-AWE] When was the newest successful backup (including the automatic safety copy before a restore)? warn = none, or older than 7 days."""
    with db.read() as cur:
        cur.execute("SELECT NOW() AS now")
        now = cur.fetchone()["now"]
        cur.execute("SELECT created_at, filename FROM backup_logs WHERE IFNULL(type, 'Backup') = 'Backup' AND status = 'Success' "
                    "ORDER BY created_at DESC, backup_id DESC LIMIT 1")
        row = cur.fetchone()
    if not row or row["created_at"] is None:
        return {"last": None, "filename": None, "age_days": None, "warn": True, "warn_after_days": BACKUP_WARN_DAYS}
    age = max(0.0, (now - row["created_at"]).total_seconds() / 86400.0)
    return {"last": row["created_at"], "filename": row["filename"], "age_days": round(age, 1), "warn": age > BACKUP_WARN_DAYS,
            "warn_after_days": BACKUP_WARN_DAYS}
