"""[RBAC][CONCURRENCY][UNHAPPY-PATH] Login, lockout, recovery requests and Role Management through the service layer."""
import threading

import pytest

from services import auth_service as auth
from services import user_service as us
from services import validators as v
from services.errors import Conflict, NotFound, PermissionDenied
from services.validators import hash_password

pytestmark = pytest.mark.db
PW = "Str0ng!Pass"


def run(db, sql, params=()):
    with db.transaction() as cur:
        cur.execute(sql, params)
        return cur.lastrowid


def rows(db, sql, params=()):
    with db.read() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


@pytest.fixture
def w(svc):
    d = svc
    u = {}
    for key, eid, name, role, email in [("admin", "ADM-2026-001", "Admin One", "Admin", "admin@x.com"),
                                        ("staff", "STF-2026-001", "Stacy Staff", "Staff", "stacy@x.com"),
                                        ("worker", "WKR-2026-001", "Wally Worker", "Worker", None)]:
        u[key] = run(d, "INSERT INTO `user` (employee_id, full_name, email, role, password_hash, status) VALUES (%s,%s,%s,%s,%s,'Active')",
                     (eid, name, email, role, None if role == "Worker" else hash_password(PW)))
    return d, u, {"user_id": u["admin"]}, {"user_id": u["staff"]}


# ---- login ----------------------------------------------------------------------------------------------------
def test_successful_login_returns_a_session_without_the_hash_and_resets_attempts(w):
    d, u, admin, staff = w
    run(d, "UPDATE `user` SET failed_attempts = 2 WHERE user_id=%s", (u["staff"],))
    s = auth.login("stf-2026-001", PW)
    assert s["user_id"] == u["staff"] and s["role"] == "Staff" and "password_hash" not in s
    assert rows(d, "SELECT failed_attempts AS f FROM `user` WHERE user_id=%s", (u["staff"],))[0]["f"] == 0


def test_three_strikes_lock_the_account_and_the_counter_survives_the_refusal(w):
    d, u, admin, staff = w
    for left in (2, 1):
        with pytest.raises(auth.AuthError, match=f"{left} attempt") as e:
            auth.login("STF-2026-001", "wrong")
        assert not e.value.locked
    with pytest.raises(auth.AuthError, match="Maximum attempts") as e:
        auth.login("STF-2026-001", "wrong")
    assert e.value.locked
    r = rows(d, "SELECT status, failed_attempts FROM `user` WHERE user_id=%s", (u["staff"],))[0]
    assert (r["status"], r["failed_attempts"]) == ("Locked", 3)                      # persisted although the call raised
    with pytest.raises(auth.AuthError, match="Locked") as e:
        auth.login("STF-2026-001", PW)                                                # even the right password is refused now
    assert e.value.locked


@pytest.mark.parametrize("status", ["Archived", "Inactive"])
def test_archived_and_inactive_accounts_cannot_log_in(w, status):
    d, u, admin, staff = w
    run(d, "UPDATE `user` SET status=%s WHERE user_id=%s", (status, u["staff"]))
    with pytest.raises(auth.AuthError, match="not active"):
        auth.login("STF-2026-001", PW)                                                # the right password does not matter
    assert rows(d, "SELECT failed_attempts AS f FROM `user` WHERE user_id=%s", (u["staff"],))[0]["f"] == 0   # no strikes counted


def test_workers_cannot_log_in_and_have_no_password(w):
    d, u, admin, staff = w
    with pytest.raises(auth.AuthError, match="Field Workers"):
        auth.login("WKR-2026-001", "anything")
    assert rows(d, "SELECT password_hash AS h FROM `user` WHERE user_id=%s", (u["worker"],))[0]["h"] is None


def test_unknown_user_empty_fields_and_hostile_input_never_crash(w):
    d, u, admin, staff = w
    with pytest.raises(auth.AuthError, match="Invalid Credentials"):
        auth.login("NOBODY-1", PW)
    for emp, pw in [("", PW), ("STF-2026-001", ""), (None, None), ("STF-2026-001", None)]:
        with pytest.raises(auth.AuthError, match="fill in all fields"):
            auth.login(emp, pw)
    with pytest.raises(auth.AuthError, match="Invalid Credentials"):
        auth.login("STF-2026-001", "x" * 200)                                          # > 72 bytes: invalid, not a ValueError
    with pytest.raises(auth.AuthError):
        auth.login("STF-2026-001' OR '1'='1", PW)


def test_passwords_are_not_stripped(w):
    d, u, admin, staff = w
    with pytest.raises(auth.AuthError):
        auth.login("STF-2026-001", PW + " ")                                           # a trailing space is a different password
    assert auth.login("STF-2026-001", PW)["user_id"] == u["staff"]


