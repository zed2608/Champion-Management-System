import os
import customtkinter as ctk
import sys
from tkinter import messagebox
from datetime import datetime
from PIL import Image
from database import get_connection, log_action

# Data Visualization
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# Import Views
from views.projects import ProjectsView
from views.inventory import InventoryView
from views.profile import ProfileView
from views.borrowing import IssuanceView
from views.tracking import TrackingView
from views.reports import ReportsView
from views.maintenance import MaintenanceView
from views.role_management import RoleManagementView
from views.help import HelpView


class DashboardApp(ctk.CTkToplevel):
    def __init__(self, parent, user_info):
        super().__init__(master=parent)

        self.user_info = user_info
        self.title("Champion Fine Tooling - Automated Management System")

        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = int(sw * 0.85)
        h = int(sh * 0.85)
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(1350, 750)

        self.protocol("WM_DELETE_WINDOW", self.confirm_logout)

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(1, weight=1)

        self.build_sidebar()
        self.build_topbar()

        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.grid(
            row=1, column=1, sticky="nsew", padx=30, pady=30)
        self.main_container.grid_rowconfigure(0, weight=1)
        self.main_container.grid_columnconfigure(0, weight=1)

        self.current_frame = None
        self.current_page_name = None
        self.dashboard_refresh_job = None
        self._inactivity_job = None
        self._warning_dialog = None

        self.show_frame("Dashboard")
        self._start_inactivity_timer()
        self.dashboard_refresh_job = self.after(
            15000, self._auto_refresh_dashboard)

        # Reset inactivity timer on any user interaction
        self.bind_all("<Motion>", self._reset_inactivity_timer)
        self.bind_all("<Key>", self._reset_inactivity_timer)
        self.bind_all("<Button>", self._reset_inactivity_timer)

    def build_sidebar(self):
        self.sidebar_frame = ctk.CTkFrame(
            self, width=250, corner_radius=0, fg_color="#1A3B22")
        self.sidebar_frame.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.sidebar_frame.grid_propagate(False)

        self.icon_path = os.path.join(os.path.dirname(
            __file__), "assets", "login_logo.png")
        try:
            self.sidebar_icon_img = ctk.CTkImage(
                light_image=Image.open(self.icon_path), size=(50, 50))
            self.sidebar_logo = ctk.CTkLabel(
                self.sidebar_frame, image=self.sidebar_icon_img, text="")
            self.sidebar_logo.pack(pady=(30, 10))
        except FileNotFoundError:
            self.sidebar_logo = ctk.CTkLabel(
                self.sidebar_frame, text="🟢", font=("Inter", 40))
            self.sidebar_logo.pack(pady=(30, 10))

        ctk.CTkLabel(self.sidebar_frame, text="Automated Management\nSystem",
                     font=("Inter", 14, "bold"), text_color="white").pack(pady=(0, 30))

        is_admin = self.user_info.get("role", "Staff") == "Admin"

        nav_items = [
            "Dashboard",
            "Inventory",
            "Issuance & Retrieval",
            "Tracking & Accountability",
        ]

        if is_admin:
            nav_items.insert(1, "Project Management")
            nav_items += ["Reports", "Maintenance", "Role Management"]

        nav_items.append("Help")

        self.nav_buttons = {}
        self.nav_badges = {}
        for item in nav_items:
            container = ctk.CTkFrame(
                self.sidebar_frame, fg_color="transparent")
            container.pack(fill="x", pady=2, padx=10)

            btn = ctk.CTkButton(
                container, text=item, anchor="w",
                fg_color="transparent", hover_color="#2A6038",
                text_color="white", font=("Inter", 13, "bold"),
                command=lambda m=item: self.show_frame(m)
            )
            btn.pack(side="left", fill="x", expand=True)

            badge = ctk.CTkLabel(container, text="", width=8,
                                 height=8, corner_radius=4, fg_color="transparent")
            badge.pack(side="right", padx=(10, 10))

            self.nav_buttons[item] = btn
            self.nav_badges[item] = badge

        ctk.CTkButton(
            self.sidebar_frame, text="Exit", anchor="w",
            fg_color="transparent", hover_color="#8B0000",
            text_color="white", font=("Inter", 13, "bold"),
            command=self.confirm_logout
        ).pack(side="bottom", fill="x", pady=20, padx=10)

    def build_topbar(self):
        self.topbar_frame = ctk.CTkFrame(
            self, height=60, corner_radius=0, fg_color="white")
        self.topbar_frame.grid(row=0, column=1, sticky="ew")
        self.topbar_frame.pack_propagate(False)

        self.logo_path = os.path.join(
            os.path.dirname(__file__), "assets", "logo.png")
        try:
            self.topbar_logo_img = ctk.CTkImage(
                light_image=Image.open(self.logo_path), size=(30, 30))
            self.header_logo = ctk.CTkLabel(
                self.topbar_frame, image=self.topbar_logo_img,
                text=" Champion Fine Tooling", compound="left",
                font=("Inter", 14, "bold"), text_color="#1A3B22"
            )
            self.header_logo.pack(side="left", padx=30)
        except FileNotFoundError:
            self.header_logo = ctk.CTkLabel(
                self.topbar_frame, text="Champion Fine Tooling",
                font=("Inter", 14, "bold"), text_color="#1A3B22"
            )
            self.header_logo.pack(side="left", padx=30)

        self.time_label = ctk.CTkLabel(
            self.topbar_frame, text="", font=("Inter", 12), text_color="#666666")
        self.time_label.pack(side="right", padx=(10, 30), pady=20)
        self._update_clock()

        self.user_frame = ctk.CTkFrame(
            self.topbar_frame, fg_color="transparent", cursor="hand2")
        self.user_frame.pack(side="right", padx=15, pady=5)
        self.user_frame.bind(
            "<Button-1>", lambda e: self.show_frame("Profile"))

        self.user_text_frame = ctk.CTkFrame(
            self.user_frame, fg_color="transparent", cursor="hand2")
        self.user_text_frame.pack(side="right", padx=(10, 0))
        self.user_text_frame.bind(
            "<Button-1>", lambda e: self.show_frame("Profile"))

        self.user_name_label = ctk.CTkLabel(
            self.user_text_frame, text=f"{self.user_info['full_name']}",
            font=("Inter", 14, "bold"), text_color="black"
        )
        self.user_name_label.pack(anchor="w")
        self.user_name_label.bind(
            "<Button-1>", lambda e: self.show_frame("Profile"))

        self.user_role_label = ctk.CTkLabel(
            self.user_text_frame, text=f"{self.user_info['role']}",
            font=("Inter", 12, "bold"), text_color="#2ECC71"
        )
        self.user_role_label.pack(anchor="w")
        self.user_role_label.bind(
            "<Button-1>", lambda e: self.show_frame("Profile"))

        self.profile_pic_label = ctk.CTkLabel(self.user_frame, text="")
        self.profile_pic_label.pack(side="right")
        self.profile_pic_label.bind(
            "<Button-1>", lambda e: self.show_frame("Profile"))

        self.refresh_topbar()

    def _update_clock(self):
        current_time = datetime.now().strftime("%a, %b %d, %Y  %I:%M:%S %p")
        self.time_label.configure(text=current_time)
        self._clock_job = self.after(1000, self._update_clock)

    def refresh_topbar(self):
        self.user_name_label.configure(text=f"{self.user_info['full_name']}")
        self.user_role_label.configure(text=f"{self.user_info['role']}")
        pic_path = os.path.join(
            os.path.dirname(__file__), "assets", "profiles",
            f"{self.user_info['employee_id']}.png"
        )
        if not os.path.exists(pic_path):
            pic_path = os.path.join(os.path.dirname(
                __file__), "assets", "login_logo.png")
        try:
            self.topbar_profile_img = ctk.CTkImage(
                light_image=Image.open(pic_path), size=(40, 40))
            self.profile_pic_label.configure(image=self.topbar_profile_img)
        except Exception:
            self.profile_pic_label.configure(text="👤")

    # Kept intact in case other parts of the original logic implicitly relied on them
    def _get_column_min_sizes(self, weights, base_width=650):
        total = sum(weights) or 1
        return [max(60, int((w / total) * base_width)) for w in weights]

    def _make_header(self, parent, headers, weights, pad_left=20, pad_right=36):
        header_frame = ctk.CTkFrame(
            parent, fg_color="#1E4528", corner_radius=5, height=35)
        header_frame.pack(fill="x", padx=(pad_left, pad_right))
        header_frame.pack_propagate(False)

        min_sizes = self._get_column_min_sizes(weights)
        for col, (text, weight) in enumerate(zip(headers, weights)):
            header_frame.grid_columnconfigure(
                col, weight=weight, minsize=min_sizes[col])
            ctk.CTkLabel(header_frame, text=text, font=("Inter", 11, "bold"),
                         text_color="white", anchor="center").grid(row=0, column=col, padx=10, pady=5, sticky="ew")
        return header_frame

    def _make_row(self, parent, values, weights, bg):
        row_frame = ctk.CTkFrame(parent, fg_color=bg, height=35)
        row_frame.pack(fill="x", padx=20, pady=0)
        row_frame.pack_propagate(False)

        min_sizes = self._get_column_min_sizes(weights)
        for col, (value, weight) in enumerate(zip(values, weights)):
            row_frame.grid_columnconfigure(
                col, weight=weight, minsize=min_sizes[col])
        return row_frame

    def confirm_logout(self):
        if hasattr(self, "_clock_job"):
            self.after_cancel(self._clock_job)
        if hasattr(self, "dashboard_refresh_job") and self.dashboard_refresh_job:
            self.after_cancel(self.dashboard_refresh_job)
        if hasattr(self, "_inactivity_job") and self._inactivity_job:
            self.after_cancel(self._inactivity_job)
            self._inactivity_job = None

        if messagebox.askyesno("Confirm Logout", "Are you sure you want to log out of your account?"):
            log_action(self.user_info.get("user_id"), "Logout", "Authentication",
                       f"User {self.user_info.get('full_name')} logged out.")
            self.destroy()
            self.master.deiconify()
            self.master.pass_entry.delete(0, "end")

            self.master.pass_entry.configure(show="•")
            self.master.eye_btn.configure(text="👁")
            self.master.show_pwd = False

            self.master.error_banner.configure(text="", fg_color="transparent")
            self.master.failed_attempts = 0

    # ── Inactivity Auto-Logout ───────────────────────────────────────────────
    _INACTIVITY_MS = 5 * 60 * 1000   # 5 minutes
    _WARNING_MS = 30               # 30-second countdown in the warning dialog

    def _start_inactivity_timer(self):
        if self._inactivity_job:
            self.after_cancel(self._inactivity_job)
        self._inactivity_job = self.after(
            self._INACTIVITY_MS, self._show_inactivity_warning)

    def _reset_inactivity_timer(self, event=None):
        if self._warning_dialog and self._warning_dialog.winfo_exists():
            return
        self._start_inactivity_timer()

    def _show_inactivity_warning(self):
        if not self.winfo_exists():
            return

        if self._warning_dialog and self._warning_dialog.winfo_exists():
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("Inactivity Warning")
        dialog.resizable(False, False)
        dialog.grab_set()
        dialog.lift()

        self.update_idletasks()
        dx = self.winfo_x() + (self.winfo_width() - 360) // 2
        dy = self.winfo_y() + (self.winfo_height() - 200) // 2
        dialog.geometry(f"360x200+{dx}+{dy}")

        self._warning_dialog = dialog
        self._warning_remaining = self._WARNING_MS

        ctk.CTkLabel(dialog, text="⚠ Session Inactivity",
                     font=("Inter", 15, "bold"), text_color="#C0392B").pack(pady=(20, 4))
        ctk.CTkLabel(dialog, text="You have been inactive for 5 minutes.",
                     font=("Inter", 11), text_color="#555555").pack()

        self._countdown_label = ctk.CTkLabel(dialog,
                                             text=f"Logging out in {self._warning_remaining} seconds…",
                                             font=("Inter", 12), text_color="#333333")
        self._countdown_label.pack(pady=(10, 16))

        ctk.CTkButton(dialog, text="Stay Logged In", width=160,
                      fg_color="#1E4528", hover_color="#14301C",
                      font=("Inter", 12, "bold"),
                      command=lambda: self._cancel_inactivity_logout(dialog)).pack()

        self._tick_warning()

    def _tick_warning(self):
        if not self.winfo_exists():
            return

        if not (self._warning_dialog and self._warning_dialog.winfo_exists()):
            return

        if self._warning_remaining <= 0:
            self._warning_dialog.destroy()
            self._warning_dialog = None
            self._force_logout()
            return

        self._countdown_label.configure(
            text=f"Logging out in {self._warning_remaining} seconds…")
        self._warning_remaining -= 1
        self._inactivity_job = self.after(1000, self._tick_warning)

    def _cancel_inactivity_logout(self, dialog):
        if dialog.winfo_exists():
            dialog.destroy()
        self._warning_dialog = None
        self._start_inactivity_timer()

    def _force_logout(self):
        if hasattr(self, "_clock_job"):
            self.after_cancel(self._clock_job)
        if hasattr(self, "dashboard_refresh_job") and self.dashboard_refresh_job:
            self.after_cancel(self.dashboard_refresh_job)
            self.dashboard_refresh_job = None
        log_action(self.user_info.get("user_id"), "Auto-Logout", "Authentication",
                   f"Session expired due to inactivity — {self.user_info.get('full_name')}.")
        self.destroy()
        self.master.deiconify()
        self.master.pass_entry.delete(0, "end")

        self.master.pass_entry.configure(show="•")
        self.master.eye_btn.configure(text="👁")
        self.master.show_pwd = False

        self.master.error_banner.configure(text="", fg_color="transparent")
        self.master.failed_attempts = 0

    def _show_loading_overlay(self):
        """Show a spinner overlay on the main container while switching frames."""
        overlay = ctk.CTkFrame(self.main_container,
                               fg_color="white", corner_radius=10)
        overlay.place(relx=0.5, rely=0.5, anchor="center",
                      relwidth=1.0, relheight=1.0)
        spinner_lbl = ctk.CTkLabel(overlay, text="⟳", font=(
            "Inter", 36), text_color="#1E4528")
        spinner_lbl.place(relx=0.5, rely=0.5, anchor="center")
        msg_lbl = ctk.CTkLabel(overlay, text="Loading...",
                               font=("Inter", 13), text_color="gray")
        msg_lbl.place(relx=0.5, rely=0.56, anchor="center")

        # Animate the spinner
        _angle = ["⟳", "↻", "⟳", "↺"]
        _idx = [0]

        def _spin():
            if overlay.winfo_exists():
                spinner_lbl.configure(text=_angle[_idx[0] % len(_angle)])
                _idx[0] += 1
                overlay._spin_job = self.after(120, _spin)
        _spin()
        return overlay

    def show_frame(self, page_name, highlight_low_stock=False, highlight_tool_id=None):
        is_admin = self.user_info.get("role", "Staff") == "Admin"
        restricted_modules = ["Project Management",
                              "Reports", "Maintenance", "Role Management"]

        if not is_admin and page_name in restricted_modules:
            messagebox.showerror(
                "Access Denied", "You do not have permission to access this module.")
            return

        self.current_page_name = page_name

        for name, btn in self.nav_buttons.items():
            if name == page_name:
                btn.configure(fg_color="#2A6038", text_color="#F1C40F")
            else:
                btn.configure(fg_color="transparent", text_color="white")

        if self.current_frame is not None:
            self.current_frame.destroy()

        # Show spinner overlay while the new frame is built
        overlay = self._show_loading_overlay()

        uid = self.user_info.get("user_id")
        if uid and page_name != "Dashboard":
            log_action(uid, "Viewed", page_name, f"Navigated to {page_name}")

        if page_name == "Profile":
            self.current_frame = ProfileView(
                self.main_container, self.user_info, self)
        elif page_name == "Project Management":
            self.current_frame = ProjectsView(
                self.main_container, self.user_info)
        elif page_name == "Inventory":
            self.current_frame = InventoryView(
                self.main_container, self.user_info,
                navigate_to=self.navigate_to_project,
                highlight_low_stock=highlight_low_stock,
                highlight_tool_id=highlight_tool_id,
            )
        elif page_name == "Issuance & Retrieval":
            self.current_frame = IssuanceView(
                self.main_container, self.user_info, navigate_to=self.navigate_to_project)
        elif page_name == "Tracking & Accountability":
            self.current_frame = TrackingView(
                self.main_container, self.user_info)
        elif page_name == "Reports":
            self.current_frame = ReportsView(
                self.main_container, navigate_to_tool=self.navigate_to_tool)
        elif page_name == "Maintenance":
            self.current_frame = MaintenanceView(
                self.main_container, self.user_info)
        elif page_name == "Role Management":
            self.current_frame = RoleManagementView(
                self.main_container, self.user_info)
        elif page_name == "Help":
            self.current_frame = HelpView(self.main_container, self.user_info)
        elif page_name == "Dashboard":
            self.current_frame = self.create_home_dashboard()
        else:
            self.current_frame = ctk.CTkFrame(
                self.main_container, fg_color="transparent")
            ctk.CTkLabel(self.current_frame, text=f"{page_name.upper()} MODULE",
                         font=("Inter", 20), text_color="gray").pack(expand=True)

        # Remove overlay and show the real frame
        if overlay.winfo_exists():
            if hasattr(overlay, "_spin_job"):
                self.after_cancel(overlay._spin_job)
            overlay.destroy()

        self.current_frame.place(
            relx=0.5, rely=0.5, anchor="center", relwidth=1.0, relheight=1.0)

    def navigate_to_tool(self, tool_id):
        self.show_frame("Inventory", highlight_tool_id=tool_id)

    def navigate_to_project(self, project_id):
        self.show_frame("Project Management")
        if hasattr(self.current_frame, 'open_project_by_id'):
            self.current_frame.open_project_by_id(project_id)

    def get_live_metrics(self):
        metrics = {
            "total_employees": 0,
            "active_workforce": 0,
            "available_qty": 0,
            "borrowed_qty": 0,
            "total_physical": 0,
            "utilization_pct": 0,
            "pending_issues": 0,
            "overdue_projects": 0,
            "action_items": 0,
            "low_stock": 0,
            "proj_active": 0,
            "proj_pending": 0,
            "proj_completed_month": 0,
            "pwd_resets": 0,
        }
        activities = []
        # chart_data: 7 days of (issues, retrievals) — [(day_label, issued, retrieved), ...]
        chart_data = []
        # deployed_rows: [(project_name, tool_count), ...] top 5
        deployed_rows = []
        # my_issuances: [(tool_name, issued_date, project_name), ...] for current user
        my_issuances = []

        conn = get_connection()
        if not conn:
            return metrics, activities, chart_data, deployed_rows, my_issuances

        try:
            cursor = conn.cursor(dictionary=True)

            cursor.execute("SELECT COUNT(*) as cnt FROM user")
            metrics["total_employees"] = int(cursor.fetchone()["cnt"] or 0)

            # Fix: only count users with activity in last 30 days
            cursor.execute("""
                SELECT COUNT(DISTINCT user_id) as cnt FROM transaction
                WHERE status = 'Active' AND borrow_date >= DATE_SUB(NOW(), INTERVAL 30 DAY)
            """)
            metrics["active_workforce"] = int(cursor.fetchone()["cnt"] or 0)

            cursor.execute(
                "SELECT IFNULL(SUM(quantity_available), 0) as qty FROM inventory")
            metrics["available_qty"] = int(cursor.fetchone()["qty"] or 0)

            cursor.execute(
                "SELECT COUNT(*) as cnt FROM transaction WHERE status = 'Active'")
            metrics["borrowed_qty"] = int(cursor.fetchone()["cnt"] or 0)

            metrics["total_physical"] = metrics["available_qty"] + \
                metrics["borrowed_qty"]
            if metrics["total_physical"] > 0:
                metrics["utilization_pct"] = int(
                    (metrics["borrowed_qty"] / metrics["total_physical"]) * 100)

            try:
                cursor.execute(
                    "SELECT COUNT(*) as cnt FROM tool WHERE `condition` IN ('Needs Repair', 'Damaged', 'Lost') AND is_archived = 0")
                metrics["pending_issues"] = int(cursor.fetchone()["cnt"] or 0)
            except Exception:
                pass

            metrics["action_items"] = metrics["pending_issues"]

            try:
                cursor.execute(
                    "SELECT COUNT(*) as cnt FROM projects WHERE status NOT IN ('Completed', 'Cancelled') AND end_date < CURDATE()")
                metrics["overdue_projects"] = int(
                    cursor.fetchone()["cnt"] or 0)
            except Exception:
                pass

            try:
                cursor.execute(
                    "SELECT COUNT(*) as cnt FROM projects WHERE status = 'Pending'")
                metrics["pending_projects"] = int(
                    cursor.fetchone()["cnt"] or 0)
            except Exception:
                metrics["pending_projects"] = 0

            # Low stock: items where quantity_available < minimum_stock
            try:
                cursor.execute("""
                    SELECT COUNT(*) as cnt FROM inventory i
                    WHERE i.minimum_stock > 0 AND i.quantity_available < i.minimum_stock
                """)
                metrics["low_stock"] = int(cursor.fetchone()["cnt"] or 0)
            except Exception:
                pass

            # Project status counts
            try:
                cursor.execute(
                    "SELECT COUNT(*) as cnt FROM projects WHERE status = 'Active'")
                metrics["proj_active"] = int(cursor.fetchone()["cnt"] or 0)
                cursor.execute(
                    "SELECT COUNT(*) as cnt FROM projects WHERE status = 'Pending'")
                metrics["proj_pending"] = int(cursor.fetchone()["cnt"] or 0)
                cursor.execute("""
                    SELECT COUNT(*) as cnt FROM projects
                    WHERE status = 'Completed' AND MONTH(end_date) = MONTH(CURDATE()) AND YEAR(end_date) = YEAR(CURDATE())
                """)
                metrics["proj_completed_month"] = int(
                    cursor.fetchone()["cnt"] or 0)
            except Exception:
                pass

            # Password Reset Requests
            try:
                cursor.execute("SELECT COUNT(*) as cnt FROM user WHERE reset_requested = 1")
                metrics["pwd_resets"] = int(cursor.fetchone()["cnt"] or 0)
            except Exception:
                pass

            # Activity feed
            cursor.execute("""
                SELECT
                    DATE_FORMAT(raw_date, '%Y-%m-%d %I:%i %p') as ts,
                    action, item, actor
                FROM (
                    SELECT borrow_date as raw_date, 'Issued' as action, t.name as item, u.full_name as actor
                    FROM transaction tr
                    JOIN tool t ON tr.tool_id = t.tool_id
                    JOIN user u ON tr.user_id = u.user_id
                    WHERE tr.type = 'Issue'

                    UNION ALL

                    SELECT return_date as raw_date, 'Retrieved' as action, t.name as item, u.full_name as actor
                    FROM transaction tr
                    JOIN tool t ON tr.tool_id = t.tool_id
                    JOIN user u ON tr.user_id = u.user_id
                    WHERE tr.type = 'Retrieval' AND tr.return_date IS NOT NULL

                    UNION ALL

                    SELECT sl.timestamp as raw_date, 'Project Created' as action, sl.details as item, IFNULL(u.full_name, 'System') as actor
                    FROM system_logs sl
                    LEFT JOIN user u ON sl.user_id = u.user_id
                    WHERE sl.action_type = 'Submitted' AND sl.module = 'Projects'
                ) as combined_log
                ORDER BY raw_date DESC
                LIMIT 10
            """)
            for row in cursor.fetchall():
                activities.append(
                    (row["ts"], row["action"], row["item"], row["actor"]))

            # 7-day deployment trend
            try:
                cursor.execute("""
                    SELECT
                        d.day_label,
                        IFNULL(i.issued, 0)    AS issued,
                        IFNULL(r.retrieved, 0) AS retrieved
                    FROM (
                        SELECT DATE_SUB(CURDATE(), INTERVAL n DAY) AS day_date,
                               DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL n DAY), '%a') AS day_label
                        FROM (SELECT 6 n UNION SELECT 5 UNION SELECT 4 UNION SELECT 3
                              UNION SELECT 2 UNION SELECT 1 UNION SELECT 0) nums
                    ) d
                    LEFT JOIN (
                        SELECT DATE(borrow_date) as dd, COUNT(*) as issued
                        FROM transaction WHERE type='Issue' AND borrow_date >= DATE_SUB(CURDATE(), INTERVAL 6 DAY)
                        GROUP BY dd
                    ) i ON i.dd = d.day_date
                    LEFT JOIN (
                        SELECT DATE(return_date) as dd, COUNT(*) as retrieved
                        FROM transaction WHERE type='Retrieval' AND return_date >= DATE_SUB(CURDATE(), INTERVAL 6 DAY)
                        GROUP BY dd
                    ) r ON r.dd = d.day_date
                    ORDER BY d.day_date
                """)
                chart_data = [(row["day_label"], int(row["issued"]), int(
                    row["retrieved"])) for row in cursor.fetchall()]
            except Exception:
                pass

            # Currently deployed: top 5 projects by active tool count
            try:
                cursor.execute("""
                    SELECT p.name as project_name, COUNT(tr.transaction_id) as tool_count
                    FROM transaction tr
                    JOIN projects p ON tr.project_id = p.project_id
                    WHERE tr.status = 'Active'
                    GROUP BY p.project_id, p.name
                    ORDER BY tool_count DESC
                    LIMIT 5
                """)
                deployed_rows = [(row["project_name"], int(
                    row["tool_count"])) for row in cursor.fetchall()]
            except Exception:
                pass

            # My active issuances for current user
            try:
                uid = self.user_info.get("user_id")
                cursor.execute("""
                    SELECT t.name as tool_name,
                           DATE_FORMAT(tr.borrow_date, '%b %d, %Y') as issued_date,
                           IFNULL(p.name, '—') as project_name
                    FROM transaction tr
                    JOIN tool t ON tr.tool_id = t.tool_id
                    LEFT JOIN projects p ON tr.project_id = p.project_id
                    WHERE tr.user_id = %s AND tr.status = 'Active'
                    ORDER BY tr.borrow_date DESC
                    LIMIT 8
                """, (uid,))
                my_issuances = [(row["tool_name"], row["issued_date"],
                                 row["project_name"]) for row in cursor.fetchall()]
            except Exception:
                pass

        except Exception as e:
            print(f"Dashboard Sync Error: {e}")
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

        return metrics, activities, chart_data, deployed_rows, my_issuances

    def create_home_dashboard(self):
        is_admin = self.user_info.get("role", "Staff") == "Admin"

        frame = ctk.CTkScrollableFrame(
            self.main_container, fg_color="transparent", orientation="vertical")
        inner_frame = ctk.CTkFrame(frame, fg_color="transparent")
        inner_frame.pack(fill="both", expand=True)

        ctk.CTkLabel(inner_frame, text="EXECUTIVE DASHBOARD", font=("Inter", 24, "bold"),
                     text_color="#1A1A1A").pack(anchor="w", pady=(0, 5))
        ctk.CTkLabel(inner_frame, text="High-level overview of system health and asset utilization. Auto-updates live.",
                     font=("Inter", 13), text_color="gray").pack(anchor="w", pady=(0, 20))

        metrics = {
            "total_employees": 0, "active_workforce": 0, "available_qty": 0,
            "borrowed_qty": 0, "total_physical": 0, "utilization_pct": 0,
            "pending_issues": 0, "overdue_projects": 0, "action_items": 0,
            "pending_projects": 0, "low_stock": 0,
            "proj_active": 0, "proj_pending": 0, "proj_completed_month": 0,
        }
        activities, chart_data, deployed_rows, my_issuances = [], [], [], []

        # ── Row 1: Summary Cards ──────────────────────────────────────────────
        num_cards = 5 if is_admin else 4
        cards_frame = ctk.CTkFrame(inner_frame, fg_color="transparent")
        cards_frame.pack(fill="x", pady=(0, 10))
        for i in range(num_cards):
            cards_frame.grid_columnconfigure(i, weight=1)

        # Card 1 – Utilization
        c1 = ctk.CTkFrame(cards_frame, fg_color="#1E4528",
                          corner_radius=10, height=130)
        c1.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        c1.pack_propagate(False)
        self.dash_util_lbl = ctk.CTkLabel(c1, text="0%", font=(
            "Inter", 28, "bold"), text_color="white")
        self.dash_util_lbl.pack(anchor="w", padx=20, pady=(20, 0))
        ctk.CTkLabel(c1, text="Asset Utilization", font=(
            "Inter", 13, "bold"), text_color="white").pack(anchor="w", padx=20, pady=(5, 0))
        ctk.CTkLabel(c1, text="Deployed vs Warehouse", font=(
            "Inter", 11), text_color="white").pack(anchor="w", padx=20)

        # Card 2 – Active Workforce
        c2 = ctk.CTkFrame(cards_frame, fg_color="#2980B9",
                          corner_radius=10, height=130)
        c2.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        c2.pack_propagate(False)
        self.dash_wf_lbl = ctk.CTkLabel(
            c2, text="0 / 0", font=("Inter", 28, "bold"), text_color="white")
        self.dash_wf_lbl.pack(anchor="w", padx=20, pady=(20, 0))
        ctk.CTkLabel(c2, text="Active Workforce", font=(
            "Inter", 13, "bold"), text_color="white").pack(anchor="w", padx=20, pady=(5, 0))
        ctk.CTkLabel(c2, text="Active last 30 days", font=(
            "Inter", 11), text_color="white").pack(anchor="w", padx=20)

        # Card 3 – Total Inventory
        c3 = ctk.CTkFrame(cards_frame, fg_color="#F1C40F",
                          corner_radius=10, height=130)
        c3.grid(row=0, column=2, padx=5, pady=5, sticky="ew")
        c3.pack_propagate(False)
        self.dash_inv_lbl = ctk.CTkLabel(c3, text="0", font=(
            "Inter", 28, "bold"), text_color="black")
        self.dash_inv_lbl.pack(anchor="w", padx=20, pady=(20, 0))
        ctk.CTkLabel(c3, text="Total Inventory", font=(
            "Inter", 13, "bold"), text_color="black").pack(anchor="w", padx=20, pady=(5, 0))
        ctk.CTkLabel(c3, text="Total physical items", font=(
            "Inter", 11), text_color="black").pack(anchor="w", padx=20)

        # Card 4 – Low Stock (admin + staff)
        c_ls = ctk.CTkFrame(cards_frame, fg_color="#F9FAFB", corner_radius=10,
                            height=130, border_width=1, border_color="#E0E0E0")
        c_ls.grid(row=0, column=3, padx=5, pady=5, sticky="ew")
        c_ls.pack_propagate(False)
        self.dash_lowstock_top = ctk.CTkFrame(c_ls, fg_color="transparent")
        self.dash_lowstock_top.pack(fill="x", padx=20, pady=(15, 0))
        self.dash_lowstock_val = ctk.CTkLabel(self.dash_lowstock_top, text="0", font=(
            "Inter", 28, "bold"), text_color="black")
        self.dash_lowstock_val.pack(side="left")
        ctk.CTkLabel(c_ls, text="Low Stock Items", font=(
            "Inter", 13, "bold"), text_color="black").pack(anchor="w", padx=20, pady=(5, 0))
        ctk.CTkLabel(c_ls, text="Near reorder level →", font=(
            "Inter", 11), text_color="#888888").pack(anchor="w", padx=20)
        self._bind_widget_tree(
            c_ls, lambda *_: self.show_frame("Inventory", highlight_low_stock=True))

        if is_admin:
            # Card 5 – Action Items
            self.dash_action_card = ctk.CTkFrame(
                cards_frame, fg_color="#F9FAFB", corner_radius=10, height=130, border_width=1, border_color="#E0E0E0")
            self.dash_action_card.grid(
                row=0, column=4, padx=5, pady=5, sticky="ew")
            self.dash_action_card.pack_propagate(False)
            self.dash_action_top = ctk.CTkFrame(
                self.dash_action_card, fg_color="transparent")
            self.dash_action_top.pack(fill="x", padx=20, pady=(15, 0))
            self._render_action_badges(metrics)
            ctk.CTkLabel(self.dash_action_card, text="Action Items", font=(
                "Inter", 13, "bold"), text_color="black").pack(anchor="w", padx=20, pady=(5, 0))
            ctk.CTkLabel(self.dash_action_card, text="Maintenance →", font=(
                "Inter", 11), text_color="#888888").pack(anchor="w", padx=20)
            self._bind_widget_tree(self.dash_action_card,
                                   lambda *_: self.show_frame("Maintenance"))

        # ── Row 2: Project Status Strip (admin only) ─────────────────────────
        if is_admin:
            strip = ctk.CTkFrame(
                inner_frame, fg_color="white", corner_radius=10, height=60)
            strip.pack(fill="x", pady=(0, 10))
            strip.pack_propagate(False)
            strip_inner = ctk.CTkFrame(strip, fg_color="transparent")
            strip_inner.pack(expand=True, fill="both", padx=20)
            ctk.CTkLabel(strip_inner, text="Projects Status:", font=(
                "Inter", 12, "bold"), text_color="#555555").pack(side="left", padx=(0, 20))
            # Active
            pf_active = ctk.CTkFrame(
                strip_inner, fg_color="#E8F5E9", corner_radius=8)
            pf_active.pack(side="left", padx=5, pady=10, ipadx=12, ipady=4)
            self.dash_proj_active_lbl = ctk.CTkLabel(
                pf_active, text="0 Active", font=("Inter", 12, "bold"), text_color="#1E4528")
            self.dash_proj_active_lbl.pack()
            # Pending
            pf_pending = ctk.CTkFrame(
                strip_inner, fg_color="#FFF8E1", corner_radius=8)
            pf_pending.pack(side="left", padx=5, pady=10, ipadx=12, ipady=4)
            self.dash_proj_pending_lbl = ctk.CTkLabel(
                pf_pending, text="0 Pending", font=("Inter", 12, "bold"), text_color="#C07A00")
            self.dash_proj_pending_lbl.pack()
            # Overdue (merged here from removed card)
            pf_overdue = ctk.CTkFrame(
                strip_inner, fg_color="#FFF5F5", corner_radius=8)
            pf_overdue.pack(side="left", padx=5, pady=10, ipadx=12, ipady=4)
            self.dash_proj_overdue_lbl = ctk.CTkLabel(
                pf_overdue, text="0 Overdue", font=("Inter", 12, "bold"), text_color="#C0392B")
            self.dash_proj_overdue_lbl.pack()
            # Completed this month
            pf_done = ctk.CTkFrame(
                strip_inner, fg_color="#E3F2FD", corner_radius=8)
            pf_done.pack(side="left", padx=5, pady=10, ipadx=12, ipady=4)
            self.dash_proj_done_lbl = ctk.CTkLabel(pf_done, text="0 Completed (this month)", font=(
                "Inter", 12, "bold"), text_color="#1565C0")
            self.dash_proj_done_lbl.pack()
            self._bind_widget_tree(
                strip, lambda *_: self.show_frame("Project Management"))

        # ── Row 3: Bottom 2-column layout ─────────────────────────────────────
        bottom_frame = ctk.CTkFrame(inner_frame, fg_color="transparent")
        bottom_frame.pack(fill="both", expand=True)
        bottom_frame.grid_columnconfigure(0, weight=2)
        bottom_frame.grid_columnconfigure(1, weight=1)
        bottom_frame.grid_rowconfigure(0, weight=1)

        # Left column: activity feed
        activity_card = ctk.CTkFrame(
            bottom_frame, fg_color="white", corner_radius=10)
        activity_card.grid(row=0, column=0, sticky="nsew",
                           padx=(0, 10), pady=10)
        ctk.CTkLabel(activity_card, text="Recent Operations (Deployments & Projects)",
                     font=("Inter", 14, "bold"), text_color="#1A1A1A").pack(anchor="w", padx=20, pady=(20, 10))
        self.dash_activity_frame = ctk.CTkFrame(
            activity_card, fg_color="transparent")
        self.dash_activity_frame.pack(
            fill="both", expand=True, padx=10, pady=(0, 10))
        self._render_activity_feed(activities)

        # Right column: trend chart (admin) OR my issuances (staff)
        right_card = ctk.CTkFrame(
            bottom_frame, fg_color="white", corner_radius=10)
        right_card.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=10)

        if is_admin:
            ctk.CTkLabel(right_card, text="7-Day Deployment Trend",
                         font=("Inter", 14, "bold"), text_color="#1A1A1A").pack(anchor="w", padx=20, pady=(20, 5))
            self.dash_chart_frame = ctk.CTkFrame(
                right_card, fg_color="transparent")
            self.dash_chart_frame.pack(fill="both", expand=True)
            self.dash_fig, self.dash_ax, self.dash_canvas = self._embed_trend_chart(
                self.dash_chart_frame, chart_data)

            # Currently Deployed mini-table below chart
            ctk.CTkLabel(right_card, text="Currently Deployed by Project",
                         font=("Inter", 13, "bold"), text_color="#1A1A1A").pack(anchor="w", padx=20, pady=(10, 4))
            self.dash_deployed_frame = ctk.CTkFrame(
                right_card, fg_color="transparent")
            self.dash_deployed_frame.pack(fill="x", padx=10, pady=(0, 10))
            self._render_deployed_table(deployed_rows)
        else:
            # Staff: My Active Issuances
            ctk.CTkLabel(right_card, text="My Active Issuances",
                         font=("Inter", 14, "bold"), text_color="#1A1A1A").pack(anchor="w", padx=20, pady=(20, 5))
            self.dash_myissue_frame = ctk.CTkFrame(
                right_card, fg_color="transparent")
            self.dash_myissue_frame.pack(
                fill="both", expand=True, padx=10, pady=(0, 10))
            self._render_my_issuances(my_issuances)

        # Load real data in background
        import threading

        def _initial_load():
            m, a, c, dr, mi = self.get_live_metrics()
            self.after(0, lambda: self._apply_dashboard_data(m, a, c, dr, mi))
        threading.Thread(target=_initial_load, daemon=True).start()

        return frame

    def _embed_trend_chart(self, parent, chart_data):
        fig, ax = plt.subplots(figsize=(5.2, 2.6), dpi=100)  # Slightly wider
        fig.patch.set_facecolor("#FFFFFF")
        ax.set_facecolor("#FFFFFF")

        self._draw_trend(ax, chart_data)
        plt.tight_layout(pad=2.0)

        canvas = FigureCanvasTkAgg(fig, master=parent)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=15, pady=(5, 10))
        return fig, ax, canvas

    def _draw_trend(self, ax, chart_data):
        ax.clear()
        if not chart_data:
            ax.text(0.5, 0.5, "No data available", ha="center", va="center", 
                    transform=ax.transAxes, color="#aaa", fontsize=11)
            ax.axis("off")
            return

        labels = [r[0] for r in chart_data]
        issued = [r[1] for r in chart_data]
        retrieved = [r[2] for r in chart_data]

        x = range(len(labels))
        ax.plot(x, issued, marker="o", color="#27AE60", linewidth=2.5, label="Issued")
        ax.plot(x, retrieved, marker="o", color="#2980B9", linewidth=2.5, linestyle="--", label="Retrieved")

        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=10, rotation=0)   # No rotation needed with wider chart
        ax.set_ylabel("Count", fontsize=10)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.legend(fontsize=9, loc="upper left", frameon=False)
        ax.yaxis.set_major_locator(plt.MaxNLocator(integer=True))

    def _render_deployed_table(self, deployed_rows):
        for w in self.dash_deployed_frame.winfo_children():
            w.destroy()
        if not deployed_rows:
            ctk.CTkLabel(self.dash_deployed_frame, text="No tools currently deployed.",
                         font=("Inter", 11), text_color="#aaa").pack(pady=8)
            return
        hdr = ctk.CTkFrame(self.dash_deployed_frame,
                           fg_color="#1E4528", corner_radius=5, height=28)
        hdr.pack(fill="x", padx=0, pady=(0, 1))
        hdr.pack_propagate(False)
        hdr.grid_columnconfigure(0, weight=3)
        hdr.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(hdr, text="Project", font=("Inter", 10, "bold"),
                     text_color="white", anchor="w").grid(row=0, column=0, padx=8, sticky="ew")
        ctk.CTkLabel(hdr, text="Tools Out", font=("Inter", 10, "bold"), text_color="white",
                     anchor="center").grid(row=0, column=1, padx=8, sticky="ew")
        for i, (proj, cnt) in enumerate(deployed_rows):
            bg = "#F9FAFB" if i % 2 == 0 else "white"
            row = ctk.CTkFrame(self.dash_deployed_frame,
                               fg_color=bg, height=28)
            row.pack(fill="x", pady=0)
            row.pack_propagate(False)
            row.grid_columnconfigure(0, weight=3)
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(row, text=proj, font=("Inter", 10), text_color="#1A1A1A", anchor="w").grid(
                row=0, column=0, padx=8, sticky="ew")
            ctk.CTkLabel(row, text=str(cnt), font=("Inter", 10, "bold"), text_color="#1E4528",
                         anchor="center").grid(row=0, column=1, padx=8, sticky="ew")

    def _render_my_issuances(self, my_issuances):
        for w in self.dash_myissue_frame.winfo_children():
            w.destroy()
        if not my_issuances:
            ctk.CTkLabel(self.dash_myissue_frame, text="✓ No tools currently issued to you.",
                         font=("Inter", 11), text_color="#27AE60").pack(pady=20)
            return
        hdr = ctk.CTkFrame(self.dash_myissue_frame,
                           fg_color="#1E4528", corner_radius=5, height=28)
        hdr.pack(fill="x", pady=(0, 1))
        hdr.pack_propagate(False)
        hdr.grid_columnconfigure(0, weight=3)
        hdr.grid_columnconfigure(1, weight=2)
        hdr.grid_columnconfigure(2, weight=2)
        ctk.CTkLabel(hdr, text="Tool", font=("Inter", 10, "bold"), text_color="white",
                     anchor="w").grid(row=0, column=0, padx=8, sticky="ew")
        ctk.CTkLabel(hdr, text="Issued", font=("Inter", 10, "bold"), text_color="white",
                     anchor="center").grid(row=0, column=1, padx=4, sticky="ew")
        ctk.CTkLabel(hdr, text="Project", font=("Inter", 10, "bold"), text_color="white",
                     anchor="center").grid(row=0, column=2, padx=8, sticky="ew")
        for i, (tool, date, proj) in enumerate(my_issuances):
            bg = "#F9FAFB" if i % 2 == 0 else "white"
            row = ctk.CTkFrame(self.dash_myissue_frame, fg_color=bg, height=28)
            row.pack(fill="x", pady=0)
            row.pack_propagate(False)
            row.grid_columnconfigure(0, weight=3)
            row.grid_columnconfigure(1, weight=2)
            row.grid_columnconfigure(2, weight=2)
            ctk.CTkLabel(row, text=tool, font=("Inter", 10), text_color="#1A1A1A", anchor="w").grid(
                row=0, column=0, padx=8, sticky="ew")
            ctk.CTkLabel(row, text=date, font=("Inter", 10), text_color="#555",
                         anchor="center").grid(row=0, column=1, padx=4, sticky="ew")
            ctk.CTkLabel(row, text=proj, font=("Inter", 10), text_color="#2980B9",
                         anchor="center").grid(row=0, column=2, padx=8, sticky="ew")

    def _bind_widget_tree(self, widget, callback):
        try:
            widget.configure(cursor="hand2")
            widget.bind("<Button-1>", callback)
        except Exception:
            pass
        for child in widget.winfo_children():
            self._bind_widget_tree(child, callback)

    def _render_action_badges(self, metrics):
        if not hasattr(self, "dash_action_top"):
            return
        for w in self.dash_action_top.winfo_children():
            w.destroy()

        if metrics["action_items"] == 0:
            ctk.CTkLabel(self.dash_action_top, text="0", font=(
                "Inter", 28, "bold"), text_color="black").pack(side="left")
            ctk.CTkLabel(self.dash_action_top, text="✓ All Clear", fg_color="#2ECC71", text_color="white", font=(
                "Inter", 11, "bold"), corner_radius=6, padx=10, pady=3).pack(side="left", padx=(15, 0), pady=(5, 0))
            self.dash_action_card.configure(
                fg_color="#F9FAFB", border_color="#E0E0E0")
        else:
            ctk.CTkLabel(self.dash_action_top, text=str(metrics['action_items']), font=(
                "Inter", 28, "bold"), text_color="#D8000C").pack(side="left")
            self.dash_action_card.configure(
                fg_color="#FFF5F5", border_color="#D8000C")

            if metrics['pending_issues'] > 0:
                ctk.CTkLabel(self.dash_action_top, text=f"⚠ {metrics['pending_issues']} Tool(s)", fg_color="#D8000C", text_color="white", font=(
                    "Inter", 10, "bold"), corner_radius=6, padx=8, pady=3).pack(side="left", padx=(10, 0), pady=(5, 0))

        is_admin = self.user_info.get("role", "Staff") == "Admin"
        if hasattr(self, "dash_action_card") and is_admin:
            self._bind_widget_tree(self.dash_action_top,
                                   lambda *_: self.show_frame("Maintenance"))

    def _render_overdue_badges(self, metrics):
        if not hasattr(self, "dash_overdue_top"):
            return
        for w in self.dash_overdue_top.winfo_children():
            w.destroy()

        if metrics["overdue_projects"] == 0:
            ctk.CTkLabel(self.dash_overdue_top, text="0", font=(
                "Inter", 28, "bold"), text_color="black").pack(side="left")
            ctk.CTkLabel(self.dash_overdue_top, text="✓ On Track", fg_color="#2ECC71", text_color="white", font=(
                "Inter", 11, "bold"), corner_radius=6, padx=10, pady=3).pack(side="left", padx=(10, 0), pady=(5, 0))
            self.dash_overdue_card.configure(
                fg_color="#F9FAFB", border_color="#E0E0E0")
        else:
            ctk.CTkLabel(self.dash_overdue_top, text=str(metrics['overdue_projects']), font=(
                "Inter", 28, "bold"), text_color="#D8000C").pack(side="left")
            self.dash_overdue_card.configure(
                fg_color="#FFF5F5", border_color="#D8000C")

            ctk.CTkLabel(self.dash_overdue_top, text=f"⚠ {metrics['overdue_projects']} Overdue", fg_color="#D8000C", text_color="white", font=(
                "Inter", 10, "bold"), corner_radius=6, padx=8, pady=3).pack(side="left", padx=(10, 0), pady=(5, 0))

        is_admin = self.user_info.get("role", "Staff") == "Admin"
        if hasattr(self, "dash_overdue_card") and is_admin:
            self._bind_widget_tree(
                self.dash_overdue_top, lambda *_: self.show_frame("Project Management"))

    def _render_activity_feed(self, activities):
        for w in self.dash_activity_frame.winfo_children():
            w.destroy()

        headers = ["Date & Time", "Action Type", "Module / Item", "User"]
        weights = [2, 2, 4, 2]

        self._make_header(self.dash_activity_frame, headers,
                          weights, pad_left=20, pad_right=20)

        if not activities:
            activities = [("-", "No recent activity recorded.", "-", "-")]

        for i, (ts, action, item, actor) in enumerate(activities):
            bg = "#F9FAFB" if i % 2 == 0 else "white"
            row_frame = self._make_row(self.dash_activity_frame, [
                                       ts, action, item, actor], weights, bg)

            font_weight = "normal"
            color = "#1A1A1A"
            if action == "Project Created":
                color = "#2980B9"
                font_weight = "bold"
            elif action == "Issued":
                color = "#27AE60"
                font_weight = "bold"
            elif action == "Retrieved":
                color = "#2ECC71"
                font_weight = "bold"

            ctk.CTkLabel(row_frame, text=ts, font=("Inter", 11), text_color="#1A1A1A",
                         anchor="center").grid(row=0, column=0, padx=10, pady=5, sticky="ew")
            ctk.CTkLabel(row_frame, text=action, font=("Inter", 11, font_weight), text_color=color,
                         anchor="center").grid(row=0, column=1, padx=10, pady=5, sticky="ew")
            ctk.CTkLabel(row_frame, text=item, font=("Inter", 11), text_color="#1A1A1A",
                         anchor="center").grid(row=0, column=2, padx=10, pady=5, sticky="ew")
            ctk.CTkLabel(row_frame, text=actor, font=("Inter", 11), text_color="#1A1A1A",
                         anchor="center").grid(row=0, column=3, padx=10, pady=5, sticky="ew")

    def _update_sidebar_badges(self, metrics):
        is_admin = self.user_info.get("role", "Staff") == "Admin"
        if not is_admin:
            return

        if "Maintenance" in self.nav_badges:
            issues = metrics.get("action_items", 0)
            if issues > 0:
                self.nav_badges["Maintenance"].configure(
                    fg_color="#F1C40F", text="")
            else:
                self.nav_badges["Maintenance"].configure(
                    fg_color="transparent", text="")

        if "Project Management" in self.nav_badges:
            pending = metrics.get("pending_projects", 0)
            if pending > 0:
                self.nav_badges["Project Management"].configure(
                    fg_color="#DB8534", text="")
            else:
                self.nav_badges["Project Management"].configure(
                    fg_color="transparent", text="")

        if "Role Management" in self.nav_badges:
            resets = metrics.get("pwd_resets", 0)
            if resets > 0:
                self.nav_badges["Role Management"].configure(
                    fg_color="#D8000C", text="")
            else:
                self.nav_badges["Role Management"].configure(
                    fg_color="transparent", text="")

    def _apply_dashboard_data(self, metrics, activities, chart_data, deployed_rows=None, my_issuances=None):
        """Apply fetched metrics to dashboard widgets — must run on main thread."""
        if not self.winfo_exists():
            return
        self._update_sidebar_badges(metrics)
        if not hasattr(self, 'dash_util_lbl') or not self.dash_util_lbl.winfo_exists():
            return

        self.dash_util_lbl.configure(text=f"{metrics['utilization_pct']}%")
        self.dash_wf_lbl.configure(
            text=f"{metrics['active_workforce']} / {metrics['total_employees']}")
        self.dash_inv_lbl.configure(text=str(metrics['total_physical']))

        # Low stock card
        ls = metrics.get("low_stock", 0)
        self.dash_lowstock_val.configure(
            text=str(ls), text_color="#D8000C" if ls > 0 else "black")
        if hasattr(self, "dash_lowstock_top"):
            card = self.dash_lowstock_top.master
            card.configure(fg_color="#FFF5F5" if ls > 0 else "#F9FAFB",
                           border_color="#D8000C" if ls > 0 else "#E0E0E0")

        is_admin = self.user_info.get("role", "Staff") == "Admin"
        if is_admin:
            self._render_action_badges(metrics)
            # Project status strip
            if hasattr(self, "dash_proj_active_lbl"):
                self.dash_proj_active_lbl.configure(
                    text=f"{metrics.get('proj_active', 0)} Active")
                self.dash_proj_pending_lbl.configure(
                    text=f"{metrics.get('proj_pending', 0)} Pending")
                ov = metrics.get('overdue_projects', 0)
                self.dash_proj_overdue_lbl.configure(
                    text=f"{ov} Overdue",
                    text_color="#D8000C" if ov > 0 else "#C0392B"
                )
                self.dash_proj_done_lbl.configure(
                    text=f"{metrics.get('proj_completed_month', 0)} Completed (this month)")
            # Trend chart
            if hasattr(self, "dash_ax"):
                self._draw_trend(self.dash_ax, chart_data)
                self.dash_canvas.draw()
            # Deployed table
            if hasattr(self, "dash_deployed_frame") and deployed_rows is not None:
                self._render_deployed_table(deployed_rows)
        else:
            # Staff: my issuances
            if hasattr(self, "dash_myissue_frame") and my_issuances is not None:
                self._render_my_issuances(my_issuances)

        self._render_activity_feed(activities)

    def _auto_refresh_dashboard(self):
        import threading

        def _fetch():
            m, a, c, dr, mi = self.get_live_metrics()
            self.after(0, lambda: self._on_refresh_done(m, a, c, dr, mi))
        threading.Thread(target=_fetch, daemon=True).start()

    def _on_refresh_done(self, metrics, activities, chart_data, deployed_rows=None, my_issuances=None):
        if not self.winfo_exists():
            return
        self._update_sidebar_badges(metrics)
        if self.current_page_name == "Dashboard" and hasattr(self, 'dash_util_lbl') and self.dash_util_lbl.winfo_exists():
            self._apply_dashboard_data(
                metrics, activities, chart_data, deployed_rows, my_issuances)
        self.dashboard_refresh_job = self.after(
            15000, self._auto_refresh_dashboard)

    def embed_chart(self, parent_frame, chart_data):
        fig, ax = plt.subplots(figsize=(4.5, 2.6), dpi=90)
        fig.patch.set_facecolor("#FFFFFF")
        ax.set_facecolor("#FFFFFF")

        categories = ["Good", "Repair", "Damaged", "Lost"]
        colors = ["#2ECC71", "#F1C40F", "#E67E22", "#95A5A6"]

        bars = ax.bar(categories, chart_data, color=colors, width=0.6)

        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_visible(False)
        ax.get_yaxis().set_ticks([])

        for bar in bars:
            yval = bar.get_height()
            offset = max(chart_data) * 0.05 + \
                0.1 if max(chart_data) > 0 else 0.1
            ax.text(bar.get_x() + bar.get_width() / 2, yval + offset,
                    int(yval), ha="center", va="bottom",
                    fontdict={"family": "sans-serif", "weight": "bold", "color": "#333333"})

        plt.tight_layout()
        canvas = FigureCanva
