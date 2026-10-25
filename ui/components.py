"""Uniform building blocks for every screen: cards, the four-button set, form fields, the page header and the "More" menu.

Screens call these instead of styling CustomTkinter widgets by hand, so every screen looks and sizes the same.
They return ordinary CustomTkinter widgets (a button is still a CTkButton), so existing code that reads ``_text`` or calls ``configure`` keeps working.
Colours, fonts and sizes come from ui.theme only.
"""
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from ui import motion
from ui import theme as T

def apply_widget_defaults():
    """Make every CustomTkinter widget that a screen does not style by hand pick up the brand colours (the stock "green" theme is mint
    with white text, about 2:1 contrast). Idempotent: safe to call more than once."""
    th = ctk.ThemeManager.theme
    both = lambda name: [getattr(T, name), T.DARK.get(name, getattr(T, name))]
    patch = {
        "CTkButton": dict(fg_color=both("PRIMARY"), hover_color=both("PRIMARY_HOVER"), text_color=both("ON_PRIMARY"), text_color_disabled=both("TEXT_MUTED"),
                          corner_radius=T.RADIUS_SM),
        "CTkOptionMenu": dict(fg_color=both("SURFACE_ALT"), button_color=both("BORDER"), button_hover_color=both("BORDER_STRONG"),
                              text_color=both("TEXT"), dropdown_fg_color=both("SURFACE"), dropdown_text_color=both("TEXT"),
                              dropdown_hover_color=both("SURFACE_MUTED"), corner_radius=T.RADIUS_SM),
        "CTkComboBox": dict(fg_color=both("SURFACE"), border_color=both("BORDER_STRONG"), button_color=both("PRIMARY"),
                            button_hover_color=both("PRIMARY_HOVER"), text_color=both("TEXT"), corner_radius=T.RADIUS_SM),
        "CTkSegmentedButton": dict(fg_color=both("SURFACE_MUTED"), selected_color=both("PRIMARY"), selected_hover_color=both("PRIMARY_HOVER"),
                                   unselected_color=both("TEXT_SECONDARY"), unselected_hover_color=both("TEXT"), text_color=both("ON_PRIMARY"),
                                   text_color_disabled=both("TEXT_MUTED")),
        "CTkCheckBox": dict(fg_color=both("PRIMARY"), hover_color=both("PRIMARY_HOVER"), border_color=both("BORDER_STRONG"),
                            checkmark_color=both("ON_PRIMARY"), text_color=both("TEXT")),
        "CTkSwitch": dict(progress_color=both("PRIMARY"), button_color=both("SURFACE"), button_hover_color=both("SURFACE_MUTED")),
        "CTkProgressBar": dict(fg_color=both("BORDER"), progress_color=both("PRIMARY")),
        "CTkScrollbar": dict(button_color=both("BORDER_STRONG"), button_hover_color=both("TEXT_MUTED")),
        "CTkEntry": dict(fg_color=both("SURFACE"), border_color=both("BORDER_STRONG"), text_color=both("TEXT"),
                         placeholder_text_color=both("TEXT_PLACEHOLDER")),
        "CTkTextbox": dict(fg_color=both("SURFACE"), border_color=both("BORDER_STRONG"), text_color=both("TEXT"),
                           scrollbar_button_color=both("BORDER_STRONG"), scrollbar_button_hover_color=both("TEXT_MUTED")),
        "CTkLabel": dict(text_color=both("TEXT")),
    }
    for widget, values in patch.items():
        th.setdefault(widget, {}).update(values)


apply_widget_defaults()

BUTTON_KINDS = {
    "primary": dict(fg_color=T.PRIMARY, hover_color=T.PRIMARY_HOVER, text_color=T.ON_PRIMARY),
    "secondary": dict(fg_color=T.BORDER, hover_color=T.BORDER_STRONG, text_color=T.TEXT),
    "ghost": dict(fg_color="transparent", hover_color=T.SURFACE_MUTED, text_color=T.PRIMARY),
    "danger": dict(fg_color=T.DANGER, hover_color=T.DANGER_HOVER, text_color=T.ON_DANGER),
}
BUTTON_HEIGHT = T.BUTTON_HEIGHT          # every normal button
BUTTON_HEIGHT_COMPACT = 28               # buttons inside table rows
FIELD_HEIGHT = T.FIELD_HEIGHT