def test_worker_with_a_null_hash_cannot_crash_login_after_promotion_attempt(w):
    d, u, admin, staff = w
    run(d, "UPDATE `user` SET role='Staff' WHERE user_id=%s", (u["worker"],))          # role flipped by raw SQL, hash still NULL
    with pytest.raises(auth.AuthError, match="Invalid Credentials"):
        auth.login("WKR-2026-001", "anything")


def test_concurrent_guesses_cannot_get_extra_attempts(w):
    d, u, admin, staff = w
    barrier, out = threading.Barrier(6, timeout=10), []

    def guess():
        barrier.wait()
        try:
            auth.login("STF-2026-001", "wrong")
        except auth.AuthError as e:
            out.append(e.locked)

    ts = [threading.Thread(target=guess) for _ in range(6)]
    [t.start() for t in ts]
    [t.join(30) for t in ts]
    r = rows(d, "SELECT status, failed_attempts FROM `user` WHERE user_id=%s", (u["staff"],))[0]
    assert r["status"] == "Locked" and r["failed_attempts"] == 3                      # exactly 3 strikes counted, never 6
    assert out.count(False) == 2 and out.count(True) == 4


# ---- recovery -------------------------------------------------------------------------------------------------
def test_forgot_username_answers_identically_and_never_reveals_the_id(w):
    d, u, admin, staff = w
    known = auth.request_username_help("stacy@x.com")
    unknown = auth.request_username_help("nobody@nowhere.com")
    garbage = auth.request_username_help("not an email")
    assert known == unknown == garbage == auth.GENERIC_RECOVERY_REPLY
    assert "STF-2026" not in known and "Stacy" not in known
    t = rows(d, "SELECT * FROM help_tickets")
    assert len(t) == 1 and t[0]["subject"] == "Username request" and t[0]["user_id"] == u["staff"] and "STF-2026-001" in t[0]["message"]
    auth.request_username_help("stacy@x.com")                                          # repeat within the hour adds nothing
    assert len(rows(d, "SELECT * FROM help_tickets")) == 1


def test_forgot_password_answers_identically_and_flags_only_real_accounts(w):
    d, u, admin, staff = w
    assert auth.request_password_reset("STF-2026-001") == auth.request_password_reset("NOBODY-1") == auth.GENERIC_RECOVERY_REPLY
    assert rows(d, "SELECT reset_requested AS r FROM `user` WHERE user_id=%s", (u["staff"],))[0]["r"] == 1
    assert auth.request_password_reset("") == auth.GENERIC_RECOVERY_REPLY


# ---- register -------------------------------------------------------------------------------------------------
def test_register_staff_and_worker(w):
    d, u, admin, staff = w
    s = us.register_user(admin, name="New Staff", email="NewStaff@X.com", role="Staff", password=PW, confirm_password=PW)
    assert s["employee_id"].startswith("STF-") and s["employee_id"].endswith("-002")           # STF-2026-001 already exists
    row = rows(d, "SELECT * FROM `user` WHERE user_id=%s", (s["user_id"],))[0]
    assert row["email"] == "newstaff@x.com" and row["password_hash"] and row["status"] == "Active"
    wk = us.register_user(admin, name="New Worker", email="", role="Worker")
    assert rows(d, "SELECT password_hash AS h, email FROM `user` WHERE user_id=%s", (wk["user_id"],))[0] == {"h": None, "email": None}
    wk2 = us.register_user(admin, name="Second Worker", email="", role="Worker")                # two blank e-mails must not collide
    assert wk2["employee_id"] != wk["employee_id"]


def test_register_validation_and_permissions(w):
    d, u, admin, staff = w
    for kw, text in [(dict(role="Staff", password="weak", confirm_password="weak"), "Password needs"),
                     (dict(role="Staff", password=PW, confirm_password=PW + "x"), "do not match"),
                     (dict(role="Staff", password="Aa1!" + "x" * 80, confirm_password="Aa1!" + "x" * 80), "too long"),
                     (dict(role="Staff", email="", password=PW, confirm_password=PW), "Email is required"),
                     (dict(role="Boss", password=PW, confirm_password=PW), "choose a role"),
                     (dict(role="Staff", email="stacy@x.com", password=PW, confirm_password=PW), "email address already exists")]:
        base = dict(name="Someone New", email="new@x.com")
        base.update(kw)
        with pytest.raises((v.ValidationError, Conflict), match=text):
            us.register_user(admin, **base)
    with pytest.raises(PermissionDenied):
        us.register_user(staff, name="Sneaky", email="s@x.com", role="Admin", password=PW, confirm_password=PW)
    assert rows(d, "SELECT COUNT(*) AS n FROM `user`")[0]["n"] == 3


