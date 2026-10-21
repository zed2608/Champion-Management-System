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
                ("report_service", "classify_abc"),          # pure ranking arithmetic: takes rows in, returns rows out, no data access
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


def find_unguarded(seen):
    return [f"{m}.{n}" for m, n, fn in seen if not hasattr(fn, "required_roles") and (m, n) not in UNGUARDED_OK]


def test_every_public_service_function_is_role_guarded():
    seen = list(service_functions())
    assert len(seen) >= 20, "the sweep found too few service functions; is the package layout unchanged?"
    unguarded = find_unguarded(seen)
    assert not unguarded, f"service functions without @require_role: {unguarded}"


# [PANEL-AWE] The Phase 4 modules are not named *_service, so the sweep above never saw them. Everything public in them must be guarded,
# except pure arithmetic/text helpers and the two internal writers called from inside other services (listed by name on purpose:
# a NEW function has to be guarded or consciously added here).
PHASE4_MODULES = ("audit_chain", "wear_forecast", "anomaly", "savings")
PHASE4_NOT_GUARDED_OK = {
    ("audit_chain", "record"), ("audit_chain", "archive_old"), ("audit_chain", "describe"),
    ("anomaly", "log_attempt"), ("anomaly", "peso"), ("anomaly", "iqr_fence"), ("anomaly", "damage_outliers"),
    ("anomaly", "blocked_demand"), ("anomaly", "overdue_clusters"), ("anomaly", "recommendations"), ("anomaly", "pdf_sections"),
    ("wear_forecast", "compute_forecast"), ("wear_forecast", "summary_line"), ("wear_forecast", "pdf_table"),
    ("savings", "month_key"), ("savings", "last_months"), ("savings", "kpi"), ("savings", "describe"),
}


def phase4_functions():
    for name in PHASE4_MODULES:
        mod = importlib.import_module(f"services.{name}")
        for fn_name, fn in inspect.getmembers(mod, inspect.isfunction):
            if fn.__module__ == mod.__name__ and not fn_name.startswith("_"):
                yield name, fn_name, fn


def test_phase4_modules_are_role_guarded_too():
    seen = list(phase4_functions())
    assert len(seen) >= 25, "the Phase 4 sweep found too few functions"
    bad = [f"{m}.{n}" for m, n, fn in seen if not hasattr(fn, "required_roles") and (m, n) not in PHASE4_NOT_GUARDED_OK]
    assert not bad, f"Phase 4 functions without @require_role: {bad}"
    for m, n, fn in seen:
        assert set(getattr(fn, "required_roles", ())) <= {"Admin"}, f"{m}.{n}: Phase 4 insight functions are Admin only"


def test_the_sweep_really_catches_an_unguarded_function():
    """The sweep above must not be able to pass vacuously: feed it a new, unguarded function and it has to be reported."""
    from services.security import require_role

    def forgotten_report(actor):
        return "anyone could call this"

    @require_role("Admin")
    def guarded_report(actor):
        return "only Admin"

    seen = list(service_functions()) + [("anomaly_service", "forgotten_report", forgotten_report),
                                        ("anomaly_service", "guarded_report", guarded_report)]
    assert find_unguarded(seen) == ["anomaly_service.forgotten_report"]


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