def fit_window(window, width, height, margin=60):
    """Center a dialog while keeping its footer inside the screen."""
    sw, sh = window.winfo_screenwidth(), window.winfo_screenheight()
    w, h = min(width, max(320, sw - margin)), min(height, max(320, sh - margin))
    window.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2)}")


def keep_above(window, parent=None):
    """Keep a newly opened window above the window that opened it."""
    previous_grab = window.grab_current()
    if previous_grab is window:
        previous_grab = None
    owner = parent if parent is not None else window.master
    if owner is not None:
        owner = owner.winfo_toplevel()
        if owner is not window:
            # The start-up splash and intro open while login is withdrawn.
            # A transient child of a withdrawn window would also disappear.
            try:
                visible = bool(owner.winfo_viewable())
            except AttributeError:
                visible = True
            if visible:
                window.transient(owner)
    window.attributes("-topmost", True)
    window.lift()

    def raise_after_map():
        try:
            if window.winfo_exists():
                window.lift()
                window.focus_force()
        except tk.TclError:
            pass

    window.after_idle(raise_after_map)

    def restore_parent(event):
        if event.widget is not window or previous_grab is None:
            return
        try:
            if previous_grab.winfo_exists():
                previous_grab.grab_set()
                previous_grab.lift()
                previous_grab.focus_force()
        except tk.TclError:
            pass

    window.bind("<Destroy>", restore_parent, add="+")


def _confirm_window(title, message, parent):
    """An explicit, foreground Yes/No window for nested project and item panels."""
    owner = parent.winfo_toplevel()
    previous_grab = owner.grab_current()
    dialog = ctk.CTkToplevel(owner)
    dialog.withdraw()
    dialog.title(title)
    dialog.configure(fg_color=T.SURFACE)
    dialog.resizable(False, False)
    result = {"yes": False}

    body = ctk.CTkFrame(dialog, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=22, pady=(20, 10))
    ctk.CTkLabel(body, text=title, font=T.font(16, "bold"), text_color=T.PRIMARY,
                 anchor="w").pack(fill="x", pady=(0, 12))
    details = ctk.CTkScrollableFrame(body, fg_color=T.SURFACE_ALT, height=130)
    details.pack(fill="both", expand=True)
    ctk.CTkLabel(details, text=message, font=T.font(12), text_color=T.TEXT,
                 wraplength=380, justify="left", anchor="w").pack(fill="x", padx=12, pady=12)
    actions = ctk.CTkFrame(body, fg_color="transparent")
    actions.pack(fill="x", pady=(14, 0))

    def close(yes=False):
        result["yes"] = yes
        dialog.destroy()

    button(actions, text="Cancel", command=lambda: close(False), kind="secondary", width=100).pack(side="right")
    button(actions, text="Confirm", command=lambda: close(True), kind="primary", width=100).pack(side="right", padx=(0, 8))
    dialog.protocol("WM_DELETE_WINDOW", lambda: close(False))
    dialog.bind("<Escape>", lambda _event: close(False))
    fit_window(dialog, 460, 290)
    keep_above(dialog, owner)
    dialog.deiconify()
    dialog.grab_set()
    dialog.focus_force()
    try:
        owner.wait_window(dialog)
    finally:
        if previous_grab is not None:
            try:
                if previous_grab.winfo_exists():
                    previous_grab.grab_set()
                    previous_grab.lift()
            except tk.TclError:
                pass
    return result["yes"]


