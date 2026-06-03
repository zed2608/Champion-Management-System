import os
import shutil
import customtkinter as ctk
from tkinter import filedialog, messagebox
from PIL import Image, ImageDraw, ImageFont
from database import get_connection, generate_id_badge
import re
import bcrypt
import qrcode

class ProfileView(ctk.CTkFrame):
    def __init__(self, parent, user_info, dashboard_app):
        super().__init__(parent, fg_color="transparent")

        self.user_info = user_info
        self.dashboard = dashboard_app
        self.db_conn = get_connection()

        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(self, text="PROFILE", font=("Inter", 24, "bold"), text_color="#1A1A1A").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 20))

        self.build_left_card()
        self.build_right_cards()

    def build_left_card(self):
        if hasattr(self, 'left_card'):
            self.left_card.destroy()

        self.left_card = ctk.CTkFrame(self, fg_color="white", corner_radius=10)
        self.left_card.grid(row=1, column=0, sticky="nsew", padx=(0, 10))

        self.pic_label = ctk.CTkLabel(self.left_card, text="", cursor="hand2")
        self.pic_label.pack(pady=(40, 5))
        self.pic_label.bind("<Button-1>", lambda e: self.upload_picture())

        ctk.CTkLabel(self.left_card, text="Click to upload profile picture", font=(
            "Inter", 10), text_color="gray").pack()
        self.load_profile_picture()

        ctk.CTkLabel(self.left_card, text=self.user_info['full_name'], font=(
            "Inter", 18, "bold"), text_color="#1A1A1A").pack(pady=(20, 0))
        ctk.CTkLabel(self.left_card, text=self.user_info['role'], font=(
            "Inter", 12), text_color="green").pack()

        ctk.CTkButton(self.left_card, text="⎙ Print My ID QR Badge", fg_color="#3498DB", hover_color="#2980B9", font=(
            "Inter", 11, "bold"), command=self.print_id_badge).pack(pady=(15, 0))

        ctk.CTkFrame(self.left_card, height=1, fg_color="#E0E0E0").pack(
            fill="x", padx=30, pady=20)

        details = [
            ("Username", self.user_info['employee_id']),
            ("Employee ID", self.user_info['employee_id']),
            ("Email", self.user_info.get('email', 'N/A')),
            ("Role", self.user_info['role'])
        ]
        for label, val in details:
            row = ctk.CTkFrame(self.left_card, fg_color="transparent")
            row.pack(fill="x", padx=30, pady=5)
            ctk.CTkLabel(row, text=label, font=("Inter", 12),
                         text_color="gray").pack(side="left")
            ctk.CTkLabel(row, text=val, font=("Inter", 12, "bold"),
                         text_color="#1A1A1A").pack(side="right")

    def print_id_badge(self):
        try:
            emp_id = self.user_info['employee_id']
            emp_name = self.user_info['full_name']
            emp_role = self.user_info['role']

            file_path = generate_id_badge(emp_id, emp_name, emp_role)
            os.startfile(file_path)

        except Exception as e:
            messagebox.showerror("Error", f"Could not generate ID badge: {e}")

    def build_right_cards(self):
        right_container = ctk.CTkFrame(self, fg_color="transparent")
        right_container.grid(row=1, column=1, sticky="nsew", padx=(10, 0))
        
        # Ensures the right section fully expands dynamically
        right_container.grid_columnconfigure(0, weight=1)
        right_container.grid_rowconfigure(0, weight=0)
        right_container.grid_rowconfigure(1, weight=1)

        edit_card = ctk.CTkFrame(
            right_container, fg_color="white", corner_radius=10)
        edit_card.grid(row=0, column=0, sticky="nsew", pady=(0, 10))

        ctk.CTkLabel(edit_card, text="Edit Profile", font=(
            "Inter", 14, "bold"), text_color="#1A1A1A").pack(anchor="w", padx=30, pady=(20, 10))

        form_frame = ctk.CTkFrame(edit_card, fg_color="transparent")
        form_frame.pack(fill="both", expand=True, padx=30)
        form_frame.grid_columnconfigure(0, weight=1)
        form_frame.grid_columnconfigure(1, weight=1)

        self.entry_name = self.create_form_field(
            form_frame, "Full Name *", self.user_info['full_name'], 0, 0)
        user_entry = self.create_form_field(
            form_frame, "Username (Disabled)", self.user_info['employee_id'], 0, 1)
        user_entry.configure(state="disabled", fg_color="#F0F0F0")

        self.entry_email = self.create_form_field(
            form_frame, "Email *", self.user_info.get('email', ''), 1, 0)
        self.entry_dept = self.create_form_field(
            form_frame, "Department", "Operations (Default)", 1, 1)

        btn_frame = ctk.CTkFrame(edit_card, fg_color="transparent")
        btn_frame.pack(fill="x", padx=30, pady=20)

        ctk.CTkButton(btn_frame, text="Save Profile", fg_color="#1E4528", hover_color="#14301C", font=(
            "Inter", 12, "bold"), command=self.confirm_save).pack(side="left", padx=(0, 10))
        ctk.CTkButton(btn_frame, text="Change Password", fg_color="#F1C40F", hover_color="#D4AC0D",
                      text_color="black", font=("Inter", 12, "bold"), command=self.open_password_modal).pack(side="left")

        history_card = ctk.CTkFrame(
            right_container, fg_color="white", corner_radius=10)
        history_card.grid(row=1, column=0, sticky="nsew", pady=(10, 0))

        ctk.CTkLabel(history_card, text="My Borrowing History",
                     font=("Inter", 14, "bold"), text_color="#1A1A1A").pack(
            anchor="w", padx=30, pady=(20, 5))

        # --- THE FIX: Unified Grid Table Strategy ---
        self.history_scroll = ctk.CTkScrollableFrame(history_card, fg_color="transparent")
        self.history_scroll.pack(fill="both", expand=True, padx=20, pady=(5, 20))

        self._load_profile_history()

    def _load_profile_history(self):
        for w in self.history_scroll.winfo_children():
            w.destroy()

        # Inner frame bound to expand across the full width
        table_inner = ctk.CTkFrame(self.history_scroll, fg_color="transparent")
        table_inner.pack(fill="x", expand=True)

        headers = ["TRN", "Tool Name", "Borrow Date", "Return Date", "Status"]
        # Balanced weights to stretch cleanly across wide screens
        weights = [1, 3, 2, 2, 1]
        # Minimum sizes to prevent squishing when minimized
        min_sizes = [60, 160, 140, 140, 80]

        # Uniform configuration enforces strict alignment for both headers and rows
        for col, (w, min_w) in enumerate(zip(weights, min_sizes)):
            table_inner.grid_columnconfigure(col, weight=w, minsize=min_w, uniform="prof_cols")

        # Header Row
        for col, text in enumerate(headers):
            cell = ctk.CTkFrame(table_inner, fg_color="#1E4528", corner_radius=0)
            cell.grid(row=0, column=col, sticky="nsew", pady=(0, 2))
            lbl = ctk.CTkLabel(cell, text=text, font=("Inter", 11, "bold"), text_color="white", anchor="center")
            lbl.pack(fill="both", expand=True, padx=2, pady=10)

        user_id = self.user_info.get("user_id")
        if not user_id:
            return

        conn = get_connection()
        if not conn:
            return

        try:
            cursor = conn.cursor(dictionary=True)
            
            cursor.execute("""
                SELECT tr.transaction_id,
                       t.name as tool_name,
                       DATE_FORMAT(DATE_ADD(tr.borrow_date, INTERVAL 8 HOUR), '%b %d, %h:%i %p') as borrow_date,
                       IF(tr.return_date IS NOT NULL, DATE_FORMAT(DATE_ADD(tr.return_date, INTERVAL 8 HOUR), '%b %d, %h:%i %p'), '—') as return_date,
                       tr.status
                FROM transaction tr
                JOIN tool t ON tr.tool_id = t.tool_id
                WHERE tr.user_id = %s
                ORDER BY tr.borrow_date DESC
                LIMIT 30
            """, (user_id,))
            rows = cursor.fetchall()

            if not rows:
                ctk.CTkLabel(table_inner, text="No borrowing history found.", text_color="gray").grid(row=1, column=0, columnspan=len(headers), pady=20)
                return

            for i, row in enumerate(rows):
                vals = [
                    str(row["transaction_id"]),
                    row["tool_name"],
                    row["borrow_date"],
                    row["return_date"],
                    row["status"],
                ]
                r_idx = i + 1
                bg = "#F9FAFB" if i % 2 == 0 else "white"

                for col, val in enumerate(vals):
                    cell = ctk.CTkFrame(table_inner, fg_color=bg, corner_radius=0)
                    cell.grid(row=r_idx, column=col, sticky="nsew")

                    color = "#1A1A1A"
                    if col == 4:
                        color = "#D8000C" if val == "Active" else "#2ECC71"
                        
                    font_w = "bold" if col == 4 else "normal"

                    lbl = ctk.CTkLabel(cell, text=val, font=("Inter", 11, font_w), text_color=color, justify="center", anchor="center")
                    
                    # Responsive text wrapping to ensure everything remains visible when minimizing
                    def set_wrap(e, l=lbl, m=min_sizes[col]):
                        target_wrap = max(m - 10, e.width - 10)
                        if not hasattr(l, '_last_wrap') or abs(l._last_wrap - target_wrap) > 5:
                            l.configure(wraplength=target_wrap)
                            l._last_wrap = target_wrap
                    cell.bind("<Configure>", set_wrap)
                    
                    lbl.pack(fill="both", expand=True, padx=4, pady=12)

        except Exception as e:
            ctk.CTkLabel(table_inner, text=f"Error: {e}", text_color="red").grid(row=1, column=0, columnspan=len(headers), pady=10)
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    def create_form_field(self, parent, label_text, default_val, row, col):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=col, sticky="ew", padx=10, pady=10)
        ctk.CTkLabel(frame, text=label_text, font=("Inter", 12),
                     text_color="gray").pack(anchor="w")
        entry = ctk.CTkEntry(frame, height=35)
        entry.insert(0, default_val)
        entry.pack(fill="x", pady=(5, 0))
        return entry

    def load_profile_picture(self):
        pic_path = os.path.join(os.path.dirname(os.path.dirname(
            __file__)), "assets", "profiles", f"{self.user_info['employee_id']}.png")
        if not os.path.exists(pic_path):
            pic_path = os.path.join(os.path.dirname(
                os.path.dirname(__file__)), "assets", "logo.png")

        try:
            img = ctk.CTkImage(light_image=Image.open(
                pic_path), size=(120, 120))
            self.pic_label.configure(image=img)
        except Exception:
            self.pic_label.configure(text="No Image")

    def upload_picture(self):
        file_path = filedialog.askopenfilename(title="Select Profile Picture", filetypes=[
                                               ("Image Files", "*.png *.jpg *.jpeg")])
        if file_path:
            if messagebox.askyesno("Confirm Upload", "Set this image as your new profile picture?"):
                dest_dir = os.path.join(os.path.dirname(
                    os.path.dirname(__file__)), "assets", "profiles")
                os.makedirs(dest_dir, exist_ok=True)
                dest_path = os.path.join(
                    dest_dir, f"{self.user_info['employee_id']}.png")
                shutil.copy(file_path, dest_path)
                self.load_profile_picture()
                self.dashboard.refresh_topbar()
                messagebox.showinfo(
                    "Success", "Profile picture updated successfully.")

    def confirm_save(self):
        new_name = self.entry_name.get().strip()
        new_email = self.entry_email.get().strip()

        if not new_name or not new_email:
            messagebox.showwarning(
                "Validation Error", "Full Name and Email are required.")
            return

        if messagebox.askyesno("Confirm Update", "Are you sure you want to save these changes?"):
            try:
                cursor = self.db_conn.cursor()
                
                cursor.execute("SELECT user_id FROM user WHERE full_name = %s AND employee_id != %s", (new_name, self.user_info['employee_id']))
                if cursor.fetchone():
                    messagebox.showerror("Duplicate", "A user with this full name already exists.")
                    return
                    
                cursor.execute("SELECT user_id FROM user WHERE email = %s AND employee_id != %s", (new_email, self.user_info['employee_id']))
                if cursor.fetchone():
                    messagebox.showerror("Duplicate", "A user with this email already exists.")
                    return

                cursor.execute("UPDATE user SET full_name = %s, email = %s WHERE employee_id = %s",
                               (new_name, new_email, self.user_info['employee_id']))
                self.db_conn.commit()

                self.user_info['full_name'] = new_name
                self.user_info['email'] = new_email
                self.dashboard.refresh_topbar()
                self.build_left_card()
                messagebox.showinfo("Success", "Profile updated securely.")
            except Exception as e:
                messagebox.showerror(
                    "Database Error", f"Failed to save profile: {e}")

    def open_password_modal(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Change Password")
        dialog.geometry("400x350")
        dialog.update_idletasks()
        x = int((dialog.winfo_screenwidth() / 2) - (400 / 2))
        y = int((dialog.winfo_screenheight() / 2) - (350 / 2))
        dialog.geometry(f"+{x}+{y}")
        dialog.configure(fg_color="white")
        dialog.attributes("-topmost", True)
        dialog.grab_set()

        ctk.CTkLabel(dialog, text="CHANGE PASSWORD", font=(
            "Inter", 14, "bold"), text_color="#1A1A1A").pack(anchor="w", padx=30, pady=(20, 10))

        curr_entry = ctk.CTkEntry(
            dialog, placeholder_text="Current Password", width=340, height=35, show="*")
        curr_entry.pack(padx=30, pady=(0, 10))
        new_entry = ctk.CTkEntry(
            dialog, placeholder_text="New Password", width=340, height=35, show="*")
        new_entry.pack(padx=30, pady=(0, 10))
        conf_entry = ctk.CTkEntry(
            dialog, placeholder_text="Confirm New Password", width=340, height=35, show="*")
        conf_entry.pack(padx=30, pady=(0, 20))

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(fill="x", padx=30)

        def process_pwd_change():
            curr_pwd = curr_entry.get()
            new_pwd = new_entry.get()
            conf_pwd = conf_entry.get()

            if not curr_pwd or not new_pwd or not conf_pwd:
                messagebox.showerror(
                    "Error", "All fields are required.", parent=dialog)
                return
            if new_pwd != conf_pwd:
                messagebox.showerror(
                    "Error", "New passwords do not match.", parent=dialog)
                return
            if len(new_pwd) < 8:
                messagebox.showerror(
                    "Weak Password", "Password must be at least 8 characters long.", parent=dialog)
                return

            if messagebox.askyesno("Confirm", "Change password?", parent=dialog):
                try:
                    cursor = self.db_conn.cursor(dictionary=True)
                    cursor.execute(
                        "SELECT password_hash FROM user WHERE employee_id = %s", (self.user_info['employee_id'],))
                    result = cursor.fetchone()

                    if result and bcrypt.checkpw(curr_pwd.encode('utf-8'), result['password_hash'].encode('utf-8')):
                        new_hashed = bcrypt.hashpw(
                            new_pwd.encode('utf-8'), bcrypt.gensalt())
                        cursor.execute("UPDATE user SET password_hash = %s WHERE employee_id = %s",
                                       (new_hashed.decode('utf-8'), self.user_info['employee_id']))
                        self.db_conn.commit()
                        messagebox.showinfo(
                            "Success", "Password updated successfully!", parent=dialog)
                        dialog.destroy()
                    else:
                        messagebox.showerror(
                            "Error", "Incorrect current password.", parent=dialog)
                except Exception as e:
                    messagebox.showerror(
                        "Database Error", f"Failed to update password: {e}", parent=dialog)
                finally:
                    cursor.close()

        ctk.CTkButton(btn_frame, text="Change Password", fg_color="#1E4528", hover_color="#14301C",
                      command=process_pwd_change).pack(side="left", expand=True, fill="x", padx=(0, 10))
        ctk.CTkButton(btn_frame, text="Cancel", width=80, fg_color="#E0E0E0", text_color="black",
                      hover_color="#CCCCCC", command=dialog.destroy).pack(side="right")