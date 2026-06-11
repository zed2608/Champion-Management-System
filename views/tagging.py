import customtkinter as ctk
from tkinter import messagebox
import qrcode
from PIL import Image, ImageDraw, ImageFont
from database import get_connection
import cv2
from pyzbar.pyzbar import decode, ZBarSymbol
import os
import tempfile


class TaggingView(ctk.CTkFrame):
    def __init__(self, parent, user_info=None):
        super().__init__(parent, fg_color="transparent")

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.user_info = user_info or {}
        self.is_staff = self.user_info.get("role", "").lower() == "staff"

        self.selected_tool_ids = set()
        self.chk_vars = {}

        self.build_main_panel()
        self.load_tagging_data()

    def build_main_panel(self):
        main_frame = ctk.CTkFrame(self, fg_color="white", corner_radius=10)
        main_frame.grid(row=0, column=0, padx=10, pady=0, sticky="nsew")

        header_row = ctk.CTkFrame(main_frame, fg_color="transparent")
        header_row.pack(fill="x", padx=20, pady=(20, 10))

        ctk.CTkLabel(header_row, text="Tag Management Hub", font=(
            "Inter", 16, "bold"), text_color="#1A1A1A").pack(side="left")
        ctk.CTkLabel(header_row, text="Click a tool to assign a tag, or use the scanner to test existing tags.", font=(
            "Inter", 11), text_color="gray").pack(side="left", padx=15, pady=(5, 0))

        search_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        search_frame.pack(fill="x", padx=20, pady=(10, 20))

        self.search_entry = ctk.CTkEntry(
            search_frame, placeholder_text="Universal Search (PID, Name, Cat, Sup, Tag)...", width=350)
        self.search_entry.pack(side="left")
        self.search_entry.bind("<Return>", lambda e: self.perform_search())

        self.filter_menu = ctk.CTkOptionMenu(search_frame, values=[
                                             "All Tools", "Needs Tag", "Already Tagged"], width=140, fg_color="#F9FAFB", text_color="black")
        self.filter_menu.pack(side="left", padx=10)

        ctk.CTkButton(search_frame, text="Search", width=80, fg_color="#F1C40F", hover_color="#D4AC0D",
                      text_color="black", font=("Inter", 11, "bold"), command=self.perform_search).pack(side="left")
        ctk.CTkButton(search_frame, text="↻ Reset", width=70, fg_color="#E0E0E0", text_color="black",
                      hover_color="#CCCCCC", font=("Inter", 11, "bold"), command=self.reset_search).pack(side="left", padx=10)

        self.scan_test_btn = ctk.CTkButton(search_frame, text="📷 Scan & Test QR", width=140, fg_color="#3498DB",
                                           hover_color="#2980B9", font=("Inter", 11, "bold"), command=self.open_test_scanner)
        self.scan_test_btn.pack(side="right", padx=10)

        self.print_batch_btn = ctk.CTkButton(search_frame, text="⎙ Print Selected QRs", width=150, fg_color="#2ECC71",
                                             hover_color="#27AE60", text_color="white", font=("Inter", 11, "bold"), command=self.print_selected_qrs)
        self.print_batch_btn.pack(side="right", padx=10)

        self.headers = ["Select", "PID", "Type", "Name",
                        "Qty", "Location", "Status", "Tag ID"]

        self.data_scroll = ctk.CTkScrollableFrame(
            main_frame, fg_color="transparent")
        self.data_scroll.pack(fill="both", expand=True, padx=20, pady=(10, 20))

    def toggle_select_all(self):
        if not hasattr(self, 'select_all_var'):
            return
        select_all = self.select_all_var.get()
        for tid, chk_var in self.chk_vars.items():
            chk_var.set(select_all)
            if select_all:
                self.selected_tool_ids.add(tid)
            else:
                self.selected_tool_ids.discard(tid)

    def load_tagging_data(self, query="", filter_type="All Tools"):
        for widget in self.data_scroll.winfo_children():
            widget.destroy()

        # Hard-Bounded Uniform Grid setup
        table_inner = ctk.CTkFrame(self.data_scroll, fg_color="transparent")
        table_inner.pack(fill="x", expand=True)

        # PERFECTED ALIGNMENT:
        # Strong emphasis on wider minimum widths for Name, Location, and Tag ID
        weights = [1, 1, 2, 3, 2, 3, 2, 3]
        min_sizes = [40, 50, 80, 160, 90, 130, 80, 140]

        for col, (w, min_w) in enumerate(zip(weights, min_sizes)):
            # 'uniform' guarantees proportional locking while resizing
            table_inner.grid_columnconfigure(
                col, weight=w, minsize=min_w, uniform="tag_cols")

        # Header Row
        self.select_all_var = ctk.BooleanVar(value=False)
        for col, text in enumerate(self.headers):
            cell = ctk.CTkFrame(
                table_inner, fg_color="#1E4528", corner_radius=0)
            cell.grid(row=0, column=col, sticky="nsew", pady=(0, 2))
            if col == 0:
                chk_all = ctk.CTkCheckBox(cell, text="", variable=self.select_all_var,
                                          command=self.toggle_select_all, width=20, border_color="white", checkmark_color="#1E4528")
                chk_all.pack(expand=True, pady=10)
            else:
                lbl = ctk.CTkLabel(cell, text=text, font=(
                    "Inter", 11, "bold"), text_color="white", anchor="center")
                lbl.pack(fill="both", expand=True, padx=2, pady=10)

        conn = get_connection()
        if not conn:
            return

        try:
            cursor = conn.cursor()

            base_query = """
                SELECT t.tool_id, IFNULL(t.item_type, 'Equipment'), t.name, IFNULL(t.category, 'Uncategorized'), IFNULL(t.supplier, 'N/A'), 
                       IFNULL(i.quantity_available, 0), IFNULL(i.quantity_total, 0), IFNULL(t.unit_of_measure, 'pcs'), IFNULL(t.location, 'N/A'), t.condition, IFNULL(t.tag_id, 'Unassigned'),
                       t.description, t.price
                FROM tool t
                LEFT JOIN inventory i ON t.tool_id = i.tool_id
                WHERE t.is_archived = 0
            """
            params = []

            if filter_type == "Needs Tag":
                base_query += " AND (t.tag_id IS NULL OR t.tag_id = '')"
            elif filter_type == "Already Tagged":
                base_query += " AND t.tag_id IS NOT NULL AND t.tag_id != ''"

            if query:
                base_query += " AND (t.name LIKE %s OR t.tool_id LIKE %s OR t.category LIKE %s OR t.supplier LIKE %s OR t.tag_id LIKE %s OR t.item_type LIKE %s)"
                params.extend([f"%{query}%"] * 6)

            cursor.execute(base_query, tuple(params))
            results = cursor.fetchall()

            if not results:
                ctk.CTkLabel(table_inner, text="No tools found matching the criteria.", text_color="gray").grid(
                    row=1, column=0, columnspan=len(self.headers), pady=20)
                return

            self.chk_vars.clear()
            for i, row_data in enumerate(results):
                tool_id, item_type, name, cat, sup, qty_avail, qty_tot, uom, loc, cond, tag, desc, price = row_data
                qty_str = f"{qty_avail:g}/{qty_tot:g} {uom}"
                display_data = ["", str(tool_id), str(item_type), str(
                    name), qty_str, str(loc), str(cond), str(tag)]
                full_data = [tool_id, name, desc, price,
                             qty_avail, loc, cond, tag, cat, sup]

                r_idx = i + 1
                bg = "#F9FAFB" if i % 2 == 0 else "white"

                for col, val in enumerate(display_data):
                    cell = ctk.CTkFrame(
                        table_inner, fg_color=bg, corner_radius=0, cursor="hand2")
                    cell.grid(row=r_idx, column=col, sticky="nsew")

                    if col == 0:
                        var = ctk.BooleanVar(
                            value=tool_id in self.selected_tool_ids)
                        self.chk_vars[tool_id] = var
                        def cmd(v=var, tid=tool_id): return self.selected_tool_ids.add(
                            tid) if v.get() else self.selected_tool_ids.discard(tid)
                        chk = ctk.CTkCheckBox(
                            cell, text="", variable=var, command=cmd, width=20)
                        chk.pack(expand=True, pady=10)
                    else:
                        txt_col = "#1A1A1A"
                        if col == 7 and val == "Unassigned":
                            txt_col = "#D8000C"
                        elif col == 2 and val == "Consumable":
                            txt_col = "#D37F00"

                        font_w = "bold" if (
                            col == 7 and val != "Unassigned") or col == 2 else "normal"

                        lbl = ctk.CTkLabel(cell, text=val, font=(
                            "Inter", 11, font_w), text_color=txt_col, justify="center", anchor="center", cursor="hand2")

                        lbl.configure(wraplength=min_sizes[col] - 10)
                        lbl.pack(fill="both", expand=True, padx=4, pady=12)

                        # Binds whole cell & text to open the modal
                        cell.bind("<Button-1>", lambda e,
                                  data=full_data: self.open_tag_manager(data))
                        lbl.bind("<Button-1>", lambda e,
                                 data=full_data: self.open_tag_manager(data))

        except Exception as e:
            messagebox.showerror(
                "Database Error", f"Failed to load tags: {e}", parent=self.winfo_toplevel())
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    def perform_search(self):
        query = self.search_entry.get().strip()
        filter_type = self.filter_menu.get()
        self.load_tagging_data(query, filter_type)

    def reset_search(self):
        self.search_entry.delete(0, 'end')
        self.filter_menu.set("All Tools")
        self.selected_tool_ids.clear()
        self.load_tagging_data()

    def print_selected_qrs(self):
        if not self.selected_tool_ids:
            messagebox.showwarning(
                "Warning", "No tools selected for batch printing.", parent=self.winfo_toplevel())
            return

        conn = get_connection()
        if not conn:
            return

        try:
            cursor = conn.cursor(dictionary=True)
            format_strings = ','.join(['%s'] * len(self.selected_tool_ids))
            cursor.execute(f"""
                SELECT tool_id, name, location, `condition`, tag_id
                FROM tool
                WHERE tool_id IN ({format_strings})
            """, tuple(self.selected_tool_ids))
            tools = cursor.fetchall()
        except Exception as e:
            messagebox.showerror("Database Error", str(e),
                                 parent=self.winfo_toplevel())
            return
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

        try:
            images = []
            for tool in tools:
                tag_id = tool['tag_id']
                if not tag_id:
                    continue

                qr_payload = f"Tag ID: {tag_id}\nPID: {tool['tool_id']}\nName: {tool['name']}\nLocation: {tool['location']}\nStatus: {tool['condition']}"
                print_qr = qrcode.QRCode(version=1, box_size=15, border=2)
                print_qr.add_data(qr_payload)
                print_qr.make(fit=True)
                qr_img = print_qr.make_image(
                    fill_color="black", back_color="white").convert("RGB")

                canvas_width = qr_img.width + 100
                canvas_height = qr_img.height + 150
                pil_canvas = Image.new(
                    'RGB', (canvas_width, canvas_height), 'white')

                offset_x = (canvas_width - qr_img.width) // 2
                pil_canvas.paste(qr_img, (offset_x, 30))

                draw = ImageDraw.Draw(pil_canvas)
                try:
                    font = ImageFont.truetype("arial.ttf", 30)
                except IOError:
                    font = ImageFont.load_default()

                text_str1 = f"{tag_id}"
                text_str2 = f"{tool['name']}"

                bbox1 = draw.textbbox((0, 0), text_str1, font=font)
                text_w1 = bbox1[2] - bbox1[0]
                text_x1 = (canvas_width - text_w1) // 2
                text_y1 = qr_img.height + 40

                bbox2 = draw.textbbox((0, 0), text_str2, font=font)
                text_w2 = bbox2[2] - bbox2[0]
                text_x2 = (canvas_width - text_w2) // 2
                text_y2 = text_y1 + 40

                draw.text((text_x1, text_y1), text_str1,
                          fill="black", font=font)
                draw.text((text_x2, text_y2), text_str2,
                          fill="black", font=font)

                images.append(pil_canvas)

            if not images:
                messagebox.showwarning(
                    "Warning", "Selected tools do not have Tag IDs assigned. Please assign tags first.", parent=self.winfo_toplevel())
                return

            temp_dir = tempfile.gettempdir()
            file_path = os.path.join(temp_dir, f"Batch_Print_Labels.pdf")
            images[0].save(file_path, "PDF", resolution=100.0,
                           save_all=True, append_images=images[1:])

            import time
            time.sleep(0.5)
            os.startfile(file_path)

        except Exception as e:
            messagebox.showerror(
                "Print Error", f"Failed to generate document.\n{e}", parent=self.winfo_toplevel())

    def open_test_scanner(self):
        try:
            cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        except:
            cap = cv2.VideoCapture(0)

        if not cap.isOpened():
            messagebox.showerror(
                "Camera Error", "No webcam detected.", parent=self.winfo_toplevel())
            return

        detected_tag = None
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            height, width, _ = frame.shape
            top_left = (int(width*0.25), int(height*0.3))
            bottom_right = (int(width*0.75), int(height*0.7))
            cv2.rectangle(frame, top_left, bottom_right, (0, 255, 0), 2)
            cv2.putText(frame, "Align QR Code inside box", (
                top_left[0], top_left[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            cv2.putText(frame, "Press 'Q' to Cancel", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

            detected_codes = decode(frame, symbols=[ZBarSymbol.QRCODE])
            for qr_code in detected_codes:
                raw_data = qr_code.data.decode('utf-8')
                if "Tag ID:" in raw_data:
                    first_line = raw_data.split('\n')[0]
                    detected_tag = first_line.replace("Tag ID: ", "").strip()
                else:
                    detected_tag = raw_data.strip()
                break

            cv2.imshow('Champion Scanner - Turbo Mode', frame)

            if detected_tag or cv2.waitKey(1) & 0xFF == ord('q'):
                break

        cap.release()
        cv2.destroyAllWindows()

        if detected_tag:
            self.fetch_and_display_scanned_tool(detected_tag)

    def fetch_and_display_scanned_tool(self, tag_id):
        conn = get_connection()
        if not conn:
            return

        try:
            cursor = conn.cursor()
            query = """
                SELECT t.name, t.category, t.supplier, t.condition, t.location, IFNULL(i.quantity_available, 0), IFNULL(i.quantity_total, 0), IFNULL(t.item_type, 'Equipment'), IFNULL(t.unit_of_measure, 'pcs')
                FROM tool t
                LEFT JOIN inventory i ON t.tool_id = i.tool_id
                WHERE t.tag_id = %s
            """
            cursor.execute(query, (tag_id,))
            result = cursor.fetchone()

            if result:
                info = (
                    f"✓ Tag Recognized: {tag_id}\n"
                    f"{'-'*40}\n"
                    f"Product Name:   {result[0]}\n"
                    f"Type:           {result[7]}\n"
                    f"Category:       {result[1]}\n"
                    f"Supplier:       {result[2]}\n"
                    f"Condition:      {result[3]}\n"
                    f"Storage Loc:    {result[4]}\n"
                    f"Qty:            {result[5]:g} / {result[6]:g} {result[8]}\n"
                )
                messagebox.showinfo(
                    "Tool Successfully Identified", info, parent=self.winfo_toplevel())
            else:
                messagebox.showwarning(
                    "Unknown Tag", f"The tag '{tag_id}' was scanned, but it is not linked to any active tool in the database.", parent=self.winfo_toplevel())
        except Exception as e:
            messagebox.showerror("Database Error", str(e),
                                 parent=self.winfo_toplevel())
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    def open_tag_manager(self, data):
        tool_id = data[0]
        tool_name = data[1]
        tool_loc = data[5]
        tool_cond = data[6]
        current_tag = "" if data[7] == "Unassigned" else data[7]
        tool_category = data[8]
        tool_supplier = data[9]

        modal = ctk.CTkToplevel(self)
        modal.title(f"Tag Manager: {tool_name}")
        modal.geometry("450x550")
        modal.configure(fg_color="white")
        modal.attributes("-topmost", True)
        modal.grab_set()

        modal.update_idletasks()
        x = int((modal.winfo_screenwidth() / 2) - (450 / 2))
        y = int((modal.winfo_screenheight() / 2) - (550 / 2))
        modal.geometry(f"+{x}+{y}")

        ctk.CTkLabel(modal, text=f"Manage Tag: {tool_name}", font=(
            "Inter", 16, "bold"), text_color="black").pack(pady=(20, 5))
        ctk.CTkLabel(modal, text=f"System ID: {tool_id}", font=(
            "Inter", 12), text_color="gray").pack(pady=(0, 20))

        form_frame = ctk.CTkFrame(modal, fg_color="transparent")
        form_frame.pack(fill="both", expand=True, padx=30)

        ctk.CTkLabel(form_frame, text="Assigned Tag ID / QR Code",
                     font=("Inter", 12, "bold"), text_color="#1A1A1A").pack(anchor="w")

        tag_row = ctk.CTkFrame(form_frame, fg_color="transparent")
        tag_row.pack(fill="x", pady=(5, 10))

        tag_entry = ctk.CTkEntry(
            tag_row, placeholder_text="Scan or enter Tag ID", height=35)
        tag_entry.pack(side="left", expand=True, fill="x", padx=(0, 5))
        if current_tag:
            tag_entry.insert(0, current_tag)

        def generate_smart_tag():
            tag_entry.delete(0, 'end')
            cat_prefix = str(tool_category)[:3].upper(
            ) if tool_category and tool_category != "None" else "GEN"
            sup_prefix = str(tool_supplier)[:3].upper(
            ) if tool_supplier and tool_supplier != "None" else "UNK"
            smart_tag = f"TAG-{str(tool_id).zfill(3)}-{cat_prefix}-{sup_prefix}"
            tag_entry.insert(0, smart_tag)
            update_preview()

        if not self.is_staff:
            ctk.CTkButton(tag_row, text="↻ Auto-Gen", width=80, height=35, fg_color="#F1C40F", text_color="black",
                          hover_color="#D4AC0D", font=("Inter", 11, "bold"), command=generate_smart_tag).pack(side="left", padx=(0, 5))

        def save_tag():
            new_tag = tag_entry.get().strip()
            if not new_tag:
                messagebox.showerror(
                    "Error", "Tag ID cannot be empty.", parent=modal)
                return

            conn = get_connection()
            if not conn:
                return
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT tool_id FROM tool WHERE tag_id = %s AND tool_id != %s", (new_tag, tool_id))
                if cursor.fetchone():
                    messagebox.showerror(
                        "Duplicate Tag", f"The Tag ID '{new_tag}' is already assigned to another tool!", parent=modal)
                    return

                cursor.execute(
                    "UPDATE tool SET tag_id = %s WHERE tool_id = %s", (new_tag, tool_id))
                conn.commit()
                messagebox.showinfo(
                    "Success", "Tag successfully linked to tool.", parent=modal)
                self.load_tagging_data()
            except Exception as e:
                messagebox.showerror("Database Error", str(e), parent=modal)
            finally:
                if conn.is_connected():
                    cursor.close()
                    conn.close()

        def clear_tag():
            if messagebox.askyesno("Remove Tag", "Are you sure you want to unlink the tag from this tool?", parent=modal):
                conn = get_connection()
                if not conn:
                    return
                try:
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE tool SET tag_id = NULL WHERE tool_id = %s", (tool_id,))
                    conn.commit()
                    tag_entry.delete(0, 'end')
                    update_preview()
                    self.load_tagging_data()
                    messagebox.showinfo(
                        "Success", "Tag removed.", parent=modal)
                except Exception as e:
                    pass
                finally:
                    if conn.is_connected():
                        cursor.close()
                        conn.close()

        if self.is_staff:
            tag_entry.configure(state="disabled")
        else:
            ctk.CTkButton(form_frame, text="Save Tag Link to Database", height=40, fg_color="#1E4528",
                          hover_color="#14301C", font=("Inter", 12, "bold"), command=save_tag).pack(fill="x", pady=(15, 5))

            if current_tag:
                ctk.CTkButton(form_frame, text="Unlink Current Tag", height=30, fg_color="white", border_width=1, border_color="#D8000C",
                              text_color="#D8000C", hover_color="#FFD2D2", font=("Inter", 11, "bold"), command=clear_tag).pack(fill="x", pady=5)

        preview_frame = ctk.CTkFrame(
            form_frame, fg_color="#F9FAFB", corner_radius=10)
        preview_frame.pack(fill="both", expand=True, pady=(20, 0))

        def update_preview():
            current_val = tag_entry.get().strip()
            if not current_val:
                return

            qr_payload = f"Tag ID: {current_val}\nPID: {tool_id}\nName: {tool_name}\nLocation: {tool_loc}\nStatus: {tool_cond}"

            qr = qrcode.QRCode(version=1, box_size=5, border=1)
            qr.add_data(qr_payload)
            qr.make(fit=True)
            raw_img = qr.make_image(
                fill_color="#1E4528", back_color="#F9FAFB").get_image()

            qr_ctk_img = ctk.CTkImage(light_image=raw_img, size=(120, 120))

            for widget in preview_frame.winfo_children():
                widget.destroy()

            ctk.CTkLabel(preview_frame, text="Live QR Preview", font=(
                "Inter", 11, "bold"), text_color="gray").pack(pady=(10, 5))
            ctk.CTkLabel(preview_frame, image=qr_ctk_img, text="").pack(pady=5)

            def execute_print():
                try:
                    modal.attributes("-topmost", False)

                    print_qr = qrcode.QRCode(version=1, box_size=15, border=2)
                    print_qr.add_data(qr_payload)
                    print_qr.make(fit=True)
                    qr_img = print_qr.make_image(
                        fill_color="black", back_color="white").convert("RGB")

                    canvas_width = qr_img.width + 100
                    canvas_height = qr_img.height + 150
                    canvas = Image.new(
                        'RGB', (canvas_width, canvas_height), 'white')

                    offset_x = (canvas_width - qr_img.width) // 2
                    canvas.paste(qr_img, (offset_x, 30))

                    draw = ImageDraw.Draw(canvas)
                    try:
                        font = ImageFont.truetype("arial.ttf", 30)
                    except IOError:
                        font = ImageFont.load_default()

                    text_str1 = f"{current_val}"
                    text_str2 = f"{tool_name}"

                    bbox1 = draw.textbbox((0, 0), text_str1, font=font)
                    text_w1 = bbox1[2] - bbox1[0]
                    text_x1 = (canvas_width - text_w1) // 2
                    text_y1 = qr_img.height + 40

                    bbox2 = draw.textbbox((0, 0), text_str2, font=font)
                    text_w2 = bbox2[2] - bbox2[0]
                    text_x2 = (canvas_width - text_w2) // 2
                    text_y2 = text_y1 + 40

                    draw.text((text_x1, text_y1), text_str1,
                              fill="black", font=font)
                    draw.text((text_x2, text_y2), text_str2,
                              fill="black", font=font)

                    temp_dir = tempfile.gettempdir()
                    safe_filename = "".join(
                        c for c in current_val if c.isalnum() or c in ('-', '_'))
                    file_path = os.path.join(
                        temp_dir, f"Print_Label_{safe_filename}.pdf")

                    canvas.save(file_path, "PDF", resolution=100.0)

                    import time
                    time.sleep(0.5)
                    os.startfile(file_path)

                except Exception as e:
                    messagebox.showerror(
                        "Print Error", f"Failed to open document viewer.\n{e}", parent=modal)
                    modal.attributes("-topmost", True)

            ctk.CTkButton(preview_frame, text="⎙ Print QR", width=140, height=35, fg_color="#1E4528",
                          hover_color="#14301C", font=("Inter", 12, "bold"), command=execute_print).pack(pady=(5, 10))

        tag_entry.bind("<KeyRelease>", lambda e: update_preview())
        update_preview()

        ctk.CTkButton(modal, text="Close", fg_color="#E0E0E0", text_color="black", hover_color="#CCCCCC", font=(
            "Inter", 11, "bold"), command=modal.destroy).pack(side="bottom", pady=20, padx=30, fill="x")
