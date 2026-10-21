from services.validators import fmt_qty
import customtkinter as ctk
from views.ui_thread import UiMixin
from tkinter import messagebox
from database import get_connection
from services import issuance_service as iss, validators as v
from services.errors import ServiceError, NotFound, Conflict, friendly_message
from services.tool_cache import tool_cache
from services.paging import fetch_page
from views.paged_table import PagedTable
import cv2
from pyzbar.pyzbar import decode, ZBarSymbol
import os
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime, timedelta, date as _date
import calendar as _cal
import threading

def _fmt_qty(x) -> str:
    """Exact quantity for display: 3.00 -> '3', 2.50 -> '2.5'."""
    try:
        return f"{float(x):g}"
    except (TypeError, ValueError):
        return str(x)


class IssuanceView(UiMixin, ctk.CTkFrame):
    def __init__(self, parent, user_info=None, navigate_to=None, *args, **kwargs):
        super().__init__(parent, fg_color="transparent")
        self._ui_init()

        self.user_info = user_info or {}
        self.navigate_to = navigate_to
        
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

        ctk.CTkLabel(top_bar, text="Issuance & Retrieval", font=("Inter", 16, "bold"), text_color="#1E4528").pack(side="left")

        tabs = ["📋 Deployment History", "📅 Deployment Schedule"]
        self.tab_var = ctk.StringVar(value="📋 Deployment History")

        self.seg_btn = ctk.CTkSegmentedButton(
            top_bar, values=tabs, variable=self.tab_var, command=self.switch_tab,
            fg_color="#F0F0F0", selected_color="#1E4528", selected_hover_color="#14301C"
        )
        self.seg_btn.pack(side="right")

        self.tab_content = ctk.CTkFrame(self, fg_color="transparent")
        self.tab_content.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 20))
        self.tab_content.grid_columnconfigure(0, weight=1) 
        self.tab_content.grid_rowconfigure(0, weight=1)
        
        self.switch_tab(tabs[0])

    def switch_tab(self, selected_tab):
        for widget in self.tab_content.winfo_children():
            widget.destroy()

        if selected_tab == "📅 Deployment Schedule":
            self.build_calendar_tab(self.tab_content)
        else:
            self.build_history_table(self.tab_content)
            self.load_transaction_history()

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
                WHERE status NOT IN ('Cancelled', 'Completed', 'Declined') AND archived_at IS NULL
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
                         font=("Inter", 10, "bold"), text_color=color).pack(anchor="w", padx=10, pady=(2, 4))
            if self.navigate_to:
                ctk.CTkButton(pcard, text="→ View Project", width=120, height=26,
                              fg_color="#1E4528", hover_color="#14301C",
                              font=("Inter", 10, "bold"),
                              command=lambda pid=p["project_id"]: self.navigate_to(pid)
                              ).pack(anchor="w", padx=10, pady=(0, 8))

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

    def open_issuance_modal(self):
        self.issuance_modal = ctk.CTkToplevel(self)
        self.issuance_modal.title("Issue Tools")
        self.issuance_modal.geometry("500x700")
        self.issuance_modal.configure(fg_color="white")
        self.issuance_modal.attributes("-topmost", True)
        self.issuance_modal.grab_set()
        
        self.issuance_modal.update_idletasks()
        x = (self.issuance_modal.winfo_screenwidth() // 2) - (500 // 2)
        y = (self.issuance_modal.winfo_screenheight() // 2) - (700 // 2)
        self.issuance_modal.geometry(f"+{x}+{y}")
        
        form_card = ctk.CTkScrollableFrame(self.issuance_modal, fg_color="white", corner_radius=0)
        form_card.pack(fill="both", expand=True)

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
        btn_row = ctk.CTkFrame(form_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 20))
        ctk.CTkButton(btn_row, text="Cancel", height=40, width=80, fg_color="#E0E0E0", text_color="black", hover_color="#CCCCCC", font=("Inter", 12, "bold"), command=self.issuance_modal.destroy).pack(side="right")
        
        self.active_borrow_user_id = None
        self.active_borrow_user_name = None
        self.borrow_cart = []
        self.current_project_reqs = []
        self.active_projects_map = {}

        self.b_emp_id.focus_set()

    def open_retrieval_modal(self):
        self.retrieval_modal = ctk.CTkToplevel(self)
        self.retrieval_modal.title("Retrieve Tools")
        self.retrieval_modal.geometry("500x650")
        self.retrieval_modal.configure(fg_color="white")
        self.retrieval_modal.attributes("-topmost", True)
        self.retrieval_modal.grab_set()
        
        self.retrieval_modal.update_idletasks()
        x = (self.retrieval_modal.winfo_screenwidth() // 2) - (500 // 2)
        y = (self.retrieval_modal.winfo_screenheight() // 2) - (650 // 2)
        self.retrieval_modal.geometry(f"+{x}+{y}")
        
        form_card = ctk.CTkScrollableFrame(self.retrieval_modal, fg_color="white", corner_radius=0)
        form_card.pack(fill="both", expand=True)

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
        btn_row = ctk.CTkFrame(form_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(10, 20))
        ctk.CTkButton(btn_row, text="Cancel", height=40, width=80, fg_color="#E0E0E0", text_color="black", hover_color="#CCCCCC", font=("Inter", 12, "bold"), command=self.retrieval_modal.destroy).pack(side="right")
        
        self.active_return_user_id = None
        self.active_return_tool_id = None
        self.active_return_item_type = None
        self.max_returnable = 0

        self.r_emp_id.focus_set()

    def build_history_table(self, parent):
        table_card = ctk.CTkFrame(parent, fg_color="white", corner_radius=10)
        table_card.grid(row=0, column=0, sticky="nsew", padx=0)
        table_card.grid_columnconfigure(0, weight=1)
        table_card.grid_rowconfigure(1, weight=1)
        
        top_bar = ctk.CTkFrame(table_card, fg_color="transparent")
        top_bar.pack(fill="x", padx=20, pady=(20, 10))
        
        title_col = ctk.CTkFrame(top_bar, fg_color="transparent")
        title_col.pack(side="left")
        ctk.CTkLabel(title_col, text="Deployment History", font=("Inter", 16, "bold"), text_color="#1A1A1A").pack(anchor="w")
        ctk.CTkLabel(title_col, text="Click any row to view details or reprint receipt.",
                     font=("Inter", 10), text_color="gray").pack(anchor="w")

        self.search_var = ctk.StringVar()
        self.search_entry = ctk.CTkEntry(top_bar, placeholder_text="Search Name or Tag...", width=200, textvariable=self.search_var)
        self.search_entry.pack(side="right", padx=(10, 0))
        
        self._search_timer = None
        def on_search_change(*args):
            if self._search_timer:
                self.after_cancel(self._search_timer)
            self._search_timer = self.after(300, self.load_transaction_history)
        self.search_var.trace_add("write", on_search_change)
                      
        self.history_filter = ctk.CTkOptionMenu(top_bar, values=["Latest", "Issue (Type)", "Retrieval (Type)", "All Active", "All Retrieved", "Overdue", "A-Z (Item)"], width=160, fg_color="#F9FAFB", text_color="black", command=lambda e: self.load_transaction_history())
        self.history_filter.pack(side="right", padx=(10, 5))

        ctk.CTkButton(top_bar, text="📥 Retrieve Tools", width=120, fg_color="#F1C40F", text_color="black", hover_color="#D4AC0D", font=("Inter", 12, "bold"), command=self.open_retrieval_modal).pack(side="right", padx=(5, 10))
        ctk.CTkButton(top_bar, text="📤 Issue Tools", width=110, fg_color="#3498DB", hover_color="#2980B9", font=("Inter", 12, "bold"), command=self.open_issuance_modal).pack(side="right", padx=(10, 0))

        self.data_scroll = ctk.CTkScrollableFrame(table_card, fg_color="transparent")
        self.data_scroll.pack(fill="both", expand=True, padx=20, pady=(10, 20))

    # --- LOGIC & DATABASE METHODS ---

    HIST_COLUMNS = [("Type", 1, 60), ("Item Name", 2, 140), ("Tag ID", 1, 80), ("Qty", 1, 50), ("Assignee", 2, 100),
                    ("Date Issued", 2, 130), ("Due / Retrieved", 2, 140), ("Status", 1, 80)]

    def load_transaction_history(self):
        # filters are read HERE, on the main thread; the worker thread only uses these saved copies
        self._hist_search = self.search_entry.get().strip()
        self._hist_filter = self.history_filter.get() if hasattr(self, "history_filter") else "Latest"
        if getattr(self, "_hist_table", None) is None or not self._hist_table.winfo_exists():
            for widget in self.data_scroll.winfo_children():
                widget.destroy()
            self._hist_table = PagedTable(
                self.data_scroll, self.HIST_COLUMNS, fetch=self._fetch_history_page, cells=self._history_cells,
                cell_style=self._history_style, on_row_click=self.open_transaction_modal, empty_text="No transactions found.",
                font_size=12, cell_pady=12, uniform="hist_cols")
            self._hist_table.pack(fill="x", expand=True)
        self._hist_table.reload(0)

    def _fetch_history_page(self, page, size):
        search_q, filter_val = self._hist_search, self._hist_filter
        where, params = [], []
        if search_q:
            like = v.like_pattern(search_q)          # [UNHAPPY-PATH] capped at 64 chars, % and _ escaped
            where.append("(u.full_name LIKE %s OR t.tag_id LIKE %s OR t.name LIKE %s)")
            params.extend([like, like, like])
        if filter_val == "All Active":
            where.append("tr.status = 'Active'")
        elif filter_val == "All Retrieved":
            where.append("tr.status = 'Returned'")
        elif filter_val == "Overdue":
            where.append("tr.status = 'Active' AND COALESCE(tr.due_date, p.end_date) < CURDATE()")
        elif filter_val == "Issue (Type)":
            where.append("tr.type = 'Issue'")
        elif filter_val == "Retrieval (Type)":
            where.append("tr.type = 'Retrieval'")
        frm = ("FROM transaction tr JOIN tool t ON tr.tool_id = t.tool_id JOIN user u ON tr.user_id = u.user_id "
               "LEFT JOIN projects p ON tr.project_id = p.project_id")
        if where:
            frm += " WHERE " + " AND ".join(where)
        group_by = " GROUP BY tr.type, t.name, t.tag_id, u.full_name, u.user_id, tr.status"
        order = ("ORDER BY t.name ASC, MIN(tr.transaction_id) DESC" if filter_val == "A-Z (Item)"
                 else "ORDER BY MAX(IF(tr.type='Retrieval', tr.return_date, tr.borrow_date)) DESC, MIN(tr.transaction_id) DESC")
        select = """SELECT tr.type, t.name as tool_name, t.tag_id, SUM(tr.quantity) as grouped_qty, u.full_name, tr.status,
                       -- [4-DATE] server time only: the session time zone (+08:00) is set by db.pool; no client-side hour shifts
                       MAX(IF(tr.type='Retrieval', tr.return_date, tr.borrow_date)) as b_date,
                       MAX(tr.borrow_date) as borrow_date_full, MAX(tr.borrow_date) as borrow_date_short,
                       MAX(tr.return_date) as return_date_full, MAX(tr.return_date) as return_date_short,
                       MIN(tr.transaction_id) as first_trn, MAX(tr.transaction_id) as last_trn,
                       IFNULL(MAX(tr.purpose), '—') as purpose, MAX(tr.project_id) as project_id, u.user_id as uid,
                       CURDATE() as server_today,
                       MAX(COALESCE(tr.due_date, p.end_date)) as due_date"""      # [4-DATE] due date = snapshot taken at issuance, not the live project date
        conn = get_connection()
        if not conn:
            raise ConnectionError("The database is not reachable.")
        try:
            cur = conn.cursor(dictionary=True)
            count_sql = f"SELECT COUNT(*) AS n FROM (SELECT 1 {frm}{group_by}) g"          # pages count GROUPS, as shown
            rows, info = fetch_page(cur, select, frm + group_by, params, order, page, size, count_sql=count_sql)
        finally:
            if conn.is_connected():
                conn.close()
        for row in rows:                                                                  # text for the table and the receipt window
            row['grouped_qty'] = _fmt_qty(row['grouped_qty'])
            if hasattr(row['b_date'], 'strftime'): row['b_date'] = row['b_date'].strftime('%b %d, %Y %I:%M %p')
            if hasattr(row['borrow_date_full'], 'strftime'): row['borrow_date_full'] = row['borrow_date_full'].strftime('%b %d, %Y %I:%M %p')
            if hasattr(row['borrow_date_short'], 'strftime'): row['borrow_date_short'] = row['borrow_date_short'].strftime('%b %d, %Y')
            if hasattr(row['return_date_full'], 'strftime'): row['return_date_full'] = row['return_date_full'].strftime('%b %d, %Y %I:%M %p')
            if hasattr(row['return_date_short'], 'strftime'): row['return_date_short'] = row['return_date_short'].strftime('%b %d, %Y')
        return rows, info

    @staticmethod
    def _history_due(row):
        """(text, colour, bold) for the 'Due / Retrieved' column."""
        if row['status'] == 'Active':
            due = row['due_date']
            if not due:
                return "No Due Date", "#1A1A1A", False
            if due < (row.get('server_today') or _date.today()):
                return f"Overdue: {due.strftime('%b %d, %Y')}", "#D8000C", True
            return f"Due: {due.strftime('%b %d, %Y')}", "#1A1A1A", False
        return (f"Ret: {row['return_date_short']}" if row['return_date_short'] else "Returned"), "#2ECC71", False

    def _history_cells(self, row):
        return [row['type'], row['tool_name'], row['tag_id'] if row['tag_id'] else "Unassigned", str(row['grouped_qty']), row['full_name'],
                row['borrow_date_short'], self._history_due(row)[0], row['status']]

    def _history_style(self, row, col, val):
        if col == 7:
            return ("#D8000C" if val == "Active" else "#2ECC71"), True
        if col == 6:
            _t, color, bold = self._history_due(row)
            return color, bold
        if col == 2 and val == "Unassigned":
            return "#D8000C", True
        return "#1A1A1A", False

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
        detail_row("Issued On:",  row['borrow_date_full'])
        if row['status'] == 'Active':
            detail_row("Due Date:", row['due_date'].strftime('%b %d, %Y') if row.get('due_date') else "No Due Date")
        else:
            detail_row("Retrieved On:", row['return_date_full'] if row.get('return_date_full') else "—")
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
                    SELECT t.name, SUM(tr.quantity) as qty
                    FROM transaction tr
                    JOIN tool t ON tr.tool_id = t.tool_id
                    WHERE tr.project_id = %s AND tr.user_id = %s AND tr.type = %s
                      AND DATE(tr.borrow_date) = (
                          SELECT DATE(borrow_date) FROM transaction WHERE transaction_id = %s
                      )
                    GROUP BY t.name
                """, (row['project_id'], row['uid'], row['type'], row['first_trn']))
                items = cursor.fetchall()
                for it in items: it['qty'] = _fmt_qty(it['qty'])
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
                        SELECT t.name, SUM(tr.quantity) as qty
                        FROM transaction tr
                        JOIN tool t ON tr.tool_id = t.tool_id
                        WHERE tr.project_id = %s AND tr.user_id = %s AND tr.type = %s
                          AND DATE(tr.borrow_date) = (
                              SELECT DATE(borrow_date) FROM transaction WHERE transaction_id = %s
                          )
                        GROUP BY t.name
                    """, (row['project_id'], row['uid'], row['type'], row['first_trn']))
                    tool_names = [f"{r['name']} (Qty: {_fmt_qty(r['qty'])})" for r in cursor.fetchall()]
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
        self.print_master_receipt(trn_range, row['full_name'], tool_names, purpose, issued_at=row.get('borrow_date_full'))

    def open_scanner(self, target_entry, trigger_method):
        """Shared scanner window; the code lands in the box and the screen's own check runs (same as pressing Enter)."""
        from views.scan_dialog import open_scan_dialog
        if getattr(self, "_scan_win", None) is not None:
            try:
                if self._scan_win.winfo_exists():
                    return
            except Exception:
                pass

        def got(code):
            target_entry.delete(0, 'end')
            target_entry.insert(0, code)
            trigger_method()
        self._scan_win = open_scan_dialog(target_entry.winfo_toplevel(), got, "Scan QR Code")

    def _reset_borrower_ui(self, message, color="#D8000C"):
        self.active_borrow_user_id = None
        self.active_borrow_user_name = None
        self.b_user_name.configure(text=message, text_color=color)
        self.b_project_menu.configure(values=["Scan Employee ID first..."], state="disabled")
        self.b_project_menu.set("Scan Employee ID first...")
        self.active_projects_map.clear()
        self._clear_proj_req_display()

    def verify_borrower(self):
        raw = self.b_emp_id.get()
        if not raw.strip():
            return
        scan = v.parse_scan(raw)                       # accepts a typed ID, a badge QR, or "Employee ID: X"
        emp_id = scan.value if scan.kind == "worker" else raw.strip()
        try:
            b = iss.verify_borrower(self.user_info, emp_id)   # [RBAC] role + status re-checked in MySQL; archived/locked refused
        except Exception as e:
            self._reset_borrower_ui(f"❌ {friendly_message(e)}")
            return
        self.active_borrow_user_id = b['user_id']
        self.active_borrow_user_name = b['full_name']
        self.b_user_name.configure(text=f"✓ Verified: {b['full_name']} ({b['role']})", text_color="#2ECC71")
        self.active_projects_map.clear()
        if b['projects']:
            dropdown_vals = ["Select a project..."]
            for p in b['projects']:
                display_text = f"Proj {p['project_id']}: {p['name']} ({p['client']})"
                dropdown_vals.append(display_text)
                self.active_projects_map[display_text] = p['project_id']
            self.b_project_menu.configure(values=dropdown_vals, state="normal")
            self.b_project_menu.set(dropdown_vals[0])
        else:
            self.b_project_menu.configure(values=["No projects needing tools"], state="disabled")
            self.b_project_menu.set("No projects needing tools")
            # say WHY: an ended / unapproved / fully issued project used to just vanish from the list
            nl = chr(10)
            self.b_user_name.configure(text=f"✓ Verified: {b['full_name']} ({b['role']})" + nl + "ℹ " + (nl + "ℹ ").join(b['notices']),
                                       text_color="#D35400", justify="left")
        self._clear_proj_req_display()

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

        try:
            proj = iss.project_requirements(self.user_info, proj_id)
        except Exception as e:
            self._clear_proj_req_display()
            messagebox.showerror("Project", friendly_message(e), parent=self.issuance_modal)
            return
        reqs = proj['reqs']
        self.current_project_reqs = reqs

        for w in self.proj_req_frame.winfo_children(): w.destroy()

        if reqs:
            header_text = f"📍 Project: {proj['name']}\n🏢 Client: {proj['client']}  |  Site: {proj['location']}"
            ctk.CTkLabel(self.proj_req_frame, text=header_text, font=("Inter", 11, "bold"), text_color="#1E4528", justify="left").pack(anchor="w", padx=10, pady=(10, 5))
            ctk.CTkFrame(self.proj_req_frame, height=1, fg_color="#E0E0E0").pack(fill="x", padx=10, pady=(0, 5))

        all_fulfilled = True
        for r in reqs:
            needed = float(r['req_qty'])
            issued = float(r['issued_qty'])
            remaining = needed - issued
            if remaining > 0: all_fulfilled = False

            txt_color = "#D8000C" if remaining > 0 else "#2ECC71"
            status_txt = f"Needs {fmt_qty(remaining)}" if remaining > 0 else "✓ Fulfilled"
            row_str = f"• {r['name']}  |  Approved: {fmt_qty(needed)}  |  {status_txt}"
            ctk.CTkLabel(self.proj_req_frame, text=row_str, font=("Inter", 11, "bold" if remaining > 0 else "normal"), text_color=txt_color).pack(anchor="w", padx=10, pady=2)

        state = "disabled" if all_fulfilled else "normal"
        if hasattr(self, 'b_tag_id') and self.b_tag_id.winfo_exists():
            self.b_tag_id.configure(state=state)
            self.b_scan_btn.configure(state=state)
            if not all_fulfilled:
                self.b_tag_id.focus_set()

    def add_tool_to_cart(self):
        raw = self.b_tag_id.get().strip()
        if not raw: return

        selected_proj = self.b_project_menu.get()
        if selected_proj not in self.active_projects_map:
            messagebox.showerror("Unauthorized", "No valid project selected.", parent=self.issuance_modal)
            return

        try:                                           # O(1) from the tool cache; DB fallback; re-checked under lock at commit
            tool = iss.lookup_tool(self.user_info, raw)
        except NotFound as e:
            messagebox.showerror("Not Found", friendly_message(e), parent=self.issuance_modal)
            return
        except Exception as e:
            messagebox.showerror("Unavailable", friendly_message(e), parent=self.issuance_modal)
            return

        req = next((r for r in self.current_project_reqs if r['tool_id'] == tool.tool_id), None)
        if not req:
            messagebox.showerror("Unauthorized", f"'{tool.name}' is NOT approved for this project.", parent=self.issuance_modal)
            return

        allowed_qty = float(req['req_qty'])
        already_issued = float(req['issued_qty'])
        in_cart = sum(item['qty_borrowed'] for item in self.borrow_cart if item['id'] == tool.tool_id)
        available = float(tool.available)

        if (already_issued + in_cart + 1) > allowed_qty:
            messagebox.showerror("Limit Reached", f"Cannot add '{tool.name}'.\nApproved Limit: {fmt_qty(allowed_qty)}\nAlready Issued: {fmt_qty(already_issued)}\nIn Cart: {fmt_qty(in_cart)}", parent=self.issuance_modal)
            return
        if (in_cart + 1) > available:
            messagebox.showerror("Out of Stock", f"Cannot add '{tool.name}'.\nOnly {fmt_qty(available)} left in the warehouse.", parent=self.issuance_modal)
            return

        existing = next((item for item in self.borrow_cart if item['id'] == tool.tool_id), None)
        if existing:
            existing['qty_borrowed'] += 1
            existing['max_qty'] = available
        else:
            self.borrow_cart.append({
                "id": tool.tool_id, "name": tool.name, "cond": tool.condition,
                "tag": tool.tag_id, "qty_borrowed": 1, "max_qty": available
            })

        self.refresh_cart_ui()
        self.b_tag_id.delete(0, 'end')

    def update_cart_qty(self, index, change):
        item = self.borrow_cart[index]
        new_qty = item['qty_borrowed'] + change
        req = next((r for r in self.current_project_reqs if r['tool_id'] == item['id']), None)
        if not req: return
        allowed_qty = float(req['req_qty'])
        already_issued = float(req['issued_qty'])
        
        if (already_issued + new_qty) > allowed_qty:
            messagebox.showwarning("Limit Reached", f"You cannot exceed the approved limit of {fmt_qty(allowed_qty)}.", parent=self.issuance_modal)
        elif new_qty > item['max_qty']:
            messagebox.showwarning("Out of Stock", f"Only {item['max_qty']} available in warehouse.", parent=self.issuance_modal)
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
            return messagebox.showerror("Error", "Please scan and verify an Employee ID first.", parent=self.issuance_modal)
        selected_proj = self.b_project_menu.get()
        proj_id = self.active_projects_map.get(selected_proj)
        if not proj_id:
            return messagebox.showerror("Error", "Please select a target project.", parent=self.issuance_modal)
        if len(self.borrow_cart) == 0:
            return messagebox.showerror("Error", "The cart is empty! Scan at least one tool.", parent=self.issuance_modal)

        cart = [{"tool_id": it['id'], "qty": it['qty_borrowed']} for it in self.borrow_cart]
        try:
            # [CONCURRENCY] ONE transaction: lock stock + project quota, re-validate, decrement, record, commit (or roll back all)
            res = iss.issue(self.user_info, self.active_borrow_user_id, proj_id, cart, selected_proj)
        except Exception as e:
            return messagebox.showerror("Could not issue", friendly_message(e), parent=self.issuance_modal)

        threading.Thread(target=lambda: tool_cache.refresh_changed(), daemon=True).start()   # other screens see the new stock at once
        receipt_tool_list = [f"{name} (Qty: {_fmt_qty(qty)})" for name, qty in res.receipt_lines]
        total_items = sum(qty for _, qty in res.receipt_lines)
        msg = f"{_fmt_qty(total_items)} item(s) issued successfully! Generating receipt..."
        if res.all_fulfilled:
            msg += "\n\nAll tools fulfilled!"
            if res.project_now_ongoing:
                msg += " Project status automatically updated to 'Ongoing'."
        messagebox.showinfo("Success", msg, parent=self.issuance_modal)

        ids = res.transaction_ids
        master_trans_id = f"{ids[0]}-{ids[-1]}" if len(ids) > 1 else str(ids[0])
        self.print_master_receipt(master_trans_id, self.active_borrow_user_name, receipt_tool_list, selected_proj,
                                  issued_at=res.issued_at)

        self.issuance_modal.destroy()
        self.load_transaction_history()

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

    def _build_receipt_image(self, trans_id_range, b_name, tool_names, purpose, issued_at=None):
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
        # [4-DATE] the receipt shows when the tools were ISSUED (server clock, from the transaction), never the clock of
        # the PC that prints it, so a reprint always matches the record and LAN PCs with drifting clocks cannot disagree.
        if hasattr(issued_at, "strftime"):
            current_time = issued_at.strftime("%B %d, %Y  —  %I:%M %p")
        else:
            current_time = str(issued_at) if issued_at else "—"
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

    def print_master_receipt(self, trans_id_range, b_name, tool_names, purpose, issued_at=None):
        try:
            img = self._build_receipt_image(trans_id_range, b_name, tool_names, purpose, issued_at)

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

            def export_jpg():
                import tempfile as _tf
                path = os.path.join(_tf.gettempdir(), "Receipt.jpg")
                img.save(path, "JPEG", quality=95)
                os.startfile(path)

            ctk.CTkButton(btn_bar, text="🖨  Export & Open JPG", height=38,
                          fg_color="#1E4528", hover_color="#14301C",
                          font=("Inter", 12, "bold"),
                          command=export_jpg).pack(side="left", padx=20, pady=11)
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
            messagebox.showwarning("Authentication Required", "Please scan Employee ID first before returning a tool.", parent=self.retrieval_modal)
            self.r_tag_id.delete(0, 'end')
            return

        raw = self.r_tag_id.get().strip()
        if not raw: return
        try:
            rec = iss.find_deployed(self.user_info, self.active_return_user_id, raw)
        except Exception as e:
            self.active_return_tool_id = None; self.active_return_item_type = None; self.max_returnable = 0
            self.r_record_info.configure(text=f"❌ {friendly_message(e)}", text_color="#D8000C")
            return
        self.active_return_tool_id = rec['tool_id']
        self.active_return_item_type = rec['item_type']
        self.max_returnable = float(rec['deployed'])
        self.r_record_info.configure(text=f"✓ Tool Identified: {rec['name']}\nCurrently Deployed Out: {_fmt_qty(rec['deployed'])}", text_color="#2ECC71")
        self.r_qty.delete(0, 'end'); self.r_qty.insert(0, "1")

    def verify_return_employee(self):
        raw = self.r_emp_id.get()
        if not raw.strip(): return
        scan = v.parse_scan(raw)
        emp_id = scan.value if scan.kind == "worker" else raw.strip()
        try:
            user = iss.verify_returner(self.user_info, emp_id)
        except Exception as e:
            self.active_return_user_id = None
            self.r_user_name.configure(text=f"❌ {friendly_message(e)}", text_color="#D8000C")
            return
        self.active_return_user_id = user['user_id']
        note = "" if user['status'] == 'Active' else f" - account {user['status']}"
        self.r_user_name.configure(text=f"✓ Verified: {user['full_name']} ({user['role']}){note}", text_color="#2ECC71")

    def execute_return(self):
        if not self.active_return_tool_id or not self.active_return_user_id:
            return messagebox.showerror("Error", "Please scan and verify both Employee ID and Tag ID/TRN.", parent=self.retrieval_modal)

        new_cond = self.r_condition.get()
        condition_notes = self.r_condition_desc.get("1.0", "end").strip()
        if new_cond != "Good" and not condition_notes:
            return messagebox.showwarning("Condition Details Required",
                                          f"Please describe what is wrong before returning an item as '{new_cond}'.",
                                          parent=self.retrieval_modal)
        try:
            # [CONCURRENCY][UNHAPPY-PATH] one transaction: close the issuance rows, move the units (stock / maintenance / lost),
            # create the Maintenance ticket for anything that is not Good, commit. Any failure rolls all of it back.
            res = iss.retrieve(self.user_info, self.active_return_user_id, self.active_return_tool_id,
                               self.r_qty.get(), new_cond, condition_notes)
        except Exception as e:
            return messagebox.showerror("Could not retrieve", friendly_message(e), parent=self.retrieval_modal)

        threading.Thread(target=lambda: tool_cache.refresh_changed(), daemon=True).start()
        qty = _fmt_qty(res.quantity)
        if new_cond == "Good":
            msg = f"Successfully retrieved {qty} item(s)!\n\nRestocked successfully."
        elif new_cond == "Lost":
            msg = (f"Retrieved {qty} item(s) recorded as 'Lost'.\n\nDeducted from Total Inventory. "
                   f"A ticket (#{res.ticket_id}) was created in Maintenance > Issues & Repairs.")
        else:
            msg = (f"Retrieved {qty} item(s) recorded as '{new_cond}'.\n\nThese units are held back from stock; the other units "
                   f"remain available. A ticket (#{res.ticket_id}) was created in Maintenance > Issues & Repairs.")
        messagebox.showinfo("Success", msg, parent=self.retrieval_modal)      # shown ONCE

        self.retrieval_modal.destroy()
        self.load_transaction_history()
