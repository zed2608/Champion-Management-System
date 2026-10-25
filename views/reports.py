import customtkinter as ctk
import threading
from views.ui_thread import UiMixin
from tkinter import messagebox
from database import get_connection
import os
import tempfile
from decimal import Decimal
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
import matplotlib
from ui import charts          # noqa: F401  (applies the one shared Matplotlib style)
from ui import components as C
from ui import theme as T
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from services.errors import friendly_message
from services import report_service as rs, anomaly, wear_forecast
from views.paged_table import list_table
from utils.pdf_table import render_pdf


def _fmt(x) -> str:
    """Exact quantity for display: 3 -> '3', 2.5 -> '2.5' (never '3.00', never truncated to 2)."""
    try:
        return f"{float(x):g}"
    except (TypeError, ValueError):
        return str(x)


class ReportsView(UiMixin, ctk.CTkFrame):
    def __init__(self, parent, navigate_to_tool=None, user_info=None):
        super().__init__(parent, fg_color="transparent")
        self._ui_init()

        self.navigate_to_tool = navigate_to_tool
        self.user_info = user_info or {}

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=0)
        self.grid_rowconfigure(2, weight=1)

        self.build_ui()

    def build_ui(self):
        # Row 0: Title
        top_bar = ctk.CTkFrame(self, fg_color="transparent")
        top_bar.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        C.PageHeader(top_bar, "Reports", "Find records and export a report").pack(side="left")

        # Date Filters
        filter_f = ctk.CTkFrame(top_bar, fg_color="transparent")
        self.date_filter_frame = filter_f
        filter_f.pack(side="right", padx=15)
        ctk.CTkLabel(filter_f, text="From:", font=T.font(12, "bold"), text_color=T.TEXT_MUTED).pack(side="left", padx=(0, 5))
        self.start_date = C.field(filter_f, placeholder_text="YYYY-MM-DD", width=100)
        self.start_date.pack(side="left", padx=(0, 2))
        self.start_date.configure(state="readonly")
        C.button(filter_f, compact=True, kind="secondary", text="📅", width=32, command=lambda: self.open_date_picker(self.start_date)).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(filter_f, text="To:", font=T.font(12, "bold"), text_color=T.TEXT_MUTED).pack(side="left", padx=(0, 5))
        self.end_date = C.field(filter_f, placeholder_text="YYYY-MM-DD", width=100)
        self.end_date.pack(side="left", padx=(0, 2))
        self.end_date.configure(state="readonly")
        C.button(filter_f, compact=True, kind="secondary", text="📅", width=32, command=lambda: self.open_date_picker(self.end_date)).pack(side="left", padx=(0, 10))
        C.button(filter_f, compact=True, kind="primary", text="Apply", width=60, command=lambda: self.switch_tab(self.tab_var.get())).pack(side="left", padx=(0, 5))
        C.button(filter_f, compact=True, kind="secondary", text="Clear", width=60, command=self.clear_date_filter).pack(side="left")

        # Row 1: Tab buttons (own row so they never overflow the title row)
        tab_bar = ctk.CTkFrame(self, fg_color="transparent")
        tab_bar.grid(row=1, column=0, sticky="ew", pady=(0, 8), padx=15)
        self.tab_var = ctk.StringVar(value="⛭ Tool Usage Report")
        self.seg_btn = ctk.CTkSegmentedButton(
            tab_bar,
            values=["⛭ Tool Usage Report", "🖹 Employee Activity", "📋 Project Allocation",
                    "⚠ Damage & Loss", "⭣ Low Stock", "⧖ Overdue Transactions"],
            variable=self.tab_var,
            fg_color=T.SURFACE_MUTED,
            selected_color=T.PRIMARY,
            selected_hover_color=T.PRIMARY_HOVER,
            command=self.switch_tab
        )
        self.seg_btn.pack(side="right")
        self.report_search_var = ctk.StringVar()
        self.report_search = C.field(tab_bar, placeholder_text="Search this report (name, ID, status)...", width=270,
                                     textvariable=self.report_search_var)
        self.report_search.pack(side="left")
        self.report_search.bind("<Return>", lambda e: self.switch_tab(self.tab_var.get()))
        C.button(tab_bar, compact=True, kind="secondary", text="Search", width=65,
                 command=lambda: self.switch_tab(self.tab_var.get())).pack(side="left", padx=5)

        self.tab_content = ctk.CTkFrame(self, fg_color="transparent")
        self.tab_content.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        self.tab_content.grid_columnconfigure(0, weight=1)
        self.tab_content.grid_rowconfigure(0, weight=1)

        self.render_usage_tab()

    def clear_date_filter(self):
        self.start_date.configure(state="normal")
        self.start_date.delete(0, 'end')
        self.start_date.configure(state="readonly")
        self.end_date.configure(state="normal")
        self.end_date.delete(0, 'end')
        self.end_date.configure(state="readonly")
        self.switch_tab(self.tab_var.get())

    def open_date_picker(self, entry_widget):
        try:
            from tkcalendar import Calendar
        except ImportError:
            messagebox.showerror("Dependency Missing", "Please install the calendar module by running in your terminal:\n\npip install tkcalendar", parent=self.winfo_toplevel())
            return

        top = ctk.CTkToplevel(self)
        top.title("Select Date")
        top.attributes("-topmost", True)
        top.grab_set()
        top.resizable(False, False)
        
        top.update_idletasks()
        sw = top.winfo_screenwidth()
        sh = top.winfo_screenheight()
        x = (sw - 280) // 2
        y = (sh - 260) // 2
        top.geometry(f"280x260+{x}+{y}")
        
        current_date = entry_widget.get().strip()
        sel_date = datetime.now()
        if current_date:
            try:
                sel_date = datetime.strptime(current_date, "%Y-%m-%d")
            except ValueError:
                pass
                
        cal = Calendar(top, selectmode='day', date_pattern='y-mm-dd',
                       year=sel_date.year, month=sel_date.month, day=sel_date.day,
                       background=T.PRIMARY, foreground='white', borderwidth=0,
                       headersbackground=T.SURFACE_ALT, headersforeground='black',
                       normalbackground='white', normalforeground='black',
                       weekendbackground='white', weekendforeground='black',
                       othermonthforeground='gray', othermonthweforeground='gray')
        cal.pack(fill="both", expand=True, padx=10, pady=(10, 5))
        
        def set_date():
            entry_widget.configure(state="normal")
            entry_widget.delete(0, "end")
            entry_widget.insert(0, cal.get_date())
            entry_widget.configure(state="readonly")
            top.destroy()
            
        C.button(top, kind="primary", text="Confirm", command=set_date).pack(pady=(0, 10), padx=10, fill="x")

    def get_and_validate_dates(self):
        sd = self.start_date.get().strip()
        ed = self.end_date.get().strip()
        start_obj = None
        end_obj = None
        if sd:
            try:
                start_obj = datetime.strptime(sd, "%Y-%m-%d")
            except ValueError:
                messagebox.showerror("Invalid Date", "From date must be in YYYY-MM-DD format (e.g., 2024-01-31).", parent=self.winfo_toplevel())
                return None, None, False
        if ed:
            try:
                end_obj = datetime.strptime(ed, "%Y-%m-%d")
            except ValueError:
                messagebox.showerror("Invalid Date", "To date must be in YYYY-MM-DD format (e.g., 2024-12-31).", parent=self.winfo_toplevel())
                return None, None, False

        if start_obj and end_obj and start_obj > end_obj:
            messagebox.showerror("Invalid Date Range", "The From date cannot be later than the To date.", parent=self.winfo_toplevel())
            return None, None, False

        return sd, ed, True

    def _new_fig(self, *args, **kw):
        """A chart figure that is released (cleared) when the tab is left or the screen is closed."""
        fig = Figure(*args, **kw)
        self._figs = getattr(self, "_figs", [])
        self._figs.append(fig)
        return fig

    def _matching_rows(self, rows):
        """The same visible search is used for screen rows and the exported PDF."""
        term = getattr(self, "_report_search_text", "").casefold()
        if not term:
            return rows
        return [r for r in rows if any(term in str(value or "").casefold() for value in r.values())]

    def _matching_damage(self, result):
        rows = self._matching_rows(result["rows"])
        if len(rows) == len(result["rows"]):
            return result
        totals = {"total_loss": Decimal(0), "total_damage": Decimal(0), "count_lost": Decimal(0),
                  "count_damaged": Decimal(0), "count_repair": Decimal(0)}
        for row in rows:
            qty = Decimal(str(row["units"]))
            flag = row["cond_flag"]
            count = {"Lost": "count_lost", "Damaged": "count_damaged", "Needs Repair": "count_repair"}.get(flag)
            if count:
                totals[count] += qty
            if flag in ("Lost", "Damaged"):
                totals["total_loss" if flag == "Lost" else "total_damage"] += qty * Decimal(str(row["price"]))
        return {"rows": rows, "summary": totals}

    def _release_figures(self):
        for fig in getattr(self, "_figs", []):
            try:
                fig.clf()
            except Exception:
                pass
        self._figs = []

    def destroy(self):
        self._release_figures()
        super().destroy()

    def switch_tab(self, selected):
        sd, ed, valid = self.get_and_validate_dates()
        if not valid: return
        self._report_search_text = self.report_search_var.get().strip()
        if selected == "⭣ Low Stock":
            self.date_filter_frame.pack_forget()
        elif not self.date_filter_frame.winfo_manager():
            self.date_filter_frame.pack(side="right", padx=15)
        
        self._release_figures()
        for widget in self.tab_content.winfo_children():
            widget.destroy()

        if selected == "▤ Inventory ABC Analysis":
            self.render_abc_tab()
        elif selected == "⛭ Tool Usage Report":
            self.render_usage_tab()
        elif selected == "🖹 Employee Activity":
            self.render_activity_tab()
        elif selected == "📋 Project Allocation":
            self.render_project_allocation_tab()
        elif selected == "⚠ Damage & Loss":
            self.render_damage_loss_tab()
        elif selected == "⭣ Low Stock":
            self.render_low_stock_tab()
        elif selected == "⧖ Overdue Transactions":
            self.render_overdue_tab()
        elif selected == "🔧 Wear":
            self.render_wear_report_tab()
        elif selected == "🔎 Anomalies":
            self.render_anomaly_tab()

    # ==========================================
    # TAB 1: ABC Analysis 
    # ==========================================
    def render_abc_tab(self):
        frame = ctk.CTkFrame(self.tab_content, fg_color=T.SURFACE, corner_radius=10)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=0)
        frame.grid_rowconfigure(1, weight=0)
        frame.grid_rowconfigure(2, weight=1)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=30, pady=(12, 4))
        ctk.CTkLabel(top, text="Inventory Analytics (ABC Analysis)",
                     font=T.font(16, "bold"), text_color=T.PRIMARY).pack(side="left")
        C.button(top, kind="primary", text="⎙ Export PDF", width=110, 
                      command=lambda: self.open_export_dialog("abc")).pack(side="right")

        self._abc_desc_lbl = ctk.CTkLabel(frame, text="Ranks tools by quantity issued: A = top 20%, B = next 30%, C = last 50%.",
                                          font=T.font(12), text_color=T.TEXT_MUTED, wraplength=900, justify="left")
        self._abc_desc_lbl.grid(row=1, column=0, sticky="w", padx=30, pady=(0, 8))

        self._abc_scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        self._abc_scroll.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 10))

        self.run_abc_algorithm()

    def run_abc_algorithm(self):
        sd, ed, valid = self.get_and_validate_dates()
        if not valid: return
        
        scroll = self._abc_scroll
        for w in scroll.winfo_children():
            w.destroy()

        loading = ctk.CTkLabel(scroll, text="Loading ABC Analysis...", text_color=T.TEXT_MUTED, font=T.font(12))
        loading.pack(pady=40)

        self.abc_table_inner = ctk.CTkFrame(scroll, fg_color="transparent")
        self.abc_pag_frame = ctk.CTkFrame(scroll, fg_color="transparent")

        def _fetch_abc():
            # [QUANTITIES] one service call shared with the PDF export; the dates were read on the MAIN thread above
            try:
                result = rs.abc_analysis(self.user_info, sd, ed)
            except Exception as e:
                self.post_ui(lambda err=e: scroll.winfo_exists() and ctk.CTkLabel(scroll, text=friendly_message(err), text_color=T.DANGER_TEXT).pack(pady=10))
                return
            self.post_ui(lambda: _render_abc(result))

        def _render_abc(result):
            if not self.winfo_exists() or not scroll.winfo_exists() or not loading.winfo_exists():
                return
            loading.destroy()

            palette = {"A": ("A (High Priority)", T.SUCCESS_BRIGHT), "B": ("B (Medium Priority)", T.ACCENT), "C": ("C (Low Priority)", T.DANGER_SOFT)}
            self._abc_raw_data = []
            for d in result["rows"]:
                category, color = palette[d["category"]]
                self._abc_raw_data.append({
                    "rank_raw": d["rank"], "tool_id": int(d["tool_id"]), "name": d["name"], "usage": d["usage"],
                    "cum_pct_raw": d["cum_pct"], "category": category, "color": color})
            c = result["counts"]
            self._abc_desc_lbl.configure(text=(
                f"Ranked by quantity issued: A = top 20% of tools, B = next 30%, C = last 50% (tools never issued are always C).   "
                f"Historical total issued (incl. archived tools): {_fmt(result['historical_total'])}   |   "
                f"{result['n_active']} active tools ranked (A {c['A']} / B {c['B']} / C {c['C']})   |   "
                f"archived tools: {_fmt(result['archived_total'])} issued"))

            self.abc_current_page = 1
            self.abc_sort_col = "rank_raw"
            self.abc_sort_desc = False

            # Place table and pagination
            self.abc_current_page = 1
            self.abc_sort_col = "rank_raw"
            self.abc_sort_desc = False

            self.abc_table_inner.pack(fill="x", pady=(0, 10))
            self.abc_pag_frame.pack(fill="x", pady=8)
            _update_abc_table()

        def _update_abc_table():
            # ... (your existing _update_abc_table code - unchanged) ...
            self._abc_raw_data.sort(key=lambda x: x[self.abc_sort_col], reverse=self.abc_sort_desc)
            self._abc_data = []
            for d in self._abc_raw_data:
                self._abc_data.append({
                    "rank": f"#{d['rank_raw']}", "tool_id": str(d['tool_id']), "name": d['name'],
                    "usage": str(d['usage']), "cum_pct": f"{d['cum_pct_raw']:.1f}%", "category": d['category']
                })

            limit = 50
            total_items = len(self._abc_raw_data)
            total_pages = max(1, (total_items + limit - 1) // limit)
            start_idx = (self.abc_current_page - 1) * limit
            end_idx = start_idx + limit
            page_data = self._abc_raw_data[start_idx:end_idx]

            for w in self.abc_table_inner.winfo_children(): w.destroy()
            if not page_data:
                ctk.CTkLabel(self.abc_table_inner, text="No data for this period", font=T.font(12),
                             text_color=T.TEXT_MUTED).pack(anchor="w", padx=8, pady=8)
                return

            headers = [("Rank", "rank_raw"), ("Tool ID", "tool_id"), ("Tool Name", "name"),
                       ("Qty Issued", "usage"), ("Cumulative %", "cum_pct_raw"), ("ABC Category", "category")]
            weights = [1, 2, 5, 2, 2, 3]
            min_sizes = [50, 80, 200, 120, 120, 140]

            for col, (w, min_w) in enumerate(zip(weights, min_sizes)):
                self.abc_table_inner.grid_columnconfigure(col, weight=w, minsize=min_w, uniform="abc_cols")

            for col, (text, sort_key) in enumerate(headers):
                cell = ctk.CTkFrame(self.abc_table_inner, fg_color=T.PRIMARY, corner_radius=0, cursor="hand2")
                cell.grid(row=0, column=col, sticky="nsew", pady=(0, 2))
                arrow = " ▼" if self.abc_sort_desc else " ▲"
                disp_text = text + arrow if self.abc_sort_col == sort_key else text
                lbl = ctk.CTkLabel(cell, text=disp_text, font=T.font(12, "bold"), text_color=T.WHITE, anchor="center", cursor="hand2")
                lbl.pack(fill="both", expand=True, padx=2, pady=10)

                def make_sort_cmd(k=sort_key):
                    def _sort(e):
                        if self.abc_sort_col == k: self.abc_sort_desc = not self.abc_sort_desc
                        else: self.abc_sort_col = k; self.abc_sort_desc = False
                        _update_abc_table()
                    return _sort
                cell.bind("<Button-1>", make_sort_cmd())
                lbl.bind("<Button-1>", make_sort_cmd())

            for i, d in enumerate(page_data):
                display_data = [f"#{d['rank_raw']}", str(d['tool_id']), str(d['name'] or 'Unknown'), str(d['usage']), f"{d['cum_pct_raw']:.1f}%", str(d['category'] or 'Unknown')]
                r_idx = i + 1
                bg=T.SURFACE_ALT if i % 2 == 0 else "white"
                for col, val in enumerate(display_data):
                    cell = ctk.CTkFrame(self.abc_table_inner, fg_color=bg, corner_radius=0)
                    cell.grid(row=r_idx, column=col, sticky="nsew")
                    txt_col = d['color'] if col == 5 else T.TEXT
                    font_w = "bold" if col == 5 else "normal"
                    lbl = ctk.CTkLabel(cell, text=val, font=T.font(12, font_w), text_color=txt_col, justify="center", anchor="center")
                    lbl.configure(wraplength=min_sizes[col] - 10)
                    lbl.pack(fill="both", expand=True, padx=4, pady=8)   # reduced pady

            # Pagination (unchanged)
            for w in self.abc_pag_frame.winfo_children(): w.destroy()
            def _prev():
                if self.abc_current_page > 1: self.abc_current_page -= 1; _update_abc_table()
            def _next():
                if self.abc_current_page < total_pages: self.abc_current_page += 1; _update_abc_table()

            p_frame = ctk.CTkFrame(self.abc_pag_frame, fg_color="transparent")
            p_frame.pack(pady=8)
            prev_btn = C.button(p_frame, kind="secondary", text="< Prev", width=60, command=_prev)
            if self.abc_current_page == 1: prev_btn.configure(state="disabled", fg_color=T.SURFACE_MUTED, text_color=T.TEXT_MUTED)
            prev_btn.pack(side="left", padx=10)
            ctk.CTkLabel(p_frame, text=f"Page {self.abc_current_page} of {total_pages}   (Total: {total_items})", font=T.font(12)).pack(side="left", padx=20)
            next_btn = C.button(p_frame, kind="secondary", text="Next >", width=60, command=_next)
            if self.abc_current_page == total_pages or total_pages == 0: next_btn.configure(state="disabled", fg_color=T.SURFACE_MUTED, text_color=T.TEXT_MUTED)
            next_btn.pack(side="left", padx=10)

        import threading
        threading.Thread(target=_fetch_abc, daemon=True).start()

    # ==========================================
    # TAB 2: Tool Usage Report
    # ==========================================
    def render_usage_tab(self):
        frame = ctk.CTkFrame(self.tab_content, fg_color=T.SURFACE, corner_radius=10)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=0)
        frame.grid_rowconfigure(1, weight=0)
        frame.grid_rowconfigure(2, weight=0)
        frame.grid_rowconfigure(3, weight=1)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=30, pady=(12, 4))
        ctk.CTkLabel(top, text="Tool Usage Report",
                     font=T.font(16, "bold"), text_color=T.PRIMARY).pack(side="left")
        C.button(top, kind="primary", text="⎙ Export PDF", width=110, 
                      command=lambda: self.open_export_dialog("usage")).pack(side="right")

        ctk.CTkLabel(frame, text="Summary of all tool transactions, availability, and condition status.",
                     font=T.font(12), text_color=T.TEXT_MUTED).grid(row=1, column=0, sticky="w", padx=30, pady=(0, 8))

        search_frame = ctk.CTkFrame(frame, fg_color="transparent")
        search_frame.grid(row=2, column=0, sticky="ew", padx=30, pady=(0, 10))
        
        self.usage_search_var = ctk.StringVar()
        self.usage_search_entry = C.field(search_frame, placeholder_text="Search Tool, Tag ID, Condition...", width=280, textvariable=self.usage_search_var)
        self.usage_search_entry.pack(side="left", padx=(0, 10))
        
        self._usage_timer = None
        def on_usage_search(*args):
            if self._usage_timer:
                self.after_cancel(self._usage_timer)
            self._usage_timer = self.after(300, lambda: self.run_usage_algorithm(self.usage_search_entry.get().strip()))
        self.usage_search_var.trace_add("write", on_usage_search)

        self._usage_scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        self._usage_scroll.grid(row=3, column=0, sticky="nsew", padx=20, pady=(0, 10))

        self.usage_table_inner = ctk.CTkFrame(self._usage_scroll, fg_color="transparent")
        self.usage_pag_frame = ctk.CTkFrame(self._usage_scroll, fg_color="transparent")

        self.usage_state = {"current_page": 1, "sort_col": "total_borrowed", "sort_desc": True, "raw_data": []}

        self.run_usage_algorithm()

    def run_usage_algorithm(self, search_query=""):
        sd, ed, valid = self.get_and_validate_dates()
        if not valid: return
        
        scroll = self._usage_scroll
        for w in scroll.winfo_children():
            w.destroy()

        loading = ctk.CTkLabel(scroll, text="Loading Tool Usage Report...", text_color=T.TEXT_MUTED, font=T.font(12))
        loading.pack(pady=40)

        self.usage_table_inner = ctk.CTkFrame(scroll, fg_color="transparent")
        self.usage_pag_frame = ctk.CTkFrame(scroll, fg_color="transparent")

        self._current_loading = loading

        def _fetch_usage():
            try:
                rows = self._matching_rows(rs.usage_report(self.user_info, sd, ed, search_query))
            except Exception as e:
                self.post_ui(lambda err=e: scroll.winfo_exists() and self._show_error(scroll, friendly_message(err)))
                return
            self.post_ui(lambda: _render_usage_safe(rows))

        def _render_usage_safe(rows):
            if not self.winfo_exists() or not scroll.winfo_exists() or not hasattr(self, '_current_loading') or not self._current_loading.winfo_exists():
                return
            self._current_loading.destroy()

            self.usage_state["raw_data"] = [
                {"tool_id": int(r['tool_id']), "name": r['name'], "tag_id": r['tag_id'],
                 "total_borrowed": r['total_borrowed'], "currently_out": r['currently_out'],
                 "qty_avail": float(r['qty_avail'] or 0), "condition": r['condition']}
                for r in rows
            ]

            self.usage_state["current_page"] = 1
            self.usage_state["sort_col"] = "total_borrowed"
            self.usage_state["sort_desc"] = True

            self.usage_table_inner.pack(fill="x", pady=(0, 10))
            self.usage_pag_frame.pack(fill="x", pady=8)
            self._update_usage_table()

        import threading
        threading.Thread(target=_fetch_usage, daemon=True).start()

    def _show_error(self, parent, message):
        for w in parent.winfo_children():
            w.destroy()
        ctk.CTkLabel(parent, text=message, text_color=T.DANGER_TEXT).pack(pady=20)

    def _update_usage_table(self):
        """Sortable and paginated table for Tool Usage Report"""
        if not hasattr(self, 'usage_table_inner') or not self.usage_table_inner.winfo_exists():
            return

        self.usage_state["raw_data"].sort(
            key=lambda x: x[self.usage_state["sort_col"]], 
            reverse=self.usage_state["sort_desc"]
        )

        self._usage_data = [
            [str(d['tool_id']), d['name'], d['tag_id'], str(d['total_borrowed']),
             str(d['currently_out']), f"{d['qty_avail']:g}", d['condition']]
            for d in self.usage_state["raw_data"]
        ]

        limit = 50
        total_items = len(self.usage_state["raw_data"])
        total_pages = max(1, (total_items + limit - 1) // limit)
        start_idx = (self.usage_state["current_page"] - 1) * limit
        page_data = self.usage_state["raw_data"][start_idx:start_idx + limit]

        for w in self.usage_table_inner.winfo_children():
            w.destroy()

        headers = [("Tool ID", "tool_id"), ("Tool Name", "name"), ("Tag ID", "tag_id"),
                   ("Total Issued", "total_borrowed"), ("Currently Out", "currently_out"),
                   ("Qty Avail", "qty_avail"), ("Condition", "condition")]
        weights = [2, 5, 2, 2, 2, 2, 2]
        min_sizes = [80, 200, 100, 120, 120, 100, 100]

        for col, (w, min_w) in enumerate(zip(weights, min_sizes)):
            self.usage_table_inner.grid_columnconfigure(col, weight=w, minsize=min_w, uniform="usage_cols")

        if not page_data:
            ctk.CTkLabel(self.usage_table_inner, text="No data for this period",
                         text_color=T.TEXT_MUTED, font=T.font(12)).grid(row=0, column=0, columnspan=len(headers), pady=8)
            return

        # Header row
        for col, (text, sort_key) in enumerate(headers):
            cell = ctk.CTkFrame(self.usage_table_inner, fg_color=T.PRIMARY, corner_radius=0, cursor="hand2")
            cell.grid(row=0, column=col, sticky="nsew", pady=(0, 2))
            arrow = " ▼" if self.usage_state["sort_desc"] else " ▲"
            disp_text = text + arrow if self.usage_state["sort_col"] == sort_key else text
            lbl = ctk.CTkLabel(cell, text=disp_text, font=T.font(12, "bold"), text_color=T.WHITE, anchor="center", cursor="hand2")
            lbl.pack(fill="both", expand=True, padx=2, pady=10)

            def make_sort_cmd(k=sort_key):
                def _sort(e):
                    if self.usage_state["sort_col"] == k:
                        self.usage_state["sort_desc"] = not self.usage_state["sort_desc"]
                    else:
                        self.usage_state["sort_col"] = k
                        self.usage_state["sort_desc"] = False
                    self._update_usage_table()
                return _sort
            cell.bind("<Button-1>", make_sort_cmd())
            lbl.bind("<Button-1>", make_sort_cmd())

        # Data rows
        for i, d in enumerate(page_data):
            vals = [str(d['tool_id']), str(d['name'] or 'Unknown'), str(d['tag_id'] or 'Unassigned'),
                    str(d['total_borrowed']), str(d['currently_out']), f"{d['qty_avail']:g}", 
                    str(d['condition'] or 'Good')]
            r_idx = i + 1
            bg=T.SURFACE_ALT if i % 2 == 0 else "white"
            for col, val in enumerate(vals):
                cell = ctk.CTkFrame(self.usage_table_inner, fg_color=bg, corner_radius=0)
                cell.grid(row=r_idx, column=col, sticky="nsew")
                txt_col=T.TEXT
                if col == 6:
                    txt_col=T.SUCCESS_TEXT if val == "Good" else T.DANGER
                elif col == 2 and val == "Unassigned":
                    txt_col=T.DANGER
                font_w = "bold" if (col == 6 or (col == 2 and val == "Unassigned")) else "normal"
                lbl = ctk.CTkLabel(cell, text=val, font=T.font(12, font_w), text_color=txt_col, justify="center", anchor="center")
                lbl.configure(wraplength=min_sizes[col] - 10)
                lbl.pack(fill="both", expand=True, padx=4, pady=8)

        # Pagination
        for w in self.usage_pag_frame.winfo_children():
            w.destroy()

        def _prev():
            if self.usage_state["current_page"] > 1:
                self.usage_state["current_page"] -= 1
                self._update_usage_table()

        def _next():
            if self.usage_state["current_page"] < total_pages:
                self.usage_state["current_page"] += 1
                self._update_usage_table()

        p_frame = ctk.CTkFrame(self.usage_pag_frame, fg_color="transparent")
        p_frame.pack(pady=8)
        prev_btn = C.button(p_frame, kind="secondary", text="< Prev", width=60, command=_prev)
        if self.usage_state["current_page"] == 1:
            prev_btn.configure(state="disabled", fg_color=T.SURFACE_MUTED, text_color=T.TEXT_MUTED)
        prev_btn.pack(side="left", padx=10)

        ctk.CTkLabel(p_frame, text=f"Page {self.usage_state['current_page']} of {total_pages}   (Total: {total_items})", font=T.font(12)).pack(side="left", padx=20)

        next_btn = C.button(p_frame, kind="secondary", text="Next >", width=60, command=_next)
        if self.usage_state["current_page"] == total_pages or total_pages == 0:
            next_btn.configure(state="disabled", fg_color=T.SURFACE_MUTED, text_color=T.TEXT_MUTED)
        next_btn.pack(side="left", padx=10)

    # ==========================================
    # TAB 3: Employee Activity Report
    # ==========================================
    def render_activity_tab(self):
        frame = ctk.CTkFrame(self.tab_content, fg_color=T.SURFACE, corner_radius=10)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=30, pady=(12, 4))
        ctk.CTkLabel(top, text="Employee Activity Report",
                     font=T.font(16, "bold"), text_color=T.PRIMARY).pack(side="left")
        C.button(top, kind="primary", text="⎙ Export PDF", width=110, 
                      command=lambda: self.open_export_dialog("activity")).pack(side="right")

        ctk.CTkLabel(frame, text="Aggregated deployment activity per employee for accountability monitoring.",
                     font=T.font(12), text_color=T.TEXT_MUTED).grid(row=1, column=0, sticky="w", padx=30, pady=(0, 4))

        scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        scroll.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 10))

        self.activity_chart_frame = ctk.CTkFrame(scroll, fg_color="transparent")

        self.activity_table_inner = ctk.CTkFrame(scroll, fg_color="transparent")
        self.activity_table_inner.pack(fill="x")

        self.activity_pag_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self.activity_pag_frame.pack(fill="x", pady=10)

        sd, ed, valid = self.get_and_validate_dates()
        if not valid: return

        def _fetch_activity():
            try:
                rows = self._matching_rows(rs.activity_report(self.user_info, sd, ed))
            except Exception as e:
                self.post_ui(lambda err=e: scroll.winfo_exists() and ctk.CTkLabel(scroll, text=friendly_message(err), text_color=T.DANGER_TEXT).pack(pady=10))
                return
            self.post_ui(lambda: _render_activity(rows))

        def _render_activity(rows):
            if not self.winfo_exists() or not scroll.winfo_exists(): return
            self._activity_raw_data = []
            for i, row in enumerate(rows):
                self._activity_raw_data.append({
                    "employee_id": row['employee_id'], "full_name": row['full_name'], "role": row['role'],
                    "total_borrows": row['total_borrows'], "active_borrows": row['active_borrows'],
                    "total_returned": row['total_returned']
                })

            # ── Render Activity Bar Chart ───────────────────────
            for w in self.activity_chart_frame.winfo_children():
                w.destroy()
            top_users = rows[:5]
            if self.activity_chart_frame.winfo_exists() and sum(r['total_borrows'] for r in top_users) > 0:
                fig = self._new_fig(figsize=(7, 1.6), dpi=90)
                fig.patch.set_facecolor(T.WHITE)
                ax = fig.add_subplot(111)
                names = [str(r['full_name'] or 'Unknown').split()[0] for r in top_users]
                counts = [r['total_borrows'] for r in top_users]
                ax.bar(names, counts, color=T.PURPLE_ALT, width=0.4)
                ax.spines["top"].set_visible(False)
                ax.spines["right"].set_visible(False)
                fig.tight_layout()
                canvas = FigureCanvasTkAgg(fig, master=self.activity_chart_frame)
                canvas.draw()
                canvas.get_tk_widget().pack(pady=3)
                self.activity_chart_frame.pack(fill="x", before=self.activity_table_inner, pady=(0, 4))
                
            self.activity_current_page = 1
            self.activity_sort_col = "total_borrows"
            self.activity_sort_desc = True
            _update_activity_table()

        def _update_activity_table():
            self._activity_raw_data.sort(key=lambda x: x[self.activity_sort_col], reverse=self.activity_sort_desc)
            self._activity_data = []
            for d in self._activity_raw_data:
                self._activity_data.append([
                    d['employee_id'], d['full_name'], d['role'],
                    str(d['total_borrows']), str(d['active_borrows']), str(d['total_returned'])
                ])

            limit = 50
            total_items = len(self._activity_raw_data)
            total_pages = max(1, (total_items + limit - 1) // limit)
            start_idx = (self.activity_current_page - 1) * limit
            end_idx = start_idx + limit
            page_data = self._activity_raw_data[start_idx:end_idx]

            for w in self.activity_table_inner.winfo_children(): w.destroy()
            if not page_data:
                ctk.CTkLabel(self.activity_table_inner, text="No data for this period", font=T.font(12),
                             text_color=T.TEXT_MUTED).pack(anchor="w", padx=8, pady=8)
                return

            headers = [("Employee ID", "employee_id"), ("Full Name", "full_name"), ("Role", "role"),
                       ("Total Issuances", "total_borrows"), ("Active Issuances", "active_borrows"),
                       ("Total Retrieved", "total_returned")]
            weights = [2, 4, 2, 2, 2, 2]
            min_sizes = [100, 180, 100, 120, 120, 120]

            for col, (w, min_w) in enumerate(zip(weights, min_sizes)):
                self.activity_table_inner.grid_columnconfigure(col, weight=w, minsize=min_w, uniform="activity_cols")

            for col, (text, sort_key) in enumerate(headers):
                cell = ctk.CTkFrame(self.activity_table_inner, fg_color=T.PRIMARY, corner_radius=0, cursor="hand2")
                cell.grid(row=0, column=col, sticky="nsew", pady=(0, 2))
                arrow = " ▼" if self.activity_sort_desc else " ▲"
                disp_text = text + arrow if self.activity_sort_col == sort_key else text
                lbl = ctk.CTkLabel(cell, text=disp_text, font=T.font(12, "bold"), text_color=T.WHITE, anchor="center", cursor="hand2")
                lbl.pack(fill="both", expand=True, padx=2, pady=10)

                def make_sort_cmd(k=sort_key):
                    def _sort(e):
                        if self.activity_sort_col == k: self.activity_sort_desc = not self.activity_sort_desc
                        else: self.activity_sort_col = k; self.activity_sort_desc = False
                        _update_activity_table()
                    return _sort
                cell.bind("<Button-1>", make_sort_cmd())
                lbl.bind("<Button-1>", make_sort_cmd())

            for i, d in enumerate(page_data):
                vals = [str(d['employee_id'] or 'Unknown'), str(d['full_name'] or 'Unknown'), str(d['role'] or 'Unknown'), str(d['total_borrows']), str(d['active_borrows']), str(d['total_returned'])]
                r_idx = i + 1
                bg=T.SURFACE_ALT if i % 2 == 0 else "white"
                for col, val in enumerate(vals):
                    cell = ctk.CTkFrame(self.activity_table_inner, fg_color=bg, corner_radius=0)
                    cell.grid(row=r_idx, column=col, sticky="nsew")
                    txt_col=T.TEXT
                    if col == 4 and int(val) > 0: txt_col=T.DANGER
                    font_w = "bold" if col == 4 and int(val) > 0 else "normal"
                    lbl = ctk.CTkLabel(cell, text=val, font=T.font(12, font_w), text_color=txt_col, justify="center", anchor="center")
                    lbl.configure(wraplength=min_sizes[col] - 10)
                    lbl.pack(fill="both", expand=True, padx=4, pady=12)

            for w in self.activity_pag_frame.winfo_children(): w.destroy()
            def _prev():
                if self.activity_current_page > 1: self.activity_current_page -= 1; _update_activity_table()
            def _next():
                if self.activity_current_page < total_pages: self.activity_current_page += 1; _update_activity_table()

            p_frame = ctk.CTkFrame(self.activity_pag_frame, fg_color="transparent")
            p_frame.pack(pady=10)
            prev_btn = C.button(p_frame, kind="secondary", text="< Prev", width=60, command=_prev)
            if self.activity_current_page == 1: prev_btn.configure(state="disabled", fg_color=T.SURFACE_MUTED, text_color=T.TEXT_MUTED)
            prev_btn.pack(side="left", padx=10)
            ctk.CTkLabel(p_frame, text=f"Page {self.activity_current_page} of {total_pages}   (Total: {total_items})", font=T.font(12)).pack(side="left", padx=20)
            next_btn = C.button(p_frame, kind="secondary", text="Next >", width=60, command=_next)
            if self.activity_current_page == total_pages or total_pages == 0: next_btn.configure(state="disabled", fg_color=T.SURFACE_MUTED, text_color=T.TEXT_MUTED)
            next_btn.pack(side="left", padx=10)

        import threading
        threading.Thread(target=_fetch_activity, daemon=True).start()

    # ==========================================
    # TAB 4: Project Allocation Report
    # ==========================================
    def render_project_allocation_tab(self):
        frame = ctk.CTkFrame(self.tab_content, fg_color=T.SURFACE, corner_radius=10)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=30, pady=(12, 4))
        ctk.CTkLabel(top, text="Project Allocation Report", font=T.font(16, "bold"), text_color=T.PRIMARY).pack(side="left")
        C.button(top, kind="primary", text="⎙ Export PDF", width=110, 
                      command=lambda: self.open_export_dialog("allocation")).pack(side="right")

        ctk.CTkLabel(frame, text="Shows which projects are holding tools, requested vs. deployed quantities.",
                     font=T.font(12), text_color=T.TEXT_MUTED).grid(row=1, column=0, sticky="w", padx=30, pady=(0, 4))

        scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        scroll.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 10))

        self._alloc_chart_frame = ctk.CTkFrame(scroll, fg_color="transparent")

        self._alloc_table = ctk.CTkFrame(scroll, fg_color="transparent")
        self._alloc_table.pack(fill="x")

        sd, ed, valid = self.get_and_validate_dates()
        if not valid: return

        def _fetch():
            try:
                rows = self._matching_rows(rs.allocation_report(self.user_info, sd, ed))
            except Exception as e:
                self.post_ui(lambda err=e: scroll.winfo_exists() and ctk.CTkLabel(scroll, text=friendly_message(err), text_color=T.DANGER_TEXT).pack(pady=10))
                return
            self.post_ui(lambda: _render(rows))

        def _render(rows):
            if not self.winfo_exists() or not scroll.winfo_exists(): return
            self._alloc_data = rows
            for w in self._alloc_chart_frame.winfo_children(): w.destroy()
            for w in self._alloc_table.winfo_children(): w.destroy()

            # ── Project Allocation Stacked Bar Chart ────────────
            if rows:
                proj_totals = {}
                for r in rows:
                    pn = str(r['project_name'] or 'Unknown')
                    pn = pn[:16] + ".." if len(pn) > 16 else pn
                    if pn not in proj_totals:
                        proj_totals[pn] = {"requested": 0, "issued": 0, "retrieved": 0}
                    proj_totals[pn]["requested"] += r['requested']
                    proj_totals[pn]["issued"] += r['issued']
                    proj_totals[pn]["retrieved"] += r['retrieved']
                top_projs = list(proj_totals.items())[:8]
                if top_projs:
                    labels = [p[0] for p in top_projs]
                    req = [p[1]["requested"] for p in top_projs]
                    iss = [p[1]["issued"] for p in top_projs]
                    ret = [p[1]["retrieved"] for p in top_projs]
                    fig = self._new_fig(figsize=(8, 1.8), dpi=90)
                    fig.patch.set_facecolor(T.WHITE)
                    ax = fig.add_subplot(111)
                    x = range(len(labels))
                    w = 0.25
                    ax.bar([i - w for i in x], req, width=w, label="Requested", color=T.INFO)
                    ax.bar(list(x), iss, width=w, label="Issued", color=T.SUCCESS_BRIGHT)
                    ax.bar([i + w for i in x], ret, width=w, label="Retrieved", color=T.TEXT_MUTED)
                    ax.set_xticks(list(x))
                    ax.set_xticklabels(labels, fontsize=8, rotation=15, ha="right")
                    ax.legend(fontsize=8)
                    ax.spines["top"].set_visible(False)
                    ax.spines["right"].set_visible(False)
                    fig.tight_layout()
                    chart_canvas = FigureCanvasTkAgg(fig, master=self._alloc_chart_frame)
                    chart_canvas.draw()
                    chart_canvas.get_tk_widget().pack(pady=3)
                    self._alloc_chart_frame.pack(fill="x", before=self._alloc_table, pady=(0, 4))
            # ────────────────────────────────────────────────────

            STATUS_COLORS = {"Ongoing": T.SUCCESS_BRIGHT, "Approved": T.INFO, "Pending": T.WARNING_ALT, "Completed": T.TEXT_MUTED}

            def alloc_cells(row):
                still_out = row['issued'] - row['retrieved']
                flag = "⚠ Unreturned" if still_out > 0 and row['status'] in ("Completed",) else ("Active" if still_out > 0 else "—")
                return [str(row['project_name'] or 'Unknown'), str(row['client'] or 'Unknown'), str(row['location'] or "—"), str(row['status'] or 'Pending'),
                        str(row['tool_name'] or 'Unknown'), _fmt(row['requested']), _fmt(row['issued']), _fmt(row['retrieved']), str(flag)]
            list_table(self._alloc_table, [("Project", 4, 140), ("Client", 3, 110), ("Location", 3, 110), ("Status", 2, 90), ("Tool", 4, 140),
                                           ("Requested", 2, 80), ("Issued", 2, 70), ("Retrieved", 2, 80), ("Flag", 2, 80)], rows, alloc_cells,
                       cell_style=lambda r, c, v: (STATUS_COLORS.get(v, T.TEXT), True) if c == 3 else ((T.DANGER if "⚠" in v else T.TEXT), c == 8),
                       empty_text="No project allocation data found.", font_size=12, cell_pady=10, uniform="alloc_cols")

        import threading
        threading.Thread(target=_fetch, daemon=True).start()

    # ==========================================
    # TAB 5: Damage, Loss & Maintenance Report
    # ==========================================
    def render_damage_loss_tab(self):
        frame = ctk.CTkFrame(self.tab_content, fg_color=T.SURFACE, corner_radius=10)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=30, pady=(12, 4))
        ctk.CTkLabel(top, text="Damage, Loss & Maintenance Report", font=T.font(16, "bold"), text_color=T.PRIMARY).pack(side="left")
        C.button(top, kind="primary", text="⎙ Export PDF", width=110, 
                      command=lambda: self.open_export_dialog("damage")).pack(side="right")

        ctk.CTkLabel(frame, text="Asset depreciation and financial loss metrics from returned condition data.",
                     font=T.font(12), text_color=T.TEXT_MUTED).grid(row=1, column=0, sticky="w", padx=30, pady=(0, 4))

        scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        scroll.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 10))

        self._dmg_summary_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self._dmg_chart_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self._dmg_table = ctk.CTkFrame(scroll, fg_color="transparent")
        self._dmg_table.pack(fill="x")

        sd, ed, valid = self.get_and_validate_dates()
        if not valid: return

        def _fetch():
            try:
                res = self._matching_damage(rs.damage_loss_report(self.user_info, sd, ed))
            except Exception as e:
                self.post_ui(lambda err=e: scroll.winfo_exists() and ctk.CTkLabel(scroll, text=friendly_message(err), text_color=T.DANGER_TEXT).pack(pady=10))
                return
            self.post_ui(lambda: _render(res["rows"], res["summary"]))

        def _render(rows, summary):
            if not self.winfo_exists() or not scroll.winfo_exists(): return
            self._dmg_data = rows
            for w in self._dmg_summary_frame.winfo_children(): w.destroy()

            # Summary KPI cards
            kpis = [
                ("💸 Total Loss Value", f"₱{float(summary['total_loss'] or 0):,.2f}", T.DANGER),
                ("🔨 Total Damage Value", f"₱{float(summary['total_damage'] or 0):,.2f}", T.WARNING),
                ("❌ Items Lost", _fmt(summary['count_lost']), T.DANGER),
                ("⚠ Items Damaged", _fmt(summary['count_damaged']), T.WARNING),
                ("🔧 Needs Repair", _fmt(summary['count_repair']), T.WARNING_ALT),
            ]
            for label, val, color in kpis if rows else []:
                card = ctk.CTkFrame(self._dmg_summary_frame, fg_color=T.SURFACE_ALT, corner_radius=8)
                card.pack(side="left", expand=True, fill="x", padx=5, pady=5)
                ctk.CTkLabel(card, text=label, font=T.font(12), text_color=T.TEXT_MUTED).pack(pady=(10, 2))
                ctk.CTkLabel(card, text=val, font=T.font(16, "bold"), text_color=color).pack(pady=(0, 10))
            if rows:
                self._dmg_summary_frame.pack(fill="x", before=self._dmg_table, pady=(0, 4))

            # ── Damage/Loss Pie Chart ───────────────────────────
            for w in self._dmg_chart_frame.winfo_children(): w.destroy()
            c_lost = summary['count_lost']
            c_dmg = summary['count_damaged']
            c_rep = summary['count_repair']
            if c_lost + c_dmg + c_rep > 0:
                fig = self._new_fig(figsize=(5, 1.7), dpi=90)
                fig.patch.set_facecolor(T.WHITE)
                ax = fig.add_subplot(111)
                sizes, lbls, colors = [], [], []
                if c_lost: sizes.append(c_lost); lbls.append(f"Lost ({c_lost})"); colors.append(T.DANGER)
                if c_dmg: sizes.append(c_dmg); lbls.append(f"Damaged ({c_dmg})"); colors.append(T.WARNING)
                if c_rep: sizes.append(c_rep); lbls.append(f"Needs Repair ({c_rep})"); colors.append(T.WARNING_ALT)
                ax.pie(sizes, labels=lbls, colors=colors, autopct='%1.1f%%', startangle=140)
                ax.axis('equal')
                fig.tight_layout()
                chart_canvas = FigureCanvasTkAgg(fig, master=self._dmg_chart_frame)
                chart_canvas.draw()
                chart_canvas.get_tk_widget().pack(pady=3)
                self._dmg_chart_frame.pack(fill="x", before=self._dmg_table, pady=(0, 4))
            # ────────────────────────────────────────────────────

            for w in self._dmg_table.winfo_children(): w.destroy()
            COND_COLORS = {"Lost": T.DANGER, "Damaged": T.WARNING, "Needs Repair": T.WARNING_ALT}
            list_table(self._dmg_table, [("Tool ID", 1, 60), ("Tool Name", 4, 160), ("Unit Price", 2, 100), ("Condition", 2, 110), ("Returned By", 3, 130),
                                         ("Return Date", 2, 100), ("Notes", 4, 160)], rows,
                       lambda row: [str(row['tool_id']), str(row['name'] or 'Unknown'), f"₱{float(row['price'] or 0):,.2f}", str(row['cond_flag'] or 'Unknown'),
                                    str(row['returned_by'] or "—"), str(row['return_date'] or "—"), str(row['notes'] or "")],
                       cell_style=lambda r, c, v: (COND_COLORS.get(v, T.TEXT), True) if c == 3 else (T.TEXT, False),
                       empty_text="No damage or loss records found.", font_size=12, cell_pady=10, uniform="dmg_cols")

        import threading
        threading.Thread(target=_fetch, daemon=True).start()

    # ==========================================
    # TAB 6: Low Stock / Procurement Report
    # ==========================================
    def render_low_stock_tab(self):
        frame = ctk.CTkFrame(self.tab_content, fg_color=T.SURFACE, corner_radius=10)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=0)   # title
        frame.grid_rowconfigure(1, weight=0)   # description
        frame.grid_rowconfigure(2, weight=1)   # scroll

        # Top bar
        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=30, pady=(12, 4))
        ctk.CTkLabel(top, text="Low Stock / Procurement Report", font=T.font(16, "bold"), text_color=T.PRIMARY).pack(side="left")
        C.button(top, kind="primary", text="⎙ Export PDF", width=110, 
                      command=lambda: self.open_export_dialog("lowstock")).pack(side="right")

        # Description
        ctk.CTkLabel(frame, text="Items where current available stock is at or below the set minimum threshold.",
                     font=T.font(12), text_color=T.TEXT_MUTED).grid(row=1, column=0, sticky="w", padx=30, pady=(0, 2))
        if self.navigate_to_tool:
            ctk.CTkLabel(frame, text="💡 Click any row to open that item directly in Inventory.",
                         font=T.font(12, "italic"), text_color=T.INFO_TEXT).grid(row=1, column=0, sticky="e", padx=30, pady=(0, 2))

        # Scrollable content
        scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        scroll.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 10))

        self._ls_table = ctk.CTkFrame(scroll, fg_color="transparent")

        def _fetch():
            try:
                rows = self._matching_rows(rs.low_stock_report(self.user_info))
            except Exception as e:
                self.post_ui(lambda err=e: scroll.winfo_exists() and ctk.CTkLabel(scroll, text=friendly_message(err), text_color=T.DANGER_TEXT).pack(pady=10))
                return
            self.post_ui(lambda: _render(rows))

        def _render(rows):
            if not self.winfo_exists() or not scroll.winfo_exists(): return
            self._ls_data = rows
            for w in self._ls_table.winfo_children(): w.destroy()

            self._ls_table.pack(fill="x", pady=(0, 10))

            def ls_cells(row):
                reorder_qty = max(0, float(row['minimum_stock'] or 0) * 2 - float(row['qty_avail'] or 0))
                return [str(row['tool_id']), str(row['name'] or 'Unknown'), str(row['item_type'] or 'Unknown'), str(row['category'] or 'Unknown'),
                        str(row['supplier'] or '—'), str(row['uom'] or 'pcs'), f"{float(row['qty_avail'] or 0):g}",
                        f"{float(row['qty_total'] or 0):g}", f"{float(row['minimum_stock'] or 0):g}", f"{reorder_qty:g}"]
            list_table(self._ls_table, [("PID", 1, 50), ("Name", 4, 150), ("Type", 2, 90), ("Category", 2, 100), ("Supplier", 3, 120), ("UoM", 1, 60),
                                        ("Available", 2, 80), ("Total", 2, 70), ("Min Stock", 2, 80), ("Reorder Qty", 2, 90)], rows, ls_cells,
                       row_bg=lambda r, i: T.DANGER_BG if float(r['qty_avail'] or 0) == 0 else (T.WARNING_BG if i % 2 == 0 else "white"),
                       cell_style=lambda r, c, v: ((T.DANGER if float(r['qty_avail'] or 0) == 0 else T.WARNING), True) if c == 6 else (T.TEXT, False),
                       on_row_click=(lambda r: self.navigate_to_tool(r['tool_id'])) if self.navigate_to_tool else None,
                       empty_text="✓ All items are above their minimum stock thresholds.\n\nTip: Set a Minimum Stock value per item in the Inventory module to enable this report.",
                       font_size=12, cell_pady=8, uniform="ls_cols")

        import threading
        threading.Thread(target=_fetch, daemon=True).start()

    # ==========================================
    # TAB 7: Overdue Transactions Report
    # ==========================================
    def render_overdue_tab(self):
        frame = ctk.CTkFrame(self.tab_content, fg_color=T.SURFACE, corner_radius=10)
        frame.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=30, pady=(12, 4))
        ctk.CTkLabel(top, text="Overdue Transactions Report", font=T.font(16, "bold"), text_color=T.PRIMARY).pack(side="left")
        C.button(top, kind="primary", text="⎙ Export PDF", width=110, 
                      command=lambda: self.open_export_dialog("overdue")).pack(side="right")
        ctk.CTkLabel(frame, text="Active transactions where the project end date has already passed — sorted by most overdue.",
                     font=T.font(12), text_color=T.TEXT_MUTED).grid(row=1, column=0, sticky="w", padx=30, pady=(0, 4))

        scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        scroll.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 10))

        self._ov_summary_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self._ov_chart_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self._ov_table = ctk.CTkFrame(scroll, fg_color="transparent")
        self._ov_table.pack(fill="x")
        
        loading_lbl = ctk.CTkLabel(self._ov_table, text="Loading Overdue Transactions...", font=T.font(12, "italic"), text_color=T.TEXT_MUTED)
        loading_lbl.pack(pady=20)

        sd, ed, valid = self.get_and_validate_dates()
        if not valid: return

        def _fetch():
            try:
                rows = self._matching_rows(rs.overdue_report(self.user_info, sd, ed))
            except Exception as e:
                self.post_ui(lambda err=e: scroll.winfo_exists() and ctk.CTkLabel(scroll, text=friendly_message(err), text_color=T.DANGER_TEXT).pack(pady=10))
                return
            self.post_ui(lambda: _render(rows))

        def _render(rows):
            if not self.winfo_exists() or not scroll.winfo_exists() or not loading_lbl.winfo_exists(): return
            loading_lbl.destroy()
            self._ov_data = rows
            for w in self._ov_summary_frame.winfo_children(): w.destroy()

            total_overdue = len(rows)
            unique_workers = len(set(r['employee_id'] for r in rows))
            max_days = max((int(r['days_overdue'] or 0) for r in rows), default=0)
            total_value = sum(float(r['price'] or 0) * float(r['units'] or 1) for r in rows)   # price x UNITS held

            kpis = [
                ("🚨 Overdue Items", str(total_overdue), T.DANGER),
                ("👷 Workers Involved", str(unique_workers), T.WARNING),
                ("📅 Longest Overdue", f"{max_days} days", T.DANGER),
                ("💰 At-Risk Value", f"₱{total_value:,.2f}", T.WARNING),
            ]
            for label, val, color in kpis if rows else []:
                card = ctk.CTkFrame(self._ov_summary_frame, fg_color=T.SURFACE_ALT, corner_radius=8)
                card.pack(side="left", expand=True, fill="x", padx=5, pady=5)
                ctk.CTkLabel(card, text=label, font=T.font(12), text_color=T.TEXT_MUTED).pack(pady=(10, 2))
                ctk.CTkLabel(card, text=val, font=T.font(16, "bold"), text_color=color).pack(pady=(0, 10))
            if rows:
                self._ov_summary_frame.pack(fill="x", before=self._ov_table, pady=(0, 4))

            # ── Overdue Bar Chart (days per worker) ─────────────
            for w in self._ov_chart_frame.winfo_children(): w.destroy()
            if rows:
                worker_max = {}
                for r in rows:
                    n = str(r['full_name'] or 'Unknown').split()[0]
                    worker_max[n] = max(worker_max.get(n, 0), int(r['days_overdue'] or 0))
                top_workers = sorted(worker_max.items(), key=lambda x: x[1], reverse=True)[:8]
                names = [w[0] for w in top_workers][::-1]
                days_vals = [w[1] for w in top_workers][::-1]
                fig = self._new_fig(figsize=(7, 1.7), dpi=90)
                fig.patch.set_facecolor(T.WHITE)
                ax = fig.add_subplot(111)
                ax.barh(names, days_vals, color=T.DANGER_SOFT)
                ax.set_xlabel("Days Overdue", fontsize=8)
                ax.spines["top"].set_visible(False)
                ax.spines["right"].set_visible(False)
                fig.tight_layout()
                chart_canvas = FigureCanvasTkAgg(fig, master=self._ov_chart_frame)
                chart_canvas.draw()
                chart_canvas.get_tk_widget().pack(pady=3)
                self._ov_chart_frame.pack(fill="x", before=self._ov_table, pady=(0, 4))
            # ────────────────────────────────────────────────────

            for w in self._ov_table.winfo_children(): w.destroy()
            def ov_cells(row):
                days = int(row['days_overdue'] or 0)
                borrow_str = row['borrow_date'].strftime('%Y-%m-%d') if row.get('borrow_date') else "—"
                due_str = row['due_date'].strftime('%Y-%m-%d') if row.get('due_date') else "—"
                return [str(row['employee_id'] or 'Unknown'), str(row['full_name'] or 'Unknown'), str(row['tool_name'] or 'Unknown'),
                        str(row['project_name'] or '—'), str(due_str), f"{days} days", str(borrow_str), f"₱{float(row['price'] or 0):,.2f}"]
            list_table(self._ov_table, [("Emp ID", 1, 70), ("Worker", 3, 130), ("Tool", 3, 130), ("Project", 3, 130), ("Due Date", 2, 100),
                                        ("Days Overdue", 2, 110), ("Issued On", 2, 100), ("Unit Price", 2, 100)], rows, ov_cells,
                       row_bg=lambda r, i: T.DANGER_BG if i % 2 == 0 else T.DANGER_BG,
                       cell_style=lambda r, c, v: (T.DANGER, True) if c == 5 else (T.TEXT, False),
                       empty_text="✓ No overdue transactions found.", font_size=12, cell_pady=10, uniform="ov_cols", header_bg=T.DANGER)

        import threading
        threading.Thread(target=_fetch, daemon=True).start()

    # ==========================================
    # [PANEL-AWE] Wear Forecast (printable copy of the Maintenance tab)
    # ==========================================
    def render_wear_report_tab(self):
        frame = ctk.CTkFrame(self.tab_content, fg_color=T.SURFACE, corner_radius=10)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)
        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=30, pady=(12, 4))
        ctk.CTkLabel(top, text="Wear & Maintenance Forecast", font=T.font(16, "bold"), text_color=T.PRIMARY).pack(side="left")
        C.button(top, kind="primary", text="⎙ Export PDF", width=110, 
                      command=lambda: self.open_export_dialog("wear")).pack(side="right")
        scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        scroll.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 10))
        loading = ctk.CTkLabel(scroll, text="Calculating…", text_color=T.TEXT_MUTED, font=T.font(12))
        loading.pack(pady=40)

        def _fetch():
            try:
                rows = wear_forecast.forecast(self.user_info)
            except Exception as e:
                self.post_ui(lambda err=e: scroll.winfo_exists() and self._show_error(scroll, friendly_message(err)))
                return
            self.post_ui(lambda: _render(rows))

        def _render(rows):
            if not self.winfo_exists() or not scroll.winfo_exists():
                return
            loading.destroy()
            self._wear_report_data = rows
            labels, body, _notes = wear_forecast.pdf_table(rows)
            list_table(scroll, [(l, w, m) for l, (w, m) in zip(labels, [(4, 150), (2, 100), (2, 90), (2, 80), (1, 70), (2, 100), (2, 100), (4, 170)])],
                       body, lambda cells: cells, row_bg=lambda cells, i: T.DANGER_BG if cells[7] != "-" else (T.SURFACE_ALT if i % 2 == 0 else "white"),
                       cell_style=lambda cells, c, v: (T.DANGER, True) if (c == 7 and v != "-") else (T.TEXT, False),
                       empty_text="No equipment to forecast yet.", font_size=12, cell_pady=10, uniform="wearrep_cols")

        threading.Thread(target=_fetch, daemon=True).start()

    # ==========================================
    # [PANEL-AWE] TAB 8: Anomalies & Recommendations
    # ==========================================
    def render_anomaly_tab(self):
        frame = ctk.CTkFrame(self.tab_content, fg_color=T.SURFACE, corner_radius=10)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)
        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=30, pady=(12, 4))
        ctk.CTkLabel(top, text="Anomalies & Recommendations", font=T.font(16, "bold"), text_color=T.PRIMARY).pack(side="left")
        C.button(top, kind="primary", text="⎙ Export PDF", width=110, 
                      command=lambda: self.open_export_dialog("anomaly")).pack(side="right")
        self._anomaly_summary = ctk.CTkLabel(frame, text="", font=T.font(12), text_color=T.TEXT_MUTED, wraplength=900, justify="left")
        self._anomaly_summary.grid(row=1, column=0, sticky="w", padx=30, pady=(0, 6))
        scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        scroll.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 10))
        loading = ctk.CTkLabel(scroll, text="Analysing…", text_color=T.TEXT_MUTED, font=T.font(12))
        loading.pack(pady=40)

        def _fetch():
            try:
                result = anomaly.analyse(self.user_info)
                counts = anomaly.blocked_attempts_summary(self.user_info)
            except Exception as e:
                self.post_ui(lambda err=e: scroll.winfo_exists() and self._show_error(scroll, friendly_message(err)))
                return
            self.post_ui(lambda: _render(result, counts))

        def _render(result, counts):
            if not self.winfo_exists() or not scroll.winfo_exists():
                return
            loading.destroy()
            self._anomaly_data = result
            self._anomaly_summary.configure(text=(
                f"Refused issuances in the last {anomaly.WINDOW_DAYS} days: {counts['out_of_stock']} out of stock, {counts['over_quota']} over the "
                f"approved quantity, {counts['past_end']} after the project ended.  Ranked by estimated peso impact; every line shows the numbers behind it."))
            recs = result["recommendations"]
            if not recs:
                ctk.CTkLabel(scroll, text="✓ Nothing unusual: no damage outliers, no Category A bottlenecks, no overdue clusters.",
                             text_color=T.TEXT_MUTED, font=T.font(12)).pack(pady=30)
                return
            colors = {"procure": T.INFO_HOVER, "damage": T.DANGER, "overdue": T.WARNING}
            for i, r in enumerate(recs, start=1):
                card = ctk.CTkFrame(scroll, fg_color=T.SURFACE_ALT, corner_radius=8, border_width=1, border_color=T.BORDER)
                card.pack(fill="x", padx=10, pady=(0, 8))
                head = ctk.CTkFrame(card, fg_color="transparent")
                head.pack(fill="x", padx=14, pady=(8, 2))
                ctk.CTkLabel(head, text=f"{i}. {r['title']}", font=T.font(12, "bold"), text_color=colors.get(r["kind"], T.TEXT)).pack(side="left")
                ctk.CTkLabel(head, text=f"≈ P{r['peso_impact']:,.2f}", font=T.font(12, "bold"), text_color=T.PRIMARY).pack(side="right")
                ctk.CTkLabel(card, text=r["text"], font=T.font(12), text_color=T.TEXT, wraplength=820, justify="left").pack(anchor="w", padx=14, pady=(0, 4))
                for line in r["evidence"]:
                    ctk.CTkLabel(card, text=f"   • {line}", font=T.font(12), text_color=T.TEXT_SECONDARY, justify="left").pack(anchor="w", padx=14)
                ctk.CTkFrame(card, height=6, fg_color="transparent").pack()

        threading.Thread(target=_fetch, daemon=True).start()

    # ==========================================
    # PDF Export Dialog
    # ==========================================
    def open_export_dialog(self, report_type):
        report_titles = {
            "abc": "Inventory ABC Analysis Report",
            "usage": "Tool Usage Report",
            "activity": "Employee Activity Report",
            "allocation": "Project Allocation Report",
            "damage": "Damage, Loss & Maintenance Report",
            "lowstock": "Low Stock / Procurement Report",
            "overdue": "Overdue Transactions Report",
            "wear": "Wear & Maintenance Forecast",
            "anomaly": "Anomalies & Recommendations",
        }
        title = report_titles.get(report_type, "Report")

        dialog = ctk.CTkToplevel(self)
        dialog.title(f"Export: {title}")
        dialog.geometry("460x320")
        dialog.configure(fg_color=T.BG)
        dialog.attributes("-topmost", True)
        dialog.grab_set()
        dialog.resizable(False, False)
        dialog.update_idletasks()
        sw, sh = dialog.winfo_screenwidth(), dialog.winfo_screenheight()
        dialog.geometry(f"460x320+{(sw-460)//2}+{(sh-320)//2}")

        card = C.card(dialog, 
                            border_width=1)
        card.pack(padx=20, pady=20, fill="both", expand=True)

        ctk.CTkLabel(card, text="Export Report",
                     font=T.font(16, "bold"), text_color=T.TEXT).pack(anchor="w", padx=20, pady=(18, 2))
        ctk.CTkLabel(card, text=title,
                     font=T.font(12), text_color=T.PRIMARY).pack(anchor="w", padx=20, pady=(0, 12))

        ctk.CTkFrame(card, height=1, fg_color=T.BORDER).pack(fill="x", padx=20, pady=(0, 12))

        ctk.CTkLabel(card, text="PDF note (optional; does not filter records)",
                     font=T.font(12, "bold"), text_color=T.TEXT_SECONDARY).pack(anchor="w", padx=20, pady=(4, 4))
        notes_entry = C.field(card, placeholder_text="e.g., Prepared for the October review")
        notes_entry.pack(fill="x", padx=20, pady=(0, 16))

        def do_export():
            note = notes_entry.get().strip()
            dialog.destroy()
            self.export_pdf(report_type, criteria_note=note or None)

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 16))
        C.button(btn_row, kind="primary", text="⎙ Export Now", 
                      command=do_export).pack(side="left", expand=True, fill="x", padx=(0, 8))
        C.button(btn_row, kind="secondary", text="Cancel", width=90, 
                      
                      command=dialog.destroy).pack(side="right")

        notes_entry.bind("<Return>", lambda e: do_export())
        notes_entry.focus_set()

    # ==========================================
    # PDF Export (shared across all tabs)
    # ==========================================
    def _export_rows(self, report_type, sd, ed):
        """(title, column labels, rows) for the PDF. Uses the SAME report_service queries as the screens, for the screen's date range."""
        me = self.user_info
        if report_type == "abc":
            res = rs.abc_analysis(me, sd, ed)
            names = {"A": "A (High)", "B": "B (Medium)", "C": "C (Low)"}
            rows = [[f"#{r['rank']}", str(r["tool_id"]), r["name"], _fmt(r["usage"]), f"{r['cum_pct']:.1f}%", names[r["category"]]]
                    for r in res["rows"]]
            rows.append(["", "", f"Historical total issued (incl. archived): {_fmt(res['historical_total'])}", "", "", ""])
            return "Inventory ABC Analysis Report", ["Rank", "Tool ID", "Tool Name", "Qty Issued", "Cumulative%", "Category"], rows
        if report_type == "usage":
            rows = [[str(r["tool_id"]), r["name"], r["tag_id"], _fmt(r["total_borrowed"]), _fmt(r["currently_out"]),
                     _fmt(r["qty_avail"]), r["condition"]] for r in self._matching_rows(rs.usage_report(me, sd, ed,
                         self.usage_search_var.get() if hasattr(self, 'usage_search_var') else ''))]
            return "Tool Usage Report", ["Tool ID", "Name", "Tag ID", "Qty Issued", "Currently Out", "Qty Avail", "Condition"], rows
        if report_type == "activity":
            rows = [[r["employee_id"], r["full_name"], r["role"], _fmt(r["total_borrows"]), _fmt(r["active_borrows"]), _fmt(r["total_returned"])]
                    for r in self._matching_rows(rs.activity_report(me, sd, ed))]
            return "Employee Activity Report", ["Employee ID", "Full Name", "Role", "Qty Issued", "Active", "Retrieved"], rows
        if report_type == "allocation":
            rows = [[r["project_name"], r["client"] or "—", r["location"] or "—", r["status"], r["tool_name"], _fmt(r["requested"]),
                     _fmt(r["issued"]), _fmt(r["retrieved"]),
                     "Unreturned" if r["issued"] - r["retrieved"] > 0 and r["status"] == "Completed" else "—"]
                    for r in self._matching_rows(rs.allocation_report(me, sd, ed))]
            return "Project Allocation Report", ["Project", "Client", "Location", "Status", "Tool", "Requested", "Issued", "Retrieved", "Flag"], rows
        if report_type == "damage":
            res = self._matching_damage(rs.damage_loss_report(me, sd, ed))
            rows = [[str(r["tool_id"]), r["name"], f"P{float(r['price']):,.2f}", _fmt(r["units"]), r["cond_flag"], r["returned_by"] or "—",
                     r["return_date"] or "—", r["notes"]] for r in res["rows"]]
            sm = res["summary"]
            rows.append(["", "TOTAL", "", "", f"Lost {_fmt(sm['count_lost'])} / Damaged {_fmt(sm['count_damaged'])} / Repair {_fmt(sm['count_repair'])}",
                         "", "", f"Loss P{float(sm['total_loss']):,.2f}  Damage P{float(sm['total_damage']):,.2f}"])
            return "Damage, Loss & Maintenance Report", ["Tool ID", "Tool Name", "Unit Price", "Units", "Condition", "Returned By", "Return Date", "Notes"], rows
        if report_type == "lowstock":
            rows = [[str(r["tool_id"]), r["name"], r["item_type"], r["category"], r["supplier"], r["uom"], _fmt(r["qty_avail"]),
                     _fmt(r["minimum_stock"]), _fmt(max(0, float(r["minimum_stock"]) * 2 - float(r["qty_avail"])))]
                    for r in self._matching_rows(rs.low_stock_report(me))]
            return "Low Stock / Procurement Report", ["PID", "Name", "Type", "Category", "Supplier", "UoM", "Available", "Min Stock", "Reorder Qty"], rows
        if report_type == "overdue":
            rows = [[r["employee_id"], r["full_name"], r["tool_name"], r["project_name"],
                     r["due_date"].strftime("%Y-%m-%d") if r.get("due_date") else "—", f"{int(r['days_overdue'] or 0)} days",
                     r["borrow_date"].strftime("%Y-%m-%d") if r.get("borrow_date") else "—", _fmt(r["units"]),
                     f"P{float(r['price']):,.2f}"] for r in self._matching_rows(rs.overdue_report(me, sd, ed))]
            return "Overdue Transactions Report", ["Emp ID", "Worker", "Tool", "Project", "Due Date", "Days Overdue", "Issued On", "Units", "Unit Price"], rows
        return "Report", [], []

    def _export_document(self, report_type, sd, ed):
        """(title, sections, notes): sections = [(heading, labels, rows)]. Every type uses the same query functions as its screen."""
        if report_type == "wear":
            labels, rows, notes = wear_forecast.pdf_table(wear_forecast.forecast(self.user_info))
            return "Wear & Maintenance Forecast", [(None, labels, rows, [4, 3, 2, 2, 2, 3, 2, 4])], notes
        if report_type == "anomaly":
            notes, sections = anomaly.pdf_sections(anomaly.analyse(self.user_info), anomaly.blocked_attempts_summary(self.user_info))
            return "Anomalies & Recommendations", sections, notes
        title, labels, rows = self._export_rows(report_type, sd, ed)
        return title, [(None, labels, rows)], []

    def export_pdf(self, report_type, criteria_note=None):
        try:
            sd, ed, valid = self.get_and_validate_dates()
            if not valid:
                return
            if not C.confirm("Export report", f"Create the {report_type} PDF for {sd or 'the first record'} through {ed or 'today'}?", parent=self.winfo_toplevel()):
                return
            try:
                title, sections, notes = self._export_document(report_type, sd, ed)
            except Exception as e:
                messagebox.showerror("Export Error", friendly_message(e), parent=self.winfo_toplevel())
                return
            criteria_parts = (["Stock as of today"] if report_type == "lowstock" else
                              ["Period: " + (f"{sd or 'beginning'} to {ed or 'today'}" if (sd or ed) else "All time")])
            if report_type == "usage" and hasattr(self, "usage_search_var") and self.usage_search_var.get().strip():
                criteria_parts.append("Search: " + self.usage_search_var.get().strip())
            if self.report_search_var.get().strip():
                criteria_parts.append("Search: " + self.report_search_var.get().strip())
            if criteria_note:
                criteria_parts.append(f"Notes: {criteria_note}")
            fpath = os.path.join(tempfile.gettempdir(), f"Report_{report_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
            try:
                render_pdf(title, "  |  ".join(criteria_parts), sections, fpath, notes)
            except Exception as e:
                messagebox.showerror("Export Error", friendly_message(e), parent=self.winfo_toplevel())
                return
            try:
                os.startfile(fpath)
            except OSError:
                messagebox.showinfo("Report saved", f"The report was saved but no program could open it.\nYou can find it here:\n{fpath}",
                                    parent=self.winfo_toplevel())
        except Exception as e:
            messagebox.showerror("Export Error", friendly_message(e), parent=self.winfo_toplevel())