def _notice_window(title, message, parent, kind):
    """Show validation, error and success notices in front of their owner."""
    owner = parent.winfo_toplevel()
    previous_grab = owner.grab_current()
    dialog = ctk.CTkToplevel(owner)
    dialog.withdraw()
    dialog.title(title)
    dialog.configure(fg_color=T.SURFACE)
    dialog.resizable(False, False)
    body = ctk.CTkFrame(dialog, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=22, pady=(20, 16))
    color = T.DANGER_TEXT if kind == "showerror" else (T.WARNING_TEXT if kind == "showwarning" else T.PRIMARY)
    ctk.CTkLabel(body, text=title, font=T.font(16, "bold"), text_color=color,
                 anchor="w").pack(fill="x", pady=(0, 12))
    details = ctk.CTkScrollableFrame(body, fg_color=T.SURFACE_ALT, height=120)
    details.pack(fill="both", expand=True)
    ctk.CTkLabel(details, text=message, font=T.font(12), text_color=T.TEXT,
                 wraplength=380, justify="left", anchor="w").pack(fill="x", padx=12, pady=12)
    button(body, text="OK", command=dialog.destroy, kind="primary", width=100).pack(anchor="e", pady=(14, 0))
    dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
    dialog.bind("<Escape>", lambda _event: dialog.destroy())
    fit_window(dialog, 460, 270)
    keep_above(dialog, owner)
    dialog.deiconify()
    dialog.grab_set()
    dialog.focus_force()
    try:
        owner.wait_window(dialog)
    finally:
        if previous_grab is not None:
            try:
                if previous_grab.winfo_exists():
                    previous_grab.grab_set()
                    previous_grab.lift()
            except tk.TclError:
                pass
    return "ok"


def ask_text(title, message, *, parent, initialvalue=""):
    """Get a short value above the active form; Cancel returns None."""
    owner = parent.winfo_toplevel()
    previous_grab = owner.grab_current()
    dialog = ctk.CTkToplevel(owner)
    dialog.withdraw()
    dialog.title(title)
    dialog.configure(fg_color=T.SURFACE)
    dialog.resizable(False, False)
    ctk.CTkLabel(dialog, text=message, font=T.font(12), text_color=T.TEXT,
                 justify="left", wraplength=380).pack(anchor="w", padx=22, pady=(20, 12))
    entry = field(dialog)
    entry.pack(fill="x", padx=22)
    if initialvalue:
        entry.insert(0, initialvalue)
    answer = {"value": None}

    def finish(accept):
        if accept:
            answer["value"] = entry.get()
        dialog.destroy()

    actions = ctk.CTkFrame(dialog, fg_color="transparent")
    actions.pack(fill="x", padx=22, pady=(18, 18))
    button(actions, text="Cancel", command=lambda: finish(False), kind="secondary", width=100).pack(side="right")
    button(actions, text="Continue", command=lambda: finish(True), kind="primary", width=100).pack(side="right", padx=(0, 8))
    dialog.protocol("WM_DELETE_WINDOW", lambda: finish(False))
    dialog.bind("<Escape>", lambda _event: finish(False))
    entry.bind("<Return>", lambda _event: finish(True))
    fit_window(dialog, 460, 220)
    keep_above(dialog, owner)
    dialog.deiconify()
    dialog.grab_set()
    entry.focus_set()
    try:
        owner.wait_window(dialog)
    finally:
        if previous_grab is not None:
            try:
                if previous_grab.winfo_exists():
                    previous_grab.grab_set()
                    previous_grab.lift()
            except tk.TclError:
                pass
    return answer["value"]


def _install_foreground_notices():
    # Every view imports tkinter.messagebox itself; patching the module once
    # covers warnings and errors in camera, project and inventory workflows.
    for kind in ("showinfo", "showwarning", "showerror"):
        original = getattr(messagebox, kind)

        def show(title=None, message=None, *, _kind=kind, _original=original, **options):
            parent = options.get("parent")
            if parent is not None and hasattr(parent, "tk"):
                return _notice_window(str(title or "Notice"), str(message or ""), parent, _kind)
            return _original(title, message, **options)

        setattr(messagebox, kind, show)


_install_foreground_notices()


def button(parent, text="", command=None, kind="primary", compact=False, **kw):
    """One of four buttons: primary (filled green), secondary (grey), ghost (text only) or danger (red). Fixed height, pointer cursor."""
    style = BUTTON_KINDS[kind]
    kw.pop("height", None)
    kw.pop("corner_radius", None)
    btn = ctk.CTkButton(parent, text=text, command=command, height=BUTTON_HEIGHT_COMPACT if compact else BUTTON_HEIGHT,
                         corner_radius=T.RADIUS_SM, font=kw.pop("font", T.font(12, "bold")), cursor="hand2",
                         fg_color=kw.pop("fg_color", style["fg_color"]), hover_color=kw.pop("hover_color", style["hover_color"]),
                         text_color=kw.pop("text_color", style["text_color"]), text_color_disabled=kw.pop("text_color_disabled", T.TEXT_MUTED),
                         **kw)
    return motion.enhance_button(btn)               # hover fade, press effect, pointer cursor (all off under CHAMPION_REDUCE_MOTION=1)


