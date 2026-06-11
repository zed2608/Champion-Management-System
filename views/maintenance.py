import customtkinter as ctk
from tkinter import messagebox, filedialog
from database import get_connection, log_action
from datetime import datetime
import os
import subprocess
import threading


class MaintenanceView(ctk.CTkFrame):
    def __init__(self, parent, user_info=None):
        super().__init__(parent, fg_color="transparent")

        self.user_info = user_info or {}
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.build_view()

        uid = self.user_info.get("user_id")
        if uid:
            log_action(uid, "Viewed", "Maintenance",
                       "Opened Maintenance module")

    def _ensure_user_archive_columns(self):
        """Run schema migration in its own connection to avoid cursor state conflicts."""
        conn = get_connection()
        if not conn:
            return
        try:
            cursor = conn.cursor()
            cursor.execute("SHOW COLUMNS FROM `user` LIKE 'status'")
            has_status = cursor.fetchone() is not None
            cursor.fetchall()  # drain any remaining rows
            if not has_status:
                cursor.execute(
                    "ALTER TABLE `user` ADD COLUMN status VARCHAR(50) NOT NULL DEFAULT 'Active'"
                )

            cursor.execute("SHOW COLUMNS FROM `user` LIKE 'archived_at'")
            has_archived = cursor.fetchone() is not None
            cursor.fetchall()  # drain
            if not has_archived:
                cursor.execute(
                    "ALTER TABLE `user` ADD COLUMN archived_at DATETIME NULL"
                )
            conn.commit()
        except Exception as e:
            print(f"[Maintenance] Schema migration warning: {e}")
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    def build_view(self):
        # Run schema migration once before any tab tries to query user columns
        self._ensure_user_archive_columns()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)

        top_bar = ctk.CTkFrame(self, fg_color="transparent")
        top_bar.grid(row=0, column=0, sticky="ew", padx=20, pady=(10, 15))

        ctk.CTkLabel(
            top_bar, text="Maintenance & Archive",
            font=("Inter", 16, "bold"), text_color="#1E4528"
        ).pack(side="left")

        tab_labels = [
            "🔧 Issues & Repairs",
            "📦 Archived Tools",
            "👥 Archived Employees",
            "📋 Archived Projects",
            "💾 Backup & Restore",
        ]
        self.tab_var = ctk.StringVar(value=tab_labels[0])
        self.seg_btn = ctk.CTkSegmentedButton(
            top_bar, values=tab_labels, variable=self.tab_var,
            command=self.switch_tab,
            fg_color="#F0F0F0", selected_color="#1E4528",
            selected_hover_color="#14301C"
        )
        self.seg_btn.pack(side="right")

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
        elif "Backup" in selected_tab:
            self.load_backup_history()

    # ------------------------------------------
    # TAB 1: Manage Issues
    # ------------------------------------------
    def render_issues_tab(self):
        frame = ctk.CTkFrame(
            self.tab_content, fg_color="white", corner_radius=10)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(20, 5))
        ctk.CTkLabel(top, text="Tool Issue Management",
                     font=("Inter", 16, "bold"), text_color="#1A1A1A").pack(side="left")

        ctk.CTkLabel(frame,
                     text="Flag damaged or lost tools, track discrepancies, and manage resolutions. "
                          "Flagging a tool automatically updates its condition in the inventory.",
                     font=("Inter", 11), text_color="gray",
                     wraplength=750, justify="left").pack(anchor="w", padx=20, pady=(0, 10))

        flag_card = ctk.CTkFrame(frame, fg_color="#F9FAFB", corner_radius=10)
        flag_card.pack(fill="x", padx=20, pady=(0, 12))

        ctk.CTkLabel(flag_card, text="🚩  Flag a Tool Issue",
                     font=("Inter", 13, "bold"), text_color="#D8000C").pack(anchor="w", padx=15, pady=(12, 8))

        form_grid = ctk.CTkFrame(flag_card, fg_color="transparent")
        form_grid.pack(fill="x", padx=15, pady=(0, 8))
        form_grid.grid_columnconfigure((0, 1, 2, 3), weight=1)

        ctk.CTkLabel(form_grid, text="Tool PID or Tag ID", font=("Inter", 11, "bold"),
                     text_color="#1A1A1A").grid(row=0, column=0, sticky="w", padx=5)
        ctk.CTkLabel(form_grid, text="Reported By (Employee ID)", font=("Inter", 11, "bold"),
                     text_color="#1A1A1A").grid(row=0, column=1, sticky="w", padx=5)
        ctk.CTkLabel(form_grid, text="Issue / Condition Type", font=("Inter", 11, "bold"),
                     text_color="#1A1A1A").grid(row=0, column=2, sticky="w", padx=5)

        self.flag_tool_id = ctk.CTkEntry(
            form_grid, placeholder_text="e.g., TAG-003 or PID 42")
        self.flag_tool_id.grid(
            row=1, column=0, sticky="ew", padx=5, pady=(3, 8))
        self.flag_reported_by = ctk.CTkEntry(
            form_grid, placeholder_text="e.g., EMP-001")
        self.flag_reported_by.grid(
            row=1, column=1, sticky="ew", padx=5, pady=(3, 8))
        self.flag_condition = ctk.CTkOptionMenu(
            form_grid,
            values=["Damaged", "Lost", "Needs Repair", "Discrepancy",
                    "Missing Parts", "Stolen", "Other"],
            fg_color="#F9FAFB", text_color="black"
        )
        self.flag_condition.grid(
            row=1, column=2, sticky="ew", padx=5, pady=(3, 8))

        notes_row = ctk.CTkFrame(flag_card, fg_color="transparent")
        notes_row.pack(fill="x", padx=15, pady=(0, 12))
        notes_row.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(notes_row, text="Issue Description / Notes",
                     font=("Inter", 11, "bold"), text_color="#1A1A1A").grid(
            row=0, column=0, sticky="w", pady=(0, 3))
        self.flag_notes = ctk.CTkEntry(
            notes_row, placeholder_text="Describe the issue in detail...")
        self.flag_notes.grid(row=1, column=0, sticky="ew", padx=(0, 10))

        ctk.CTkButton(notes_row, text="Submit Flag", width=130,
                      fg_color="#D8000C", hover_color="#B00000",
                      text_color="white", font=("Inter", 12, "bold"),
                      command=self.submit_flag).grid(row=1, column=1, padx=(0, 0))

        filter_row = ctk.CTkFrame(frame, fg_color="transparent")
        filter_row.pack(fill="x", padx=20, pady=(0, 5))

        ctk.CTkLabel(filter_row, text="Show:", font=(
            "Inter", 12), text_color="gray").pack(side="left")
        self.issues_filter = ctk.CTkOptionMenu(
            filter_row, values=["Open (Pending)", "All Issues", "Resolved"],
            width=150, fg_color="#F9FAFB", text_color="black",
            command=lambda e: self.load_issues()
        )
        self.issues_filter.pack(side="left", padx=8)
        self.issues_filter.set("Open (Pending)")

        self.issues_search_var = ctk.StringVar()
        self.issues_search = ctk.CTkEntry(filter_row, placeholder_text="Search tool or reporter...",
                                          width=200, textvariable=self.issues_search_var)
        self.issues_search.pack(side="left", padx=(0, 5))

        self._issues_timer = None

        def on_issues_search(*args):
            if self._issues_timer:
                self.after_cancel(self._issues_timer)
            self._issues_timer = self.after(300, self.load_issues)
        self.issues_search_var.trace_add("write", on_issues_search)

        self.issues_summary = ctk.CTkLabel(frame, text="", font=("Inter", 11, "bold"),
                                           text_color="#1E4528")
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

        if not tool_input or not reported_by:
            messagebox.showerror("Error", "Tool ID/Tag and Reported By are required.",
                                 parent=self.winfo_toplevel())
            return

        conn = get_connection()
        if not conn:
            return
        try:
            cursor = conn.cursor(dictionary=True)
            if tool_input.isdigit():
                cursor.execute(
                    "SELECT tool_id, name FROM tool WHERE tool_id = %s", (tool_input,))
            else:
                cursor.execute(
                    "SELECT tool_id, name FROM tool WHERE tag_id = %s", (tool_input,))
            tool = cursor.fetchone()
            if not tool:
                messagebox.showerror("Not Found", "No tool found with that PID or Tag ID.",
                                     parent=self.winfo_toplevel())
                return

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tool_issues (
                    issue_id INT AUTO_INCREMENT PRIMARY KEY,
                    tool_id INT NOT NULL,
                    reported_by VARCHAR(100),
                    condition_flag VARCHAR(100),
                    notes TEXT,
                    flagged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_resolved TINYINT(1) DEFAULT 0,
                    FOREIGN KEY (tool_id) REFERENCES tool(tool_id)
                )
            """)
            cursor.execute("""
                INSERT INTO tool_issues (tool_id, reported_by, condition_flag, notes)
                VALUES (%s, %s, %s, %s)
            """, (tool["tool_id"], reported_by, condition, notes or "No additional details."))
            cursor.execute(
                "UPDATE tool SET `condition` = %s WHERE tool_id = %s",
                (condition, tool["tool_id"])
            )
            conn.commit()

            uid = self.user_info.get("user_id")
            if uid:
                log_action(uid, "Flagged", "Maintenance",
                           f"Flagged tool '{tool['name']}' (PID: {tool['tool_id']}) — {condition}: {notes}")

            messagebox.showinfo("Flagged",
                                f"Tool '{tool['name']}' has been flagged.\n"
                                f"Its condition has been updated to '{condition}' in the inventory.",
                                parent=self.winfo_toplevel())
            self.flag_tool_id.delete(0, "end")
            self.flag_reported_by.delete(0, "end")
            self.flag_notes.delete(0, "end")
            self.load_issues()
        except Exception as e:
            messagebox.showerror("Database Error", str(e),
                                 parent=self.winfo_toplevel())
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    def load_issues(self):
        for w in self._issues_scroll.winfo_children():
            w.destroy()

        # Hard-Bounded Uniform Grid Setup
        table_inner = ctk.CTkFrame(self._issues_scroll, fg_color="transparent")
        table_inner.pack(fill="x", expand=True)

        headers = ["#", "Tool Name", "Reported By",
                   "Issue Type", "Description", "Flagged At", "Status"]
        weights = [1, 3, 2, 2, 4, 3, 2]
        min_sizes = [50, 150, 100, 100, 200, 150, 100]

        for col, (w, min_w) in enumerate(zip(weights, min_sizes)):
            table_inner.grid_columnconfigure(
                col, weight=w, minsize=min_w, uniform="issue_cols")

        for col, text in enumerate(headers):
            cell = ctk.CTkFrame(
                table_inner, fg_color="#1E4528", corner_radius=0)
            cell.grid(row=0, column=col, sticky="nsew", pady=(0, 2))
            lbl = ctk.CTkLabel(cell, text=text, font=(
                "Inter", 12, "bold"), text_color="white", anchor="center")
            lbl.pack(fill="both", expand=True, padx=2, pady=10)

        loading_lbl = ctk.CTkLabel(table_inner, text="↻ Loading issues... Please wait",
                                   text_color="gray", font=("Inter", 12, "italic"))
        loading_lbl.grid(row=1, column=0, columnspan=len(headers), pady=20)

        status_filter = self.issues_filter.get() if hasattr(
            self, "issues_filter") else "Open (Pending)"
        q = self.issues_search.get().strip() if hasattr(self, "issues_search") else ""

        def _fetch():
            conn = get_connection()
            if not conn:
                self.after(0, lambda: loading_lbl.configure(text="Error: Could not connect to database.", text_color="red"))
                return
            try:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS tool_issues (
                        issue_id INT AUTO_INCREMENT PRIMARY KEY,
                        tool_id INT NOT NULL,
                        reported_by VARCHAR(100),
                        condition_flag VARCHAR(100),
                        notes TEXT,
                        flagged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        is_resolved TINYINT(1) DEFAULT 0,
                        FOREIGN KEY (tool_id) REFERENCES tool(tool_id)
                    )
                """)
                conn.commit()

                # --- THE AUTO-SYNC FIX ---
                cursor.execute("""
                    INSERT INTO tool_issues (tool_id, reported_by, condition_flag, notes, is_resolved)
                    SELECT tool_id, 'System Auto-Sync', `condition`, 'Automatically flagged by system due to inventory condition.', 0
                    FROM tool t
                    WHERE `condition` IN ('Needs Repair', 'Damaged', 'Lost')
                      AND is_archived = 0
                      AND NOT EXISTS (
                          SELECT 1 FROM tool_issues ti WHERE ti.tool_id = t.tool_id AND ti.is_resolved = 0
                      )
                """)
                conn.commit()

                sql = """
                    SELECT ti.issue_id, t.name as tool_name, ti.reported_by,
                           ti.condition_flag, IFNULL(ti.notes,'—') as notes,
                       ti.flagged_at,
                           ti.is_resolved
                    FROM tool_issues ti
                    JOIN tool t ON ti.tool_id = t.tool_id
                    WHERE 1=1
                """
                params = []
                if status_filter == "Open (Pending)":
                    sql += " AND ti.is_resolved = 0"
                elif status_filter == "Resolved":
                    sql += " AND ti.is_resolved = 1"
                if q:
                    sql += " AND (t.name LIKE %s OR ti.reported_by LIKE %s OR ti.condition_flag LIKE %s)"
                    params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
                sql += " ORDER BY ti.is_resolved ASC, ti.flagged_at DESC"
                cursor.execute(sql, tuple(params))
                rows = cursor.fetchall()

                self.after(0, lambda: self._render_issues(
                    rows, table_inner, loading_lbl, headers, min_sizes))
            except Exception as e:
                self.after(0, lambda err=e: loading_lbl.configure(
                    text=f"Error: {err}", text_color="red", wraplength=600))
            finally:
                if conn.is_connected():
                    cursor.close()
                    conn.close()

        import threading
        threading.Thread(target=_fetch, daemon=True).start()

    def _render_issues(self, rows, table_inner, loading_lbl, headers, min_sizes):
        if not self.winfo_exists() or not table_inner.winfo_exists():
            return
        loading_lbl.destroy()

        total = len(rows)
        open_cnt = sum(1 for r in rows if not r["is_resolved"])
        resolved_cnt = total - open_cnt
        if hasattr(self, "issues_summary"):
            self.issues_summary.configure(
                text=f"  Total: {total}   |   Open: {open_cnt}   |   Resolved: {resolved_cnt}"
            )

        if not rows:
            ctk.CTkLabel(
                table_inner, text="No issues found. Inventory is clean.", text_color="gray").grid(row=1, column=0, columnspan=len(headers), pady=20)
            return

        condition_colors = {
            "Damaged": "#E74C3C", "Lost": "#C0392B", "Needs Repair": "#F39C12",
            "Discrepancy": "#8E44AD", "Stolen": "#C0392B", "Missing Parts": "#D35400", "Other": "#7F8C8D",
        }

        for i, row in enumerate(rows):
            resolved_text = "✓ Resolved" if row["is_resolved"] else "⚠ Pending"
            vals = [
                str(row["issue_id"]), row["tool_name"], row["reported_by"],
                row["condition_flag"], row["notes"], row["flagged_at"], resolved_text,
            ]
            bg = "#F0FFF0" if row["is_resolved"] else (
                "#FFF8F0" if i % 2 == 0 else "#FFF3F3")

            r_idx = i + 1
            for col, val in enumerate(vals):
                cell = ctk.CTkFrame(table_inner, fg_color=bg,
                                    corner_radius=0, cursor="hand2")
                cell.grid(row=r_idx, column=col, sticky="nsew")

                txt_col = "#1A1A1A"
                if col == 3:
                    txt_col = condition_colors.get(val, "#D35400")
                elif col == 6:
                    txt_col = "#2ECC71" if "Resolved" in val else "#D8000C"
                font_w = "bold" if col in (3, 6) else "normal"

                lbl = ctk.CTkLabel(cell, text=val, font=(
                    "Inter", 12, font_w), text_color=txt_col, justify="center", anchor="center", cursor="hand2")

                # High-performance static wrapping
                lbl.configure(wraplength=min_sizes[col] - 10)
                lbl.pack(fill="both", expand=True, padx=4, pady=12)

                cell.bind("<Button-1>", lambda e,
                          r=row: self.open_issue_modal(r))
                lbl.bind("<Button-1>", lambda e,
                         r=row: self.open_issue_modal(r))

    def open_issue_modal(self, row):
        modal = ctk.CTkToplevel(self)
        modal.title(f"Issue #{row['issue_id']} — {row['tool_name']}")
        modal.configure(fg_color="white")
        modal.attributes("-topmost", True)
        modal.grab_set()

        modal.update_idletasks()
        x = (modal.winfo_screenwidth() // 2) - (480 // 2)
        y = (modal.winfo_screenheight() // 2) - (470 // 2)
        modal.geometry(f"480x470+{x}+{y}")

        status_color = "#2ECC71" if row["is_resolved"] else "#D8000C"
        status_text = "✓ RESOLVED" if row["is_resolved"] else "⚠ PENDING"
        ctk.CTkLabel(modal, text=f"Issue #{row['issue_id']}: {row['tool_name']}",
                     font=("Inter", 15, "bold"), text_color="black").pack(pady=(20, 3))
        ctk.CTkLabel(modal, text=f"{status_text}  |  Flagged by: {row['reported_by']}",
                     font=("Inter", 11, "bold"), text_color=status_color).pack(pady=(0, 5))
        ctk.CTkLabel(modal, text=f"Flagged At: {row['flagged_at']}",
                     font=("Inter", 11), text_color="gray").pack(pady=(0, 10))

        detail_card = ctk.CTkFrame(modal, fg_color="#F9FAFB", corner_radius=8)
        detail_card.pack(fill="x", padx=25, pady=(0, 10))
        ctk.CTkLabel(detail_card, text=f"Issue Type:  {row['condition_flag']}",
                     font=("Inter", 12, "bold"), text_color="#D35400").pack(anchor="w", padx=15, pady=(10, 3))
        ctk.CTkLabel(detail_card, text=f"Description:  {row['notes']}",
                     font=("Inter", 11), text_color="#1A1A1A",
                     wraplength=400, justify="left").pack(anchor="w", padx=15, pady=(0, 10))

        form = ctk.CTkFrame(modal, fg_color="transparent")
        form.pack(fill="x", padx=25)

        ctk.CTkLabel(form, text="Update Condition:", font=("Inter", 11, "bold"),
                     text_color="#1A1A1A").pack(anchor="w")
        cond_menu = ctk.CTkOptionMenu(
            form, values=["Good", "Needs Repair", "Damaged", "Lost"],
            fg_color="#F9FAFB", text_color="black")
        cond_menu.set(row["condition_flag"] if row["condition_flag"] in
                      ["Good", "Needs Repair", "Damaged", "Lost"] else "Needs Repair")
        cond_menu.pack(fill="x", pady=(5, 10))

        ctk.CTkLabel(form, text="Restock Quantity (if replaced/found):", font=("Inter", 11, "bold"),
                     text_color="#1A1A1A").pack(anchor="w")
        restock_entry = ctk.CTkEntry(
            form, placeholder_text="0 (Leave 0 if already in stock)")
        restock_entry.pack(fill="x", pady=(5, 10))

        ctk.CTkLabel(form, text="Resolution Notes:", font=("Inter", 11, "bold"),
                     text_color="#1A1A1A").pack(anchor="w")
        notes_entry = ctk.CTkEntry(
            form, placeholder_text="e.g., Sent to repair, replaced, etc.")
        notes_entry.pack(fill="x", pady=(5, 10))

        def resolve_issue():
            conn = get_connection()
            if not conn:
                return
            try:
                cursor = conn.cursor()
                resolution = notes_entry.get().strip() or "Marked resolved by Admin."

                try:
                    rq = float(restock_entry.get().strip() or 0)
                    if rq < 0:
                        raise ValueError
                except ValueError:
                    messagebox.showerror(
                        "Error", "Restock Quantity must be a positive number.", parent=modal)
                    return

                if rq > 0:
                    cursor.execute(
                        "UPDATE inventory SET quantity_available = quantity_available + %s, quantity_total = quantity_total + %s WHERE tool_id = %s", (rq, rq, row["tool_id"]))

                cursor.execute("""
                    UPDATE tool_issues
                    SET is_resolved = 1, condition_flag = %s,
                        notes = CONCAT(IFNULL(notes,''), ' | Resolution: ', %s)
                    WHERE issue_id = %s
                """, (cond_menu.get(), resolution, row["issue_id"]))

                cursor.execute("""
                    UPDATE tool SET `condition` = %s
                    WHERE tool_id = (SELECT tool_id FROM tool_issues WHERE issue_id = %s)
                """, (cond_menu.get(), row["issue_id"]))
                conn.commit()

                uid = self.user_info.get("user_id")
                if uid:
                    log_action(uid, "Resolved", "Maintenance",
                               f"Resolved issue #{row['issue_id']} for '{row['tool_name']}'. "
                               f"New condition: {cond_menu.get()}")

                messagebox.showinfo(
                    "Resolved", "Issue marked as resolved, inventory updated, and removed from open issues.", parent=modal)
                modal.destroy()
                self.load_issues()
            except Exception as e:
                messagebox.showerror("Error", str(e), parent=modal)
            finally:
                if conn.is_connected():
                    cursor.close()
                    conn.close()

        btn_row = ctk.CTkFrame(modal, fg_color="transparent")
        btn_row.pack(fill="x", padx=25, pady=(5, 20))
        ctk.CTkButton(btn_row, text="✓ Mark Resolved & Update Inventory",
                      fg_color="#1E4528", hover_color="#14301C",
                      command=resolve_issue).pack(side="left", padx=(0, 10), fill="x", expand=True)
        ctk.CTkButton(btn_row, text="Close", fg_color="#E0E0E0",
                      text_color="black", hover_color="#CCCCCC", width=80,
                      command=modal.destroy).pack(side="right")

    # ------------------------------------------
    # TAB 2: Archived Tools
    # ------------------------------------------
    def render_tools_tab(self):
        frame = ctk.CTkFrame(
            self.tab_content, fg_color="white", corner_radius=10)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(20, 10))
        ctk.CTkLabel(top, text="Archived & Decommissioned Tools",
                     font=("Inter", 16, "bold"), text_color="#1A1A1A").pack(side="left")

        self._tools_scroll = ctk.CTkScrollableFrame(
            frame, fg_color="transparent")
        self._tools_scroll.pack(
            fill="both", expand=True, padx=20, pady=(5, 20))
        return frame

    def load_archived_tools(self):
        for w in self._tools_scroll.winfo_children():
            w.destroy()

        # Hard-Bounded Uniform Grid Setup
        table_inner = ctk.CTkFrame(self._tools_scroll, fg_color="transparent")
        table_inner.pack(fill="x", expand=True)

        headers = ["Tool ID", "Name", "Category",
                   "Qty", "Archived At", "Action"]
        weights = [1, 3, 2, 1, 2, 1]
        min_sizes = [70, 200, 150, 60, 150, 100]

        for col, (w, min_w) in enumerate(zip(weights, min_sizes)):
            table_inner.grid_columnconfigure(
                col, weight=w, minsize=min_w, uniform="tool_cols")

        for col, text in enumerate(headers):
            cell = ctk.CTkFrame(
                table_inner, fg_color="#1E4528", corner_radius=0)
            cell.grid(row=0, column=col, sticky="nsew", pady=(0, 2))
            lbl = ctk.CTkLabel(cell, text=text, font=(
                "Inter", 12, "bold"), text_color="white", anchor="center")
            lbl.pack(fill="both", expand=True, padx=2, pady=10)

        loading_lbl = ctk.CTkLabel(table_inner, text="↻ Loading archived tools... Please wait",
                                   text_color="gray", font=("Inter", 12, "italic"))
        loading_lbl.grid(row=1, column=0, columnspan=len(headers), pady=20)

        def _fetch():
            conn = get_connection()
            if not conn:
                self.after(0, lambda: loading_lbl.configure(text="Error: Could not connect to database.", text_color="red"))
                return
            try:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("""
                    SELECT t.tool_id, t.name, t.category, t.`condition`,
                           IFNULL(t.archived_at, t.date_acquired) as archived_date,
                           IFNULL(i.quantity_total, 0) as qty_total
                    FROM tool t
                    LEFT JOIN inventory i ON t.tool_id = i.tool_id
                    WHERE t.is_archived = 1
                    ORDER BY t.archived_at DESC
                """)
                rows = cursor.fetchall()
                self.after(0, lambda: self._render_archived_tools(
                    rows, table_inner, loading_lbl, headers, min_sizes))
            except Exception as e:
                self.after(0, lambda err=e: loading_lbl.configure(
                    text=f"Error: {err}", text_color="red", wraplength=600))
            finally:
                if conn.is_connected():
                    cursor.close()
                    conn.close()

        import threading
        threading.Thread(target=_fetch, daemon=True).start()

    def _render_archived_tools(self, rows, table_inner, loading_lbl, headers, min_sizes):
        if not self.winfo_exists() or not table_inner.winfo_exists():
            return
        loading_lbl.destroy()

        if not rows:
            ctk.CTkLabel(
                table_inner, text="No archived tools found.", text_color="gray").grid(row=1, column=0, columnspan=len(headers), pady=20)
            return

        for i, row in enumerate(rows):
            archived_ts = row["archived_date"].strftime(
                "%Y-%m-%d %H:%M") if row["archived_date"] else "—"
            vals = [str(row["tool_id"]), row["name"], row["category"],
                    f"{row['qty_total']:g}", archived_ts]

            r_idx = i + 1
            bg = "#F9FAFB" if i % 2 == 0 else "white"

            for col, val in enumerate(vals):
                cell = ctk.CTkFrame(table_inner, fg_color=bg, corner_radius=0)
                cell.grid(row=r_idx, column=col, sticky="nsew")
                lbl = ctk.CTkLabel(cell, text=val, font=(
                    "Inter", 12), text_color="#1A1A1A", justify="center", anchor="center")
                lbl.configure(wraplength=min_sizes[col] - 10)
                lbl.pack(fill="both", expand=True, padx=4, pady=12)

            btn_cell = ctk.CTkFrame(table_inner, fg_color=bg, corner_radius=0)
            btn_cell.grid(row=r_idx, column=5, sticky="nsew")
            btn_f = ctk.CTkFrame(btn_cell, fg_color="transparent")
            btn_f.pack(expand=True)

            btn = ctk.CTkButton(btn_f, text="Restore", width=60, height=28, fg_color="#2980B9", hover_color="#1F618D", font=(
                "Inter", 11, "bold"), command=lambda r=row["tool_id"]: self.restore_tool(r))
            btn.pack(expand=True, pady=10)

    def restore_tool(self, tool_id):
        if not messagebox.askyesno("Confirm Restore", f"Are you sure you want to restore Tool PID: {tool_id}?"):
            return
        conn = get_connection()
        if not conn:
            return
        try:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE tool SET is_archived = 0 WHERE tool_id = %s", (tool_id,))
            conn.commit()

            uid = self.user_info.get("user_id")
            if uid:
                log_action(uid, "Edited", "Maintenance",
                           f"Restored Tool PID: {tool_id} from Archive")

            messagebox.showinfo(
                "Success", "Tool restored to active inventory.")
            self.load_archived_tools()
        except Exception as e:
            messagebox.showerror("Error", str(e))
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    # ------------------------------------------
    # TAB 3: Archived Employees
    # ------------------------------------------
    def render_employees_tab(self):
        frame = ctk.CTkFrame(
            self.tab_content, fg_color="white", corner_radius=10)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(20, 10))
        ctk.CTkLabel(top, text="Inactive / Archived Employees",
                     font=("Inter", 16, "bold"), text_color="#1A1A1A").pack(side="left")

        self._emp_scroll = ctk.CTkScrollableFrame(
            frame, fg_color="transparent")
        self._emp_scroll.pack(fill="both", expand=True, padx=20, pady=(5, 20))
        return frame

    def load_archived_employees(self):
        for w in self._emp_scroll.winfo_children():
            w.destroy()

        # Hard-Bounded Uniform Grid Setup
        table_inner = ctk.CTkFrame(self._emp_scroll, fg_color="transparent")
        table_inner.pack(fill="x", expand=True)

        headers = ["User ID", "Employee ID", "Full Name",
                   "Role", "Status", "Archived At", "Action"]
        weights = [1, 2, 3, 2, 2, 2, 1]
        min_sizes = [60, 100, 180, 100, 100, 150, 100]

        for col, (w, min_w) in enumerate(zip(weights, min_sizes)):
            table_inner.grid_columnconfigure(
                col, weight=w, minsize=min_w, uniform="emp_cols")

        for col, text in enumerate(headers):
            cell = ctk.CTkFrame(
                table_inner, fg_color="#1E4528", corner_radius=0)
            cell.grid(row=0, column=col, sticky="nsew", pady=(0, 2))
            lbl = ctk.CTkLabel(cell, text=text, font=(
                "Inter", 12, "bold"), text_color="white", anchor="center")
            lbl.pack(fill="both", expand=True, padx=2, pady=10)

        loading_lbl = ctk.CTkLabel(table_inner, text="↻ Loading archived employees... Please wait",
                                   text_color="gray", font=("Inter", 12, "italic"))
        loading_lbl.grid(row=1, column=0, columnspan=len(headers), pady=20)

        def _fetch():
            conn = get_connection()
            if not conn:
                self.after(0, lambda: loading_lbl.configure(text="Error: Could not connect to database.", text_color="red"))
                return
            try:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("""
                    SELECT user_id, employee_id, full_name, role, status, archived_at
                    FROM `user`
                    WHERE IFNULL(status, 'Inactive') != 'Active'
                    ORDER BY archived_at DESC, user_id DESC
                """)
                rows = cursor.fetchall()
                self.after(0, lambda: self._render_archived_employees(
                    rows, table_inner, loading_lbl, headers, min_sizes))
            except Exception as e:
                self.after(0, lambda err=e: loading_lbl.configure(
                    text=f"Error: {err}", text_color="red", wraplength=600))
            finally:
                if conn.is_connected():
                    cursor.close()
                    conn.close()

        import threading
        threading.Thread(target=_fetch, daemon=True).start()

    def _render_archived_employees(self, rows, table_inner, loading_lbl, headers, min_sizes):
        if not self.winfo_exists() or not table_inner.winfo_exists():
            return
        loading_lbl.destroy()

        if not rows:
            ctk.CTkLabel(
                table_inner, text="No archived employees found.", text_color="gray").grid(row=1, column=0, columnspan=len(headers), pady=20)
            return

        for i, row in enumerate(rows):
            status_display = row["status"] if row.get("status") else "Inactive"
            archived_at = row.get("archived_at")
            archived_display = archived_at.strftime(
                "%Y-%m-%d %H:%M:%S") if archived_at else "—"
            vals = [str(row["user_id"]), row["employee_id"], row["full_name"],
                    row["role"], status_display, archived_display]

            r_idx = i + 1
            bg = "#F9FAFB" if i % 2 == 0 else "white"

            for col, val in enumerate(vals):
                cell = ctk.CTkFrame(table_inner, fg_color=bg, corner_radius=0)
                cell.grid(row=r_idx, column=col, sticky="nsew")
                lbl = ctk.CTkLabel(cell, text=val, font=(
                    "Inter", 12), text_color="#1A1A1A", justify="center", anchor="center")
                lbl.configure(wraplength=min_sizes[col] - 10)
                lbl.pack(fill="both", expand=True, padx=4, pady=12)

            btn_cell = ctk.CTkFrame(table_inner, fg_color=bg, corner_radius=0)
            btn_cell.grid(row=r_idx, column=6, sticky="nsew")
            btn_f = ctk.CTkFrame(btn_cell, fg_color="transparent")
            btn_f.pack(expand=True)

            btn = ctk.CTkButton(btn_f, text="Restore", width=60, height=28, fg_color="#2980B9", hover_color="#1F618D", font=(
                "Inter", 11, "bold"), command=lambda r=row["user_id"]: self.restore_employee(r))
            btn.pack(expand=True, pady=10)

    def restore_employee(self, user_id):
        if not messagebox.askyesno("Confirm Restore", f"Restore employee access for User ID: {user_id}?"):
            return
        conn = get_connection()
        if not conn:
            return
        try:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE `user` SET status = 'Active', archived_at = NULL WHERE user_id = %s",
                (user_id,)
            )
            conn.commit()

            uid = self.user_info.get("user_id")
            if uid:
                log_action(uid, "Edited", "Maintenance",
                           f"Restored Employee UID: {user_id} from Archive")

            messagebox.showinfo("Success", "Employee access restored.")
            self.load_archived_employees()
        except Exception as e:
            messagebox.showerror("Error", str(e))
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    # ------------------------------------------
    # TAB 4: Archived Projects
    # ------------------------------------------
    def render_projects_tab(self):
        frame = ctk.CTkFrame(
            self.tab_content, fg_color="white", corner_radius=10)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(20, 10))
        ctk.CTkLabel(top, text="Completed / Archived Projects",
                     font=("Inter", 16, "bold"), text_color="#1A1A1A").pack(side="left")

        self._proj_scroll = ctk.CTkScrollableFrame(
            frame, fg_color="transparent")
        self._proj_scroll.pack(fill="both", expand=True, padx=20, pady=(5, 20))
        return frame

    def load_archived_projects(self):
        for w in self._proj_scroll.winfo_children():
            w.destroy()

        # Hard-Bounded Uniform Grid Setup
        table_inner = ctk.CTkFrame(self._proj_scroll, fg_color="transparent")
        table_inner.pack(fill="x", expand=True)

        headers = ["Project ID", "Project Name", "Client/Dept",
                   "Status", "End/Archived At", "Action"]
        weights = [1, 3, 2, 1, 2, 1]
        min_sizes = [70, 200, 150, 100, 150, 100]

        for col, (w, min_w) in enumerate(zip(weights, min_sizes)):
            table_inner.grid_columnconfigure(
                col, weight=w, minsize=min_w, uniform="proj_cols")

        for col, text in enumerate(headers):
            cell = ctk.CTkFrame(
                table_inner, fg_color="#1E4528", corner_radius=0)
            cell.grid(row=0, column=col, sticky="nsew", pady=(0, 2))
            lbl = ctk.CTkLabel(cell, text=text, font=(
                "Inter", 12, "bold"), text_color="white", anchor="center")
            lbl.pack(fill="both", expand=True, padx=2, pady=10)

        loading_lbl = ctk.CTkLabel(table_inner, text="↻ Loading archived projects... Please wait",
                                   text_color="gray", font=("Inter", 12, "italic"))
        loading_lbl.grid(row=1, column=0, columnspan=len(headers), pady=20)

        def _fetch():
            conn = get_connection()
            if not conn:
                self.after(0, lambda: loading_lbl.configure(text="Error: Could not connect to database.", text_color="red"))
                return
            try:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("""
                    SELECT project_id, name, client, status, end_date, archived_at
                    FROM projects
                    WHERE archived_at IS NOT NULL
                    ORDER BY archived_at DESC
                """)
                rows = cursor.fetchall()
                self.after(0, lambda: self._render_archived_projects(
                    rows, table_inner, loading_lbl, headers, min_sizes))
            except Exception as e:
                self.after(0, lambda err=e: loading_lbl.configure(
                    text=f"Error: {err}", text_color="red", wraplength=600))
            finally:
                if conn.is_connected():
                    cursor.close()
                    conn.close()

        import threading
        threading.Thread(target=_fetch, daemon=True).start()

    def _render_archived_projects(self, rows, table_inner, loading_lbl, headers, min_sizes):
        if not self.winfo_exists() or not table_inner.winfo_exists():
            return
        loading_lbl.destroy()

        if not rows:
            ctk.CTkLabel(table_inner, text="No archived projects found. Archive a Completed or Cancelled project from Project Management.",
                         text_color="gray", wraplength=600, justify="center").grid(row=1, column=0, columnspan=len(headers), pady=30)
            return

        for i, row in enumerate(rows):
            display_date = "—"
            if row.get("archived_at"):
                display_date = row["archived_at"].strftime("%Y-%m-%d %H:%M:%S")
            elif row.get("end_date"):
                display_date = row["end_date"].strftime("%Y-%m-%d")

            client_display = row.get("client") or "—"
            vals = [str(row["project_id"]), row["name"],
                    client_display, row["status"], display_date]

            r_idx = i + 1
            bg = "#F9FAFB" if i % 2 == 0 else "white"

            for col, val in enumerate(vals):
                cell = ctk.CTkFrame(table_inner, fg_color=bg, corner_radius=0)
                cell.grid(row=r_idx, column=col, sticky="nsew")
                lbl = ctk.CTkLabel(cell, text=val, font=(
                    "Inter", 12), text_color="#1A1A1A", justify="center", anchor="center")
                lbl.configure(wraplength=min_sizes[col] - 10)
                lbl.pack(fill="both", expand=True, padx=4, pady=12)

            btn_cell = ctk.CTkFrame(table_inner, fg_color=bg, corner_radius=0)
            btn_cell.grid(row=r_idx, column=5, sticky="nsew")
            btn_f = ctk.CTkFrame(btn_cell, fg_color="transparent")
            btn_f.pack(expand=True)

            btn = ctk.CTkButton(btn_f, text="Restore", width=60, height=28, fg_color="#2980B9", hover_color="#1F618D", font=(
                "Inter", 11, "bold"), command=lambda r=row["project_id"]: self.restore_project(r))
            btn.pack(expand=True, pady=10)

    def restore_project(self, project_id):
        if not messagebox.askyesno("Confirm Restore", f"Restore Project ID: {project_id} to Active status?"):
            return
        conn = get_connection()
        if not conn:
            return
        try:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE projects SET status = 'Approved', archived_at = NULL WHERE project_id = %s", (project_id,))
            conn.commit()

            uid = self.user_info.get("user_id")
            if uid:
                log_action(uid, "Edited", "Maintenance",
                           f"Restored Project ID: {project_id} from Archive")

            messagebox.showinfo(
                "Success", "Project marked as Approved and restored from archive.")
            self.load_archived_projects()
        except Exception as e:
            messagebox.showerror("Error", str(e))
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    # ------------------------------------------
    # TAB 5: Backup & Restore
    # ------------------------------------------
    def render_backup_tab(self):
        frame = ctk.CTkFrame(
            self.tab_content, fg_color="white", corner_radius=10)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        # --- Header ---
        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(20, 5))
        ctk.CTkLabel(top, text="Database Backup & Restore",
                     font=("Inter", 16, "bold"), text_color="#1A1A1A").pack(side="left")

        ctk.CTkLabel(frame,
                     text="Create verified backups of the entire champion_db database and restore from a "
                          "previous backup file (.sql). Always backup before making major system changes.",
                     font=("Inter", 11), text_color="gray",
                     wraplength=800, justify="left").pack(anchor="w", padx=20, pady=(0, 12))

        # --- Actions row: Backup card + Restore card side by side ---
        actions_row = ctk.CTkFrame(frame, fg_color="transparent")
        actions_row.pack(fill="x", padx=20, pady=(0, 12))
        actions_row.grid_columnconfigure(0, weight=1)
        actions_row.grid_columnconfigure(1, weight=1)

        # -- Backup Card --
        backup_card = ctk.CTkFrame(actions_row, fg_color="#F0FFF4", corner_radius=10,
                                   border_width=1, border_color="#A8D5BA")
        backup_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        ctk.CTkLabel(backup_card, text="💾  Create Backup",
                     font=("Inter", 13, "bold"), text_color="#1E4528").pack(anchor="w", padx=15, pady=(14, 4))
        ctk.CTkLabel(backup_card,
                     text="Exports the full database schema and all data to a .sql file.\n"
                          "The backup is saved to a folder of your choice.",
                     font=("Inter", 11), text_color="#333333",
                     wraplength=340, justify="left").pack(anchor="w", padx=15, pady=(0, 8))

        dest_row = ctk.CTkFrame(backup_card, fg_color="transparent")
        dest_row.pack(fill="x", padx=15, pady=(0, 8))
        ctk.CTkLabel(dest_row, text="Save to:", font=("Inter", 11, "bold"),
                     text_color="#1A1A1A").pack(side="left", padx=(0, 8))
        self._backup_dest_var = ctk.StringVar(
            value="(click Browse to choose folder)")
        dest_entry = ctk.CTkEntry(dest_row, textvariable=self._backup_dest_var,
                                  state="readonly", fg_color="#FFFFFF",
                                  text_color="#555555", width=180)
        dest_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(dest_row, text="Browse", width=70, height=28,
                      fg_color="#1E4528", hover_color="#14301C",
                      font=("Inter", 11, "bold"),
                      command=self._browse_backup_dest).pack(side="right")

        fname_row = ctk.CTkFrame(backup_card, fg_color="transparent")
        fname_row.pack(fill="x", padx=15, pady=(0, 4))
        ctk.CTkLabel(fname_row, text="File name (optional):", font=("Inter", 11, "bold"),
                     text_color="#1A1A1A").pack(side="left", padx=(0, 6))
        self._backup_fname_entry = ctk.CTkEntry(fname_row,
                                                placeholder_text="e.g., before_payroll_update  (no spaces/.sql needed)")
        self._backup_fname_entry.pack(side="left", fill="x", expand=True)

        note_row = ctk.CTkFrame(backup_card, fg_color="transparent")
        note_row.pack(fill="x", padx=15, pady=(0, 4))
        ctk.CTkLabel(note_row, text="Note (optional):", font=("Inter", 11, "bold"),
                     text_color="#1A1A1A").pack(side="left", padx=(0, 6))
        self._backup_note_entry = ctk.CTkEntry(note_row,
                                               placeholder_text="e.g., Before major update")
        self._backup_note_entry.pack(side="left", fill="x", expand=True)

        self._backup_btn = ctk.CTkButton(backup_card, text="⬇  Run Backup Now",
                                         fg_color="#1E4528", hover_color="#14301C",
                                         font=("Inter", 12, "bold"),
                                         command=self._run_backup)
        self._backup_btn.pack(fill="x", padx=15, pady=(8, 14))

        # -- Restore Card --
        restore_card = ctk.CTkFrame(actions_row, fg_color="#FFF8F0", corner_radius=10,
                                    border_width=1, border_color="#F5CBA7")
        restore_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        ctk.CTkLabel(restore_card, text="⬆  Restore from Backup",
                     font=("Inter", 13, "bold"), text_color="#C07A00").pack(anchor="w", padx=15, pady=(14, 4))
        ctk.CTkLabel(restore_card,
                     text="Restores the database from a selected .sql backup file.\n"
                          "⚠ WARNING: This will OVERWRITE all current data.",
                     font=("Inter", 11), text_color="#333333",
                     wraplength=340, justify="left").pack(anchor="w", padx=15, pady=(0, 8))

        src_row = ctk.CTkFrame(restore_card, fg_color="transparent")
        src_row.pack(fill="x", padx=15, pady=(0, 8))
        ctk.CTkLabel(src_row, text="File:", font=("Inter", 11, "bold"),
                     text_color="#1A1A1A").pack(side="left", padx=(0, 8))
        self._restore_src_var = ctk.StringVar(value="(no file selected)")
        src_entry = ctk.CTkEntry(src_row, textvariable=self._restore_src_var,
                                 state="readonly", fg_color="#FFFFFF",
                                 text_color="#555555", width=180)
        src_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(src_row, text="Browse", width=70, height=28,
                      fg_color="#C07A00", hover_color="#A06000",
                      font=("Inter", 11, "bold"),
                      command=self._browse_restore_file).pack(side="right")

        ctk.CTkLabel(restore_card,
                     text="Make sure you have a fresh backup before proceeding.",
                     font=("Inter", 10), text_color="gray",
                     wraplength=340, justify="left").pack(anchor="w", padx=15, pady=(0, 4))

        restore_note_row = ctk.CTkFrame(restore_card, fg_color="transparent")
        restore_note_row.pack(fill="x", padx=15, pady=(0, 4))
        ctk.CTkLabel(restore_note_row, text="Note (optional):", font=("Inter", 11, "bold"),
                     text_color="#1A1A1A").pack(side="left", padx=(0, 6))
        self._restore_note_entry = ctk.CTkEntry(restore_note_row,
                                                placeholder_text="e.g., Rolling back after failed update")
        self._restore_note_entry.pack(side="left", fill="x", expand=True)

        self._restore_btn = ctk.CTkButton(restore_card, text="⬆  Restore Database",
                                          fg_color="#C07A00", hover_color="#A06000",
                                          font=("Inter", 12, "bold"),
                                          command=self._run_restore)
        self._restore_btn.pack(fill="x", padx=15, pady=(8, 14))

        # --- Status bar ---
        self._backup_status_lbl = ctk.CTkLabel(frame, text="",
                                               font=("Inter", 11, "bold"),
                                               text_color="#1E4528")
        self._backup_status_lbl.pack(anchor="w", padx=20, pady=(0, 6))

        # --- Backup History Table ---
        hist_hdr = ctk.CTkFrame(frame, fg_color="transparent")
        hist_hdr.pack(fill="x", padx=20, pady=(4, 0))
        ctk.CTkLabel(hist_hdr, text="Backup History",
                     font=("Inter", 13, "bold"), text_color="#1A1A1A").pack(side="left")
        ctk.CTkButton(hist_hdr, text="↻ Refresh", width=80, height=28,
                      fg_color="#E0E0E0", text_color="black", hover_color="#CCCCCC",
                      font=("Inter", 11, "bold"),
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

    def _get_mysqldump_path(self):
        """Try to locate mysqldump. Checks common Windows MySQL install paths."""
        candidates = [
            "mysqldump",  # if on PATH
            r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe",
            r"C:\Program Files\MySQL\MySQL Server 5.7\bin\mysqldump.exe",
            r"C:\xampp\mysql\bin\mysqldump.exe",
            r"C:\wamp64\bin\mysql\mysql8.0\bin\mysqldump.exe",
            r"C:\wamp\bin\mysql\mysql8.0\bin\mysqldump.exe",
        ]
        for c in candidates:
            try:
                result = subprocess.run(
                    [c, "--version"], capture_output=True, timeout=5)
                if result.returncode == 0:
                    return c
            except Exception:
                continue
        return None

    def _get_mysql_path(self):
        """Try to locate mysql client. Same search logic as mysqldump."""
        candidates = [
            "mysql",
            r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe",
            r"C:\Program Files\MySQL\MySQL Server 5.7\bin\mysql.exe",
            r"C:\xampp\mysql\bin\mysql.exe",
            r"C:\wamp64\bin\mysql\mysql8.0\bin\mysql.exe",
            r"C:\wamp\bin\mysql\mysql8.0\bin\mysql.exe",
        ]
        for c in candidates:
            try:
                result = subprocess.run(
                    [c, "--version"], capture_output=True, timeout=5)
                if result.returncode == 0:
                    return c
            except Exception:
                continue
        return None

    def _get_db_config(self):
        """Pull DB credentials from environment (same as database.py)."""
        return {
            "host":   os.getenv("DB_HOST", "127.0.0.1"),
            "port":   os.getenv("DB_PORT", "3306"),
            "user":   os.getenv("DB_USER", "root"),
            "password": os.getenv("DB_PASS", ""),
            "db":     os.getenv("DB_NAME", "champion_db"),
        }

    def _ensure_backup_log_table(self):
        conn = get_connection()
        if not conn:
            return
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS backup_logs (
                    backup_id   INT AUTO_INCREMENT PRIMARY KEY,
                    filename    VARCHAR(255),
                    filepath    TEXT,
                    file_size   VARCHAR(50),
                    note        TEXT,
                    created_by  INT,
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status      VARCHAR(50) DEFAULT 'Success',
                    type        VARCHAR(20) DEFAULT 'Backup'
                )
            """)
            conn.commit()
            # Add 'type' column if table already existed without it
            cursor.execute("SHOW COLUMNS FROM backup_logs LIKE 'type'")
            has_type = cursor.fetchone() is not None
            cursor.fetchall()
            if not has_type:
                cursor.execute(
                    "ALTER TABLE backup_logs ADD COLUMN type VARCHAR(20) DEFAULT 'Backup'"
                )
            conn.commit()
        except Exception as e:
            print(f"[Backup] Table init warning: {e}")
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    def _run_backup(self):
        dest_folder = self._backup_dest_var.get().strip()
        if not dest_folder or dest_folder == "(click Browse to choose folder)":
            messagebox.showerror("No Destination",
                                 "Please choose a folder to save the backup.",
                                 parent=self.winfo_toplevel())
            return
        if not os.path.isdir(dest_folder):
            messagebox.showerror("Invalid Folder",
                                 "The selected destination folder does not exist.",
                                 parent=self.winfo_toplevel())
            return

        mysqldump = self._get_mysqldump_path()
        if not mysqldump:
            messagebox.showerror(
                "mysqldump Not Found",
                "Could not locate mysqldump.exe.\n\n"
                "Please add the MySQL bin folder to your system PATH, then retry.\n"
                "Example: C:\\Program Files\\MySQL\\MySQL Server 8.0\\bin",
                parent=self.winfo_toplevel()
            )
            return

        self._backup_btn.configure(state="disabled", text="⏳ Backing up...")
        self._backup_status_lbl.configure(text="⟳ Running backup, please wait...",
                                          text_color="#C07A00")
        self.update_idletasks()

        note = self._backup_note_entry.get().strip()
        custom_fname = self._backup_fname_entry.get().strip()

        def _do_backup():
            cfg = self._get_db_config()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            if custom_fname:
                # Sanitize: replace spaces with underscores, strip unsafe chars
                safe_name = "".join(
                    c if c.isalnum() or c in ("-", "_") else "_"
                    for c in custom_fname.replace(" ", "_")
                )
                filename = f"{safe_name}_{timestamp}.sql"
            else:
                filename = f"champion_db_backup_{timestamp}.sql"
            filepath = os.path.join(dest_folder, filename)

            try:
                cmd = [
                    mysqldump,
                    f"--host={cfg['host']}",
                    f"--port={cfg['port']}",
                    f"--user={cfg['user']}",
                    f"--password={cfg['password']}",
                    "--single-transaction",
                    "--routines",
                    "--triggers",
                    "--set-gtid-purged=OFF",
                    cfg["db"],
                ]
                with open(filepath, "w", encoding="utf-8") as f:
                    result = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE,
                                            timeout=120)

                if result.returncode != 0:
                    err_msg = result.stderr.decode(
                        "utf-8", errors="replace").strip()
                    # mysqldump prints password warning to stderr but still succeeds;
                    # only treat it as a real error if the file is empty/tiny.
                    if os.path.getsize(filepath) < 512:
                        raise RuntimeError(f"mysqldump error: {err_msg}")

                # Compute human-readable file size
                size_bytes = os.path.getsize(filepath)
                if size_bytes >= 1_048_576:
                    size_str = f"{size_bytes / 1_048_576:.2f} MB"
                elif size_bytes >= 1024:
                    size_str = f"{size_bytes / 1024:.1f} KB"
                else:
                    size_str = f"{size_bytes} B"

                # Log to DB
                self._ensure_backup_log_table()
                conn = get_connection()
                if conn:
                    try:
                        cursor = conn.cursor()
                        uid = self.user_info.get("user_id")
                        cursor.execute("""
                            INSERT INTO backup_logs
                                (filename, filepath, file_size, note, created_by, status, type)
                            VALUES (%s, %s, %s, %s, %s, 'Success', 'Backup')
                        """, (filename, filepath, size_str, note or None, uid))
                        conn.commit()
                        if uid:
                            log_action(uid, "Backup", "Maintenance",
                                       f"Database backup created: {filename} ({size_str})")
                    except Exception:
                        pass
                    finally:
                        if conn.is_connected():
                            cursor.close()
                            conn.close()

                self.after(0, lambda: self._on_backup_done(
                    True, filepath, size_str))

            except Exception as e:
                # Log failure
                self._ensure_backup_log_table()
                conn2 = get_connection()
                if conn2:
                    try:
                        cursor2 = conn2.cursor()
                        uid = self.user_info.get("user_id")
                        cursor2.execute("""
                            INSERT INTO backup_logs
                                (filename, filepath, file_size, note, created_by, status, type)
                            VALUES (%s, %s, %s, %s, %s, 'Failed', 'Backup')
                        """, (filename, filepath, "—", note or None, uid))
                        conn2.commit()
                    except Exception:
                        pass
                    finally:
                        if conn2.is_connected():
                            cursor2.close()
                            conn2.close()
                self.after(0, lambda err=e: self._on_backup_done(
                    False, None, None, str(err)))

        threading.Thread(target=_do_backup, daemon=True).start()

    def _on_backup_done(self, success, filepath, size_str, error_msg=None):
        self._backup_btn.configure(state="normal", text="⬇  Run Backup Now")
        if success:
            self._backup_status_lbl.configure(
                text=f"✓ Backup complete! Saved: {os.path.basename(filepath)}  ({size_str})",
                text_color="#1E4528"
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
                text_color="#D8000C"
            )
            messagebox.showerror(
                "Backup Failed",
                f"The backup could not be completed.\n\nDetails:\n{error_msg}",
                parent=self.winfo_toplevel()
            )

    def _run_restore(self):
        src_file = self._restore_src_var.get().strip()
        if not src_file or src_file == "(no file selected)":
            messagebox.showerror("No File Selected",
                                 "Please select a .sql backup file to restore from.",
                                 parent=self.winfo_toplevel())
            return
        if not os.path.isfile(src_file):
            messagebox.showerror("File Not Found",
                                 "The selected backup file no longer exists.",
                                 parent=self.winfo_toplevel())
            return

        mysql_client = self._get_mysql_path()
        if not mysql_client:
            messagebox.showerror(
                "mysql Not Found",
                "Could not locate the mysql client executable.\n\n"
                "Please add the MySQL bin folder to your system PATH, then retry.",
                parent=self.winfo_toplevel()
            )
            return

        confirmed = messagebox.askyesno(
            "⚠ Confirm Restore",
            f"This will OVERWRITE all current data in the database with the contents of:\n\n"
            f"{os.path.basename(src_file)}\n\n"
            "This action CANNOT be undone.\n\n"
            "Are you absolutely sure you want to proceed?",
            parent=self.winfo_toplevel()
        )
        if not confirmed:
            return

        self._restore_btn.configure(state="disabled", text="⏳ Restoring...")
        self._backup_status_lbl.configure(text="⟳ Restoring database, please wait...",
                                          text_color="#C07A00")
        self.update_idletasks()

        restore_note = self._restore_note_entry.get().strip()

        # Snapshot existing backup history BEFORE restore wipes the table
        existing_logs = []
        try:
            self._ensure_backup_log_table()
            _snap_conn = get_connection()
            if _snap_conn:
                try:
                    _snap_cur = _snap_conn.cursor(dictionary=True)
                    _snap_cur.execute("""
                        SELECT filename, filepath, file_size, note,
                               created_by, created_at, status, type
                        FROM backup_logs
                        ORDER BY created_at ASC
                    """)
                    existing_logs = _snap_cur.fetchall()
                except Exception:
                    existing_logs = []
                finally:
                    if _snap_conn.is_connected():
                        _snap_cur.close()
                        _snap_conn.close()
        except Exception:
            existing_logs = []

        def _do_restore():
            cfg = self._get_db_config()
            src_basename = os.path.basename(src_file)
            uid = self.user_info.get("user_id")
            try:
                cmd = [
                    mysql_client,
                    f"--host={cfg['host']}",
                    f"--port={cfg['port']}",
                    f"--user={cfg['user']}",
                    f"--password={cfg['password']}",
                    cfg["db"],
                ]
                with open(src_file, "r", encoding="utf-8") as f:
                    result = subprocess.run(cmd, stdin=f, stderr=subprocess.PIPE,
                                            timeout=300)

                if result.returncode != 0:
                    err_msg = result.stderr.decode(
                        "utf-8", errors="replace").strip()
                    # Ignore password warning on stderr if exit code is still 0
                    if result.returncode != 0:
                        raise RuntimeError(f"mysql restore error: {err_msg}")

                # Restore wiped backup_logs — rebuild the table and re-insert all
                # previous history rows plus this new restore entry.
                # Truncate first because the restored SQL may already contain old rows.
                self._ensure_backup_log_table()
                conn_log = get_connection()
                if conn_log:
                    try:
                        cursor_log = conn_log.cursor()
                        cursor_log.execute("TRUNCATE TABLE backup_logs")
                        # Re-insert all pre-restore history rows
                        for old_row in existing_logs:
                            cursor_log.execute("""
                                INSERT INTO backup_logs
                                    (filename, filepath, file_size, note,
                                     created_by, created_at, status, type)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            """, (
                                old_row["filename"],
                                old_row["filepath"],
                                old_row["file_size"],
                                old_row["note"],
                                old_row["created_by"],
                                old_row["created_at"],
                                old_row["status"],
                                old_row.get("type") or "Backup",
                            ))
                        # Insert new restore entry
                        cursor_log.execute("""
                            INSERT INTO backup_logs
                                (filename, filepath, file_size, note, created_by, status, type)
                            VALUES (%s, %s, %s, %s, %s, 'Success', 'Restore')
                        """, (src_basename, src_file, "—",
                              restore_note or None, uid))
                        conn_log.commit()
                        if uid:
                            log_action(uid, "Restore", "Maintenance",
                                       f"Database restored from backup: {src_basename}")
                    except Exception:
                        pass
                    finally:
                        if conn_log.is_connected():
                            cursor_log.close()
                            conn_log.close()

                self.after(0, lambda: self._on_restore_done(True))

            except Exception as e:
                self.after(
                    0, lambda err=e: self._on_restore_done(False, str(err)))

        threading.Thread(target=_do_restore, daemon=True).start()

    def _on_restore_done(self, success, error_msg=None):
        self._restore_btn.configure(state="normal", text="⬆  Restore Database")
        if success:
            self._backup_status_lbl.configure(
                text="✓ Restore complete! Database has been overwritten from the backup file.",
                text_color="#1E4528"
            )
            messagebox.showinfo(
                "Restore Successful",
                "The database has been successfully restored from the backup file.\n\n"
                "Please restart the application to ensure all modules reflect the restored data.",
                parent=self.winfo_toplevel()
            )
            self._restore_src_var.set("(no file selected)")
            self._restore_note_entry.delete(0, "end")
            self.load_backup_history()
        else:
            self._backup_status_lbl.configure(
                text="✗ Restore failed. See error details.",
                text_color="#D8000C"
            )
            messagebox.showerror(
                "Restore Failed",
                f"The restore could not be completed.\n\nDetails:\n{error_msg}",
                parent=self.winfo_toplevel()
            )

    def load_backup_history(self):
        if not hasattr(self, "_backup_hist_scroll"):
            return
        for w in self._backup_hist_scroll.winfo_children():
            w.destroy()

        self._ensure_backup_log_table()

        table_inner = ctk.CTkFrame(
            self._backup_hist_scroll, fg_color="transparent")
        table_inner.pack(fill="x", expand=True)

        headers = ["#", "Type", "Filename", "File Size", "Note",
                   "Created By", "Date & Time", "Status"]
        weights = [1, 1, 4, 1, 3, 2, 3, 1]
        min_sizes = [40, 80, 200, 80, 160, 120, 160, 80]

        for col, (w, min_w) in enumerate(zip(weights, min_sizes)):
            table_inner.grid_columnconfigure(
                col, weight=w, minsize=min_w, uniform="bk_cols")

        for col, text in enumerate(headers):
            cell = ctk.CTkFrame(
                table_inner, fg_color="#1E4528", corner_radius=0)
            cell.grid(row=0, column=col, sticky="nsew", pady=(0, 2))
            lbl = ctk.CTkLabel(cell, text=text, font=("Inter", 12, "bold"),
                               text_color="white", anchor="center")
            lbl.pack(fill="both", expand=True, padx=2, pady=10)

        loading_lbl = ctk.CTkLabel(table_inner,
                                   text="↻ Loading backup history...",
                                   text_color="gray", font=("Inter", 12, "italic"))
        loading_lbl.grid(row=1, column=0, columnspan=len(headers), pady=20)

        def _fetch():
            conn = get_connection()
            if not conn:
                self.after(0, lambda: loading_lbl.configure(text="Error: Could not connect to database.", text_color="red"))
                return
            try:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("""
                    SELECT bl.backup_id, IFNULL(bl.type, 'Backup') as type,
                           bl.filename, bl.file_size,
                           IFNULL(bl.note, '—') as note,
                           IFNULL(u.full_name, 'System') as created_by,
                           bl.created_at,
                           bl.status, bl.filepath
                    FROM backup_logs bl
                    LEFT JOIN `user` u ON bl.created_by = u.user_id
                    ORDER BY bl.created_at DESC
                    LIMIT 50
                """)
                rows = cursor.fetchall()
                self.after(0, lambda: self._render_backup_history(
                    rows, table_inner, loading_lbl, headers, min_sizes))
            except Exception as e:
                self.after(0, lambda err=e: loading_lbl.configure(
                    text=f"Error: {err}", text_color="red", wraplength=600))
            finally:
                if conn.is_connected():
                    cursor.close()
                    conn.close()

        threading.Thread(target=_fetch, daemon=True).start()

    def _render_backup_history(self, rows, table_inner, loading_lbl, headers, min_sizes):
        if not self.winfo_exists() or not table_inner.winfo_exists():
            return
        loading_lbl.destroy()

        if not rows:
            ctk.CTkLabel(table_inner,
                         text="No backup records found. Create your first backup above.",
                         text_color="gray").grid(
                row=1, column=0, columnspan=len(headers), pady=20)
            return

        for i, row in enumerate(rows):
            status_ok = row["status"] == "Success"
            entry_type = row.get("type") or "Backup"

            # Format datetime in Python to avoid DATE_FORMAT driver inconsistencies
            raw_dt = row["created_at"]
            if hasattr(raw_dt, "strftime"):
                created_at_str = raw_dt.strftime("%b %d, %Y %I:%M %p")
            else:
                created_at_str = str(raw_dt) if raw_dt else "—"

            vals = [
                str(len(rows) - i),
                entry_type,
                row["filename"],
                row["file_size"],
                row["note"],
                row["created_by"],
                created_at_str,
                row["status"],
            ]
            bg = "#F0FFF4" if status_ok else "#FFF5F5"
            r_idx = i + 1

            for col, val in enumerate(vals):
                cell = ctk.CTkFrame(table_inner, fg_color=bg, corner_radius=0)
                cell.grid(row=r_idx, column=col, sticky="nsew")

                txt_col = "#1A1A1A"
                font_w = "normal"
                if col == 1:  # Type
                    txt_col = "#1E4528" if entry_type == "Backup" else "#C07A00"
                    font_w = "bold"
                elif col == 7:  # Status
                    txt_col = "#1E4528" if status_ok else "#D8000C"
                    font_w = "bold"

                lbl = ctk.CTkLabel(cell, text=val,
                                   font=("Inter", 12, font_w),
                                   text_color=txt_col,
                                   justify="center", anchor="center")
                lbl.configure(wraplength=min_sizes[col] - 10)
                lbl.pack(fill="both", expand=True, padx=4, pady=10)
