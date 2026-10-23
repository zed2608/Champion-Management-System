"""The tour must expose its instructions and buttons at normal desktop size."""
import customtkinter as ctk

from ui import tour


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
