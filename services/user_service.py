"""Role Management: register, edit, archive and restore accounts. Admin only.

[RBAC] Workers (field personnel) have NO login: their ``password_hash`` is NULL (the old system stored the bcrypt hash of one shared
constant for every Worker). Admin and Staff need a strong password, hashed with bcrypt after the 72-byte check; passwords are never
stripped.
[CONCURRENCY] Employee ids come from ``id_sequences`` read ``FOR UPDATE``, so two Admins registering at the same moment cannot get the
same id, and sequence numbers above 999 work (ADM-2026-1000).
Duplicate full names are WARNED, not blocked (real employees share names); the e-mail address stays unique.
Safety rule (new): the last Active Admin can neither be archived nor demoted, and you cannot archive yourself, so the system can never
lock everyone out of administration.
"""
import difflib

from db import db
from services import validators as v
from services.errors import Conflict, NotFound, ServiceError
from services.security import require_role

ROLES = ("Admin", "Staff", "Worker")
PREFIX = {"Admin": "ADM", "Staff": "STF", "Worker": "WKR"}


class DuplicateName(Conflict):
    """An active user already has this full name. Not an error by itself: the screen asks, then retries with allow_duplicate_name=True."""

    def __init__(self, name, count):
        self.name, self.count = name, count
        super().__init__(f"{count} active user(s) are already named '{name}'. Register another person with the same name?")


def find_similar_names(name, exclude_user_id=None):
    """Read-only helper for the "Similar name detected" prompt: (exact_match_count, similar_names[:3]) among non-archived users."""
    name = v.clean_text(name, max_len=v.MAX_NAME, field="Full Name")
    with db.read() as cur:
        cur.execute("SELECT full_name FROM `user` WHERE status <> 'Archived' AND user_id <> %s", (exclude_user_id or 0,))
        existing = [r["full_name"] for r in cur.fetchall() if r["full_name"]]
    exact = sum(1 for n in existing if n.lower() == name.lower())
    similar = [n for n in existing if n.lower() != name.lower()
               and difflib.SequenceMatcher(None, name.lower(), n.lower()).ratio() > 0.85]
    return exact, similar[:3]


def _check_email(cur, email, role, exclude_user_id=None):
    email = v.validate_email(email, required=(role != "Worker"))
    if email:
        cur.execute("SELECT 1 AS x FROM `user` WHERE email = %s AND user_id <> %s", (email, exclude_user_id or 0))
        if cur.fetchone():
            raise Conflict("A user with this email address already exists.")
    return email


def _active_admins(cur, excluding=None):
    """How many OTHER active Admins exist. The Admin rows are locked first (ascending id), so two Admins archiving or demoting each
    other at the same moment are serialised: the second sees the first's change and is refused instead of leaving no Admin."""
    cur.execute("SELECT user_id FROM `user` WHERE role = 'Admin' AND status = 'Active' ORDER BY user_id FOR UPDATE")
    return sum(1 for r in cur.fetchall() if r["user_id"] != (excluding or 0))


def _next_employee_id(cur, role):
    prefix = PREFIX[role]
    cur.execute("SELECT YEAR(NOW()) AS y")
    year = cur.fetchone()["y"]
    cur.execute("INSERT INTO id_sequences (prefix, yr, last_seq) VALUES (%s, %s, 0) ON DUPLICATE KEY UPDATE last_seq = last_seq", (prefix, year))
    cur.execute("SELECT last_seq FROM id_sequences WHERE prefix = %s AND yr = %s FOR UPDATE", (prefix, year))   # serialises Admins
    last = cur.fetchone()["last_seq"]
    # never go below an id the old code (MAX+1) already handed out
    cur.execute("SELECT employee_id FROM `user` WHERE employee_id LIKE %s", (f"{prefix}-{year}-%",))
    for r in cur.fetchall():
        tail = (r["employee_id"] or "").rsplit("-", 1)[-1]
        if tail.isdigit():
            last = max(last, int(tail))
    nxt = last + 1
    cur.execute("UPDATE id_sequences SET last_seq = %s WHERE prefix = %s AND yr = %s", (nxt, prefix, year))
    return f"{prefix}-{year}-{nxt:03d}"


@require_role("Admin")
def register_user(actor, *, name, email, role, password="", confirm_password="", allow_duplicate_name=False) -> dict:
    if role not in ROLES:
        raise v.ValidationError("Please choose a role.")
    name = v.clean_text(name, max_len=v.MAX_NAME, field="Full Name")
    pw_hash = None
    if role != "Worker":                                   # Workers have no login: no password at all
        if password != confirm_password:
            raise v.ValidationError("Passwords do not match.")
        pw_hash = v.hash_password(password)

    def work(cur):
        em = _check_email(cur, email, role)
        cur.execute("SELECT COUNT(*) AS n FROM `user` WHERE status <> 'Archived' AND full_name = %s", (name,))
        same = cur.fetchone()["n"]
        if same and not allow_duplicate_name:
            raise DuplicateName(name, same)
        emp = _next_employee_id(cur, role)
        cur.execute("INSERT INTO `user` (employee_id, full_name, email, role, password_hash, status) VALUES (%s, %s, %s, %s, %s, 'Active')",
                    (emp, name, em, role, pw_hash))
        return {"user_id": cur.lastrowid, "employee_id": emp, "name": name, "role": role}

    return db.run_in_transaction(work)


