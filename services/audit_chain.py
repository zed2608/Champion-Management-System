"""[PANEL-AWE] Tamper-evident audit log: writing, archiving and verifying the hash chain.

* ``record`` is the ONLY writer. It calls the stored procedure ``sp_log_action`` (db/triggers.sql), which locks the chain head, appends the
  row with the previous row's hash and its own hash, and moves the head. Two terminals therefore take turns and cannot fork the chain.
* Old rows are MOVED to ``system_logs_archive`` (``archive_old``), never deleted; the old "keep only 10,000 rows" pruning is gone.
* ``verify_chain`` (Admin) recomputes every hash and reports "intact" or the first broken entry.
"""
import os

from mysql.connector import errors as mysql_errors

from db import audit_core, db
from services.errors import get_logger
from services.security import require_role

ARCHIVE_KEEP_LIVE = int(os.environ.get("CHAMPION_AUDIT_KEEP_LIVE", "20000") or 20000)
ARCHIVE_EVERY = 200                     # check for rows to archive once per this many writes
_writes = 0


def record(user_id, action_type, module, details, session_id=None):
    """Append one audit row. Never raises: a failing log must not break the action being logged (it is reported to logs\\app.log)."""
    global _writes
    args = (user_id, str(action_type or "")[:100], str(module or "")[:100], None if details is None else str(details), (session_id or None) and str(session_id)[:36])
    try:
        try:
            with db.transaction() as cur:
                cur.execute("CALL sp_log_action(%s,%s,%s,%s,%s)", args)
        except mysql_errors.Error as e:
            if getattr(e, "errno", None) != 1305:                        # 1305 = procedure does not exist (database not upgraded yet)
                raise
            with db.transaction() as cur:                                # old schema: plain insert; the upgrade will chain it later
                cur.execute("INSERT INTO system_logs (user_id, action_type, module, details) VALUES (%s,%s,%s,%s)", args[:4])
        _writes += 1
        if _writes % ARCHIVE_EVERY == 0:
            archive_old()
    except Exception:
        get_logger().exception("Audit log write failed")


def archive_old(keep=None):
    """Move everything older than the newest ``keep`` live rows into the archive (at most 5000 per call)."""
    try:
        with db.transaction() as cur:
            cur.execute("CALL sp_archive_audit(%s)", (int(keep if keep is not None else ARCHIVE_KEEP_LIVE),))
    except Exception:
        get_logger().warning("Audit archiving skipped", exc_info=True)


@require_role("Admin")
def verify_chain(actor):
    """Recompute the whole chain. {"intact", "checked", "head_hash", "last_log_id", "first_broken_log_id", "reason"}."""
    with db.read() as cur:
        result = audit_core.verify(cur)
    from database import log_action
    log_action(actor["user_id"], "Verified", "Tracking & Accountability",
               "Audit chain verified: " + (f"intact, {result['checked']} entries" if result["intact"]
                                           else f"BROKEN at entry #{result['first_broken_log_id']}"))
    return result


@require_role("Admin")
def chain_status(actor):
    """Cheap status for the dashboard (no recomputation): head hash, newest entry, live and archived counts."""
    with db.read() as cur:
        cur.execute("SELECT head_hash, last_log_id FROM audit_chain_head WHERE id = 1")
        head = cur.fetchone() or {"head_hash": audit_core.GENESIS, "last_log_id": 0}
        cur.execute("SELECT COUNT(*) AS n FROM system_logs")
        live = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM system_logs_archive")
        archived = cur.fetchone()["n"]
    return {"head_hash": head["head_hash"], "last_log_id": head["last_log_id"], "live": live, "archived": archived}


@require_role("Admin")
def audit_report(actor, limit=200):
    """Everything the printed audit report needs: a fresh verification plus the newest ``limit`` entries (with session ids)."""
    result = verify_chain.__wrapped__(actor)
    with db.read() as cur:
        cur.execute("SELECT sl.log_id, sl.`timestamp` AS ts, IFNULL(u.full_name, CONCAT('UID:', sl.user_id)) AS employee, sl.action_type, sl.module, "
                    "IFNULL(sl.details, '') AS details, sl.session_id FROM system_logs sl LEFT JOIN `user` u ON u.user_id = sl.user_id "
                    "ORDER BY sl.log_id DESC LIMIT %s", (max(1, min(int(limit), 2000)),))
        rows = cur.fetchall()
    return {"verify": result, "rows": rows}


def describe(result):
    """One plain sentence for a verification result (screen and PDF use the same words)."""
    if result["intact"]:
        return f"INTACT: {result['checked']} entries checked, none altered, none missing."
    return f"BROKEN at entry #{result['first_broken_log_id']}: {result['reason']}"
