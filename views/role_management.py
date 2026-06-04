import customtkinter as ctk
from tkinter import messagebox
from database import get_connection, generate_id_badge, log_action
import bcrypt
import secrets
import os
import tempfile
import qrcode
from PIL import Image, ImageDraw, ImageFont
import re


class RoleManagementView(ctk.CTkFrame):
    def __init__(self, parent, user_info=None):
        super().__init__(parent, fg_color="transparent")

        self.user_info = user_info or {}
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.build_ui()

    def build_ui(self):
        self.inner = ctk.CTkFrame(self, fg_color="transparent")
        self.inner.grid(row=0, column=0, sticky="nsew")
        self.inner.grid_columnconfigure(0, weight=1)
        self.inner.grid_rowconfigure(0, weight=1)

        self.build_table_panel()

    # ==========================================
    # LEFT: Register / Add User Form
    # ==========================================
    def open_register_modal(self):
        self.reg_modal = ctk.CTkToplevel(self)
        self.reg_modal.title("Register New User")
        self.reg_modal.geometry("450x650")
        self.reg_modal.configure(fg_color="white")
        self.reg_modal.attributes("-topmost", True)
        self.reg_modal.grab_set()
        
        self.reg_modal.update_idletasks()
        x = (self.reg_modal.winfo_screenwidth() // 2) - (450 // 2)
        y = (self.reg_modal.winfo_screenheight() // 2) - (650 // 2)
        self.reg_modal.geometry(f"+{x}+{y}")

        self._form_card = ctk.CTkScrollableFrame(
            self.reg_modal, fg_color="white", corner_radius=0)
        self._form_card.pack(fill="both", expand=True)
        form_card = self._form_card

        ctk.CTkLabel(form_card, text="Register New User",
                     font=("Inter", 16, "bold"), text_color="#1A1A1A").pack(
            anchor="w", padx=20, pady=(20, 5))
        ctk.CTkLabel(form_card,
                     text="Fill in all required fields to create a new account.",
                     font=("Inter", 11), text_color="gray", wraplength=240,
                     justify="left").pack(anchor="w", padx=20, pady=(0, 15))

        def field(parent, label, ph, show=None):
            ctk.CTkLabel(parent, text=label, font=("Inter", 12, "bold"),
                         text_color="#1A1A1A").pack(anchor="w", padx=20)
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
                     font=("Inter", 12, "bold"), text_color="#1A1A1A").pack(anchor="w", padx=20)
        self.reg_role = ctk.CTkOptionMenu(
            form_card, values=["Staff", "Admin", "Worker"],
            fg_color="#F9FAFB", text_color="black",
            command=self._on_reg_role_change)
        self.reg_role.pack(fill="x", padx=20, pady=(5, 10))

        # Bottom section (password fields OR worker notice + buttons) — rebuilt on role change
        self._reg_bottom = ctk.CTkFrame(form_card, fg_color="transparent")
        self._reg_bottom.pack(fill="x")
        self._build_reg_bottom("Staff")

    def _build_reg_bottom(self, role):
        for w in self._reg_bottom.winfo_children():
            w.destroy()

        if role == "Worker":
            ctk.CTkLabel(self._reg_bottom,
                         text="Workers cannot log into the system.\nNo password is required.",
                         font=("Inter", 11), text_color="#D35400",
                         wraplength=240, justify="left").pack(anchor="w", padx=20, pady=(0, 12))
            self.reg_pass    = None
            self.reg_confirm = None
        else:
            ctk.CTkLabel(self._reg_bottom, text="Password *",
                         font=("Inter", 12, "bold"), text_color="#1A1A1A").pack(anchor="w", padx=20)
            pass_row = ctk.CTkFrame(self._reg_bottom, fg_color="transparent")
            pass_row.pack(fill="x", padx=20, pady=(5, 4))
            self.reg_pass = ctk.CTkEntry(pass_row, placeholder_text="Min. 8 characters", show="•")
            self.reg_pass.pack(side="left", fill="x", expand=True, padx=(0, 5))
            self._show_pass = False
            eye_pass = ctk.CTkButton(pass_row, text="👁", width=38, height=38,
                                     fg_color="#F3F4F6", text_color="#4B5563",
                                     hover_color="#E5E7EB", corner_radius=6,
                                     font=("Inter", 14))
            eye_pass.pack(side="left")

            def _toggle_pass():
                self._show_pass = not self._show_pass
                self.reg_pass.configure(show="" if self._show_pass else "•")
                eye_pass.configure(text="✕" if self._show_pass else "👁")
            eye_pass.configure(command=_toggle_pass)

            # ── Password strength criteria ──────────────────────
            strength_frame = ctk.CTkFrame(self._reg_bottom, fg_color="transparent")
            strength_frame.pack(anchor="w", padx=20, pady=(0, 8))
            GRAY = "#AAAAAA"; GREEN = "#2ECC71"
            crit_8     = ctk.CTkLabel(strength_frame, text="✗  At least 8 characters",     font=("Inter", 10), text_color=GRAY)
            crit_num   = ctk.CTkLabel(strength_frame, text="✗  Contains a number",         font=("Inter", 10), text_color=GRAY)
            crit_upper = ctk.CTkLabel(strength_frame, text="✗  Contains an uppercase letter", font=("Inter", 10), text_color=GRAY)
            crit_spec  = ctk.CTkLabel(strength_frame, text="✗  Contains a special character", font=("Inter", 10), text_color=GRAY)
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
                         font=("Inter", 12, "bold"), text_color="#1A1A1A").pack(anchor="w", padx=20)
            confirm_row = ctk.CTkFrame(self._reg_bottom, fg_color="transparent")
            confirm_row.pack(fill="x", padx=20, pady=(5, 10))
            self.reg_confirm = ctk.CTkEntry(confirm_row, placeholder_text="Re-enter password", show="•")
            self.reg_confirm.pack(side="left", fill="x", expand=True, padx=(0, 5))
            self._show_confirm = False
            eye_confirm = ctk.CTkButton(confirm_row, text="👁", width=38, height=38,
                                        fg_color="#F3F4F6", text_color="#4B5563",
                                        hover_color="#E5E7EB", corner_radius=6,
                                        font=("Inter", 14))
            eye_confirm.pack(side="left")

            def _toggle_confirm():
                self._show_confirm = not self._show_confirm
                self.reg_confirm.configure(show="" if self._show_confirm else "•")
                eye_confirm.configure(text="✕" if self._show_confirm else "👁")
            eye_confirm.configure(command=_toggle_confirm)

        btn_row = ctk.CTkFrame(self._reg_bottom, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(15, 20))
        btn_row.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(btn_row, text="Register", height=40,
                      fg_color="#1E4528", hover_color="#14301C",
                      font=("Inter", 13, "bold"),
                      command=self.execute_register).grid(row=0, column=0, padx=(0, 5), sticky="ew")
        ctk.CTkButton(btn_row, text="Cancel", height=40,
                      fg_color="#E0E0E0", text_color="black", hover_color="#CCCCCC",
                      font=("Inter", 13, "bold"),
                      command=self.reg_modal.destroy).grid(row=0, column=1, padx=(5, 0), sticky="ew")

    def _on_reg_role_change(self, role):
        self._build_reg_bottom(role)

    def execute_register(self):
        name = self.reg_name.get().strip()
        email = self.reg_email.get().strip()
        role = self.reg_role.get()
        pwd = self.reg_pass.get().strip() if self.reg_pass else ""
        cpwd = self.reg_confirm.get().strip() if self.reg_confirm else ""

        # 1. Validation
        if role == "Worker":
            if not name:
                return messagebox.showerror("Validation Error", "Full Name is required for Workers.", parent=self.reg_modal)
            pwd = "FIELD_WORKER_NO_LOGIN_SYSTEM_LOCKED" 
            cpwd = pwd
        else:
            if not all([name, pwd, cpwd]):
                return messagebox.showerror("Validation Error", "Full Name and Password are required.", parent=self.reg_modal)
            if pwd != cpwd:
                return messagebox.showerror("Password Mismatch", "Passwords do not match.", parent=self.reg_modal)
            if len(pwd) < 8:
                return messagebox.showerror("Weak Password", "Password must be at least 8 characters.", parent=self.reg_modal)

        conn = get_connection()
        if not conn: return
        try:
            cursor = conn.cursor(dictionary=True)
            
            cursor.execute("SELECT user_id FROM user WHERE full_name = %s", (name,))
            if cursor.fetchone():
                messagebox.showerror("Duplicate User", "A user with this full name already exists.", parent=self.reg_modal)
                return
                
            if email:
                cursor.execute("SELECT user_id FROM user WHERE email = %s", (email,))
                if cursor.fetchone():
                    messagebox.showerror("Duplicate User", "A user with this email address already exists.", parent=self.reg_modal)
                    return
            
            # --- 2. THE AUTO-GENERATION ENGINE ---
            prefix = ""
            if role == "Admin": prefix = "ADM"
            elif role == "Staff": prefix = "STF"
            elif role == "Worker": prefix = "WKR"
            
            from datetime import datetime
            current_year = datetime.now().year
            
            # Find the highest existing ID for this specific role and year
            search_pattern = f"{prefix}-{current_year}-%"
            cursor.execute("SELECT employee_id FROM user WHERE employee_id LIKE %s ORDER BY employee_id DESC LIMIT 1", (search_pattern,))
            last_record = cursor.fetchone()
            
            if last_record and last_record['employee_id']:
                # Extract the last 3 digits and add 1
                last_seq = int(last_record['employee_id'].split('-')[-1])
                new_seq = last_seq + 1
            else:
                new_seq = 1 # Start at 001 if no users exist for this year
                
            # Combine them into the final format (e.g., ADM-2026-004)
            new_emp_id = f"{prefix}-{current_year}-{new_seq:03d}"
            
            # --- 3. SAVE TO DATABASE ---
            hashed_pw = bcrypt.hashpw(pwd.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            
            cursor.execute("INSERT INTO user (employee_id, full_name, email, role, password_hash) VALUES (%s, %s, %s, %s, %s)",
                           (new_emp_id, name, email, role, hashed_pw))
            conn.commit()
            
            if self.user_info.get("user_id"):
                log_action(self.user_info['user_id'], "Added", "Role Management", f"Registered new {role}: {name} ({new_emp_id})")
                
            # Announce the generated ID to the Admin
            messagebox.showinfo("Registration Success", f"{role} registered successfully!\n\nSystem Assigned ID: {new_emp_id}", parent=self.reg_modal)
            
            self.reg_modal.destroy()
            self.load_user_table()
            
        except Exception as e:
            messagebox.showerror("Database Error", str(e), parent=self.reg_modal)
        finally:
            if conn.is_connected(): cursor.close(); conn.close()

    # ==========================================
    # RIGHT: User Management Table
    # ==========================================
    def build_table_panel(self):
        table_card = ctk.CTkFrame(
            self.inner, fg_color="white", corner_radius=10)
        table_card.grid(row=0, column=0, sticky="nsew", padx=0)
        table_card.grid_columnconfigure(0, weight=1)
        table_card.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(table_card, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(20, 10))
        ctk.CTkLabel(top, text="Registered Users",
                     font=("Inter", 16, "bold"), text_color="#1A1A1A").pack(side="left")

        self.user_search = ctk.CTkEntry(
            top, placeholder_text="Search name or ID...", width=200)
        self.user_search.pack(side="right", padx=(5, 0))
        self.user_search.bind("<Return>", lambda e: self.load_user_table())
        ctk.CTkButton(top, text="Search", width=70,
                      fg_color="#1E4528", hover_color="#14301C",
                      font=("Inter", 11, "bold"),
                      command=self.load_user_table).pack(side="right", padx=5)
        ctk.CTkButton(top, text="↻", width=40,
                      fg_color="#E0E0E0", text_color="black", hover_color="#CCCCCC",
                      command=lambda: [self.user_search.delete(0, "end"),
                                       self.load_user_table()]).pack(side="right")
                                       
        ctk.CTkButton(top, text="+ Register New User", width=150, fg_color="#1E4528", hover_color="#14301C", font=("Inter", 12, "bold"), command=self.open_register_modal).pack(side="right", padx=(10, 5))

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
            cell = ctk.CTkFrame(table_inner, fg_color="#1E4528", corner_radius=0)
            cell.grid(row=0, column=col, sticky="nsew", pady=(0, 2))
            lbl = ctk.CTkLabel(cell, text=text, font=("Inter", 11, "bold"), text_color="white", anchor="center")
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
                             text_color="gray").grid(row=1, column=0, columnspan=len(headers), pady=20)
                return

            for i, row in enumerate(rows):
                r_idx = i + 1
                bg = "#F9FAFB" if i % 2 == 0 else "white"

                is_locked = row["status"] == "Locked" or row["reset_requested"] == 1
                display_name = f"🔒 {row['full_name']}" if is_locked else row["full_name"]

                vals = [row["employee_id"], display_name, row["email"], row["role"]]
                
                for col, val in enumerate(vals):
                    cell = ctk.CTkFrame(table_inner, fg_color=bg, corner_radius=0)
                    cell.grid(row=r_idx, column=col, sticky="nsew")

                    color = "#1A1A1A"
                    if is_locked and col in (0, 1, 2):
                        color = "#D8000C"
                    elif col == 3:
                        if val == "Admin": color = "#2ECC71"
                        elif val == "Worker": color = "#D35400"

                    lbl = ctk.CTkLabel(cell, text=val, font=("Inter", 11), text_color=color, justify="center", anchor="center")
                    
                    lbl.configure(wraplength=min_sizes[col] - 10)
                    lbl.pack(fill="both", expand=True, padx=4, pady=12)

                # Action Cell (Contains all 3 Buttons)
                btn_cell = ctk.CTkFrame(table_inner, fg_color=bg, corner_radius=0)
                btn_cell.grid(row=r_idx, column=4, sticky="nsew")
                
                action_frame = ctk.CTkFrame(btn_cell, fg_color="transparent")
                action_frame.pack(expand=True, pady=6)
                
                ctk.CTkButton(action_frame, text="Edit", width=56, height=28,
                              fg_color="#F1C40F", text_color="black",
                              hover_color="#D4AC0D", font=("Inter", 10, "bold"),
                              command=lambda r=row: self.open_edit_modal(r)).pack(side="left", padx=(0, 4))
                              
                ctk.CTkButton(action_frame, text="🔖 Badge", width=80, height=28,
                              fg_color="#3498DB", text_color="white",
                              hover_color="#2980B9", font=("Inter", 10, "bold"),
                              command=lambda r=row: self.print_user_badge(r)).pack(side="left", padx=(0, 4))
                              
                ctk.CTkButton(action_frame, text="Archive", width=56, height=28,
                              fg_color="#FFEAEA", text_color="#D8000C",
                              hover_color="#FFC0C0", font=("Inter", 10, "bold"),
                              command=lambda r=row: self.delete_user(r)).pack(side="left")

        except Exception as e:
            ctk.CTkLabel(self.user_scroll,
                         text=f"Error: {e}", text_color="red").pack(pady=10)
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    def delete_user(self, row):
        if messagebox.askyesno("Confirm Archive", f"Deactivate and archive user '{row['full_name']}'?\n\nThey will no longer be able to log in and will be moved to Maintenance > Archived Employees.", parent=self.winfo_toplevel()):
            conn = get_connection()
            if not conn: return
            try:
                cursor = conn.cursor()
                cursor.execute("UPDATE user SET status = 'Archived' WHERE user_id = %s", (row['user_id'],))
                conn.commit()
                log_action(self.user_info['user_id'], "Archived", "Role Management", f"Archived user {row['full_name']}")
                messagebox.showinfo("Archived", f"User '{row['full_name']}' has been deactivated.\n\nThey have been moved to Maintenance > Archived Employees.", parent=self.winfo_toplevel())
                self.load_user_table()
            except Exception as e:
                messagebox.showerror("Error", str(e), parent=self.winfo_toplevel())
            finally:
                if conn.is_connected(): cursor.close(); conn.close()

    def open_edit_modal(self, row):
        modal = ctk.CTkToplevel(self)
        modal.title(f"Edit User — {row['full_name']}")
        modal.geometry("500x500")
        modal.configure(fg_color="white")
        modal.resizable(False, False)
        modal.attributes("-topmost", True)
        modal.grab_set()
        modal.update_idletasks()
        x = (modal.winfo_screenwidth() // 2) - 250
        y = (modal.winfo_screenheight() // 2) - 250
        modal.geometry(f"+{x}+{y}")

        ctk.CTkLabel(modal, text=f"Edit: {row['full_name']}",
                     font=("Inter", 15, "bold"), text_color="black").pack(pady=(20, 3))
        ctk.CTkLabel(modal, text=f"Employee ID: {row['employee_id']}",
                     font=("Inter", 11), text_color="gray").pack(pady=(0, 15))

        if row.get("status") == "Locked" or row.get("reset_requested") == 1:
            ctk.CTkLabel(modal, text="⚠ This account is locked or requested a password reset.",
                         font=("Inter", 12, "bold"), text_color="#D8000C").pack(pady=(0, 10))

        form = ctk.CTkFrame(modal, fg_color="transparent")
        form.pack(fill="x", padx=30)

        def make_field(lbl, val):
            ctk.CTkLabel(form, text=lbl, font=("Inter", 11, "bold"),
                         text_color="#1A1A1A").pack(anchor="w")
            e = ctk.CTkEntry(form, height=35)
            e.insert(0, val)
            e.pack(fill="x", pady=(4, 10))
            return e

        name_e  = make_field("Full Name *",  row["full_name"])
        email_e = make_field("Email *",      row["email"] if row["email"] != "—" else "")

        ctk.CTkLabel(form, text="Role", font=("Inter", 11, "bold"),
                     text_color="#1A1A1A").pack(anchor="w")
        role_menu = ctk.CTkOptionMenu(form, values=["Staff", "Admin", "Worker"],
                                      fg_color="#F9FAFB", text_color="black", height=35)
        role_menu.set(row["role"])
        role_menu.pack(fill="x", pady=(4, 10))

        # Dynamic password section — hidden for Worker
        pass_section = ctk.CTkFrame(form, fg_color="transparent")
        pass_e_holder = [None]  # mutable container so inner functions can update reference

        def build_pass_section(target_role):
            for w in pass_section.winfo_children():
                w.destroy()
            if target_role == "Worker":
                ctk.CTkLabel(pass_section,
                             text="Workers cannot log into the system. Password is not used.",
                             font=("Inter", 11), text_color="#D35400",
                             wraplength=400, justify="left").pack(anchor="w", pady=(0, 8))
                pass_e_holder[0] = None
            else:
                ctk.CTkLabel(pass_section,
                             text="New Password (leave blank to keep current)",
                             font=("Inter", 11, "bold"), text_color="#1A1A1A").pack(anchor="w")
                pass_row = ctk.CTkFrame(pass_section, fg_color="transparent")
                pass_row.pack(fill="x", pady=(4, 15))
                
                e = ctk.CTkEntry(pass_row, placeholder_text="Optional new password",
                                 show="•", height=35)
                e.pack(side="left", fill="x", expand=True, padx=(0, 5))
                
                show_pwd_state = [False]
                eye_btn = ctk.CTkButton(pass_row, text="👁", width=38, height=35,
                                        fg_color="#F3F4F6", text_color="#4B5563",
                                        hover_color="#E5E7EB", corner_radius=6,
                                        font=("Inter", 14))
                eye_btn.pack(side="left")
                
                def _toggle_edit_pass():
                    show_pwd_state[0] = not show_pwd_state[0]
                    e.configure(show="" if show_pwd_state[0] else "•")
                    eye_btn.configure(text="✕" if show_pwd_state[0] else "👁")
                eye_btn.configure(command=_toggle_edit_pass)
                
                pass_e_holder[0] = e

        role_menu.configure(command=lambda r: build_pass_section(r))
        build_pass_section(row["role"])
        pass_section.pack(fill="x")

        def save_edit():
            new_name  = name_e.get().strip()
            new_email = email_e.get().strip()
            new_role  = role_menu.get()
            new_pass  = pass_e_holder[0].get().strip() if pass_e_holder[0] else ""

            if not new_name:
                messagebox.showerror("Error", "Full Name is required.", parent=modal)
                return

            # --- FIX A: Require Email for login-enabled roles (Admin/Staff)
            if new_role != "Worker" and not new_email:
                messagebox.showerror("Error", "Email Address is required to enable the Forgot Password feature.", parent=modal)
                return

            # If promoting a Worker to a login role, a password is required
            old_role = row["role"]
            if new_role != "Worker" and old_role == "Worker" and not new_pass:
                messagebox.showerror("Password Required",
                                     "Assigning a login role requires setting a password.",
                                     parent=modal)
                return

            conn = get_connection()
            if not conn:
                return
            try:
                cursor = conn.cursor()
                if new_role == "Worker":
                    # Keep existing hash or store placeholder — Workers never log in
                    cursor.execute("""
                        UPDATE user SET full_name=%s, email=%s, role=%s,
                                        status='Active', failed_attempts=0, reset_requested=0
                        WHERE user_id=%s
                    """, (new_name, new_email or None, new_role, row["user_id"]))
                elif new_pass:
                    if len(new_pass) < 8:
                        messagebox.showerror("Weak Password",
                                             "Password must be at least 8 characters.",
                                             parent=modal)
                        return
                    hashed = bcrypt.hashpw(new_pass.encode("utf-8"),
                                           bcrypt.gensalt()).decode("utf-8")
                    cursor.execute("""
                        UPDATE user SET full_name=%s, email=%s, role=%s, password_hash=%s,
                                        status='Active', failed_attempts=0, reset_requested=0
                        WHERE user_id=%s
                    """, (new_name, new_email or None, new_role, hashed, row["user_id"]))
                else:
                    cursor.execute("""
                        UPDATE user SET full_name=%s, email=%s, role=%s,
                                        status='Active', failed_attempts=0, reset_requested=0
                        WHERE user_id=%s
                    """, (new_name, new_email or None, new_role, row["user_id"]))
                conn.commit()
                messagebox.showinfo("Updated", "User account updated successfully.", parent=modal)
                modal.destroy()
                self.load_user_table()
            except Exception as e:
                messagebox.showerror("Error", str(e), parent=modal)
            finally:
                if conn.is_connected():
                    cursor.close()
                    conn.close()

        btn_row = ctk.CTkFrame(modal, fg_color="transparent")
        btn_row.pack(fill="x", padx=30, pady=(5, 20))
        ctk.CTkButton(btn_row, text="Save Changes", height=38,
                      fg_color="#1E4528", hover_color="#14301C",
                      command=save_edit).pack(side="left", padx=(0, 10), fill="x", expand=True)
        ctk.CTkButton(btn_row, text="Cancel", height=38,
                      fg_color="#E0E0E0", text_color="black", hover_color="#CCCCCC",
                      command=modal.destroy).pack(side="right", padx=(10, 0), fill="x", expand=True)

    def print_user_badge(self, row):
        try:
            qr_payload = f"Employee ID: {row['employee_id']}\nName: {row['full_name']}\nRole: {row['role']}"
            qr = qrcode.QRCode(version=1, box_size=10, border=2)
            qr.add_data(qr_payload)
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
            
            canvas_width, canvas_height = 400, 600
            canvas = Image.new('RGB', (canvas_width, canvas_height), 'white')
            draw = ImageDraw.Draw(canvas)
            
            draw.rectangle([(0, 0), (canvas_width, 80)], fill="#1E4528")
            try:
                font_title = ImageFont.truetype("arialbd.ttf", 22)
                font_name = ImageFont.truetype("arialbd.ttf", 24)
                font_role = ImageFont.truetype("arial.ttf", 18)
                font_id = ImageFont.truetype("arial.ttf", 16)
            except IOError:
                font_title = font_name = font_role = font_id = ImageFont.load_default()
                
            title_text = "CHAMPION FINE TOOLING"
            bbox = draw.textbbox((0, 0), title_text, font=font_title)
            draw.text(((canvas_width - (bbox[2] - bbox[0])) // 2, 25), title_text, fill="white", font=font_title)
            
            qr_x = (canvas_width - qr_img.width) // 2
            qr_y = 120
            canvas.paste(qr_img, (qr_x, qr_y))
            
            y_offset = qr_y + qr_img.height + 30
            
            name_text = row['full_name']
            bbox = draw.textbbox((0, 0), name_text, font=font_name)
            draw.text(((canvas_width - (bbox[2] - bbox[0])) // 2, y_offset), name_text, fill="black", font=font_name)
            
            y_offset += 40
            role_text = f"Role: {row['role']}"
            bbox = draw.textbbox((0, 0), role_text, font=font_role)
            draw.text(((canvas_width - (bbox[2] - bbox[0])) // 2, y_offset), role_text, fill="#555555", font=font_role)
            
            y_offset += 30
            id_text = f"ID: {row['employee_id']}"
            bbox = draw.textbbox((0, 0), id_text, font=font_id)
            draw.text(((canvas_width - (bbox[2] - bbox[0])) // 2, y_offset), id_text, fill="#555555", font=font_id)
            
            temp_dir = tempfile.gettempdir()
            file_path = os.path.join(temp_dir, f"Badge_{row['employee_id']}.pdf")
            canvas.save(file_path, "PDF", resolution=100.0)
            
            import time
            time.sleep(0.5)
            os.startfile(file_path)
            
        except Exception as e:
            messagebox.showerror("Print Error", f"Failed to generate badge.\n{e}", parent=self.winfo_toplevel())