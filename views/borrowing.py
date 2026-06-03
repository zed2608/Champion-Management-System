import customtkinter as ctk
from tkinter import messagebox
from database import get_connection
import cv2
from pyzbar.pyzbar import decode, ZBarSymbol
import os
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime, timedelta, date as _date
import calendar as _cal

class BorrowingView(ctk.CTkFrame): 
    def __init__(self, parent, user_info=None, *args, **kwargs):
        super().__init__(parent, fg_color="transparent")
        
        self.user_info = user_info or {}
        
        self.grid_columnconfigure(0, weight=1) 
        self.grid_rowconfigure(0, weight=0) # Top Bar
        self.grid_rowconfigure(1, weight=1) # Content Area

        self.active_borrow_user_id = None
        self.active_borrow_user_name = None
        self.borrow_cart = [] 
        self.current_project_reqs = [] 
        self.active_projects_map = {}
        
        self.active_return_user_id = None
        self.active_return_tool_id = None
        self.max_returnable = 0

        self.build_top_tabs()

    def build_top_tabs(self):
        top_bar = ctk.CTkFrame(self, fg_color="transparent")
        top_bar.grid(row=0, column=0, sticky="ew", padx=20, pady=(10, 15))

        ctk.CTkLabel(top_bar, text="Tool Management", font=("Inter", 16, "bold"), text_color="#1E4528").pack(side="left")

        tabs = ["📤 Tool Issuance", "📥 Tool Retrieval", "📅 Deployment Schedule"]
        self.tab_var = ctk.StringVar(value=tabs[0])

        self.seg_btn = ctk.CTkSegmentedButton(
            top_bar, values=tabs, variable=self.tab_var, command=self.switch_tab,
            fg_color="#F0F0F0", selected_color="#1E4528", selected_hover_color="#14301C"
        )
        self.seg_btn.pack(side="right")

        self.tab_content = ctk.CTkFrame(self, fg_color="transparent")
        self.tab_content.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 20))
        self.tab_content.grid_columnconfigure(0, weight=1, minsize=380) # Left Form
        self.tab_content.grid_columnconfigure(1, weight=2, minsize=750) # Right History Table
        self.tab_content.grid_rowconfigure(0, weight=1)
        
        self.switch_tab(tabs[0])

    def switch_tab(self, selected_tab):
        for widget in self.tab_content.winfo_children():
            widget.destroy()

        if selected_tab == "📅 Deployment Schedule":
            self.build_calendar_tab(self.tab_content)
            return

        if selected_tab == "📤 Tool Issuance":
            self.build_issuance_tab(self.tab_content)
            self.b_emp_id.focus_set()
        else:
            self.build_retrieval_tab(self.tab_content)
            self.r_emp_id.focus_set()

        self.build_history_table(self.tab_content)
        self.load_transaction_history()

    # ══════════════════════════════════════════════════════════
    # DEPLOYMENT SCHEDULE CALENDAR
    # ══════════════════════════════════════════════════════════
    def build_calendar_tab(self, parent):
        now = datetime.now()
        self._cal_year      = now.year
        self._cal_month     = now.month
        self._cal_selected  = None
        self._cal_projects_by_day = {}

        outer = ctk.CTkFrame(parent, fg_color="transparent")
        outer.grid(row=0, column=0, columnspan=2, sticky="nsew")
        outer.grid_columnconfigure(0, weight=3)
        outer.grid_columnconfigure(1, weight=1)
        outer.grid_rowconfigure(0, weight=1)

        # Left: scrollable calendar card
        self._cal_card = ctk.CTkScrollableFrame(outer, fg_color="white", corner_radius=10)
        self._cal_card.grid(row=0, column=0, sticky="nsew", padx=(10, 5))

        # Right: day-detail card
        self._cal_detail = ctk.CTkFrame(outer, fg_color="white", corner_radius=10)
        self._cal_detail.grid(row=0, column=1, sticky="nsew", padx=(5, 10))

        self._render_calendar()
        self._render_day_detail(None)

    # ── Query ──────────────────────────────────────────────────
    def _cal_query_projects(self):
        import calendar as _cal_mod
        first = _date(self._cal_year, self._cal_month, 1)
        last  = _date(self._cal_year, self._cal_month,
                      _cal_mod.monthrange(self._cal_year, self._cal_month)[1])
        by_day = {}
        conn = get_connection()
        if not conn:
            return by_day
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT project_id, name, client, start_date, end_date, status
                FROM projects
                WHERE status NOT IN ('Cancelled', 'Completed')
                  AND start_date <= %s AND end_date >= %s
                ORDER BY start_date
            """, (last, first))
            for p in cursor.fetchall():
                s = max(p["start_date"], first)
                e = min(p["end_date"],   last)
                cur = s
                while cur <= e:
                    if cur.month == self._cal_month:
                        by_day.setdefault(cur.day, []).append(p)
                    cur += timedelta(days=1)
        except Exception:
            pass
        finally:
            if conn.is_connected():
                cursor.close(); conn.close()
        return by_day

    # ── Render full month grid ─────────────────────────────────
    def _render_calendar(self):
        import calendar as _cal_mod
        card = self._cal_card
        for w in card.winfo_children():
            w.destroy()

        self._cal_projects_by_day = self._cal_query_projects()

        # ── Navigation row ──────────────────────────────────────
        nav = ctk.CTkFrame(card, fg_color="transparent")
        nav.pack(fill="x", padx=20, pady=(20, 8))

        ctk.CTkButton(nav, text="◀", width=34, height=34,
                      fg_color="#E0E0E0", text_color="#1A1A1A", hover_color="#CCCCCC",
                      font=("Inter", 13, "bold"),
                      command=self._cal_prev).pack(side="left")

        month_label = datetime(self._cal_year, self._cal_month, 1).strftime("%B  %Y")
        ctk.CTkLabel(nav, text=month_label,
                     font=("Inter", 16, "bold"), text_color="#1A1A1A").pack(side="left", padx=14)

        ctk.CTkButton(nav, text="▶", width=34, height=34,
                      fg_color="#E0E0E0", text_color="#1A1A1A", hover_color="#CCCCCC",
                      font=("Inter", 13, "bold"),
                      command=self._cal_next).pack(side="left")

        ctk.CTkButton(nav, text="Today", width=74, height=34,
                      fg_color="#1E4528", hover_color="#14301C",
                      font=("Inter", 11, "bold"),
                      command=self._cal_goto_today).pack(side="right")

        # ── Legend ──────────────────────────────────────────────
        legend = ctk.CTkFrame(card, fg_color="#F9FAFB", corner_radius=8)
        legend.pack(fill="x", padx=20, pady=(0, 12))
        STATUS_COLORS = {
            "Pending":  "#F39C12",
            "Approved": "#3498DB",
            "Ongoing":  "#2ECC71",
            "Overdue":  "#E74C3C",
        }
        for status, color in STATUS_COLORS.items():
            chip = ctk.CTkFrame(legend, fg_color="transparent")
            chip.pack(side="left", padx=14, pady=7)
            ctk.CTkFrame(chip, fg_color=color, width=12, height=12,
                         corner_radius=6).pack(side="left", padx=(0, 5))
            ctk.CTkLabel(chip, text=status, font=("Inter", 10),
                         text_color="#555555").pack(side="left")

        # ── Day-of-week header ───────────────────────────────────
        dow = ctk.CTkFrame(card, fg_color="transparent")
        dow.pack(fill="x", padx=20)
        DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        for i, d in enumerate(DOW):
            dow.grid_columnconfigure(i, weight=1)
            ctk.CTkLabel(dow, text=d, font=("Inter", 11, "bold"),
                         text_color="#888888").grid(row=0, column=i, pady=6, sticky="ew")

        # ── Month grid ──────────────────────────────────────────
        grid_f = ctk.CTkFrame(card, fg_color="transparent")
        grid_f.pack(fill="x", padx=20, pady=(0, 20))
        for i in range(7):
            grid_f.grid_columnconfigure(i, weight=1)

        today         = _date.today()
        first_weekday = _date(self._cal_year, self._cal_month, 1).weekday()
        total_days    = _cal_mod.monthrange(self._cal_year, self._cal_month)[1]
        STATUS_COLORS_EXT = {**STATUS_COLORS, "Completed": "#95A5A6"}

        # Pre-enforce uniform row heights for all rows in this month's grid
        for r in range(6):
            grid_f.grid_rowconfigure(r, minsize=74)

        col, row_idx = first_weekday, 0

        # blank leading cells — grid_propagate(False) enforces height=74
        for c in range(first_weekday):
            blank = ctk.CTkFrame(grid_f, fg_color="transparent", height=74)
            blank.grid(row=0, column=c, padx=2, pady=2, sticky="nsew")
            blank.grid_propagate(False)

        for day in range(1, total_days + 1):
            cur_date = _date(self._cal_year, self._cal_month, day)
            projs    = self._cal_projects_by_day.get(day, [])
            is_today = (cur_date == today)
            is_sel   = (self._cal_selected == day)

            if is_today:
                bg = "#1E4528";  num_col = "white"
            elif is_sel:
                bg = "#E8F5E9";  num_col = "#1E4528"
            elif projs:
                bg = "#F0F8FF";  num_col = "#1A1A1A"
            else:
                bg = "#F9FAFB";  num_col = "#7F8C8D"

            cell = ctk.CTkFrame(grid_f, fg_color=bg, corner_radius=8, height=74)
            cell.grid(row=row_idx, column=col, padx=2, pady=2, sticky="nsew")
            cell.grid_propagate(False)
            cell.configure(cursor="hand2")
            cell.bind("<Button-1>", lambda e, d=day: self._cal_click(d))

            num = ctk.CTkLabel(cell, text=str(day),
                               font=("Inter", 12, "bold"), text_color=num_col)
            num.pack(anchor="nw", padx=7, pady=(5, 0))
            num.configure(cursor="hand2")
            num.bind("<Button-1>", lambda e, d=day: self._cal_click(d))

            if projs:
                dots = ctk.CTkFrame(cell, fg_color="transparent")
                dots.pack(anchor="sw", padx=5, pady=(0, 5))
                for p in projs[:4]:
                    raw = p["status"].replace(" (OVERDUE)", "")
                    clr = "#E74C3C" if "OVERDUE" in p["status"] else STATUS_COLORS_EXT.get(raw, "#95A5A6")
                    ctk.CTkFrame(dots, fg_color=clr, width=8, height=8,
                                 corner_radius=4).pack(side="left", padx=1)
                if len(projs) > 4:
                    ctk.CTkLabel(dots, text=f"+{len(projs)-4}",
                                 font=("Inter", 8), text_color="#888888").pack(side="left")

            col += 1
            if col == 7:
                col = 0
                row_idx += 1

        # trailing blank cells to pad the last row to full width
        while row_idx < 6:
            blank = ctk.CTkFrame(grid_f, fg_color="transparent", height=74)
            blank.grid(row=row_idx, column=col, padx=2, pady=2, sticky="nsew")
            blank.grid_propagate(False)
            col += 1
            if col == 7:
                col = 0
                row_idx += 1

    # ── Day-detail panel ──────────────────────────────────────
    def _render_day_detail(self, day):
        card = self._cal_detail
        for w in card.winfo_children():
            w.destroy()

        if day is None:
            ctk.CTkLabel(card, text="📅", font=("Inter", 42), text_color="#CCCCCC").pack(pady=(50, 8))
            ctk.CTkLabel(card, text="Select a day\nto view projects",
                         font=("Inter", 12), text_color="#AAAAAA", justify="center").pack()
            return

        date_str = datetime(self._cal_year, self._cal_month, day).strftime("%B %d, %Y")
        ctk.CTkLabel(card, text=date_str,
                     font=("Inter", 13, "bold"), text_color="#1A1A1A").pack(pady=(20, 4), padx=15)

        projs = self._cal_projects_by_day.get(day, [])
        STATUS_COLORS = {"Pending": "#F39C12", "Approved": "#3498DB",
                         "Ongoing": "#2ECC71", "Completed": "#95A5A6"}

        if not projs:
            ctk.CTkLabel(card, text="No projects active\non this day.",
                         font=("Inter", 11), text_color="gray", justify="center").pack(pady=20)
            return

        ctk.CTkLabel(card, text=f"{len(projs)} project(s) active",
                     font=("Inter", 10), text_color="gray").pack(padx=15, pady=(0, 8))

        scroll = ctk.CTkScrollableFrame(card, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=8, pady=(0, 10))

        for p in projs:
            raw    = p["status"].replace(" (OVERDUE)", "")
            color  = "#E74C3C" if "OVERDUE" in p["status"] else STATUS_COLORS.get(raw, "#95A5A6")
            pcard  = ctk.CTkFrame(scroll, fg_color="#F9FAFB", corner_radius=8)
            pcard.pack(fill="x", pady=4)
            ctk.CTkLabel(pcard, text=p["name"],
                         font=("Inter", 11, "bold"), text_color="#1A1A1A",
                         wraplength=165, justify="left").pack(anchor="w", padx=10, pady=(8, 2))
            ctk.CTkLabel(pcard, text=p["client"],
                         font=("Inter", 10), text_color="#888888",
                         wraplength=165, justify="left").pack(anchor="w", padx=10)
            dates_txt = f"{p['start_date']}  →  {p['end_date']}"
            ctk.CTkLabel(pcard, text=dates_txt,
                         font=("Inter", 9), text_color="#AAAAAA").pack(anchor="w", padx=10)
            ctk.CTkLabel(pcard, text=p["status"],
                         font=("Inter", 10, "bold"), text_color=color).pack(anchor="w", padx=10, pady=(2, 8))

    # ── Navigation callbacks ───────────────────────────────────
    def _cal_prev(self):
        if self._cal_month == 1:
            self._cal_year -= 1; self._cal_month = 12
        else:
            self._cal_month -= 1
        self._cal_selected = None
        self._render_calendar()
        self._render_day_detail(None)

    def _cal_next(self):
        if self._cal_month == 12:
            self._cal_year += 1; self._cal_month = 1
        else:
            self._cal_month += 1
        self._cal_selected = None
        self._render_calendar()
        self._render_day_detail(None)

    def _cal_goto_today(self):
        now = datetime.now()
        self._cal_year = now.year; self._cal_month = now.month
        self._cal_selected = now.day
        self._render_calendar()
        self._render_day_detail(now.day)

    def _cal_click(self, day):
        self._cal_selected = day
        self._render_calendar()
        self._render_day_detail(day)

    # --- SIDE-BY-SIDE UI BUILDERS ---

    def build_issuance_tab(self, parent):
        form_card = ctk.CTkScrollableFrame(parent, fg_color="white", corner_radius=10, width=380)
        form_card.grid(row=0, column=0, sticky="nsew", padx=(10, 5))

        ctk.CTkLabel(form_card, text="Project Tool Deployment", font=("Inter", 16, "bold"), text_color="#1E4528").pack(anchor="w", padx=20, pady=(20, 5))
        ctk.CTkLabel(form_card, text="1. Scan ID  ➔  2. Select Project  ➔  3. Scan Required Tools", font=("Inter", 11), text_color="gray").pack(anchor="w", padx=20, pady=(0, 15))

        ctk.CTkLabel(form_card, text="1. Assignee ID (Employee ID)", font=("Inter", 11, "bold"), text_color="#1A1A1A").pack(anchor="w", padx=20)
        b_emp_row = ctk.CTkFrame(form_card, fg_color="transparent")
        b_emp_row.pack(fill="x", padx=20, pady=(5, 5))
        self.b_emp_id = ctk.CTkEntry(b_emp_row, placeholder_text="Scan ID & Press Enter...")
        self.b_emp_id.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.b_emp_id.bind("<Return>", lambda e: self.verify_borrower())
        ctk.CTkButton(b_emp_row, text="📷 Scan", width=65, fg_color="#3498DB", hover_color="#2980B9", font=("Inter", 11, "bold"), command=lambda: self.open_scanner(self.b_emp_id, self.verify_borrower)).pack(side="left")
        
        self.b_user_name = ctk.CTkLabel(form_card, text="Name: Pending Scan...", font=("Inter", 11), text_color="gray")
        self.b_user_name.pack(anchor="w", padx=20, pady=(0, 15))

        ctk.CTkLabel(form_card, text="2. Select Target Project", font=("Inter", 11, "bold"), text_color="#1A1A1A").pack(anchor="w", padx=20)
        self.b_project_menu = ctk.CTkOptionMenu(form_card, values=["Scan Employee ID first..."], fg_color="#F9FAFB", text_color="black", state="disabled", command=self.on_project_selected)
        self.b_project_menu.pack(fill="x", padx=20, pady=(5, 5))

        self.proj_req_frame = ctk.CTkFrame(form_card, fg_color="#FFF8F0", corner_radius=5, border_width=1, border_color="#E0E0E0")
        self.proj_req_frame.pack(fill="x", padx=20, pady=(5, 15))
        ctk.CTkLabel(self.proj_req_frame, text="Project Requirements will appear here...", font=("Inter", 11, "italic"), text_color="gray").pack(pady=10)

        ctk.CTkLabel(form_card, text="3. Scan Required Tools", font=("Inter", 11, "bold"), text_color="#1A1A1A").pack(anchor="w", padx=20)
        b_tag_row = ctk.CTkFrame(form_card, fg_color="transparent")
        b_tag_row.pack(fill="x", padx=20, pady=(5, 5))
        self.b_tag_id = ctk.CTkEntry(b_tag_row, placeholder_text="Scan Tool Tag & Press Enter...", state="disabled") 
        self.b_tag_id.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.b_tag_id.bind("<Return>", lambda e: self.add_tool_to_cart())
        self.b_scan_btn = ctk.CTkButton(b_tag_row, text="📷 Scan", width=65, fg_color="#3498DB", hover_color="#2980B9", font=("Inter", 11, "bold"), command=lambda: self.open_scanner(self.b_tag_id, self.add_tool_to_cart), state="disabled")
        self.b_scan_btn.pack(side="left")

        self.cart_frame = ctk.CTkScrollableFrame(form_card, fg_color="#F9FAFB", height=120, corner_radius=5)
        self.cart_frame.pack(fill="x", padx=20, pady=(10, 20))
        self.refresh_cart_ui() 

        ctk.CTkButton(form_card, text="Issue Tools & Print Receipt", height=40, fg_color="#1E4528", hover_color="#14301C", font=("Inter", 13, "bold"), command=self.execute_borrow).pack(fill="x", padx=20, pady=(0, 20))

    def build_retrieval_tab(self, parent):
        form_card = ctk.CTkScrollableFrame(parent, fg_color="white", corner_radius=10, width=380)
        form_card.grid(row=0, column=0, sticky="nsew", padx=(10, 5))

        ctk.CTkLabel(form_card, text="Secure Tool Retrieval", font=("Inter", 16, "bold"), text_color="#F1C40F").pack(anchor="w", padx=20, pady=(20, 5))
        ctk.CTkLabel(form_card, text="Scan Employee ID and Tool Tag (or enter TRN) to restock.", font=("Inter", 11), text_color="gray").pack(anchor="w", padx=20, pady=(0, 15))

        ctk.CTkLabel(form_card, text="1. Surrendering Employee ID", font=("Inter", 11, "bold"), text_color="#1A1A1A").pack(anchor="w", padx=20)
        r_emp_row = ctk.CTkFrame(form_card, fg_color="transparent")
        r_emp_row.pack(fill="x", padx=20, pady=(5, 5))
        self.r_emp_id = ctk.CTkEntry(r_emp_row, placeholder_text="Scan ID & Press Enter...")
        self.r_emp_id.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.r_emp_id.bind("<Return>", lambda e: self.verify_return_employee())
        ctk.CTkButton(r_emp_row, text="📷 Scan", width=65, fg_color="#3498DB", hover_color="#2980B9", font=("Inter", 11, "bold"), command=lambda: self.open_scanner(self.r_emp_id, self.verify_return_employee)).pack(side="left")

        self.r_user_name = ctk.CTkLabel(form_card, text="Name: Pending Scan...", font=("Inter", 11), text_color="gray")
        self.r_user_name.pack(anchor="w", padx=20, pady=(0, 15))

        ctk.CTkLabel(form_card, text="2. Tag ID or Receipt TRN (e.g., TRN-42)", font=("Inter", 11, "bold"), text_color="#1A1A1A").pack(anchor="w", padx=20)
        r_tag_row = ctk.CTkFrame(form_card, fg_color="transparent")
        r_tag_row.pack(fill="x", padx=20, pady=(5, 5))
        self.r_tag_id = ctk.CTkEntry(r_tag_row, placeholder_text="Scan Tag or enter TRN...")
        self.r_tag_id.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.r_tag_id.bind("<Return>", lambda e: self.verify_tool_for_return())
        ctk.CTkButton(r_tag_row, text="📷 Scan", width=65, fg_color="#3498DB", hover_color="#2980B9", font=("Inter", 11, "bold"), command=lambda: self.open_scanner(self.r_tag_id, self.verify_tool_for_return)).pack(side="left")

        self.r_record_info = ctk.CTkLabel(form_card, text="Record: Pending Scan...", font=("Inter", 11), text_color="gray", justify="left")
        self.r_record_info.pack(anchor="w", padx=20, pady=(0, 15))

        cond_qty_row = ctk.CTkFrame(form_card, fg_color="transparent")
        cond_qty_row.pack(fill="x", padx=20, pady=(5, 20))
        cond_qty_row.grid_columnconfigure(0, weight=2)
        cond_qty_row.grid_columnconfigure(1, weight=1)

        c_frame = ctk.CTkFrame(cond_qty_row, fg_color="transparent")
        c_frame.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        ctk.CTkLabel(c_frame, text="3. Return Condition", font=("Inter", 11, "bold"), text_color="#1A1A1A").pack(anchor="w")
        self.r_condition = ctk.CTkOptionMenu(c_frame, values=["Good", "Needs Repair", "Damaged", "Lost"], fg_color="#F9FAFB", text_color="black")
        self.r_condition.pack(fill="x", pady=(5, 0))
        ctk.CTkLabel(c_frame, text="Condition Details", font=("Inter", 10), text_color="gray").pack(anchor="w", pady=(10, 0))
        self.r_condition_desc = ctk.CTkTextbox(c_frame, height=80, fg_color="#F9FAFB", border_width=1, border_color="#E0E0E0")
        self.r_condition_desc.pack(fill="x", pady=(5, 0))

        q_frame = ctk.CTkFrame(cond_qty_row, fg_color="transparent")
        q_frame.grid(row=0, column=1, sticky="ew", padx=(5, 0))
        ctk.CTkLabel(q_frame, text="Qty", font=("Inter", 11, "bold"), text_color="#1A1A1A").pack(anchor="w")
        self.r_qty = ctk.CTkEntry(q_frame, placeholder_text="1")
        self.r_qty.pack(fill="x", pady=(5, 0))
        self.r_qty.insert(0, "1")

        ctk.CTkButton(form_card, text="Confirm Retrieval & Restock", height=40, fg_color="#F1C40F", text_color="black", hover_color="#D4AC0D", font=("Inter", 13, "bold"), command=self.execute_return).pack(fill="x", padx=20, pady=(0, 20))

    def build_history_table(self, parent):
        table_card = ctk.CTkFrame(parent, fg_color="white", corner_radius=10)
        table_card.grid(row=0, column=1, sticky="nsew", padx=(5, 10))
        
        top_bar = ctk.CTkFrame(table_card, fg_color="transparent")
        top_bar.pack(fill="x", padx=20, pady=(20, 10))
        
        title_col = ctk.CTkFrame(top_bar, fg_color="transparent")
        title_col.pack(side="left")
        ctk.CTkLabel(title_col, text="Deployment History", font=("Inter", 16, "bold"), text_color="#1A1A1A").pack(anchor="w")
        ctk.CTkLabel(title_col, text="Click any row to view details or reprint receipt.",
                     font=("Inter", 10), text_color="gray").pack(anchor="w")

        self.search_entry = ctk.CTkEntry(top_bar, placeholder_text="Search Name or Tag...", width=200)
        self.search_entry.pack(side="right", padx=(10, 0))
        self.search_entry.bind("<Return>", lambda e: self.load_transaction_history())
        ctk.CTkButton(top_bar, text="Search", width=70, fg_color="#E0E0E0", text_color="black",
                      hover_color="#CCCCCC", font=("Inter", 11, "bold"),
                      command=self.load_transaction_history).pack(side="right")

        self.data_scroll = ctk.CTkScrollableFrame(table_card, fg_color="transparent")
        self.data_scroll.pack(fill="both", expand=True, padx=20, pady=(10, 20))

    # --- LOGIC & DATABASE METHODS ---

    def load_transaction_history(self):
        for widget in self.data_scroll.winfo_children(): widget.destroy()

        # Hard-Bounded Uniform Grid setup
        table_inner = ctk.CTkFrame(self.data_scroll, fg_color="transparent")
        table_inner.pack(fill="x", expand=True)

        headers = ["Type", "Item Name", "Tag ID", "Qty", "Assignee", "Date & Time", "Status"]
        
        # Dynamic Proportions to ensure important columns (Name, Assignee, Date) don't get squished
        weights = [1, 3, 2, 1, 2, 3, 1]
        min_sizes = [60, 160, 100, 50, 120, 160, 80]

        # Enforce exact column alignment and boundaries
        for col, (w, min_w) in enumerate(zip(weights, min_sizes)):
            table_inner.grid_columnconfigure(col, weight=w, minsize=min_w, uniform="hist_cols")

        # Header Row
        for col, text in enumerate(headers):
            cell = ctk.CTkFrame(table_inner, fg_color="#1E4528", corner_radius=0)
            cell.grid(row=0, column=col, sticky="nsew", pady=(0, 2))
            lbl = ctk.CTkLabel(cell, text=text, font=("Inter", 11, "bold"), text_color="white", anchor="center")
            lbl.pack(fill="both", expand=True, padx=2, pady=10)

        search_q = self.search_entry.get().strip()
        conn = get_connection()
        if not conn: return
        
        try:
            cursor = conn.cursor(dictionary=True)
            query = """
                SELECT tr.type, t.name as tool_name, t.tag_id, COUNT(tr.transaction_id) as grouped_qty,
                       u.full_name, tr.status,
                       DATE_FORMAT(DATE_ADD(MAX(IF(tr.type='Retrieval', tr.return_date, tr.borrow_date)), INTERVAL 8 HOUR), '%b %d, %Y %h:%i %p') as b_date,
                       MIN(tr.transaction_id) as first_trn,
                       MAX(tr.transaction_id) as last_trn,
                       IFNULL(MAX(tr.purpose), '—') as purpose,
                       MAX(tr.project_id) as project_id,
                       u.user_id as uid
                FROM transaction tr
                JOIN tool t ON tr.tool_id = t.tool_id
                JOIN user u ON tr.user_id = u.user_id
            """
            group_by = " GROUP BY tr.type, t.name, t.tag_id, u.full_name, u.user_id, tr.status"
            order_by = " ORDER BY MAX(IF(tr.type='Retrieval', tr.return_date, tr.borrow_date)) DESC LIMIT 50"
            
            if search_q:
                query += " WHERE u.full_name LIKE %s OR t.tag_id LIKE %s OR t.name LIKE %s"
                query += group_by + order_by
                cursor.execute(query, (f"%{search_q}%", f"%{search_q}%", f"%{search_q}%"))
            else:
                query += group_by + order_by
                cursor.execute(query)

            results = cursor.fetchall()
            
            if not results:
                ctk.CTkLabel(table_inner, text="No transactions found.", text_color="gray").grid(row=1, column=0, columnspan=len(headers), pady=20)
                return

            for i, row in enumerate(results):
                display_data = [
                    row['type'], row['tool_name'],
                    row['tag_id'] if row['tag_id'] else "Unassigned",
                    str(row['grouped_qty']), row['full_name'], row['b_date'], row['status']
                ]
                
                r_idx = i + 1
                bg = "#F9FAFB" if i % 2 == 0 else "white"

                for col, val in enumerate(display_data):
                    cell = ctk.CTkFrame(table_inner, fg_color=bg, corner_radius=0, cursor="hand2")
                    cell.grid(row=r_idx, column=col, sticky="nsew")

                    txt_color = "#D8000C" if col == 6 and val == "Active" else ("#2ECC71" if col == 6 else "#1A1A1A")
                    font_w = "bold" if col == 6 else "normal"
                    
                    lbl = ctk.CTkLabel(cell, text=val, font=("Inter", 11, font_w), text_color=txt_color, justify="center", anchor="center", cursor="hand2")
                    
                    # SAFE AUTO-WRAP: Uses the strict minimum widths to ensure text NEVER squishes unreadably
                    def set_wrap(e, l=lbl, m=min_sizes[col]):
                        target_wrap = max(m - 10, e.width - 10)
                        if not hasattr(l, '_last_wrap') or abs(l._last_wrap - target_wrap) > 5:
                            l.configure(wraplength=target_wrap)
                            l._last_wrap = target_wrap
                    cell.bind("<Configure>", set_wrap)
                    
                    lbl.pack(fill="both", expand=True, padx=4, pady=12)

                    # Binds whole cell & text to open the modal
                    cell.bind("<Button-1>", lambda e, r=row: self.open_transaction_modal(r))
                    lbl.bind("<Button-1>", lambda e, r=row: self.open_transaction_modal(r))
                    
        finally:
            if conn.is_connected(): cursor.close(); conn.close()

    def open_transaction_modal(self, row):
        trn_label = (f"TRN-{row['first_trn']}–{row['last_trn']}"
                     if row['first_trn'] != row['last_trn']
                     else f"TRN-{row['first_trn']}")

        modal = ctk.CTkToplevel(self)
        modal.title(f"Transaction Overview — {trn_label}")
        modal.geometry("520x550")
        modal.minsize(400, 450)
        modal.configure(fg_color="white")
        modal.attributes("-topmost", True)
        modal.grab_set()
        modal.update_idletasks()
        x = (modal.winfo_screenwidth() // 2) - 260
        y = (modal.winfo_screenheight() // 2) - 275
        modal.geometry(f"+{x}+{y}")

        # Header
        type_color = "#1E4528" if row['type'] == "Issue" else "#D35400"
        ctk.CTkLabel(modal, text="Transaction Overview",
                     font=("Inter", 16, "bold"), text_color="#1A1A1A").pack(pady=(20, 2))
        ctk.CTkLabel(modal, text=trn_label,
                     font=("Inter", 12, "bold"), text_color=type_color).pack(pady=(0, 12))

        # Details card
        card = ctk.CTkFrame(modal, fg_color="#F9FAFB", corner_radius=10)
        card.pack(fill="x", padx=24, pady=(0, 10))

        def detail_row(label, value, val_color="#1A1A1A"):
            r = ctk.CTkFrame(card, fg_color="transparent")
            r.pack(fill="x", padx=16, pady=(6, 0))
            ctk.CTkLabel(r, text=label, font=("Inter", 11, "bold"),
                         text_color="#1E4528", width=110, anchor="w").pack(side="left")
            ctk.CTkLabel(r, text=value, font=("Inter", 11),
                         text_color=val_color, wraplength=330, justify="left").pack(side="left")

        status_color = "#D8000C" if row['status'] == "Active" else "#2ECC71"
        detail_row("Type:",       row['type'])
        detail_row("Date/Time:",  row['b_date'])
        detail_row("Assignee:",   row['full_name'])
        detail_row("Purpose:",    row['purpose'])
        detail_row("Status:",     row['status'], val_color=status_color)
        ctk.CTkFrame(card, height=8, fg_color="transparent").pack()

        # Buttons (Pack these FIRST at the bottom so they are anchored)
        btn_frame = ctk.CTkFrame(modal, fg_color="transparent")
        btn_frame.pack(side="bottom", fill="x", padx=24, pady=(0, 20))

        ctk.CTkButton(btn_frame, text="🖨  Reprint Receipt", height=38,
                      fg_color="#1E4528", hover_color="#14301C",
                      font=("Inter", 12, "bold"),
                      command=lambda: self._reprint_from_history(row, modal)).pack(
            side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(btn_frame, text="Close", height=38, width=80,
                      fg_color="#E0E0E0", text_color="black", hover_color="#CCCCCC",
                      font=("Inter", 12, "bold"),
                      command=modal.destroy).pack(side="right")

        # Items section
        ctk.CTkLabel(modal, text="Items in this Transaction",
                     font=("Inter", 12, "bold"), text_color="#1A1A1A").pack(anchor="w", padx=24, pady=(6, 2))
        
        # CTkScrollableFrame configured to expand and absorb overflow
        items_frame = ctk.CTkScrollableFrame(modal, fg_color="#F9FAFB", corner_radius=8)
        items_frame.pack(fill="both", expand=True, padx=24, pady=(0, 12))

        # Query all tools in the same project+user batch
        self._load_modal_items(items_frame, row)

    def _load_modal_items(self, frame, row):
        conn = get_connection()
        if not conn:
            ctk.CTkLabel(frame, text=f"{row['tool_name']}  (Qty: {row['grouped_qty']})",
                         font=("Inter", 11), text_color="#1A1A1A").pack(anchor="w", padx=10, pady=6)
            return
        try:
            cursor = conn.cursor(dictionary=True)
            if row.get('project_id'):
                cursor.execute("""
                    SELECT t.name, COUNT(*) as qty
                    FROM transaction tr
                    JOIN tool t ON tr.tool_id = t.tool_id
                    WHERE tr.project_id = %s AND tr.user_id = %s AND tr.type = %s
                      AND DATE(tr.borrow_date) = (
                          SELECT DATE(borrow_date) FROM transaction WHERE transaction_id = %s
                      )
                    GROUP BY t.name
                """, (row['project_id'], row['uid'], row['type'], row['first_trn']))
                items = cursor.fetchall()
            else:
                items = [{"name": row['tool_name'], "qty": row['grouped_qty']}]

            for item in items:
                ctk.CTkLabel(frame,
                             text=f"• {item['name']}  (Qty: {item['qty']})",
                             font=("Inter", 11), text_color="#1A1A1A").pack(
                    anchor="w", padx=10, pady=(4, 0))
        except Exception:
            ctk.CTkLabel(frame, text=f"• {row['tool_name']}  (Qty: {row['grouped_qty']})",
                         font=("Inter", 11), text_color="#1A1A1A").pack(anchor="w", padx=10, pady=6)
        finally:
            if conn.is_connected(): cursor.close(); conn.close()

    def _reprint_from_history(self, row, modal=None):
        conn = get_connection()
        tool_names = []
        if conn:
            try:
                cursor = conn.cursor(dictionary=True)
                if row.get('project_id'):
                    cursor.execute("""
                        SELECT t.name, COUNT(*) as qty
                        FROM transaction tr
                        JOIN tool t ON tr.tool_id = t.tool_id
                        WHERE tr.project_id = %s AND tr.user_id = %s AND tr.type = %s
                          AND DATE(tr.borrow_date) = (
                              SELECT DATE(borrow_date) FROM transaction WHERE transaction_id = %s
                          )
                        GROUP BY t.name
                    """, (row['project_id'], row['uid'], row['type'], row['first_trn']))
                    tool_names = [f"{r['name']} (Qty: {r['qty']})" for r in cursor.fetchall()]
                else:
                    tool_names = [f"{row['tool_name']} (Qty: {row['grouped_qty']})"]
            except Exception:
                tool_names = [f"{row['tool_name']} (Qty: {row['grouped_qty']})"]
            finally:
                if conn.is_connected(): cursor.close(); conn.close()

        if not tool_names:
            tool_names = [f"{row['tool_name']} (Qty: {row['grouped_qty']})"]

        trn_range = (f"{row['first_trn']}-{row['last_trn']}"
                     if row['first_trn'] != row['last_trn']
                     else str(row['first_trn']))
        purpose = row.get('purpose') or "—"
        self.print_master_receipt(trn_range, row['full_name'], tool_names, purpose)

    def open_scanner(self, target_entry, trigger_method):
        try: cap = cv2.VideoCapture(0, cv2.CAP_DSHOW) 
        except: cap = cv2.VideoCapture(0) 
        if not cap.isOpened(): return messagebox.showerror("Camera Error", "No webcam detected.", parent=self.winfo_toplevel())

        detected_data = None
        cv2.namedWindow('Champion Scanner - Turbo Mode', cv2.WINDOW_NORMAL)
        cv2.setWindowProperty('Champion Scanner - Turbo Mode', cv2.WND_PROP_TOPMOST, 1)
        
        while True:
            ret, frame = cap.read()
            if not ret: break
            height, width, _ = frame.shape
            top_left = (int(width*0.25), int(height*0.3))
            bottom_right = (int(width*0.75), int(height*0.7))
            
            cv2.rectangle(frame, top_left, bottom_right, (0, 255, 0), 2)
            cv2.putText(frame, "Align QR Code inside box", (top_left[0], top_left[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            cv2.putText(frame, "Press 'Q' to Cancel", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            
            detected_codes = decode(frame, symbols=[ZBarSymbol.QRCODE])
            for barcode in detected_codes:
                raw_data = barcode.data.decode('utf-8')
                if "Tag ID:" in raw_data:
                    first_line = raw_data.split('\n')[0]
                    detected_data = first_line.replace("Tag ID:", "").strip()
                else:
                    detected_data = raw_data.strip()
                break 
                
            cv2.imshow('Champion Scanner - Turbo Mode', frame)
            if detected_data or cv2.waitKey(1) & 0xFF == ord('q'): break

        cap.release()
        cv2.destroyAllWindows()
        if detected_data:
            target_entry.delete(0, 'end')
            target_entry.insert(0, detected_data)
            trigger_method()

    def verify_borrower(self):
        emp_id = self.b_emp_id.get().strip()
        if not emp_id: return
        conn = get_connection()
        if not conn: return
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT user_id, full_name, role FROM user WHERE employee_id = %s", (emp_id,))
            user = cursor.fetchone()
            
            if user:
                self.active_borrow_user_id = user['user_id']
                self.active_borrow_user_name = user['full_name']
                self.b_user_name.configure(text=f"✓ Verified: {user['full_name']} ({user['role']})", text_color="#2ECC71")
                
                cursor.execute("""
                    SELECT DISTINCT p.project_id, p.name, p.client 
                    FROM projects p
                    JOIN project_requirements pr ON p.project_id = pr.project_id
                    WHERE p.status IN ('Approved', 'Ongoing') 
                    AND p.workers_assigned LIKE %s
                    AND pr.status != 'Fulfilled'
                """, (f"%{emp_id}%",))
                
                assigned_projects = cursor.fetchall()
                if assigned_projects:
                    self.active_projects_map.clear()
                    dropdown_vals = ["Select a project..."]
                    for p in assigned_projects:
                        display_text = f"Proj {p['project_id']}: {p['name']} ({p['client']})"
                        dropdown_vals.append(display_text)
                        self.active_projects_map[display_text] = p['project_id']
                        
                    self.b_project_menu.configure(values=dropdown_vals, state="normal")
                    self.b_project_menu.set(dropdown_vals[0])
                    self._clear_proj_req_display()
                else:
                    self.b_project_menu.configure(values=["No projects needing tools"], state="disabled")
                    self.b_project_menu.set("No projects needing tools")
                    self.active_projects_map.clear()
                    self._clear_proj_req_display()
            else:
                self.active_borrow_user_id = None
                self.active_borrow_user_name = None
                self.b_user_name.configure(text="❌ Employee ID not found.", text_color="#D8000C")
                self.b_project_menu.configure(values=["Scan Employee ID first..."], state="disabled")
                self.b_project_menu.set("Scan Employee ID first...")
                self._clear_proj_req_display()
        finally:
            if conn.is_connected(): cursor.close(); conn.close()

    def _clear_proj_req_display(self):
        for w in self.proj_req_frame.winfo_children(): w.destroy()
        ctk.CTkLabel(self.proj_req_frame, text="Select a project to see requirements...", font=("Inter", 11, "italic"), text_color="gray").pack(pady=10)
        self.b_tag_id.configure(state="disabled")
        self.b_scan_btn.configure(state="disabled")
        self.current_project_reqs.clear()

    def on_project_selected(self, choice):
        if choice == "Select a project...":
            self._clear_proj_req_display()
            return
            
        proj_id = self.active_projects_map.get(choice)
        if not proj_id: return
        
        conn = get_connection()
        if not conn: return
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT pr.tool_id, t.name, pr.quantity as req_qty, pr.status,
                       (SELECT COUNT(*) FROM transaction WHERE project_id = %s AND tool_id = pr.tool_id AND type = 'Issue' AND status = 'Active') as issued_qty,
                       p.name as p_name, p.client as p_client, p.location as p_location
                FROM project_requirements pr
                JOIN tool t ON pr.tool_id = t.tool_id
                JOIN projects p ON pr.project_id = p.project_id
                WHERE pr.project_id = %s
            """, (proj_id, proj_id))
            
            reqs = cursor.fetchall()
            self.current_project_reqs = reqs 
            
            for w in self.proj_req_frame.winfo_children(): w.destroy()
            
            if reqs:
                p_name = reqs[0]['p_name']
                p_client = reqs[0]['p_client']
                p_loc = reqs[0]['p_location']
                header_text = f"📍 Project: {p_name}\n🏢 Client: {p_client}  |  Site: {p_loc}"
                ctk.CTkLabel(self.proj_req_frame, text=header_text, font=("Inter", 11, "bold"), text_color="#1E4528", justify="left").pack(anchor="w", padx=10, pady=(10, 5))
                ctk.CTkFrame(self.proj_req_frame, height=1, fg_color="#E0E0E0").pack(fill="x", padx=10, pady=(0, 5))
            
            all_fulfilled = True
            for r in reqs:
                needed = float(r['req_qty'])
                issued = float(r['issued_qty'])
                remaining = needed - issued
                if remaining > 0: all_fulfilled = False
                
                txt_color = "#D8000C" if remaining > 0 else "#2ECC71"
                status_txt = f"Needs {remaining:g}" if remaining > 0 else "✓ Fulfilled"
                row_str = f"• {r['name']}  |  Approved: {needed:g}  |  {status_txt}"
                ctk.CTkLabel(self.proj_req_frame, text=row_str, font=("Inter", 11, "bold" if remaining > 0 else "normal"), text_color=txt_color).pack(anchor="w", padx=10, pady=2)
            
            if not all_fulfilled:
                self.b_tag_id.configure(state="normal")
                self.b_scan_btn.configure(state="normal")
                self.b_tag_id.focus_set()
            else:
                self.b_tag_id.configure(state="disabled")
                self.b_scan_btn.configure(state="disabled")
                
        finally:
            if conn.is_connected(): cursor.close(); conn.close()

    def add_tool_to_cart(self):
        tag_id = self.b_tag_id.get().strip()
        if not tag_id: return

        selected_proj = self.b_project_menu.get()
        if selected_proj not in self.active_projects_map:
            messagebox.showerror("Unauthorized", "No valid project selected.", parent=self.winfo_toplevel())
            return
            
        conn = get_connection()
        if not conn: return
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT t.tool_id, t.name, t.condition, IFNULL(i.quantity_available, 0) as qty FROM tool t LEFT JOIN inventory i ON t.tool_id = i.tool_id WHERE t.tag_id = %s AND t.is_archived = 0", (tag_id,))
            tool = cursor.fetchone()
            
            if not tool:
                messagebox.showerror("Not Found", "Invalid or Unassigned Tag ID.", parent=self.winfo_toplevel())
                return
            if tool['qty'] <= 0:
                messagebox.showerror("Out of Stock", f"'{tool['name']}' is currently out of stock!", parent=self.winfo_toplevel())
                return

            req = next((r for r in self.current_project_reqs if r['tool_id'] == tool['tool_id']), None)
            if not req:
                messagebox.showerror("Unauthorized", f"'{tool['name']}' is NOT approved for this project.", parent=self.winfo_toplevel())
                return

            allowed_qty = float(req['req_qty'])
            already_issued = float(req['issued_qty'])
            in_cart = sum(item['qty_borrowed'] for item in self.borrow_cart if item['id'] == tool['tool_id'])

            if (already_issued + in_cart + 1) > allowed_qty:
                messagebox.showerror("Limit Reached", f"Cannot add '{tool['name']}'.\nApproved Limit: {allowed_qty:g}\nAlready Issued: {already_issued}\nIn Cart: {in_cart}", parent=self.winfo_toplevel())
                return

            # --- FIX B: Check real physical inventory constraints before accepting into cart ---
            if (in_cart + 1) > tool['qty']:
                messagebox.showerror("Out of Stock", f"Cannot add '{tool['name']}'.\nOnly {tool['qty']} left in the warehouse.", parent=self.winfo_toplevel())
                return
            # ---------------------------------------------------------------------------------

            existing = next((item for item in self.borrow_cart if item['id'] == tool['tool_id']), None)
            if existing:
                existing['qty_borrowed'] += 1
            else:
                self.borrow_cart.append({
                    "id": tool['tool_id'], "name": tool['name'], "cond": tool['condition'], 
                    "tag": tag_id, "qty_borrowed": 1, "max_qty": tool['qty']
                })
                
            self.refresh_cart_ui()
            self.b_tag_id.delete(0, 'end') 
            
        finally:
            if conn.is_connected(): cursor.close(); conn.close()

    def update_cart_qty(self, index, change):
        item = self.borrow_cart[index]
        new_qty = item['qty_borrowed'] + change
        req = next((r for r in self.current_project_reqs if r['tool_id'] == item['id']), None)
        if not req: return
        allowed_qty = float(req['req_qty'])
        already_issued = float(req['issued_qty'])
        
        if (already_issued + new_qty) > allowed_qty:
            messagebox.showwarning("Limit Reached", f"You cannot exceed the approved limit of {allowed_qty:g}.", parent=self.winfo_toplevel())
        elif new_qty > item['max_qty']:
            messagebox.showwarning("Out of Stock", f"Only {item['max_qty']} available in warehouse.", parent=self.winfo_toplevel())
        elif new_qty <= 0:
            self.remove_from_cart(index)
        else:
            item['qty_borrowed'] = new_qty
            self.refresh_cart_ui()

    def remove_from_cart(self, index):
        self.borrow_cart.pop(index)
        self.refresh_cart_ui()

    def refresh_cart_ui(self):
        for widget in self.cart_frame.winfo_children(): widget.destroy()
        if len(self.borrow_cart) == 0:
            ctk.CTkLabel(self.cart_frame, text="Cart is empty. Scan required tools to add.", text_color="gray").pack(pady=10)
            return

        for i, item in enumerate(self.borrow_cart):
            row = ctk.CTkFrame(self.cart_frame, fg_color="white", corner_radius=5, height=35)
            row.pack(fill="x", pady=2, padx=5)
            row.pack_propagate(False)
            ctk.CTkLabel(row, text=f"✓ {item['name']}  |  Tag: {item['tag']}", font=("Inter", 11, "bold"), text_color="#1E4528").pack(side="left", padx=10, pady=5)
            ctk.CTkButton(row, text="✕", width=25, height=25, fg_color="#FFEAEA", text_color="#D8000C", hover_color="#FFC0C0", command=lambda idx=i: self.remove_from_cart(idx)).pack(side="right", padx=(5, 10))
            ctk.CTkButton(row, text="+", width=25, height=25, fg_color="#E0E0E0", text_color="black", hover_color="#CCCCCC", command=lambda idx=i: self.update_cart_qty(idx, 1)).pack(side="right", padx=2)
            ctk.CTkLabel(row, text=f"Qty: {item['qty_borrowed']}", font=("Inter", 11, "bold"), text_color="black").pack(side="right", padx=8)
            ctk.CTkButton(row, text="-", width=25, height=25, fg_color="#E0E0E0", text_color="black", hover_color="#CCCCCC", command=lambda idx=i: self.update_cart_qty(idx, -1)).pack(side="right", padx=2)

    def execute_borrow(self):
        if not self.active_borrow_user_id:
            return messagebox.showerror("Error", "Please scan and verify an Employee ID first.", parent=self.winfo_toplevel())
        selected_proj = self.b_project_menu.get()
        proj_id = self.active_projects_map.get(selected_proj)
        if not proj_id:
            return messagebox.showerror("Error", "Please select a target project.", parent=self.winfo_toplevel())
        if len(self.borrow_cart) == 0:
            return messagebox.showerror("Error", "The cart is empty! Scan at least one tool.", parent=self.winfo_toplevel())
            
        purpose = selected_proj
        conn = get_connection()
        if not conn: return
        try:
            cursor = conn.cursor(dictionary=True)
            transaction_ids = []; receipt_tool_list = []
            
            # --- FIX B: Hard Block Database Check Before Execution ---
            for item in self.borrow_cart:
                cursor.execute("SELECT quantity_available FROM inventory WHERE tool_id = %s", (item['id'],))
                db_qty = cursor.fetchone()['quantity_available']
                if item['qty_borrowed'] > db_qty:
                    return messagebox.showerror("Inventory Error", f"Transaction aborted.\n'{item['name']}' only has {db_qty} remaining in stock.", parent=self.winfo_toplevel())
            # ---------------------------------------------------------
            
            for item in self.borrow_cart:
                cursor.execute("UPDATE inventory SET quantity_available = quantity_available - %s WHERE tool_id = %s", (item['qty_borrowed'], item['id']))
                for _ in range(int(item['qty_borrowed'])):
                    cursor.execute("""
                        INSERT INTO transaction (user_id, tool_id, type, borrow_date, purpose, status, condition_at_borrow, project_id) 
                        VALUES (%s, %s, 'Issue', NOW(), %s, 'Active', %s, %s)
                    """, (self.active_borrow_user_id, item['id'], purpose, item['cond'], proj_id))
                    transaction_ids.append(str(cursor.lastrowid))
                receipt_tool_list.append(f"{item['name']} (Qty: {item['qty_borrowed']})")
                
            cursor.execute("""
                SELECT pr.req_id, pr.tool_id, pr.quantity as req_qty,
                       (SELECT COUNT(*) FROM transaction WHERE project_id = %s AND tool_id = pr.tool_id AND type = 'Issue' AND status = 'Active') as total_issued
                FROM project_requirements pr WHERE pr.project_id = %s
            """, (proj_id, proj_id))
            reqs = cursor.fetchall()
            
            all_fulfilled = True
            for r in reqs:
                if float(r['total_issued']) >= float(r['req_qty']):
                    cursor.execute("UPDATE project_requirements SET status = 'Fulfilled' WHERE req_id = %s", (r['req_id'],))
                else: all_fulfilled = False
                    
            if all_fulfilled:
                cursor.execute("UPDATE projects SET status = 'Ongoing' WHERE project_id = %s", (proj_id,))
            
            conn.commit()
            
            total_items = sum(item['qty_borrowed'] for item in self.borrow_cart)
            msg = f"{total_items} items issued successfully! Generating receipt..."
            if all_fulfilled: msg += "\n\nAll tools fulfilled! Project status automatically updated to 'Ongoing'."
            messagebox.showinfo("Success", msg, parent=self.winfo_toplevel())
            
            master_trans_id = f"{transaction_ids[0]}-{transaction_ids[-1]}" if len(transaction_ids) > 1 else transaction_ids[0]
            self.print_master_receipt(master_trans_id, self.active_borrow_user_name, receipt_tool_list, purpose)
            
            self.b_emp_id.delete(0, 'end')
            self.b_project_menu.set("Scan Employee ID first...")
            self.b_project_menu.configure(state="disabled")
            self._clear_proj_req_display()
            self.b_user_name.configure(text="Name: Pending Scan...", text_color="gray")
            self.active_borrow_user_id = None; self.borrow_cart.clear()
            self.refresh_cart_ui(); self.load_transaction_history()
            
        except Exception as e:
            messagebox.showerror("Database Error", str(e), parent=self.winfo_toplevel())
        finally:
            if conn.is_connected(): cursor.close(); conn.close()

    # ── Receipt helpers ────────────────────────────────────────────
    def _load_receipt_font(self, filename, size):
        fonts_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        for path in [os.path.join(fonts_dir, filename), filename]:
            try:
                return ImageFont.truetype(path, size)
            except (IOError, OSError):
                continue
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()

    def _build_receipt_image(self, trans_id_range, b_name, tool_names, purpose):
        W = 800
        LINE = 40
        H = 280 + max(60, len(tool_names) * LINE) + 120
        img = Image.new("RGB", (W, H), "#FAFAFA")
        draw = ImageDraw.Draw(img)

        # Header band
        draw.rectangle([(0, 0), (W, 90)], fill="#1E4528")
        f_hdr   = self._load_receipt_font("arialbd.ttf", 22)
        f_sub   = self._load_receipt_font("arial.ttf",   14)
        f_label = self._load_receipt_font("arial.ttf",   13)
        f_value = self._load_receipt_font("arialbd.ttf", 16)
        f_items = self._load_receipt_font("arialbd.ttf", 15)
        f_item  = self._load_receipt_font("arial.ttf",   15)
        f_sig   = self._load_receipt_font("arial.ttf",   12)

        draw.text((30, 18), "CHAMPION FINE TOOLING CORP.", fill="white", font=f_hdr)
        draw.text((30, 56), "MASTER DEPLOYMENT RECEIPT", fill="#A8D5BA", font=f_sub)

        # Transaction metadata
        current_time = datetime.now().strftime("%B %d, %Y  —  %I:%M %p")
        y = 110
        meta = [
            ("Transaction:",  f"TRN-[{trans_id_range}]"),
            ("Date & Time:",  current_time),
            ("Issued To:",    b_name),
            ("Project:",      str(purpose)[:70]),
        ]
        for label, value in meta:
            draw.text((30,  y), label, fill="#888888", font=f_label)
            draw.text((180, y), value, fill="#1A1A1A", font=f_value)
            y += 38

        draw.line([(30, y + 8), (W - 30, y + 8)], fill="#DDDDDD", width=1)
        y += 24

        # Items
        draw.text((30, y), "Items Issued:", fill="#1A1A1A", font=f_items)
        y += 32
        for name in tool_names:
            draw.ellipse([(30, y + 6), (40, y + 16)], fill="#1E4528")
            draw.text((52, y), name, fill="#1A1A1A", font=f_item)
            y += LINE

        draw.line([(30, y + 18), (W - 30, y + 18)], fill="#DDDDDD", width=1)
        y += 36
        draw.text((30,      y), "Authorized Admin Signature: ___________________________", fill="#888888", font=f_sig)
        draw.text((W - 280, y), "Received By: ___________________", fill="#888888", font=f_sig)

        return img

    def print_master_receipt(self, trans_id_range, b_name, tool_names, purpose):
        try:
            img = self._build_receipt_image(trans_id_range, b_name, tool_names, purpose)

            # ── Instant in-app preview ────────────────────────────
            preview = ctk.CTkToplevel(self)
            preview.title(f"Receipt — TRN-{trans_id_range}")
            preview.configure(fg_color="white")
            preview.attributes("-topmost", True)
            preview.grab_set()
            preview.update_idletasks()
            pw, ph = 840, min(img.height // 2 + 120, 700)
            sw, sh = preview.winfo_screenwidth(), preview.winfo_screenheight()
            preview.geometry(f"{pw}x{ph}+{(sw-pw)//2}+{(sh-ph)//2}")

            # Scrollable image area
            scroll_area = ctk.CTkScrollableFrame(preview, fg_color="#F0F0F0")
            scroll_area.pack(fill="both", expand=True, padx=0, pady=0)

            display_w = img.width // 2
            display_h = img.height // 2
            ctk_img = ctk.CTkImage(light_image=img, size=(display_w, display_h))
            img_lbl = ctk.CTkLabel(scroll_area, image=ctk_img, text="")
            img_lbl.pack(padx=20, pady=20)

            # Button bar
            btn_bar = ctk.CTkFrame(preview, fg_color="white", height=60)
            btn_bar.pack(fill="x", side="bottom")
            btn_bar.pack_propagate(False)

            def export_pdf():
                import tempfile as _tf
                path = os.path.join(_tf.gettempdir(), "Receipt.pdf")
                img.save(path, "PDF", resolution=150.0)
                os.startfile(path)

            ctk.CTkButton(btn_bar, text="🖨  Export & Open PDF", height=38,
                          fg_color="#1E4528", hover_color="#14301C",
                          font=("Inter", 12, "bold"),
                          command=export_pdf).pack(side="left", padx=20, pady=11)
            ctk.CTkButton(btn_bar, text="Close", height=38, width=90,
                          fg_color="#E0E0E0", text_color="black", hover_color="#CCCCCC",
                          font=("Inter", 12, "bold"),
                          command=preview.destroy).pack(side="right", padx=20, pady=11)

        except Exception as e:
            messagebox.showwarning("Receipt Warning",
                                   f"Transaction saved but receipt failed:\n{e}",
                                   parent=self.winfo_toplevel())

    def verify_tool_for_return(self):
        if not self.active_return_user_id:
            messagebox.showwarning("Authentication Required", "Please scan Employee ID first before returning a tool.", parent=self.winfo_toplevel())
            self.r_tag_id.delete(0, 'end')
            return

        tag_input = self.r_tag_id.get().strip()
        if not tag_input: return
        
        search_val = tag_input
        if tag_input.upper().startswith("TRN-"):
            search_val = tag_input.upper().replace("TRN-", "").split("-")[0]

        conn = get_connection()
        if not conn: return
        try:
            cursor = conn.cursor(dictionary=True)
            if search_val.isdigit():
                cursor.execute("SELECT tool_id FROM transaction WHERE transaction_id = %s AND user_id = %s AND status = 'Active'", (search_val, self.active_return_user_id))
            else:
                cursor.execute("SELECT tool_id FROM tool WHERE tag_id = %s", (search_val,))
                
            target_tool = cursor.fetchone()
            if not target_tool:
                self.r_record_info.configure(text="❌ No active records found for this Tag/TRN combo.", text_color="#D8000C")
                return

            query = """
                SELECT t.tool_id, t.name, COUNT(tr.transaction_id) as active_borrows
                FROM transaction tr
                JOIN tool t ON tr.tool_id = t.tool_id
                WHERE tr.tool_id = %s AND tr.status = 'Active' AND tr.user_id = %s
                GROUP BY t.tool_id, t.name
            """
            cursor.execute(query, (target_tool['tool_id'], self.active_return_user_id))
            record = cursor.fetchone()
            
            if record:
                self.active_return_tool_id = record['tool_id']
                self.max_returnable = record['active_borrows']
                self.r_record_info.configure(text=f"✓ Tool Identified: {record['name']}\nCurrently Deployed Out: {record['active_borrows']}", text_color="#2ECC71")
                self.r_qty.delete(0, 'end'); self.r_qty.insert(0, "1")
            else:
                self.active_return_tool_id = None; self.max_returnable = 0
                self.r_record_info.configure(text="❌ No active records found.", text_color="#D8000C")
        finally:
            if conn.is_connected(): cursor.close(); conn.close()

    def verify_return_employee(self):
        emp_id = self.r_emp_id.get().strip()
        if not emp_id: return
        conn = get_connection()
        if not conn: return
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT user_id, full_name, role FROM user WHERE employee_id = %s", (emp_id,))
            user = cursor.fetchone()
            if user:
                self.active_return_user_id = user['user_id']
                self.r_user_name.configure(text=f"✓ Verified: {user['full_name']} ({user['role']})", text_color="#2ECC71")
            else:
                self.active_return_user_id = None
                self.r_user_name.configure(text="❌ Employee ID not found.", text_color="#D8000C")
        finally:
            if conn.is_connected(): cursor.close(); conn.close()

    def execute_return(self):
        if not self.active_return_tool_id or not self.active_return_user_id:
            return messagebox.showerror("Error", "Please scan and verify both Employee ID and Tag ID/TRN.", parent=self.winfo_toplevel())
        try:
            return_qty = int(self.r_qty.get().strip())
            if return_qty <= 0: raise ValueError
        except ValueError:
            return messagebox.showerror("Error", "Quantity must be a positive whole number.", parent=self.winfo_toplevel())
            
        if return_qty > self.max_returnable:
            return messagebox.showerror("Error", f"Cannot retrieve {return_qty}. You only have {self.max_returnable} deployed.", parent=self.winfo_toplevel())

        new_cond = self.r_condition.get()
        condition_notes = self.r_condition_desc.get("1.0", "end").strip()
        conn = get_connection()
        if not conn: return
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SHOW COLUMNS FROM transaction LIKE 'condition_return_notes'")
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE transaction ADD COLUMN condition_return_notes TEXT NULL")

            cursor.execute("SELECT transaction_id FROM transaction WHERE tool_id = %s AND status = 'Active' AND user_id = %s ORDER BY borrow_date ASC LIMIT %s", (self.active_return_tool_id, self.active_return_user_id, return_qty))
            transactions_to_close = cursor.fetchall()
            
            for trans in transactions_to_close:
                cursor.execute("""
                    UPDATE transaction 
                    SET status = 'Returned', return_date = NOW(), type = 'Retrieval', condition_at_return = %s, condition_return_notes = %s 
                    WHERE transaction_id = %s
                """, (new_cond, condition_notes or None, trans['transaction_id']))
            
            cursor.execute("UPDATE inventory SET quantity_available = quantity_available + %s WHERE tool_id = %s", (return_qty, self.active_return_tool_id))
            cursor.execute("UPDATE tool SET `condition` = %s WHERE tool_id = %s", (new_cond, self.active_return_tool_id))
            conn.commit()
            messagebox.showinfo("Success", f"Successfully retrieved {return_qty} item(s) and restocked inventory!", parent=self.winfo_toplevel())
            
            self.r_emp_id.delete(0, 'end'); self.r_tag_id.delete(0, 'end')
            self.r_user_name.configure(text="Name: Pending Scan...", text_color="gray")
            self.r_record_info.configure(text="Record: Pending Scan...", text_color="gray")
            self.r_condition.set("Good"); self.r_qty.delete(0, 'end'); self.r_qty.insert(0, "1")
            self.r_condition_desc.delete("1.0", "end")
            self.active_return_tool_id = None; self.active_return_user_id = None; self.max_returnable = 0
            
            self.load_transaction_history()
        finally:
            if conn.is_connected(): cursor.close(); conn.close()