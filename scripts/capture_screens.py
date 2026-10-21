"""Take a screenshot of every main screen (and every tab) of the real program at about 1366x768.

    python scripts/capture_screens.py docs/screenshots/before

It builds a THROWAWAY database (test_shots) with the demo seeder, opens the real program against it as Admin (plus the Staff dashboard and the login
window), grabs the pictures from the screen and drops the throwaway database again. It never touches champion_db: the database name is fixed here,
the credentials come from .env only to create/drop that one test_ database.
Needs a real Windows desktop (it grabs pixels); nothing else should cover the window while it runs (about 2 minutes).
"""
import ctypes
import gc
import os
import re
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
SHOTS_DB = "test_shots"
W, H = 1366, 768


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40]


def pump(root, seconds):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.02)


def settle(root, seconds=8.0):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        busy = [t for t in threading.enumerate() if t is not threading.main_thread() and t.is_alive() and t.name != "tool-cache-poller"]
        if not busy:
            break
        time.sleep(0.05)
    pump(root, 0.6)


def walk(widget):
    try:
        kids = widget.winfo_children()
    except Exception:
        return
    for k in kids:
        yield k
        yield from walk(k)


def main(out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    from dotenv import dotenv_values
    env = dotenv_values(ROOT / ".env")
    os.environ.update({"DB_HOST": "127.0.0.1" if env.get("DB_HOST", "localhost") in ("localhost", "127.0.0.1") else env["DB_HOST"],
                       "DB_PORT": env.get("DB_PORT") or "3306", "DB_USER": env["DB_USER"], "DB_PASS": env.get("DB_PASS", ""), "DB_NAME": SHOTS_DB,
                       "CHAMPION_LOG_DIR": str(Path(os.environ.get("TEMP", ".")) / "champion_shot_logs")})
    if "aiven" in os.environ["DB_HOST"].lower():
        raise SystemExit("Refusing: Aiven host.")
    import mysql.connector
    import seed_demo_data as seed
    from db import migrate
    from db import db
    admin_conn = mysql.connector.connect(host=os.environ["DB_HOST"], port=int(os.environ["DB_PORT"]), user=os.environ["DB_USER"],
                                         password=os.environ["DB_PASS"], autocommit=True)
    cur = admin_conn.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS `{SHOTS_DB}`")
    cur.execute(f"CREATE DATABASE `{SHOTS_DB}` CHARACTER SET utf8mb4")
    try:
        migrate.run(db, require_backup=False, log=lambda *_: None)
        ids = seed.build(db, "Shots-Admin1!", "Shots-Staff1!")
        from PIL import ImageGrab
        import customtkinter as ctk
        import dashboard as dash
        import main as login_module

        def grab(win, name):
            win.update_idletasks()
            win.lift()
            win.attributes("-topmost", True)
            pump(win, 0.3)
            x, y, w, h = win.winfo_rootx(), win.winfo_rooty(), win.winfo_width(), win.winfo_height()
            ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(out / f"{name}.png")
            win.attributes("-topmost", False)
            print("  saved", name, f"{w}x{h}")

        root = login_module.LoginApp()
        root.update()
        grab(root, "00_login")
        users = {"Admin": {"user_id": ids["admin"], "employee_id": "ADM-2026-001", "role": "Admin", "full_name": "Rhea Santos", "email": None, "status": "Active"},
                 "Staff": {"user_id": ids["staff"], "employee_id": "STF-2026-001", "role": "Staff", "full_name": "Miguel Ramos", "email": None, "status": "Active"}}
        root.withdraw()
        pages = ["Dashboard", "Project Management", "Inventory", "Issuance & Retrieval", "Tracking & Accountability", "Reports", "Maintenance",
                 "Role Management", "Help", "Profile"]
        for role, role_pages in (("Admin", pages), ("Staff", ["Dashboard", "Inventory", "Issuance & Retrieval", "Tracking & Accountability"])):
            app = dash.DashboardApp(root, user_info=users[role])
            app.geometry(f"{W}x{H}+0+0")
            settle(app)
            for n, page in enumerate(role_pages, 1):
                app.show_frame(page)
                settle(app)
                prefix = f"{role.lower()}_{n:02d}_{slug(page)}"
                grab(app, prefix)
                for bar in [w for w in walk(app.current_frame) if w.__class__.__name__ == "CTkSegmentedButton"][:1]:
                    for value in list(bar._value_list):
                        bar.set(value)
                        if bar._command:
                            bar._command(value)
                        settle(app)
                        grab(app, f"{prefix}__{slug(value)}")
            app.destroy()
            gc.collect()
        root.destroy()
    finally:
        cur.execute(f"DROP DATABASE IF EXISTS `{SHOTS_DB}`")
        admin_conn.close()
    print("Done. Throwaway database dropped.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots/before")
    os._exit(0)                       # background poller threads must not keep the process alive