def field(parent, **kw):
    """A text box with the standard height, border and font. ``placeholder_text``, ``textvariable``, ``show`` and ``width`` pass through.
    (CustomTkinter never shows a placeholder when a textvariable is attached, so in that case a grey hint label sits inside the box.)"""
    kw.pop("height", None)
    kw.pop("corner_radius", None)
    placeholder, var = kw.get("placeholder_text"), kw.get("textvariable")
    entry = ctk.CTkEntry(parent, height=FIELD_HEIGHT, corner_radius=T.RADIUS_SM, fg_color=kw.pop("fg_color", T.SURFACE),
                         border_color=kw.pop("border_color", T.BORDER_STRONG), border_width=1, text_color=kw.pop("text_color", T.TEXT),
                         placeholder_text_color=T.TEXT_PLACEHOLDER, font=kw.pop("font", T.font(12)), **kw)
    if var is not None and placeholder:
        hint = ctk.CTkLabel(entry, text=placeholder, text_color=T.TEXT_PLACEHOLDER, fg_color=T.SURFACE, font=T.font(12), anchor="w", height=18)

        def sync(*_):
            try:
                if var.get():
                    hint.place_forget()
                else:
                    hint.place(x=10, rely=0.5, anchor="w")
            except Exception:                                    # the box was destroyed
                pass
        hint.bind("<Button-1>", lambda e: entry.focus_set())
        var.trace_add("write", sync)
        sync()
    return entry


def card(parent, **kw):
    """A white panel with a thin border and the standard corner radius."""
    kw.pop("corner_radius", None)
    kw.pop("border_width", None)
    return ctk.CTkFrame(parent, fg_color=kw.pop("fg_color", T.SURFACE), corner_radius=T.RADIUS_MD, border_width=1,
                        border_color=kw.pop("border_color", T.BORDER), **kw)


def notify(widget, message, kind="success"):
    """Tell the person something that already happened, without making them click: a toast on the main window. Falls back to a plain dialog
    when the screen is used without the main window (tests, tools). Never use this for a question or a destructive confirmation."""
    show = getattr(widget.winfo_toplevel(), "show_toast", None)
    if show is not None:
        show(message, kind)
    elif kind == "error":
        messagebox.showerror("Error", message, parent=widget.winfo_toplevel())
    else:
        messagebox.showinfo("Done", message, parent=widget.winfo_toplevel())


def confirm(title, message, *, parent=None):
    """Ask before an action; the question stays above the active panel.

    A native Windows question can fall behind a topmost project or catalog
    window. Use an owned CTk window for real screens; keep the native fallback
    for callers without a Tk window.
    """
    if parent is not None and hasattr(parent, "tk"):
        return _confirm_window(title, message, parent)

    # The native fallback is also useful to headless integrations which
    # provide a messagebox parent without an actual Tk window.
    topmost_windows = []
    if parent is not None:
        window = parent
        while window is not None:
            try:
                if window.attributes("-topmost"):
                    topmost_windows.append(window)
                    window.attributes("-topmost", False)
            except Exception:
                pass
            window = getattr(window, "master", None)
        try:
            parent.lift()
        except Exception:
            pass
    try:
        return messagebox.askyesno(title, message, parent=parent, default="no", icon="question")
    finally:
        for window in reversed(topmost_windows):
            try:
                if window.winfo_exists():
                    window.attributes("-topmost", True)
                    window.lift()
            except Exception:
                pass


def label(parent, text="", size=12, weight="normal", color=None, **kw):
    return ctk.CTkLabel(parent, text=text, font=T.font(size, weight), text_color=color or T.TEXT, **kw)


