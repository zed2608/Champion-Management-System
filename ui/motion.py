"""Small colour transitions for hover and click, built on Tk's ``after()`` (no threads, never blocks the UI).

    tween_color(widget, "fg_color", "#1E4528", "#14301C")      # fades over ~120 ms in a few steps
    enhance_button(button)                                       # hover fade + short press effect + pointer cursor
    hover_fade(widget, normal, hover)                            # same, for a card / row / label

Rules
  * ``CHAMPION_REDUCE_MOTION=1`` (in the environment or in .env) turns every transition off: colours change at once.
  * A new transition on the same widget and attribute cancels the running one; destroying the widget cancels its jobs; a job that runs after
    its widget is gone does nothing (no Tk errors).
  * Only real ``#RRGGBB`` colours are faded. "transparent" is faded from/to the colour of the nearest parent that has one.
"""
import os
import re
import tkinter as tk
from pathlib import Path

from ui import theme as T

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
STEPS = 6
_env_loaded = False


def reduced_motion():
    """True when animations are switched off (``CHAMPION_REDUCE_MOTION`` = 1/true/yes/on, from the environment or the project's .env)."""
    global _env_loaded
    if not _env_loaded:
        _env_loaded = True
        try:
            from dotenv import load_dotenv
            load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
        except Exception:
            pass
    return str(os.getenv("CHAMPION_REDUCE_MOTION", "")).strip().lower() in ("1", "true", "yes", "on")


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t):
    """The colour ``t`` (0..1) of the way from hex colour a to hex colour b."""
    ra, rb = _rgb(a), _rgb(b)
    return "#%02X%02X%02X" % tuple(round(x + (y - x) * t) for x, y in zip(ra, rb))


def darken(color, amount=0.12):
    return mix(color, "#000000", amount)


def frames(start, end, steps=STEPS):
    """The colours shown during a fade, last one exactly ``end``."""
    return [mix(start, end, i / steps) for i in range(1, steps + 1)]


def _as_hex(color):
    if isinstance(color, (list, tuple)):
        color = color[0]
    return color if isinstance(color, str) and _HEX.match(color) else None


def resolve_background(widget):
    """The colour a transparent widget really shows: the nearest parent with a real fg_color."""
    w = widget
    while w is not None:
        try:
            c = _as_hex(w.cget("fg_color"))
        except Exception:
            c = None
        if c:
            return c
        w = getattr(w, "master", None)
    return T.BG


def _jobs(widget):
    if not hasattr(widget, "_motion_jobs"):
        widget._motion_jobs = {}
        try:
            widget.bind("<Destroy>", lambda e, w=widget: cancel(w) if e.widget is w else None, add="+")
        except Exception:
            pass
    return widget._motion_jobs


def cancel(widget, attr=None):
    """Stop the running transition(s) of a widget (a screen calls this when it closes)."""
    jobs = getattr(widget, "_motion_jobs", None)
    if not jobs:
        return
    for key in ([attr] if attr else list(jobs)):
        job = jobs.pop(key, None)
        if job is not None:
            try:
                widget.after_cancel(job)
            except Exception:
                pass


def tween_color(widget, attr, start, end, ms=T.ANIM_FAST, final=None):
    """Fade ``attr`` of ``widget`` from ``start`` to ``end``. ``final`` is what to leave in the end (e.g. "transparent")."""
    cancel(widget, attr)
    target = final if final is not None else end
    a, b = _as_hex(start), _as_hex(end)
    if reduced_motion() or not a or not b or a == b:
        _apply(widget, attr, target)
        return
    seq = frames(a, b)
    delay = max(10, int(ms / len(seq)))
    jobs = _jobs(widget)

    def step(i=0):
        jobs.pop(attr, None)
        try:
            if not widget.winfo_exists():
                return
            _apply(widget, attr, seq[i] if i < len(seq) - 1 else target)
            if i < len(seq) - 1:
                jobs[attr] = widget.after(delay, step, i + 1)
        except tk.TclError:
            return
    step(0)


def _apply(widget, attr, color):
    try:
        widget.configure(**{attr: color})
        if not hasattr(widget, "_motion_last"):
            widget._motion_last = {}
        widget._motion_last[attr] = color
    except (tk.TclError, ValueError):
        pass


def _changed_by_someone_else(widget, attr="fg_color"):
    """True when the screen has set a new colour since our last step (e.g. the sidebar marked this button as the active page)."""
    last = getattr(widget, "_motion_last", {}).get(attr)
    return last is not None and widget.cget(attr) != last


