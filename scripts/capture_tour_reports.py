"""Capture the nine Reports tabs from the local champion_demo database.

    .venv\\Scripts\\python.exe scripts/capture_tour_reports.py

Requires an unlocked 1920x1080 desktop. Refuses a remote or non-demo database.
"""
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    check_only = "--check-only" in sys.argv
    from dotenv import dotenv_values

    config = dotenv_values(ROOT / (".env.demo" if (ROOT / ".env.demo").exists() else ".env"))
    host = (config.get("DB_HOST") or "").lower()
    if host not in ("localhost", "127.0.0.1"):
        raise SystemExit("Capture requires local MySQL; remote hosts are refused.")
    if not config.get("DB_USER"):
        raise SystemExit("Local MySQL credentials are missing.")
    os.environ.update({k: v for k, v in config.items() if k.startswith("DB_") and v is not None})
    os.environ["DB_NAME"] = "champion_demo"
    os.environ["CHAMPION_LOG_DIR"] = str(Path(os.environ.get("TEMP", ".")) / "champion_tour_capture_logs")

    import customtkinter as ctk
    from PIL import ImageGrab
    from database import get_connection
    from dashboard import DashboardApp

    conn = get_connection()
    if not conn:
        raise SystemExit("champion_demo is not available.")
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT user_id, employee_id, full_name, role FROM `user` WHERE role='Admin' LIMIT 1")
        user = cur.fetchone()
        cur.close()
    finally:
        conn.close()
    if not user:
        raise SystemExit("No demo Admin exists.")

    out = ROOT / "docs" / "screenshots" / "tour_dashboard_after"
    if not check_only:
        out.mkdir(parents=True, exist_ok=True)
    root = ctk.CTk()
    root.withdraw()
    app = DashboardApp(root, user_info=user)
    try:
        for width, height in ((1366, 768), (1920, 1080)):
            app.geometry(f"{width}x{height}+0+0")
            app.show_frame("Reports")
            app.update()
            view = app.current_frame
            values = list(view.seg_btn._value_list)
            for i, value in enumerate(values, 1):
                if i > 1:
                    view.seg_btn.set(value)
                    view.switch_tab(value)
                end = time.monotonic() + (3 if check_only else 8)
                while time.monotonic() < end:
                    app.update()
                    time.sleep(.02)
                app.update_idletasks()
                app.lift()
                app.attributes("-topmost", True)
                app.update()
                x, y = app.winfo_rootx(), app.winfo_rooty()
                name = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
                if check_only:
                    assert view.tab_content.winfo_children(), value
                    print(f"{width}x{height} {name}: opened", flush=True)
                else:
                    path = out / f"{width}x{height}_{i:02d}_{name}.png"
                    ImageGrab.grab(bbox=(x, y, x + width, y + height), all_screens=True).save(path)
                    print(path.relative_to(ROOT), flush=True)
                app.attributes("-topmost", False)
    finally:
        app.destroy()
        root.destroy()


if __name__ == "__main__":
    main()
