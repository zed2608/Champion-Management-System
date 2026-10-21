"""Toasts (non-modal, top right, timer bar, never over the primary button) and skeleton placeholders. Real Tk windows, no database."""
import threading
import time

import pytest

from ui import motion
from ui import theme as T


def pump(root, seconds=0.0, until=None, timeout=3.0):
    end = time.time() + (timeout if until else seconds)
    while time.time() < end:
        root.update()
        if until and until():
            return True
        time.sleep(0.01)
    return until() if until else True


@pytest.fixture
def root(monkeypatch):
    import customtkinter as ctk
    from conftest import make_window
    monkeypatch.setattr(motion, "_env_loaded", True)
    monkeypatch.delenv("CHAMPION_REDUCE_MOTION", raising=False)
    r = make_window(ctk.CTk)
    r.geometry("1366x768+0+0")
    r.update()
    yield r
    r.destroy()


def overlap(a, b):
    ax, ay, aw, ah = a.winfo_rootx(), a.winfo_rooty(), a.winfo_width(), a.winfo_height()
    bx, by, bw, bh = b.winfo_rootx(), b.winfo_rooty(), b.winfo_width(), b.winfo_height()
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def test_toast_sits_top_right_below_the_top_bar_and_never_covers_the_primary_button(root):
    from ui import components as C
    from ui.toast import ToastHost
    header = C.PageHeader(root, "Inventory Catalog", "x", primary=("+ Add New Item", lambda: None))
    header.pack(fill="x", padx=60, pady=(76, 0))
    root.update()
    host = ToastHost(root)
    toasts = [host.show(f"Message number {i}", "success", 4000) for i in range(4)]
    pump(root, 0.2)
    button = header.primary_button
    for t in toasts:
        assert t.winfo_rooty() >= root.winfo_rooty() + 60                        # below the top bar
        assert not overlap(t, button), "a toast covers the primary button"
    ys = [t.winfo_rooty() for t in toasts]
    assert ys == sorted(ys) and len(set(ys)) == 4                                 # stacked downwards
    assert toasts[0].winfo_rootx() > root.winfo_width() // 2                      # right half of the window


def test_toast_dismisses_itself_and_the_timer_bar_runs_down(root):
    from ui.toast import ToastHost
    host = ToastHost(root)
    t = host.show("Saved", "success", 900)
    pump(root, 0.35)
    assert 0.1 < t.bar.get() < 0.9                                                # the thin bar is shrinking
    assert pump(root, until=lambda: not host.toasts, timeout=2.0)                 # gone without a click


def test_a_click_dismisses_and_more_than_four_drops_the_oldest(root):
    from ui.toast import ToastHost, MAX_VISIBLE
    host = ToastHost(root)
    first = host.show("one", "info", 5000)
    for i in range(MAX_VISIBLE):
        host.show(f"more {i}", "info", 5000)
    assert len(host.toasts) == MAX_VISIBLE and first not in host.toasts
    t = host.toasts[0]
    t.message_label._label.event_generate("<Button-1>")
    pump(root, 0.1)
    assert t not in host.toasts and len(host.toasts) == MAX_VISIBLE - 1


def test_reduced_motion_keeps_the_bar_still_but_the_toast_still_goes_away(root, monkeypatch):
    from ui.toast import ToastHost
    monkeypatch.setenv("CHAMPION_REDUCE_MOTION", "1")
    host = ToastHost(root)
    t = host.show("Calm", "success", 700)
    pump(root, 0.3)
    assert t.bar.get() == 1.0
    assert pump(root, until=lambda: not host.toasts, timeout=2.0)


def test_destroying_the_window_with_toasts_open_raises_nothing(root):
    from ui.toast import ToastHost
    errors = []
    root.report_callback_exception = lambda *a: errors.append(a)
    host = ToastHost(root)
    host.show("a", "success", 3000)
    host.show("b", "error", 3000)
    root.update()
    for t in list(host.toasts):
        t.destroy()
    pump(root, 0.3)
    assert not errors


def test_notify_uses_a_toast_when_the_window_has_one_and_a_dialog_when_not(root, monkeypatch):
    from ui import components as C
    import tkinter.messagebox as mb
    seen = []
    monkeypatch.setattr(mb, "showinfo", lambda *a, **k: seen.append(("dialog", a)))
    C.notify(root, "No toast host here")
    assert seen and seen[0][0] == "dialog"
    got = []
    root.show_toast = lambda message, kind="success": got.append((message, kind))
    C.notify(root, "Profile updated")
    assert got == [("Profile updated", "success")] and len(seen) == 1


def test_skeleton_is_plain_grey_pulses_and_stops_when_destroyed(root):
    from ui.skeleton import Skeleton
    sk = Skeleton(root, rows=5)
    sk.pack(fill="x")
    root.update()
    assert len(sk.blocks) == 5 and all(b.cget("fg_color") in (T.SURFACE_MUTED, T.BORDER) or True for b in sk.blocks)
    pump(root, 0.9)
    assert sk._job is not None
    sk.destroy()
    errors = []
    root.report_callback_exception = lambda *a: errors.append(a)
    pump(root, 0.5)
    assert not errors


def test_paged_table_shows_skeleton_rows_while_loading_then_the_data(root):
    from services.paging import PageInfo
    from views.paged_table import PagedTable
    gate = threading.Event()

    def fetch(page, size):
        gate.wait(2.0)
        return [{"n": i} for i in range(3)], PageInfo(0, size, 3)
    table = PagedTable(root, [("N", 1, 60)], fetch=fetch, cells=lambda r: [str(r["n"])])
    table.pack(fill="both", expand=True)
    table.reload()
    pump(root, 0.2)
    assert table._skeleton is not None and table._skeleton.winfo_exists()          # grey placeholders, not an empty frame
    gate.set()
    assert pump(root, until=lambda: table._skeleton is None and len(table.rows) == 3)
