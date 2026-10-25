import os
import json
import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
from PIL import Image
import bcrypt
from database import get_connection, log_action
from dashboard import DashboardApp
from database import log_action, start_session
import cv2
from pyzbar.pyzbar import decode, ZBarSymbol
from services.errors import friendly_message
from services import auth_service, validators as _v
from ui import components as C
from ui import theme as T

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("green")
C.apply_widget_defaults()          # the stock green theme is mint with white text; use the brand colours instead


class LoginApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.REMEMBER_FILE = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "remember_config.json")
        self.title("Champion Fine Tooling - Automated Management System")
        self.configure(fg_color=T.BG)
        self.minsize(450, 680)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        w, h = 450, 680
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        self.icon_path = os.path.join(os.path.dirname(
            __file__), "assets", "login_logo.png")
        try:
            icon_img = tk.PhotoImage(file=self.icon_path)
            self.iconphoto(False, icon_img)
        except Exception:
            pass


        self.main_frame = C.card(self, 
                                       border_width=1)
        self.main_frame.pack(pady=40, padx=40, fill="both", expand=True)

        self.content_frame = ctk.CTkFrame(
            self.main_frame, fg_color="transparent")
        self.content_frame.place(relx=0.5, rely=0.5, anchor="center")

        try:
            self.main_logo_img = ctk.CTkImage(
                light_image=Image.open(self.icon_path), size=(110, 100))
            ctk.CTkLabel(self.content_frame,
                         image=self.main_logo_img, text="").pack(pady=(0, 10))
        except FileNotFoundError:
            ctk.CTkLabel(self.content_frame, text="[ LOGO ]",
                         font=T.font(20, "bold"), text_color=T.SUCCESS_TEXT).pack(pady=(0, 10))

        ctk.CTkLabel(self.content_frame, text="Champion Fine Tooling Corp.",
                     font=T.font(20, "bold"), text_color=T.TEXT).pack(pady=(0, 2))
        ctk.CTkLabel(self.content_frame, text="Automated Management System",
                     font=T.font(16), text_color=T.TEXT_MUTED).pack(pady=(0, 20))

        # --- THE USERNAME FIELD & SCAN BUTTON ---
        self.user_frame_container = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        self.user_frame_container.pack(pady=(0, 15))

        self.user_entry = C.field(self.user_frame_container,
                                       placeholder_text="Employee ID (e.g. ADM-2026-001)",
                                       width=215, 
                                       border_color=T.BORDER_STRONG)
        self.user_entry.pack(side="left", padx=(0, 5))

        self.scan_btn = C.button(self.user_frame_container, kind="primary", text="📷 Scan", width=60, 
                                      
                                      command=self.open_scanner)
        self.scan_btn.pack(side="right")
        
        # Intercept scanner carriage return to drop focus instantly to password
        self.user_entry.bind("<Return>", lambda e: self.pass_entry.focus_set())
        self.user_entry.bind("<KeyRelease>", lambda e: (self.format_emp_id(e, self.user_entry), self.login_button.configure(state="normal", text="Login")))
        
        # Set window focus to this entry field immediately upon application startup
        self.user_entry.focus_set()

        self.pass_frame = ctk.CTkFrame(
            self.content_frame, fg_color="transparent", width=280, height=40)
        self.pass_frame.pack(pady=(0, 10))
        self.pass_frame.pack_propagate(False)

        self.pass_entry = C.field(self.pass_frame,
                                       placeholder_text="Password",
                                       width=235, 
                                       
                                       show="•")
        self.pass_entry.pack(side="left")
        self.pass_entry.bind("<Return>", lambda e: self.login())

        self.show_pwd = False
        self.eye_btn = C.button(self.pass_frame, kind="secondary", text="👁", width=40, 
                                     
                                     
                                     command=self.toggle_password)
        self.eye_btn.pack(side="right", padx=(5, 0))

        self.remember_check = ctk.CTkCheckBox(self.content_frame, text="Remember me",
                                              font=T.font(12), checkbox_width=18,
                                              checkbox_height=18, border_color=T.BORDER_STRONG,
                                              text_color=T.TEXT_SECONDARY)
        self.remember_check.pack(anchor="w", pady=(0, 15))

        self.error_banner = ctk.CTkLabel(self.content_frame, text="",
                                         fg_color="transparent", text_color=T.DANGER_TEXT,
                                         font=T.font(12, "bold"), corner_radius=5)
        self.error_banner.pack(fill="x", pady=(0, 10))

        self.login_button = C.button(self.content_frame, kind="primary", text="Login",
                                          command=self.login, width=280, 
                                          
                                          hover_color=T.PRIMARY_HOVER)
        self.login_button.pack(pady=(0, 15))

        footer = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        footer.pack(pady=5)
        lbl_u = ctk.CTkLabel(footer, text="Forgot Username?",
                             font=T.font(12), text_color=T.TEXT_SECONDARY, cursor="hand2")
        lbl_u.pack(side="left", padx=5)
        lbl_u.bind("<Button-1>", lambda e: self.open_forgot_username())
        ctk.CTkLabel(footer, text="|", font=T.font(12),
                     text_color=T.BORDER_STRONG).pack(side="left")
        lbl_p = ctk.CTkLabel(footer, text="Forgot Password?",
                             font=T.font(12), text_color=T.TEXT_SECONDARY, cursor="hand2")
        lbl_p.pack(side="left", padx=5)
        lbl_p.bind("<Button-1>", lambda e: self.open_forgot_password())

        self.load_remember_me()
        self._enforce_schema_current()

    def _enforce_schema_current(self):
        """[UNHAPPY-PATH] Schema changes are made by `python -m db.migrate`, never by the screens. If the database is not
        at the expected version, say so plainly and do not let anyone log in against a half-upgraded database."""
        from db import db
        from db.migrate import check_schema_current
        ok, msg = check_schema_current(db)
        if not ok and db.online is not False:
            self.show_error(msg)
            self.login_button.configure(state="disabled", text="Database needs upgrade")

    def format_emp_id(self, event, widget):
        if event.keysym in ('BackSpace', 'Delete', 'Left', 'Right', 'Up', 'Down', 'Tab'):
            return
        text = widget.get().replace('-', '').upper()
        text = ''.join(c for c in text if c.isalnum())[:10]
        formatted = ''
        for i, char in enumerate(text):
            if i == 3 or i == 7:
                formatted += '-'
            formatted += char
        if widget.get() != formatted:
            widget.delete(0, 'end')
            widget.insert(0, formatted)

    def center_window(self, window, width, height):
        window.update_idletasks()
        sw, sh = window.winfo_screenwidth(), window.winfo_screenheight()
        window.geometry(f"{width}x{height}+{(sw-width)//2}+{(sh-height)//2}")

    def toggle_password(self):
        if self.show_pwd:
            self.pass_entry.configure(show="•")
            self.eye_btn.configure(text="👁")
        else:
            self.pass_entry.configure(show="")
            self.eye_btn.configure(text="✕")
        self.show_pwd = not self.show_pwd

    def show_error(self, message):
        self.error_banner.configure(text=f"⚠ {message}", fg_color=T.DANGER_BORDER)

    def load_remember_me(self):
        if os.path.exists(self.REMEMBER_FILE):
            try:
                with open(self.REMEMBER_FILE, "r") as f:
                    data = json.load(f)
                    if "username" in data:
                        self.user_entry.delete(0, 'end')
                        self.user_entry.insert(0, data["username"])
                        self.remember_check.select()
            except Exception:
                pass

    def handle_remember_me(self, username):
        if str(self.remember_check.get()) == "1":
            try:
                with open(self.REMEMBER_FILE, "w") as f:
                    json.dump({"username": username}, f)
            except Exception:
                pass
        else:
            if os.path.exists(self.REMEMBER_FILE):
                os.remove(self.REMEMBER_FILE)

    def login(self, event=None):
        if self.login_button.cget("state") == "disabled":
            return
        self.login_button.configure(state="disabled", text="Authenticating...")
        self.update_idletasks()

        username = self.user_entry.get().strip()
        password = self.pass_entry.get()            # [RBAC] never stripped: a trailing space is part of the password

        try:
            # [RBAC][CONCURRENCY] status + role + lockout are decided in MySQL; Locked/Archived/Inactive accounts and Workers
            # are refused; the failed-attempt counter is committed before the refusal.
            user = auth_service.login(username, password)
        except auth_service.AuthError as e:
            self.show_error(str(e))
            if e.locked:
                if "Maximum" in str(e):
                    messagebox.showwarning("Account Locked", "Too many failed attempts. Your account has been locked. "
                                           "Please request a password reset.", parent=self)
                self.login_button.configure(state="disabled", text="Locked")
            else:
                self.login_button.configure(state="normal", text="Login")
            return
        except Exception as e:
            self.show_error(friendly_message(e))
            self.login_button.configure(state="normal", text="Login")
            return

        self.handle_remember_me(username)
        self.show_loading_screen(user)

    def show_loading_screen(self, user):
        self.withdraw()
        load_win = ctk.CTkToplevel(self)
        self.center_window(load_win, 460, 260)
        load_win.overrideredirect(True)
        load_win.configure(fg_color=T.PRIMARY)
        ctk.CTkLabel(load_win, text="CHAMPION FINE TOOLING",
                     font=T.font(20, "bold"), text_color=T.ON_PRIMARY).pack(pady=(70, 4))
        ctk.CTkLabel(load_win, text="Opening your dashboard", font=T.font(14), text_color=T.GREEN_TINT).pack()
        progress = ctk.CTkProgressBar(
            load_win, width=300, height=3, corner_radius=0, fg_color=T.PRIMARY_HOVER, progress_color=T.ACCENT)
        progress.pack(pady=(44, 0))
        progress.configure(mode="indeterminate")
        progress.start()

        def open_dashboard():
            try:
                start_session(user['user_id'])
                log_action(user['user_id'], "Login", "Authentication", f"User '{user['full_name']}' logged in.")
            except Exception as e:
                print(f"Failed to log login action: {e}")
            progress.stop()
            load_win.destroy()
            self.launch_dashboard(user)

        load_win.after(80, open_dashboard)

    def launch_dashboard(self, user):
        try:
            dashboard = DashboardApp(self, user_info=user)
            self.center_window(dashboard, 1350, 850)
            self.login_button.configure(state="normal", text="Login")
            
            # Re-enable inputs if it was logged out correctly previously
            self.user_entry.configure(state="normal")
            self.pass_entry.configure(state="normal")
            
            if self.remember_check.get() == 0:
                self.user_entry.delete(0, 'end')
            self.pass_entry.delete(0, 'end')
        except Exception as e:
            self.show_error(friendly_message(e))
            self.deiconify()
            self.login_button.configure(state="normal", text="Login")

    def open_forgot_username(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Forgot Username")
        self.center_window(dialog, 450, 300)
        dialog.configure(fg_color=T.BG)
        dialog.attributes("-topmost", True)
        dialog.grab_set()
        main_frame = C.card(dialog, 
                                  border_width=1)
        main_frame.pack(pady=20, padx=20, fill="both", expand=True)
        content = ctk.CTkFrame(main_frame, fg_color="transparent")
        content.place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(content, text="RETRIEVE USERNAME",
                     font=T.font(14, "bold"), text_color=T.TEXT).pack(anchor="w", padx=10, pady=(10, 5))
        ctk.CTkLabel(content,
                     text="Enter your registered email address to\nretrieve your Employee ID.",
                     font=T.font(12), text_color=T.TEXT_MUTED, justify="left").pack(anchor="w", padx=10, pady=(0, 15))
        email_entry = C.field(content, placeholder_text="Registered Email",
                                   width=340)
        email_entry.pack(padx=10, pady=(0, 15))

        def retrieve():
            email_val = email_entry.get().strip()
            if not email_val:
                messagebox.showerror(
                    "Error", "Please enter your email.", parent=dialog)
                return
            try:
                # [UNHAPPY-PATH] identical reply whether or not the e-mail exists; the id is NEVER shown here.
                # A match creates a support ticket for an Admin, who contacts the person.
                reply = auth_service.request_username_help(email_val)
            except Exception as e:
                messagebox.showerror("Error", friendly_message(e), parent=dialog)
                return
            messagebox.showinfo("Request Received", reply, parent=dialog)
            dialog.destroy()

        btn_frame = ctk.CTkFrame(content, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=(0, 10))
        C.button(btn_frame, kind="primary", text="Retrieve Username", 
                      
                      command=retrieve).pack(side="left", expand=True, fill="x", padx=(0, 10))
        C.button(btn_frame, kind="secondary", text="Cancel", width=80, 
                      
                      command=dialog.destroy).pack(side="right")

    def open_forgot_password(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Request Password Reset")
        self.center_window(dialog, 450, 300)
        dialog.configure(fg_color=T.BG)
        dialog.attributes("-topmost", True)
        dialog.grab_set()

        main_frame = C.card(dialog, 
                                  border_width=1)
        main_frame.pack(pady=20, padx=20, fill="both", expand=True)
        content = ctk.CTkFrame(main_frame, fg_color="transparent")
        content.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(content, text="REQUEST PASSWORD RESET",
                     font=T.font(14, "bold"), text_color=T.TEXT).pack(anchor="w", padx=10, pady=(10, 5))
        ctk.CTkLabel(content,
                     text="Enter your Employee ID. A notification will be sent\nto the System Administrator to reset your password.",
                     font=T.font(12), text_color=T.TEXT_MUTED, justify="left").pack(anchor="w", padx=10, pady=(0, 15))

        emp_id_entry = C.field(content, placeholder_text="Employee ID (e.g. ADM-2026-001)",
                                    width=340)
        emp_id_entry.pack(padx=10, pady=(5, 15))
        emp_id_entry.bind("<KeyRelease>", lambda e: self.format_emp_id(e, emp_id_entry))

        def send_reset_request():
            e_id = emp_id_entry.get().strip()
            if not e_id:
                messagebox.showerror(
                    "Error", "Please enter your Employee ID.", parent=dialog)
                return
            try:
                reply = auth_service.request_password_reset(e_id)     # identical reply whether or not the id exists
            except Exception as e:
                messagebox.showerror("Error", friendly_message(e), parent=dialog)
                return
            messagebox.showinfo("Request Sent", reply, parent=dialog)
            dialog.destroy()

        btn_frame = ctk.CTkFrame(content, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=(0, 10))

        C.button(btn_frame, kind="danger", text="Send Request to Admin", 
                      command=send_reset_request).pack(side="left", expand=True, fill="x", padx=(0, 10))
        C.button(btn_frame, kind="secondary", text="Cancel", width=80, 
                      command=dialog.destroy).pack(side="right")

    def open_scanner(self):
        """Badge scan: the shared scanner window (worker thread, camera probing, reconnect) fills the ID box."""
        from views.scan_dialog import open_scan_dialog
        if getattr(self, "scanner_window", None) is not None:
            try:
                if self.scanner_window.winfo_exists():
                    return
            except Exception:
                pass

        def got(code):
            self.user_entry.delete(0, 'end')
            self.user_entry.insert(0, code)
            self.pass_entry.focus_set()
        self.scanner_window = open_scan_dialog(self, got, "Scan ID Badge")

    def close_scanner(self):
        w = getattr(self, "scanner_window", None)
        if w is not None:
            try:
                w.close()
            except Exception:
                pass

    def on_closing(self):
        if messagebox.askyesno("Exit Application", "Close the entire system?"):
            self.close_scanner()
            os._exit(0)


if __name__ == "__main__":
    from ui.intro import run_startup
    app = LoginApp()
    run_startup(app)                  # splash (about 1.5 s), the four-slide intro on the first launch, then the login window
    app.mainloop()
