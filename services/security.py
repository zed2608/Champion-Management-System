"""Server-side role checks.

[RBAC] The sidebar hides modules, but a hidden button is not a permission. Every privileged service function is wrapped in
``@require_role(...)``, which on EVERY call re-reads the caller's role and status from MySQL. A stale or tampered in-memory
``user_info`` (role edited, account archived or locked after login) therefore cannot escalate, and the decorated function
receives the freshly loaded actor, not the caller's copy. Refusals are written to the audit log.

[UNHAPPY-PATH] The same wrapper normalises ids: a database-id argument (tool_id, project_id, user_id, issue_id, borrower_id, ...) that
arrives as text from a screen ("1") becomes an int (and junk becomes a ValidationError), so a service never has to guess the type.

    @require_role("Admin")
    def archive_tool(actor, tool_id): ...        # actor is {"user_id", "employee_id", "full_name", "role", "status"}
"""
import functools
import inspect

from db import db
from services.errors import PermissionDenied
from services.validators import parse_id

ALL_ROLES = ("Admin", "Staff", "Worker")

# Parameters that are DATABASE ids. (tag_id and employee_id are NOT: they are text like 'CAL-001' / 'ADM-2026-001'.)
DB_ID_PARAMS = frozenset({"tool_id", "project_id", "user_id", "issue_id", "borrower_id", "transaction_id", "req_id"})


def load_actor(user_id):
    """Fresh row for the session user, or None."""
    if not user_id:
        return None
    with db.read() as cur:
        cur.execute("SELECT user_id, employee_id, full_name, role, status FROM `user` WHERE user_id = %s", (user_id,))
        return cur.fetchone()


def _audit_denial(user_id, fn_name, why):
    try:
        from database import log_action                  # imported late: database.py imports db at load time
        log_action(user_id, "Denied", "Security", f"{fn_name}: {why}")
    except Exception:
        pass                                             # never let logging hide the refusal


def _normalise_ids(sig, current, args, kwargs):
    """Bind the call and convert text ids to ints (only for parameters named *_id, only when they are text)."""
    try:
        bound = sig.bind(current, *args, **kwargs)
    except TypeError:
        return args, kwargs                              # wrong arguments: let the function raise its own TypeError
    for name, value in list(bound.arguments.items()):
        if name in DB_ID_PARAMS and isinstance(value, str):
            bound.arguments[name] = parse_id(value, name.replace("_id", "").replace("_", " ").strip().capitalize() + " ID")
    new = bound.args[1:], bound.kwargs
    return new


def require_role(*roles):
    """Allow the call only if the CURRENT database row says the actor is Active and has one of ``roles``.
    Workers have no session at all (they are identified by QR badge only), so they are never allowed here."""
    allowed = set(roles)

    def decorator(fn):
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(actor, *args, **kwargs):
            uid = actor.get("user_id") if isinstance(actor, dict) else None
            current = load_actor(uid)
            if current is None:
                _audit_denial(uid, fn.__name__, "unknown user")
                raise PermissionDenied("Your session is no longer valid. Please log in again.")
            if current["status"] != "Active":
                _audit_denial(uid, fn.__name__, f"account is {current['status']}")
                raise PermissionDenied("Your account is not active. Please contact an administrator.")
            if current["role"] not in allowed:
                _audit_denial(uid, fn.__name__, f"role {current['role']} not in {sorted(allowed)}")
                raise PermissionDenied("You do not have permission to do that.")
            args, kwargs = _normalise_ids(sig, current, args, kwargs)
            return fn(current, *args, **kwargs)
        wrapper.required_roles = tuple(roles)            # lets a test assert that every service function is guarded
        return wrapper
    return decorator