@require_role("Admin")
def update_user(actor, user_id, *, name, email, role, new_password="", confirm_password="", allow_duplicate_name=False) -> dict:
    """Edit an account. Saving also clears a lockout / reset request (that is how an Admin unlocks someone)."""
    if role not in ROLES:
        raise v.ValidationError("Please choose a role.")
    name = v.clean_text(name, max_len=v.MAX_NAME, field="Full Name")
    new_hash = None
    if new_password or confirm_password:
        if role == "Worker":
            raise v.ValidationError("Workers have no login, so they have no password.")
        if new_password != confirm_password:
            raise v.ValidationError("Passwords do not match.")
        new_hash = v.hash_password(new_password)

    def work(cur):
        cur.execute("SELECT * FROM `user` WHERE user_id = %s FOR UPDATE", (user_id,))
        u = cur.fetchone()
        if not u:
            raise NotFound("User not found.")
        if u["status"] == "Archived":
            raise Conflict("This account is archived. Restore it from Maintenance first.")
        em = _check_email(cur, email, role, exclude_user_id=user_id)
        cur.execute("SELECT COUNT(*) AS n FROM `user` WHERE status <> 'Archived' AND full_name = %s AND user_id <> %s", (name, user_id))
        same = cur.fetchone()["n"]
        if same and name.lower() != (u["full_name"] or "").lower() and not allow_duplicate_name:
            raise DuplicateName(name, same)
        if u["role"] == "Admin" and role != "Admin" and _active_admins(cur, excluding=user_id) == 0:
            raise Conflict("This is the last active Admin. Promote another Admin first.")
        if role == "Worker":
            pw = None                                          # no login, no password hash
        elif new_hash:
            pw = new_hash
        elif u["role"] == "Worker" or not u["password_hash"]:
            raise v.ValidationError("Assigning a login role requires setting a password.")
        else:
            pw = u["password_hash"]
        cur.execute("""UPDATE `user` SET full_name = %s, email = %s, role = %s, password_hash = %s,
                              status = 'Active', failed_attempts = 0, reset_requested = 0 WHERE user_id = %s""",
                    (name, em, role, pw, user_id))
        return {"user_id": user_id, "employee_id": u["employee_id"], "name": name, "role": role,
                "unlocked": u["status"] == "Locked" or bool(u["reset_requested"])}

    return db.run_in_transaction(work)


@require_role("Admin")
def archive_user(actor, user_id) -> dict:
    def work(cur):
        cur.execute("SELECT * FROM `user` WHERE user_id = %s FOR UPDATE", (user_id,))
        u = cur.fetchone()
        if not u:
            raise NotFound("User not found.")
        if u["status"] == "Archived":
            raise Conflict("This account is already archived.")
        if u["user_id"] == actor["user_id"]:
            raise Conflict("You cannot archive your own account.")
        if u["role"] == "Admin" and u["status"] == "Active" and _active_admins(cur, excluding=user_id) == 0:
            raise Conflict("This is the last active Admin and cannot be archived.")
        cur.execute("UPDATE `user` SET status = 'Archived', archived_at = NOW() WHERE user_id = %s", (user_id,))
        return {"user_id": user_id, "name": u["full_name"], "employee_id": u["employee_id"]}

    return db.run_in_transaction(work)


@require_role("Admin")
def restore_user(actor, user_id) -> dict:
    def work(cur):
        cur.execute("SELECT * FROM `user` WHERE user_id = %s FOR UPDATE", (user_id,))
        u = cur.fetchone()
        if not u:
            raise NotFound("User not found.")
        if u["status"] != "Archived":
            raise Conflict("This account is not archived.")
        cur.execute("UPDATE `user` SET status = 'Active', archived_at = NULL, failed_attempts = 0 WHERE user_id = %s", (user_id,))
        return {"user_id": user_id, "name": u["full_name"], "employee_id": u["employee_id"], "role": u["role"]}

    return db.run_in_transaction(work)


# ---- own profile (Admin and Staff). The target is ALWAYS the caller's own row: there is no user-id parameter to tamper with. ----
@require_role("Admin", "Staff")
def update_profile(actor, *, name, email, allow_duplicate_name=False) -> dict:
    name = v.clean_text(name, max_len=v.MAX_NAME, field="Full Name")

    def work(cur):
        em = _check_email(cur, email, actor["role"], exclude_user_id=actor["user_id"])
        cur.execute("SELECT full_name FROM `user` WHERE user_id = %s FOR UPDATE", (actor["user_id"],))
        current = cur.fetchone()["full_name"] or ""
        cur.execute("SELECT COUNT(*) AS n FROM `user` WHERE status <> 'Archived' AND full_name = %s AND user_id <> %s", (name, actor["user_id"]))
        same = cur.fetchone()["n"]
        if same and name.lower() != current.lower() and not allow_duplicate_name:
            raise DuplicateName(name, same)
        cur.execute("UPDATE `user` SET full_name = %s, email = %s WHERE user_id = %s", (name, em, actor["user_id"]))
        return {"full_name": name, "email": em}

    return db.run_in_transaction(work)


@require_role("Admin", "Staff")
def change_password(actor, current_password, new_password, confirm_password) -> None:
    if new_password != confirm_password:
        raise v.ValidationError("New passwords do not match.")
    new_hash = v.hash_password(new_password)                      # strength + 72-byte limit, passwords are never stripped

    def work(cur):
        cur.execute("SELECT password_hash FROM `user` WHERE user_id = %s FOR UPDATE", (actor["user_id"],))
        row = cur.fetchone()
        if not v.verify_password(current_password, row["password_hash"]):
            raise ServiceError("Incorrect current password.")
        cur.execute("UPDATE `user` SET password_hash = %s WHERE user_id = %s", (new_hash, actor["user_id"]))

    db.run_in_transaction(work)
