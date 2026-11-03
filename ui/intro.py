"""Start-up experience: a short splash, then (first launch only) a four-slide intro. Both are reachable again from Help > About.

    run_startup(login_window)        # splash -> intro (if not dismissed) -> shows the login window

Rules: the splash lasts about 1.5 s (a progress line fills); the intro takes under 20 seconds to read, has Next / Back / Skip, progress dots,
left/right arrow keys and a "Don't show again" box that is remembered in ui_prefs.json. With CHAMPION_REDUCE_MOTION=1 the splash is
shorter and the progress line does not animate. Nothing here touches the database.
"""
import customtkinter as ctk

from ui import components as C
from ui import motion, prefs
from ui import theme as T

SPLASH_MS = 1500
SLIDES = [
    ("The problem",
     ["Oily hands, skipped logbooks, phantom inventory.",
      "About P10,000 in tools is lost every month."]),
    ("How it works",
     ["Scan the worker's badge and the tool's tag.",
      "Issue, return, and see the insight."]),
    ("Decision support",
     ["ABC analysis, wear forecast, anomaly alerts",
      "and a tamper-evident audit chain."]),
    ("About the project",
     ["Cayper Tech, Technological Institute of the Philippines.",
      "Software Engineering 2 and Project Management 3.",
      "Client: Champion Fine Tooling Corporation.",
      "Team (roles to be added):",
      "Cyrus Austin G. Andal, Charles Joseph S. Peralta,",
      "Angelo Genesis N. Talastas, Ayzhiedy Jee D. Reyes"]),
]
ABOUT_TEAM_NOTE = ("Team members (roles to be added): Cyrus Austin G. Andal, Charles Joseph S. Peralta, "
                   "Angelo Genesis N. Talastas, Ayzhiedy Jee D. Reyes")


def should_show_intro():
    return not prefs.get("intro_seen", False)


def _center(win, w, h):
    win.update_idletasks()
    x, y = (win.winfo_screenwidth() - w) // 2, (win.winfo_screenheight() - h) // 3
    win.geometry(f"{w}x{h}+{x}+{y}")


class SplashScreen(ctk.CTkToplevel):
    """Borderless, about 1.5 seconds, a thin progress line. ``on_done`` is called when it closes."""

    def __init__(self, parent, on_done=None, ms=None):
        super().__init__(parent, fg_color=T.PRIMARY)
        self.overrideredirect(True)
        C.keep_above(self, parent)
        _center(self, 460, 260)
        self.on_done = on_done
        self._ms = ms if ms is not None else (800 if motion.reduced_motion() else SPLASH_MS)
        ctk.CTkLabel(self, text="CHAMPION FINE TOOLING", font=T.font(20, "bold"), text_color=T.ON_PRIMARY).pack(pady=(70, 4))
        ctk.CTkLabel(self, text="Automated Management System", font=T.font(14), text_color=T.GREEN_TINT).pack()
        self.bar = ctk.CTkProgressBar(self, width=300, height=3, corner_radius=0, fg_color=T.PRIMARY_HOVER, progress_color=T.ACCENT)
        self.bar.pack(pady=(44, 0))
        self.bar.set(1.0 if motion.reduced_motion() else 0.0)
        self._t, self._job, self._finished = 0, None, False
        self._job = self.after(30, self._tick)

    def _tick(self):
        self._job = None
        self._t += 30
        if not motion.reduced_motion():
            self.bar.set(min(1.0, self._t / self._ms))
        if self._t >= self._ms:
            self.finish()
            return
        self._job = self.after(30, self._tick)

    def finish(self):
        if self._finished:
            return
        self._finished = True
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
        callback = self.on_done
        self.destroy()
        if callback:
            callback()


class IntroWindow(ctk.CTkToplevel):
    """Four slides. Closing it by any route (Skip, Done, the window's X, Escape) saves the "Don't show again" choice."""

    def __init__(self, parent, on_done=None, first_run=True):
        super().__init__(parent, fg_color=T.SURFACE)
        self.title("Welcome")
        self.resizable(False, False)
        self.on_done, self.index, self._closed = on_done, 0, False
        _center(self, 720, 440)
        C.keep_above(self, parent)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.card = C.card(self)
        self.card.pack(fill="both", expand=True, padx=T.S4, pady=(T.S4, T.S2))
        self.title_label = ctk.CTkLabel(self.card, text="", font=T.font(28, "bold"), text_color=T.PRIMARY, anchor="w")
        self.title_label.pack(anchor="w", padx=T.S6, pady=(T.S6, T.S3))
        self.body = ctk.CTkFrame(self.card, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=T.S6)
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=T.S4, pady=(0, T.S4))
        self.dont_show = ctk.CTkCheckBox(foot, text="Don't show again", font=T.font(12), text_color=T.TEXT)
        self.dont_show.pack(side="left")
        if first_run:
            self.dont_show.select()                                   # a first launch is shown once; un-tick it to see the intro again
        self.next_btn = C.button(foot, "Next ▶", self.next, "primary", width=90)
        self.next_btn.pack(side="right")
        self.back_btn = C.button(foot, "◀ Back", self.back, "secondary", width=90)
        self.back_btn.pack(side="right", padx=T.S2)
        self.skip_btn = C.button(foot, "Skip", self.close, "ghost", width=70)
        self.skip_btn.pack(side="right", padx=T.S2)
        self.dots = ctk.CTkFrame(foot, fg_color="transparent")
        self.dots.pack(side="right", padx=T.S4)
        self._dot_labels = [ctk.CTkLabel(self.dots, text="●", font=T.font(14), text_color=T.BORDER_STRONG, width=18) for _ in SLIDES]
        for d in self._dot_labels:
            d.pack(side="left")
        self.bind("<Right>", lambda e: self.next())
        self.bind("<Left>", lambda e: self.back())
        self.bind("<Escape>", lambda e: self.close())
        self._show()
        self.after(150, self.focus_force)

    def _show(self):
        title, lines = SLIDES[self.index]
        self.title_label.configure(text=title)
        for w in self.body.winfo_children():
            w.destroy()
        for line in lines:
            ctk.CTkLabel(self.body, text=line, font=T.font(16), text_color=T.TEXT, anchor="w", justify="left").pack(anchor="w", pady=3)
        for i, d in enumerate(self._dot_labels):
            d.configure(text_color=T.PRIMARY if i == self.index else T.BORDER_STRONG)
        self.back_btn.configure(state="normal" if self.index > 0 else "disabled")
        self.next_btn.configure(text="Done ✓" if self.index == len(SLIDES) - 1 else "Next ▶")

    def next(self):
        if self.index >= len(SLIDES) - 1:
            self.close()
        else:
            self.index += 1
            self._show()

    def back(self):
        if self.index > 0:
            self.index -= 1
            self._show()

    def close(self):
        if self._closed:
            return
        self._closed = True
        prefs.set("intro_seen", bool(int(self.dont_show.get())))
        callback = self.on_done
        self.destroy()
        if callback:
            callback()


def run_startup(window):
    """Hide the login window, show the splash, then the intro if it has not been dismissed, then reveal the login window."""
    window.withdraw()

    def reveal():
        window.deiconify()
        window.lift()
        window.focus_force()

    def after_splash():
        if should_show_intro():
            IntroWindow(window, on_done=reveal)
        else:
            reveal()
    SplashScreen(window, on_done=after_splash)
