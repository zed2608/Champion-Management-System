"""[RBAC] Server-side role checks for EVERY service function.

1. A sweep proves no service function can be added without a role guard.
2. A matrix calls each guarded function as Admin / Staff / Worker / archived Admin / unknown user and checks that the decorator,
   which re-reads the role from MySQL, refuses before any argument is even looked at.
"""
import importlib
import inspect
import pkgutil

import pytest

import services
from services.errors import PermissionDenied
from services.security import ALL_ROLES

# Read-only helpers that take no actor and expose no private data (used by the screens for "similar name" prompts).
UNGUARDED_OK = {("inventory_service", "find_similar_names"), ("project_service", "find_similar_names"),
                ("user_service", "find_similar_names"),
                # pre-login entry points: no session exists yet, so there is no role to check (they validate their own input)
                ("auth_service", "login"), ("auth_service", "request_username_help"), ("auth_service", "request_password_reset")}


def service_functions():
    for info in pkgutil.iter_modules(services.__path__):
        if not info.name.endswith("_service"):
            continue
        mod = importlib.import_module(f"services.{info.name}")
        for name, fn in inspect.getmembers(mod, inspect.isfunction):
            if fn.__module__ == mod.__name__ and not name.startswith("_"):
                yield info.name, name, fn


def test_every_public_service_function_is_role_guarded():
    seen = list(service_functions())
    assert len(seen) >= 20, "the sweep found too few service functions; is the package layout unchanged?"
    unguarded = [f"{m}.{n}" for m, n, fn in seen if not hasattr(fn, "required_roles") and (m, n) not in UNGUARDED_OK]
    assert not unguarded, f"service functions without @require_role: {unguarded}"


def test_no_service_ever_allows_the_worker_role():
    for m, n, fn in service_functions():
        roles = getattr(fn, "required_roles", ())
        assert "Worker" not in roles, f"{m}.{n} allows Worker, but Workers have no session at all"
        assert set(roles) <= set(ALL_ROLES), f"{m}.{n}: unknown role in {roles}"


@pytest.mark.db
def test_matrix_every_guarded_function_enforces_its_roles_in_mysql(svc):
    d = svc
    ids = {}
    for key, eid, role, status in [("admin", "ADM-2026-001", "Admin", "Active"), ("staff", "STF-2026-001", "Staff", "Active"),
                                   ("worker", "WKR-2026-001", "Worker", "Active"), ("old_admin", "ADM-2025-009", "Admin", "Archived"),
                                   ("locked_staff", "STF-2025-008", "Staff", "Locked")]:
        with d.transaction() as cur:
            cur.execute("INSERT INTO `user` (employee_id, full_name, role, status) VALUES (%s,%s,%s,%s)", (eid, key, role, status))
            ids[key] = cur.lastrowid
    actors = {"admin": "Admin", "staff": "Staff", "worker": "Worker", "old_admin": "Admin", "locked_staff": "Staff"}

    checked = 0
    for m, n, fn in service_functions():
        roles = getattr(fn, "required_roles", None)
        if roles is None:
            continue
        nparams = len([p for p in inspect.signature(fn.__wrapped__).parameters.values()
                       if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) and p.default is p.empty]) - 1
        args = [None] * nparams                                 # the guard must refuse BEFORE arguments are used
        for key, role in actors.items():
            allowed = role in roles and key not in ("old_admin", "locked_staff")
            if allowed:
                continue                                        # allowed callers are exercised by the behaviour tests
            with pytest.raises(PermissionDenied):
                fn({"user_id": ids[key], "role": "Admin"}, *args)   # a session dict that CLAIMS Admin must not matter
            checked += 1
        for bogus in ({}, None, {"user_id": 999999}, {"user_id": ids["worker"]}):
            with pytest.raises(PermissionDenied):
                fn(bogus, *args)
            checked += 1
    assert checked >= 100, checked
    with d.read() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM system_logs WHERE action_type = 'Denied'")
        assert cur.fetchone()["n"] >= 50                        # refusals are written to the audit log
