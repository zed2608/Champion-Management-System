import customtkinter as ctk
from views.ui_thread import UiMixin
from tkinter import messagebox, filedialog
from database import get_connection, log_action
from datetime import datetime
import os
import subprocess
import threading
from services.validators import fmt_qty
from services.errors import friendly_message
from services import backup_service, wear_forecast
from services.paging import PageInfo, clamp_page, fetch_page
from services.validators import like_pattern
from views.paged_table import PagedTable, list_table
from services import maintenance_service as mnt, inventory_service as inv_svc, project_service as proj_svc, user_service
from ui import components as C
from ui import theme as T


class MaintenanceView(UiMixin, ctk.CTkFrame):
    def __init__(self, parent, user_info=None):
        super().__init__(parent, fg_color="transparent")
        self._ui_init()

        self.user_info = user_info or {}
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.build_view()

        uid = self.user_info.get("user_id")
        if uid:
            log_action(uid, "Viewed", "Maintenance",
                       "Opened Maintenance module")

    def build_view(self):
        # Run schema migration once before any tab tries to query user columns

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)

        top_bar = ctk.CTkFrame(self, fg_color="transparent")
        top_bar.grid(row=0, column=0, sticky="ew", padx=20, pady=(10, 15))

        C.PageHeader(top_bar, "Maintenance & Archive", "Repairs, archives, service forecasts and backups").pack(side="top", anchor="w")

        tab_labels = [
            "🔧 Issues & Repairs",
            "📦 Archived Tools",
            "👥 Archived Employees",
            "📋 Archived Projects",
            "📈 Wear Forecast",
            "💾 Backup & Restore",
        ]
        self.tab_var = ctk.StringVar(value=tab_labels[0])
        self.seg_btn = ctk.CTkSegmentedButton(
            top_bar, values=tab_labels, variable=self.tab_var,
            command=self.switch_tab,
            fg_color=T.SURFACE_MUTED, selected_color=T.PRIMARY,
            selected_hover_color=T.PRIMARY_HOVER
        )
        self.seg_btn.pack(side="top", anchor="w", pady=(10, 0))

        self.tab_content = ctk.CTkFrame(self, fg_color="transparent")
        self.tab_content.grid(
            row=1, column=0, sticky="nsew", padx=10, pady=(0, 20))
        self.tab_content.grid_columnconfigure(0, weight=1)
        self.tab_content.grid_rowconfigure(0, weight=1)

        self.cached_tabs = {}
        self.switch_tab(tab_labels[0])

    def switch_tab(self, selected_tab):
        if hasattr(self, "current_tab") and self.current_tab:
            self.current_tab.grid_remove()

        if selected_tab not in self.cached_tabs:
            if "Issues" in selected_tab:
                self.cached_tabs[selected_tab] = self.render_issues_tab()
            elif "Tools" in selected_tab:
                self.cached_tabs[selected_tab] = self.render_tools_tab()
            elif "Employees" in selected_tab:
                self.cached_tabs[selected_tab] = self.render_employees_tab()
            elif "Projects" in selected_tab:
                self.cached_tabs[selected_tab] = self.render_projects_tab()
            elif "Wear" in selected_tab:
                self.cached_tabs[selected_tab] = self.render_wear_tab()
            elif "Backup" in selected_tab:
                self.cached_tabs[selected_tab] = self.render_backup_tab()

        self.current_tab = self.cached_tabs[selected_tab]
        self.current_tab.grid(row=0, column=0, sticky="nsew")

        if "Issues" in selected_tab:
            self.load_issues()
        elif "Tools" in selected_tab:
            self.load_archived_tools()
        elif "Employees" in selected_tab:
            self.load_archived_employees()
        elif "Projects" in selected_tab:
            self.load_archived_projects()
        elif "Wear" in selected_tab:
            self.load_wear()
        elif "Backup" in selected_tab:
            self.load_backup_history()

    # ------------------------------------------
    # TAB 1: Manage Issues
    # ------------------------------------------
    def render_issues_tab(self):
        frame = ctk.CTkFrame(
            self.tab_content, fg_color=T.SURFACE, corner_radius=10)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(20, 5))
        ctk.CTkLabel(top, text="Tool Issue Management",
                     font=T.font(16, "bold"), text_color=T.TEXT).pack(side="left")

        ctk.CTkLabel(frame,
                     text="Flag damaged or lost tools, track discrepancies, and manage resolutions. "
                          "Flagging a tool automatically updates its condition in the inventory.",
                     font=T.font(12), text_color=T.TEXT_MUTED,
                     wraplength=750, justify="left").pack(anchor="w", padx=20, pady=(0, 10))

        flag_card = ctk.CTkFrame(frame, fg_color=T.SURFACE_ALT, corner_radius=10)
        flag_card.pack(fill="x", padx=20, pady=(0, 12))

        ctk.CTkLabel(flag_card, text="🚩  Flag a Tool Issue",
                     font=T.font(14, "bold"), text_color=T.DANGER_TEXT).pack(anchor="w", padx=15, pady=(12, 8))

        form_grid = ctk.CTkFrame(flag_card, fg_color="transparent")
        form_grid.pack(fill="x", padx=15, pady=(0, 8))
        form_grid.grid_columnconfigure((0, 1, 2, 3), weight=1)

        ctk.CTkLabel(form_grid, text="Tool PID or Tag ID", font=T.font(12, "bold"),
                     text_color=T.TEXT).grid(row=0, column=0, sticky="w", padx=5)
        ctk.CTkLabel(form_grid, text="Reported By (Employee ID)", font=T.font(12, "bold"),
                     text_color=T.TEXT).grid(row=0, column=1, sticky="w", padx=5)
        ctk.CTkLabel(form_grid, text="Issue / Condition Type", font=T.font(12, "bold"),
                     text_color=T.TEXT).grid(row=0, column=2, sticky="w", padx=5)

        self.flag_tool_id = C.field(
            form_grid, placeholder_text="e.g., TAG-003 or PID 42")
        self.flag_tool_id.grid(
            row=1, column=0, sticky="ew", padx=5, pady=(3, 8))
        self.flag_reported_by = C.field(
            form_grid, placeholder_text="e.g., EMP-001")
        self.flag_reported_by.grid(
            row=1, column=1, sticky="ew", padx=5, pady=(3, 8))
        self.flag_condition = ctk.CTkOptionMenu(
            form_grid,
            values=["Damaged", "Lost", "Needs Repair", "Discrepancy",
                    "Missing Parts", "Stolen", "Other"],
            fg_color=T.SURFACE_ALT, text_color=T.TEXT
        )
        self.flag_condition.grid(
            row=1, column=2, sticky="ew", padx=5, pady=(3, 8))
        ctk.CTkLabel(form_grid, text="Units (qty)", font=T.font(12, "bold"),
                     text_color=T.TEXT).grid(row=0, column=3, sticky="w", padx=5)
        self.flag_qty = C.field(form_grid, placeholder_text="1")
        self.flag_qty.grid(row=1, column=3, sticky="ew", padx=5, pady=(3, 8))
        self.flag_qty.insert(0, "1")

        notes_row = ctk.CTkFrame(flag_card, fg_color="transparent")
        notes_row.pack(fill="x", padx=15, pady=(0, 12))
        notes_row.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(notes_row, text="Issue Description / Notes",
                     font=T.font(12, "bold"), text_color=T.TEXT).grid(
            row=0, column=0, sticky="w", pady=(0, 3))
        self.flag_notes = C.field(
            notes_row, placeholder_text="Describe the issue in detail...")
        self.flag_notes.grid(row=1, column=0, sticky="ew", padx=(0, 10))

        C.button(notes_row, kind="danger", text="Submit Flag", width=130,
                      
                      
                      command=self.submit_flag).grid(row=1, column=1, padx=(0, 0))

        filter_row = ctk.CTkFrame(frame, fg_color="transparent")
        filter_row.pack(fill="x", padx=20, pady=(0, 5))

        ctk.CTkLabel(filter_row, text="Show:", font=T.font(12), text_color=T.TEXT_MUTED).pack(side="left")
        self.issues_filter = ctk.CTkOptionMenu(
            filter_row, values=["Open (Pending)", "All Issues", "Resolved"],
            width=150, fg_color=T.SURFACE_ALT, text_color=T.TEXT,
            command=lambda e: self.load_issues()
        )
        self.issues_filter.pack(side="left", padx=8)
        self.issues_filter.set("Open (Pending)")

        self.issues_search_var = ctk.StringVar()
        self.issues_search = C.field(filter_row, placeholder_text="Search tool or reporter...",
                                          width=200, textvariable=self.issues_search_var)
        self.issues_search.pack(side="left", padx=(0, 5))

        self._issues_timer = None

        def on_issues_search(*args):
            if self._issues_timer:
                self.after_cancel(self._issues_timer)
            self._issues_timer = self.after(300, self.load_issues)
        self.issues_search_var.trace_add("write", on_issues_search)

        self.issues_summary = ctk.CTkLabel(frame, text="", font=T.font(12, "bold"),
                                           text_color=T.PRIMARY)
        self.issues_summary.pack(anchor="w", padx=20, pady=(0, 5))

        self._issues_scroll = ctk.CTkScrollableFrame(
            frame, fg_color="transparent")
        self._issues_scroll.pack(
            fill="both", expand=True, padx=20, pady=(5, 20))
        return frame

    def submit_flag(self):
        tool_input = self.flag_tool_id.get().strip()
        reported_by = self.flag_reported_by.get().strip()
        condition = self.flag_condition.get()
        notes = self.flag_notes.get().strip()
        qty = self.flag_qty.get().strip() or "1"

        if not tool_input or not reported_by:
            messagebox.showerror("Error", "Tool ID/Tag and Reported By are required.",
                                 parent=self.winfo_toplevel())
            return
        try:
            # [CONCURRENCY][RBAC] one transaction: locks the tool's stock, moves exactly these units, creates the ticket
            res = mnt.flag_tool(self.user_info, tool_input, reported_by, condition, notes, qty)
        except Exception as e:
            messagebox.showerror("Could not flag", friendly_message(e), parent=self.winfo_toplevel())
            return

        uid = self.user_info.get("user_id")
        if uid:
            log_action(uid, "Flagged", "Maintenance",
                       f"Flagged tool '{res['name']}' (PID: {res['tool_id']}) x{qty} - {condition}: {notes}")
        what = (f"{qty} unit(s) were taken out of circulation." if res["moved"]
                else "This is a record only; no stock was moved.")
        messagebox.showinfo("Flagged", f"Tool '{res['name']}' has been flagged ({condition}).\n{what}",
                            parent=self.winfo_toplevel())
        self.flag_tool_id.delete(0, "end")
        self.flag_reported_by.delete(0, "end")
        self.flag_notes.delete(0, "end")
        self.flag_qty.delete(0, "end")
        self.flag_qty.insert(0, "1")
        self.load_issues()

    ISSUE_COLUMNS = [("#", 1, 50), ("Tool Name", 3, 150), ("Reported By", 2, 100), ("Issue Type", 2, 100), ("Description", 4, 200),
                     ("Flagged At", 3, 150), ("Status", 2, 100)]
    ISSUE_COLORS = {"Damaged": T.DANGER_SOFT, "Lost": T.DANGER_HOVER, "Needs Repair": T.WARNING_ALT, "Discrepancy": T.PURPLE, "Stolen": T.DANGER_HOVER,
                    "Missing Parts": T.WARNING_STRONG, "Other": T.TEXT_MUTED}

    def load_issues(self, keep_page=False):
        self._issues_filter_val = self.issues_filter.get() if hasattr(self, "issues_filter") else "Open (Pending)"      # main thread
        self._issues_query = self.issues_search.get().strip() if hasattr(self, "issues_search") else ""
        if getattr(self, "_issues_table", None) is None or not self._issues_table.winfo_exists():
            for w in self._issues_scroll.winfo_children():
                w.destroy()
            self._issues_table = PagedTable(
                self._issues_scroll, self.ISSUE_COLUMNS, fetch=self._fetch_issues_page,
                cells=lambda r: [str(r["issue_id"]), r["tool_name"], r["reported_by"], r["condition_flag"], r["notes"],
                                 r["flagged_at"], "✓ Resolved" if r["is_resolved"] else "⚠ Pending"],
                row_bg=lambda r, i: T.SUCCESS_BG if r["is_resolved"] else (T.WARNING_BG if i % 2 == 0 else T.DANGER_BG),
                cell_style=lambda r, c, v: (self.ISSUE_COLORS.get(v, T.WARNING_STRONG), True) if c == 3 else
                                           (((T.SUCCESS_TEXT if "Resolved" in v else T.DANGER), True) if c == 6 else (T.TEXT, False)),
                on_row_click=self.open_issue_modal, on_loaded=self._issues_loaded, empty_text="No issues found. Inventory is clean.",
                font_size=12, cell_pady=12, uniform="issue_cols")
            self._issues_table.pack(fill="x", expand=True)
        self._issues_table.reload(self._issues_table.page if keep_page else 0)

    def _fetch_issues_page(self, page, size):
        where, params = "WHERE 1=1", []
        if self._issues_filter_val == "Open (Pending)":
            where += " AND ti.is_resolved = 0"
        elif self._issues_filter_val == "Resolved":
            where += " AND ti.is_resolved = 1"
        if self._issues_query:
            where += " AND (t.name LIKE %s OR ti.reported_by LIKE %s OR ti.condition_flag LIKE %s)"
            params += [like_pattern(self._issues_query)] * 3
        frm = f"FROM tool_issues ti JOIN tool t ON ti.tool_id = t.tool_id {where}"
        conn = get_connection()
        if not conn:
            raise ConnectionError("The database is not reachable.")
        try:
            cur = conn.cursor(dictionary=True)
            # [UNHAPPY-PATH] no auto-sync here any more: tickets are created inside the transaction that causes them
            # (retrieval, manual flag) and, once, by `db.migrate` for tools the old screens had flagged.
            rows, info = fetch_page(
                cur, "SELECT ti.issue_id, t.name as tool_name, ti.reported_by, ti.condition_flag, IFNULL(ti.notes,'—') as notes, ti.flagged_at, ti.is_resolved",
                frm, params, "ORDER BY ti.is_resolved ASC, ti.flagged_at DESC, ti.issue_id DESC", page, size)
            cur.execute(f"SELECT COALESCE(SUM(ti.is_resolved = 0), 0) AS open_n {frm}", tuple(params))
            self._issues_open = int(cur.fetchone()["open_n"] or 0)
            return rows, info
        finally:
            if conn.is_connected():
                conn.close()

    def _issues_loaded(self, rows, info):
        if hasattr(self, "issues_summary") and self.issues_summary.winfo_exists():
            opened = getattr(self, "_issues_open", 0)
            self.issues_summary.configure(text=f"  Total: {info.total}   |   Open: {opened}   |   Resolved: {info.total - opened}")

    def open_issue_modal(self, row):
        modal = ctk.CTkToplevel(self)
        modal.title(f"Issue #{row['issue_id']} — {row['tool_name']}")
        modal.configure(fg_color=T.SURFACE)
        modal.attributes("-topmost", True)
        modal.grab_set()

        modal.update_idletasks()
        x = (modal.winfo_screenwidth() // 2) - (480 // 2)
        y = (modal.winfo_screenheight() // 2) - (470 // 2)
        modal.geometry(f"480x470+{x}+{y}")

        status_color=T.SUCCESS_TEXT if row["is_resolved"] else T.DANGER
        status_text = "✓ RESOLVED" if row["is_resolved"] else "⚠ PENDING"
        ctk.CTkLabel(modal, text=f"Issue #{row['issue_id']}: {row['tool_name']}",
                     font=T.font(16, "bold"), text_color=T.TEXT).pack(pady=(20, 3))
        ctk.CTkLabel(modal, text=f"{status_text}  |  Flagged by: {row['reported_by']}",
                     font=T.font(12, "bold"), text_color=status_color).pack(pady=(0, 5))
        ctk.CTkLabel(modal, text=f"Flagged At: {row['flagged_at']}",
                     font=T.font(12), text_color=T.TEXT_MUTED).pack(pady=(0, 10))

        detail_card = ctk.CTkFrame(modal, fg_color=T.SURFACE_ALT, corner_radius=8)
        detail_card.pack(fill="x", padx=25, pady=(0, 10))
        ctk.CTkLabel(detail_card, text=f"Issue Type:  {row['condition_flag']}",
                     font=T.font(12, "bold"), text_color=T.WARNING_TEXT).pack(anchor="w", padx=15, pady=(10, 3))
        ctk.CTkLabel(detail_card, text=f"Description:  {row['notes']}",
                     font=T.font(12), text_color=T.TEXT,
                     wraplength=400, justify="left").pack(anchor="w", padx=15, pady=(0, 10))

        form = ctk.CTkFrame(modal, fg_color="transparent")
        form.pack(fill="x", padx=25)

        ctk.CTkLabel(form, text="Final condition of the affected unit(s):", font=T.font(12, "bold"),
                     text_color=T.TEXT).pack(anchor="w")
        ctk.CTkLabel(form, text="Good = return the unit(s) to stock.  Anything else = remove them from stock for good.",
                     font=T.font(12), text_color=T.TEXT_MUTED, wraplength=420, justify="left").pack(anchor="w")
        cond_menu = ctk.CTkOptionMenu(
            form, values=["Good", "Needs Repair", "Damaged", "Lost"],
            fg_color=T.SURFACE_ALT, text_color=T.TEXT)
        cond_menu.set(row["condition_flag"] if row["condition_flag"] in
                      ["Good", "Needs Repair", "Damaged", "Lost"] else "Needs Repair")
        cond_menu.pack(fill="x", pady=(5, 10))

        ctk.CTkLabel(form, text="New units to add (replacement bought / found):", font=T.font(12, "bold"),
                     text_color=T.TEXT).pack(anchor="w")
        restock_entry = C.field(
            form, placeholder_text="0 (Leave 0 if already in stock)")
        restock_entry.pack(fill="x", pady=(5, 10))

        ctk.CTkLabel(form, text="Resolution Notes:", font=T.font(12, "bold"),
                     text_color=T.TEXT).pack(anchor="w")
        notes_entry = C.field(
            form, placeholder_text="e.g., Sent to repair, replaced, etc.")
        notes_entry.pack(fill="x", pady=(5, 10))

        def resolve_issue():
            try:
                # [CONCURRENCY] one transaction: locks the ticket (a stale modal is refused) and the stock, moves the units
                out = mnt.resolve_issue(self.user_info, row["issue_id"], cond_menu.get(),
                                        restock_entry.get().strip(), notes_entry.get().strip())
            except Exception as e:
                messagebox.showerror("Could not resolve", friendly_message(e), parent=modal)
                return
            uid = self.user_info.get("user_id")
            if uid:
                log_action(uid, "Resolved", "Maintenance",
                           f"Resolved issue #{row['issue_id']} for '{row['tool_name']}'. Outcome: {out['outcome']} ({out['effect']})")
            messagebox.showinfo("Resolved", f"Issue resolved: {out['effect']}.", parent=modal)
            modal.destroy()
            self.load_issues(keep_page=True)

        btn_row = ctk.CTkFrame(modal, fg_color="transparent")
        btn_row.pack(fill="x", padx=25, pady=(5, 20))
        C.button(btn_row, kind="primary", text="✓ Mark Resolved & Update Inventory",
                      
                      command=resolve_issue).pack(side="left", padx=(0, 10), fill="x", expand=True)
        C.button(btn_row, kind="secondary", text="Close", 
                      width=80,
                      command=modal.destroy).pack(side="right")

    # ------------------------------------------
    # [PANEL-AWE] Wear Forecast
    # ------------------------------------------
    def render_wear_tab(self):
        frame = ctk.CTkFrame(self.tab_content, fg_color=T.SURFACE, corner_radius=10)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)
        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(20, 5))
        ctk.CTkLabel(top, text="Wear & Maintenance Forecast", font=T.font(16, "bold"), text_color=T.TEXT).pack(side="left")
        ctk.CTkLabel(frame, text="Hours each tool has been out on jobs (open issuances count up to now), how much of its service interval is used, "
                                 "and when service is due at the last 30 days' pace. Click a row to set that tool's own interval or mark it serviced.",
                     font=T.font(12), text_color=T.TEXT_MUTED, wraplength=900, justify="left").pack(anchor="w", padx=20, pady=(0, 8))
        row = ctk.CTkFrame(frame, fg_color=T.SURFACE_ALT, corner_radius=8)
        row.pack(fill="x", padx=20, pady=(0, 8))
        ctk.CTkLabel(row, text="Default interval - category:", font=T.font(12, "bold")).pack(side="left", padx=(12, 6), pady=10)
        self.wear_cat = C.field(row, placeholder_text="e.g. Drills (or * for all others)", width=220)
        self.wear_cat.pack(side="left", padx=4)
        self.wear_hours = C.field(row, placeholder_text="hours", width=90)
        self.wear_hours.pack(side="left", padx=4)
        C.button(row, kind="primary", text="Save default", width=110, command=self.save_wear_default).pack(side="left", padx=8)
        self.wear_defaults_lbl = ctk.CTkLabel(row, text="", font=T.font(12), text_color=T.TEXT_MUTED)
        self.wear_defaults_lbl.pack(side="left", padx=8)
        self._wear_scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        self._wear_scroll.pack(fill="both", expand=True, padx=20, pady=(5, 20))
        return frame

    WEAR_COLUMNS = [("Tool", 4, 150), ("Category", 2, 100), ("Hours used", 2, 90), ("Interval", 2, 80), ("% used", 1, 70), ("Due in", 2, 100),
                    ("Damage / 100 h", 2, 100), ("Flags", 4, 170)]

    def load_wear(self, keep_page=False):
        for w in self._wear_scroll.winfo_children():
            w.destroy()
        loading = ctk.CTkLabel(self._wear_scroll, text="Calculating...", text_color=T.TEXT_MUTED, font=T.font(12, "italic"))
        loading.pack(pady=20)

        def work():
            try:
                rows = wear_forecast.forecast(self.user_info)
                defaults = wear_forecast.list_defaults(self.user_info)
            except Exception as e:
                msg = friendly_message(e)
                self.post_ui(lambda: loading.winfo_exists() and loading.configure(text=msg, text_color=T.DANGER_TEXT))
                return
            self.post_ui(lambda: self._show_wear(rows, defaults, loading))
        threading.Thread(target=work, daemon=True).start()

    def _show_wear(self, rows, defaults, loading):
        if not loading.winfo_exists():
            return
        loading.destroy()
        self.wear_defaults_lbl.configure(text="Now: " + ", ".join(f"{d['category']} = {d['hours']} h" for d in defaults))

        def due(r):
            if r["days_to_due"] is None:
                return "not used lately"
            return "overdue" if r["days_to_due"] <= 0 else f"{r['days_to_due']:g} days"
        self._wear_table = list_table(
            self._wear_scroll, self.WEAR_COLUMNS, rows,
            lambda r: [r["name"], r["category"], f"{r['hours_since_service']:g}", f"{r['interval']:g}", f"{r['pct_used']:g}%", due(r),
                       "-" if r["damage_rate"] is None else f"{r['damage_rate']:g}", ", ".join(r["flags"]) or "-"],
            row_bg=lambda r, i: T.DANGER_BG if r["flags"] else (T.SURFACE_ALT if i % 2 == 0 else "white"),
            cell_style=lambda r, c, v: (T.DANGER, True) if (c == 7 and v != "-") else (T.TEXT, False),
            on_row_click=self.open_wear_modal, empty_text="No equipment to forecast yet.", font_size=12, cell_pady=10, uniform="wear_cols")

    def save_wear_default(self):
        cat, hours = self.wear_cat.get().strip(), self.wear_hours.get().strip()
        try:
            wear_forecast.set_category_default(self.user_info, cat, hours)
        except Exception as e:
            messagebox.showerror("Could not save", friendly_message(e), parent=self.winfo_toplevel())
            return
        log_action(self.user_info.get("user_id"), "Edited", "Maintenance", f"Service interval for '{cat}' set to {hours} hours")
        self.wear_cat.delete(0, "end")
        self.wear_hours.delete(0, "end")
        self.load_wear()

    def open_wear_modal(self, row):
        modal = ctk.CTkToplevel(self)
        modal.title(f"Service - {row['name']}")
        modal.configure(fg_color=T.SURFACE)
        modal.attributes("-topmost", True)
        modal.grab_set()
        modal.geometry("460x330")
        ctk.CTkLabel(modal, text=row["name"], font=T.font(16, "bold")).pack(pady=(18, 4))
        ctk.CTkLabel(modal, text=wear_forecast.summary_line(row), font=T.font(12), text_color=T.TEXT_SECONDARY, wraplength=400, justify="left").pack(padx=24, pady=(0, 10))
        ctk.CTkLabel(modal, text="Own service interval in hours (empty = category default):", font=T.font(12, "bold")).pack(anchor="w", padx=24)
        entry = C.field(modal)
        entry.pack(fill="x", padx=24, pady=(4, 10))

        def save():
            try:
                wear_forecast.set_tool_interval(self.user_info, row["tool_id"], entry.get().strip())
            except Exception as e:
                messagebox.showerror("Could not save", friendly_message(e), parent=modal)
                return
            modal.destroy()
            self.load_wear()

        def serviced():
            if not messagebox.askyesno("Mark serviced", f"Restart the service clock of '{row['name']}' from now?", parent=modal):
                return
            try:
                wear_forecast.mark_serviced(self.user_info, row["tool_id"])
            except Exception as e:
                messagebox.showerror("Could not save", friendly_message(e), parent=modal)
                return
            modal.destroy()
            self.load_wear()
        C.button(modal, kind="primary", text="Save interval", command=save).pack(fill="x", padx=24, pady=4)
        C.button(modal, kind="primary", text="Mark serviced now", command=serviced).pack(fill="x", padx=24, pady=4)
        C.button(modal, kind="secondary", text="Close", command=modal.destroy).pack(fill="x", padx=24, pady=4)

    # ------------------------------------------
    # TAB 2: Archived Tools
    # ------------------------------------------
    def render_tools_tab(self):
        frame = ctk.CTkFrame(
            self.tab_content, fg_color=T.SURFACE, corner_radius=10)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(20, 10))
        ctk.CTkLabel(top, text="Archived & Decommissioned Tools",
                     font=T.font(16, "bold"), text_color=T.TEXT).pack(side="left")

        self._tools_scroll = ctk.CTkScrollableFrame(
            frame, fg_color="transparent")
        self._tools_scroll.pack(
            fill="both", expand=True, padx=20, pady=(5, 20))
        return frame

    def load_archived_tools(self, keep_page=False):
        if getattr(self, "_tools_table", None) is None or not self._tools_table.winfo_exists():
            for w in self._tools_scroll.winfo_children():
                w.destroy()
            self._tools_table = PagedTable(
                self._tools_scroll, [("Tool ID", 1, 70), ("Name", 3, 200), ("Category", 2, 150), ("Qty", 1, 60), ("Archived At", 2, 150), ("Action", 1, 100)],
                fetch=self._fetch_archived_tools,
                cells=lambda r: [str(r["tool_id"]), r["name"], r["category"], f"{fmt_qty(r['qty_total'])}",
                                 r["archived_date"].strftime("%Y-%m-%d %H:%M") if r["archived_date"] else "—", ""],
                actions={5: {"text": "Restore", "command": lambda r: self.restore_tool(r["tool_id"])}},
                empty_text="No archived tools found.", font_size=12, cell_pady=12, uniform="tool_cols")
            self._tools_table.pack(fill="x", expand=True)
        self._tools_table.reload(self._tools_table.page if keep_page else 0)

    def _fetch_archived_tools(self, page, size):
        conn = get_connection()
        if not conn:
            raise ConnectionError("The database is not reachable.")
        try:
            cur = conn.cursor(dictionary=True)
            return fetch_page(
                cur, """SELECT t.tool_id, t.name, t.category, t.`condition`, IFNULL(t.archived_at, t.date_acquired) as archived_date,
                               IFNULL(i.quantity_total, 0) as qty_total""",
                "FROM tool t LEFT JOIN inventory i ON t.tool_id = i.tool_id WHERE t.is_archived = 1", [],
                "ORDER BY t.archived_at DESC, t.tool_id DESC", page, size)
        finally:
            if conn.is_connected():
                conn.close()

    def restore_tool(self, tool_id):
        if not messagebox.askyesno("Confirm Restore", f"Are you sure you want to restore Tool PID: {tool_id}?"):
            return
        try:
            res = inv_svc.restore_tool(self.user_info, tool_id)
        except Exception as e:
            messagebox.showerror("Could not restore", friendly_message(e))
            return
        uid = self.user_info.get("user_id")
        if uid:
            log_action(uid, "Edited", "Maintenance", f"Restored Tool PID: {tool_id} ('{res['name']}') from Archive")
        C.notify(self, "Tool restored to active inventory.")
        self.load_archived_tools(keep_page=True)

    # ------------------------------------------
    # TAB 3: Archived Employees
    # ------------------------------------------
    def render_employees_tab(self):
        frame = ctk.CTkFrame(
            self.tab_content, fg_color=T.SURFACE, corner_radius=10)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(20, 10))
        ctk.CTkLabel(top, text="Inactive / Archived Employees",
                     font=T.font(16, "bold"), text_color=T.TEXT).pack(side="left")

        self._emp_scroll = ctk.CTkScrollableFrame(
            frame, fg_color="transparent")
        self._emp_scroll.pack(fill="both", expand=True, padx=20, pady=(5, 20))
        return frame

    def load_archived_employees(self, keep_page=False):
        if getattr(self, "_emp_table", None) is None or not self._emp_table.winfo_exists():
            for w in self._emp_scroll.winfo_children():
                w.destroy()
            self._emp_table = PagedTable(
                self._emp_scroll, [("User ID", 1, 60), ("Employee ID", 2, 100), ("Full Name", 3, 180), ("Role", 2, 100), ("Status", 2, 100),
                                   ("Archived At", 2, 150), ("Action", 1, 100)],
                fetch=self._fetch_archived_employees,
                cells=lambda r: [str(r["user_id"]), r["employee_id"], r["full_name"], r["role"], r["status"] or "Inactive",
                                 r["archived_at"].strftime("%Y-%m-%d %H:%M:%S") if r.get("archived_at") else "—", ""],
                actions={6: {"text": "Restore", "command": lambda r: self.restore_employee(r["user_id"])}},
                empty_text="No archived employees found.", font_size=12, cell_pady=12, uniform="emp_cols")
            self._emp_table.pack(fill="x", expand=True)
        self._emp_table.reload(self._emp_table.page if keep_page else 0)

    def _fetch_archived_employees(self, page, size):
        conn = get_connection()
        if not conn:
            raise ConnectionError("The database is not reachable.")
        try:
            cur = conn.cursor(dictionary=True)
            return fetch_page(cur, "SELECT user_id, employee_id, full_name, role, status, archived_at",
                              "FROM `user` WHERE IFNULL(status, 'Inactive') != 'Active'", [],
                              "ORDER BY archived_at DESC, user_id DESC", page, size)
        finally:
            if conn.is_connected():
                conn.close()

    def restore_employee(self, user_id):
        if not messagebox.askyesno("Confirm Restore", "Restore this employee to Active status? They will be able to log in (Staff/Admin) or receive tools (Workers) again."):
            return
        try:
            res = user_service.restore_user(self.user_info, user_id)
        except Exception as e:
            messagebox.showerror("Could not restore", friendly_message(e))
            return
        uid = self.user_info.get("user_id")
        if uid:
            log_action(uid, "Edited", "Maintenance", f"Restored employee {res['name']} ({res['employee_id']}) from Archive")
        C.notify(self, f"{res['name']} was restored.")
        self.load_archived_employees(keep_page=True)

    # ------------------------------------------
    # TAB 4: Archived Projects
    # ------------------------------------------
    def render_projects_tab(self):
        frame = ctk.CTkFrame(
            self.tab_content, fg_color=T.SURFACE, corner_radius=10)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(20, 10))
        ctk.CTkLabel(top, text="Completed / Archived Projects",
                     font=T.font(16, "bold"), text_color=T.TEXT).pack(side="left")

        self._proj_scroll = ctk.CTkScrollableFrame(
            frame, fg_color="transparent")
        self._proj_scroll.pack(fill="both", expand=True, padx=20, pady=(5, 20))
        return frame

    def load_archived_projects(self, keep_page=False):
        if getattr(self, "_proj_table", None) is None or not self._proj_table.winfo_exists():
            for w in self._proj_scroll.winfo_children():
                w.destroy()

            def when(r):
                if r.get("archived_at"):
                    return r["archived_at"].strftime("%Y-%m-%d %H:%M:%S")
                return r["end_date"].strftime("%Y-%m-%d") if r.get("end_date") else "—"
            self._proj_table = PagedTable(
                self._proj_scroll, [("Project ID", 1, 70), ("Project Name", 3, 200), ("Client/Dept", 2, 150), ("Status", 1, 100),
                                    ("End/Archived At", 2, 150), ("Action", 1, 100)],
                fetch=self._fetch_archived_projects,
                cells=lambda r: [str(r["project_id"]), r["name"], r.get("client") or "—", r["status"], when(r), ""],
                actions={5: {"text": "Restore", "command": lambda r: self.restore_project(r["project_id"])}},
                empty_text="No archived projects found. Archive a Completed or Cancelled project from Project Management.",
                font_size=12, cell_pady=12, uniform="proj_cols")
            self._proj_table.pack(fill="x", expand=True)
        self._proj_table.reload(self._proj_table.page if keep_page else 0)

    def _fetch_archived_projects(self, page, size):
        conn = get_connection()
        if not conn:
            raise ConnectionError("The database is not reachable.")
        try:
            cur = conn.cursor(dictionary=True)
            return fetch_page(cur, "SELECT project_id, name, client, status, end_date, archived_at",
                              "FROM projects WHERE archived_at IS NOT NULL", [],
                              "ORDER BY archived_at DESC, project_id DESC", page, size)
        finally:
            if conn.is_connected():
                conn.close()

    def restore_project(self, project_id):
        if not messagebox.askyesno("Confirm Restore", f"Restore Project ID: {project_id}? It returns to the status it had before it was archived."):
            return
        try:
            res = proj_svc.restore_project(self.user_info, project_id)     # back to the status it had before archiving
        except Exception as e:
            messagebox.showerror("Could not restore", friendly_message(e))
            return
        uid = self.user_info.get("user_id")
        if uid:
            log_action(uid, "Edited", "Maintenance", f"Restored Project '{res['name']}' (PID: {project_id}) to {res['status']}")
        C.notify(self, f"Project restored as {res['status']}.")
        self.load_archived_projects(keep_page=True)

    # ------------------------------------------
    # TAB 5: Backup & Restore
    # ------------------------------------------
    def render_backup_tab(self):
        frame = ctk.CTkFrame(
            self.tab_content, fg_color=T.SURFACE, corner_radius=10)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        # --- Header ---
        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(20, 5))
        ctk.CTkLabel(top, text="Database Backup & Restore",
                     font=T.font(16, "bold"), text_color=T.TEXT).pack(side="left")

        ctk.CTkLabel(frame,
                     text="Create verified backups of the entire champion_db database and restore from a "
                          "previous backup file (.sql). Always backup before making major system changes.",
                     font=T.font(12), text_color=T.TEXT_MUTED,
                     wraplength=800, justify="left").pack(anchor="w", padx=20, pady=(0, 12))

        # --- Actions row: Backup card + Restore card side by side ---
        actions_row = ctk.CTkFrame(frame, fg_color="transparent")
        actions_row.pack(fill="x", padx=20, pady=(0, 12))
        actions_row.grid_columnconfigure(0, weight=1)
        actions_row.grid_columnconfigure(1, weight=1)

        # -- Backup Card --
        backup_card = ctk.CTkFrame(actions_row, fg_color=T.SUCCESS_BG, corner_radius=10,
                                   border_width=1, border_color=T.GREEN_TINT)
        backup_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        ctk.CTkLabel(backup_card, text="💾  Create Backup",
                     font=T.font(14, "bold"), text_color=T.PRIMARY).pack(anchor="w", padx=15, pady=(14, 4))
        ctk.CTkLabel(backup_card,
                     text="Exports the full database schema and all data to a .sql file.\n"
                          "The backup is saved to a folder of your choice.",
                     font=T.font(12), text_color=T.TEXT,
                     wraplength=340, justify="left").pack(anchor="w", padx=15, pady=(0, 8))

        dest_row = ctk.CTkFrame(backup_card, fg_color="transparent")
        dest_row.pack(fill="x", padx=15, pady=(0, 8))
        ctk.CTkLabel(dest_row, text="Save to:", font=T.font(12, "bold"),
                     text_color=T.TEXT).pack(side="left", padx=(0, 8))
        self._backup_dest_var = ctk.StringVar(
            value="(click Browse to choose folder)")
        dest_entry = C.field(dest_row, textvariable=self._backup_dest_var,
                                  state="readonly", 
                                  width=180)
        dest_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        C.button(dest_row, compact=True, kind="primary", text="Browse", width=70, 
                      
                      
                      command=self._browse_backup_dest).pack(side="right")

        fname_row = ctk.CTkFrame(backup_card, fg_color="transparent")
        fname_row.pack(fill="x", padx=15, pady=(0, 4))
        ctk.CTkLabel(fname_row, text="File name (optional):", font=T.font(12, "bold"),
                     text_color=T.TEXT).pack(side="left", padx=(0, 6))
        self._backup_fname_entry = C.field(fname_row,
                                                placeholder_text="e.g., before_payroll_update  (no spaces/.sql needed)")
        self._backup_fname_entry.pack(side="left", fill="x", expand=True)

        note_row = ctk.CTkFrame(backup_card, fg_color="transparent")
        note_row.pack(fill="x", padx=15, pady=(0, 4))
        ctk.CTkLabel(note_row, text="Note (optional):", font=T.font(12, "bold"),
                     text_color=T.TEXT).pack(side="left", padx=(0, 6))
        self._backup_note_entry = C.field(note_row,
                                               placeholder_text="e.g., Before major update")
        self._backup_note_entry.pack(side="left", fill="x", expand=True)

        self._backup_btn = C.button(backup_card, kind="primary", text="⬇  Run Backup Now",
                                         
                                         
                                         command=self._run_backup)
        self._backup_btn.pack(fill="x", padx=15, pady=(8, 14))

        # -- Restore Card --
        restore_card = ctk.CTkFrame(actions_row, fg_color=T.WARNING_BG, corner_radius=10,
                                    border_width=1, border_color=T.WARNING_BORDER)
        restore_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        ctk.CTkLabel(restore_card, text="⬆  Restore from Backup",
                     font=T.font(14, "bold"), text_color=T.WARNING_TEXT).pack(anchor="w", padx=15, pady=(14, 4))
        ctk.CTkLabel(restore_card,
                     text="Restores the database from a selected .sql backup file.\n"
                          "⚠ WARNING: This will OVERWRITE all current data.",
                     font=T.font(12), text_color=T.TEXT,
                     wraplength=340, justify="left").pack(anchor="w", padx=15, pady=(0, 8))

        src_row = ctk.CTkFrame(restore_card, fg_color="transparent")
        src_row.pack(fill="x", padx=15, pady=(0, 8))
        ctk.CTkLabel(src_row, text="File:", font=T.font(12, "bold"),
                     text_color=T.TEXT).pack(side="left", padx=(0, 8))
        self._restore_src_var = ctk.StringVar(value="(no file selected)")
        src_entry = C.field(src_row, textvariable=self._restore_src_var,
                                 state="readonly", 
                                 width=180)
        src_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(src_row, text="Browse", width=70, height=28,
                      fg_color=T.WARNING_TEXT, hover_color=T.WARNING_TEXT,
                      font=T.font(12, "bold"),
                      command=self._browse_restore_file).pack(side="right")

        ctk.CTkLabel(restore_card,
                     text="Make sure you have a fresh backup before proceeding.",
                     font=T.font(12), text_color=T.TEXT_MUTED,
                     wraplength=340, justify="left").pack(anchor="w", padx=15, pady=(0, 4))

        restore_note_row = ctk.CTkFrame(restore_card, fg_color="transparent")
        restore_note_row.pack(fill="x", padx=15, pady=(0, 4))
        ctk.CTkLabel(restore_note_row, text="Note (optional):", font=T.font(12, "bold"),
                     text_color=T.TEXT).pack(side="left", padx=(0, 6))
        self._restore_note_entry = C.field(restore_note_row,
                                                placeholder_text="e.g., Rolling back after failed update")
        self._restore_note_entry.pack(side="left", fill="x", expand=True)

        self._restore_btn = ctk.CTkButton(restore_card, text="⬆  Restore Database",
                                          fg_color=T.WARNING_TEXT, hover_color=T.WARNING_TEXT,
                                          font=T.font(12, "bold"),
                                          command=self._run_restore)
        self._restore_btn.pack(fill="x", padx=15, pady=(8, 14))

        # --- Status bar ---
        self._backup_status_lbl = ctk.CTkLabel(frame, text="",
                                               font=T.font(12, "bold"),
                                               text_color=T.PRIMARY)
        self._backup_status_lbl.pack(anchor="w", padx=20, pady=(0, 6))

        # --- Backup History Table ---
        hist_hdr = ctk.CTkFrame(frame, fg_color="transparent")
        hist_hdr.pack(fill="x", padx=20, pady=(4, 0))
        ctk.CTkLabel(hist_hdr, text="Backup History",
                     font=T.font(14, "bold"), text_color=T.TEXT).pack(side="left")
        C.button(hist_hdr, compact=True, kind="secondary", text="↻ Refresh", width=80, 
                      
                      
                      command=self.load_backup_history).pack(side="right")

        self._backup_hist_scroll = ctk.CTkScrollableFrame(
            frame, fg_color="transparent")
        self._backup_hist_scroll.pack(
            fill="both", expand=True, padx=20, pady=(4, 20))

        return frame

    # ---- Backup helpers ----

    def _browse_backup_dest(self):
        folder = filedialog.askdirectory(title="Select Backup Destination Folder",
                                         parent=self.winfo_toplevel())
        if folder:
            self._backup_dest_var.set(folder)

    def _browse_restore_file(self):
        filepath = filedialog.askopenfilename(
            title="Select Backup File to Restore",
            filetypes=[("SQL Backup Files", "*.sql"), ("All Files", "*.*")],
            parent=self.winfo_toplevel()
        )
        if filepath:
            self._restore_src_var.set(filepath)

    def _run_backup(self):
        dest_folder = self._backup_dest_var.get().strip()
        if not dest_folder or dest_folder == "(click Browse to choose folder)":
            messagebox.showerror("No Destination", "Please choose a folder to save the backup.", parent=self.winfo_toplevel())
            return
        # Tk values are read HERE, on the main thread; the worker thread never touches a widget.
        note = self._backup_note_entry.get().strip()
        custom_fname = self._backup_fname_entry.get().strip()
        self._backup_btn.configure(state="disabled", text="⏳ Backing up...")
        self._backup_status_lbl.configure(text="⟳ Running backup, please wait...", text_color=T.WARNING_TEXT)

        def _do_backup():
            try:
                out = backup_service.create_backup(self.user_info, dest_folder, custom_fname, note)
            except Exception as e:
                msg = friendly_message(e)
                self._after_safe(lambda: self._on_backup_done(False, None, None, msg))
                return
            self._after_safe(lambda: self._on_backup_done(True, out["path"], out["size"]))

        threading.Thread(target=_do_backup, daemon=True).start()

    def _after_safe(self, fn):
        """Hand a result from a worker thread to the Tk thread (dropped if this screen was closed meanwhile)."""
        self.post_ui(fn)

    def _on_backup_done(self, success, filepath, size_str, error_msg=None):
        self._backup_btn.configure(state="normal", text="⬇  Run Backup Now")
        if success:
            self._backup_status_lbl.configure(
                text=f"✓ Backup complete! Saved: {os.path.basename(filepath)}  ({size_str})",
                text_color=T.PRIMARY
            )
            messagebox.showinfo(
                "Backup Successful",
                f"Database backup completed successfully.\n\n"
                f"File: {os.path.basename(filepath)}\n"
                f"Size: {size_str}\n"
                f"Location: {os.path.dirname(filepath)}",
                parent=self.winfo_toplevel()
            )
            self._backup_note_entry.delete(0, "end")
            self._backup_fname_entry.delete(0, "end")
            self.load_backup_history()
        else:
            self._backup_status_lbl.configure(
                text=f"✗ Backup failed. See error details.",
                text_color=T.DANGER_TEXT
            )
            messagebox.showerror(
                "Backup Failed",
                f"The backup could not be completed.\n\nDetails:\n{error_msg}",
                parent=self.winfo_toplevel()
            )

    def _run_restore(self):
        src_file = self._restore_src_var.get().strip()
        if not src_file or src_file == "(no file selected)":
            messagebox.showerror("No File Selected", "Please select a .sql backup file to restore from.", parent=self.winfo_toplevel())
            return
        if not os.path.isfile(src_file):
            messagebox.showerror("File Not Found", "The selected backup file no longer exists.", parent=self.winfo_toplevel())
            return
        confirmed = messagebox.askyesno(
            "⚠ Confirm Restore",
            f"This will REPLACE all current data with the contents of:\n\n{os.path.basename(src_file)}\n\n"
            "Before anything is changed, the system saves an automatic safety backup of the current data.\n\n"
            "IMPORTANT: every other computer using the system must log out first, otherwise their work may be lost or "
            "may fail during the restore.\n\nProceed?",
            parent=self.winfo_toplevel())
        if not confirmed:
            return
        restore_note = self._restore_note_entry.get().strip()          # read on the main thread
        self._restore_btn.configure(state="disabled", text="⏳ Restoring...")
        self._backup_status_lbl.configure(text="⟳ Checking the file, saving a safety backup, then restoring...", text_color=T.WARNING_TEXT)

        def _do_restore():
            try:
                res = backup_service.restore_backup(self.user_info, src_file, restore_note)
            except Exception as e:
                msg = friendly_message(e)
                self._after_safe(lambda: self._on_restore_done(False, msg))
                return
            self._after_safe(lambda: self._on_restore_done(True, None, res.get("safety_backup")))

        threading.Thread(target=_do_restore, daemon=True).start()

    def _on_restore_done(self, success, error_msg=None, safety=None):
        self._restore_btn.configure(state="normal", text="⬆  Restore Database")
        if success:
            self._backup_status_lbl.configure(
                text="✓ Restore complete! Database has been overwritten from the backup file.",
                text_color=T.PRIMARY
            )
            messagebox.showinfo(
                "Restore Successful",
                "The database has been restored from the backup file.\n\n"
                + (f"A safety copy of the data from just before the restore is here:\n{safety}\n\n" if safety else "")
                + "Please restart the application so every screen shows the restored data.",
                parent=self.winfo_toplevel()
            )
            self._restore_src_var.set("(no file selected)")
            self._restore_note_entry.delete(0, "end")
            self.load_backup_history()
        else:
            self._backup_status_lbl.configure(
                text="✗ Restore failed. See error details.",
                text_color=T.DANGER_TEXT
            )
            messagebox.showerror(
                "Restore Failed",
                f"The restore could not be completed.\n\nDetails:\n{error_msg}",
                parent=self.winfo_toplevel()
            )

    def load_backup_history(self):
        if not hasattr(self, "_backup_hist_scroll"):
            return
        if getattr(self, "_backup_table", None) is None or not self._backup_table.winfo_exists():
            for w in self._backup_hist_scroll.winfo_children():
                w.destroy()

            def fetch(page, size):
                rows, total = backup_service.history_page(self.user_info, size, page * size)
                return rows, PageInfo(page, size, total)

            def fetch_clamped(page, size):                 # the service returns the total; clamp here if the list shrank
                rows, info = fetch(page, size)
                if not rows and info.total and page:
                    last = clamp_page(page, size, info.total)
                    rows, info = fetch(last, size)
                return rows, info

            def when(r):
                d = r["created_at"]
                return d.strftime("%b %d, %Y %I:%M %p") if hasattr(d, "strftime") else (str(d) if d else "—")
            self._backup_table = PagedTable(
                self._backup_hist_scroll, [("Type", 1, 80), ("Filename", 4, 200), ("File Size", 1, 80), ("Checksum (SHA-256)", 2, 140),
                                           ("Note", 3, 160), ("Created By", 2, 120), ("Date & Time", 3, 160), ("Status", 1, 80)],
                fetch=fetch_clamped,
                cells=lambda r: [r["type"], r["filename"], r["file_size"], (r["sha256"] or "—")[:12] + ("…" if r["sha256"] else ""),
                                 r["note"], r["created_by"], when(r), r["status"]],
                row_bg=lambda r, i: T.SUCCESS_BG if r["status"] == "Success" else T.DANGER_BG,
                cell_style=lambda r, c, v: ((T.PRIMARY if r["type"] == "Backup" else T.WARNING_TEXT), True) if c == 0 else
                                           (((T.PRIMARY if r["status"] == "Success" else T.DANGER), True) if c == 7 else (T.TEXT, False)),
                empty_text="No backup records found. Create your first backup above.", font_size=12, cell_pady=10, uniform="bk_cols")
            self._backup_table.pack(fill="x", expand=True)
        self._backup_table.reload(0)
