"""[PANEL-AWE] Hash-chain arithmetic for the audit log, with no application dependencies (the migration uses it too).

    row_hash = SHA-256( prev_hash, log_id, user_id, action_type, module, details, timestamp, session_id )

The fields are joined with the ASCII "unit separator" (character 31) so "ab"+"c" can never be confused with "a"+"bc". The timestamp is
written as ``YYYY-MM-DDTHH:MM:SS`` in UTC. ``sp_log_action`` in db/triggers.sql computes the very same string in SQL,
so a row written by the stored procedure verifies here, and the other way round.
"""
import hashlib

GENESIS = "0" * 64
SEP = "\x1f"
TS_FORMAT = "%Y-%m-%dT%H:%M:%S"
# The timestamp is hashed as UTC wall-clock text computed by MySQL from the stored instant, so the hash does not depend on the time zone
# of the PC that wrote or checks the row.
TS_UTC_SQL = "CAST(DATE_ADD('1970-01-01 00:00:00', INTERVAL UNIX_TIMESTAMP(`timestamp`) SECOND) AS DATETIME)"
COLUMNS = f"log_id, user_id, action_type, module, details, {TS_UTC_SQL} AS ts_utc, session_id, prev_hash, row_hash"


def row_digest(prev_hash, log_id, user_id, action_type, module, details, timestamp, session_id):
    parts = [prev_hash or GENESIS, str(log_id), "" if user_id is None else str(user_id), action_type or "", module or "", details or "",
             timestamp.strftime(TS_FORMAT) if hasattr(timestamp, "strftime") else str(timestamp or "").replace(" ", "T"), session_id or ""]
    return hashlib.sha256(SEP.join(parts).encode("utf-8")).hexdigest()


def _digest_of(row, prev):
    return row_digest(prev, row["log_id"], row["user_id"], row["action_type"], row["module"], row["details"], row["ts_utc"], row["session_id"])


def backfill(cur, batch=2000):
    """Chain every row that has no hash yet, in log_id order, continuing after the last hashed row. Idempotent.
    ``cur``: dictionary cursor inside a transaction the caller commits. Returns the number of rows chained."""
    cur.execute("SELECT head_hash, last_log_id FROM audit_chain_head WHERE id = 1 FOR UPDATE")
    head = cur.fetchone()
    if head is None:
        cur.execute("INSERT INTO audit_chain_head (id, head_hash, last_log_id) VALUES (1, %s, 0)", (GENESIS,))
        head = {"head_hash": GENESIS, "last_log_id": 0}
    cur.execute("SELECT log_id, row_hash FROM (SELECT log_id, row_hash FROM system_logs WHERE row_hash IS NOT NULL "
                "UNION ALL SELECT log_id, row_hash FROM system_logs_archive WHERE row_hash IS NOT NULL) x ORDER BY log_id DESC LIMIT 1")
    last = cur.fetchone()
    prev, last_id = (last["row_hash"], last["log_id"]) if last else (GENESIS, 0)
    done = 0
    while True:
        cur.execute(f"SELECT {COLUMNS} FROM system_logs WHERE row_hash IS NULL AND log_id > %s ORDER BY log_id LIMIT %s", (last_id, batch))
        rows = cur.fetchall()
        if not rows:
            break
        for r in rows:
            digest = _digest_of(r, prev)
            cur.execute("UPDATE system_logs SET prev_hash = %s, row_hash = %s WHERE log_id = %s AND row_hash IS NULL", (prev, digest, r["log_id"]))
            prev, last_id, done = digest, r["log_id"], done + 1
    if done:
        cur.execute("UPDATE audit_chain_head SET head_hash = %s, last_log_id = %s WHERE id = 1", (prev, last_id))
    return done


def verify(cur, chunk=5000):
    """Recompute the whole chain (archive first, then the live table).

    Returns {"intact", "checked", "head_hash", "last_log_id", "first_broken_log_id", "reason"}. The first broken row is the first one whose
    stored hash, link or content disagrees with the recomputation; removing the newest rows is caught by the stored chain head."""
    state = {"prev": GENESIS, "checked": 0, "last": 0}
    out = {"intact": True, "checked": 0, "head_hash": None, "last_log_id": 0, "first_broken_log_id": None, "reason": ""}

    def broken(log_id, why):
        out.update(intact=False, first_broken_log_id=log_id, reason=why, checked=state["checked"], head_hash=state["prev"], last_log_id=state["last"])
        return out

    def scan(table, after_id):
        """Check rows of ``table`` newer than ``after_id``; returns a failure dict or None."""
        cursor_id = after_id
        while True:
            cur.execute(f"SELECT {COLUMNS} FROM {table} WHERE log_id > %s ORDER BY log_id LIMIT %s", (cursor_id, chunk))
            rows = cur.fetchall()
            if not rows:
                return None
            for r in rows:
                cursor_id = r["log_id"]
                if r["row_hash"] is None:
                    return broken(r["log_id"], "This entry has no hash: it was added outside the application.")
                if r["prev_hash"] != state["prev"]:
                    return broken(r["log_id"], "The entry before this one was removed or changed.")
                if _digest_of(r, state["prev"]) != r["row_hash"]:
                    return broken(r["log_id"], "This entry's content does not match its hash: it was edited.")
                state.update(prev=r["row_hash"], last=r["log_id"], checked=state["checked"] + 1)

    failure = scan("system_logs_archive", 0) or scan("system_logs", state["last"])    # a live row that is also archived (interrupted move) is skipped
    if failure:
        return failure
    for _ in range(4):                       # rows may be appended while we read; the head is compared only once we have caught up
        cur.execute("SELECT head_hash, last_log_id FROM audit_chain_head WHERE id = 1")
        head = cur.fetchone()
        if head is None or head["head_hash"] == state["prev"]:
            break
        before = state["last"]
        failure = scan("system_logs", state["last"])
        if failure:
            return failure
        if state["last"] == before:          # nothing new and still different: entries at the end were removed
            return broken(state["last"] + 1 if state["checked"] else head["last_log_id"],
                          "Entries at the end of the log were removed (the stored chain head does not match).")
    out.update(checked=state["checked"], head_hash=state["prev"], last_log_id=state["last"])
    return out
