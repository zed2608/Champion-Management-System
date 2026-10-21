"""Colour transitions: exact end colours, ~120 ms, cancelled on destroy, off under CHAMPION_REDUCE_MOTION=1, never an error on a dead widget."""
import time

import pytest

from ui import motion
from ui import theme as T


def pump(root, seconds):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.01)


def test_mix_and_frames_end_exactly_on_the_target():
    assert motion.mix("#000000", "#FFFFFF", 0.5) == "#808080"
    seq = motion.frames("#1E4528", "#14301C")
    assert len(seq) == motion.STEPS and seq[-1] == "#14301C" and seq[0] != "#14301C"
    assert motion.darken("#FFFFFF", 0.5) == "#808080"


def test_reduced_motion_switch(monkeypatch):
    monkeypatch.setattr(motion, "_env_loaded", True)
    for value, expected in (("1", True), ("true", True), ("0", False), ("", False)):
        monkeypatch.setenv("CHAMPION_REDUCE_MOTION", value)
        assert motion.reduced_motion() is expected


class FakeWidget:
    def __init__(self):
        self.colour, self.jobs, self.cancelled = "#000000", [], []

    def configure(self, **kw):
        self.colour = kw.get("fg_color", self.colour)

    def after(self, ms, fn, *a):
        self.jobs.append((ms, fn, a))
        return len(self.jobs)

    def after_cancel(self, job):
        self.cancelled.append(job)

    def winfo_exists(self):
        return True

    def bind(self, *a, **k):
        pass


def test_tween_uses_after_in_small_steps_totalling_about_120ms(monkeypatch):
    monkeypatch.setattr(motion, "_env_loaded", True)
    monkeypatch.delenv("CHAMPION_REDUCE_MOTION", raising=False)
    w = FakeWidget()
    motion.tween_color(w, "fg_color", "#000000", "#FFFFFF", 120)
    seen = [w.colour]
    while w.jobs:
        ms, fn, a = w.jobs.pop(0)
        assert 10 <= ms <= 40
        fn(*a)
        seen.append(w.colour)
    assert seen[-1] == "#FFFFFF" and len(seen) == motion.STEPS and seen == sorted(seen)
    assert motion.STEPS * 20 <= 140


def test_a_new_tween_cancels_the_running_one(monkeypatch):
    monkeypatch.setattr(motion, "_env_loaded", True)
    monkeypatch.delenv("CHAMPION_REDUCE_MOTION", raising=False)
    w = FakeWidget()
    motion.tween_color(w, "fg_color", "#000000", "#FFFFFF")
    motion.tween_color(w, "fg_color", "#FFFFFF", "#000000")
    assert w.cancelled, "the first transition should have been cancelled"


def test_with_reduced_motion_the_colour_changes_at_once_and_nothing_is_scheduled(monkeypatch):
    monkeypatch.setattr(motion, "_env_loaded", True)
    monkeypatch.setenv("CHAMPION_REDUCE_MOTION", "1")
    w = FakeWidget()
    motion.tween_color(w, "fg_color", "#000000", "#FFFFFF")
    assert w.colour == "#FFFFFF" and not w.jobs


@pytest.fixture
def root():
    import customtkinter as ctk
    from conftest import make_window
    r = make_window(ctk.CTk)
    r.geometry("300x200+0+0")
    r.update()
    yield r
    r.destroy()


def test_button_fades_on_hover_presses_and_returns(root, monkeypatch):
    from ui import components as C
    monkeypatch.setattr(motion, "_env_loaded", True)
    monkeypatch.delenv("CHAMPION_REDUCE_MOTION", raising=False)
    clicked = []
    b = C.button(root, "Go", lambda: clicked.append(1), "primary")
    b.pack(padx=20, pady=20)
    root.update()
    assert str(b.cget("cursor")) in ("hand2", "hand")                       # pointer on everything clickable
    b._canvas.event_generate("<Enter>")
    pump(root, 0.3)
    assert b.cget("fg_color") == T.PRIMARY_HOVER
    b._canvas.event_generate("<ButtonPress-1>")
    pump(root, 0.05)
    assert b.cget("fg_color") not in (T.PRIMARY, T.PRIMARY_HOVER)           # the darker "press" colour
    b._canvas.event_generate("<ButtonRelease-1>")
    pump(root, 0.3)
    b._canvas.event_generate("<Leave>")
    pump(root, 0.3)
    assert b.cget("fg_color") == T.PRIMARY


