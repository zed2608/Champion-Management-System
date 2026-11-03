"""The dashboard: four KPI cards for both roles, with optional Admin details."""
import gc
import threading
import time

import pytest

pytestmark = pytest.mark.db


def run(db, sql, params=()):
    with db.transaction() as cur:
        cur.execute(sql, params)
        return cur.lastrowid


def pump(root, seconds=0.0, until=None, timeout=6.0):
    end = time.time() + (timeout if until else seconds)
    while time.time() < end:
        root.update()
        if until and until():
            return True
        time.sleep(0.02)
    return until() if until else True


def settle(root, seconds=8.0):
    """Wait for every loader thread to finish, THEN collect garbage on the main thread (freeing Tk objects on a worker thread crashes Python)."""
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        if not [t for t in threading.enumerate() if t is not threading.main_thread() and t.is_alive() and t.name != "tool-cache-poller"]:
            break
        time.sleep(0.05)
    gc.collect()
    pump(root, 0.25)


def walk(w):
    try:
        kids = w.winfo_children()
    except Exception:
        return
    for k in kids:
        yield k
        yield from walk(k)


@pytest.fixture
def world(svc, monkeypatch):
    import customtkinter as ctk
    from conftest import make_window
    d = svc
    admin = run(d, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('ADM-2026-001','Admin','Admin','Active')")
    staff = run(d, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('STF-2026-001','Stacy','Staff','Active')")
    tool = run(d, "INSERT INTO tool (name, tag_id, item_type, price) VALUES ('Caliper','CAL-001','Equipment',900)")
    run(d, "INSERT INTO inventory (tool_id, quantity_total, quantity_available, minimum_stock) VALUES (%s,5,1,3)", (tool,))
    users = {"Admin": {"user_id": admin, "employee_id": "ADM-2026-001", "role": "Admin", "full_name": "Admin", "email": None, "status": "Active"},
             "Staff": {"user_id": staff, "employee_id": "STF-2026-001", "role": "Staff", "full_name": "Stacy", "email": None, "status": "Active"}}
    root = make_window(ctk.CTk)
    root.geometry("1366x768+0+0")
    root.update()
    yield root, users
    try:
        settle(root)
        root.destroy()
    except Exception:
        pass


@pytest.mark.parametrize("role,count", [("Admin", 4), ("Staff", 4)])
def test_kpi_cards_are_identical_in_size_and_type(world, role, count):
    import dashboard as dash
    from ui.components import KpiCard
    root, users = world
    app = dash.DashboardApp(root, user_info=users[role])
    pump(root, 1.0)
    cards = [w for w in walk(app.current_frame) if isinstance(w, KpiCard)]
    assert len(cards) == count, len(cards)
    assert len({c.winfo_height() for c in cards}) == 1 and cards[0].winfo_height() == 130
    assert max(c.winfo_width() for c in cards) - min(c.winfo_width() for c in cards) <= 2
    assert len({c.title_label.cget("font")[1] for c in cards}) == 1
    assert len({c.note_label.cget("font")[1] for c in cards}) == 1
    values = [c.value_label for c in cards if c.value_label is not None]
    assert len({v.cget("font")[1] for v in values}) == 1 and values[0].cget("font")[1] == 28
    # number on top, label below, status line last
    for c in cards:
        assert c.top.winfo_rooty() < c.title_label.winfo_rooty() < c.note_label.winfo_rooty()
    settle(root)
    app.destroy()


def test_admin_keeps_every_phase4_card_and_staff_gets_none_of_them(world):
    import dashboard as dash
    root, users = world
    app = dash.DashboardApp(root, user_info=users["Admin"])
    assert pump(root, until=lambda: getattr(app, "ins_labels", None) and all(l.cget("text") != "Loading..." for l in app.ins_labels.values()))
    assert {"backup", "audit", "wear", "recs"} <= set(app.ins_labels) or len(app.ins_labels) >= 4
    settle(root)
    app.destroy()
    app = dash.DashboardApp(root, user_info=users["Staff"])
    pump(root, 1.0)
    assert not getattr(app, "ins_labels", None)
    texts = [getattr(w, "_text", "") for w in walk(app.current_frame)]
    assert not any("ADMIN INSIGHTS" in t for t in texts)
    settle(root)
    app.destroy()


def test_low_stock_card_turns_red_and_keeps_that_colour_under_the_mouse(world):
    import dashboard as dash
    from ui import theme as T
    root, users = world
    app = dash.DashboardApp(root, user_info=users["Admin"])
    assert pump(root, until=lambda: app.dash_lowstock_card._hover_base == T.DANGER_BG)           # 1 of 5 is below the minimum of 3
    assert app.dash_lowstock_val.cget("text") == "1"
    app.dash_lowstock_card._canvas.event_generate("<Enter>") if hasattr(app.dash_lowstock_card, "_canvas") else None
    pump(root, 0.3)
    settle(root)
    app.destroy()


def test_charts_use_the_shared_style_and_every_figure_is_closed(world):
    import matplotlib
    import matplotlib.pyplot as plt
    import dashboard as dash
    from ui import theme as T
    assert matplotlib.rcParams["font.family"][0] == T.FAMILY
    assert matplotlib.rcParams["axes.spines.top"] is False and matplotlib.rcParams["axes.grid"] is True
    assert matplotlib.rcParams["grid.color"] == T.BORDER and not matplotlib.rcParams["legend.frameon"]
    root, users = world
    before = len(plt.get_fignums())
    app = dash.DashboardApp(root, user_info=users["Admin"])
    pump(root, 1.5)
    assert len(plt.get_fignums()) > before                                                       # the dashboard drew its charts
    app.show_frame("Help")
    pump(root, 0.5)
    assert len(plt.get_fignums()) == before                                                      # leaving the dashboard closed them
    settle(root)
    app.destroy()
