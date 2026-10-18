import customtkinter as ctk
from tkinter import messagebox
from database import get_connection, log_action
from datetime import datetime
from services.errors import friendly_message
from services.paging import fetch_page
from services.validators import like_pattern
from views.paged_table import PagedTable



def _status_style(status_col, tag_col):
    """Cell colours shared by the transaction tables: Active in red, Retrieved in green, an untagged tool in red."""
    def style(row, col, val):
        if col == status_col:
            return ("#D8000C" if val == "Active" else "#2ECC71"), True
        if col == tag_col and val == "Unassigned":
            return "#D8000C", True
        return "#1A1A1A", False
    return style


def _with_quantity(rows):
    """[QUANTITIES] A consumable issued as 2.5 kg is ONE record: show 'Grease x2.5' so the amount is visible (equipment, quantity 1, is unchanged)."""
    from services.validators import fmt_qty
    for r in rows:
        q = r.get("quantity")
        if q is not None and q != 1:
            r["tool_name"] = f"{r['tool_name']} x{fmt_qty(q)}"
    return rows


class TrackingView(ctk.CTkFrame):
    def __init__(self, parent, user_info=None):
        super().__init__(parent, fg_color="transparent")

        self.user_info = user_info or {}
        self.is_admin = self.user_info.get("role", "Staff") == "Admin"

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)

        if self.is_admin:
            self.build_admin_view()
        else:
            self.build_staff_view()

        uid = self.user_info.get("user_id")
        if uid:
            log_action(uid, "Viewed", "Tracking & Accountability",
                       "Opened Tracking module")

    # ==========================================
    # MODAL FIX (Deployment Details)
    # ==========================================
    def view_deployment_details(self, row):
        modal = ctk.CTkToplevel(self)
        trans_id = row.get("transaction_id", "N/A")
        modal.title(f"Deployment History - Receipt #{trans_id}")

        modal.minsize(500, 500)
        modal.attributes("-topmost", True)
        modal.grab_set()
        
        modal.update_idletasks()
        x = (modal.winfo_screenwidth() // 2) - (500 // 2)
        y = (modal.winfo_screenheight() // 2) - (600 // 2)
        modal.geometry(f"500x600+{x}+{y}")

        bottom_frame = ctk.CTkFrame(modal, fg_color="transparent")
        bottom_frame.pack(fill="x", side="bottom", padx=20, pady=20)

        scroll_container = ctk.CTkScrollableFrame(
            modal, fg_color="transparent")
        scroll_container.pack(fill="both", expand=True, padx=20, pady=(20, 0))

        ctk.CTkLabel(scroll_container, text="Champion Fine Tooling", font=(
            "Inter", 20, "bold"), text_color="#1E4528").pack(pady=(0, 2))
        ctk.CTkLabel(scroll_container, text="Official Issuance Receipt", font=(
            "Inter", 14), text_color="gray").pack(pady=(0, 20))

        issued_to = row.get("full_name", self.user_info.get("username", "N/A"))
        trans_type = row.get("type", "Issuance")

        details = (
            f"Transaction ID: {trans_id}\n"
            f"Type: {trans_type}\n"
            f"Date Out: {row.get('borrow_date', 'N/A')}\n"
            f"Date In: {row.get('return_date', 'N/A')}\n"
            f"Issued To: {issued_to}\n"
        )
        ctk.CTkLabel(scroll_container, text=details, justify="left",
                     font=("Inter", 13)).pack(anchor="w", pady=(0, 20))

        ctk.CTkLabel(scroll_container, text="Items Deployed:", font=(
            "Inter", 13, "bold")).pack(anchor="w", pady=(0, 5))

        tool_name = row.get("tool_name", "N/A")
        tag_id = row.get("tag_id", "N/A")
        status = row.get("status", "N/A")
        ctk.CTkLabel(scroll_container, text=f"• {tool_name} (Tag: {tag_id}) - {status}", font=(
            "Inter", 12)).pack(anchor="w", padx=10, pady=2)

    def build_admin_view(self):
        top_bar = ctk.CTkFrame(self, fg_color="transparent")
        top_bar.grid(row=0, column=0, sticky="ew", padx=20, pady=(10, 15))

        ctk.CTkLabel(top_bar, text="Tracking & Accountability", font=(
            "Inter", 16, "bold"), text_color="#1E4528").pack(side="left")

        tabs = ["📋 Issuance & Retrieval Logs", "🔎 Audit Records", "⚙️ Activity Log"]
        self.tab_var = ctk.StringVar(value=tabs[0])

        self.seg_btn = ctk.CTkSegmentedButton(
            top_bar, values=tabs, variable=self.tab_var, command=self.switch_tab,
            fg_color="#F0F0F0", selected_color="#1E4528", selected_hover_color="#14301C"
        )
        self.seg_btn.pack(side="right")

        self.tab_content = ctk.CTkFrame(self, fg_color="transparent")
        self.tab_content.grid(
            row=1, column=0, sticky="nsew", padx=10, pady=(0, 20))
        self.tab_content.grid_columnconfigure(0, weight=1)
        self.tab_content.grid_rowconfigure(0, weight=1)

        self.cached_tabs = {}
        self.switch_tab(tabs[0])

    def switch_tab(self, selected_tab):
        if hasattr(self, "current_tab") and self.current_tab:
            self.current_tab.grid_remove()

        if selected_tab not in self.cached_tabs:
            if "Issuance" in selected_tab:
                self.cached_tabs[selected_tab] = self.render_logs_tab()
            elif "Audit" in selected_tab:
                self.cached_tabs[selected_tab] = self.render_audit_tab()
            elif "Activity" in selected_tab:
                self.cached_tabs[selected_tab] = self.render_activity_tab()

        self.current_tab = self.cached_tabs[selected_tab]
        self.current_tab.grid(row=0, column=0, sticky="nsew")

        if "Issuance" in selected_tab:
            self.load_logs()
            self.log_search.focus_set()
        elif "Audit" in selected_tab:
            self.load_audit()
            self.audit_search.focus_set()
        elif "Activity" in selected_tab:
            self.load_activity()
            self.act_search.focus_set()

    # ------------------------------------------
    # TAB 1: Borrow/Return Logs
    # ------------------------------------------
    def render_logs_tab(self):
        frame = ctk.CTkFrame(
            self.tab_content, fg_color="white", corner_radius=10)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(20, 5))
        ctk.CTkLabel(top, text="Issuance & Retrieval Logs",
                     font=("Inter", 16, "bold"), text_color="#1A1A1A").pack(side="left")

        self.log_search_var = ctk.StringVar()
        self.log_search = ctk.CTkEntry(
            top, placeholder_text="Search employee or tool...", width=220, textvariable=self.log_search_var)
        self.log_search.pack(side="right", padx=(5, 0))

        self._log_timer = None
        def on_log_search(*args):
            if self._log_timer:
                self.after_cancel(self._log_timer)
            self._log_timer = self.after(300, self.load_logs)
        self.log_search_var.trace_add("write", on_log_search)

        ctk.CTkLabel(frame, text="An endless, chronological history book. Records exactly what happened and when (e.g., 'John took a hammer on Tuesday').",
                     font=("Inter", 11, "italic"), text_color="gray").pack(anchor="w", padx=20, pady=(0, 8))

        self._log_scroll = ctk.CTkScrollableFrame(
            frame, fg_color="transparent")
        self._log_scroll.pack(fill="both", expand=True, padx=20, pady=(5, 20))
        return frame

    def _format_tx_dates(self, rows):
        """Receipt / table text for the two dates (done in the worker thread, so the Tk thread only copies strings)."""
        for r in rows:
            for key in ("borrow_date", "return_date"):
                if hasattr(r[key], 'strftime'):
                    r[key] = r[key].strftime('%b %d, %Y %I:%M %p')
                elif not r[key]:
                    r[key] = "—"
        return rows

    LOG_COLUMNS = [("TRN", 1, 50), ("Type", 1, 70), ("Tool Name", 3, 160), ("Tag ID", 2, 100), ("Assignee", 2, 120),
                   ("Date Issued", 3, 150), ("Date Retrieved", 3, 150), ("Status", 1, 80)]

    def load_logs(self):
        self._log_query = self.log_search.get().strip() if hasattr(self, "log_search") else ""     # read on the main thread
        if getattr(self, "_log_table", None) is None or not self._log_table.winfo_exists():
            for w in self._log_scroll.winfo_children():
                w.destroy()
            self._log_table = PagedTable(
                self._log_scroll, self.LOG_COLUMNS, fetch=self._fetch_logs_page,
                cells=lambda r: [str(r["transaction_id"]), r["type"], r["tool_name"], r["tag_id"], r["full_name"], r["borrow_date"], r["return_date"], r["status"]],
                cell_style=_status_style(7, 3), on_row_click=self.view_deployment_details, empty_text="No transaction records found.",
                font_size=11, cell_pady=12, uniform="log_cols")
            self._log_table.pack(fill="x", expand=True)
        self._log_table.reload(0)

    def _fetch_logs_page(self, page, size):
        q = self._log_query
        where, params = "WHERE 1=1", []
        if q:
            where += " AND (u.full_name LIKE %s OR t.name LIKE %s OR t.tag_id LIKE %s)"
            params = [like_pattern(q)] * 3
        conn = get_connection()
        if not conn:
            raise ConnectionError("The database is not reachable.")
        try:
            cur = conn.cursor(dictionary=True)
            rows, info = fetch_page(
                cur, """SELECT tr.transaction_id, tr.quantity, tr.type, t.name as tool_name, IFNULL(t.tag_id,'Unassigned') as tag_id,
                               u.full_name, tr.borrow_date, tr.return_date, tr.status""",
                f"FROM transaction tr JOIN tool t ON tr.tool_id = t.tool_id JOIN user u ON tr.user_id = u.user_id {where}", params,
                "ORDER BY tr.borrow_date DESC, tr.transaction_id DESC", page, size)
            return self._format_tx_dates(_with_quantity(rows)), info
        finally:
            if conn.is_connected():
                conn.close()

    # ------------------------------------------
    # TAB 2: Audit Records
    # ------------------------------------------
    def render_audit_tab(self):
        frame = ctk.CTkFrame(
            self.tab_content, fg_color="white", corner_radius=10)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(20, 5))
        ctk.CTkLabel(top, text="Audit Trail — Issuance & Retrieval Records",
                     font=("Inter", 16, "bold"), text_color="#1A1A1A").pack(side="left")

        ctk.CTkLabel(frame, text="Investigating Missing Items: An active math equation. Cross-references Total Inventory vs. Available Stock vs. Active Transactions to flag discrepancies.",
                     font=("Inter", 11, "italic"), text_color="gray").pack(anchor="w", padx=20, pady=(0, 8))

        filter_row = ctk.CTkFrame(frame, fg_color="transparent")
        filter_row.pack(fill="x", padx=20, pady=(0, 8))

        ctk.CTkLabel(filter_row, text="Filter by Status:",
                     font=("Inter", 12), text_color="gray").pack(side="left")
        self.audit_filter = ctk.CTkOptionMenu(
            filter_row, values=["All", "Active", "Retrieved"],
            width=120, fg_color="#F9FAFB", text_color="black", command=lambda e: self.load_audit()
        )
        self.audit_filter.pack(side="left", padx=8)

        self.audit_search_var = ctk.StringVar()
        self.audit_search = ctk.CTkEntry(
            filter_row, placeholder_text="Search name / tool...", width=200, textvariable=self.audit_search_var)
        self.audit_search.pack(side="left", padx=(0, 5))

        self._audit_timer = None
        def on_audit_search(*args):
            if self._audit_timer:
                self.after_cancel(self._audit_timer)
            self._audit_timer = self.after(300, self.load_audit)
        self.audit_search_var.trace_add("write", on_audit_search)

        self.audit_summary = ctk.CTkLabel(frame, text="", font=("Inter", 11, "bold"),
                                          text_color="#1E4528")
        self.audit_summary.pack(anchor="w", padx=20, pady=(0, 5))

        self._audit_scroll = ctk.CTkScrollableFrame(
            frame, fg_color="transparent")
        self._audit_scroll.pack(
            fill="both", expand=True, padx=20, pady=(5, 20))
        return frame

    AUDIT_COLUMNS = [("TRN", 1, 50), ("Assignee", 2, 120), ("Tool", 3, 150), ("Tag ID", 2, 100), ("Date Issued", 3, 150), ("Date Retrieved", 3, 150),
                     ("Cond@Issuance", 2, 90), ("Cond@Retrieval", 2, 90), ("Status", 1, 80)]

    def load_audit(self):
        self._audit_status = self.audit_filter.get() if hasattr(self, "audit_filter") else "All"      # read on the main thread
        self._audit_query = self.audit_search.get().strip() if hasattr(self, "audit_search") else ""
        if getattr(self, "_audit_table", None) is None or not self._audit_table.winfo_exists():
            for w in self._audit_scroll.winfo_children():
                w.destroy()
            self._audit_table = PagedTable(
                self._audit_scroll, self.AUDIT_COLUMNS, fetch=self._fetch_audit_page,
                cells=lambda r: [str(r["transaction_id"]), r["full_name"], r["tool_name"], r["tag_id"], r["borrow_date"], r["return_date"],
                                 r["cond_borrow"], r["cond_return"], r["status"]],
                row_bg=lambda r, i: "#FFF8F0" if r["status"] == "Active" else ("#F9FAFB" if i % 2 == 0 else "white"),
                cell_style=_status_style(8, 3), on_loaded=self._audit_loaded, empty_text="No records match the audit criteria.",
                font_size=11, cell_pady=12, uniform="audit_cols")
            self._audit_table.pack(fill="x", expand=True)
        self._audit_table.reload(0)

    def _fetch_audit_page(self, page, size):
        where, params = "WHERE 1=1", []
        if self._audit_status != "All":
            where += " AND tr.status = %s"
            params.append("Returned" if self._audit_status == "Retrieved" else self._audit_status)
        if self._audit_query:
            where += " AND (u.full_name LIKE %s OR t.name LIKE %s)"
            params += [like_pattern(self._audit_query)] * 2
        frm = f"FROM transaction tr JOIN tool t ON tr.tool_id = t.tool_id JOIN user u ON tr.user_id = u.user_id {where}"
        conn = get_connection()
        if not conn:
            raise ConnectionError("The database is not reachable.")
        try:
            cur = conn.cursor(dictionary=True)
            rows, info = fetch_page(
                cur, """SELECT tr.transaction_id, tr.quantity, u.full_name, t.name as tool_name, IFNULL(t.tag_id,'Unassigned') as tag_id,
                               tr.borrow_date, tr.return_date, IFNULL(tr.condition_at_borrow,'N/A') as cond_borrow,
                               IFNULL(tr.condition_at_return,'N/A') as cond_return, tr.status""",
                frm, params, "ORDER BY tr.borrow_date DESC, tr.transaction_id DESC", page, size)
            cur.execute(f"SELECT SUM(tr.status = 'Active') AS active, SUM(tr.status = 'Returned') AS returned {frm}", tuple(params))
            c = cur.fetchone() or {}
            self._audit_counts = (info.total, int(c.get("active") or 0), int(c.get("returned") or 0))     # whole result set, not just this page
            return self._format_tx_dates(_with_quantity(rows)), info
        finally:
            if conn.is_connected():
                conn.close()

    def _audit_loaded(self, rows, info):
        total, active, returned = getattr(self, "_audit_counts", (info.total, 0, 0))
        if hasattr(self, "audit_summary") and self.audit_summary.winfo_exists():
            self.audit_summary.configure(text=f"  Total: {total}   |   Active: {active}   |   Retrieved: {returned}")

    # ------------------------------------------
    # TAB 3: Activity Log
    # ------------------------------------------
    def render_activity_tab(self):
        frame = ctk.CTkFrame(
            self.tab_content, fg_color="white", corner_radius=10)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(20, 5))
        ctk.CTkLabel(top, text="Full System Activity Log",
                     font=("Inter", 16, "bold"), text_color="#1A1A1A").pack(side="left")

        ctk.CTkLabel(frame,
                     text="Records every login, logout, module visit, edit, search, and transaction. "
                          "Auto-pruned to the latest 10,000 entries to protect the database.",
                     font=("Inter", 11), text_color="gray",
                     wraplength=900, justify="left").pack(anchor="w", padx=20, pady=(0, 8))

        filter_row = ctk.CTkFrame(frame, fg_color="transparent")
        filter_row.pack(fill="x", padx=20, pady=(0, 8))

        ctk.CTkLabel(filter_row, text="Module:", font=(
            "Inter", 12), text_color="gray").pack(side="left")
        self.act_module_filter = ctk.CTkOptionMenu(
            filter_row,
            values=["All", "Authentication", "Dashboard", "Inventory", "Projects",
                    "Tagging", "Issuance & Retrieval", "Tracking & Accountability",
                    "Reports", "Maintenance", "Role Management", "Profile"],
            width=180, fg_color="#F9FAFB", text_color="black"
        )
        self.act_module_filter.pack(side="left", padx=8)
        self.act_module_filter.configure(command=lambda e: self.do_act_search())

        self.act_search_var = ctk.StringVar()
        self.act_search = ctk.CTkEntry(
            filter_row, placeholder_text="Search user or details...", width=200, textvariable=self.act_search_var)
        self.act_search.pack(side="left", padx=(0, 5))

        self._act_timer = None
        def on_act_search(*args):
            if self._act_timer:
                self.after_cancel(self._act_timer)
            self._act_timer = self.after(300, self.do_act_search)
        self.act_search_var.trace_add("write", on_act_search)

        self.act_summary = ctk.CTkLabel(frame, text="", font=(
            "Inter", 11, "bold"), text_color="#1E4528")
        self.act_summary.pack(anchor="w", padx=20, pady=(0, 5))

        self._act_scroll = ctk.CTkScrollableFrame(
            frame, fg_color="transparent")
        self._act_scroll.pack(fill="both", expand=True, padx=20, pady=(5, 5))
        
        return frame

    ACT_COLORS = {"Login": "#2ECC71", "Logout": "#E74C3C", "Added": "#3498DB", "Edited": "#F39C12", "Archived": "#95A5A6", "Searched": "#9B59B6",
                  "Viewed": "#1A1A1A", "Issued": "#27AE60", "Retrieved": "#16A085", "Submitted": "#2980B9", "Approved": "#27AE60",
                  "Flagged": "#D8000C", "Resolved": "#2ECC71"}

    def do_act_search(self):
        self.load_activity()

    def load_activity(self):
        self._act_module = self.act_module_filter.get() if hasattr(self, "act_module_filter") else "All"      # read on the main thread
        self._act_query = self.act_search.get().strip() if hasattr(self, "act_search") else ""
        if getattr(self, "_act_table", None) is None or not self._act_table.winfo_exists():
            for w in self._act_scroll.winfo_children():
                w.destroy()
            self._act_table = PagedTable(
                self._act_scroll, [("Log ID", 1, 60), ("Timestamp", 3, 150), ("Employee", 3, 150), ("Action Type", 2, 100), ("Module", 2, 120),
                                   ("Details", 5, 250)],
                fetch=self._fetch_activity_page,
                cells=lambda r: [str(r["log_id"]), r["ts"], r["employee"], r["action_type"], r["module"], r["details"]],
                cell_style=lambda r, c, v: (self.ACT_COLORS.get(v, "#555555"), True) if c == 3 else ("#1A1A1A", False),
                on_loaded=lambda rows, info: self.act_summary.configure(text=f"  {info.label()} entries") if self.act_summary.winfo_exists() else None,
                empty_text="No activity records found.", page_size=50, font_size=11, cell_pady=12, uniform="act_cols")
            self._act_table.pack(fill="x", expand=True)
        self._act_table.reload(0)

    def _fetch_activity_page(self, page, size):
        where, params = "WHERE 1=1", []
        if self._act_module != "All":
            where += " AND sl.module = %s"
            params.append(self._act_module)
        if self._act_query:
            where += " AND (u.full_name LIKE %s OR sl.details LIKE %s OR sl.action_type LIKE %s)"
            params += [like_pattern(self._act_query)] * 3
        conn = get_connection()
        if not conn:
            raise ConnectionError("The database is not reachable.")
        try:
            cur = conn.cursor(dictionary=True)
            rows, info = fetch_page(
                cur, """SELECT sl.log_id, sl.timestamp as ts, IFNULL(u.full_name, CONCAT('UID:', sl.user_id)) as employee,
                               sl.action_type, sl.module, IFNULL(sl.details,'—') as details""",
                f"FROM system_logs sl LEFT JOIN user u ON sl.user_id = u.user_id {where}", params, "ORDER BY sl.log_id DESC", page, size)
        finally:
            if conn.is_connected():
                conn.close()
        for r in rows:
            if hasattr(r["ts"], 'strftime'):
                r["ts"] = r["ts"].strftime('%b %d, %Y %I:%M %p')
        return rows, info

    def build_staff_view(self):
        top_bar = ctk.CTkFrame(self, fg_color="transparent")
        top_bar.grid(row=0, column=0, sticky="ew", padx=20, pady=(10, 15))

        ctk.CTkLabel(top_bar, text="Tracking & Accountability", font=(
            "Inter", 16, "bold"), text_color="#1E4528").pack(side="left")

        tabs = ["👤 My History"]
        self.tab_var = ctk.StringVar(value=tabs[0])

        self.seg_btn = ctk.CTkSegmentedButton(
            top_bar, values=tabs, variable=self.tab_var,
            fg_color="#F0F0F0", selected_color="#1E4528", selected_hover_color="#14301C"
        )
        self.seg_btn.pack(side="right")

        self.tab_content = ctk.CTkFrame(self, fg_color="transparent")
        self.tab_content.grid(
            row=1, column=0, sticky="nsew", padx=10, pady=(0, 20))
        self.tab_content.grid_columnconfigure(0, weight=1)
        self.tab_content.grid_rowconfigure(0, weight=1)

        frame = ctk.CTkFrame(
            self.tab_content, fg_color="white", corner_radius=10)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(20, 10))
        ctk.CTkLabel(top, text="My Deployment History", font=(
            "Inter", 16, "bold"), text_color="#1A1A1A").pack(side="left")
        ctk.CTkLabel(frame, text="Click on any transaction record below to view its Deployment Receipt.", font=(
            "Inter", 11), text_color="gray").pack(anchor="w", padx=20, pady=(0, 10))

        scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=20, pady=(5, 20))

        user_id = self.user_info.get("user_id")
        if not user_id:
            emp_id = self.user_info.get("employee_id")
            if emp_id:
                conn2 = get_connection()
                if conn2:
                    try:
                        c2 = conn2.cursor(dictionary=True)
                        c2.execute("SELECT user_id FROM user WHERE employee_id = %s", (emp_id,))
                        row2 = c2.fetchone()
                        if row2:
                            user_id = row2["user_id"]
                    except Exception:
                        pass
                    finally:
                        if conn2.is_connected():
                            conn2.close()

        if not user_id:
            ctk.CTkLabel(scroll, text="Could not resolve user session. Please log out and log back in.", text_color="red").pack(pady=20)
            return

        def fetch(page, size):
            conn = get_connection()
            if not conn:
                raise ConnectionError("The database is not reachable.")
            try:
                cur = conn.cursor(dictionary=True)
                rows, info = fetch_page(
                    cur, """SELECT tr.transaction_id, tr.quantity, t.name as tool_name, IFNULL(t.tag_id,'Unassigned') as tag_id,
                                   tr.borrow_date, tr.return_date, IFNULL(tr.condition_at_return,'—') as cond_return, tr.status""",
                    "FROM transaction tr JOIN tool t ON tr.tool_id = t.tool_id WHERE tr.user_id = %s", [user_id],
                    "ORDER BY tr.borrow_date DESC, tr.transaction_id DESC", page, size)
                return self._format_tx_dates(_with_quantity(rows)), info
            finally:
                if conn.is_connected():
                    conn.close()

        self._my_table = PagedTable(
            scroll, [("TRN", 1, 50), ("Tool Name", 3, 160), ("Tag ID", 2, 100), ("Date Issued", 3, 150), ("Date Retrieved", 3, 150),
                     ("Cond@Retrieval", 2, 100), ("Status", 1, 80)],
            fetch=fetch,
            cells=lambda r: [str(r["transaction_id"]), r["tool_name"], r["tag_id"], r["borrow_date"], r["return_date"], r["cond_return"], r["status"]],
            cell_style=_status_style(6, 2), on_row_click=self.view_deployment_details, empty_text="You have no deployment history.",
            font_size=11, cell_pady=12, uniform="staff_cols")
        self._my_table.pack(fill="x", expand=True)
        self._my_table.reload(0)
