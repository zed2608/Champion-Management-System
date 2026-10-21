import os
import threading
import time
import customtkinter as ctk
from views.ui_thread import UiMixin
import sys
from tkinter import messagebox
from datetime import datetime
from PIL import Image
from database import get_connection, log_action, end_session

# Data Visualization
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# Import Views
from views.projects import ProjectsView
from views.inventory import InventoryView
from views.profile import ProfileView
from services import dashboard_service, session_settings
from services.errors import friendly_message
from views.borrowing import IssuanceView
from views.tracking import TrackingView
from views.reports import ReportsView
from views.maintenance import MaintenanceView
from views.role_management import RoleManagementView
from views.help import HelpView
from ui import components as C
from ui import motion
from ui.toast import ToastHost
from ui import theme as T


_EMPTY_METRICS = {
    "total_employees": 0, "active_workforce": 0, "available_qty": 0, "borrowed_qty": 0, "total_physical": 0, "utilization_pct": 0,
    "pending_issues": 0, "overdue_projects": 0, "action_items": 0, "low_stock": 0, "proj_active": 0, "proj_pending": 0,
    "proj_completed_month": 0, "pwd_resets": 0, "pending_projects": 0,
}


class DashboardApp(UiMixin, ctk.CTkToplevel):
    def __init__(self, parent, user_info):
        super().__init__(master=parent)
        self._ui_init()

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
        self._warning_dialog = None

        self.toasts = ToastHost(self)
        self.show_frame("Dashboard")
        self._setup_inactivity()
        self.dashboard_refresh_job = self.after(
            15000, self._auto_refresh_dashboard)

        self._init_offline_banner()
        name = (self.user_info.get("full_name") or "").strip()
        if name:                                              # a short non-modal greeting after login
            self.after(700, lambda: self.show_toast(f"Welcome back, {name}", "info", 3000))
        from services.tool_cache import tool_cache   # [CONCURRENCY] O(1) scan lookups, kept fresh across terminals
        tool_cache.start()

        # Reset inactivity timer on any user interaction
        self.bind_all("<Motion>", self._on_activity, add="+")
        self.bind_all("<Key>", self._on_activity, add="+")
        self.bind_all("<Button>", self._on_activity, add="+")

    def build_sidebar(self):
        self.sidebar_frame = ctk.CTkFrame(
            self, width=250, corner_radius=0, fg_color=T.SIDEBAR)
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
                self.sidebar_frame, text="🟢", font=T.font(40))
            self.sidebar_logo.pack(pady=(30, 10))

        ctk.CTkLabel(self.sidebar_frame, text="Automated Management\nSystem",
                     font=T.font(14, "bold"), text_color=T.WHITE).pack(pady=(0, 30))

        is_admin = self.user_info.get("role", "Staff") == "Admin"

        nav_items = [
            "Dashboard",
            "Inventory",
            "Issuance & Retrieval",
            "Tracking & Accountability",
        ]

        nav_items.insert(1, "Project Management")            # Staff see it too, read-only (the screen hides every action)
        if is_admin:
            nav_items += ["Reports", "Maintenance", "Role Management"]

        nav_items.append("Help")

        self.nav_buttons = {}
        self.nav_badges = {}
        for item in nav_items:
            container = ctk.CTkFrame(
                self.sidebar_frame, fg_color="transparent")
            container.pack(fill="x", pady=2, padx=10)

            btn = C.button(
                container, kind="ghost", compact=True, text=item, anchor="w", text_color=T.WHITE, hover_color=T.SIDEBAR_ACTIVE, font=T.font(14, "bold"),
                
                
                command=lambda m=item: self.show_frame(m)
            )
            btn.pack(side="left", fill="x", expand=True)

            badge = ctk.CTkLabel(container, text="", width=8,
                                 height=8, corner_radius=4, fg_color="transparent")
            badge.pack(side="right", padx=(10, 10))

            self.nav_buttons[item] = btn
            self.nav_badges[item] = badge

        C.button(
            self.sidebar_frame, kind="ghost", compact=True, text="Exit", anchor="w", text_color=T.WHITE, hover_color=T.DANGER_DARK, font=T.font(14, "bold"),
            
            
            command=self.confirm_logout
        ).pack(side="bottom", fill="x", pady=20, padx=10)

    def build_topbar(self):
        self.topbar_frame = ctk.CTkFrame(
            self, height=60, corner_radius=0, fg_color=T.SURFACE)
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
                font=T.font(14, "bold"), text_color=T.SIDEBAR
            )
            self.header_logo.pack(side="left", padx=30)
        except FileNotFoundError:
            self.header_logo = ctk.CTkLabel(
                self.topbar_frame, text="Champion Fine Tooling",
                font=T.font(14, "bold"), text_color=T.SIDEBAR
            )
            self.header_logo.pack(side="left", padx=30)

        self.time_label = ctk.CTkLabel(
            self.topbar_frame, text="", font=T.font(12), text_color=T.TEXT_SECONDARY)
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
            font=T.font(14, "bold"), text_color=T.TEXT
        )
        self.user_name_label.pack(anchor="w")
        self.user_name_label.bind(
            "<Button-1>", lambda e: self.show_frame("Profile"))

        self.user_role_label = ctk.CTkLabel(
            self.user_text_frame, text=f"{self.user_info['role']}",
            font=T.font(12, "bold"), text_color=T.SUCCESS_TEXT
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
            parent, fg_color=T.PRIMARY, corner_radius=5, height=35)
        header_frame.pack(fill="x", padx=(pad_left, pad_right))
        header_frame.pack_propagate(False)

        min_sizes = self._get_column_min_sizes(weights)
        for col, (text, weight) in enumerate(zip(headers, weights)):
            header_frame.grid_columnconfigure(
                col, weight=weight, minsize=min_sizes[col])
            ctk.CTkLabel(header_frame, text=text, font=T.font(12, "bold"),
                         text_color=T.WHITE, anchor="center").grid(row=0, column=col, padx=10, pady=5, sticky="ew")
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

    # ---- [UNHAPPY-PATH] "Database offline - retrying" banner ---------------------------------------------------------
    def _init_offline_banner(self):
        """Non-blocking overlay (never shifts the layout, never a modal). Shown when the pool cannot reach MySQL and
        hidden again when a connection succeeds. While offline, a background ping retries every 5 s."""
        from db import db
        self._db = db
        self._offline_banner = ctk.CTkLabel(
            self, text="⚠  Database offline – retrying…  Nothing is being saved.", font=T.font(12, "bold"),
            fg_color=T.DANGER, text_color=T.WHITE, corner_radius=8, height=34)
        self._offline_retry_job = None

        def on_status(online):               # called from whichever thread noticed: hop to the Tk thread
            try:
                self.post_ui(lambda: self._apply_db_status(online))
            except Exception:
                pass                          # window is closing
        self._db_status_cb = on_status
        db.add_status_listener(on_status)
        if db.online is False:
            self._apply_db_status(False)

    def _apply_db_status(self, online):
        if not self.winfo_exists():
            return
        if online:
            self._offline_banner.place_forget()
            if self._offline_retry_job:
                self.after_cancel(self._offline_retry_job)
                self._offline_retry_job = None
        else:
            self._offline_banner.place(relx=0.5, y=64, anchor="n")
            self._offline_banner.lift()
            if not self._offline_retry_job:
                self._offline_retry_job = self.after(5000, self._retry_db)

    def _retry_db(self):
        self._offline_retry_job = None
        if not self.winfo_exists() or self._db.online is not False:
            return
        import threading
        threading.Thread(target=self._db.ping, daemon=True).start()   # a success flips the status listener
        self._offline_retry_job = self.after(5000, self._retry_db)

    def destroy(self):
        try:
            self._cancel_timers()
            self._close_figures()
        except Exception:
            pass
        try:
            self._db.remove_status_listener(self._db_status_cb)
            from services.tool_cache import tool_cache
            tool_cache.stop(join=False)
        except Exception:
            pass
        super().destroy()

    def _track_fig(self, fig):
        self._figs = getattr(self, "_figs", [])
        self._figs.append(fig)
        return fig

    def _close_figures(self):
        for fig in getattr(self, "_figs", []):
            try:
                plt.close(fig)
            except Exception:
                pass
        self._figs = []
        for name in ("dash_fig", "dash_ax", "dash_canvas"):
            if hasattr(self, name):
                delattr(self, name)

    def _cancel_timers(self):
        for name in ("_clock_job", "dashboard_refresh_job", "_idle_job", "_warning_job"):
            job = getattr(self, name, None)
            if job:
                try:
                    self.after_cancel(job)
                except Exception:
                    pass
                setattr(self, name, None)

    def confirm_logout(self):
        # [UNHAPPY-PATH] Ask FIRST. The old code cancelled the clock, the dashboard refresh and the inactivity timer before asking, so
        # answering "No" left the session with no timeout and a frozen dashboard.
        if not messagebox.askyesno("Confirm Logout", "Are you sure you want to log out of your account?"):
            self._on_activity()                                  # the dialog was activity too
            return
        self._cancel_timers()
        log_action(self.user_info.get("user_id"), "Logout", "Authentication",
                   f"User {self.user_info.get('full_name')} logged out.")
        self._return_to_login()

    def _return_to_login(self):
        end_session()
        self.destroy()
        self.master.deiconify()
        self.master.pass_entry.delete(0, "end")

        self.master.pass_entry.configure(show="•")
        self.master.eye_btn.configure(text="👁")
        self.master.show_pwd = False

        self.master.error_banner.configure(text="", fg_color="transparent")
        self.master.failed_attempts = 0

    # ── Inactivity Auto-Logout ───────────────────────────────────────────────
    # 15 minutes idle (configurable, see services/session_settings.py), then a 30-second warning. The clock is a wall-time deadline
    # checked once a second, so a sleeping laptop or a busy UI cannot stretch the session, and mouse movement costs one assignment.
    def _setup_inactivity(self):
        self._idle_limit_s = session_settings.idle_minutes() * 60
        self._warn_s = session_settings.warning_seconds()
        self._last_activity = time.monotonic()
        self._idle_job = None
        self._warning_job = None
        self._warning_deadline = None
        self._idle_job = self.after(1000, self._idle_check)

    def _on_activity(self, event=None):
        if self._warning_dialog is not None:                     # once the warning is up only "Stay Logged In" counts
            return
        self._last_activity = time.monotonic()

    def _idle_check(self):
        self._idle_job = None
        if not self.winfo_exists():
            return
        if self._warning_dialog is None and time.monotonic() - self._last_activity >= self._idle_limit_s:
            self._show_inactivity_warning()
        if self._idle_job is None and self._warning_dialog is None:
            self._idle_job = self.after(1000, self._idle_check)

    def _show_inactivity_warning(self):
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
        self._warning_deadline = time.monotonic() + self._warn_s
        dialog.protocol("WM_DELETE_WINDOW", self._stay_logged_in)

        ctk.CTkLabel(dialog, text="⚠ Session Inactivity",
                     font=T.font(16, "bold"), text_color=T.DANGER_TEXT).pack(pady=(20, 4))
        minutes = self._idle_limit_s // 60
        ctk.CTkLabel(dialog, text=f"You have been inactive for {minutes} minute{'s' if minutes != 1 else ''}.",
                     font=T.font(12), text_color=T.TEXT_SECONDARY).pack()

        self._countdown_label = ctk.CTkLabel(dialog, text=f"Logging out in {self._warn_s} seconds…",
                                             font=T.font(12), text_color=T.TEXT)
        self._countdown_label.pack(pady=(10, 16))

        C.button(dialog, kind="primary", text="Stay Logged In", width=160,
                      
                      
                      command=self._stay_logged_in).pack()
        self._warning_check()

    def _warning_check(self):
        self._warning_job = None
        if not self.winfo_exists() or self._warning_dialog is None:
            return
        remaining = self._warning_deadline - time.monotonic()
        if remaining <= 0:
            try:
                self._warning_dialog.destroy()
            except Exception:
                pass
            self._warning_dialog = None
            self._force_logout()
            return
        try:
            self._countdown_label.configure(text=f"Logging out in {int(remaining) + 1} seconds…")
        except Exception:
            pass
        self._warning_job = self.after(500, self._warning_check)

    def _stay_logged_in(self):
        dialog, self._warning_dialog = self._warning_dialog, None
        if self._warning_job:
            try:
                self.after_cancel(self._warning_job)
            except Exception:
                pass
            self._warning_job = None
        if dialog is not None:
            try:
                dialog.destroy()
            except Exception:
                pass
        self._last_activity = time.monotonic()
        if self._idle_job is None:
            self._idle_job = self.after(1000, self._idle_check)

    def _force_logout(self):
        self._cancel_timers()
        log_action(self.user_info.get("user_id"), "Auto-Logout", "Authentication",
                   f"Session expired due to inactivity — {self.user_info.get('full_name')}.")
        self._return_to_login()

    def _show_loading_overlay(self):
        """Show a spinner overlay on the main container while switching frames."""
        overlay = ctk.CTkFrame(self.main_container,
                               fg_color=T.SURFACE, corner_radius=10)
        overlay.place(relx=0.5, rely=0.5, anchor="center",
                      relwidth=1.0, relheight=1.0)
        spinner_lbl = ctk.CTkLabel(overlay, text="⟳", font=T.font(40), text_color=T.PRIMARY)
        spinner_lbl.place(relx=0.5, rely=0.5, anchor="center")
        msg_lbl = ctk.CTkLabel(overlay, text="Loading...",
                               font=T.font(14), text_color=T.TEXT_MUTED)
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
        restricted_modules = ["Reports", "Maintenance", "Role Management"]   # [RBAC] UI hint only: services re-check the role in MySQL

        if not is_admin and page_name in restricted_modules:
            messagebox.showerror(
                "Access Denied", "You do not have permission to access this module.")
            return

        self.current_page_name = page_name

        for name, btn in self.nav_buttons.items():
            if name == page_name:
                btn.configure(fg_color=T.SIDEBAR_ACTIVE, text_color=T.ACCENT)
            else:
                btn.configure(fg_color="transparent", text_color=T.WHITE)

        if self.current_frame is not None:
            self._close_figures()                            # pyplot keeps every figure alive until it is closed
            self.current_frame.destroy()

        # Show spinner overlay while the new frame is built
        overlay = self._show_loading_overlay()

        uid = self.user_info.get("user_id")
        if uid and page_name != "Dashboard":
            log_action(uid, "Viewed", page_name, f"Navigated to {page_name}")

        # [UNHAPPY-PATH] A page that fails to build must never leave the spinner overlay up forever.
        try:
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
                    self.main_container, navigate_to_tool=self.navigate_to_tool, user_info=self.user_info)
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
                             font=T.font(20), text_color=T.TEXT_MUTED).pack(expand=True)
        except Exception as e:
            import traceback; traceback.print_exc()
            self.current_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
            ctk.CTkLabel(self.current_frame, text=f"Could not load {page_name}. Please try again or contact an administrator.",
                         font=T.font(14), text_color=T.DANGER_TEXT).pack(expand=True)
        finally:
            # Remove overlay whether or not the page built
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
        """[RBAC][QUANTITIES] All numbers come from dashboard_service: sums of quantity (not row counts) and a Staff-safe feed."""
        try:
            return dashboard_service.live_metrics(self.user_info)
        except Exception as e:
            print(f"Dashboard Sync Error: {friendly_message(e)}")
            return dict(_EMPTY_METRICS), [], [], [], []

    # ── [PANEL-AWE] Admin insight cards ──────────────────────────────────────────────────────────────────────────────
    def _build_insights(self, parent):
        """Four cards for the Admin only: last backup, audit chain, top wear forecasts, top recommendations. They start as "Loading…" and are
        filled from a worker thread (services.dashboard_service.admin_insights), so building the dashboard never waits for them."""
        panel = ctk.CTkFrame(parent, fg_color=T.SURFACE, corner_radius=10)
        panel.pack(fill="x", pady=(0, 10))
        head = ctk.CTkFrame(panel, fg_color="transparent")
        head.pack(fill="x", padx=15, pady=(10, 0))
        ctk.CTkLabel(head, text="ADMIN INSIGHTS", font=T.font(14, "bold"), text_color=T.PRIMARY).pack(side="left")
        C.button(head, compact=True, kind="secondary", text="↻ Refresh", width=80, 
                      command=self._load_insights).pack(side="right")
        grid = ctk.CTkFrame(panel, fg_color="transparent")
        grid.pack(fill="x", padx=10, pady=(4, 10))
        grid.grid_columnconfigure((0, 1), weight=1, uniform="ins")
        self.ins_labels = {}
        for key, title, row, col, go, span in (("backup", "Last backup", 0, 0, "Maintenance", 1), ("audit", "Audit chain", 0, 1, "Tracking", 1),
                                               ("wear", "Wear forecast - top 5", 1, 0, "Maintenance", 1),
                                               ("recommendations", "Recommendations - top 5", 1, 1, "Reports", 1),
                                               ("savings", "Lost-tool value vs the P10,000 monthly baseline", 2, 0, "Reports", 2)):
            card = ctk.CTkFrame(grid, fg_color=T.SURFACE_ALT, corner_radius=8)
            card.grid(row=row, column=col, columnspan=span, padx=5, pady=5, sticky="nsew")
            t = ctk.CTkFrame(card, fg_color="transparent")
            t.pack(fill="x", padx=12, pady=(8, 2))
            ctk.CTkLabel(t, text=title, font=T.font(12, "bold"), text_color=T.TEXT).pack(side="left")
            C.button(t, compact=True, kind="ghost", text="Open", width=50, text_color=T.INFO_TEXT, hover_color=T.INFO_BG, 
                          command=lambda g=go: self.show_frame(g)).pack(side="right")
            lbl = ctk.CTkLabel(card, text="Loading...", font=T.font(12), text_color=T.TEXT_MUTED, justify="left", anchor="w", wraplength=520)
            lbl.pack(fill="x", padx=12, pady=(0, 10))
            self.ins_labels[key] = lbl
        self._load_insights()

    def _load_insights(self):
        for lbl in getattr(self, "ins_labels", {}).values():
            lbl.configure(text="Loading...", text_color=T.TEXT_MUTED)

        def work():
            try:
                result = dashboard_service.admin_insights(self.user_info)
            except Exception as e:
                msg = friendly_message(e)
                self.post_ui(lambda: self._apply_insights({k: {"error": msg} for k in ("backup", "audit", "wear", "recommendations", "savings")}))
                return
            self.post_ui(lambda: self._apply_insights(result))
        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def insight_texts(result):
        """{key: (text, colour)} for the four cards (pure: the unit tests read this)."""
        green, red, grey, dark=T.PRIMARY, T.DANGER, "gray", T.TEXT
        out = {}
        part = result.get("backup", {})
        if not part:
            pass
        elif "error" in part:
            out["backup"] = (part["error"], red)
        else:
            b = part["data"]
            if b["last"] is None:
                out["backup"] = ("No backup has been recorded. Make one in Maintenance > Backup & Restore.", red)
            else:
                text = f"{b['age_days']:g} days ago ({b['last']:%b %d, %Y %I:%M %p})"
                out["backup"] = ((f"WARNING: last backup was {text}. Backups older than {b['warn_after_days']} days are not safe enough." if b["warn"]
                                  else f"OK: {text}"), red if b["warn"] else green)
        part = result.get("audit", {})
        if not part:
            pass
        elif "error" in part:
            out["audit"] = (part["error"], red)
        else:
            a = part["data"]
            head = (a["head_hash"] or "")[:12]
            if not a["verified"]:
                out["audit"] = (f"{a['live'] + a['archived']} entries, head {head}... (too large to check on load - use Verify in Tracking).", grey)
            elif a["intact"]:
                out["audit"] = (f"INTACT: {a['checked']} entries checked, head {head}...", green)
            else:
                out["audit"] = (f"BROKEN at entry #{a['first_broken_log_id']}: {a['reason']}", red)
        part = result.get("wear", {})
        if not part:
            pass
        elif "error" in part:
            out["wear"] = (part["error"], red)
        elif not part["data"]:
            out["wear"] = ("No equipment to forecast yet.", grey)
        else:
            from services import wear_forecast
            lines = []
            for r in part["data"]:
                due = "not used lately" if r["days_to_due"] is None else ("overdue" if r["days_to_due"] <= 0 else f"due in {r['days_to_due']:g} days")
                flag = f"  [{', '.join(r['flags'])}]" if r["flags"] else ""
                lines.append(f"{r['name']}: {r['pct_used']:g}% of {r['interval']:g} h used, {due}{flag}")
            out["wear"] = ("\n".join(lines), dark)
        part = result.get("recommendations", {})
        if not part:
            pass
        elif "error" in part:
            out["recommendations"] = (part["error"], red)
        elif not part["data"]:
            out["recommendations"] = ("Nothing unusual right now.", grey)
        else:
            out["recommendations"] = ("\n".join(f"{i}. {r['text']}" for i, r in enumerate(part["data"], start=1)), dark)
        part = result.get("savings", {})
        if not part:
            pass
        elif "error" in part:
            out["savings"] = (part["error"], red)
        else:
            from services import savings
            k = part["data"]
            out["savings"] = (savings.describe(k), green if k["this_month"]["saved"] >= 0 else red)
        return out

    def _apply_insights(self, result):
        if not self.winfo_exists():
            return
        for key, (text, color) in self.insight_texts(result).items():
            lbl = getattr(self, "ins_labels", {}).get(key)
            if lbl is not None and lbl.winfo_exists():
                lbl.configure(text=text, text_color=color)

    def create_home_dashboard(self):
        is_admin = self.user_info.get("role", "Staff") == "Admin"

        frame = ctk.CTkScrollableFrame(
            self.main_container, fg_color="transparent", orientation="vertical")
        inner_frame = ctk.CTkFrame(frame, fg_color="transparent")
        inner_frame.pack(fill="both", expand=True)

        ctk.CTkLabel(inner_frame, text="EXECUTIVE DASHBOARD", font=T.font(20, "bold"),
                     text_color=T.TEXT).pack(anchor="w", pady=(0, 5))
        ctk.CTkLabel(inner_frame, text="High-level overview of system health and asset utilization. Auto-updates live.",
                     font=T.font(14), text_color=T.TEXT_MUTED).pack(anchor="w", pady=(0, 20))

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
        c1 = ctk.CTkFrame(cards_frame, fg_color=T.PRIMARY,
                          corner_radius=10, height=130)
        c1.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        c1.pack_propagate(False)
        self.dash_util_lbl = ctk.CTkLabel(c1, text="0%", font=T.font(28, "bold"), text_color=T.WHITE)
        self.dash_util_lbl.pack(anchor="w", padx=20, pady=(20, 0))
        ctk.CTkLabel(c1, text="Asset Utilization", font=T.font(14, "bold"), text_color=T.WHITE).pack(anchor="w", padx=20, pady=(5, 0))
        ctk.CTkLabel(c1, text="Deployed vs Warehouse", font=T.font(12), text_color=T.WHITE).pack(anchor="w", padx=20)

        # Card 2 – Active Workforce
        c2 = ctk.CTkFrame(cards_frame, fg_color=T.INFO_HOVER,
                          corner_radius=10, height=130)
        c2.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        c2.pack_propagate(False)
        self.dash_wf_lbl = ctk.CTkLabel(
            c2, text="0 / 0", font=T.font(28, "bold"), text_color=T.WHITE)
        self.dash_wf_lbl.pack(anchor="w", padx=20, pady=(20, 0))
        ctk.CTkLabel(c2, text="Active Workforce", font=T.font(14, "bold"), text_color=T.WHITE).pack(anchor="w", padx=20, pady=(5, 0))
        ctk.CTkLabel(c2, text="Active last 30 days", font=T.font(12), text_color=T.WHITE).pack(anchor="w", padx=20)

        # Card 3 – Total Inventory
        c3 = ctk.CTkFrame(cards_frame, fg_color=T.ACCENT,
                          corner_radius=10, height=130)
        c3.grid(row=0, column=2, padx=5, pady=5, sticky="ew")
        c3.pack_propagate(False)
        self.dash_inv_lbl = ctk.CTkLabel(c3, text="0", font=T.font(28, "bold"), text_color=T.TEXT)
        self.dash_inv_lbl.pack(anchor="w", padx=20, pady=(20, 0))
        ctk.CTkLabel(c3, text="Total Inventory", font=T.font(14, "bold"), text_color=T.TEXT).pack(anchor="w", padx=20, pady=(5, 0))
        ctk.CTkLabel(c3, text="Total physical items", font=T.font(12), text_color=T.TEXT).pack(anchor="w", padx=20)

        # Card 4 – Low Stock (admin + staff)
        c_ls = ctk.CTkFrame(cards_frame, fg_color=T.SURFACE_ALT, corner_radius=10,
                            height=130, border_width=1, border_color=T.BORDER)
        c_ls.grid(row=0, column=3, padx=5, pady=5, sticky="ew")
        c_ls.pack_propagate(False)
        self.dash_lowstock_top = ctk.CTkFrame(c_ls, fg_color="transparent")
        self.dash_lowstock_top.pack(fill="x", padx=20, pady=(15, 0))
        self.dash_lowstock_val = ctk.CTkLabel(self.dash_lowstock_top, text="0", font=T.font(28, "bold"), text_color=T.TEXT)
        self.dash_lowstock_val.pack(side="left")
        ctk.CTkLabel(c_ls, text="Low Stock Items", font=T.font(14, "bold"), text_color=T.TEXT).pack(anchor="w", padx=20, pady=(5, 0))
        ctk.CTkLabel(c_ls, text="Near reorder level →", font=T.font(12), text_color=T.TEXT_MUTED).pack(anchor="w", padx=20)
        self._bind_widget_tree(
            c_ls, lambda *_: self.show_frame("Inventory", highlight_low_stock=True), hover=True)

        if is_admin:
            # Card 5 – Action Items
            self.dash_action_card = ctk.CTkFrame(
                cards_frame, fg_color=T.SURFACE_ALT, corner_radius=10, height=130, border_width=1, border_color=T.BORDER)
            self.dash_action_card.grid(
                row=0, column=4, padx=5, pady=5, sticky="ew")
            self.dash_action_card.pack_propagate(False)
            self.dash_action_top = ctk.CTkFrame(
                self.dash_action_card, fg_color="transparent")
            self.dash_action_top.pack(fill="x", padx=20, pady=(15, 0))
            self._render_action_badges(metrics)
            ctk.CTkLabel(self.dash_action_card, text="Action Items", font=T.font(14, "bold"), text_color=T.TEXT).pack(anchor="w", padx=20, pady=(5, 0))
            ctk.CTkLabel(self.dash_action_card, text="Maintenance →", font=T.font(12), text_color=T.TEXT_MUTED).pack(anchor="w", padx=20)
            self._bind_widget_tree(self.dash_action_card,
                                   lambda *_: self.show_frame("Maintenance"), hover=True)

        # ── Row 2: Project Status Strip (admin only) ─────────────────────────
        if is_admin:
            strip = ctk.CTkFrame(
                inner_frame, fg_color=T.SURFACE, corner_radius=10, height=60)
            strip.pack(fill="x", pady=(0, 10))
            strip.pack_propagate(False)
            strip_inner = ctk.CTkFrame(strip, fg_color="transparent")
            strip_inner.pack(expand=True, fill="both", padx=20)
            ctk.CTkLabel(strip_inner, text="Projects Status:", font=T.font(12, "bold"), text_color=T.TEXT_SECONDARY).pack(side="left", padx=(0, 20))
            # Active
            pf_active = ctk.CTkFrame(
                strip_inner, fg_color=T.SUCCESS_BG, corner_radius=8)
            pf_active.pack(side="left", padx=5, pady=10, ipadx=12, ipady=4)
            self.dash_proj_active_lbl = ctk.CTkLabel(
                pf_active, text="0 Active", font=T.font(12, "bold"), text_color=T.PRIMARY)
            self.dash_proj_active_lbl.pack()
            # Pending
            pf_pending = ctk.CTkFrame(
                strip_inner, fg_color=T.WARNING_BG, corner_radius=8)
            pf_pending.pack(side="left", padx=5, pady=10, ipadx=12, ipady=4)
            self.dash_proj_pending_lbl = ctk.CTkLabel(
                pf_pending, text="0 Pending", font=T.font(12, "bold"), text_color=T.WARNING_TEXT)
            self.dash_proj_pending_lbl.pack()
            # Overdue (merged here from removed card)
            pf_overdue = ctk.CTkFrame(
                strip_inner, fg_color=T.DANGER_BG, corner_radius=8)
            pf_overdue.pack(side="left", padx=5, pady=10, ipadx=12, ipady=4)
            self.dash_proj_overdue_lbl = ctk.CTkLabel(
                pf_overdue, text="0 Overdue", font=T.font(12, "bold"), text_color=T.DANGER_TEXT)
            self.dash_proj_overdue_lbl.pack()
            # Completed this month
            pf_done = ctk.CTkFrame(
                strip_inner, fg_color=T.INFO_BG, corner_radius=8)
            pf_done.pack(side="left", padx=5, pady=10, ipadx=12, ipady=4)
            self.dash_proj_done_lbl = ctk.CTkLabel(pf_done, text="0 Completed (this month)", font=T.font(12, "bold"), text_color=T.INFO_DARK)
            self.dash_proj_done_lbl.pack()
            self._bind_widget_tree(
                strip, lambda *_: self.show_frame("Project Management"))

        if is_admin:
            self._build_insights(inner_frame)

        # ── Row 3: Bottom 2-column layout ─────────────────────────────────────
        bottom_frame = ctk.CTkFrame(inner_frame, fg_color="transparent")
        bottom_frame.pack(fill="both", expand=True)
        bottom_frame.grid_columnconfigure(0, weight=2)
        bottom_frame.grid_columnconfigure(1, weight=1)
        bottom_frame.grid_rowconfigure(0, weight=1)

        # Left column: activity feed
        activity_card = ctk.CTkFrame(
            bottom_frame, fg_color=T.SURFACE, corner_radius=10)
        activity_card.grid(row=0, column=0, sticky="nsew",
                           padx=(0, 10), pady=10)
        ctk.CTkLabel(activity_card, text="Recent Operations (Deployments & Projects)",
                     font=T.font(14, "bold"), text_color=T.TEXT).pack(anchor="w", padx=20, pady=(20, 10))
        self.dash_activity_frame = ctk.CTkFrame(
            activity_card, fg_color="transparent")
        self.dash_activity_frame.pack(
            fill="both", expand=True, padx=10, pady=(0, 10))
        self._render_activity_feed(activities)

        # Right column: trend chart (admin) OR my issuances (staff)
        right_card = ctk.CTkFrame(
            bottom_frame, fg_color=T.SURFACE, corner_radius=10)
        right_card.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=10)

        if is_admin:
            ctk.CTkLabel(right_card, text="7-Day Deployment Trend",
                         font=T.font(14, "bold"), text_color=T.TEXT).pack(anchor="w", padx=20, pady=(20, 5))
            self.dash_chart_frame = ctk.CTkFrame(
                right_card, fg_color="transparent")
            self.dash_chart_frame.pack(fill="both", expand=True)
            self.dash_fig, self.dash_ax, self.dash_canvas = self._embed_trend_chart(
                self.dash_chart_frame, chart_data)

            # Currently Deployed mini-table below chart
            ctk.CTkLabel(right_card, text="Currently Deployed by Project",
                         font=T.font(14, "bold"), text_color=T.TEXT).pack(anchor="w", padx=20, pady=(10, 4))
            self.dash_deployed_frame = ctk.CTkFrame(
                right_card, fg_color="transparent")
            self.dash_deployed_frame.pack(fill="x", padx=10, pady=(0, 10))
            self._render_deployed_table(deployed_rows)
        else:
            # Staff: My Active Issuances
            ctk.CTkLabel(right_card, text="My Active Issuances",
                         font=T.font(14, "bold"), text_color=T.TEXT).pack(anchor="w", padx=20, pady=(20, 5))
            self.dash_myissue_frame = ctk.CTkFrame(
                right_card, fg_color="transparent")
            self.dash_myissue_frame.pack(
                fill="both", expand=True, padx=10, pady=(0, 10))
            self._render_my_issuances(my_issuances)

        # Load real data in background
        import threading

        def _initial_load():
            m, a, c, dr, mi = self.get_live_metrics()
            self.post_ui(lambda: self._apply_dashboard_data(m, a, c, dr, mi))
        threading.Thread(target=_initial_load, daemon=True).start()

        return frame

    def _embed_trend_chart(self, parent, chart_data):
        fig, ax = plt.subplots(figsize=(5.2, 2.6), dpi=100)  # Slightly wider
        self._track_fig(fig)
        fig.patch.set_facecolor(T.WHITE)
        ax.set_facecolor(T.WHITE)

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
                    transform=ax.transAxes, color=T.TEXT_MUTED, fontsize=11)
            ax.axis("off")
            return

        labels = [r[0] for r in chart_data]
        issued = [r[1] for r in chart_data]
        retrieved = [r[2] for r in chart_data]

        x = range(len(labels))
        ax.plot(x, issued, marker="o", color=T.SUCCESS_DARK, linewidth=2.5, label="Issued")
        ax.plot(x, retrieved, marker="o", color=T.INFO_HOVER, linewidth=2.5, linestyle="--", label="Retrieved")

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
                         font=T.font(12), text_color=T.TEXT_MUTED).pack(pady=8)
            return
        hdr = ctk.CTkFrame(self.dash_deployed_frame,
                           fg_color=T.PRIMARY, corner_radius=5, height=28)
        hdr.pack(fill="x", padx=0, pady=(0, 1))
        hdr.pack_propagate(False)
        hdr.grid_columnconfigure(0, weight=3)
        hdr.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(hdr, text="Project", font=T.font(12, "bold"),
                     text_color=T.WHITE, anchor="w").grid(row=0, column=0, padx=8, sticky="ew")
        ctk.CTkLabel(hdr, text="Tools Out", font=T.font(12, "bold"), text_color=T.WHITE,
                     anchor="center").grid(row=0, column=1, padx=8, sticky="ew")
        for i, (proj, cnt) in enumerate(deployed_rows):
            bg=T.SURFACE_ALT if i % 2 == 0 else "white"
            row = ctk.CTkFrame(self.dash_deployed_frame,
                               fg_color=bg, height=28)
            row.pack(fill="x", pady=0)
            row.pack_propagate(False)
            row.grid_columnconfigure(0, weight=3)
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(row, text=proj, font=T.font(12), text_color=T.TEXT, anchor="w").grid(
                row=0, column=0, padx=8, sticky="ew")
            ctk.CTkLabel(row, text=str(cnt), font=T.font(12, "bold"), text_color=T.PRIMARY,
                         anchor="center").grid(row=0, column=1, padx=8, sticky="ew")

    def _render_my_issuances(self, my_issuances):
        for w in self.dash_myissue_frame.winfo_children():
            w.destroy()
        if not my_issuances:
            ctk.CTkLabel(self.dash_myissue_frame, text="✓ No tools currently issued to you.",
                         font=T.font(12), text_color=T.SUCCESS_TEXT).pack(pady=20)
            return
        hdr = ctk.CTkFrame(self.dash_myissue_frame,
                           fg_color=T.PRIMARY, corner_radius=5, height=28)
        hdr.pack(fill="x", pady=(0, 1))
        hdr.pack_propagate(False)
        hdr.grid_columnconfigure(0, weight=3)
        hdr.grid_columnconfigure(1, weight=2)
        hdr.grid_columnconfigure(2, weight=2)
        ctk.CTkLabel(hdr, text="Tool", font=T.font(12, "bold"), text_color=T.WHITE,
                     anchor="w").grid(row=0, column=0, padx=8, sticky="ew")
        ctk.CTkLabel(hdr, text="Issued", font=T.font(12, "bold"), text_color=T.WHITE,
                     anchor="center").grid(row=0, column=1, padx=4, sticky="ew")
        ctk.CTkLabel(hdr, text="Project", font=T.font(12, "bold"), text_color=T.WHITE,
                     anchor="center").grid(row=0, column=2, padx=8, sticky="ew")
        for i, (tool, date, proj) in enumerate(my_issuances):
            bg=T.SURFACE_ALT if i % 2 == 0 else "white"
            row = ctk.CTkFrame(self.dash_myissue_frame, fg_color=bg, height=28)
            row.pack(fill="x", pady=0)
            row.pack_propagate(False)
            row.grid_columnconfigure(0, weight=3)
            row.grid_columnconfigure(1, weight=2)
            row.grid_columnconfigure(2, weight=2)
            ctk.CTkLabel(row, text=tool, font=T.font(12), text_color=T.TEXT, anchor="w").grid(
                row=0, column=0, padx=8, sticky="ew")
            ctk.CTkLabel(row, text=date, font=T.font(12), text_color=T.TEXT_SECONDARY,
                         anchor="center").grid(row=0, column=1, padx=4, sticky="ew")
            ctk.CTkLabel(row, text=proj, font=T.font(12), text_color=T.INFO_TEXT,
                         anchor="center").grid(row=0, column=2, padx=8, sticky="ew")

    def show_toast(self, message, kind="success", ms=3500):
        """A short non-modal notice at the top right (screens call this after something already happened)."""
        text = str(message).lstrip("✓✕ ").strip()
        return self.toasts.show(text, kind, ms)

    def _bind_widget_tree(self, widget, callback, hover=False):
        try:
            widget.configure(cursor="hand2")
            widget.bind("<Button-1>", callback)
        except Exception:
            pass
        for child in widget.winfo_children():
            self._bind_widget_tree(child, callback)
        if hover:                                            # a card the person can click: fade to a slightly tinted colour under the mouse
            base = motion._as_hex(widget.cget("fg_color"))
            if base:
                motion.hover_fade(widget, base, motion.mix(base, T.PRIMARY, 0.08), targets=list(widget.winfo_children()))

    def _render_action_badges(self, metrics):
        if not hasattr(self, "dash_action_top"):
            return
        for w in self.dash_action_top.winfo_children():
            w.destroy()

        if metrics["action_items"] == 0:
            ctk.CTkLabel(self.dash_action_top, text="0", font=T.font(28, "bold"), text_color=T.TEXT).pack(side="left")
            ctk.CTkLabel(self.dash_action_top, text="✓ All Clear", fg_color=T.SUCCESS, text_color=T.WHITE, font=T.font(12, "bold"), corner_radius=6, padx=10, pady=3).pack(side="left", padx=(15, 0), pady=(5, 0))
            self.dash_action_card.configure(
                fg_color=T.SURFACE_ALT, border_color=T.BORDER)
        else:
            ctk.CTkLabel(self.dash_action_top, text=str(metrics['action_items']), font=T.font(28, "bold"), text_color=T.DANGER_TEXT).pack(side="left")
            self.dash_action_card.configure(
                fg_color=T.DANGER_BG, border_color=T.DANGER)

            if metrics['pending_issues'] > 0:
                ctk.CTkLabel(self.dash_action_top, text=f"⚠ {metrics['pending_issues']} Tool(s)", fg_color=T.DANGER, text_color=T.WHITE, font=T.font(12, "bold"), corner_radius=6, padx=8, pady=3).pack(side="left", padx=(10, 0), pady=(5, 0))

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
            ctk.CTkLabel(self.dash_overdue_top, text="0", font=T.font(28, "bold"), text_color=T.TEXT).pack(side="left")
            ctk.CTkLabel(self.dash_overdue_top, text="✓ On Track", fg_color=T.SUCCESS, text_color=T.WHITE, font=T.font(12, "bold"), corner_radius=6, padx=10, pady=3).pack(side="left", padx=(10, 0), pady=(5, 0))
            self.dash_overdue_card.configure(
                fg_color=T.SURFACE_ALT, border_color=T.BORDER)
        else:
            ctk.CTkLabel(self.dash_overdue_top, text=str(metrics['overdue_projects']), font=T.font(28, "bold"), text_color=T.DANGER_TEXT).pack(side="left")
            self.dash_overdue_card.configure(
                fg_color=T.DANGER_BG, border_color=T.DANGER)

            ctk.CTkLabel(self.dash_overdue_top, text=f"⚠ {metrics['overdue_projects']} Overdue", fg_color=T.DANGER, text_color=T.WHITE, font=T.font(12, "bold"), corner_radius=6, padx=8, pady=3).pack(side="left", padx=(10, 0), pady=(5, 0))

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
            bg=T.SURFACE_ALT if i % 2 == 0 else "white"
            row_frame = self._make_row(self.dash_activity_frame, [
                                       ts, action, item, actor], weights, bg)

            font_weight = "normal"
            color=T.TEXT
            if action == "Project Created":
                color=T.INFO_HOVER
                font_weight = "bold"
            elif action == "Issued":
                color=T.SUCCESS_DARK
                font_weight = "bold"
            elif action == "Retrieved":
                color=T.SUCCESS_TEXT
                font_weight = "bold"

            ctk.CTkLabel(row_frame, text=ts, font=T.font(12), text_color=T.TEXT,
                         anchor="center").grid(row=0, column=0, padx=10, pady=5, sticky="ew")
            ctk.CTkLabel(row_frame, text=action, font=T.font(12, font_weight), text_color=color,
                         anchor="center").grid(row=0, column=1, padx=10, pady=5, sticky="ew")
            ctk.CTkLabel(row_frame, text=item, font=T.font(12), text_color=T.TEXT,
                         anchor="center").grid(row=0, column=2, padx=10, pady=5, sticky="ew")
            ctk.CTkLabel(row_frame, text=actor, font=T.font(12), text_color=T.TEXT,
                         anchor="center").grid(row=0, column=3, padx=10, pady=5, sticky="ew")

    def _update_sidebar_badges(self, metrics):
        is_admin = self.user_info.get("role", "Staff") == "Admin"
        if not is_admin:
            return

        if "Maintenance" in self.nav_badges:
            issues = metrics.get("action_items", 0)
            if issues > 0:
                self.nav_badges["Maintenance"].configure(
                    fg_color=T.ACCENT, text="")
            else:
                self.nav_badges["Maintenance"].configure(
                    fg_color="transparent", text="")

        if "Project Management" in self.nav_badges:
            pending = metrics.get("pending_projects", 0)
            if pending > 0:
                self.nav_badges["Project Management"].configure(
                    fg_color=T.WARNING, text="")
            else:
                self.nav_badges["Project Management"].configure(
                    fg_color="transparent", text="")

        if "Role Management" in self.nav_badges:
            resets = metrics.get("pwd_resets", 0)
            if resets > 0:
                self.nav_badges["Role Management"].configure(
                    fg_color=T.DANGER, text="")
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
            text=str(ls), text_color=T.DANGER_TEXT if ls > 0 else "black")
        if hasattr(self, "dash_lowstock_top"):
            card = self.dash_lowstock_top.master
            card.configure(fg_color=T.DANGER_BG if ls > 0 else T.SURFACE_ALT,
                           border_color=T.DANGER if ls > 0 else T.BORDER)

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
                    text_color=T.DANGER_TEXT if ov > 0 else T.DANGER_HOVER
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
            self.post_ui(lambda: self._on_refresh_done(m, a, c, dr, mi))
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
        self._track_fig(fig)
        fig.patch.set_facecolor(T.WHITE)
        ax.set_facecolor(T.WHITE)

        categories = ["Good", "Repair", "Damaged", "Lost"]
        colors = [T.SUCCESS_BRIGHT, T.ACCENT, T.WARNING, T.TEXT_MUTED]

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
                    fontdict={"family": "sans-serif", "weight": "bold", "color": T.TEXT})

        plt.tight_layout()
        canvas = FigureCanva