def test_duplicate_full_names_warn_then_allow_but_email_stays_unique(w):
    d, u, admin, staff = w
    with pytest.raises(us.DuplicateName) as e:
        us.register_user(admin, name="stacy staff", email="other@x.com", role="Staff", password=PW, confirm_password=PW)
    assert e.value.count == 1
    ok = us.register_user(admin, name="stacy staff", email="other@x.com", role="Staff", password=PW, confirm_password=PW,
                          allow_duplicate_name=True)                                           # real employees share names
    assert ok["employee_id"]
    exact, similar = us.find_similar_names("Stacy Staf")
    assert exact == 0 and "Stacy Staff" in similar
    with pytest.raises(Conflict, match="email"):
        us.register_user(admin, name="Third Stacy", email="OTHER@x.com", role="Staff", password=PW, confirm_password=PW)


def test_employee_ids_are_unique_under_concurrent_registration_and_pass_999(w):
    d, u, admin, staff = w
    run(d, "INSERT INTO id_sequences (prefix, yr, last_seq) VALUES ('WKR', YEAR(NOW()), 998) ON DUPLICATE KEY UPDATE last_seq = 998")
    barrier, ids, errs = threading.Barrier(5, timeout=10), [], []

    def reg(i):
        barrier.wait()
        try:
            ids.append(us.register_user(admin, name=f"Concurrent Worker {i}", email="", role="Worker")["employee_id"])
        except Exception as e:                                                                 # noqa: BLE001
            errs.append(e)

    ts = [threading.Thread(target=reg, args=(i,)) for i in range(5)]
    [t.start() for t in ts]
    [t.join(60) for t in ts]
    assert not errs, errs
    assert len(set(ids)) == 5, ids                                                             # no two Admins got the same id
    assert sorted(int(i.rsplit("-", 1)[1]) for i in ids) == [999, 1000, 1001, 1002, 1003]       # carried on past 999


# ---- update / archive / restore --------------------------------------------------------------------------------------
def test_update_unlocks_the_account_and_keeps_the_password_when_none_is_given(w):
    d, u, admin, staff = w
    for _ in range(3):
        with pytest.raises(auth.AuthError):
            auth.login("STF-2026-001", "wrong")
    old = rows(d, "SELECT password_hash AS h FROM `user` WHERE user_id=%s", (u["staff"],))[0]["h"]
    r = us.update_user(admin, u["staff"], name="Stacy Staff", email="stacy@x.com", role="Staff")
    assert r["unlocked"] is True
    row = rows(d, "SELECT status, failed_attempts, reset_requested, password_hash FROM `user` WHERE user_id=%s", (u["staff"],))[0]
    assert (row["status"], row["failed_attempts"], row["reset_requested"], row["password_hash"]) == ("Active", 0, 0, old)
    assert auth.login("STF-2026-001", PW)["user_id"] == u["staff"]
    us.update_user(admin, u["staff"], name="Stacy Staff", email="stacy@x.com", role="Staff", new_password="N3w!Password", confirm_password="N3w!Password")
    assert auth.login("STF-2026-001", "N3w!Password")["user_id"] == u["staff"]


def test_role_changes_worker_to_login_role_needs_a_password_and_demotion_clears_it(w):
    d, u, admin, staff = w
    with pytest.raises(v.ValidationError, match="requires setting a password"):
        us.update_user(admin, u["worker"], name="Wally Worker", email="wally@x.com", role="Staff")
    us.update_user(admin, u["worker"], name="Wally Worker", email="wally@x.com", role="Staff", new_password=PW, confirm_password=PW)
    assert auth.login("WKR-2026-001", PW)["role"] == "Staff"
    us.update_user(admin, u["worker"], name="Wally Worker", email="", role="Worker")             # back to a Worker: hash removed
    assert rows(d, "SELECT password_hash AS h FROM `user` WHERE user_id=%s", (u["worker"],))[0]["h"] is None
    with pytest.raises(v.ValidationError, match="no login"):
        us.update_user(admin, u["worker"], name="Wally Worker", email="", role="Worker", new_password=PW, confirm_password=PW)


def test_the_last_active_admin_cannot_be_demoted_and_nobody_archives_themselves(w):
    d, u, admin, staff = w
    with pytest.raises(Conflict, match="last active Admin"):
        us.update_user(admin, u["admin"], name="Admin One", email="admin@x.com", role="Staff")
    with pytest.raises(Conflict, match="own account"):
        us.archive_user(admin, u["admin"])
    us.register_user(admin, name="Admin Two", email="a2@x.com", role="Admin", password=PW, confirm_password=PW)
    us.update_user(admin, u["admin"], name="Admin One", email="admin@x.com", role="Staff")      # allowed now: another Admin exists
    with pytest.raises(PermissionDenied):                                                        # and the role is re-read from MySQL
        us.register_user(admin, name="Nope", email="n@x.com", role="Staff", password=PW, confirm_password=PW)