def _pointer_inside(widget):
    try:
        x, y = widget.winfo_pointerxy()
        wx, wy = widget.winfo_rootx(), widget.winfo_rooty()
        return wx <= x < wx + widget.winfo_width() and wy <= y < wy + widget.winfo_height()
    except Exception:
        return False


def count_up(label, target, fmt=lambda v: f"{v:g}", ms=400, steps=10):
    """Show ``fmt(target)`` in ``label``, counting from what it showed before (0 the first time) over about 400 ms.
    Nothing happens when the number did not change; with reduced motion the number is simply set."""
    try:
        target = float(target)
    except (TypeError, ValueError):
        label.configure(text=str(target))
        return
    previous = getattr(label, "_count_value", None)
    label._count_value = target
    cancel(label, "count")
    if previous == target:
        _apply(label, "text", fmt(target))
        return
    start = 0.0 if previous is None else previous
    if reduced_motion() or ms <= 0:
        _apply(label, "text", fmt(target))
        return
    jobs = _jobs(label)
    delay = max(10, ms // steps)

    def step(i=1):
        jobs.pop("count", None)
        try:
            if not label.winfo_exists():
                return
            t = i / steps
            eased = 1 - (1 - t) ** 2                                   # fast at first, settles gently
            value = target if i >= steps else start + (target - start) * eased
            if i < steps and float(target).is_integer() and float(start).is_integer():
                value = round(value)
            _apply(label, "text", fmt(value))
            if i < steps:
                jobs["count"] = label.after(delay, step, i + 1)
        except tk.TclError:
            return
    step(1)


def hover_fade(widget, normal, hover, attr="fg_color", ms=T.ANIM_FAST, pointer=True, targets=None):
    """Fade ``widget`` to ``hover`` while the mouse is over it (or over any of ``targets``, e.g. its labels)."""
    if pointer:
        try:
            widget.configure(cursor="hand2")
        except Exception:
            pass
    state = {"over": False}

    def enter(_e=None):
        if not state["over"]:
            state["over"] = True
            tween_color(widget, attr, normal() if callable(normal) else normal, hover() if callable(hover) else hover, ms)

    def leave(e=None):
        if _pointer_inside(widget):                      # moved onto a child of the same card: still inside
            return
        state["over"] = False
        tween_color(widget, attr, hover() if callable(hover) else hover, normal() if callable(normal) else normal, ms)

    for w in [widget, *(targets or [])]:
        try:
            w.bind("<Enter>", enter, add="+")
            w.bind("<Leave>", leave, add="+")
        except Exception:
            pass


def enhance_button(btn, ms=T.ANIM_FAST):
    """Hover fade, a short darker "press" and a pointer cursor for a CTkButton. Disabled buttons stay still."""
    try:
        btn.configure(hover=False, cursor="hand2")      # we do the hover ourselves, with a fade
    except Exception:
        return btn
    state = {"normal": None, "pressed": False}

    def colours():
        raw = btn.cget("fg_color")
        transparent = raw == "transparent"
        normal = resolve_background(btn.master) if transparent else (_as_hex(raw) or None)
        hover = _as_hex(btn.cget("hover_color"))
        return raw, normal, hover, transparent

    def enter(_e=None):
        if str(btn.cget("state")) == "disabled":
            return
        raw, normal, hover, transparent = colours()
        state["normal"] = raw
        if hover and normal:
            tween_color(btn, "fg_color", normal, hover, ms)

    def leave(_e=None):
        if state["normal"] is None:
            return
        if _changed_by_someone_else(btn):                # e.g. a click made this the active sidebar item: keep what the screen chose
            state["normal"] = None
            return
        raw, normal, hover, transparent = colours()
        back = state["normal"]
        state["normal"] = None
        tween_color(btn, "fg_color", _as_hex(btn.cget("fg_color")) or hover or "#000000",
                    (resolve_background(btn.master) if back == "transparent" else _as_hex(back)) or "#000000", ms, final=back)

    def press(_e=None):
        if str(btn.cget("state")) == "disabled":
            return
        h = _as_hex(btn.cget("hover_color")) or _as_hex(btn.cget("fg_color"))
        if h and not reduced_motion():
            cancel(btn, "fg_color")
            _apply(btn, "fg_color", darken(h))

    def release(_e=None):
        if state["normal"] is not None:
            raw, normal, hover, transparent = colours()
            if hover:
                tween_color(btn, "fg_color", _as_hex(btn.cget("fg_color")) or hover, hover, 80)

    btn.bind("<Enter>", enter, add="+")
    btn.bind("<Leave>", leave, add="+")
    btn.bind("<ButtonPress-1>", press, add="+")
    btn.bind("<ButtonRelease-1>", release, add="+")
    return btn
