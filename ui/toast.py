"""Non-modal notifications: small cards stacked at the top right that dismiss themselves, with a thin timer bar.

    host = ToastHost(window)              # once per main window
    host.show("Tool archived.")           # success (default)
    host.show("Could not save.", kind="error")

Rules
  * Toasts never block anything and never need a click; clicking one dismisses it early.
  * They sit LEFT of the page header's primary button column (``RIGHT_CLEAR`` px from the right edge) and below the top bar, so the primary
    action of a screen is never covered. At most ``MAX_VISIBLE`` are shown; older ones are dropped first.
  * A confirmation dialog that guards a destructive action is NOT replaced by a toast: toasts only report what already happened.
  * With CHAMPION_REDUCE_MOTION=1 the timer bar does not animate (the toast still disappears on time).
  * All timers are cancelled when the host or a toast is destroyed.
"""
import customtkinter as ctk

from ui import motion
from ui import theme as T

RIGHT_CLEAR = 230          # px kept free at the right edge (the primary button column)
TOP = 72                   # px below the top of the window (under the top bar)
WIDTH = 340
GAP = 8
MAX_VISIBLE = 4
TICK_MS = 50

KINDS = {
    "success": dict(bg=T.SUCCESS_BG, fg=T.SUCCESS_TEXT, bar=T.SUCCESS, icon="✓"),
    "error": dict(bg=T.DANGER_BG, fg=T.DANGER_TEXT, bar=T.DANGER, icon="✕"),
    "warning": dict(bg=T.WARNING_BG, fg=T.WARNING_TEXT, bar=T.WARNING, icon="!"),
    "info": dict(bg=T.INFO_BG, fg=T.INFO_TEXT, bar=T.INFO, icon="i"),
}


class Toast(ctk.CTkFrame):
    def __init__(self, host, message, kind, ms):
        style = KINDS.get(kind, KINDS["info"])
        super().__init__(host.window, fg_color=style["bg"], corner_radius=T.RADIUS_MD, border_width=1, border_color=style["bar"], width=WIDTH)
        self.host, self._total, self._left, self._job = host, max(500, ms), max(500, ms), None
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="x", padx=T.S3, pady=(T.S3, T.S2))
        ctk.CTkLabel(body, text=style["icon"], width=22, font=T.font(14, "bold"), text_color=style["fg"]).pack(side="left", anchor="n")
        self.message_label = ctk.CTkLabel(body, text=message, font=T.font(12, "bold"), text_color=T.TEXT, wraplength=WIDTH - 80, justify="left", anchor="w")
        self.message_label.pack(side="left", fill="x", expand=True, padx=(T.S2, 0))
        self.bar = ctk.CTkProgressBar(self, height=3, corner_radius=0, fg_color=style["bg"], progress_color=style["bar"])
        self.bar.set(1.0)
        self.bar.pack(fill="x", padx=1, pady=(0, 1))
        self.configure(cursor="hand2")
        for w in (self, body, self.message_label):
            w.bind("<Button-1>", lambda e: self.dismiss(), add="+")
        self._job = self.after(TICK_MS, self._tick)

    def _tick(self):
        self._job = None
        self._left -= TICK_MS
        if self._left <= 0:
            self.dismiss()
            return
        if not motion.reduced_motion():
            try:
                self.bar.set(self._left / self._total)
            except Exception:
                return
        self._job = self.after(TICK_MS, self._tick)

    def dismiss(self):
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        self.host._remove(self)


class ToastHost:
    def __init__(self, window):
        self.window = window
        self.toasts = []
        window.bind("<Configure>", lambda e: self.layout() if e.widget is window else None, add="+")
        window.bind("<Destroy>", lambda e: self.clear() if e.widget is window else None, add="+")

    def show(self, message, kind="success", ms=3500):
        while len(self.toasts) >= MAX_VISIBLE:
            self.toasts[0].dismiss()
        toast = Toast(self, str(message), kind, ms)
        self.toasts.append(toast)
        self.layout()
        return toast

    def layout(self):
        try:
            width = self.window.winfo_width()
        except Exception:
            return
        y = TOP
        for t in list(self.toasts):
            try:
                t.place(x=max(8, width - RIGHT_CLEAR - WIDTH), y=y)
                t.lift()
                t.update_idletasks()
                y += t.winfo_reqheight() + GAP
            except Exception:
                pass

    def _remove(self, toast):
        if toast in self.toasts:
            self.toasts.remove(toast)
        try:
            toast.destroy()
        except Exception:
            pass
        self.layout()

    def clear(self):
        for t in list(self.toasts):
            try:
                if t._job is not None:
                    t.after_cancel(t._job)
            except Exception:
                pass
        self.toasts.clear()