def test_two_admins_cannot_archive_each_other_at_the_same_moment(w):
    d, u, admin, staff = w
    b_id = us.register_user(admin, name="Admin Two", email="a2@x.com", role="Admin", password=PW, confirm_password=PW)["user_id"]
    barrier, out = threading.Barrier(2, timeout=10), []

    def go(actor_id, target_id):
        barrier.wait()
        try:
            us.archive_user({"user_id": actor_id}, target_id)
            out.append("archived")
        except (Conflict, PermissionDenied):
            out.append("refused")

    ts = [threading.Thread(target=go, args=(u["admin"], b_id)), threading.Thread(target=go, args=(b_id, u["admin"]))]
    [t.start() for t in ts]
    [t.join(30) for t in ts]
    assert sorted(out) == ["archived", "refused"], out
    assert rows(d, "SELECT COUNT(*) AS n FROM `user` WHERE role='Admin' AND status='Active'")[0]["n"] == 1     # never zero


def test_archive_and_restore_cycle(w):
    d, u, admin, staff = w
    us.archive_user(admin, u["staff"])
    r = rows(d, "SELECT status, archived_at FROM `user` WHERE user_id=%s", (u["staff"],))[0]
    assert r["status"] == "Archived" and r["archived_at"] is not None
    with pytest.raises(auth.AuthError, match="not active"):
        auth.login("STF-2026-001", PW)
    with pytest.raises(Conflict, match="archived"):
        us.update_user(admin, u["staff"], name="Stacy Staff", email="stacy@x.com", role="Staff")   # an edit must not silently un-archive
    us.restore_user(admin, u["staff"])
    assert auth.login("STF-2026-001", PW)["user_id"] == u["staff"]
    with pytest.raises(Conflict, match="not archived"):
        us.restore_user(admin, u["staff"])
    with pytest.raises(NotFound):
        us.archive_user(admin, 9999)


def test_staff_cannot_run_any_user_management_function_even_by_calling_the_service_directly(w):
    d, u, admin, staff = w
    for call in (lambda: us.register_user(staff, name="x", email="x@x.com", role="Admin", password=PW, confirm_password=PW),
                 lambda: us.update_user(staff, u["staff"], name="x", email="x@x.com", role="Admin"),
                 lambda: us.archive_user(staff, u["admin"]), lambda: us.restore_user(staff, u["admin"])):
        with pytest.raises(PermissionDenied):
            call()
    assert rows(d, "SELECT role FROM `user` WHERE user_id=%s", (u["staff"],))[0]["role"] == "Staff"      # no self-promotion


# ---- own profile ----------------------------------------------------------------------------------------------
def test_profile_updates_only_the_callers_own_row_and_shared_names_are_allowed(w):
    d, u, admin, staff = w
    us.update_profile(staff, name="Stacy S.", email="stacy.new@x.com")
    assert rows(d, "SELECT full_name, email FROM `user` WHERE user_id=%s", (u["staff"],))[0] == {"full_name": "Stacy S.", "email": "stacy.new@x.com"}
    assert rows(d, "SELECT full_name FROM `user` WHERE user_id=%s", (u["admin"],))[0]["full_name"] == "Admin One"
    with pytest.raises(us.DuplicateName):
        us.update_profile(staff, name="Admin One", email="stacy.new@x.com")
    us.update_profile(staff, name="Admin One", email="stacy.new@x.com", allow_duplicate_name=True)
    with pytest.raises(Conflict, match="email"):
        us.update_profile(staff, name="Stacy S.", email="admin@x.com")


def test_change_password_checks_the_current_one_and_the_rules(w):
    d, u, admin, staff = w
    with pytest.raises(Exception, match="Incorrect current"):
        us.change_password(staff, "wrong", "N3w!Password", "N3w!Password")
    with pytest.raises(v.ValidationError, match="do not match"):
        us.change_password(staff, PW, "N3w!Password", "different")
    with pytest.raises(v.ValidationError, match="Password needs"):
        us.change_password(staff, PW, "weak", "weak")
    us.change_password(staff, PW, "N3w!Password", "N3w!Password")
    assert auth.login("STF-2026-001", "N3w!Password")["user_id"] == u["staff"]
    with pytest.raises(auth.AuthError):
        auth.login("STF-2026-001", PW)
