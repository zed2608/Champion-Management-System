"""Optional report charts must not leave an empty spacer above the table."""
import time

import customtkinter as ctk


def _wait(root, predicate):
    end = time.monotonic() + 4
    while time.monotonic() < end:
        root.update()
        if predicate():
            return
        time.sleep(.02)
    assert predicate()


def test_activity_table_starts_near_description_when_chart_has_no_data(monkeypatch):
    from conftest import make_window
    from views.reports import ReportsView
    from services import report_service as rs

    monkeypatch.setattr(ReportsView, "render_abc_tab", lambda self: None)
    monkeypatch.setattr(rs, "activity_report", lambda *_: [])
    root = make_window(ctk.CTk)
    root.geometry("1366x768+0+0")
    try:
        view = ReportsView(root, user_info={"role": "Admin"})
        view.pack(fill="both", expand=True)
        view.switch_tab("🖹 Employee Activity")
        _wait(root, lambda: hasattr(view, "_activity_raw_data") and bool(view.activity_table_inner.winfo_children()))
        assert view.activity_chart_frame.winfo_manager() == ""
        assert view.activity_table_inner.winfo_manager() == "pack"
        frame = view.tab_content.winfo_children()[0]
        desc = [w for w in frame.winfo_children() if isinstance(w, ctk.CTkLabel)][0]
        gap = view.activity_table_inner.winfo_rooty() - (desc.winfo_rooty() + desc.winfo_height())
        assert gap < 80, gap
        assert any(getattr(w, "_text", "") == "No data for this period" for w in view.activity_table_inner.winfo_children())
    finally:
        root.destroy()
