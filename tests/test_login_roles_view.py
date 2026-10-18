"""Drives the REAL login window and Role Management handlers against a throwaway database and records every dialog.
Skipped without a display. Calls the methods the buttons call; it does not synthesise mouse clicks."""
import pytest

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
def seeded(svc):
    d = svc
    ids = {}
    for key, eid, name, role, email in [("admin", "ADM-2026-001", "Admin One", "Admin", "admin@x.com"),
                                        ("staff", "STF-2026-001", "Stacy Staff", "Staff", "stacy@x.com"),
                                        ("worker", "WKR-2026-001", "Wally Worker", "Worker", None)]:
        ids[key] = run(d, "INSERT INTO `user` (employee_id, full_name, email, role, password_hash, status) VALUES (%s,%s,%s,%s,%s,'Active')",
                       (eid, name, email, role, None if role == "Worker" else hash_password(PW)))
    return d, ids


@pytest.fixture
def tk():
    import customtkinter as ctk
    from conftest import make_window
    root = make_window(ctk.CTk)
    root.geometry("400x300+0+0")
    root.update()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


def test_login_window_uses_the_service_and_shows_plain_messages(seeded, monkeypatch):
    import main
    d, ids = seeded
    from conftest import make_window
    app = make_window(main.LoginApp)
    try:
        entered = []
        monkeypatch.setattr(app, "show_loading_screen", lambda user: entered.append(user))
        monkeypatch.setattr(main.messagebox, "showwarning", lambda *a, **k: entered.append(("warn", a[1])))
        errors = []
        monkeypatch.setattr(app, "show_error", lambda msg: errors.append(msg))

        def attempt(user, pw):
            app.login_button.configure(state="normal", text="Login")
            app.user_entry.delete(0, "end"); app.user_entry.insert(0, user)
            app.pass_entry.delete(0, "end"); app.pass_entry.insert(0, pw)
            app.login()

        attempt("WKR-2026-001", "x")
        assert errors[-1].startswith("Access Denied: Field Workers")
        attempt("STF-2026-001", "wrong")
        assert "2 attempt(s) left" in errors[-1]
        attempt("STF-2026-001", "wrong"); attempt("STF-2026-001", "wrong")
        assert "Maximum attempts" in errors[-1] and app.login_button.cget("text") == "Locked"
        assert any(isinstance(e, tuple) and e[0] == "warn" for e in entered)
        run(d, "UPDATE `user` SET status='Active', failed_attempts=0 WHERE user_id=%s", (ids["staff"],))
        entered.clear()
        attempt("STF-2026-001", PW)
        assert len(entered) == 1 and entered[0]["role"] == "Staff" and "password_hash" not in entered[0]
        assert rows(d, "SELECT COUNT(*) AS n FROM `user`")[0]["n"] == 3
    finally:
        app.destroy()


def test_register_archive_and_the_blank_email_bug_through_the_real_role_screen(seeded, tk, monkeypatch):
    import database
    import views.role_management as rm
    d, ids = seeded
    monkeypatch.setattr(rm, "get_connection", database.get_connection)
    shown = []
    for name in ("showinfo", "showerror", "showwarning"):
        monkeypatch.setattr(rm.messagebox, name, lambda title, msg, _n=name, **k: shown.append((_n, title, msg)))
    answers = []
    monkeypatch.setattr(rm.messagebox, "askyesno", lambda title, msg, **k: (answers.append(title), True)[1])
    monkeypatch.setattr(rm.RoleManagementView, "load_user_table", lambda self, *a, **k: None)
    view = rm.RoleManagementView(tk, {"user_id": ids["admin"], "role": "Admin", "full_name": "Admin One"})

    def register(name, role, email="", pwd="", cpwd=None):
        view.open_register_modal()                                  # the screen builds a fresh form each time
        view.reg_name.insert(0, name)
        view.reg_email.insert(0, email)
        view.reg_role.set(role)
        view._build_reg_bottom(role)
        if view.reg_pass:
            view.reg_pass.insert(0, pwd)
            view.reg_confirm.insert(0, pwd if cpwd is None else cpwd)
        view.execute_register()

    register("Worker Number One", "Worker")
    register("Worker Number Two", "Worker")                       # two blank e-mails: the old code hit the UNIQUE key here
    assert [m[0] for m in shown] == ["showinfo", "showinfo"], shown
    assert rows(d, "SELECT COUNT(*) AS n FROM `user` WHERE role='Worker' AND password_hash IS NULL")[0]["n"] == 3
    shown.clear()
    register("New Staffer", "Staff", "new@x.com", "weak")
    assert shown[0][0] == "showerror" and "Password needs" in shown[0][2]
    shown.clear(); answers.clear()
    register("Stacy Staff", "Staff", "other@x.com", PW)           # a name that already exists: warns, then allows
    assert "Same Name Found" in answers and shown[-1][0] == "showinfo"

    shown.clear()
    victim = rows(d, "SELECT user_id FROM `user` WHERE full_name='Worker Number One'")[0]["user_id"]
    view.delete_user({"user_id": victim, "full_name": "Worker Number One"})
    assert rows(d, "SELECT status FROM `user` WHERE user_id=%s", (victim,))[0]["status"] == "Archived"
    view.delete_user({"user_id": ids["admin"], "full_name": "Admin One"})                  # yourself
    assert shown[-1][0] == "showerror" and "own account" in shown[-1][2]
