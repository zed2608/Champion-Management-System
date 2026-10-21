"""Reusable paged table. Holds ONE page of rows, however large the table is, and RECYCLES its row widgets: the cells are created once
(the first time a page needs them) and only their text and colours change when the page changes. Loading happens in a worker thread;
the result comes back through a queue that the Tk thread polls, so no thread ever touches a widget.

    table = PagedTable(parent, columns=[("PID", 1, 50), ("Name", 4, 150)], fetch=my_fetch, cells=lambda row: [row["id"], row["name"]])
    table.pack(fill="x")
    table.reload()                     # back to page 1
``fetch(page, size) -> (rows, PageInfo)`` runs in the worker thread (use services.paging.fetch_page).
"""
import queue
import threading

import customtkinter as ctk

from services.errors import friendly_message
from services.paging import DEFAULT_PAGE_SIZE, PAGE_SIZES, PageInfo
from ui import theme as T

HEADER_BG=T.PRIMARY
POLL_MS = 40


class PagedTable(ctk.CTkFrame):
    def __init__(self, parent, columns, fetch, cells, page_size=DEFAULT_PAGE_SIZE, row_bg=None, cell_style=None, on_row_click=None,
                 on_loaded=None, empty_text="No records found.", font_size=12, cell_pady=8, checkbox=None, actions=None, uniform="pt", header_bg=HEADER_BG, **kw):
        super().__init__(parent, fg_color="transparent", **kw)
        self.columns, self._fetch, self._cells = columns, fetch, cells
        self._row_bg, self._cell_style, self._on_click, self._on_loaded = row_bg, cell_style, on_row_click, on_loaded
        self._empty_text, self._fsize, self._cell_pady, self._checkbox, self._uniform = empty_text, min(T.SIZES, key=lambda s: abs(s - font_size)), cell_pady, checkbox, uniform
        self._header_bg = header_bg
        self._actions = actions or {}                      # {column: {"text", "command"(row), "fg", "hover", "width"}}: one button per row
        self.page, self.page_size = 0, page_size
        self.info = PageInfo(0, page_size, 0)
        self.rows = []                                     # the rows currently shown
        self._slots = []                                   # recycled row widgets
        self._results = queue.Queue()
        self._seq = 0                                      # only the newest request may draw (older answers are dropped)
        self._poll_job = None
        self._dead = False
        self._build_bar()
        self._build_grid()

    # ---- layout ---------------------------------------------------------------------------------------------------------------
    def _build_bar(self):
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 4))
        self.info_lbl = ctk.CTkLabel(bar, text="", font=T.font(12), text_color=T.TEXT_SECONDARY)
        self.info_lbl.pack(side="left")
        self.next_btn = ctk.CTkButton(bar, text="Next ▶", width=70, height=26, command=lambda: self.goto(self.page + 1), font=T.font(12, "bold"))
        self.last_btn = ctk.CTkButton(bar, text="Last ⏭", width=60, height=26, command=lambda: self.goto(10 ** 9), font=T.font(12, "bold"))
        self.page_lbl = ctk.CTkLabel(bar, text="Page 1 of 1", font=T.font(12, "bold"), width=90)
        self.prev_btn = ctk.CTkButton(bar, text="◀ Prev", width=70, height=26, command=lambda: self.goto(self.page - 1), font=T.font(12, "bold"))
        self.first_btn = ctk.CTkButton(bar, text="⏮ First", width=60, height=26, command=lambda: self.goto(0), font=T.font(12, "bold"))
        self.size_menu = ctk.CTkOptionMenu(bar, values=[str(s) for s in PAGE_SIZES], width=70, height=26, command=self._size_changed)
        self.size_menu.set(str(self.page_size))
        for w in (self.last_btn, self.next_btn, self.page_lbl, self.prev_btn, self.first_btn):
            w.pack(side="right", padx=2)
        ctk.CTkLabel(bar, text="Rows:", font=T.font(12), text_color=T.TEXT_SECONDARY).pack(side="right", padx=(8, 2))
        self.size_menu.pack(side="right", padx=2)

    def _build_grid(self):
        self.grid_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.grid_frame.pack(fill="x", expand=True)
        for col, (_title, weight, minsize) in enumerate(self.columns):
            self.grid_frame.grid_columnconfigure(col, weight=weight, minsize=minsize, uniform=self._uniform)
        for col, (title, _w, _m) in enumerate(self.columns):
            cell = ctk.CTkFrame(self.grid_frame, fg_color=self._header_bg, corner_radius=0)
            cell.grid(row=0, column=col, sticky="nsew", pady=(0, 2))
            ctk.CTkLabel(cell, text=title, font=T.font(self._fsize, "bold"), text_color=T.WHITE, anchor="center").pack(fill="both", expand=True, padx=2, pady=10)
        self.message = ctk.CTkLabel(self.grid_frame, text="", text_color=T.TEXT_MUTED, font=T.font(12, "italic"))

    def _make_slot(self, index):
        slot = {"row": None, "cells": [], "labels": [], "check": None, "check_var": None}
        for col, (_title, _w, minsize) in enumerate(self.columns):
            cell = ctk.CTkFrame(self.grid_frame, corner_radius=0, cursor="hand2" if self._on_click else "")
            cell.grid(row=index + 1, column=col, sticky="nsew")
            if col in self._actions:
                spec = self._actions[col]
                holder = ctk.CTkFrame(cell, fg_color="transparent")
                holder.pack(expand=True)
                btn = ctk.CTkButton(holder, text=spec["text"], width=spec.get("width", 60), height=28, fg_color=spec.get("fg", T.INFO_HOVER),
                                    hover_color=spec.get("hover", T.INFO_DARK), font=T.font(12, "bold"),
                                    command=lambda s=slot, sp=spec: sp["command"](s["row"]) if s["row"] is not None else None)
                btn.pack(expand=True, pady=self._cell_pady)
                slot["cells"].append(cell)
                slot["labels"].append(None)
                continue
            if self._checkbox and col == self._checkbox["col"]:
                var = ctk.StringVar(value="off")
                chk = ctk.CTkCheckBox(cell, text="", variable=var, onvalue="on", offvalue="off", width=20, height=20,
                                      command=lambda s=slot: self._toggled(s))
                chk.pack(expand=True, pady=self._cell_pady)
                slot["check"], slot["check_var"] = chk, var
                slot["cells"].append(cell)
                slot["labels"].append(None)
                continue
            lbl = ctk.CTkLabel(cell, text="", font=T.font(self._fsize), justify="center", anchor="center", cursor="hand2" if self._on_click else "")
            lbl.configure(wraplength=max(20, minsize - 10))
            lbl.pack(fill="both", expand=True, padx=4, pady=self._cell_pady)
            if self._on_click:
                cell.bind("<Button-1>", lambda e, s=slot: self._clicked(s))
                lbl.bind("<Button-1>", lambda e, s=slot: self._clicked(s))
            slot["cells"].append(cell)
            slot["labels"].append(lbl)
        self._slots.append(slot)
        return slot

    # ---- loading --------------------------------------------------------------------------------------------------------------
    def reload(self, page=None):
        """Load ``page`` (default: the first). Safe to call as often as you like; only the newest answer is drawn."""
        if self._dead:
            return
        if page is not None:
            self.page = max(0, page)
        self._seq += 1
        seq, page_no, size = self._seq, self.page, self.page_size
        self._show_message("↻ Loading... Please wait")
        self._set_buttons(False)

        def work():
            try:
                rows, info = self._fetch(page_no, size)
                self._results.put((seq, rows, info, None))
            except Exception as e:                     # shown, never raised in the thread
                self._results.put((seq, None, None, friendly_message(e)))
        threading.Thread(target=work, daemon=True).start()
        if self._poll_job is None:
            self._poll_job = self.after(POLL_MS, self._poll)

    def refresh(self):
        """Reload the page the person is on."""
        self.reload(self.page)

    def goto(self, page):
        self.reload(max(0, min(page, self.info.pages - 1)))

    def _size_changed(self, value):
        self.page_size = int(value)
        self.reload(0)

    def _poll(self):
        self._poll_job = None
        if self._dead:
            return
        newest = None
        try:
            while True:
                item = self._results.get_nowait()
                if item[0] == self._seq:
                    newest = item
        except queue.Empty:
            pass
        if newest is None:
            self._poll_job = self.after(POLL_MS, self._poll)
            return
        _seq, rows, info, error = newest
        if error is not None:
            self._show_message(error, "red")
            self._set_buttons(True)
            return
        self.info, self.page, self.rows = info, info.page, rows
        self._paint()

    # ---- drawing --------------------------------------------------------------------------------------------------------------
    def _show_message(self, text, color="gray"):
        for slot in self._slots:
            for c in slot["cells"]:
                c.grid_remove()
        if text:
            self.message.configure(text=text, text_color=color, wraplength=700)
            self.message.grid(row=1, column=0, columnspan=len(self.columns), pady=20)
        else:
            self.message.grid_remove()

    def _paint(self):
        rows = self.rows
        if not rows:
            self._show_message(self._empty_text)
        else:
            self.message.grid_remove()
            while len(self._slots) < len(rows):
                self._make_slot(len(self._slots))
            for i, slot in enumerate(self._slots):
                if i >= len(rows):
                    for c in slot["cells"]:
                        c.grid_remove()
                    slot["row"] = None
                    continue
                row = rows[i]
                slot["row"] = row
                values = self._cells(row)
                bg = self._row_bg(row, i) if self._row_bg else (T.SURFACE_ALT if i % 2 == 0 else "white")
                for col, cell in enumerate(slot["cells"]):
                    cell.configure(fg_color=bg)
                    cell.grid()
                    lbl = slot["labels"][col]
                    if lbl is None and col in self._actions:           # a button column: nothing to repaint
                        continue
                    if lbl is None:                                    # the checkbox column
                        enabled, checked = self._checkbox["state"](row)
                        slot["check"].configure(state="normal" if enabled else "disabled")
                        slot["check_var"].set("on" if (enabled and checked) else "off")
                        continue
                    val = "" if values[col] is None else str(values[col])
                    color, bold = (T.TEXT, False)
                    if self._cell_style:
                        color, bold = self._cell_style(row, col, val)
                    lbl.configure(text=val, text_color=color, font=T.font(self._fsize, "bold" if bold else "normal"))
        self.info_lbl.configure(text=self.info.label())
        self.page_lbl.configure(text=f"Page {self.info.page + 1} of {self.info.pages}")
        self._set_buttons(True)
        if self._on_loaded:
            self._on_loaded(rows, self.info)

    def _set_buttons(self, ready):
        has_prev = ready and self.info.page > 0
        has_next = ready and self.info.page + 1 < self.info.pages
        for b, on in ((self.first_btn, has_prev), (self.prev_btn, has_prev), (self.next_btn, has_next), (self.last_btn, has_next)):
            b.configure(state="normal" if on else "disabled")

    # ---- events ---------------------------------------------------------------------------------------------------------------
    def _clicked(self, slot):
        if slot["row"] is not None and self._on_click:
            self._on_click(slot["row"])

    def _toggled(self, slot):
        if slot["row"] is not None and self._checkbox:
            self._checkbox["toggle"](slot["row"], slot["check_var"].get() == "on")

    def destroy(self):
        self._dead = True
        if self._poll_job is not None:
            try:
                self.after_cancel(self._poll_job)
            except Exception:
                pass
            self._poll_job = None
        super().destroy()


def list_table(parent, columns, rows, cells, page_size=DEFAULT_PAGE_SIZE, **kw):
    """A PagedTable over rows that are already in memory (the reports compute their whole result first, because charts, totals and
    the PDF export need all of it). Same paging controls and the same recycled row widgets."""
    from services.paging import clamp_page

    def fetch(page, size):
        page = clamp_page(page, size, len(rows))
        return rows[page * size:(page + 1) * size], PageInfo(page, size, len(rows))
    t = PagedTable(parent, columns, fetch=fetch, cells=cells, page_size=page_size, **kw)
    t.pack(fill="x", expand=True)
    t.reload(0)
    return t
