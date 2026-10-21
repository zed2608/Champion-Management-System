"""Uniform building blocks for every screen: cards, the four-button set, form fields, the page header and the "More" menu.

Screens call these instead of styling CustomTkinter widgets by hand, so every screen looks and sizes the same.
They return ordinary CustomTkinter widgets (a button is still a CTkButton), so existing code that reads ``_text`` or calls ``configure`` keeps working.
Colours, fonts and sizes come from ui.theme only.
"""
import tkinter as tk

import customtkinter as ctk

from ui import theme as T

def apply_widget_defaults():
    """Make every CustomTkinter widget that a screen does not style by hand pick up the brand colours (the stock "green" theme is mint
    with white text, about 2:1 contrast). Idempotent: safe to call more than once."""
    th = ctk.ThemeManager.theme
    both = lambda name: [getattr(T, name), T.DARK.get(name, getattr(T, name))]
    patch = {
        "CTkButton": dict(fg_color=both("PRIMARY"), hover_color=both("PRIMARY_HOVER"), text_color=both("ON_PRIMARY"), text_color_disabled=both("TEXT_MUTED"),
                          corner_radius=T.RADIUS_SM),
        "CTkOptionMenu": dict(fg_color=both("SURFACE_ALT"), button_color=both("PRIMARY"), button_hover_color=both("PRIMARY_HOVER"),
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


def button(parent, text="", command=None, kind="primary", compact=False, **kw):
    """One of four buttons: primary (filled green), secondary (grey), ghost (text only) or danger (red). Fixed height, pointer cursor."""
    style = BUTTON_KINDS[kind]
    kw.pop("height", None)
    kw.pop("corner_radius", None)
    return ctk.CTkButton(parent, text=text, command=command, height=BUTTON_HEIGHT_COMPACT if compact else BUTTON_HEIGHT,
                         corner_radius=T.RADIUS_SM, font=kw.pop("font", T.font(12, "bold")), cursor="hand2",
                         fg_color=kw.pop("fg_color", style["fg_color"]), hover_color=kw.pop("hover_color", style["hover_color"]),
                         text_color=kw.pop("text_color", style["text_color"]), text_color_disabled=kw.pop("text_color_disabled", T.TEXT_MUTED),
                         **kw)


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


def label(parent, text="", size=12, weight="normal", color=None, **kw):
    return ctk.CTkLabel(parent, text=text, font=T.font(size, weight), text_color=color or T.TEXT, **kw)


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
