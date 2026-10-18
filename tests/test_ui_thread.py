"""UiMixin: worker threads hand results to the Tk thread through a queue, and a destroyed screen never receives anything."""
import threading
import time

import customtkinter as ctk
import pytest

from conftest import make_window
from views.ui_thread import UiMixin


class Screen(UiMixin, ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color="transparent")
        self._ui_init()
        self.log = []


@pytest.fixture
def root():
    r = make_window(ctk.CTk)
    r.geometry("300x200+0+0")
    yield r
    r.destroy()


def pump(root, until, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        root.update()
        if until():
            return True
        time.sleep(0.01)
    return until()


def test_worker_result_runs_on_the_tk_thread(root):
    s = Screen(root)
    s.pack()
    main = threading.get_ident()
    seen = {}

    def work():
        s.post_ui(lambda: seen.update(thread=threading.get_ident(), value=42))
    t = threading.Thread(target=work)
    t.start()
    t.join()
    assert pump(root, lambda: "value" in seen)
    assert seen["thread"] == main and seen["value"] == 42                  # NOT the worker thread


def test_post_from_a_thread_works_even_when_the_loop_is_not_running(root):
    s = Screen(root)
    s.pack()
    t = threading.Thread(target=lambda: s.post_ui(lambda: s.log.append("ok")))
    t.start()
    t.join()                                                                  # self.after() here would raise "main thread is not in main loop"
    assert pump(root, lambda: s.log == ["ok"])


def test_after_jobs_are_cancelled_when_the_screen_is_destroyed(root):
    s = Screen(root)
    s.pack()
    s.after(150, lambda: s.log.append("late"))
    s.after(10, lambda: s.log.append("early"))
    assert pump(root, lambda: s.log == ["early"])
    assert len(s._ui_after_ids) == 1                                          # the fired job was forgotten, the pending one is tracked
    s.destroy()
    log = s.log
    pump(root, lambda: False, timeout=0.4)
    assert log == ["early"]                                                   # "late" never fired into a dead widget


def test_nothing_is_delivered_to_a_destroyed_screen(root):
    s = Screen(root)
    s.pack()
    s.destroy()
    s.post_ui(lambda: s.log.append("ghost"))
    pump(root, lambda: False, timeout=0.3)
    assert s.log == []


def test_exception_in_a_posted_callable_does_not_stop_later_ones(root):
    s = Screen(root)
    s.pack()

    def boom():
        raise RuntimeError("bad update")
    s.post_ui(boom)
    s.post_ui(lambda: s.log.append("after boom"))
    assert pump(root, lambda: s.log == ["after boom"])


def test_after_cancel_still_works(root):
    s = Screen(root)
    s.pack()
    job = s.after(100, lambda: s.log.append("never"))
    s.after_cancel(job)
    pump(root, lambda: False, timeout=0.3)
    assert s.log == [] and job not in s._ui_after_ids
