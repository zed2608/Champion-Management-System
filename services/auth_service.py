"""Login, lockout and account-recovery requests.

These functions run BEFORE any session exists, so they are the only service functions without ``@require_role``; they are
listed as deliberate exceptions in tests/test_rbac_matrix.py. Everything they accept is validated here.

[RBAC] Only an Active, non-Worker account can log in. Locked, Archived and Inactive accounts are refused (the old check only looked
for 'Locked'). Passwords are never stripped and over-long input (bcrypt's 72-byte limit) is simply "invalid", never a crash.
[CONCURRENCY] The user row is locked while attempts are counted, so two terminals guessing at once cannot get extra tries; the failed
attempt is committed BEFORE the refusal is raised (a rolled-back counter would defeat the 3-strike lock).
[UNHAPPY-PATH] "Forgot username / password" answer identically whether or not the account exists, and never reveal an employee id.
"""
from dataclasses import dataclass

from db import db
from services import validators as v
from services.errors import ServiceError

MAX_FAILED_ATTEMPTS = 3
GENERIC_RECOVERY_REPLY = "If that account exists, an administrator has been notified and will contact you."


class AuthError(ServiceError):
    def __init__(self, message, *, locked=False):
        self.locked = locked
        super().__init__(message)


@dataclass
class _Outcome:
    user: dict = None
    error: AuthError = None


def _public(user):
    """The session dict: everything the app needs, never the hash."""
    return {k: v_ for k, v_ in user.items() if k != "password_hash"}


def login(employee_id, password) -> dict:
    emp = (employee_id or "").strip() if isinstance(employee_id, str) else ""
    pw = password if isinstance(password, str) else ""             # NOT stripped: a trailing space is part of the secret
    if not emp or not pw:
        raise AuthError("Please fill in all fields.")
    emp = v.clean_text(emp, max_len=50, field="Employee ID", required=False)

    def work(cur):
        cur.execute("SELECT * FROM `user` WHERE employee_id = %s FOR UPDATE", (emp,))
        u = cur.fetchone()
        if not u:
            return _Outcome(error=AuthError("Invalid Credentials."))
        if u["role"] == "Worker":
            return _Outcome(error=AuthError("Access Denied: Field Workers do not have system login privileges."))
        if u["status"] == "Locked":
            return _Outcome(error=AuthError("Account Locked. Please contact Admin.", locked=True))
        if u["status"] != "Active":
            return _Outcome(error=AuthError("This account is not active. Please contact an administrator."))
        if v.verify_password(pw, u["password_hash"]):
            if u["failed_attempts"]:
                cur.execute("UPDATE `user` SET failed_attempts = 0 WHERE user_id = %s", (u["user_id"],))
            return _Outcome(user=_public(u))
        failed = (u["failed_attempts"] or 0) + 1
        if failed >= MAX_FAILED_ATTEMPTS:
            cur.execute("UPDATE `user` SET failed_attempts = %s, status = 'Locked' WHERE user_id = %s", (failed, u["user_id"]))
            return _Outcome(error=AuthError("Account Locked: Maximum attempts reached. Please request a password reset.", locked=True))
        cur.execute("UPDATE `user` SET failed_attempts = %s WHERE user_id = %s", (failed, u["user_id"]))
        return _Outcome(error=AuthError(f"Invalid Credentials. {MAX_FAILED_ATTEMPTS - failed} attempt(s) left."))

    out = db.run_in_transaction(work)                              # committed, THEN refuse
    if out.error:
        raise out.error
    return out.user


def request_username_help(email) -> str:
    """"Forgot username": never shows the id. If the e-mail belongs to an account, an Admin gets a support ticket (Help >
    Support Tickets) and contacts the person. The reply is identical either way. Repeat requests within an hour add nothing."""
    try:
        em = v.validate_email(email, required=True)
    except v.ValidationError:
        return GENERIC_RECOVERY_REPLY                              # a malformed address looks the same as an unknown one

    def work(cur):
        cur.execute("SELECT user_id, full_name, employee_id, status FROM `user` WHERE email = %s", (em,))
        u = cur.fetchone()
        if not u or u["status"] == "Archived":
            return
        cur.execute("SELECT 1 AS x FROM help_tickets WHERE user_id = %s AND subject = 'Username request' AND status = 'Open' "
                    "AND created_at > NOW() - INTERVAL 1 HOUR", (u["user_id"],))
        if cur.fetchone():
            return
        cur.execute("INSERT INTO help_tickets (user_id, subject, message) VALUES (%s, 'Username request', %s)",
                    (u["user_id"], f"{u['full_name']} ({u['employee_id']}) asked for their username. Please contact them at their "
                                   f"registered email address."))

    db.run_in_transaction(work)          # a database failure is NOT hidden: the person must know nothing was recorded
    return GENERIC_RECOVERY_REPLY


def request_password_reset(employee_id) -> str:
    """"Forgot password": flags the account for an Admin (dashboard counter, Role Management). Identical reply either way."""
    emp = v.clean_text(employee_id, max_len=50, field="Employee ID", required=False) if isinstance(employee_id, str) else ""
    if not emp:
        return GENERIC_RECOVERY_REPLY

    def work(cur):
        cur.execute("SELECT user_id, full_name, status FROM `user` WHERE employee_id = %s FOR UPDATE", (emp,))
        u = cur.fetchone()
        if not u or u["status"] == "Archived":
            return None
        cur.execute("UPDATE `user` SET reset_requested = 1 WHERE user_id = %s", (u["user_id"],))
        return u

    u = db.run_in_transaction(work)      # a database failure is NOT hidden (only whether the account exists is)
    if u:
        try:
            from database import log_action
            log_action(u["user_id"], "Flagged", "Authentication", f"'{u['full_name']}' requested a password reset.")
        except Exception:
            pass                         # the flag is already saved; a missing audit line must not turn success into an error
    return GENERIC_RECOVERY_REPLY
