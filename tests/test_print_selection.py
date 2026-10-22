"""Click the actual print controls while paged rows are recycled."""
import time

import customtkinter as ctk

from services.paging import PageInfo
from views.paged_table import PagedTable


def _wait(root, predicate):
    end = time.monotonic() + 3
    while time.monotonic() < end:
        root.update()
        if predicate():
            return
        time.sleep(.01)
    assert predicate()


def test_print_checkbox_click_after_page_size_search_and_row_reuse():
    from conftest import make_window

    root = make_window(ctk.CTk)
    root.geometry("700x420+0+0")
    rows = [{"id": i, "tag": f"TAG-{i}" if i != 0 else ""} for i in range(40)]
    selected = set()
    filtered = list(reversed(rows))

    def fetch(page, size):
        page = min(page, max(0, (len(filtered) - 1) // size))
        return filtered[page * size:(page + 1) * size], PageInfo(page, size, len(filtered))

    table = PagedTable(root, [("Print", 1, 50), ("Item", 3, 120)], fetch, lambda row: ["", row["id"]],
                       checkbox={"col": 0, "state": lambda row: (bool(row["tag"]), row["id"] in selected),
                                 "toggle": lambda row, on: selected.add(row["id"]) if on else selected.discard(row["id"])})
    table.pack(fill="both", expand=True)

    def loaded(id):
        _wait(root, lambda: table.rows and table.rows[0]["id"] == id)
        root.update()

    def click_first():
        slot = table._slots[0]
        assert slot["check"].cget("state") == "normal"
        # The cell padding is part of the visible Print control's click target.
        cell = slot["cells"][0]
        cell._canvas.event_generate("<ButtonPress-1>", x=2, y=cell.winfo_height() // 2)
        cell._canvas.event_generate("<ButtonRelease-1>", x=2, y=cell.winfo_height() // 2)
        root.update()
        assert slot["check_var"].get() == "on"

    try:
        table.reload(0)
        loaded(39)
        click_first()
        assert 39 in selected

        table.goto(1)
        loaded(14)
        click_first()
        assert 14 in selected

        table._size_changed("50")
        loaded(39)
        assert table._slots[0]["check_var"].get() == "on"

        filtered[:] = [rows[0], rows[1]]
        table.reload(0)
        loaded(0)
        assert table._slots[0]["check"].cget("state") == "disabled"
        table._slots[0]["cells"][0]._canvas.event_generate("<ButtonPress-1>", x=2, y=10)
        root.update()
        assert 0 not in selected

        filtered[:] = [rows[2]]
        table.reload(0)
        loaded(2)
        click_first()
        assert 2 in selected and 39 in selected and 14 in selected
    finally:
        root.destroy()
