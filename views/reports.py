import customtkinter as ctk
from tkinter import messagebox
from database import get_connection
import os
import tempfile
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


class ReportsView(ctk.CTkFrame):
    def __init__(self, parent, navigate_to_tool=None):
        super().__init__(parent, fg_color="transparent")

        self.navigate_to_tool = navigate_to_tool

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=0)
        self.grid_rowconfigure(2, weight=1)

        self.build_ui()

    def build_ui(self):
        # Row 0: Title
        top_bar = ctk.CTkFrame(self, fg_color="transparent")
        top_bar.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        ctk.CTkLabel(top_bar, text="Reports", font=("Inter", 16, "bold"),
                     text_color="#1E4528").pack(side="left")

        # Date Filters
        filter_f = ctk.CTkFrame(top_bar, fg_color="transparent")
        filter_f.pack(side="right", padx=15)
        ctk.CTkLabel(filter_f, text="From:", font=("Inter", 11, "bold"), text_color="gray").pack(side="left", padx=(0, 5))
        self.start_date = ctk.CTkEntry(filter_f, placeholder_text="YYYY-MM-DD", width=110, height=32)
        self.start_date.pack(side="left", padx=(0, 10))
        self.start_date.bind("<KeyRelease>", lambda e: self._format_date_mask(e, self.start_date))
        ctk.CTkLabel(filter_f, text="To:", font=("Inter", 11, "bold"), text_color="gray").pack(side="left", padx=(0, 5))
        self.end_date = ctk.CTkEntry(filter_f, placeholder_text="YYYY-MM-DD", width=110, height=32)
        self.end_date.pack(side="left", padx=(0, 10))
        self.end_date.bind("<KeyRelease>", lambda e: self._format_date_mask(e, self.end_date))
        ctk.CTkButton(filter_f, text="Apply", width=60, height=32, fg_color="#3498DB", hover_color="#2980B9", font=("Inter", 11, "bold"), command=lambda: self.switch_tab(self.tab_var.get())).pack(side="left", padx=(0, 5))
        ctk.CTkButton(filter_f, text="Clear", width=60, height=32, fg_color="#E0E0E0", text_color="black", hover_color="#CCCCCC", font=("Inter", 11, "bold"), command=self.clear_date_filter).pack(side="left")

        # Row 1: Tab buttons (own row so they never overflow the title row)
        tab_bar = ctk.CTkFrame(self, fg_color="transparent")
        tab_bar.grid(row=1, column=0, sticky="ew", pady=(0, 8), padx=15)
        self.tab_var = ctk.StringVar(value="▤ Inventory ABC Analysis")
        self.seg_btn = ctk.CTkSegmentedButton(
            tab_bar,
            values=["▤ Inventory ABC Analysis", "⛭ Tool Usage Report", "🖹 Employee Activity",
                    "📋 Project Allocation", "⚠ Damage & Loss", "⭣ Low Stock", "⧖ Overdue Transactions"],
            variable=self.tab_var,
            fg_color="#F0F0F0",
            selected_color="#1E4528",
            selected_hover_color="#14301C",
            command=self.switch_tab
        )
        self.seg_btn.pack(side="right")

        self.tab_content = ctk.CTkFrame(self, fg_color="transparent")
        self.tab_content.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        self.tab_content.grid_columnconfigure(0, weight=1)
        self.tab_content.grid_rowconfigure(0, weight=1)

        self.render_abc_tab()

    def clear_date_filter(self):
        self.start_date.delete(0, 'end')
        self.end_date.delete(0, 'end')
        self.switch_tab(self.tab_var.get())

    def _format_date_mask(self, event, entry_widget):
        if event.keysym in ('BackSpace', 'Delete', 'Left', 'Right', 'Up', 'Down', 'Tab'):
            return
            
        text = entry_widget.get().replace('-', '')
        if not text.isdigit() and text != "":
            text = ''.join(filter(str.isdigit, text))
            
        formatted = ''
        for i, char in enumerate(text[:8]):
            if i == 4 or i == 6:
                formatted += '-'
            formatted += char
            
        current_val = entry_widget.get()
        if current_val != formatted:
            entry_widget.delete(0, 'end')
            entry_widget.insert(0, formatted)

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

    def switch_tab(self, selected):
        sd, ed, valid = self.get_and_validate_dates()
        if not valid: return
        
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

    # ==========================================
    # TAB 1: ABC Analysis 
    # ==========================================
    def render_abc_tab(self):
        frame = ctk.CTkFrame(self.tab_content, fg_color="white", corner_radius=10)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=0)
        frame.grid_rowconfigure(1, weight=0)
        frame.grid_rowconfigure(2, weight=1)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=30, pady=(12, 4))
        ctk.CTkLabel(top, text="Inventory Analytics (ABC Analysis)",
                     font=("Inter", 16, "bold"), text_color="#1E4528").pack(side="left")
        ctk.CTkButton(top, text="⎙ Export PDF", width=110, fg_color="#1E4528", hover_color="#14301C",
                      font=("Inter", 11, "bold"), command=lambda: self.open_export_dialog("abc")).pack(side="right")

        ctk.CTkLabel(frame, text="Categorizes tools by deployment frequency using the Pareto Principle (80/20).",
                     font=("Inter", 11), text_color="gray").grid(row=1, column=0, sticky="w", padx=30, pady=(0, 8))

        self._abc_scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        self._abc_scroll.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 10))

        self.run_abc_algorithm()

    def run_abc_algorithm(self):
        sd, ed, valid = self.get_and_validate_dates()
        if not valid: return
        
        scroll = self._abc_scroll
        for w in scroll.winfo_children():
            w.destroy()

        loading = ctk.CTkLabel(scroll, text="Loading ABC Analysis...", text_color="gray", font=("Inter", 12))
        loading.pack(pady=40)

        self.abc_table_inner = ctk.CTkFrame(scroll, fg_color="transparent")
        self.abc_pag_frame = ctk.CTkFrame(scroll, fg_color="transparent")

        def _fetch_abc():
            conn = get_connection()
            if not conn:
                return
            try:
                cursor = conn.cursor(dictionary=True)
                sd = self.start_date.get().strip()
                ed = self.end_date.get().strip()
                
                date_filter = ""
                params = []
                if sd:
                    date_filter += " AND tr.borrow_date >= %s"
                    params.append(sd)
                if ed:
                    date_filter += " AND tr.borrow_date <= %s"
                    params.append(ed + " 23:59:59")

                cursor.execute("""
                    SELECT t.tool_id, t.name, COUNT(tr.transaction_id) as usage_count
                    FROM tool t
                    LEFT JOIN transaction tr ON t.tool_id = tr.tool_id """ + date_filter + """
                    WHERE t.is_archived = 0
                    GROUP BY t.tool_id, t.name
                    ORDER BY usage_count DESC
                """, tuple(params))
                tools = cursor.fetchall()
            except Exception as e:
                self.after(0, lambda err=e: scroll.winfo_exists() and ctk.CTkLabel(scroll, text=f"Error: {err}", text_color="red").pack(pady=10))
                return
            finally:
                if conn.is_connected():
                    cursor.close()
                    conn.close()
            self.after(0, lambda: _render_abc(tools))

        def _render_abc(tools):
            if not self.winfo_exists() or not scroll.winfo_exists() or not loading.winfo_exists():
                return
            loading.destroy()

            total_usage = sum(t['usage_count'] for t in tools) or 1
            cumulative = 0
            self._abc_raw_data = []
            
            for i, tool in enumerate(tools):
                cumulative += tool['usage_count']
                cum_pct = (cumulative / total_usage) * 100
                if cum_pct <= 70:
                    category, color = "A (High Priority)", "#2ECC71"
                elif cum_pct <= 90:
                    category, color = "B (Medium Priority)", "#F1C40F"
                else:
                    category, color = "C (Low Priority)", "#E74C3C"
                    
                self._abc_raw_data.append({
                    "rank_raw": i+1, "tool_id": int(tool['tool_id']), "name": tool['name'],
                    "usage": int(tool['usage_count'] or 0), "cum_pct_raw": cum_pct, "category": category,
                    "color": color
                })

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

            headers = [("Rank", "rank_raw"), ("Tool ID", "tool_id"), ("Tool Name", "name"),
                       ("Times Borrowed", "usage"), ("Cumulative %", "cum_pct_raw"), ("ABC Category", "category")]
            weights = [1, 2, 5, 2, 2, 3]
            min_sizes = [50, 80, 200, 120, 120, 140]

            for col, (w, min_w) in enumerate(zip(weights, min_sizes)):
                self.abc_table_inner.grid_columnconfigure(col, weight=w, minsize=min_w, uniform="abc_cols")

            for col, (text, sort_key) in enumerate(headers):
                cell = ctk.CTkFrame(self.abc_table_inner, fg_color="#1E4528", corner_radius=0, cursor="hand2")
                cell.grid(row=0, column=col, sticky="nsew", pady=(0, 2))
                arrow = " ▼" if self.abc_sort_desc else " ▲"
                disp_text = text + arrow if self.abc_sort_col == sort_key else text
                lbl = ctk.CTkLabel(cell, text=disp_text, font=("Inter", 11, "bold"), text_color="white", anchor="center", cursor="hand2")
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
                bg = "#F9FAFB" if i % 2 == 0 else "white"
                for col, val in enumerate(display_data):
                    cell = ctk.CTkFrame(self.abc_table_inner, fg_color=bg, corner_radius=0)
                    cell.grid(row=r_idx, column=col, sticky="nsew")
                    txt_col = d['color'] if col == 5 else "#1A1A1A"
                    font_w = "bold" if col == 5 else "normal"
                    lbl = ctk.CTkLabel(cell, text=val, font=("Inter", 11, font_w), text_color=txt_col, justify="center", anchor="center")
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
            prev_btn = ctk.CTkButton(p_frame, text="< Prev", width=60, fg_color="#E0E0E0", text_color="black", hover_color="#CCCCCC", command=_prev)
            if self.abc_current_page == 1: prev_btn.configure(state="disabled", fg_color="#F0F0F0", text_color="gray")
            prev_btn.pack(side="left", padx=10)
            ctk.CTkLabel(p_frame, text=f"Page {self.abc_current_page} of {total_pages}   (Total: {total_items})", font=("Inter", 11)).pack(side="left", padx=20)
            next_btn = ctk.CTkButton(p_frame, text="Next >", width=60, fg_color="#E0E0E0", text_color="black", hover_color="#CCCCCC", command=_next)
            if self.abc_current_page == total_pages or total_pages == 0: next_btn.configure(state="disabled", fg_color="#F0F0F0", text_color="gray")
            next_btn.pack(side="left", padx=10)

        import threading
        threading.Thread(target=_fetch_abc, daemon=True).start()

    # ==========================================
    # TAB 2: Tool Usage Report
    # ==========================================
    def render_usage_tab(self):
        frame = ctk.CTkFrame(self.tab_content, fg_color="white", corner_radius=10)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=0)
        frame.grid_rowconfigure(1, weight=0)
        frame.grid_rowconfigure(2, weight=0)
        frame.grid_rowconfigure(3, weight=1)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=30, pady=(12, 4))
        ctk.CTkLabel(top, text="Tool Usage Report",
                     font=("Inter", 16, "bold"), text_color="#1E4528").pack(side="left")
        ctk.CTkButton(top, text="⎙ Export PDF", width=110, fg_color="#1E4528", hover_color="#14301C",
                      font=("Inter", 11, "bold"), command=lambda: self.open_export_dialog("usage")).pack(side="right")

        ctk.CTkLabel(frame, text="Summary of all tool transactions, availability, and condition status.",
                     font=("Inter", 11), text_color="gray").grid(row=1, column=0, sticky="w", padx=30, pady=(0, 8))

        search_frame = ctk.CTkFrame(frame, fg_color="transparent")
        search_frame.grid(row=2, column=0, sticky="ew", padx=30, pady=(0, 10))
        
        self.usage_search_entry = ctk.CTkEntry(search_frame, placeholder_text="Search Tool, Tag ID, Condition...", width=280, height=38)
        self.usage_search_entry.pack(side="left", padx=(0, 10))
        self.usage_search_entry.bind("<Return>", lambda e: self.run_usage_algorithm(self.usage_search_entry.get().strip()))
        
        ctk.CTkButton(search_frame, text="Search", width=80, height=38, fg_color="#3498DB", text_color="white", hover_color="#2980B9", font=("Inter", 12, "bold"), command=lambda: self.run_usage_algorithm(self.usage_search_entry.get().strip())).pack(side="left", padx=(0, 10))
        ctk.CTkButton(search_frame, text="⟳ Reset", width=80, height=38, fg_color="#E0E0E0", text_color="black", hover_color="#CCCCCC", font=("Inter", 12, "bold"), command=lambda: [self.usage_search_entry.delete(0, 'end'), self.run_usage_algorithm("")]).pack(side="left", padx=(0, 10))

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

        loading = ctk.CTkLabel(scroll, text="Loading Tool Usage Report...", text_color="gray", font=("Inter", 12))
        loading.pack(pady=40)

        self.usage_table_inner = ctk.CTkFrame(scroll, fg_color="transparent")
        self.usage_pag_frame = ctk.CTkFrame(scroll, fg_color="transparent")

        self._current_loading = loading

        def _fetch_usage():
            conn = get_connection()
            if not conn:
                return
            try:
                cursor = conn.cursor(dictionary=True)
                
                sd = self.start_date.get().strip()
                ed = self.end_date.get().strip()
                
                date_filter = ""
                date_params = []
                if sd:
                    date_filter += " AND tr.borrow_date >= %s"
                    date_params.append(sd)
                if ed:
                    date_filter += " AND tr.borrow_date <= %s"
                    date_params.append(ed + " 23:59:59")

                search_filter = ""
                search_params = []
                if search_query:
                    search_filter = " AND (t.name LIKE %s OR CAST(t.tool_id AS CHAR) LIKE %s OR IFNULL(t.tag_id, '') LIKE %s OR t.condition LIKE %s)"
                    search_params.extend([f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", f"%{search_query}%"])

                query = f"""
                    SELECT t.tool_id, t.name,
                           IFNULL(t.tag_id,'Unassigned') as tag_id,
                           COUNT(tr.transaction_id) as total_borrowed,
                           IFNULL(i.quantity_total - i.quantity_available, 0) as currently_out,
                           IFNULL(i.quantity_available,0) as qty_avail,
                           t.`condition`
                    FROM tool t
                    LEFT JOIN inventory i ON t.tool_id = i.tool_id
                    LEFT JOIN transaction tr ON t.tool_id = tr.tool_id {date_filter}
                    WHERE t.is_archived = 0 {search_filter}
                    GROUP BY t.tool_id, t.name, t.tag_id, i.quantity_total, i.quantity_available, t.`condition`
                    ORDER BY total_borrowed DESC
                """
                params = date_params + search_params
                cursor.execute(query, tuple(params))
                rows = cursor.fetchall()
            except Exception as e:
                self.after(0, lambda err=e: scroll.winfo_exists() and self._show_error(scroll, f"Error: {err}"))
                return
            finally:
                if conn and conn.is_connected():
                    cursor.close()
                    conn.close()
            self.after(0, lambda: _render_usage_safe(rows))

        def _render_usage_safe(rows):
            if not self.winfo_exists() or not scroll.winfo_exists() or not hasattr(self, '_current_loading') or not self._current_loading.winfo_exists():
                return
            self._current_loading.destroy()

            self.usage_state["raw_data"] = [
                {"tool_id": int(r['tool_id']), "name": r['name'], "tag_id": r['tag_id'],
                 "total_borrowed": int(r['total_borrowed'] or 0), "currently_out": int(r['currently_out'] or 0),
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
        ctk.CTkLabel(parent, text=message, text_color="red").pack(pady=20)

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
                   ("Total Borrowed", "total_borrowed"), ("Currently Out", "currently_out"),
                   ("Qty Avail", "qty_avail"), ("Condition", "condition")]
        weights = [2, 5, 2, 2, 2, 2, 2]
        min_sizes = [80, 200, 100, 120, 120, 100, 100]

        for col, (w, min_w) in enumerate(zip(weights, min_sizes)):
            self.usage_table_inner.grid_columnconfigure(col, weight=w, minsize=min_w, uniform="usage_cols")

        if not page_data:
            ctk.CTkLabel(self.usage_table_inner, text="No tool usage data found for the selected period.",
                         text_color="gray", font=("Inter", 12)).grid(row=0, column=0, columnspan=len(headers), pady=30)
            return

        # Header row
        for col, (text, sort_key) in enumerate(headers):
            cell = ctk.CTkFrame(self.usage_table_inner, fg_color="#1E4528", corner_radius=0, cursor="hand2")
            cell.grid(row=0, column=col, sticky="nsew", pady=(0, 2))
            arrow = " ▼" if self.usage_state["sort_desc"] else " ▲"
            disp_text = text + arrow if self.usage_state["sort_col"] == sort_key else text
            lbl = ctk.CTkLabel(cell, text=disp_text, font=("Inter", 11, "bold"), text_color="white", anchor="center", cursor="hand2")
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
            bg = "#F9FAFB" if i % 2 == 0 else "white"
            for col, val in enumerate(vals):
                cell = ctk.CTkFrame(self.usage_table_inner, fg_color=bg, corner_radius=0)
                cell.grid(row=r_idx, column=col, sticky="nsew")
                txt_col = "#1A1A1A"
                if col == 6:
                    txt_col = "#2ECC71" if val == "Good" else "#D8000C"
                elif col == 2 and val == "Unassigned":
                    txt_col = "#D8000C"
                font_w = "bold" if (col == 6 or (col == 2 and val == "Unassigned")) else "normal"
                lbl = ctk.CTkLabel(cell, text=val, font=("Inter", 11, font_w), text_color=txt_col, justify="center", anchor="center")
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
        prev_btn = ctk.CTkButton(p_frame, text="< Prev", width=60, fg_color="#E0E0E0", text_color="black", hover_color="#CCCCCC", command=_prev)
        if self.usage_state["current_page"] == 1:
            prev_btn.configure(state="disabled", fg_color="#F0F0F0", text_color="gray")
        prev_btn.pack(side="left", padx=10)

        ctk.CTkLabel(p_frame, text=f"Page {self.usage_state['current_page']} of {total_pages}   (Total: {total_items})", font=("Inter", 11)).pack(side="left", padx=20)

        next_btn = ctk.CTkButton(p_frame, text="Next >", width=60, fg_color="#E0E0E0", text_color="black", hover_color="#CCCCCC", command=_next)
        if self.usage_state["current_page"] == total_pages or total_pages == 0:
            next_btn.configure(state="disabled", fg_color="#F0F0F0", text_color="gray")
        next_btn.pack(side="left", padx=10)

    # ==========================================
    # TAB 3: Employee Activity Report
    # ==========================================
    def render_activity_tab(self):
        frame = ctk.CTkFrame(self.tab_content, fg_color="white", corner_radius=10)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=30, pady=(12, 4))
        ctk.CTkLabel(top, text="Employee Activity Report",
                     font=("Inter", 16, "bold"), text_color="#1E4528").pack(side="left")
        ctk.CTkButton(top, text="⎙ Export PDF", width=110, fg_color="#1E4528", hover_color="#14301C",
                      font=("Inter", 11, "bold"), command=lambda: self.open_export_dialog("activity")).pack(side="right")

        ctk.CTkLabel(frame, text="Aggregated borrowing activity per employee for accountability monitoring.",
                     font=("Inter", 11), text_color="gray").grid(row=1, column=0, sticky="w", padx=30, pady=(0, 4))

        scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        scroll.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 10))

        self.activity_chart_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self.activity_chart_frame.pack(fill="x", pady=(0, 15))

        self.activity_table_inner = ctk.CTkFrame(scroll, fg_color="transparent")
        self.activity_table_inner.pack(fill="x", pady=(10, 0))

        self.activity_pag_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self.activity_pag_frame.pack(fill="x", pady=10)

        sd, ed, valid = self.get_and_validate_dates()
        if not valid: return

        def _fetch_activity():
            conn = get_connection()
            if not conn:
                return
            try:
                cursor = conn.cursor(dictionary=True)
                sd = self.start_date.get().strip()
                ed = self.end_date.get().strip()
                
                date_filter = ""
                params = []
                if sd:
                    date_filter += " AND tr.borrow_date >= %s"
                    params.append(sd)
                if ed:
                    date_filter += " AND tr.borrow_date <= %s"
                    params.append(ed + " 23:59:59")

                cursor.execute("""
                    SELECT u.employee_id, u.full_name, u.role,
                           COUNT(tr.transaction_id) as total_borrows,
                           SUM(CASE WHEN tr.status='Active' THEN 1 ELSE 0 END) as active_borrows,
                           SUM(CASE WHEN tr.status='Returned' THEN 1 ELSE 0 END) as total_returned
                    FROM user u
                    LEFT JOIN transaction tr ON u.user_id = tr.user_id """ + date_filter + """
                    WHERE IFNULL(u.status, 'Active') != 'Archived'
                    GROUP BY u.user_id, u.employee_id, u.full_name, u.role
                    ORDER BY total_borrows DESC
                """, tuple(params))
                rows = cursor.fetchall()
            except Exception as e:
                self.after(0, lambda err=e: scroll.winfo_exists() and ctk.CTkLabel(scroll, text=f"Error: {err}", text_color="red").pack(pady=10))
                return
            finally:
                if conn.is_connected():
                    cursor.close()
                    conn.close()
            self.after(0, lambda: _render_activity(rows))

        def _render_activity(rows):
            if not self.winfo_exists() or not scroll.winfo_exists(): return
            self._activity_raw_data = []
            for i, row in enumerate(rows):
                self._activity_raw_data.append({
                    "employee_id": row['employee_id'], "full_name": row['full_name'], "role": row['role'],
                    "total_borrows": int(row['total_borrows'] or 0), "active_borrows": int(row['active_borrows'] or 0),
                    "total_returned": int(row['total_returned'] or 0)
                })

            # ── Render Activity Bar Chart ───────────────────────
            for w in self.activity_chart_frame.winfo_children():
                w.destroy()
            top_users = rows[:5]
            if self.activity_chart_frame.winfo_exists() and sum(r['total_borrows'] for r in top_users) > 0:
                fig = Figure(figsize=(7, 2.5), dpi=90)
                fig.patch.set_facecolor('#FFFFFF')
                ax = fig.add_subplot(111)
                names = [str(r['full_name'] or 'Unknown').split()[0] for r in top_users]
                counts = [r['total_borrows'] for r in top_users]
                ax.bar(names, counts, color="#9B59B6", width=0.4)
                ax.spines["top"].set_visible(False)
                ax.spines["right"].set_visible(False)
                fig.tight_layout()
                canvas = FigureCanvasTkAgg(fig, master=self.activity_chart_frame)
                canvas.draw()
                canvas.get_tk_widget().pack(pady=10)
                
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

            headers = [("Employee ID", "employee_id"), ("Full Name", "full_name"), ("Role", "role"),
                       ("Total Borrows", "total_borrows"), ("Currently Active", "active_borrows"),
                       ("Total Returned", "total_returned")]
            weights = [2, 4, 2, 2, 2, 2]
            min_sizes = [100, 180, 100, 120, 120, 120]

            for col, (w, min_w) in enumerate(zip(weights, min_sizes)):
                self.activity_table_inner.grid_columnconfigure(col, weight=w, minsize=min_w, uniform="activity_cols")

            for col, (text, sort_key) in enumerate(headers):
                cell = ctk.CTkFrame(self.activity_table_inner, fg_color="#1E4528", corner_radius=0, cursor="hand2")
                cell.grid(row=0, column=col, sticky="nsew", pady=(0, 2))
                arrow = " ▼" if self.activity_sort_desc else " ▲"
                disp_text = text + arrow if self.activity_sort_col == sort_key else text
                lbl = ctk.CTkLabel(cell, text=disp_text, font=("Inter", 11, "bold"), text_color="white", anchor="center", cursor="hand2")
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
                bg = "#F9FAFB" if i % 2 == 0 else "white"
                for col, val in enumerate(vals):
                    cell = ctk.CTkFrame(self.activity_table_inner, fg_color=bg, corner_radius=0)
                    cell.grid(row=r_idx, column=col, sticky="nsew")
                    txt_col = "#1A1A1A"
                    if col == 4 and int(val) > 0: txt_col = "#D8000C"
                    font_w = "bold" if col == 4 and int(val) > 0 else "normal"
                    lbl = ctk.CTkLabel(cell, text=val, font=("Inter", 11, font_w), text_color=txt_col, justify="center", anchor="center")
                    lbl.configure(wraplength=min_sizes[col] - 10)
                    lbl.pack(fill="both", expand=True, padx=4, pady=12)

            for w in self.activity_pag_frame.winfo_children(): w.destroy()
            def _prev():
                if self.activity_current_page > 1: self.activity_current_page -= 1; _update_activity_table()
            def _next():
                if self.activity_current_page < total_pages: self.activity_current_page += 1; _update_activity_table()

            p_frame = ctk.CTkFrame(self.activity_pag_frame, fg_color="transparent")
            p_frame.pack(pady=10)
            prev_btn = ctk.CTkButton(p_frame, text="< Prev", width=60, fg_color="#E0E0E0", text_color="black", hover_color="#CCCCCC", command=_prev)
            if self.activity_current_page == 1: prev_btn.configure(state="disabled", fg_color="#F0F0F0", text_color="gray")
            prev_btn.pack(side="left", padx=10)
            ctk.CTkLabel(p_frame, text=f"Page {self.activity_current_page} of {total_pages}   (Total: {total_items})", font=("Inter", 11)).pack(side="left", padx=20)
            next_btn = ctk.CTkButton(p_frame, text="Next >", width=60, fg_color="#E0E0E0", text_color="black", hover_color="#CCCCCC", command=_next)
            if self.activity_current_page == total_pages or total_pages == 0: next_btn.configure(state="disabled", fg_color="#F0F0F0", text_color="gray")
            next_btn.pack(side="left", padx=10)

        import threading
        threading.Thread(target=_fetch_activity, daemon=True).start()

    # ==========================================
    # TAB 4: Project Allocation Report
    # ==========================================
    def render_project_allocation_tab(self):
        frame = ctk.CTkFrame(self.tab_content, fg_color="white", corner_radius=10)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=30, pady=(12, 4))
        ctk.CTkLabel(top, text="Project Allocation Report", font=("Inter", 16, "bold"), text_color="#1E4528").pack(side="left")
        ctk.CTkButton(top, text="⎙ Export PDF", width=110, fg_color="#1E4528", hover_color="#14301C",
                      font=("Inter", 11, "bold"), command=lambda: self.open_export_dialog("allocation")).pack(side="right")

        ctk.CTkLabel(frame, text="Shows which projects are holding tools, requested vs. deployed quantities.",
                     font=("Inter", 11), text_color="gray").grid(row=1, column=0, sticky="w", padx=30, pady=(0, 4))

        scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        scroll.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 10))

        self._alloc_chart_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self._alloc_chart_frame.pack(fill="x", pady=(0, 15))

        self._alloc_table = ctk.CTkFrame(scroll, fg_color="transparent")
        self._alloc_table.pack(fill="x", pady=(10, 0))

        sd, ed, valid = self.get_and_validate_dates()
        if not valid: return

        def _fetch():
            conn = get_connection()
            if not conn: return
            try:
                cursor = conn.cursor(dictionary=True)
                sd = self.start_date.get().strip()
                ed = self.end_date.get().strip()
                
                params = []
                date_filter = ""
                if sd:
                    date_filter += " AND tr.borrow_date >= %s"
                    params.append(sd)
                if ed:
                    date_filter += " AND tr.borrow_date <= %s"
                    params.append(ed + " 23:59:59")

                having_clause = " HAVING issued > 0 OR retrieved > 0" if (sd or ed) else ""

                cursor.execute("""
                    SELECT p.name as project_name, p.client, p.location, p.status,
                           t.name as tool_name, pr.quantity as requested,
                           COUNT(tr.transaction_id) as issued,
                           IFNULL(SUM(CASE WHEN tr.status='Returned' THEN 1 ELSE 0 END), 0) as retrieved,
                           pr.status as req_status
                    FROM projects p
                    JOIN project_requirements pr ON p.project_id = pr.project_id
                    JOIN tool t ON pr.tool_id = t.tool_id
                    LEFT JOIN transaction tr ON tr.project_id = p.project_id AND tr.tool_id = t.tool_id """ + date_filter + """
                    WHERE p.archived_at IS NULL
                    GROUP BY p.project_id, t.tool_id, pr.quantity, pr.status
                    """ + having_clause + """
                    ORDER BY p.status ASC, p.name ASC, t.name ASC
                """, params)
                rows = cursor.fetchall()
            except Exception as e:
                self.after(0, lambda err=e: scroll.winfo_exists() and ctk.CTkLabel(scroll, text=f"Error: {err}", text_color="red").pack(pady=10))
                return
            finally:
                if conn.is_connected(): cursor.close(); conn.close()
            self.after(0, lambda: _render(rows))

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
                    proj_totals[pn]["requested"] += int(r['requested'])
                    proj_totals[pn]["issued"] += int(r['issued'])
                    proj_totals[pn]["retrieved"] += int(r['retrieved'])
                top_projs = list(proj_totals.items())[:8]
                if top_projs:
                    labels = [p[0] for p in top_projs]
                    req = [p[1]["requested"] for p in top_projs]
                    iss = [p[1]["issued"] for p in top_projs]
                    ret = [p[1]["retrieved"] for p in top_projs]
                    fig = Figure(figsize=(8, 2.8), dpi=90)
                    fig.patch.set_facecolor('#FFFFFF')
                    ax = fig.add_subplot(111)
                    x = range(len(labels))
                    w = 0.25
                    ax.bar([i - w for i in x], req, width=w, label="Requested", color="#3498DB")
                    ax.bar(list(x), iss, width=w, label="Issued", color="#2ECC71")
                    ax.bar([i + w for i in x], ret, width=w, label="Retrieved", color="#95A5A6")
                    ax.set_xticks(list(x))
                    ax.set_xticklabels(labels, fontsize=8, rotation=15, ha="right")
                    ax.legend(fontsize=8)
                    ax.spines["top"].set_visible(False)
                    ax.spines["right"].set_visible(False)
                    fig.tight_layout()
                    chart_canvas = FigureCanvasTkAgg(fig, master=self._alloc_chart_frame)
                    chart_canvas.draw()
                    chart_canvas.get_tk_widget().pack(pady=10)
            # ────────────────────────────────────────────────────

            headers = ["Project", "Client", "Location", "Status", "Tool", "Requested", "Issued", "Retrieved", "Flag"]
            weights = [4, 3, 3, 2, 4, 2, 2, 2, 2]
            min_sizes = [140, 110, 110, 90, 140, 80, 70, 80, 80]
            for col, (w, mn) in enumerate(zip(weights, min_sizes)):
                self._alloc_table.grid_columnconfigure(col, weight=w, minsize=mn, uniform="alloc_cols")
            for col, text in enumerate(headers):
                cell = ctk.CTkFrame(self._alloc_table, fg_color="#1E4528", corner_radius=0)
                cell.grid(row=0, column=col, sticky="nsew", pady=(0, 2))
                ctk.CTkLabel(cell, text=text, font=("Inter", 11, "bold"), text_color="white", anchor="center").pack(fill="both", expand=True, padx=2, pady=10)

            if not rows:
                ctk.CTkLabel(self._alloc_table, text="No project allocation data found.", text_color="gray").grid(row=1, column=0, columnspan=len(headers), pady=20)
                return

            STATUS_COLORS = {"Ongoing": "#2ECC71", "Approved": "#3498DB", "Pending": "#F39C12", "Completed": "#95A5A6"}
            for i, row in enumerate(rows):
                bg = "#F9FAFB" if i % 2 == 0 else "white"
                still_out = int(row['issued']) - int(row['retrieved'])
                flag = "⚠ Unreturned" if still_out > 0 and row['status'] in ("Completed",) else ("Active" if still_out > 0 else "—")
                vals = [str(row['project_name'] or 'Unknown'), str(row['client'] or 'Unknown'), str(row['location'] or "—"), str(row['status'] or 'Pending'),
                        str(row['tool_name'] or 'Unknown'), str(int(row['requested'] or 0)), str(int(row['issued'] or 0)),
                        str(int(row['retrieved'] or 0)), str(flag)]
                for col, val in enumerate(vals):
                    cell = ctk.CTkFrame(self._alloc_table, fg_color=bg, corner_radius=0)
                    cell.grid(row=i+1, column=col, sticky="nsew")
                    txt = STATUS_COLORS.get(val, "#1A1A1A") if col == 3 else ("#D8000C" if "⚠" in str(val) else "#1A1A1A")
                    fw = "bold" if col in (3, 8) else "normal"
                    ctk.CTkLabel(cell, text=val, font=("Inter", 11, fw), text_color=txt,
                                 anchor="center", wraplength=min_sizes[col]-10).pack(fill="both", expand=True, padx=4, pady=10)

        import threading
        threading.Thread(target=_fetch, daemon=True).start()

    # ==========================================
    # TAB 5: Damage, Loss & Maintenance Report
    # ==========================================
    def render_damage_loss_tab(self):
        frame = ctk.CTkFrame(self.tab_content, fg_color="white", corner_radius=10)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=30, pady=(12, 4))
        ctk.CTkLabel(top, text="Damage, Loss & Maintenance Report", font=("Inter", 16, "bold"), text_color="#1E4528").pack(side="left")
        ctk.CTkButton(top, text="⎙ Export PDF", width=110, fg_color="#1E4528", hover_color="#14301C",
                      font=("Inter", 11, "bold"), command=lambda: self.open_export_dialog("damage")).pack(side="right")

        ctk.CTkLabel(frame, text="Asset depreciation and financial loss metrics from returned condition data.",
                     font=("Inter", 11), text_color="gray").grid(row=1, column=0, sticky="w", padx=30, pady=(0, 4))

        scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        scroll.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 10))

        self._dmg_summary_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self._dmg_summary_frame.pack(fill="x", pady=(0, 5))
        self._dmg_chart_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self._dmg_chart_frame.pack(fill="x", pady=(0, 15))
        self._dmg_table = ctk.CTkFrame(scroll, fg_color="transparent")
        self._dmg_table.pack(fill="x", pady=(10, 0))

        sd, ed, valid = self.get_and_validate_dates()
        if not valid: return

        def _fetch():
            conn = get_connection()
            if not conn: return
            try:
                cursor = conn.cursor(dictionary=True)
                sd = self.start_date.get().strip()
                ed = self.end_date.get().strip()
                
                params = []
                date_filter = ""
                if sd:
                    date_filter += " AND tr.return_date >= %s"
                    params.append(sd)
                if ed:
                    date_filter += " AND tr.return_date <= %s"
                    params.append(ed + " 23:59:59")

                cursor.execute("""
                    SELECT t.tool_id, t.name, IFNULL(t.price, 0) as price,
                           tr.condition_at_return as cond_flag,
                           u.full_name as returned_by,
                           DATE_FORMAT(tr.return_date, '%Y-%m-%d') as return_date,
                           IFNULL(tr.condition_return_notes, '—') as notes
                    FROM transaction tr
                    JOIN tool t ON tr.tool_id = t.tool_id
                    LEFT JOIN user u ON tr.user_id = u.user_id
                    WHERE tr.type = 'Retrieval'
                      AND tr.condition_at_return IN ('Damaged', 'Lost', 'Needs Repair') """ + date_filter + """
                    ORDER BY tr.return_date DESC
                """, params)
                rows = cursor.fetchall()

                cursor.execute("""
                    SELECT
                        SUM(CASE WHEN tr.condition_at_return = 'Lost' THEN IFNULL(t.price, 0) ELSE 0 END) as total_loss,
                        SUM(CASE WHEN tr.condition_at_return = 'Damaged' THEN IFNULL(t.price, 0) ELSE 0 END) as total_damage,
                        COUNT(CASE WHEN tr.condition_at_return = 'Lost' THEN 1 END) as count_lost,
                        COUNT(CASE WHEN tr.condition_at_return = 'Damaged' THEN 1 END) as count_damaged,
                        COUNT(CASE WHEN tr.condition_at_return = 'Needs Repair' THEN 1 END) as count_repair
                    FROM transaction tr
                    JOIN tool t ON tr.tool_id = t.tool_id
                    WHERE tr.type = 'Retrieval'
                      AND tr.condition_at_return IN ('Damaged', 'Lost', 'Needs Repair') """ + date_filter + """
                """, params)
                summary = cursor.fetchone()
            except Exception as e:
                self.after(0, lambda err=e: scroll.winfo_exists() and ctk.CTkLabel(scroll, text=f"Error: {err}", text_color="red").pack(pady=10))
                return
            finally:
                if conn.is_connected(): cursor.close(); conn.close()
            self.after(0, lambda: _render(rows, summary))

        def _render(rows, summary):
            if not self.winfo_exists() or not scroll.winfo_exists(): return
            self._dmg_data = rows
            for w in self._dmg_summary_frame.winfo_children(): w.destroy()

            # Summary KPI cards
            kpis = [
                ("💸 Total Loss Value", f"₱{float(summary['total_loss'] or 0):,.2f}", "#D8000C"),
                ("🔨 Total Damage Value", f"₱{float(summary['total_damage'] or 0):,.2f}", "#E67E22"),
                ("❌ Items Lost", str(summary['count_lost'] or 0), "#D8000C"),
                ("⚠ Items Damaged", str(summary['count_damaged'] or 0), "#E67E22"),
                ("🔧 Needs Repair", str(summary['count_repair'] or 0), "#F39C12"),
            ]
            for label, val, color in kpis:
                card = ctk.CTkFrame(self._dmg_summary_frame, fg_color="#F9FAFB", corner_radius=8)
                card.pack(side="left", expand=True, fill="x", padx=5, pady=5)
                ctk.CTkLabel(card, text=label, font=("Inter", 10), text_color="gray").pack(pady=(10, 2))
                ctk.CTkLabel(card, text=val, font=("Inter", 16, "bold"), text_color=color).pack(pady=(0, 10))

            # ── Damage/Loss Pie Chart ───────────────────────────
            for w in self._dmg_chart_frame.winfo_children(): w.destroy()
            c_lost = int(summary['count_lost'] or 0)
            c_dmg = int(summary['count_damaged'] or 0)
            c_rep = int(summary['count_repair'] or 0)
            if c_lost + c_dmg + c_rep > 0:
                fig = Figure(figsize=(5, 2.5), dpi=90)
                fig.patch.set_facecolor('#FFFFFF')
                ax = fig.add_subplot(111)
                sizes, lbls, colors = [], [], []
                if c_lost: sizes.append(c_lost); lbls.append(f"Lost ({c_lost})"); colors.append("#D8000C")
                if c_dmg: sizes.append(c_dmg); lbls.append(f"Damaged ({c_dmg})"); colors.append("#E67E22")
                if c_rep: sizes.append(c_rep); lbls.append(f"Needs Repair ({c_rep})"); colors.append("#F39C12")
                ax.pie(sizes, labels=lbls, colors=colors, autopct='%1.1f%%', startangle=140)
                ax.axis('equal')
                fig.tight_layout()
                chart_canvas = FigureCanvasTkAgg(fig, master=self._dmg_chart_frame)
                chart_canvas.draw()
                chart_canvas.get_tk_widget().pack(pady=10)
            # ────────────────────────────────────────────────────

            for w in self._dmg_table.winfo_children(): w.destroy()
            headers = ["Tool ID", "Tool Name", "Unit Price", "Condition", "Returned By", "Return Date", "Notes"]
            weights = [1, 4, 2, 2, 3, 2, 4]
            min_sizes = [60, 160, 100, 110, 130, 100, 160]
            for col, (w, mn) in enumerate(zip(weights, min_sizes)):
                self._dmg_table.grid_columnconfigure(col, weight=w, minsize=mn, uniform="dmg_cols")
            for col, text in enumerate(headers):
                cell = ctk.CTkFrame(self._dmg_table, fg_color="#1E4528", corner_radius=0)
                cell.grid(row=0, column=col, sticky="nsew", pady=(0, 2))
                ctk.CTkLabel(cell, text=text, font=("Inter", 11, "bold"), text_color="white", anchor="center").pack(fill="both", expand=True, padx=2, pady=10)

            if not rows:
                ctk.CTkLabel(self._dmg_table, text="No damage or loss records found.", text_color="gray").grid(row=1, column=0, columnspan=len(headers), pady=20)
                return

            COND_COLORS = {"Lost": "#D8000C", "Damaged": "#E67E22", "Needs Repair": "#F39C12"}
            for i, row in enumerate(rows):
                bg = "#F9FAFB" if i % 2 == 0 else "white"
                vals = [str(row['tool_id']), str(row['name'] or 'Unknown'), f"₱{float(row['price'] or 0):,.2f}",
                        str(row['cond_flag'] or 'Unknown'), str(row['returned_by'] or "—"), str(row['return_date'] or "—"), str(row['notes'] or "")]
                for col, val in enumerate(vals):
                    cell = ctk.CTkFrame(self._dmg_table, fg_color=bg, corner_radius=0)
                    cell.grid(row=i+1, column=col, sticky="nsew")
                    txt = COND_COLORS.get(val, "#1A1A1A") if col == 3 else "#1A1A1A"
                    fw = "bold" if col == 3 else "normal"
                    ctk.CTkLabel(cell, text=val, font=("Inter", 11, fw), text_color=txt,
                                 anchor="center", wraplength=min_sizes[col]-10).pack(fill="both", expand=True, padx=4, pady=10)

        import threading
        threading.Thread(target=_fetch, daemon=True).start()

    # ==========================================
    # TAB 6: Low Stock / Procurement Report
    # ==========================================
    def render_low_stock_tab(self):
        frame = ctk.CTkFrame(self.tab_content, fg_color="white", corner_radius=10)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=0)   # title
        frame.grid_rowconfigure(1, weight=0)   # description
        frame.grid_rowconfigure(2, weight=1)   # scroll

        # Top bar
        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=30, pady=(12, 4))
        ctk.CTkLabel(top, text="Low Stock / Procurement Report", font=("Inter", 16, "bold"), text_color="#1E4528").pack(side="left")
        ctk.CTkButton(top, text="⎙ Export PDF", width=110, fg_color="#1E4528", hover_color="#14301C",
                      font=("Inter", 11, "bold"), command=lambda: self.open_export_dialog("lowstock")).pack(side="right")

        # Description
        ctk.CTkLabel(frame, text="Items where current available stock is at or below the set minimum threshold.",
                     font=("Inter", 11), text_color="gray").grid(row=1, column=0, sticky="w", padx=30, pady=(0, 2))
        if self.navigate_to_tool:
            ctk.CTkLabel(frame, text="💡 Click any row to open that item directly in Inventory.",
                         font=("Inter", 11, "italic"), text_color="#2980B9").grid(row=1, column=0, sticky="e", padx=30, pady=(0, 2))

        # Scrollable content
        scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        scroll.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 10))

        self._ls_table = ctk.CTkFrame(scroll, fg_color="transparent")

        def _fetch():
            conn = get_connection()
            if not conn: return
            try:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("""
                    SELECT t.tool_id, t.name, t.item_type, t.category,
                           IFNULL(t.supplier, '—') as supplier,
                           IFNULL(t.unit_of_measure, 'pcs') as uom,
                           IFNULL(i.quantity_available, 0) as qty_avail,
                           IFNULL(i.quantity_total, 0) as qty_total,
                           IFNULL(i.minimum_stock, 0) as minimum_stock,
                           IFNULL(t.price, 0) as price
                    FROM tool t
                    JOIN inventory i ON t.tool_id = i.tool_id
                    WHERE t.is_archived = 0
                      AND i.minimum_stock > 0
                    AND i.quantity_available < i.minimum_stock
                    ORDER BY (i.quantity_available / NULLIF(i.minimum_stock, 0)) ASC
                """)
                rows = cursor.fetchall()
            except Exception as e:
                self.after(0, lambda err=e: scroll.winfo_exists() and ctk.CTkLabel(scroll, text=f"Error: {err}", text_color="red").pack(pady=10))
                return
            finally:
                if conn.is_connected(): cursor.close(); conn.close()
            self.after(0, lambda: _render(rows))

        def _render(rows):
            if not self.winfo_exists() or not scroll.winfo_exists(): return
            self._ls_data = rows
            for w in self._ls_table.winfo_children(): w.destroy()

            self._ls_table.pack(fill="x", pady=(0, 10))

            headers = ["PID", "Name", "Type", "Category", "Supplier", "UoM", "Available", "Total", "Min Stock", "Reorder Qty"]
            weights = [1, 4, 2, 2, 3, 1, 2, 2, 2, 2]
            min_sizes = [50, 150, 90, 100, 120, 60, 80, 70, 80, 90]

            for col, (w, mn) in enumerate(zip(weights, min_sizes)):
                self._ls_table.grid_columnconfigure(col, weight=w, minsize=mn, uniform="ls_cols")

            for col, text in enumerate(headers):
                cell = ctk.CTkFrame(self._ls_table, fg_color="#1E4528", corner_radius=0)
                cell.grid(row=0, column=col, sticky="nsew", pady=(0, 2))
                ctk.CTkLabel(cell, text=text, font=("Inter", 11, "bold"), text_color="white", anchor="center").pack(fill="both", expand=True, padx=2, pady=10)

            if not rows:
                ctk.CTkLabel(self._ls_table,
                             text="✓ All items are above their minimum stock thresholds.\n\nTip: Set a Minimum Stock value per item in the Inventory module to enable this report.",
                             text_color="gray", font=("Inter", 12), justify="center").grid(row=1, column=0, columnspan=len(headers), pady=30)
                return

            for i, row in enumerate(rows):
                bg = "#FFF3F3" if float(row['qty_avail'] or 0) == 0 else ("#FFFBF0" if i % 2 == 0 else "white")
                reorder_qty = max(0, float(row['minimum_stock'] or 0) * 2 - float(row['qty_avail'] or 0))
                vals = [str(row['tool_id']), str(row['name'] or 'Unknown'), str(row['item_type'] or 'Unknown'), str(row['category'] or 'Unknown'),
                        str(row['supplier'] or '—'), str(row['uom'] or 'pcs'), f"{float(row['qty_avail'] or 0):g}",
                        f"{float(row['qty_total'] or 0):g}", f"{float(row['minimum_stock'] or 0):g}",
                        f"{reorder_qty:g}"]
                tid = row['tool_id']
                for col, val in enumerate(vals):
                    cell = ctk.CTkFrame(self._ls_table, fg_color=bg, corner_radius=0,
                                        cursor="hand2" if self.navigate_to_tool else "")
                    cell.grid(row=i+1, column=col, sticky="nsew")
                    txt = "#D8000C" if col == 6 and float(row['qty_avail']) == 0 else ("#E67E22" if col == 6 else "#1A1A1A")
                    fw = "bold" if col == 6 else "normal"
                    lbl = ctk.CTkLabel(cell, text=val, font=("Inter", 11, fw), text_color=txt,
                                       anchor="center", wraplength=min_sizes[col]-10,
                                       cursor="hand2" if self.navigate_to_tool else "")
                    lbl.pack(fill="both", expand=True, padx=4, pady=8)
                    if self.navigate_to_tool:
                        cell.bind("<Button-1>", lambda e, t=tid: self.navigate_to_tool(t))
                        lbl.bind("<Button-1>",  lambda e, t=tid: self.navigate_to_tool(t))

        import threading
        threading.Thread(target=_fetch, daemon=True).start()

    # ==========================================
    # TAB 7: Overdue Transactions Report
    # ==========================================
    def render_overdue_tab(self):
        frame = ctk.CTkFrame(self.tab_content, fg_color="white", corner_radius=10)
        frame.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=30, pady=(12, 4))
        ctk.CTkLabel(top, text="Overdue Transactions Report", font=("Inter", 16, "bold"), text_color="#1E4528").pack(side="left")
        ctk.CTkButton(top, text="⎙ Export PDF", width=110, fg_color="#1E4528", hover_color="#14301C",
                      font=("Inter", 11, "bold"), command=lambda: self.open_export_dialog("overdue")).pack(side="right")
        ctk.CTkLabel(frame, text="Active transactions where the project end date has already passed — sorted by most overdue.",
                     font=("Inter", 11), text_color="gray").grid(row=1, column=0, sticky="w", padx=30, pady=(0, 4))

        scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        scroll.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 10))

        self._ov_summary_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self._ov_summary_frame.pack(fill="x", pady=(0, 5))
        self._ov_chart_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self._ov_chart_frame.pack(fill="x", pady=(0, 5))
        self._ov_table = ctk.CTkFrame(scroll, fg_color="transparent")
        self._ov_table.pack(fill="x", pady=(5, 0))
        
        loading_lbl = ctk.CTkLabel(self._ov_table, text="Loading Overdue Transactions...", font=("Inter", 12, "italic"), text_color="gray")
        loading_lbl.pack(pady=20)

        sd, ed, valid = self.get_and_validate_dates()
        if not valid: return

        def _fetch():
            conn = get_connection()
            if not conn: return
            try:
                cursor = conn.cursor(dictionary=True)
                sd = self.start_date.get().strip()
                ed = self.end_date.get().strip()
                
                params = []
                date_filter = ""
                if sd:
                    date_filter += " AND tr.borrow_date >= %s"
                    params.append(sd)
                if ed:
                    date_filter += " AND tr.borrow_date <= %s"
                    params.append(ed + " 23:59:59")

                cursor.execute("""
                    SELECT u.employee_id, u.full_name, t.name as tool_name,
                           IFNULL(p.name, '—') as project_name,
                           p.end_date as due_date,
                           DATEDIFF(CURDATE(), p.end_date) as days_overdue,
                           tr.borrow_date,
                           IFNULL(t.price, 0) as price
                    FROM transaction tr
                    JOIN user u ON tr.user_id = u.user_id
                    JOIN tool t ON tr.tool_id = t.tool_id
                    LEFT JOIN projects p ON tr.project_id = p.project_id
                    WHERE tr.status = 'Active'
                      AND p.end_date < CURDATE() """ + date_filter + """
                    ORDER BY days_overdue DESC
                """, tuple(params))
                rows = cursor.fetchall()
            except Exception as e:
                self.after(0, lambda err=e: scroll.winfo_exists() and ctk.CTkLabel(scroll, text=f"Error: {err}", text_color="red").pack(pady=10))
                return
            finally:
                if conn.is_connected(): cursor.close(); conn.close()
            self.after(0, lambda: _render(rows))

        def _render(rows):
            if not self.winfo_exists() or not scroll.winfo_exists() or not loading_lbl.winfo_exists(): return
            loading_lbl.destroy()
            self._ov_data = rows
            for w in self._ov_summary_frame.winfo_children(): w.destroy()

            total_overdue = len(rows)
            unique_workers = len(set(r['employee_id'] for r in rows))
            max_days = max((int(r['days_overdue'] or 0) for r in rows), default=0)
            total_value = sum(float(r['price'] or 0) for r in rows)

            kpis = [
                ("🚨 Overdue Items", str(total_overdue), "#D8000C"),
                ("👷 Workers Involved", str(unique_workers), "#E67E22"),
                ("📅 Longest Overdue", f"{max_days} days", "#D8000C"),
                ("💰 At-Risk Value", f"₱{total_value:,.2f}", "#E67E22"),
            ]
            for label, val, color in kpis:
                card = ctk.CTkFrame(self._ov_summary_frame, fg_color="#F9FAFB", corner_radius=8)
                card.pack(side="left", expand=True, fill="x", padx=5, pady=5)
                ctk.CTkLabel(card, text=label, font=("Inter", 10), text_color="gray").pack(pady=(10, 2))
                ctk.CTkLabel(card, text=val, font=("Inter", 16, "bold"), text_color=color).pack(pady=(0, 10))

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
                fig = Figure(figsize=(7, 2.5), dpi=90)
                fig.patch.set_facecolor('#FFFFFF')
                ax = fig.add_subplot(111)
                ax.barh(names, days_vals, color="#E74C3C")
                ax.set_xlabel("Days Overdue", fontsize=8)
                ax.spines["top"].set_visible(False)
                ax.spines["right"].set_visible(False)
                fig.tight_layout()
                chart_canvas = FigureCanvasTkAgg(fig, master=self._ov_chart_frame)
                chart_canvas.draw()
                chart_canvas.get_tk_widget().pack(pady=10)
            # ────────────────────────────────────────────────────

            for w in self._ov_table.winfo_children(): w.destroy()
            headers = ["Emp ID", "Worker", "Tool", "Project", "Due Date", "Days Overdue", "Issued On", "Unit Price"]
            weights = [1, 3, 3, 3, 2, 2, 2, 2]
            min_sizes = [70, 130, 130, 130, 100, 110, 100, 100]
            for col, (w, mn) in enumerate(zip(weights, min_sizes)):
                self._ov_table.grid_columnconfigure(col, weight=w, minsize=mn, uniform="ov_cols")
            for col, text in enumerate(headers):
                cell = ctk.CTkFrame(self._ov_table, fg_color="#D8000C", corner_radius=0)
                cell.grid(row=0, column=col, sticky="nsew", pady=(0, 2))
                ctk.CTkLabel(cell, text=text, font=("Inter", 11, "bold"), text_color="white", anchor="center").pack(fill="both", expand=True, padx=2, pady=10)

            if not rows:
                ctk.CTkLabel(self._ov_table, text="✓ No overdue transactions found.", text_color="gray",
                             font=("Inter", 12)).grid(row=1, column=0, columnspan=len(headers), pady=30)
                return

            for i, row in enumerate(rows):
                days = int(row['days_overdue'] or 0)
                bg = "#FFF0F0" if i % 2 == 0 else "#FFF8F8"
                borrow_str = row['borrow_date'].strftime('%Y-%m-%d') if row.get('borrow_date') else "—"
                due_str = row['due_date'].strftime('%Y-%m-%d') if row.get('due_date') else "—"
                vals = [str(row['employee_id'] or 'Unknown'), str(row['full_name'] or 'Unknown'), str(row['tool_name'] or 'Unknown'),
                        str(row['project_name'] or '—'), str(due_str), f"{days} days",
                        str(borrow_str), f"₱{float(row['price'] or 0):,.2f}"]
                for col, val in enumerate(vals):
                    cell = ctk.CTkFrame(self._ov_table, fg_color=bg, corner_radius=0)
                    cell.grid(row=i+1, column=col, sticky="nsew")
                    txt = "#D8000C" if col == 5 else "#1A1A1A"
                    fw = "bold" if col == 5 else "normal"
                    ctk.CTkLabel(cell, text=val, font=("Inter", 11, fw), text_color=txt,
                                 anchor="center", wraplength=min_sizes[col]-10).pack(fill="both", expand=True, padx=4, pady=10)

        import threading
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
        }
        title = report_titles.get(report_type, "Report")

        dialog = ctk.CTkToplevel(self)
        dialog.title(f"Export: {title}")
        dialog.geometry("460x320")
        dialog.configure(fg_color="#F4F6F8")
        dialog.attributes("-topmost", True)
        dialog.grab_set()
        dialog.resizable(False, False)
        dialog.update_idletasks()
        sw, sh = dialog.winfo_screenwidth(), dialog.winfo_screenheight()
        dialog.geometry(f"460x320+{(sw-460)//2}+{(sh-320)//2}")

        card = ctk.CTkFrame(dialog, fg_color="white", corner_radius=10,
                            border_width=1, border_color="#E0E0E0")
        card.pack(padx=20, pady=20, fill="both", expand=True)

        ctk.CTkLabel(card, text="Export Report",
                     font=("Inter", 16, "bold"), text_color="#1A1A1A").pack(anchor="w", padx=20, pady=(18, 2))
        ctk.CTkLabel(card, text=title,
                     font=("Inter", 12), text_color="#1E4528").pack(anchor="w", padx=20, pady=(0, 12))

        ctk.CTkFrame(card, height=1, fg_color="#E0E0E0").pack(fill="x", padx=20, pady=(0, 12))

        ctk.CTkLabel(card, text="Additional Criteria / Notes  (optional)",
                     font=("Inter", 11, "bold"), text_color="#555555").pack(anchor="w", padx=20, pady=(4, 4))
        notes_entry = ctk.CTkEntry(card, placeholder_text="e.g., Site A only, Q1 review...")
        notes_entry.pack(fill="x", padx=20, pady=(0, 16))

        def do_export():
            note = notes_entry.get().strip()
            dialog.destroy()
            self.export_pdf(report_type, criteria_note=note or None)

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 16))
        ctk.CTkButton(btn_row, text="⎙ Export Now", fg_color="#1E4528", hover_color="#14301C",
                      font=("Inter", 12, "bold"), command=do_export).pack(side="left", expand=True, fill="x", padx=(0, 8))
        ctk.CTkButton(btn_row, text="Cancel", width=90, fg_color="#E0E0E0",
                      text_color="black", hover_color="#CCCCCC",
                      command=dialog.destroy).pack(side="right")

        notes_entry.bind("<Return>", lambda e: do_export())
        notes_entry.focus_set()

    # ==========================================
    # PDF Export (shared across all tabs)
    # ==========================================
    def export_pdf(self, report_type, criteria_note=None):
        try:
            canvas_width = 900
            line_h = 28
            timestamp = datetime.now().strftime("%B %d, %Y %I:%M %p")

            conn = get_connection()
            if not conn:
                messagebox.showerror("Export Error", "Cannot connect to database.", parent=self.winfo_toplevel())
                return
            try:
                cursor = conn.cursor(dictionary=True)

                if report_type == "abc":
                    title = "Inventory ABC Analysis Report"
                    col_labels = ["Rank", "Tool ID", "Tool Name", "Times Borrowed", "Cumulative%", "Category"]
                    cursor.execute("""
                        SELECT t.tool_id, t.name, COUNT(tr.transaction_id) as usage_count
                        FROM tool t
                        LEFT JOIN transaction tr ON t.tool_id = tr.tool_id
                        WHERE t.is_archived = 0
                        GROUP BY t.tool_id, t.name
                        ORDER BY usage_count DESC
                    """)
                    tools = cursor.fetchall()
                    total_usage = sum(t['usage_count'] for t in tools) or 1
                    cumulative = 0
                    rows = []
                    for i, tool in enumerate(tools):
                        cumulative += tool['usage_count']
                        cum_pct = (cumulative / total_usage) * 100
                        cat = "A (High)" if cum_pct <= 70 else ("B (Medium)" if cum_pct <= 90 else "C (Low)")
                        rows.append([f"#{i+1}", str(tool['tool_id']), tool['name'],
                                     str(tool['usage_count']), f"{cum_pct:.1f}%", cat])

                elif report_type == "usage":
                    title = "Tool Usage Report"
                    col_labels = ["Tool ID", "Name", "Tag ID", "Total Borrowed", "Currently Out", "Qty Avail", "Condition"]
                    cursor.execute("""
                        SELECT t.tool_id, t.name, IFNULL(t.tag_id,'—') as tag_id,
                               COUNT(tr.transaction_id) as total_borrowed,
                               IFNULL(i.quantity_total - i.quantity_available, 0) as currently_out,
                               IFNULL(i.quantity_available,0) as qty_avail,
                               t.`condition`
                        FROM tool t
                        LEFT JOIN inventory i ON t.tool_id = i.tool_id
                        LEFT JOIN transaction tr ON t.tool_id = tr.tool_id
                        WHERE t.is_archived = 0
                        GROUP BY t.tool_id, t.name, t.tag_id, i.quantity_total, i.quantity_available, t.`condition`
                        ORDER BY total_borrowed DESC
                    """)
                    rows = [[str(r['tool_id']), r['name'], r['tag_id'],
                             str(r['total_borrowed']), str(r['currently_out'] or 0),
                             f"{float(r['qty_avail']):g}", r['condition']]
                            for r in cursor.fetchall()]

                elif report_type == "activity":
                    title = "Employee Activity Report"
                    col_labels = ["Employee ID", "Full Name", "Role", "Total Borrows", "Active", "Returned"]
                    cursor.execute("""
                        SELECT u.employee_id, u.full_name, u.role,
                               COUNT(tr.transaction_id) as total_borrows,
                               SUM(CASE WHEN tr.status='Active' THEN 1 ELSE 0 END) as active_borrows,
                               SUM(CASE WHEN tr.status='Returned' THEN 1 ELSE 0 END) as returned_borrows
                        FROM user u
                        LEFT JOIN transaction tr ON u.user_id = tr.user_id
                        WHERE IFNULL(u.status, 'Active') != 'Archived'
                        GROUP BY u.user_id, u.employee_id, u.full_name, u.role
                        ORDER BY total_borrows DESC
                    """)
                    rows = [[r['employee_id'], r['full_name'], r['role'],
                             str(r['total_borrows']), str(r['active_borrows'] or 0),
                             str(r['returned_borrows'] or 0)]
                            for r in cursor.fetchall()]

                elif report_type == "allocation":
                    title = "Project Allocation Report"
                    col_labels = ["Project", "Client", "Location", "Status", "Tool", "Requested", "Issued", "Retrieved", "Flag"]
                    cursor.execute("""
                        SELECT p.name as project_name, p.client, p.location, p.status,
                               t.name as tool_name, pr.quantity as requested,
                               COUNT(tr.transaction_id) as issued,
                               IFNULL(SUM(CASE WHEN tr.status='Returned' THEN 1 ELSE 0 END), 0) as retrieved
                        FROM projects p
                        JOIN project_requirements pr ON p.project_id = pr.project_id
                        JOIN tool t ON pr.tool_id = t.tool_id
                        LEFT JOIN transaction tr ON tr.project_id = p.project_id AND tr.tool_id = t.tool_id
                        WHERE p.archived_at IS NULL
                        GROUP BY p.project_id, t.tool_id, pr.quantity, pr.status
                        ORDER BY p.status ASC, p.name ASC, t.name ASC
                    """)
                    rows = [[r['project_name'], r['client'] or '—', r['location'] or '—', r['status'],
                             r['tool_name'], str(int(r['requested'])), str(int(r['issued'])), str(int(r['retrieved'])),
                             "Unreturned" if int(r['issued']) - int(r['retrieved']) > 0 and r['status'] == "Completed" else "—"]
                            for r in cursor.fetchall()]

                elif report_type == "damage":
                    title = "Damage, Loss & Maintenance Report"
                    col_labels = ["Tool ID", "Tool Name", "Unit Price", "Condition", "Returned By", "Return Date", "Notes"]
                    cursor.execute("""
                        SELECT t.tool_id, t.name, IFNULL(t.price, 0) as price,
                               tr.condition_at_return as cond_flag,
                               u.full_name as returned_by,
                               DATE_FORMAT(tr.return_date, '%Y-%m-%d') as return_date,
                               IFNULL(tr.condition_return_notes, '—') as notes
                        FROM transaction tr
                        JOIN tool t ON tr.tool_id = t.tool_id
                        LEFT JOIN user u ON tr.user_id = u.user_id
                        WHERE tr.type = 'Retrieval'
                          AND tr.condition_at_return IN ('Damaged', 'Lost', 'Needs Repair')
                        ORDER BY tr.return_date DESC
                    """)
                    rows = [[str(r['tool_id']), r['name'], f"P{float(r['price']):,.2f}",
                             r['cond_flag'], r['returned_by'] or '—', r['return_date'] or '—', r['notes']]
                            for r in cursor.fetchall()]

                elif report_type == "lowstock":
                    title = "Low Stock / Procurement Report"
                    col_labels = ["PID", "Name", "Type", "Category", "Supplier", "UoM", "Available", "Min Stock", "Reorder Qty"]
                    cursor.execute("""
                        SELECT t.tool_id, t.name, t.item_type, t.category,
                               IFNULL(t.supplier, '—') as supplier,
                               IFNULL(t.unit_of_measure, 'pcs') as uom,
                               IFNULL(i.quantity_available, 0) as qty_avail,
                               IFNULL(i.minimum_stock, 0) as minimum_stock
                        FROM tool t
                        JOIN inventory i ON t.tool_id = i.tool_id
                        WHERE t.is_archived = 0
                          AND i.minimum_stock > 0
                        AND i.quantity_available < i.minimum_stock
                        ORDER BY (i.quantity_available / NULLIF(i.minimum_stock, 0)) ASC
                    """)
                    rows = [[str(r['tool_id']), r['name'], r['item_type'], r['category'],
                             r['supplier'], r['uom'], f"{float(r['qty_avail']):g}",
                             f"{float(r['minimum_stock']):g}",
                             f"{max(0, float(r['minimum_stock'])*2 - float(r['qty_avail'])):g}"]
                            for r in cursor.fetchall()]

                elif report_type == "overdue":
                    title = "Overdue Transactions Report"
                    col_labels = ["Emp ID", "Worker", "Tool", "Project", "Due Date", "Days Overdue", "Issued On", "Unit Price"]
                    cursor.execute("""
                        SELECT u.employee_id, u.full_name, t.name as tool_name,
                               IFNULL(p.name, '—') as project_name,
                               p.end_date as due_date,
                               DATEDIFF(CURDATE(), p.end_date) as days_overdue,
                               tr.borrow_date,
                               IFNULL(t.price, 0) as price
                        FROM transaction tr
                        JOIN user u ON tr.user_id = u.user_id
                        JOIN tool t ON tr.tool_id = t.tool_id
                        LEFT JOIN projects p ON tr.project_id = p.project_id
                        WHERE tr.status = 'Active'
                          AND p.end_date < CURDATE()
                        ORDER BY days_overdue DESC
                    """)
                    rows = [[r['employee_id'], r['full_name'], r['tool_name'], r['project_name'],
                             r['due_date'].strftime('%Y-%m-%d') if r.get('due_date') else '—',
                             str(int(r['days_overdue'] or 0)) + " days",
                             r['borrow_date'].strftime('%Y-%m-%d') if r.get('borrow_date') else '—',
                             f"P{float(r['price']):,.2f}"]
                            for r in cursor.fetchall()]
                else:
                    rows = []
                    title = "Report"
                    col_labels = []
            finally:
                if conn.is_connected():
                    cursor.close()
                    conn.close()

            total_rows = len(rows)
            criteria_parts = ["Period: All Time (No filters applied)"]
            if criteria_note:
                criteria_parts.append(f"Notes: {criteria_note}")
            criteria = "  |  ".join(criteria_parts)

            try:
                font_title = ImageFont.truetype("arialbd.ttf", 26)
                font_header = ImageFont.truetype("arialbd.ttf", 16)
                font_body = ImageFont.truetype("arial.ttf", 14)
            except IOError:
                font_title = font_header = font_body = ImageFont.load_default()

            col_count = len(col_labels)
            col_w = (canvas_width - 60) // col_count
            col_x = [30 + i * col_w for i in range(col_count)]

            def wrap_cell(text, font, max_w):
                words = str(text).split()
                lines, cur = [], ""
                for word in words:
                    test = (cur + " " + word).strip()
                    try:
                        w = font.getlength(test)
                    except AttributeError:
                        w = len(test) * 8
                    if w <= max_w - 4:
                        cur = test
                    else:
                        if cur:
                            lines.append(cur)
                        cur = word
                if cur:
                    lines.append(cur)
                return lines or [""]

            wrapped_rows = []
            for row in rows:
                wrapped = [wrap_cell(cell, font_body, col_w) for cell in row]
                row_h = max(len(lines) for lines in wrapped) * line_h
                wrapped_rows.append((wrapped, row_h))

            total_height = sum(rh for _, rh in wrapped_rows)
            canvas_height = 185 + total_height + 80
            canvas = Image.new("RGB", (canvas_width, canvas_height), "white")
            draw = ImageDraw.Draw(canvas)

            draw.text((30, 20), "CHAMPION FINE TOOLING CORPORATION", fill="#1E4528", font=font_title)
            draw.text((30, 60), title, fill="black", font=font_header)
            draw.text((30, 90), f"Generated: {timestamp}", fill="gray", font=font_body)
            draw.text((30, 115), criteria, fill="#444444", font=font_body)
            draw.line((30, 145, canvas_width - 30, 145), fill="#1E4528", width=2)

            y = 160
            for j, label in enumerate(col_labels):
                draw.text((col_x[j], y), label, fill="#1E4528", font=font_header)
            draw.line((30, y + 20, canvas_width - 30, y + 20), fill="#CCCCCC", width=1)
            y += 28

            for r_idx, (wrapped, row_h) in enumerate(wrapped_rows):
                fill = "#F9FAFB" if r_idx % 2 == 0 else "white"
                draw.rectangle([30, y - 2, canvas_width - 30, y + row_h - 4], fill=fill)
                for j, lines in enumerate(wrapped):
                    for li, line in enumerate(lines):
                        draw.text((col_x[j], y + li * line_h), line, fill="black", font=font_body)
                y += row_h

            draw.line((30, y + 10, canvas_width - 30, y + 10), fill="#CCCCCC", width=1)
            draw.text((30, y + 20), f"Total Records: {total_rows}", fill="gray", font=font_body)

            temp_dir = tempfile.gettempdir()
            fname = f"Report_{report_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            fpath = os.path.join(temp_dir, fname)
            canvas.save(fpath, "PDF", resolution=100.0)
            os.startfile(fpath)

        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to generate PDF:\n{e}",
                                 parent=self.winfo_toplevel())