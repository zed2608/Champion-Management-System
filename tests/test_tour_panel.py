"""The tour must expose its instructions and buttons at normal desktop size."""
import ast
from pathlib import Path

import customtkinter as ctk

from ui import tour
from ui import theme as T


def test_tour_and_table_use_supported_font_sizes():
    root = Path(__file__).resolve().parents[1]
    for name in ("ui/tour.py", "views/paged_table.py"):
        tree = ast.parse((root / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "T"
                    and node.func.attr == "font" and node.args and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, int)):
                assert node.args[0].value in T.SIZES, f"{name}:{node.lineno} uses an unsupported font size"


def test_guided_tour_panel_shows_full_content(monkeypatch):
    from conftest import make_window

    root = make_window(ctk.CTk)
    root.geometry("1351x881+0+0")
    root.user_info = {"role": "Staff"}
    root.current_page_name = "Dashboard"
    root.current_frame = ctk.CTkFrame(root)
    root.current_frame.pack(fill="both", expand=True)
    nav = ctk.CTkButton(root.current_frame, text="Dashboard")
    nav.pack(anchor="w")
    root.nav_buttons = {"Dashboard": nav}
    root.user_frame = nav
    monkeypatch.setattr(tour, "steps_for", lambda role: (tour.Step("Dashboard", "Find your way", "Use the left menu.", "nav:Dashboard"),))
    try:
        guided = tour.GuidedTour(root)
        root.update()
        assert guided.panel.winfo_width() >= 400
        assert guided.panel.winfo_height() >= 200
        assert guided.title.winfo_ismapped()
        assert guided.detail.winfo_ismapped()
        assert guided.next_button.winfo_ismapped()
        assert guided.back_button.winfo_ismapped()
        assert guided.next_button.winfo_rooty() + guided.next_button.winfo_height() <= guided.panel.winfo_rooty() + guided.panel.winfo_height()
        guided.close()
    finally:
        root.destroy()