def test_transparent_button_fades_from_its_parents_colour_and_returns_to_transparent(root, monkeypatch):
    from ui import components as C
    monkeypatch.setattr(motion, "_env_loaded", True)
    monkeypatch.delenv("CHAMPION_REDUCE_MOTION", raising=False)
    b = C.button(root, "Nav", None, "ghost", hover_color=T.SIDEBAR_ACTIVE)
    b.pack()
    root.update()
    b._canvas.event_generate("<Enter>")
    pump(root, 0.3)
    assert b.cget("fg_color") == T.SIDEBAR_ACTIVE
    b._canvas.event_generate("<Leave>")
    pump(root, 0.3)
    assert b.cget("fg_color") == "transparent"


def test_destroying_a_widget_mid_fade_raises_nothing(root, monkeypatch):
    from ui import components as C
    monkeypatch.setattr(motion, "_env_loaded", True)
    monkeypatch.delenv("CHAMPION_REDUCE_MOTION", raising=False)
    errors = []
    root.report_callback_exception = lambda *a: errors.append(a)
    b = C.button(root, "Bye", None, "primary")
    b.pack()
    root.update()
    b._canvas.event_generate("<Enter>")
    root.update()
    b.destroy()
    pump(root, 0.3)
    assert not errors


def test_reduced_motion_makes_a_real_button_change_at_once(root, monkeypatch):
    from ui import components as C
    monkeypatch.setattr(motion, "_env_loaded", True)
    monkeypatch.setenv("CHAMPION_REDUCE_MOTION", "1")
    b = C.button(root, "Calm", None, "primary")
    b.pack()
    root.update()
    b._canvas.event_generate("<Enter>")
    root.update()
    assert b.cget("fg_color") == T.PRIMARY_HOVER


def test_count_up_reaches_the_exact_number_and_only_moves_when_it_changed(root, monkeypatch):
    import customtkinter as ctk
    monkeypatch.setattr(motion, "_env_loaded", True)
    monkeypatch.delenv("CHAMPION_REDUCE_MOTION", raising=False)
    lbl = ctk.CTkLabel(root, text="0")
    lbl.pack()
    motion.count_up(lbl, 40, lambda v: f"{v:g}%")
    shown = []
    end = time.time() + 1.0
    while time.time() < end:
        root.update()
        t = lbl.cget("text")
        if not shown or shown[-1] != t:
            shown.append(t)
        time.sleep(0.005)
    values = [float(x.rstrip("%")) for x in shown]
    assert values[-1] == 40 and values == sorted(values) and len(values) >= 4        # a visible count, ending exactly on the number
    motion.count_up(lbl, 40, lambda v: f"{v:g}%")                                      # unchanged: no new animation
    assert lbl.cget("text") == "40%" and "count" not in getattr(lbl, "_motion_jobs", {})
    motion.count_up(lbl, 25.5, lambda v: f"{v:g}%")                                    # counts down from the previous number
    pump(root, 0.8)
    assert lbl.cget("text") == "25.5%"


def test_count_up_is_instant_under_reduced_motion_and_accepts_decimals(root, monkeypatch):
    import customtkinter as ctk
    from decimal import Decimal
    monkeypatch.setattr(motion, "_env_loaded", True)
    monkeypatch.setenv("CHAMPION_REDUCE_MOTION", "1")
    lbl = ctk.CTkLabel(root, text="0")
    lbl.pack()
    motion.count_up(lbl, Decimal("988.5"), lambda v: f"{v:g}")
    assert lbl.cget("text") == "988.5"
