"""Exercise print selection with Tk press/release events on local champion_demo."""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    from dotenv import dotenv_values

    config = dotenv_values(ROOT / (".env.demo" if (ROOT / ".env.demo").exists() else ".env"))
    if (config.get("DB_HOST") or "").lower() not in ("localhost", "127.0.0.1"):
        raise SystemExit("This check requires local champion_demo MySQL.")
    os.environ.update({k: v for k, v in config.items() if k.startswith("DB_") and v is not None})
    os.environ["DB_NAME"] = "champion_demo"
    os.environ["CHAMPION_LOG_DIR"] = str(Path(os.environ.get("TEMP", ".")) / "champion_tour_check_logs")

    import customtkinter as ctk
    from views.inventory import InventoryView

    root = ctk.CTk()
    root.geometry("1366x768+0+0")
    view = InventoryView(root, user_info={"role": "Admin"})
    view.pack(fill="both", expand=True)
    table = view._inv_table

    def wait_for(predicate):
        end = time.monotonic() + 8
        while time.monotonic() < end:
            root.update()
            if predicate():
                return
            time.sleep(.02)
        raise AssertionError("Inventory did not load the expected row")

    def click(widget, x=8, y=8):
        target = getattr(widget, "_canvas", widget)
        target.event_generate("<ButtonPress-1>", x=x, y=y)
        target.event_generate("<ButtonRelease-1>", x=x, y=y)
        root.update()

    def click_first():
        slot = table._slots[0]
        assert slot["row"]["tag_id"] and slot["check"].cget("state") == "normal"
        click(slot["check"])
        assert slot["check_var"].get() == "on"
        assert str(slot["row"]["tool_id"]) in view.selected_for_print

    try:
        wait_for(lambda: table.rows and table.rows[0]["tool_id"] == 40)
        click_first()
        table.goto(1)
        wait_for(lambda: table.rows and table.rows[0]["tool_id"] == 15)
        click_first()
        table._size_changed("50")
        wait_for(lambda: table.rows and len(table.rows) == 40)
        assert table._slots[0]["check_var"].get() == "on"
        view.search_entry.insert(0, "Hard Hat")
        view.perform_search()
        wait_for(lambda: table.rows and table.rows[0]["name"] == "Hard Hat")
        assert table._slots[0]["check"].cget("state") == "disabled"
        click(table._slots[0]["cells"][0])
        assert table._slots[0]["check_var"].get() == "off"
        view.search_entry.delete(0, "end")
        view.search_entry.insert(0, "Welding Helmet")
        view.perform_search()
        wait_for(lambda: table.rows and table.rows[0]["name"] == "Welding Helmet")
        click_first()
        assert view.selected_count_label.cget("text") == "3 selected"
        assert view.batch_print_btn.cget("state") == "normal"
        click(view.select_page_check)
        assert view.selected_count_label.cget("text") == "2 selected"
        assert view.batch_print_btn.cget("state") == "normal"
        print("champion_demo print controls: click, paging, page size, search, row reuse, disabled, count and page selection passed")
    finally:
        root.destroy()


if __name__ == "__main__":
    main()
