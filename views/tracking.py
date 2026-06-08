import customtkinter as ctk
from tkinter import messagebox
from database import get_connection, log_action
from datetime import datetime


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

        tabs = ["📋 Borrow/Return Logs", "🔎 Audit Records", "⚙️ Activity Log"]
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
            if "Borrow" in selected_tab:
                self.cached_tabs[selected_tab] = self.render_logs_tab()
            elif "Audit" in selected_tab:
                self.cached_tabs[selected_tab] = self.render_audit_tab()
            elif "Activity" in selected_tab:
                self.cached_tabs[selected_tab] = self.render_activity_tab()

        self.current_tab = self.cached_tabs[selected_tab]
        self.current_tab.grid(row=0, column=0, sticky="nsew")

        if "Borrow" in selected_tab:
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
        ctk.CTkLabel(top, text="Borrow / Return Transaction Logs",
                     font=("Inter", 16, "bold"), text_color="#1A1A1A").pack(side="left")

        self.log_search = ctk.CTkEntry(
            top, placeholder_text="Search employee or tool...", width=220)
        self.log_search.pack(side="right", padx=(5, 0))
        self.log_search.bind("<Return>", lambda e: self.load_logs())

        ctk.CTkButton(top, text="Search", width=70, fg_color="#1E4528",
                      hover_color="#14301C", font=("Inter", 11, "bold"),
                      command=self.load_logs).pack(side="right", padx=5)
        ctk.CTkButton(top, text="↻", width=40, fg_color="#E0E0E0",
                      text_color="black", hover_color="#CCCCCC",
                      command=lambda: [self.log_search.delete(0, "end"), self.load_logs()]).pack(side="right")

        ctk.CTkLabel(frame, text="An endless, chronological history book. Records exactly what happened and when (e.g., 'John took a hammer on Tuesday').",
                     font=("Inter", 11, "italic"), text_color="gray").pack(anchor="w", padx=20, pady=(0, 8))

        self._log_scroll = ctk.CTkScrollableFrame(
            frame, fg_color="transparent")
        self._log_scroll.pack(fill="both", expand=True, padx=20, pady=(5, 20))
        return frame

    def load_logs(self):
        for w in self._log_scroll.winfo_children():
            w.destroy()

        # Hard-Bounded Uniform Grid setup
        table_inner = ctk.CTkFrame(self._log_scroll, fg_color="transparent")
        table_inner.pack(fill="x", expand=True)

        headers = ["TRN", "Type", "Tool Name", "Tag ID", "Borrower", "Borrow Date", "Return Date", "Status"]
        weights = [1, 1, 3, 2, 2, 3, 3, 1]
        min_sizes = [50, 70, 160, 100, 120, 150, 150, 80]

        for col, (w, min_w) in enumerate(zip(weights, min_sizes)):
            table_inner.grid_columnconfigure(col, weight=w, minsize=min_w, uniform="log_cols")

        # Header Row
        for col, text in enumerate(headers):
            cell = ctk.CTkFrame(table_inner, fg_color="#1E4528", corner_radius=0)
            cell.grid(row=0, column=col, sticky="nsew", pady=(0, 2))
            lbl = ctk.CTkLabel(cell, text=text, font=("Inter", 11, "bold"), text_color="white", anchor="center")
            lbl.pack(fill="both", expand=True, padx=2, pady=10)

        q = self.log_search.get().strip() if hasattr(self, "log_search") else ""
        conn = get_connection()
        if not conn:
            return
        try:
            cursor = conn.cursor(dictionary=True)
            sql = """
                SELECT tr.transaction_id, tr.type, t.name as tool_name,
                       IFNULL(t.tag_id,'Unassigned') as tag_id,
                       u.full_name,
                       DATE_FORMAT(tr.borrow_date, '%b %d, %Y %I:%i %p') as borrow_date,
                       IF(tr.return_date IS NOT NULL,
                           DATE_FORMAT(tr.return_date, '%b %d, %Y %I:%i %p'), '—') as return_date,
                       tr.status
                FROM transaction tr
                JOIN tool t ON tr.tool_id = t.tool_id
                JOIN user u ON tr.user_id = u.user_id
            """
            params = []
            if q:
                sql += " WHERE u.full_name LIKE %s OR t.name LIKE %s OR t.tag_id LIKE %s"
                params = [f"%{q}%", f"%{q}%", f"%{q}%"]
            sql += " ORDER BY tr.borrow_date DESC LIMIT 200"
            cursor.execute(sql, params)
            rows = cursor.fetchall()

            if not rows:
                ctk.CTkLabel(table_inner, text="No transaction records found.",
                             text_color="gray").grid(row=1, column=0, columnspan=len(headers), pady=20)
                return

            for i, row in enumerate(rows):
                r_idx = i + 1
                bg = "#F9FAFB" if i % 2 == 0 else "white"

                vals = [
                    str(row["transaction_id"]), row["type"], row["tool_name"],
                    row["tag_id"], row["full_name"],
                    row["borrow_date"], row["return_date"], row["status"],
                ]
                
                for col, val in enumerate(vals):
                    cell = ctk.CTkFrame(table_inner, fg_color=bg, corner_radius=0, cursor="hand2")
                    cell.grid(row=r_idx, column=col, sticky="nsew")

                    txt_color = "#1A1A1A"
                    font_w = "normal"
                    if col == 7:
                        txt_color = "#D8000C" if val == "Active" else "#2ECC71"
                        font_w = "bold"
                    elif col == 3 and val == "Unassigned":
                        txt_color = "#D8000C"
                        font_w = "bold"

                    lbl = ctk.CTkLabel(cell, text=val, font=("Inter", 11, font_w), text_color=txt_color, justify="center", anchor="center", cursor="hand2")
                    
                    # High-performance static wrapping
                    lbl.configure(wraplength=min_sizes[col] - 10)

                    lbl.pack(fill="both", expand=True, padx=4, pady=12)

                    # Binds whole cell & text to open the modal
                    cell.bind("<Button-1>", lambda e, r=row: self.view_deployment_details(r))
                    lbl.bind("<Button-1>", lambda e, r=row: self.view_deployment_details(r))

        except Exception as e:
            ctk.CTkLabel(
                self._log_scroll, text=f"Error: {e}", text_color="red").pack(pady=10)
        finally:
            if conn.is_connected():
                cursor.close()
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
        ctk.CTkLabel(top, text="Audit Trail — Borrow & Return Records",
                     font=("Inter", 16, "bold"), text_color="#1A1A1A").pack(side="left")

        ctk.CTkLabel(frame, text="Investigating Missing Items: An active math equation. Cross-references Total Inventory vs. Available Stock vs. Active Transactions to flag discrepancies.",
                     font=("Inter", 11, "italic"), text_color="gray").pack(anchor="w", padx=20, pady=(0, 8))

        filter_row = ctk.CTkFrame(frame, fg_color="transparent")
        filter_row.pack(fill="x", padx=20, pady=(0, 8))

        ctk.CTkLabel(filter_row, text="Filter by Status:",
                     font=("Inter", 12), text_color="gray").pack(side="left")
        self.audit_filter = ctk.CTkOptionMenu(
            filter_row, values=["All", "Active", "Returned"],
            width=120, fg_color="#F9FAFB", text_color="black"
        )
        self.audit_filter.pack(side="left", padx=8)

        self.audit_search = ctk.CTkEntry(
            filter_row, placeholder_text="Search name / tool...", width=200)
        self.audit_search.pack(side="left", padx=(0, 5))
        self.audit_search.bind("<Return>", lambda e: self.load_audit())

        ctk.CTkButton(filter_row, text="Run Audit", width=80,
                      fg_color="#F1C40F", text_color="black", hover_color="#D4AC0D",
                      font=("Inter", 11, "bold"),
                      command=self.load_audit).pack(side="left", padx=5)
        ctk.CTkButton(filter_row, text="↻ Reset", width=70,
                      fg_color="#E0E0E0", text_color="black", hover_color="#CCCCCC",
                      command=lambda: [self.audit_search.delete(0, "end"),
                                       self.audit_filter.set("All"), self.load_audit()]).pack(side="left")

        self.audit_summary = ctk.CTkLabel(frame, text="", font=("Inter", 11, "bold"),
                                          text_color="#1E4528")
        self.audit_summary.pack(anchor="w", padx=20, pady=(0, 5))

        self._audit_scroll = ctk.CTkScrollableFrame(
            frame, fg_color="transparent")
        self._audit_scroll.pack(
            fill="both", expand=True, padx=20, pady=(5, 20))
        return frame

    def load_audit(self):
        for w in self._audit_scroll.winfo_children():
            w.destroy()

        table_inner = ctk.CTkFrame(self._audit_scroll, fg_color="transparent")
        table_inner.pack(fill="x", expand=True)

        headers = ["TRN", "Borrower", "Tool", "Tag ID", "Borrowed On", "Return Date", "Cond@Borrow", "Cond@Return", "Status"]
        weights = [1, 2, 3, 2, 3, 3, 2, 2, 1]
        min_sizes = [50, 120, 150, 100, 150, 150, 90, 90, 80]

        for col, (w, min_w) in enumerate(zip(weights, min_sizes)):
            table_inner.grid_columnconfigure(col, weight=w, minsize=min_w, uniform="audit_cols")

        # Header Row
        for col, text in enumerate(headers):
            cell = ctk.CTkFrame(table_inner, fg_color="#1E4528", corner_radius=0)
            cell.grid(row=0, column=col, sticky="nsew", pady=(0, 2))
            lbl = ctk.CTkLabel(cell, text=text, font=("Inter", 11, "bold"), text_color="white", anchor="center")
            lbl.pack(fill="both", expand=True, padx=2, pady=10)

        status_filter = self.audit_filter.get() if hasattr(
            self, "audit_filter") else "All"
        q = self.audit_search.get().strip() if hasattr(self, "audit_search") else ""

        conn = get_connection()
        if not conn:
            return
        try:
            cursor = conn.cursor(dictionary=True)
            sql = """
                SELECT tr.transaction_id, u.full_name, t.name as tool_name,
                       IFNULL(t.tag_id,'Unassigned') as tag_id,
                       DATE_FORMAT(tr.borrow_date, '%b %d, %Y %I:%i %p') as borrow_date,
                       IF(tr.return_date IS NOT NULL,
                           DATE_FORMAT(tr.return_date, '%b %d, %Y %I:%i %p'), '—') as return_date,
                       IFNULL(tr.condition_at_borrow,'N/A') as cond_borrow,
                       IFNULL(tr.condition_at_return,'N/A')  as cond_return,
                       tr.status
                FROM transaction tr
                JOIN tool t ON tr.tool_id = t.tool_id
                JOIN user u ON tr.user_id = u.user_id
                WHERE 1=1
            """
            params = []
            if status_filter != "All":
                sql += " AND tr.status = %s"
                params.append(status_filter)
            if q:
                sql += " AND (u.full_name LIKE %s OR t.name LIKE %s)"
                params += [f"%{q}%", f"%{q}%"]
            sql += " ORDER BY tr.borrow_date DESC"
            cursor.execute(sql, params)
            rows = cursor.fetchall()

            total = len(rows)
            active = sum(1 for r in rows if r["status"] == "Active")
            returned = sum(1 for r in rows if r["status"] == "Returned")
            self.audit_summary.configure(
                text=f"  Total: {total}   |   Active: {active}   |   Returned: {returned}"
            )

            if not rows:
                ctk.CTkLabel(
                    table_inner, text="No records match the audit criteria.", text_color="gray").grid(row=1, column=0, columnspan=len(headers), pady=20)
                return

            for i, row in enumerate(rows):
                r_idx = i + 1
                bg = "#FFF8F0" if row["status"] == "Active" else ("#F9FAFB" if i % 2 == 0 else "white")
                
                vals = [
                    str(row["transaction_id"]), row["full_name"], row["tool_name"],
                    row["tag_id"], row["borrow_date"], row["return_date"],
                    row["cond_borrow"], row["cond_return"], row["status"],
                ]
                
                for col, val in enumerate(vals):
                    cell = ctk.CTkFrame(table_inner, fg_color=bg, corner_radius=0)
                    cell.grid(row=r_idx, column=col, sticky="nsew")

                    txt_color = "#1A1A1A"
                    font_w = "normal"
                    if col == 8:
                        txt_color = "#D8000C" if val == "Active" else "#2ECC71"
                        font_w = "bold"
                    elif col == 3 and val == "Unassigned":
                        txt_color = "#D8000C"
                        font_w = "bold"

                    lbl = ctk.CTkLabel(cell, text=val, font=("Inter", 11, font_w), text_color=txt_color, justify="center", anchor="center")
                    
                    # High-performance static wrapping
                    lbl.configure(wraplength=min_sizes[col] - 10)

                    lbl.pack(fill="both", expand=True, padx=4, pady=12)

        except Exception as e:
            ctk.CTkLabel(
                self._audit_scroll, text=f"Error: {e}", text_color="red").pack(pady=10)
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

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

        self.act_search = ctk.CTkEntry(
            filter_row, placeholder_text="Search user or details...", width=200)
        self.act_search.pack(side="left", padx=(0, 5))
        self.act_search.bind("<Return>", lambda e: self.do_act_search())

        ctk.CTkButton(filter_row, text="Search", width=80,
                      fg_color="#1E4528", hover_color="#14301C",
                      font=("Inter", 11, "bold"),
                      command=self.do_act_search).pack(side="left", padx=5)
        ctk.CTkButton(filter_row, text="↻ Reset", width=70,
                      fg_color="#E0E0E0", text_color="black", hover_color="#CCCCCC",
                      command=lambda: [
                          self.act_search.delete(0, "end"),
                          self.act_module_filter.set("All"),
                          self.do_act_search()
                      ]).pack(side="left")

        self.act_summary = ctk.CTkLabel(frame, text="", font=(
            "Inter", 11, "bold"), text_color="#1E4528")
        self.act_summary.pack(anchor="w", padx=20, pady=(0, 5))

        self._act_scroll = ctk.CTkScrollableFrame(
            frame, fg_color="transparent")
        self._act_scroll.pack(fill="both", expand=True, padx=20, pady=(5, 5))
        
        self.pagination_frame = ctk.CTkFrame(frame, fg_color="transparent")
        self.pagination_frame.pack(fill="x", padx=20, pady=(0, 20))

        self.act_prev_btn = ctk.CTkButton(self.pagination_frame, text="◀ Previous", width=100, fg_color="#E0E0E0", text_color="black", hover_color="#CCCCCC", font=("Inter", 11, "bold"), command=self.act_prev_page)
        self.act_prev_btn.pack(side="left", padx=5)

        self.act_page_label = ctk.CTkLabel(self.pagination_frame, text="Page 1", font=("Inter", 11, "bold"))
        self.act_page_label.pack(side="left", expand=True)

        self.act_next_btn = ctk.CTkButton(self.pagination_frame, text="Next ▶", width=100, fg_color="#1E4528", hover_color="#14301C", font=("Inter", 11, "bold"), command=self.act_next_page)
        self.act_next_btn.pack(side="right", padx=5)

        self.current_act_page = 1
        self.act_page_size = 50

        return frame

    def do_act_search(self):
        self.current_act_page = 1
        self.load_activity()

    def act_prev_page(self):
        if self.current_act_page > 1:
            self.current_act_page -= 1
            self.load_activity()

    def act_next_page(self):
        if getattr(self, "has_more_act_pages", False):
            self.current_act_page += 1
            self.load_activity()

    def load_activity(self):
        for w in self._act_scroll.winfo_children():
            w.destroy()

        table_inner = ctk.CTkFrame(self._act_scroll, fg_color="transparent")
        table_inner.pack(fill="x", expand=True)

        headers = ["Log ID", "Timestamp", "Employee", "Action Type", "Module", "Details"]
        weights = [1, 3, 3, 2, 2, 5]
        min_sizes = [60, 150, 150, 100, 120, 250]

        for col, (w, min_w) in enumerate(zip(weights, min_sizes)):
            table_inner.grid_columnconfigure(col, weight=w, minsize=min_w, uniform="act_cols")

        for col, text in enumerate(headers):
            cell = ctk.CTkFrame(table_inner, fg_color="#1E4528", corner_radius=0)
            cell.grid(row=0, column=col, sticky="nsew", pady=(0, 2))
            lbl = ctk.CTkLabel(cell, text=text, font=("Inter", 11, "bold"), text_color="white", anchor="center")
            lbl.pack(fill="both", expand=True, padx=2, pady=10)

        module_filter = self.act_module_filter.get() if hasattr(
            self, "act_module_filter") else "All"
        q = self.act_search.get().strip() if hasattr(self, "act_search") else ""

        conn = get_connection()
        if not conn:
            return
        try:
            cursor = conn.cursor(dictionary=True)
            count_sql = """
                SELECT COUNT(*) as cnt
                FROM system_logs sl
                LEFT JOIN user u ON sl.user_id = u.user_id
                WHERE 1=1
            """
            count_params = []
            if module_filter != "All":
                count_sql += " AND sl.module = %s"
                count_params.append(module_filter)
            if q:
                count_sql += " AND (u.full_name LIKE %s OR sl.details LIKE %s OR sl.action_type LIKE %s)"
                count_params += [f"%{q}%", f"%{q}%", f"%{q}%"]
                
            cursor.execute(count_sql, count_params)
            total_records = cursor.fetchone()["cnt"]
            
            sql = """
                SELECT sl.log_id,
                       DATE_FORMAT(sl.timestamp, '%b %d, %Y %I:%i %p') as ts,
                       IFNULL(u.full_name, CONCAT('UID:', sl.user_id)) as employee,
                       sl.action_type, sl.module, IFNULL(sl.details,'—') as details
                FROM system_logs sl
                LEFT JOIN user u ON sl.user_id = u.user_id
                WHERE 1=1
            """
            params = list(count_params)
            offset = (self.current_act_page - 1) * self.act_page_size
            sql += f" ORDER BY sl.log_id DESC LIMIT {self.act_page_size} OFFSET {offset}"
            
            cursor.execute(sql, params)
            rows = cursor.fetchall()

            total_pages = (total_records + self.act_page_size - 1) // self.act_page_size
            if total_pages == 0: total_pages = 1
            
            self.has_more_act_pages = self.current_act_page < total_pages
            self.act_page_label.configure(text=f"Page {self.current_act_page} of {total_pages}")
            self.act_prev_btn.configure(state="normal" if self.current_act_page > 1 else "disabled")
            self.act_next_btn.configure(state="normal" if self.has_more_act_pages else "disabled")

            start_idx = offset + 1 if total_records > 0 else 0
            end_idx = min(offset + self.act_page_size, total_records)
            self.act_summary.configure(text=f"  Showing {start_idx}-{end_idx} of {total_records} entries")

            if not rows:
                ctk.CTkLabel(table_inner, text="No activity records found.",
                             text_color="gray").grid(row=1, column=0, columnspan=len(headers), pady=20)
                return

            action_colors = {
                "Login":    "#2ECC71", "Logout":   "#E74C3C", "Added":     "#3498DB",
                "Edited":   "#F39C12", "Archived": "#95A5A6", "Searched": "#9B59B6",
                "Viewed":   "#1A1A1A", "Issued":   "#27AE60", "Retrieved": "#16A085",
                "Submitted": "#2980B9", "Approved": "#27AE60", "Flagged":  "#D8000C",
                "Resolved": "#2ECC71",
            }

            for i, row in enumerate(rows):
                r_idx = i + 1
                bg = "#F9FAFB" if i % 2 == 0 else "white"

                vals = [
                    str(row["log_id"]), row["ts"], row["employee"],
                    row["action_type"], row["module"], row["details"]
                ]
                
                for col, val in enumerate(vals):
                    cell = ctk.CTkFrame(table_inner, fg_color=bg, corner_radius=0)
                    cell.grid(row=r_idx, column=col, sticky="nsew")

                    txt_color = "#1A1A1A"
                    font_w = "normal"
                    if col == 3:
                        txt_color = action_colors.get(val, "#555555")
                        font_w = "bold"

                    lbl = ctk.CTkLabel(cell, text=val, font=("Inter", 11, font_w), text_color=txt_color, justify="center", anchor="center")
                    
                    # High-performance static wrapping
                    lbl.configure(wraplength=min_sizes[col] - 10)

                    lbl.pack(fill="both", expand=True, padx=4, pady=12)

        except Exception as e:
            ctk.CTkLabel(
                self._act_scroll, text=f"Error: {e}", text_color="red").pack(pady=10)
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

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
        ctk.CTkLabel(top, text="My Borrowing & Return History", font=(
            "Inter", 16, "bold"), text_color="#1A1A1A").pack(side="left")
        ctk.CTkLabel(frame, text="Click on any transaction record below to view its Deployment Receipt.", font=(
            "Inter", 11), text_color="gray").pack(anchor="w", padx=20, pady=(0, 10))

        scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=20, pady=(5, 20))

        table_inner = ctk.CTkFrame(scroll, fg_color="transparent")
        table_inner.pack(fill="x", expand=True)

        headers = ["TRN", "Tool Name", "Tag ID", "Borrow Date", "Return Date", "Cond@Return", "Status"]
        weights = [1, 3, 2, 3, 3, 2, 1]
        min_sizes = [50, 160, 100, 150, 150, 100, 80]

        for col, (w, min_w) in enumerate(zip(weights, min_sizes)):
            table_inner.grid_columnconfigure(col, weight=w, minsize=min_w, uniform="staff_cols")

        # Header Row
        for col, text in enumerate(headers):
            cell = ctk.CTkFrame(table_inner, fg_color="#1E4528", corner_radius=0)
            cell.grid(row=0, column=col, sticky="nsew", pady=(0, 2))
            lbl = ctk.CTkLabel(cell, text=text, font=("Inter", 11, "bold"), text_color="white", anchor="center")
            lbl.pack(fill="both", expand=True, padx=2, pady=10)

        user_id = self.user_info.get("user_id")
        if not user_id:
            emp_id = self.user_info.get("employee_id")
            if emp_id:
                conn2 = get_connection()
                if conn2:
                    try:
                        c2 = conn2.cursor(dictionary=True)
                        c2.execute(
                            "SELECT user_id FROM user WHERE employee_id = %s", (emp_id,))
                        row2 = c2.fetchone()
                        if row2:
                            user_id = row2["user_id"]
                    except Exception:
                        pass
                    finally:
                        if conn2.is_connected():
                            c2.close()
                            conn2.close()

        if not user_id:
            ctk.CTkLabel(table_inner, text="Could not resolve user session. Please log out and log back in.",
                         text_color="red").grid(row=1, column=0, columnspan=len(headers), pady=20)
            ctk.CTkLabel(scroll, text="Could not resolve user session. Please log out and log back in.",
                         text_color="red").pack(pady=20)
            return

        conn = get_connection()
        if not conn:
            return
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT tr.transaction_id, t.name as tool_name,
                       IFNULL(t.tag_id,'Unassigned') as tag_id,
                       DATE_FORMAT(tr.borrow_date, '%b %d, %Y %I:%i %p') as borrow_date,
                       IF(tr.return_date IS NOT NULL, DATE_FORMAT(tr.return_date, '%b %d, %Y %I:%i %p'), '—') as return_date,
                       IFNULL(tr.condition_at_return,'—') as cond_return,
                       tr.status
                FROM transaction tr
                JOIN tool t ON tr.tool_id = t.tool_id
                WHERE tr.user_id = %s
                ORDER BY tr.borrow_date DESC
            """, (user_id,))
            rows = cursor.fetchall()

            if not rows:
                ctk.CTkLabel(
                    table_inner, text="You have no borrowing history.", text_color="gray").grid(row=1, column=0, columnspan=len(headers), pady=20)
                return

            for i, row in enumerate(rows):
                r_idx = i + 1
                bg = "#F9FAFB" if i % 2 == 0 else "white"

                vals = [
                    str(row["transaction_id"]), row["tool_name"], row["tag_id"],
                    row["borrow_date"], row["return_date"],
                    row["cond_return"], row["status"]
                ]
                
                for col, val in enumerate(vals):
                    cell = ctk.CTkFrame(table_inner, fg_color=bg, corner_radius=0, cursor="hand2")
                    cell.grid(row=r_idx, column=col, sticky="nsew")

                    txt_color = "#1A1A1A"
                    font_w = "normal"
                    if col == 6:
                        txt_color = "#D8000C" if val == "Active" else "#2ECC71"
                        font_w = "bold"
                    elif col == 2 and val == "Unassigned":
                        txt_color = "#D8000C"
                        font_w = "bold"

                    lbl = ctk.CTkLabel(cell, text=val, font=("Inter", 11, font_w), text_color=txt_color, justify="center", anchor="center", cursor="hand2")
                    
                    # High-performance static wrapping
                    lbl.configure(wraplength=min_sizes[col] - 10)

                    lbl.pack(fill="both", expand=True, padx=4, pady=12)

                    # Binds whole cell & text to open the modal
                    cell.bind("<Button-1>", lambda e, r=row: self.view_deployment_details(r))
                    lbl.bind("<Button-1>", lambda e, r=row: self.view_deployment_details(r))

        except Exception as e:
            ctk.CTkLabel(
                scroll, text=f"Error: {e}", text_color="red").pack(pady=10)
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()