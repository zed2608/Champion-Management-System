"""Splash, four-slide intro and the local preference file. Real Tk windows; the preference file is a temporary one, never the real ui_prefs.json."""
import re
import time

import pytest

from ui import intro, motion, prefs


def pump(root, seconds=0.0, until=None, timeout=3.0):
    end = time.time() + (timeout if until else seconds)
    while time.time() < end:
        root.update()
        if until and until():
            return True
        time.sleep(0.01)
    return until() if until else True


@pytest.fixture
def root(monkeypatch, tmp_path):
    import customtkinter as ctk
    from conftest import make_window
    monkeypatch.setenv("CHAMPION_UI_PREFS", str(tmp_path / "ui_prefs.json"))
    monkeypatch.setattr(motion, "_env_loaded", True)
    monkeypatch.delenv("CHAMPION_REDUCE_MOTION", raising=False)
    r = make_window(ctk.CTk)
    r.geometry("400x300+0+0")
    r.update()
    yield r
    r.destroy()


def test_prefs_round_trip_and_never_raise(monkeypatch, tmp_path):
    monkeypatch.setenv("CHAMPION_UI_PREFS", str(tmp_path / "p.json"))
    assert prefs.get("intro_seen", False) is False
    assert prefs.set("intro_seen", True) and prefs.get("intro_seen") is True
    (tmp_path / "p.json").write_text("not json", encoding="utf-8")
    assert prefs.get("intro_seen", "default") == "default"                       # a damaged file is ignored, not an error
    monkeypatch.setenv("CHAMPION_UI_PREFS", str(tmp_path / "missing_folder" / "p.json"))
    assert prefs.set("x", 1) is False and prefs.get("x") is None                  # unwritable: reported, nothing raised


def test_the_intro_reads_in_under_twenty_seconds_and_names_the_people():
    words = sum(len(re.findall(r"\S+", " ".join([title, *lines]))) for title, lines in intro.SLIDES)
    assert len(intro.SLIDES) == 4 and words <= 100, words                         # about 5 words a second
    text = " ".join(" ".join(lines) for _t, lines in intro.SLIDES)
    for must in ("Cayper Tech", "Technological Institute of the Philippines", "Software Engineering 2", "Project Management 3",
                 "Champion Fine Tooling Corporation", "Cyrus Austin G. Andal", "Charles Joseph S. Peralta", "Angelo Genesis N. Talastas",
                 "Ayzhiedy Jee D. Reyes", "10,000", "ABC", "wear forecast", "audit chain"):
        assert must in text, must
    assert "roles to be added" in text                                            # the team list is marked as a placeholder


def test_splash_closes_itself_after_about_one_and_a_half_seconds(root):
    assert intro.SPLASH_MS == 1500
    done = []
    t0 = time.time()
    s = intro.SplashScreen(root, on_done=lambda: done.append(time.time() - t0), ms=300)
    pump(root, 0.1)
    assert s.overrideredirect() in (True, 1) and 0.0 <= s.bar.get() < 1.0
    assert pump(root, until=lambda: done, timeout=2.0)
    assert 0.25 <= done[0] <= 1.0


def test_slides_next_back_dots_and_arrow_keys(root):
    w = intro.IntroWindow(root)
    pump(root, 0.2)
    assert w.index == 0 and str(w.back_btn.cget("state")) == "disabled"
    assert [d.cget("text_color") for d in w._dot_labels].count(w._dot_labels[0].cget("text_color")) == 1       # exactly one dot is lit
    w.event_generate("<Right>")
    pump(root, 0.1)
    assert w.index == 1 and str(w.back_btn.cget("state")) == "normal"
    w.event_generate("<Left>")
    pump(root, 0.1)
    assert w.index == 0
    for _ in range(3):
        w.next()
    assert w.index == 3 and w.next_btn.cget("text").startswith("Done")
    w.close()


def test_skip_with_the_box_ticked_remembers_and_the_intro_never_returns(root):
    assert intro.should_show_intro()
    closed = []
    w = intro.IntroWindow(root, on_done=lambda: closed.append(1))
    pump(root, 0.1)
    assert int(w.dont_show.get()) == 1                                           # ticked on a first launch
    w.skip_btn.invoke()
    pump(root, 0.1)
    assert closed == [1] and not intro.should_show_intro()


def test_unticking_the_box_shows_it_again_next_time_and_reset_brings_it_back(root):
    w = intro.IntroWindow(root)
    pump(root, 0.1)
    w.dont_show.deselect()
    w.close()
    assert intro.should_show_intro()
    prefs.set("intro_seen", True)
    assert not intro.should_show_intro()
    prefs.set("intro_seen", False)
    assert intro.should_show_intro()


def test_startup_runs_splash_then_intro_then_reveals_the_window(root, monkeypatch):
    monkeypatch.setattr(intro, "SPLASH_MS", 150)
    revealed = []
    root.deiconify = lambda: revealed.append("shown")
    intro.run_startup(root)
    assert pump(root, until=lambda: any(isinstance(w, intro.IntroWindow) for w in root.winfo_children()))
    assert not revealed                                                           # hidden while the intro is up
    [w for w in root.winfo_children() if isinstance(w, intro.IntroWindow)][0].close()
    assert pump(root, until=lambda: revealed)
    revealed.clear()
    intro.run_startup(root)                                                       # second start: intro is dismissed, only the splash
    assert pump(root, until=lambda: revealed)
    assert not any(isinstance(w, intro.IntroWindow) for w in root.winfo_children())


def test_reduced_motion_makes_the_splash_short_and_still(root, monkeypatch):
    monkeypatch.setenv("CHAMPION_REDUCE_MOTION", "1")
    s = intro.SplashScreen(root)
    assert s.bar.get() == 1.0 and s._ms < intro.SPLASH_MS
    s.finish()


@pytest.mark.db
def test_help_about_tab_replays_the_intro_and_resets_it(svc, root, monkeypatch):
    import views.help as vh
    uid = None
    with svc.transaction() as cur:
        cur.execute("INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('ADM-2026-001','Admin','Admin','Active')")
        uid = cur.lastrowid
    view = vh.HelpView(root, {"user_id": uid, "role": "Admin", "full_name": "Admin"})
    view.pack(fill="both", expand=True)
    pump(root, 0.5)
    about = next(v for v in view.seg_btn._value_list if "About" in v)
    view.seg_btn.set(about)
    view.switch_tab(about)
    pump(root, 0.2)
    prefs.set("intro_seen", True)
    buttons = [w for w in view.tab_content.winfo_children()[0].winfo_children()[-2].winfo_children() if hasattr(w, "_text")]
    reset = next(b for b in buttons if "again" in b._text)
    reset.invoke()
    assert intro.should_show_intro()
    replay = next(b for b in buttons if "Replay" in b._text)
    replay.invoke()
    pump(root, 0.3)
    assert any(isinstance(w, intro.IntroWindow) for w in root.winfo_toplevel().winfo_children())