class KpiCard(ctk.CTkFrame):
    """The dashboard's number card: same size and type everywhere. Number on top, label below, a small status line under it, and a
    slim colour stripe on the left. ``with_value=False`` leaves the number row empty (the Action Items card fills it with badges)."""

    def __init__(self, parent, title, note, accent, value="0", with_value=True, background=None, **kw):
        base = background or T.SURFACE
        super().__init__(parent, fg_color=base, corner_radius=T.RADIUS_MD, border_width=1, border_color=T.BORDER, height=136, **kw)
        self.pack_propagate(False)
        self.stripe = ctk.CTkFrame(self, fg_color=accent, width=5, corner_radius=3)
        self.stripe.pack(side="left", fill="y", padx=(T.S3, 0), pady=T.S4)
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(side="left", fill="both", expand=True, padx=(T.S3, T.S3))
        self.top = ctk.CTkFrame(body, fg_color="transparent")
        self.top.pack(fill="x", pady=(T.S4, 0))
        self.value_label = None
        if with_value:
            self.value_label = ctk.CTkLabel(self.top, text=value, font=T.font(28, "bold"), text_color=T.TEXT)
            self.value_label.pack(side="left")
        self.title_label = ctk.CTkLabel(body, text=title, font=T.font(14, "bold"), text_color=T.TEXT, anchor="w")
        self.title_label.pack(anchor="w", pady=(T.S1, 0))
        self.note_label = ctk.CTkLabel(body, text=note, font=T.font(12), text_color=T.TEXT_MUTED, anchor="w")
        self.note_label.pack(anchor="w")
        self._hover_base = base

    def set_state(self, fg, border):
        """Change the card colours (e.g. red when something needs attention); hover fades keep returning to THIS colour."""
        self._hover_base = fg
        self.configure(fg_color=fg, border_color=border)


class MoreMenu(ctk.CTkButton):
    """A ghost "More" button that opens a small menu of extra actions, so a toolbar never shows more than three secondary buttons."""

    def __init__(self, parent, items, text="More ▾", **kw):
        super().__init__(parent, text=text, command=self._open, height=BUTTON_HEIGHT, corner_radius=T.RADIUS_SM, font=T.font(12, "bold"),
                         cursor="hand2", fg_color="transparent", hover_color=T.SURFACE_MUTED, text_color=T.PRIMARY,
                         border_width=1, border_color=T.BORDER_STRONG, **kw)
        self.items = list(items)

    def _open(self):
        menu = tk.Menu(self, tearoff=0, font=T.font(12), bg=T.SURFACE, fg=T.TEXT, activebackground=T.PRIMARY, activeforeground=T.ON_PRIMARY, bd=0)
        for label_text, command in self.items:
            menu.add_command(label=label_text, command=command)
        try:
            menu.tk_popup(self.winfo_rootx(), self.winfo_rooty() + self.winfo_height())
        finally:
            menu.grab_release()


class PageHeader(ctk.CTkFrame):
    """Title, one-line subtitle, and the primary action on the right.  ``actions`` is the right-hand frame: extra buttons go there too."""

    def __init__(self, parent, title, subtitle="", primary=None, **kw):
        super().__init__(parent, fg_color="transparent", **kw)
        left = ctk.CTkFrame(self, fg_color="transparent", height=1)
        left.pack(side="left", fill="x", expand=True)
        self.title_label = ctk.CTkLabel(left, text=title, font=T.font(20, "bold"), text_color=T.PRIMARY, anchor="w")
        self.title_label.pack(anchor="w")
        self.subtitle_label = ctk.CTkLabel(left, text=subtitle, font=T.font(12), text_color=T.TEXT_MUTED, anchor="w")
        if subtitle:
            self.subtitle_label.pack(anchor="w")
        self.actions = ctk.CTkFrame(self, fg_color="transparent", width=1, height=1)   # an empty CTkFrame would ask for 200x200
        self.actions.pack(side="right")
        self.primary_button = None
        if primary:
            text, command = primary
            self.primary_button = button(self.actions, text, command, "primary")
            self.primary_button.pack(side="right", padx=(T.S2, 0))

    def add_secondary(self, text, command):
        b = button(self.actions, text, command, "secondary")
        b.pack(side="right", padx=(T.S2, 0))
        return b

    def add_more(self, items):
        m = MoreMenu(self.actions, items)
        m.pack(side="right", padx=(T.S2, 0))
        return m
