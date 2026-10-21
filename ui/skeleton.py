"""Plain grey placeholder blocks shown while data loads, so a screen never flashes an empty frame.

    sk = Skeleton(parent, rows=6)          # grey bars with a gentle pulse; ``sk.destroy()`` when the real content arrives

The pulse is a slow colour fade between two greys (off with CHAMPION_REDUCE_MOTION=1); it stops by itself when the placeholder is destroyed.
"""
import customtkinter as ctk

from ui import motion
from ui import theme as T

WIDTHS = (0.92, 0.78, 0.86, 0.64, 0.9, 0.7, 0.82, 0.58)       # of the available width, so the bars look like uneven text rows
PULSE_MS = 700


class Skeleton(ctk.CTkFrame):
    def __init__(self, parent, rows=6, row_height=18, **kw):
        super().__init__(parent, fg_color="transparent", **kw)
        self.blocks = []
        for i in range(rows):
            holder = ctk.CTkFrame(self, fg_color="transparent", height=row_height + T.S3)
            holder.pack(fill="x", padx=T.S4, pady=(T.S1, T.S1))
            holder.pack_propagate(False)
            block = ctk.CTkFrame(holder, fg_color=T.SURFACE_MUTED, corner_radius=T.RADIUS_SM, height=row_height)
            block.place(relx=0, rely=0.5, relwidth=WIDTHS[i % len(WIDTHS)], anchor="w")
            self.blocks.append(block)
        self._job, self._phase, self._dead = None, 0, False
        if not motion.reduced_motion():
            self._job = self.after(PULSE_MS, self._pulse)

    def _pulse(self):
        self._job = None
        if self._dead:
            return
        self._phase ^= 1
        a, b = (T.SURFACE_MUTED, T.BORDER) if self._phase else (T.BORDER, T.SURFACE_MUTED)
        for block in self.blocks:
            motion.tween_color(block, "fg_color", a, b, T.ANIM_SLOW)
        self._job = self.after(PULSE_MS, self._pulse)

    def destroy(self):
        self._dead = True
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
        super().destroy()
