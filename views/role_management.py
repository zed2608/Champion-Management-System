import customtkinter as ctk
from views.ui_thread import UiMixin
from tkinter import messagebox
from database import get_connection, generate_id_badge, log_action
import bcrypt
import secrets
import os
import tempfile
import qrcode
from PIL import Image, ImageDraw, ImageFont
import re
import difflib
from services.errors import friendly_message
from services import user_service
from ui import components as C
from ui import theme as T


class RoleManagementView(UiMixin, ctk.CTkFrame):
    def __init__(self, parent, user_info=None):
        super().__init__(parent, fg_color="transparent")
        self._ui_init()

        self.user_info = user_info or {}
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)

        self.build_ui()

    def build_ui(self):
        C.PageHeader(self, "Role Management", "Register staff and workers, and control who can sign in",
                     primary=("+ Register New User", self.open_register_modal)).grid(row=0, column=0, sticky="ew", padx=20, pady=(10, 15))
        self.inner = ctk.CTkFrame(self, fg_color="transparent")
        self.inner.grid(row=1, column=0, sticky="nsew")
        self.inner.grid_columnconfigure(0, weight=1)
        self.inner.grid_rowconfigure(0, weight=1)

        self.build_table_panel()

    # ==========================================
    # LEFT: Register / Add User Form
    # ==========================================
    def open_register_modal(self):
        self.reg_modal = ctk.CTkToplevel(self)
        self.reg_modal.title("Register New User")
        C.fit_window(self.reg_modal, 450, 650)
        self.reg_modal.configure(fg_color=T.SURFACE)
        self.reg_modal.attributes("-topmost", True)
        self.reg_modal.grab_set()
        
        self._form_card = ctk.CTkScrollableFrame(
            self.reg_modal, fg_color=T.SURFACE, corner_radius=0)
        self._form_card.pack(fill="both", expand=True)
        form_card = self._form_card

        ctk.CTkLabel(form_card, text="Register New User",
                     font=T.font(16, "bold"), text_color=T.TEXT).pack(
            anchor="w", padx=20, pady=(20, 5))
        ctk.CTkLabel(form_card,
                     text="Fill in all required fields to create a new account.",
                     font=T.font(12), text_color=T.TEXT_MUTED, wraplength=240,
                     justify="left").pack(anchor="w", padx=20, pady=(0, 15))

        def field(parent, label, ph, show=None):
            ctk.CTkLabel(parent, text=label, font=T.font(12, "bold"),
                         text_color=T.TEXT).pack(anchor="w", padx=20)
            kw = dict(placeholder_text=ph)
            if show:
                kw["show"] = show
            e = ctk.CTkEntry(parent, **kw)
            e.pack(fill="x", padx=20, pady=(5, 10))
            return e

        self.reg_name   = field(form_card, "Full Name *",   "Juan Dela Cruz")
        # Added asterisk to Email label to indicate it's now required
        self.reg_email  = field(form_card, "Email Address *", "employee@champion.com")

        ctk.CTkLabel(form_card, text="Role *",
                     font=T.font(12, "bold"), text_color=T.TEXT).pack(anchor="w", padx=20)
        self.reg_role = ctk.CTkOptionMenu(
            form_card, values=["Staff", "Admin", "Worker"],
            fg_color=T.SURFACE_ALT, text_color=T.TEXT,
            command=self._on_reg_role_change)
        self.reg_role.pack(fill="x", padx=20, pady=(5, 10))

        # Bottom section (password fields OR worker notice + buttons) — rebuilt on role change
        self._reg_bottom = ctk.CTkFrame(form_card, fg_color="transparent")
        self._reg_bottom.pack(fill="x")
        self._build_reg_bottom("Staff")
        btn_row = ctk.CTkFrame(self.reg_modal, fg_color="transparent")
        btn_row.pack(side="bottom", fill="x", padx=20, pady=(8, 16))
        btn_row.grid_columnconfigure((0, 1), weight=1)
        C.button(btn_row, kind="primary", text="Register",
                 command=self.execute_register).grid(row=0, column=0, padx=(0, 5), sticky="ew")
        C.button(btn_row, kind="secondary", text="Cancel",
                 command=self.reg_modal.destroy).grid(row=0, column=1, padx=(5, 0), sticky="ew")

    def _build_reg_bottom(self, role):
        for w in self._reg_bottom.winfo_children():
            w.destroy()

        if role == "Worker":
            ctk.CTkLabel(self._reg_bottom,
                         text="Workers cannot log into the system.\nNo password is required.",
                         font=T.font(12), text_color=T.WARNING_TEXT,
                         wraplength=240, justify="left").pack(anchor="w", padx=20, pady=(0, 12))
            self.reg_pass    = None
            self.reg_confirm = None
        else:
            ctk.CTkLabel(self._reg_bottom, text="Password *",
                         font=T.font(12, "bold"), text_color=T.TEXT).pack(anchor="w", padx=20)
            pass_row = ctk.CTkFrame(self._reg_bottom, fg_color="transparent")
            pass_row.pack(fill="x", padx=20, pady=(5, 4))
            self.reg_pass = C.field(pass_row, placeholder_text="Min. 8 characters", show="•")
            self.reg_pass.pack(side="left", fill="x", expand=True, padx=(0, 5))
            self._show_pass = False
            eye_pass = C.button(pass_row, kind="secondary", text="👁", width=38, 
                                     
                                     corner_radius=6)
            eye_pass.pack(side="left")

            def _toggle_pass():
                self._show_pass = not self._show_pass
                self.reg_pass.configure(show="" if self._show_pass else "•")
                eye_pass.configure(text="✕" if self._show_pass else "👁")
            eye_pass.configure(command=_toggle_pass)

            # ── Password strength criteria ──────────────────────
            strength_frame = ctk.CTkFrame(self._reg_bottom, fg_color="transparent")
            strength_frame.pack(anchor="w", padx=20, pady=(0, 8))
            GRAY=T.TEXT_MUTED; GREEN=T.SUCCESS_TEXT
            crit_8     = ctk.CTkLabel(strength_frame, text="✗  At least 8 characters",     font=T.font(12), text_color=GRAY)
            crit_num   = ctk.CTkLabel(strength_frame, text="✗  Contains a number",         font=T.font(12), text_color=GRAY)
            crit_upper = ctk.CTkLabel(strength_frame, text="✗  Contains an uppercase letter", font=T.font(12), text_color=GRAY)
            crit_spec  = ctk.CTkLabel(strength_frame, text="✗  Contains a special character", font=T.font(12), text_color=GRAY)
            for lbl in (crit_8, crit_num, crit_upper, crit_spec):
                lbl.pack(anchor="w")

            def _check_strength(event=None):
                pwd = self.reg_pass.get()
                has_8     = len(pwd) >= 8
                has_num   = any(c.isdigit() for c in pwd)
                has_upper = any(c.isupper() for c in pwd)
                has_spec  = any(c in r"!@#$%^&*()_+-=[]{}|;':\",./<>?" for c in pwd)
                crit_8.configure(    text=f"{'✓' if has_8     else '✗'}  At least 8 characters",      text_color=GREEN if has_8     else GRAY)
                crit_num.configure(  text=f"{'✓' if has_num   else '✗'}  Contains a number",          text_color=GREEN if has_num   else GRAY)
                crit_upper.configure(text=f"{'✓' if has_upper else '✗'}  Contains an uppercase letter", text_color=GREEN if has_upper else GRAY)
                crit_spec.configure( text=f"{'✓' if has_spec  else '✗'}  Contains a special character", text_color=GREEN if has_spec  else GRAY)

            self.reg_pass.bind("<KeyRelease>", _check_strength)
            # ────────────────────────────────────────────────────

            ctk.CTkLabel(self._reg_bottom, text="Confirm Password *",
                         font=T.font(12, "bold"), text_color=T.TEXT).pack(anchor="w", padx=20)
            confirm_row = ctk.CTkFrame(self._reg_bottom, fg_color="transparent")
            confirm_row.pack(fill="x", padx=20, pady=(5, 10))
            self.reg_confirm = C.field(confirm_row, placeholder_text="Re-enter password", show="•")
            self.reg_confirm.pack(side="left", fill="x", expand=True, padx=(0, 5))
            self._show_confirm = False
            eye_confirm = C.button(confirm_row, kind="secondary", text="👁", width=38, 
                                        
                                        corner_radius=6)
            eye_confirm.pack(side="left")

            def _toggle_confirm():
                self._show_confirm = not self._show_confirm
                self.reg_confirm.configure(show="" if self._show_confirm else "•")
                eye_confirm.configure(text="✕" if self._show_confirm else "👁")
            eye_confirm.configure(command=_toggle_confirm)

    def _on_reg_role_change(self, role):
        self._build_reg_bottom(role)

    def execute_register(self):
        name = self.reg_name.get().strip()
        email = self.reg_email.get().strip()
        role = self.reg_role.get()
        pwd = self.reg_pass.get() if self.reg_pass else ""            # [RBAC] passwords are not stripped
        cpwd = self.reg_confirm.get() if self.reg_confirm else ""

        if not name:
            return messagebox.showerror("Validation Error", "Full Name is required.", parent=self.reg_modal)
        try:
            same, similar = user_service.find_similar_names(name)
        except Exception as e:
            return messagebox.showerror("Validation Error", friendly_message(e), parent=self.reg_modal)
        allow_dup = False
        if same:                                                       # real employees share names: WARN, then allow
            if not C.confirm("Same Name Found",
                                       f"{same} active user(s) are already named '{name}'.\n\nRegister another person with the same name?",
                                       parent=self.reg_modal):
                return
            allow_dup = True
        elif similar:
            sim_list = "\n".join([f"• {sn}" for sn in similar])
            if not C.confirm("Similar Name Detected",
                                       f"Wait! Similar names already exist:\n\n{sim_list}\n\nAre you sure you want to register '{name}' as a new distinct user?",
                                       parent=self.reg_modal):
                return
        if not C.confirm("Confirm registration", f"Register {name} as {role}?", parent=self.reg_modal):
            return
        try:
            # [RBAC][CONCURRENCY] Admin only; Workers get NO password; ids come from a locked sequence; blank e-mail is stored as NULL
            res = user_service.register_user(self.user_info, name=name, email=email, role=role, password=pwd,
                                             confirm_password=cpwd, allow_duplicate_name=allow_dup)
        except Exception as e:
            return messagebox.showerror("Could not register", friendly_message(e), parent=self.reg_modal)

        if self.user_info.get("user_id"):
            log_action(self.user_info['user_id'], "Added", "Role Management", f"Registered new {role}: {name} ({res['employee_id']})")
        messagebox.showinfo("Registration Success", f"{role} registered successfully!\n\nSystem Assigned ID: {res['employee_id']}", parent=self.reg_modal)

        self.reg_modal.destroy()
        self.load_user_table()
        dashboard = self.winfo_toplevel()
        if hasattr(dashboard, "dashboard_refresh_job") and dashboard.dashboard_refresh_job:
            dashboard.after_cancel(dashboard.dashboard_refresh_job)
        if hasattr(dashboard, "_auto_refresh_dashboard"):
            dashboard._auto_refresh_dashboard()

    # ==========================================
    # RIGHT: User Management Table
    # ==========================================
    def build_table_panel(self):
        table_card = ctk.CTkFrame(
            self.inner, fg_color=T.SURFACE, corner_radius=10)
        table_card.grid(row=0, column=0, sticky="nsew", padx=0)
        table_card.grid_columnconfigure(0, weight=1)
        table_card.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(table_card, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(20, 10))
        ctk.CTkLabel(top, text="Registered Users",
                     font=T.font(16, "bold"), text_color=T.TEXT).pack(side="left")

        self.user_search_var = ctk.StringVar()
        self.user_search = C.field(
            top, placeholder_text="Search name or ID...", width=200, textvariable=self.user_search_var)
        self.user_search.pack(side="right", padx=(5, 0))
        
        self._user_search_timer = None
        def on_user_search(*args):
            if self._user_search_timer: self.after_cancel(self._user_search_timer)
            self._user_search_timer = self.after(300, self.load_user_table)
        self.user_search_var.trace_add("write", on_user_search)
                                       

        self.user_scroll = ctk.CTkScrollableFrame(
            table_card, fg_color="transparent")
        self.user_scroll.pack(fill="both", expand=True, padx=20, pady=(5, 20))

        self.load_user_table()

    def load_user_table(self):
        for w in self.user_scroll.winfo_children():
            w.destroy()

        # Hard-Bounded Uniform Grid setup
        table_inner = ctk.CTkFrame(self.user_scroll, fg_color="transparent")
        table_inner.pack(fill="x", expand=True)

        headers = ["Employee ID", "Full Name", "Email", "Role", "Actions"]
        weights = [1, 2, 2, 1, 2]
        min_sizes = [110, 160, 160, 80, 240] # Strict 240px min size specifically to fit all 3 buttons!

        for col, (w, min_w) in enumerate(zip(weights, min_sizes)):
            table_inner.grid_columnconfigure(col, weight=w, minsize=min_w, uniform="role_cols")

        # Header Row
        for col, text in enumerate(headers):
            cell = ctk.CTkFrame(table_inner, fg_color=T.PRIMARY, corner_radius=0)
            cell.grid(row=0, column=col, sticky="nsew", pady=(0, 2))
            lbl = ctk.CTkLabel(cell, text=text, font=T.font(12, "bold"), text_color=T.WHITE, anchor="center")
            lbl.pack(fill="both", expand=True, padx=2, pady=10)

        q = self.user_search.get().strip() if hasattr(self, "user_search") else ""
        conn = get_connection()
        if not conn:
            return
        try:
            cursor = conn.cursor(dictionary=True)
            sql = """
                SELECT user_id, employee_id, full_name,
                       IFNULL(email,'—') as email, role, IFNULL(status, 'Active') as status,
                       IFNULL(failed_attempts, 0) as failed_attempts, IFNULL(reset_requested, 0) as reset_requested
                FROM user WHERE IFNULL(status, 'Active') != 'Archived'
            """
            params = []
            if q:
                sql += " AND (full_name LIKE %s OR employee_id LIKE %s)"
                params = [f"%{q}%", f"%{q}%"]
            sql += " ORDER BY full_name ASC"
            cursor.execute(sql, params)
            rows = cursor.fetchall()

            if not rows:
                ctk.CTkLabel(table_inner, text="No users found.",
                             text_color=T.TEXT_MUTED).grid(row=1, column=0, columnspan=len(headers), pady=20)
                return

            for i, row in enumerate(rows):
                r_idx = i + 1
                bg=T.SURFACE_ALT if i % 2 == 0 else "white"

                is_locked = row["status"] == "Locked" or row["reset_requested"] == 1
                display_name = f"🔒 {row['full_name']}" if is_locked else row["full_name"]

                raw_email = row["email"]
                if "@" in raw_email:
                    local, domain = raw_email.split("@", 1)
                    censored_email = f"{local[0]}****@{domain}" if local else f"****@{domain}"
                else:
                    censored_email = raw_email

                vals = [row["employee_id"], display_name, censored_email, row["role"]]
                
                for col, val in enumerate(vals):
                    cell = ctk.CTkFrame(table_inner, fg_color=bg, corner_radius=0)
                    cell.grid(row=r_idx, column=col, sticky="nsew")

                    color=T.TEXT
                    if is_locked and col in (0, 1, 2):
                        color=T.DANGER
                    elif col == 3:
                        if val == "Admin": color=T.SUCCESS_TEXT
                        elif val == "Worker": color=T.WARNING_STRONG

                    lbl = ctk.CTkLabel(cell, text=val, font=T.font(12), text_color=color, justify="center", anchor="center")
                    
                    lbl.configure(wraplength=min_sizes[col] - 10)
                    lbl.pack(fill="both", expand=True, padx=4, pady=12)

                # Action Cell (Contains all 3 Buttons)
                btn_cell = ctk.CTkFrame(table_inner, fg_color=bg, corner_radius=0)
                btn_cell.grid(row=r_idx, column=4, sticky="nsew")
                
                action_frame = ctk.CTkFrame(btn_cell, fg_color="transparent")
                action_frame.pack(expand=True, pady=6)
                
                C.button(action_frame, compact=True, kind="secondary", text="Edit", width=56, 
                              
                              
                              command=lambda r=row: self.open_edit_modal(r)).pack(side="left", padx=(0, 4))
                              
                C.button(action_frame, compact=True, kind="primary", text="🔖 Badge", width=80, 
                              
                              
                              command=lambda r=row: self.print_user_badge(r)).pack(side="left", padx=(0, 4))
                              
                ctk.CTkButton(action_frame, text="Archive", width=56, height=28,
                              fg_color=T.DANGER_BG_STRONG, text_color=T.DANGER_TEXT,
                              hover_color=T.DANGER_BORDER, font=T.font(12, "bold"),
                              command=lambda r=row: self.delete_user(r)).pack(side="left")

        except Exception as e:
            ctk.CTkLabel(self.user_scroll,
                         text=friendly_message(e), text_color=T.DANGER_TEXT).pack(pady=10)
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    def delete_user(self, row):
        if not C.confirm("Confirm Archive", f"Deactivate and archive user '{row['full_name']}'?\n\nThey will no longer be able to log in and will be moved to Maintenance > Archived Employees.", parent=self.winfo_toplevel()):
            return
        try:
            user_service.archive_user(self.user_info, row['user_id'])     # refuses yourself and the last active Admin
        except Exception as e:
            return messagebox.showerror("Could not archive", friendly_message(e), parent=self.winfo_toplevel())
        log_action(self.user_info['user_id'], "Archived", "Role Management", f"Archived user {row['full_name']}")
        self.load_user_table()
        dashboard = self.winfo_toplevel()
        if hasattr(dashboard, "show_toast"):
            dashboard.show_toast(f"✓ User '{row['full_name']}' deactivated and archived.")
        if hasattr(dashboard, "dashboard_refresh_job") and dashboard.dashboard_refresh_job:
            dashboard.after_cancel(dashboard.dashboard_refresh_job)
        if hasattr(dashboard, "_auto_refresh_dashboard"):
            dashboard._auto_refresh_dashboard()

    def open_edit_modal(self, row):
        modal = ctk.CTkToplevel(self)
        modal.title(f"Edit User — {row['full_name']}")
        modal.geometry("500x700")
        modal.configure(fg_color=T.SURFACE)
        modal.resizable(False, False)
        modal.attributes("-topmost", True)
        modal.grab_set()
        modal.update_idletasks()
        x = (modal.winfo_screenwidth() // 2) - 250
        y = (modal.winfo_screenheight() // 2) - 350
        modal.geometry(f"500x700+{x}+{y}")

        ctk.CTkLabel(modal, text=f"Edit: {row['full_name']}",
                     font=T.font(16, "bold"), text_color=T.TEXT).pack(pady=(20, 3))
        ctk.CTkLabel(modal, text=f"Employee ID: {row['employee_id']}",
                     font=T.font(12), text_color=T.TEXT_MUTED).pack(pady=(0, 15))

        if row.get("status") == "Locked" or row.get("reset_requested") == 1:
            ctk.CTkLabel(modal, text="⚠ This account is locked or requested a password reset.",
                         font=T.font(12, "bold"), text_color=T.DANGER_TEXT).pack(pady=(0, 10))

        form = ctk.CTkFrame(modal, fg_color="transparent")
        form.pack(fill="x", padx=30)

        def make_field(lbl, val):
            ctk.CTkLabel(form, text=lbl, font=T.font(12, "bold"),
                         text_color=T.TEXT).pack(anchor="w")
            e = C.field(form)
            e.insert(0, val)
            e.pack(fill="x", pady=(4, 10))
            return e

        name_e  = make_field("Full Name *",  row["full_name"])
        email_e = make_field("Email *",      row["email"] if row["email"] != "—" else "")

        ctk.CTkLabel(form, text="Role", font=T.font(12, "bold"),
                     text_color=T.TEXT).pack(anchor="w")
        role_menu = ctk.CTkOptionMenu(form, values=["Staff", "Admin", "Worker"],
                                      fg_color=T.SURFACE_ALT, text_color=T.TEXT, height=35)
        role_menu.set(row["role"])
        role_menu.pack(fill="x", pady=(4, 10))

        # Dynamic password section — hidden for Worker
        pass_section = ctk.CTkFrame(form, fg_color="transparent")
        pass_e_holder = [None, None]  # mutable container so inner functions can update reference

        def build_pass_section(target_role):
            for w in pass_section.winfo_children():
                w.destroy()
            if target_role == "Worker":
                ctk.CTkLabel(pass_section,
                             text="Workers cannot log into the system. Password is not used.",
                             font=T.font(12), text_color=T.WARNING_TEXT,
                             wraplength=400, justify="left").pack(anchor="w", pady=(0, 8))
                pass_e_holder[0] = None
                pass_e_holder[1] = None
            else:
                ctk.CTkLabel(pass_section,
                             text="New Password (leave blank to keep current)",
                             font=T.font(12, "bold"), text_color=T.TEXT).pack(anchor="w")
                pass_row = ctk.CTkFrame(pass_section, fg_color="transparent")
                pass_row.pack(fill="x", pady=(4, 5))
                
                e = C.field(pass_row, placeholder_text="Optional new password",
                                 show="•")
                e.pack(side="left", fill="x", expand=True, padx=(0, 5))
                
                show_pwd_state = [False]
                eye_btn = C.button(pass_row, kind="secondary", text="👁", width=38, 
                                        
                                        corner_radius=6)
                eye_btn.pack(side="left")
                
                def _toggle_edit_pass():
                    show_pwd_state[0] = not show_pwd_state[0]
                    e.configure(show="" if show_pwd_state[0] else "•")
                    eye_btn.configure(text="✕" if show_pwd_state[0] else "👁")
                eye_btn.configure(command=_toggle_edit_pass)

                # Password strength criteria
                strength_frame = ctk.CTkFrame(pass_section, fg_color="transparent")
                strength_frame.pack(anchor="w", pady=(0, 8))
                GRAY=T.TEXT_MUTED; GREEN=T.SUCCESS_TEXT
                crit_8     = ctk.CTkLabel(strength_frame, text="✗  At least 8 characters",     font=T.font(12), text_color=GRAY)
                crit_num   = ctk.CTkLabel(strength_frame, text="✗  Contains a number",         font=T.font(12), text_color=GRAY)
                crit_upper = ctk.CTkLabel(strength_frame, text="✗  Contains an uppercase letter", font=T.font(12), text_color=GRAY)
                crit_spec  = ctk.CTkLabel(strength_frame, text="✗  Contains a special character", font=T.font(12), text_color=GRAY)
                for lbl in (crit_8, crit_num, crit_upper, crit_spec):
                    lbl.pack(anchor="w")

                def _check_edit_strength(event=None):
                    pwd = e.get()
                    if not pwd:
                        for lbl in (crit_8, crit_num, crit_upper, crit_spec):
                            lbl.configure(text=lbl.cget("text").replace("✓", "✗"), text_color=GRAY)
                        return
                    has_8     = len(pwd) >= 8
                    has_num   = any(c.isdigit() for c in pwd)
                    has_upper = any(c.isupper() for c in pwd)
                    has_spec  = any(c in r"!@#$%^&*()_+-=[]{}|;':\",./<>?" for c in pwd)
                    crit_8.configure(    text=f"{'✓' if has_8     else '✗'}  At least 8 characters",      text_color=GREEN if has_8     else GRAY)
                    crit_num.configure(  text=f"{'✓' if has_num   else '✗'}  Contains a number",          text_color=GREEN if has_num   else GRAY)
                    crit_upper.configure(text=f"{'✓' if has_upper else '✗'}  Contains an uppercase letter", text_color=GREEN if has_upper else GRAY)
                    crit_spec.configure( text=f"{'✓' if has_spec  else '✗'}  Contains a special character", text_color=GREEN if has_spec  else GRAY)

                e.bind("<KeyRelease>", _check_edit_strength)

                ctk.CTkLabel(pass_section, text="Confirm New Password", font=T.font(12, "bold"), text_color=T.TEXT).pack(anchor="w")
                conf_row = ctk.CTkFrame(pass_section, fg_color="transparent")
                conf_row.pack(fill="x", pady=(4, 15))
                conf_e = C.field(conf_row, placeholder_text="Re-enter new password", show="•")
                conf_e.pack(side="left", fill="x", expand=True, padx=(0, 5))
                
                show_conf_state = [False]
                eye_conf_btn = C.button(conf_row, kind="secondary", text="👁", width=38, 
                                        
                                        corner_radius=6)
                eye_conf_btn.pack(side="left")
                
                def _toggle_conf_pass():
                    show_conf_state[0] = not show_conf_state[0]
                    conf_e.configure(show="" if show_conf_state[0] else "•")
                    eye_conf_btn.configure(text="✕" if show_conf_state[0] else "👁")
                eye_conf_btn.configure(command=_toggle_conf_pass)
                
                pass_e_holder[0] = e
                pass_e_holder[1] = conf_e

        role_menu.configure(command=lambda r: build_pass_section(r))
        build_pass_section(row["role"])
        pass_section.pack(fill="x")

        def save_edit():
            new_name  = name_e.get().strip()
            new_email = email_e.get().strip()
            new_role  = role_menu.get()
            new_pass  = pass_e_holder[0].get() if pass_e_holder[0] else ""      # [RBAC] passwords are not stripped
            conf_pass = pass_e_holder[1].get() if pass_e_holder[1] else ""

            if not new_name:
                messagebox.showerror("Error", "Full Name is required.", parent=modal)
                return
            allow_dup = False
            try:
                same, similar = user_service.find_similar_names(new_name, exclude_user_id=row["user_id"])
            except Exception as e:
                return messagebox.showerror("Error", friendly_message(e), parent=modal)
            if new_name.lower() != row['full_name'].lower():
                if same:
                    if not C.confirm("Same Name Found", f"{same} active user(s) are already named '{new_name}'.\n\nRename this user anyway?", parent=modal):
                        return
                    allow_dup = True
                elif similar:
                    sim_list = "\n".join([f"• {sn}" for sn in similar])
                    if not C.confirm("Similar Name Detected", f"Similar user names already exist:\n\n{sim_list}\n\nAre you sure you want to rename this user to '{new_name}'?", parent=modal):
                        return
            if not C.confirm("Confirm account changes", f"Save changes for {new_name} ({new_role})?", parent=modal):
                return
            try:
                res = user_service.update_user(self.user_info, row["user_id"], name=new_name, email=new_email, role=new_role,
                                               new_password=new_pass, confirm_password=conf_pass, allow_duplicate_name=allow_dup)
            except Exception as e:
                return messagebox.showerror("Could not update", friendly_message(e), parent=modal)
            if self.user_info.get("user_id"):
                log_action(self.user_info['user_id'], "Edited", "Role Management",
                           f"Edited user {res['name']} ({res['employee_id']}){' and cleared the lockout' if res['unlocked'] else ''}")
            C.notify(self, "User account updated successfully.")
            modal.destroy()
            self.load_user_table()
            dashboard = self.winfo_toplevel()
            if hasattr(dashboard, "dashboard_refresh_job") and dashboard.dashboard_refresh_job:
                dashboard.after_cancel(dashboard.dashboard_refresh_job)
            if hasattr(dashboard, "_auto_refresh_dashboard"):
                dashboard._auto_refresh_dashboard()

        btn_row = ctk.CTkFrame(modal, fg_color="transparent")
        btn_row.pack(fill="x", padx=30, pady=(5, 20))
        C.button(btn_row, kind="primary", text="Save Changes", 
                      
                      command=save_edit).pack(side="left", padx=(0, 10), fill="x", expand=True)
        C.button(btn_row, kind="secondary", text="Cancel", 
                      
                      command=modal.destroy).pack(side="right", padx=(10, 0), fill="x", expand=True)

    def print_user_badge(self, row):
        try:
            file_path = generate_id_badge(row['employee_id'], row['full_name'], row['role'])
            import time
            time.sleep(0.5)
            os.startfile(file_path)
            
        except Exception as e:
            messagebox.showerror("Print Error", f"Failed to generate badge.\n{e}", parent=self.winfo_toplevel())
