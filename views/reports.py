import customtkinter as ctk
from tkinter import messagebox
from database import get_connection
import os
import tempfile
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime


class ReportsView(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color="transparent")

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)

        self.build_ui()

    def build_ui(self):
        top_bar = ctk.CTkFrame(self, fg_color="transparent")
        top_bar.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        ctk.CTkLabel(top_bar, text="Reports", font=("Inter", 16, "bold"),
                     text_color="#1E4528").pack(side="left")

        self.tab_var = ctk.StringVar(value="Inventory ABC Analysis")
        self.seg_btn = ctk.CTkSegmentedButton(
            top_bar,
            values=["Inventory ABC Analysis", "Tool Usage Report", "Employee Activity"],
            variable=self.tab_var,
            fg_color="#F0F0F0",
            selected_color="#1E4528",
            selected_hover_color="#14301C",
            font=("Inter", 12, "bold"),
            command=self.switch_tab
        )
        self.seg_btn.pack(side="right")

        self.tab_content = ctk.CTkFrame(self, fg_color="transparent")
        self.tab_content.grid(row=1, column=0, sticky="nsew")
        self.tab_content.grid_columnconfigure(0, weight=1)
        self.tab_content.grid_rowconfigure(0, weight=1)

        self.render_abc_tab()

    def switch_tab(self, selected):
        for widget in self.tab_content.winfo_children():
            widget.destroy()

        if selected == "Inventory ABC Analysis":
            self.render_abc_tab()
        elif selected == "Tool Usage Report":
            self.render_usage_tab()
        elif selected == "Employee Activity":
            self.render_activity_tab()

    # ==========================================
    # TAB 1: ABC Analysis 
    # ==========================================
    def render_abc_tab(self):
        frame = ctk.CTkFrame(
            self.tab_content, fg_color="white", corner_radius=10)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.pack(fill="x", padx=30, pady=(20, 5))

        ctk.CTkLabel(top, text="Inventory Analytics (ABC Analysis)",
                     font=("Inter", 20, "bold"), text_color="#1E4528").pack(side="left")
        ctk.CTkButton(top, text="⎙ Export PDF", width=110,
                      fg_color="#1E4528", hover_color="#14301C",
                      font=("Inter", 11, "bold"),
                      command=lambda: self.open_export_dialog("abc")).pack(side="right")

        ctk.CTkLabel(frame,
                     text="Algorithm dynamically categorizes tools based on the Pareto Principle (80/20 usage).",
                     font=("Inter", 12), text_color="gray").pack(anchor="w", padx=30, pady=(0, 20))

        self._abc_scroll = ctk.CTkScrollableFrame(
            frame, fg_color="transparent")
        self._abc_scroll.pack(fill="both", expand=True, padx=30, pady=(10, 30))

        self.run_abc_algorithm()

    def run_abc_algorithm(self):
        """Implements Figure 96 (ABC Inventory Categorization)"""
        scroll = self._abc_scroll
        for w in scroll.winfo_children():
            w.destroy()

        # Hard-Bounded Uniform Grid Setup
        table_inner = ctk.CTkFrame(scroll, fg_color="transparent")
        table_inner.pack(fill="x", expand=True)

        headers = ["Rank", "Tool ID", "Tool Name", "Times Borrowed", "Cumulative %", "ABC Category"]
        weights = [1, 2, 5, 2, 2, 3]
        min_sizes = [50, 80, 200, 120, 120, 140]

        for col, (w, min_w) in enumerate(zip(weights, min_sizes)):
            table_inner.grid_columnconfigure(col, weight=w, minsize=min_w, uniform="abc_cols")

        for col, text in enumerate(headers):
            cell = ctk.CTkFrame(table_inner, fg_color="#1E4528", corner_radius=0)
            cell.grid(row=0, column=col, sticky="nsew", pady=(0, 2))
            lbl = ctk.CTkLabel(cell, text=text, font=("Inter", 11, "bold"), text_color="white", anchor="center")
            lbl.pack(fill="both", expand=True, padx=2, pady=10)

        conn = get_connection()
        if not conn:
            return
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT t.tool_id, t.name, COUNT(tr.transaction_id) as usage_count
                FROM tool t
                LEFT JOIN transaction tr ON t.tool_id = tr.tool_id AND tr.type = 'Issue'
                WHERE t.is_archived = 0
                GROUP BY t.tool_id, t.name
                ORDER BY usage_count DESC
            """)
            tools = cursor.fetchall()

            total_usage = sum(t['usage_count'] for t in tools) or 1
            cumulative = 0

            self._abc_data = []

            for i, tool in enumerate(tools):
                cumulative += tool['usage_count']
                cum_pct = (cumulative / total_usage) * 100

                if cum_pct <= 70:
                    category = "A (High Priority)"
                    color = "#2ECC71"
                elif cum_pct <= 90:
                    category = "B (Medium Priority)"
                    color = "#F1C40F"
                else:
                    category = "C (Low Priority)"
                    color = "#E74C3C"

                self._abc_data.append({
                    "rank": f"#{i+1}",
                    "tool_id": str(tool['tool_id']),
                    "name": tool['name'],
                    "usage": str(tool['usage_count']),
                    "cum_pct": f"{cum_pct:.1f}%",
                    "category": category,
                })

                display_data = [f"#{i+1}", str(tool['tool_id']), tool['name'],
                                str(tool['usage_count']), f"{cum_pct:.1f}%", category]

                r_idx = i + 1
                bg = "#F9FAFB" if i % 2 == 0 else "white"

                for col, val in enumerate(display_data):
                    cell = ctk.CTkFrame(table_inner, fg_color=bg, corner_radius=0)
                    cell.grid(row=r_idx, column=col, sticky="nsew")

                    txt_col = color if col == 5 else "#1A1A1A"
                    font_w = "bold" if col == 5 else "normal"

                    lbl = ctk.CTkLabel(cell, text=val, font=("Inter", 11, font_w), text_color=txt_col, justify="center", anchor="center")
                    
                    lbl.configure(wraplength=min_sizes[col] - 10)
                    lbl.configure(wraplength=min_sizes[col] - 10)
                    lbl.configure(wraplength=min_sizes[col] - 10)
                    lbl.pack(fill="both", expand=True, padx=4, pady=12)

        except Exception as e:
            ctk.CTkLabel(
                scroll, text=f"Error: {e}", text_color="red").pack(pady=10)
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    # ==========================================
    # TAB 2: Tool Usage Report
    # ==========================================
    def render_usage_tab(self):
        frame = ctk.CTkFrame(
            self.tab_content, fg_color="white", corner_radius=10)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.pack(fill="x", padx=30, pady=(20, 5))

        ctk.CTkLabel(top, text="Tool Usage Report",
                     font=("Inter", 20, "bold"), text_color="#1E4528").pack(side="left")
        ctk.CTkButton(top, text="⎙ Export PDF", width=110,
                      fg_color="#1E4528", hover_color="#14301C",
                      font=("Inter", 11, "bold"),
                      command=lambda: self.open_export_dialog("usage")).pack(side="right")

        ctk.CTkLabel(frame,
                     text="Summary of all tool transactions, availability, and condition status.",
                     font=("Inter", 12), text_color="gray").pack(anchor="w", padx=30, pady=(0, 15))

        scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=30, pady=(10, 30))

        # Hard-Bounded Uniform Grid Setup
        table_inner = ctk.CTkFrame(scroll, fg_color="transparent")
        table_inner.pack(fill="x", expand=True)

        headers = ["Tool ID", "Tool Name", "Tag ID", "Total Borrowed", "Currently Out", "Qty Avail", "Condition"]
        weights = [2, 5, 2, 2, 2, 2, 2]
        min_sizes = [80, 200, 100, 120, 120, 100, 100]

        for col, (w, min_w) in enumerate(zip(weights, min_sizes)):
            table_inner.grid_columnconfigure(col, weight=w, minsize=min_w, uniform="usage_cols")

        for col, text in enumerate(headers):
            cell = ctk.CTkFrame(table_inner, fg_color="#1E4528", corner_radius=0)
            cell.grid(row=0, column=col, sticky="nsew", pady=(0, 2))
            lbl = ctk.CTkLabel(cell, text=text, font=("Inter", 11, "bold"), text_color="white", anchor="center")
            lbl.pack(fill="both", expand=True, padx=2, pady=10)

        self._usage_data = []

        conn = get_connection()
        if not conn:
            return
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT t.tool_id, t.name,
                       IFNULL(t.tag_id,'Unassigned') as tag_id,
                       COUNT(tr.transaction_id) as total_borrowed,
                       SUM(CASE WHEN tr.status='Active' THEN 1 ELSE 0 END) as currently_out,
                       IFNULL(i.quantity_available,0) as qty_avail,
                       t.`condition`
                FROM tool t
                LEFT JOIN transaction tr ON t.tool_id = tr.tool_id AND tr.type='Issue'
                LEFT JOIN inventory i ON t.tool_id = i.tool_id
                WHERE t.is_archived = 0
                GROUP BY t.tool_id, t.name, t.tag_id, i.quantity_available, t.`condition`
                ORDER BY total_borrowed DESC
            """)
            rows = cursor.fetchall()

            for i, row in enumerate(rows):
                vals = [
                    str(row['tool_id']),
                    row['name'],
                    row['tag_id'],
                    str(row['total_borrowed']),
                    str(row['currently_out'] or 0),
                    str(row['qty_avail']),
                    row['condition'],
                ]
                self._usage_data.append(vals)

                r_idx = i + 1
                bg = "#F9FAFB" if i % 2 == 0 else "white"

                for col, val in enumerate(vals):
                    cell = ctk.CTkFrame(table_inner, fg_color=bg, corner_radius=0)
                    cell.grid(row=r_idx, column=col, sticky="nsew")

                    txt_col = "#1A1A1A"
                    if col == 6:
                        txt_col = "#2ECC71" if val == "Good" else "#D8000C"
                    elif col == 2 and val == "Unassigned":
                        txt_col = "#D8000C"

                    font_w = "bold" if (col == 6 or (col == 2 and val == "Unassigned")) else "normal"

                    lbl = ctk.CTkLabel(cell, text=val, font=("Inter", 11, font_w), text_color=txt_col, justify="center", anchor="center")
                    
                    def set_wrap(e, l=lbl, m=min_sizes[col]):
                        target_wrap = max(m - 10, e.width - 10)
                        if not hasattr(l, '_last_wrap') or abs(l._last_wrap - target_wrap) > 5:
                            l.configure(wraplength=target_wrap)
                            l._last_wrap = target_wrap
                    cell.bind("<Configure>", set_wrap)

                    lbl.pack(fill="both", expand=True, padx=4, pady=12)

        except Exception as e:
            ctk.CTkLabel(
                scroll, text=f"Error: {e}", text_color="red").pack(pady=10)
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    # ==========================================
    # TAB 3: Employee Activity Report
    # ==========================================
    def render_activity_tab(self):
        frame = ctk.CTkFrame(
            self.tab_content, fg_color="white", corner_radius=10)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.pack(fill="x", padx=30, pady=(20, 5))

        ctk.CTkLabel(top, text="Employee Activity Report",
                     font=("Inter", 20, "bold"), text_color="#1E4528").pack(side="left")
        ctk.CTkButton(top, text="⎙ Export PDF", width=110,
                      fg_color="#1E4528", hover_color="#14301C",
                      font=("Inter", 11, "bold"),
                      command=lambda: self.open_export_dialog("activity")).pack(side="right")

        ctk.CTkLabel(frame,
                     text="Aggregated borrowing activity per employee for accountability monitoring.",
                     font=("Inter", 12), text_color="gray").pack(anchor="w", padx=30, pady=(0, 15))

        scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=30, pady=(10, 30))

        # Hard-Bounded Uniform Grid Setup
        table_inner = ctk.CTkFrame(scroll, fg_color="transparent")
        table_inner.pack(fill="x", expand=True)

        headers = ["Employee ID", "Full Name", "Role", "Total Borrows", "Currently Active", "Total Returned"]
        weights = [2, 4, 2, 2, 2, 2]
        min_sizes = [100, 180, 100, 120, 120, 120]

        for col, (w, min_w) in enumerate(zip(weights, min_sizes)):
            table_inner.grid_columnconfigure(col, weight=w, minsize=min_w, uniform="activity_cols")

        for col, text in enumerate(headers):
            cell = ctk.CTkFrame(table_inner, fg_color="#1E4528", corner_radius=0)
            cell.grid(row=0, column=col, sticky="nsew", pady=(0, 2))
            lbl = ctk.CTkLabel(cell, text=text, font=("Inter", 11, "bold"), text_color="white", anchor="center")
            lbl.pack(fill="both", expand=True, padx=2, pady=10)

        self._activity_data = []

        conn = get_connection()
        if not conn:
            return
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT u.employee_id, u.full_name, u.role,
                       COUNT(tr.transaction_id) as total_borrows,
                       SUM(CASE WHEN tr.status='Active' THEN 1 ELSE 0 END) as active_borrows,
                       SUM(CASE WHEN tr.status='Returned' THEN 1 ELSE 0 END) as total_returned
                FROM user u
                LEFT JOIN transaction tr ON u.user_id = tr.user_id AND tr.type = 'Issue'
                GROUP BY u.user_id, u.employee_id, u.full_name, u.role
                ORDER BY total_borrows DESC
            """)
            rows = cursor.fetchall()

            for i, row in enumerate(rows):
                vals = [
                    row['employee_id'],
                    row['full_name'],
                    row['role'],
                    str(row['total_borrows']),
                    str(row['active_borrows'] or 0),
                    str(row['total_returned'] or 0),
                ]
                self._activity_data.append(vals)

                r_idx = i + 1
                bg = "#F9FAFB" if i % 2 == 0 else "white"

                for col, val in enumerate(vals):
                    cell = ctk.CTkFrame(table_inner, fg_color=bg, corner_radius=0)
                    cell.grid(row=r_idx, column=col, sticky="nsew")

                    txt_col = "#1A1A1A"
                    if col == 4 and int(val) > 0:
                        txt_col = "#D8000C"
                        
                    font_w = "bold" if col == 4 and int(val) > 0 else "normal"

                    lbl = ctk.CTkLabel(cell, text=val, font=("Inter", 11, font_w), text_color=txt_col, justify="center", anchor="center")
                    
                    def set_wrap(e, l=lbl, m=min_sizes[col]):
                        target_wrap = max(m - 10, e.width - 10)
                        if not hasattr(l, '_last_wrap') or abs(l._last_wrap - target_wrap) > 5:
                            l.configure(wraplength=target_wrap)
                            l._last_wrap = target_wrap
                    cell.bind("<Configure>", set_wrap)

                    lbl.pack(fill="both", expand=True, padx=4, pady=12)

        except Exception as e:
            ctk.CTkLabel(
                scroll, text=f"Error: {e}", text_color="red").pack(pady=10)
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    # ==========================================
    # PDF Export Dialog (date range popup)
    # ==========================================
    def open_export_dialog(self, report_type):
        report_titles = {
            "abc": "Inventory ABC Analysis Report",
            "usage": "Tool Usage Report",
            "activity": "Employee Activity Report",
        }
        title = report_titles.get(report_type, "Report")

        dialog = ctk.CTkToplevel(self)
        dialog.title(f"Export: {title}")
        dialog.geometry("460x420")
        dialog.configure(fg_color="#F4F6F8")
        dialog.attributes("-topmost", True)
        dialog.grab_set()
        dialog.resizable(False, False)
        dialog.update_idletasks()
        sw, sh = dialog.winfo_screenwidth(), dialog.winfo_screenheight()
        dialog.geometry(f"460x420+{(sw-460)//2}+{(sh-420)//2}")

        card = ctk.CTkFrame(dialog, fg_color="white", corner_radius=10,
                            border_width=1, border_color="#E0E0E0")
        card.pack(padx=20, pady=20, fill="both", expand=True)

        ctk.CTkLabel(card, text="Export Report",
                     font=("Inter", 16, "bold"), text_color="#1A1A1A").pack(anchor="w", padx=20, pady=(18, 2))
        ctk.CTkLabel(card, text=title,
                     font=("Inter", 12), text_color="#1E4528").pack(anchor="w", padx=20, pady=(0, 12))

        ctk.CTkFrame(card, height=1, fg_color="#E0E0E0").pack(fill="x", padx=20, pady=(0, 12))

        ctk.CTkLabel(card, text="Date Range  (optional — leave blank for all records)",
                     font=("Inter", 11, "bold"), text_color="#555555").pack(anchor="w", padx=20, pady=(0, 6))

        dates_row = ctk.CTkFrame(card, fg_color="transparent")
        dates_row.pack(fill="x", padx=20, pady=(0, 10))
        dates_row.grid_columnconfigure(0, weight=1)
        dates_row.grid_columnconfigure(1, weight=1)

        start_f = ctk.CTkFrame(dates_row, fg_color="transparent")
        start_f.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ctk.CTkLabel(start_f, text="From Date", font=("Inter", 11), text_color="gray").pack(anchor="w")
        start_entry = ctk.CTkEntry(start_f, placeholder_text="YYYY-MM-DD")
        start_entry.pack(fill="x", pady=(4, 0))

        end_f = ctk.CTkFrame(dates_row, fg_color="transparent")
        end_f.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        ctk.CTkLabel(end_f, text="To Date", font=("Inter", 11), text_color="gray").pack(anchor="w")
        end_entry = ctk.CTkEntry(end_f, placeholder_text="YYYY-MM-DD")
        end_entry.pack(fill="x", pady=(4, 0))

        ctk.CTkLabel(card, text="Additional Criteria / Notes  (optional)",
                     font=("Inter", 11, "bold"), text_color="#555555").pack(anchor="w", padx=20, pady=(4, 4))
        notes_entry = ctk.CTkEntry(card, placeholder_text="e.g., Site A only, Q1 review...")
        notes_entry.pack(fill="x", padx=20, pady=(0, 16))

        def _validate_date(val, label):
            if not val:
                return True
            try:
                datetime.strptime(val, "%Y-%m-%d")
                return True
            except ValueError:
                messagebox.showerror("Invalid Date",
                                     f"{label} must be in YYYY-MM-DD format.", parent=dialog)
                return False

        def do_export():
            sd = start_entry.get().strip()
            ed = end_entry.get().strip()
            note = notes_entry.get().strip()
            if not _validate_date(sd, "From Date"):
                return
            if not _validate_date(ed, "To Date"):
                return
            dialog.destroy()
            self.export_pdf(report_type,
                            start_date=sd or None,
                            end_date=ed or None,
                            criteria_note=note or None)

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 16))
        ctk.CTkButton(btn_row, text="⎙ Export Now", fg_color="#1E4528", hover_color="#14301C",
                      font=("Inter", 12, "bold"), command=do_export).pack(side="left", expand=True, fill="x", padx=(0, 8))
        ctk.CTkButton(btn_row, text="Cancel", width=90, fg_color="#E0E0E0",
                      text_color="black", hover_color="#CCCCCC",
                      command=dialog.destroy).pack(side="right")

        start_entry.focus_set()
        start_entry.bind("<Return>", lambda e: end_entry.focus_set())
        end_entry.bind("<Return>", lambda e: notes_entry.focus_set())
        notes_entry.bind("<Return>", lambda e: do_export())

    # ==========================================
    # PDF Export (shared across all tabs)
    # ==========================================
    def export_pdf(self, report_type, start_date=None, end_date=None, criteria_note=None):
        try:
            canvas_width = 900
            line_h = 28
            timestamp = datetime.now().strftime("%B %d, %Y %I:%M %p")

            # Build date range label for PDF
            if start_date and end_date:
                date_range_label = f"{start_date}  to  {end_date}"
            elif start_date:
                date_range_label = f"From {start_date}"
            elif end_date:
                date_range_label = f"Up to {end_date}"
            else:
                date_range_label = "All records (no date filter)"

            # Re-query with date filter if dates provided
            conn = get_connection() if (start_date or end_date) else None

            if report_type == "abc":
                title = "Inventory ABC Analysis Report"
                col_labels = ["Rank", "Tool ID", "Tool Name",
                              "Times Borrowed", "Cumulative%", "Category"]
                if conn:
                    try:
                        cursor = conn.cursor(dictionary=True)
                        params = []
                        date_filter = ""
                        if start_date:
                            date_filter += " AND tr.borrow_date >= %s"
                            params.append(start_date)
                        if end_date:
                            date_filter += " AND tr.borrow_date <= %s"
                            params.append(end_date + " 23:59:59")
                        cursor.execute(f"""
                            SELECT t.tool_id, t.name, COUNT(tr.transaction_id) as usage_count
                            FROM tool t
                            LEFT JOIN transaction tr ON t.tool_id = tr.tool_id AND tr.type = 'Issue' {date_filter}
                            WHERE t.is_archived = 0
                            GROUP BY t.tool_id, t.name
                            ORDER BY usage_count DESC
                        """, params)
                        tools = cursor.fetchall()
                        total_usage = sum(t['usage_count'] for t in tools) or 1
                        cumulative = 0
                        filtered_data = []
                        for i, tool in enumerate(tools):
                            cumulative += tool['usage_count']
                            cum_pct = (cumulative / total_usage) * 100
                            cat = "A (High)" if cum_pct <= 70 else ("B (Medium)" if cum_pct <= 90 else "C (Low)")
                            filtered_data.append({
                                "rank": f"#{i+1}", "tool_id": str(tool['tool_id']),
                                "name": tool['name'], "usage": str(tool['usage_count']),
                                "cum_pct": f"{cum_pct:.1f}%", "category": cat
                            })
                        rows = [[d["rank"], d["tool_id"], d["name"], d["usage"], d["cum_pct"], d["category"]]
                                for d in filtered_data]
                    finally:
                        if conn.is_connected(): cursor.close(); conn.close()
                else:
                    data = getattr(self, "_abc_data", [])
                    rows = [[d["rank"], d["tool_id"], d["name"], d["usage"], d["cum_pct"], d["category"]]
                            for d in data]

            elif report_type == "usage":
                title = "Tool Usage Report"
                col_labels = ["Tool ID", "Name", "Tag ID", "Total Borrowed",
                              "Currently Out", "Qty Avail", "Condition"]
                if conn:
                    try:
                        cursor = conn.cursor(dictionary=True)
                        params = []
                        date_filter = ""
                        if start_date:
                            date_filter += " AND tr.borrow_date >= %s"
                            params.append(start_date)
                        if end_date:
                            date_filter += " AND tr.borrow_date <= %s"
                            params.append(end_date + " 23:59:59")
                        cursor.execute(f"""
                            SELECT t.tool_id, t.name, IFNULL(t.tag_id,'—') as tag_id,
                                   COUNT(tr.transaction_id) as total_borrowed,
                                   SUM(IF(tr.status='Active',1,0)) as currently_out,
                                   IFNULL(i.quantity_available,0) as qty_avail,
                                   t.`condition`
                            FROM tool t
                            LEFT JOIN inventory i ON t.tool_id = i.tool_id
                            LEFT JOIN transaction tr ON t.tool_id = tr.tool_id AND tr.type='Issue' {date_filter}
                            WHERE t.is_archived = 0
                            GROUP BY t.tool_id, t.name, t.tag_id, i.quantity_available, t.`condition`
                            ORDER BY total_borrowed DESC
                        """, params)
                        rows = [[str(r['tool_id']), r['name'], r['tag_id'],
                                 str(r['total_borrowed']), str(r['currently_out'] or 0),
                                 str(r['qty_avail']), r['condition']]
                                for r in cursor.fetchall()]
                    finally:
                        if conn.is_connected(): cursor.close(); conn.close()
                else:
                    rows = getattr(self, "_usage_data", [])

            else:
                title = "Employee Activity Report"
                col_labels = ["Employee ID", "Full Name", "Role",
                              "Total Borrows", "Active", "Returned"]
                if conn:
                    try:
                        cursor = conn.cursor(dictionary=True)
                        params = []
                        date_filter = ""
                        if start_date:
                            date_filter += " AND tr.borrow_date >= %s"
                            params.append(start_date)
                        if end_date:
                            date_filter += " AND tr.borrow_date <= %s"
                            params.append(end_date + " 23:59:59")
                        cursor.execute(f"""
                            SELECT u.employee_id, u.full_name, u.role,
                                   COUNT(tr.transaction_id) as total_borrows,
                                   SUM(IF(tr.status='Active',1,0)) as active_borrows,
                                   SUM(IF(tr.status='Returned',1,0)) as returned_borrows
                            FROM user u
                            LEFT JOIN transaction tr ON u.user_id = tr.user_id AND tr.type='Issue' {date_filter}
                            GROUP BY u.user_id, u.employee_id, u.full_name, u.role
                            ORDER BY total_borrows DESC
                        """, params)
                        rows = [[r['employee_id'], r['full_name'], r['role'],
                                 str(r['total_borrows']), str(r['active_borrows'] or 0),
                                 str(r['returned_borrows'] or 0)]
                                for r in cursor.fetchall()]
                    finally:
                        if conn.is_connected(): cursor.close(); conn.close()
                else:
                    rows = getattr(self, "_activity_data", [])

            total_rows = len(rows)

            criteria_parts = [f"Period: {date_range_label}"]
            if criteria_note:
                criteria_parts.append(f"Notes: {criteria_note}")
            criteria = "  |  ".join(criteria_parts)

            canvas_height = 185 + (total_rows * line_h) + 80

            canvas = Image.new("RGB", (canvas_width, canvas_height), "white")
            draw = ImageDraw.Draw(canvas)

            try:
                font_title = ImageFont.truetype("arialbd.ttf", 26)
                font_header = ImageFont.truetype("arialbd.ttf", 16)
                font_body = ImageFont.truetype("arial.ttf", 14)
            except IOError:
                font_title = font_header = font_body = ImageFont.load_default()

            # Title block
            draw.text((30, 20), "CHAMPION FINE TOOLING CORPORATION",
                      fill="#1E4528", font=font_title)
            draw.text((30, 60), title, fill="black", font=font_header)
            draw.text((30, 90), f"Generated: {timestamp}", fill="gray", font=font_body)
            draw.text((30, 115), criteria, fill="#444444", font=font_body)
            draw.line((30, 145, canvas_width - 30, 145), fill="#1E4528", width=2)

            # Column headers
            col_x = [30 + i * ((canvas_width - 60) // len(col_labels))
                     for i in range(len(col_labels))]
            y = 160
            for j, label in enumerate(col_labels):
                draw.text((col_x[j], y), label,
                          fill="#1E4528", font=font_header)

            draw.line((30, y + 20, canvas_width - 30, y + 20),
                      fill="#CCCCCC", width=1)
            y += 28

            # Data rows
            for r_idx, row in enumerate(rows):
                fill = "#F9FAFB" if r_idx % 2 == 0 else "white"
                draw.rectangle([30, y - 2, canvas_width - 30, y + line_h - 4],
                               fill=fill)
                for j, cell in enumerate(row):
                    draw.text((col_x[j], y), str(cell),
                              fill="black", font=font_body)
                y += line_h

            draw.line((30, y + 10, canvas_width - 30, y + 10),
                      fill="#CCCCCC", width=1)
            draw.text((30, y + 20), f"Total Records: {total_rows}",
                      fill="gray", font=font_body)

            temp_dir = tempfile.gettempdir()
            fname = f"Report_{report_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            fpath = os.path.join(temp_dir, fname)
            canvas.save(fpath, "PDF", resolution=100.0)
            os.startfile(fpath)

        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to generate PDF:\n{e}",
                                 parent=self.winfo_toplevel())