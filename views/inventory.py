import customtkinter as ctk
from views.ui_thread import UiMixin
from tkinter import messagebox
from database import get_connection, log_action
import os
import tempfile
import qrcode
from PIL import Image, ImageDraw, ImageFont
import difflib
import threading
import cv2
from pyzbar.pyzbar import decode, ZBarSymbol
from datetime import datetime
from services.validators import fmt_qty
from services.errors import friendly_message
from services.paging import fetch_page
from services.validators import like_pattern
from views.paged_table import PagedTable
from services import inventory_service as inv_svc


class InventoryView(UiMixin, ctk.CTkFrame):
    def __init__(self, parent, user_info=None, navigate_to=None, highlight_low_stock=False, highlight_tool_id=None, *args, **kwargs):
        super().__init__(parent, fg_color="transparent", *args, **kwargs)
        self._ui_init()

        self.user_info = user_info or {}
        self.navigate_to = navigate_to
        self.highlight_low_stock = highlight_low_stock
        self.highlight_tool_id = highlight_tool_id

        # 1. Main Wrapper Expansion
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)

        self.tool_hash_table = {}

        self.build_top_bar()
        self.build_main_table()
        self.load_inventory_data()

    def build_top_bar(self):
        top_bar = ctk.CTkFrame(self, fg_color="transparent")
        top_bar.grid(row=0, column=0, sticky="ew", padx=20, pady=(10, 15))

        ctk.CTkLabel(top_bar, text="Inventory Catalog", font=(
            "Inter", 16, "bold"), text_color="#1E4528").pack(side="left")

    def open_add_item_modal(self):
        self.add_modal = ctk.CTkToplevel(self)
        self.add_modal.title("Add New Item")
        self.add_modal.geometry("500x700")
        self.add_modal.configure(fg_color="white")
        self.add_modal.attributes("-topmost", True)
        self.add_modal.grab_set()

        self.add_modal.update_idletasks()
        x = (self.add_modal.winfo_screenwidth() // 2) - (500 // 2)
        y = (self.add_modal.winfo_screenheight() // 2) - (700 // 2)
        self.add_modal.geometry(f"500x700+{x}+{y}")

        form_card = ctk.CTkScrollableFrame(
            self.add_modal, fg_color="white", corner_radius=0)
        form_card.pack(fill="both", expand=True)

        ctk.CTkLabel(form_card, text="Add New Item", font=(
            "Inter", 16, "bold"), text_color="#1A1A1A").pack(anchor="w", padx=20, pady=(20, 10))

        row_type = ctk.CTkFrame(form_card, fg_color="transparent")
        row_type.pack(fill="x", padx=20, pady=(5, 10))
        row_type.grid_columnconfigure(0, weight=1)
        row_type.grid_columnconfigure(1, weight=1)

        t_frame = ctk.CTkFrame(row_type, fg_color="transparent")
        t_frame.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        ctk.CTkLabel(t_frame, text="Item Type *", font=("Inter",
                     11, "bold"), text_color="#1E4528").pack(anchor="w")
        self.type_menu = ctk.CTkOptionMenu(t_frame, values=[
                                           "Equipment", "Consumable"], fg_color="#E8F8F5", text_color="black")
        self.type_menu.pack(fill="x", pady=(5, 0))

        uom_frame = ctk.CTkFrame(row_type, fg_color="transparent")
        uom_frame.grid(row=0, column=1, sticky="ew", padx=(5, 0))
        ctk.CTkLabel(uom_frame, text="Unit (UoM) *", font=("Inter",
                     11, "bold"), text_color="#1E4528").pack(anchor="w")
        self.uom_menu = ctk.CTkOptionMenu(uom_frame, values=[
                                          "pcs", "boxes", "sets", "kg", "rolls", "packs", "liters", "meters", "feet"], fg_color="#E8F8F5", text_color="black")
        self.uom_menu.pack(fill="x", pady=(5, 0))

        ctk.CTkLabel(form_card, text="💡 Consumables (e.g. boxes of nails) support fractional returns. (e.g., return 0.5 for half box).", font=(
            "Inter", 10), text_color="gray", justify="left", wraplength=300).pack(anchor="w", padx=20, pady=(0, 10))

        ctk.CTkLabel(form_card, text="Product Name *", font=("Inter",
                     11, "bold"), text_color="#1A1A1A").pack(anchor="w", padx=20)
        self.name_entry = ctk.CTkEntry(
            form_card, placeholder_text="e.g., #2 Nails (Box)")
        self.name_entry.pack(fill="x", padx=20, pady=(5, 10))

        ctk.CTkLabel(form_card, text="Description", font=(
            "Inter", 11, "bold"), text_color="#1A1A1A").pack(anchor="w", padx=20)
        self.desc_entry = ctk.CTkEntry(
            form_card, placeholder_text="Brief details about the item...")
        self.desc_entry.pack(fill="x", padx=20, pady=(5, 10))

        ctk.CTkLabel(form_card, text="Category *", font=("Inter", 11,
                     "bold"), text_color="#1A1A1A").pack(anchor="w", padx=20)
        self.cat_menu = ctk.CTkComboBox(
            form_card, values=["Loading..."], fg_color="#F9FAFB", text_color="black")
        self.cat_menu.pack(fill="x", padx=20, pady=(5, 10))

        ctk.CTkLabel(form_card, text="Supplier", font=(
            "Inter", 11, "bold"), text_color="#1A1A1A").pack(anchor="w", padx=20)
        self.sup_menu = ctk.CTkComboBox(
            form_card, values=["Loading..."], fg_color="#F9FAFB", text_color="black")
        self.sup_menu.pack(fill="x", padx=20, pady=(5, 10))

        row_frame = ctk.CTkFrame(form_card, fg_color="transparent")
        row_frame.pack(fill="x", padx=20, pady=(5, 10))
        row_frame.grid_columnconfigure(0, weight=1)
        row_frame.grid_columnconfigure(1, weight=1)

        p_frame = ctk.CTkFrame(row_frame, fg_color="transparent")
        p_frame.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        ctk.CTkLabel(p_frame, text="Price", font=(
            "Inter", 12, "bold"), text_color="#1A1A1A").pack(anchor="w")
        self.price_entry = ctk.CTkEntry(
            p_frame, placeholder_text="0.00", height=36)
        self.price_entry.pack(fill="x", pady=(5, 0))

        q_frame = ctk.CTkFrame(row_frame, fg_color="transparent")
        q_frame.grid(row=0, column=1, sticky="ew", padx=(5, 0))
        ctk.CTkLabel(q_frame, text="Quantity *", font=("Inter", 12,
                     "bold"), text_color="#1A1A1A").pack(anchor="w")
        self.qty_entry = ctk.CTkEntry(q_frame, placeholder_text="0", height=36)
        self.qty_entry.pack(fill="x", pady=(5, 0))

        ctk.CTkLabel(form_card, text="Storage Location", font=(
            "Inter", 12, "bold"), text_color="#1A1A1A").pack(anchor="w", padx=20)
        self.loc_entry = ctk.CTkEntry(
            form_card, placeholder_text="e.g., Shelf A1", height=36)
        self.loc_entry.pack(fill="x", padx=20, pady=(5, 20))

        self.name_entry.bind("<Return>", lambda e: self.desc_entry.focus_set())
        self.desc_entry.bind(
            "<Return>", lambda e: self.price_entry.focus_set())
        self.price_entry.bind("<Return>", lambda e: self.qty_entry.focus_set())
        self.qty_entry.bind("<Return>", lambda e: self.loc_entry.focus_set())
        self.loc_entry.bind("<Return>", lambda e: self.validate_and_save())

        btn_row = ctk.CTkFrame(form_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(10, 20))
        btn_row.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkButton(btn_row, text="Save Item", height=40, fg_color="#1E4528", hover_color="#14301C", font=(
            "Inter", 13, "bold"), command=self.validate_and_save).grid(row=0, column=0, padx=(0, 5), sticky="ew")
        ctk.CTkButton(btn_row, text="Cancel", height=40, fg_color="#E0E0E0", text_color="black", hover_color="#CCCCCC", font=(
            "Inter", 13, "bold"), command=self.add_modal.destroy).grid(row=0, column=1, padx=(5, 0), sticky="ew")

        self.name_entry.focus_set()
        self.load_dynamic_dropdowns()

    def load_dynamic_dropdowns(self):
        conn = get_connection()
        if not conn:
            return
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT category FROM tool WHERE category IS NOT NULL AND category != 'Uncategorized' AND category != ''")
            cats = [row[0] for row in cursor.fetchall()]

            cursor.execute(
                "SELECT DISTINCT supplier FROM tool WHERE supplier IS NOT NULL AND supplier != 'N/A' AND supplier != ''")
            sups = [row[0] for row in cursor.fetchall()]

            if not cats:
                cats = ["Tools", "Measuring", "Power Tools", "Consumables"]
            if not sups:
                sups = ["ACME", "Global Tooling"]

            if hasattr(self, 'cat_menu') and self.cat_menu.winfo_exists():
                self.cat_menu.configure(values=cats)
                self.cat_menu.set("Type or select...")
            if hasattr(self, 'sup_menu') and self.sup_menu.winfo_exists():
                self.sup_menu.configure(values=sups)
                self.sup_menu.set("Type or select...")
        except Exception as e:
            print(f"Dropdown Load Error: {e}")
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    def build_main_table(self):
        table_card = ctk.CTkFrame(self, fg_color="white", corner_radius=10)
        table_card.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 20))
        table_card.grid_columnconfigure(0, weight=1)
        table_card.grid_rowconfigure(1, weight=1)

        search_frame = ctk.CTkFrame(table_card, fg_color="transparent")
        search_frame.pack(fill="x", padx=20, pady=(20, 10))

        self.search_var = ctk.StringVar()
        self.search_entry = ctk.CTkEntry(
            search_frame, placeholder_text="Universal search (Name, Tag, ID, Supplier, Loc, Desc)...", width=350, height=38, textvariable=self.search_var)
        self.search_entry.pack(side="left", padx=(0, 10))

        self._search_timer = None
        def on_search_change(*args):
            if self._search_timer:
                self.after_cancel(self._search_timer)
            self._search_timer = self.after(300, self.perform_search)
        self.search_var.trace_add("write", on_search_change)

        self.sort_menu = ctk.CTkOptionMenu(search_frame, values=["Most Recent", "Oldest", "A-Z (Name)", "Z-A (Name)", "PID (Low-High)", "Needs Tag", "Already Tagged"],
                                           width=140, height=38, fg_color="#F9FAFB", text_color="black", command=lambda e: self.perform_search())
        self.sort_menu.pack(side="left", padx=(0, 10))

        is_staff = self.user_info.get("role", "").lower() == "staff"

        if not is_staff:
            ctk.CTkButton(search_frame, text="+ Add New Item", width=120, height=38, fg_color="#1E4528", hover_color="#14301C",
                          font=("Inter", 12, "bold"), command=self.open_add_item_modal).pack(side="right", padx=(10, 0))
            
        ctk.CTkButton(search_frame, text="📷 Scan & Test QR", width=140, height=38, fg_color="#8E44AD", hover_color="#732D91", 
                      font=("Inter", 12, "bold"), command=self.open_test_scanner).pack(side="right", padx=(10, 0))
        
        self.batch_print_btn = ctk.CTkButton(search_frame, text="⎙ Batch Print Tags", width=140, height=38, fg_color="#F1C40F", hover_color="#D4AC0D", text_color="black", font=("Inter", 12, "bold"), command=self.execute_batch_print)
        self.batch_print_btn.pack(side="right", padx=(10, 0))

        hint_text = ("💡 Click a row to View  ·  tick ☑ tagged items, then Batch Print Tags" if is_staff
                     else "💡 Click a row to View/Edit  ·  tick ☑ tagged items, then Batch Print Tags")
        ctk.CTkLabel(search_frame, text=hint_text,
                     font=("Inter", 12, "italic"), text_color="gray").pack(side="right", padx=10)

        self.data_scroll = ctk.CTkScrollableFrame(
            table_card, fg_color="transparent")
        self.data_scroll.pack(fill="both", expand=True, padx=20, pady=(5, 20))
        
    def toggle_print_selection(self, pid, value):
        if value == "on":
            self.selected_for_print.add(pid)
        else:
            self.selected_for_print.discard(pid)

    def execute_batch_print(self):
        if not hasattr(self, 'selected_for_print') or not self.selected_for_print:
            messagebox.showwarning("No Items Selected", "Please select at least one item with an assigned Tag ID by clicking its checkbox.", parent=self.winfo_toplevel())
            return
            
        try:
            canvas_width = 850
            canvas_height = 1100
            
            conn = get_connection()
            if not conn: return
            
            items = []
            try:
                cursor = conn.cursor(dictionary=True)
                placeholders = ', '.join(['%s'] * len(self.selected_for_print))
                query = f"SELECT tool_id, name, location, `condition`, tag_id FROM tool WHERE tool_id IN ({placeholders})"
                cursor.execute(query, tuple(self.selected_for_print))
                items = cursor.fetchall()
            finally:
                if conn.is_connected():
                    cursor.close()
                    conn.close()

            if not items:
                return

            # A4 at 300 DPI
            canvas_width = 2480
            canvas_height = 3508
            
            canvas = Image.new('RGB', (canvas_width, canvas_height), 'white')
            draw = ImageDraw.Draw(canvas)
            try:
                font = ImageFont.truetype("arialbd.ttf", 36)
                font_small = ImageFont.truetype("arial.ttf", 28)
            except IOError:
                font = ImageFont.load_default()
                font_small = ImageFont.load_default()

            cols = 5
            rows = 6
            cell_w = 496 # 1.654 inches * 300 DPI
            cell_h = 584 # 1.948 inches * 300 DPI
            margin_x = (canvas_width - (cols * cell_w)) // 2
            margin_y = (canvas_height - (rows * cell_h)) // 2
            
            pages = []
            
            for i, item in enumerate(items):
                idx_on_page = i % (cols * rows)
                
                if idx_on_page == 0 and i > 0:
                    pages.append(canvas)
                    canvas = Image.new('RGB', (canvas_width, canvas_height), 'white')
                    draw = ImageDraw.Draw(canvas)
                
                col = idx_on_page % cols
                row = idx_on_page // cols
                x = margin_x + col * cell_w
                y = margin_y + row * cell_h
                
                # Draw border around the tag for easy cutting
                draw.rectangle([x, y, x + cell_w, y + cell_h], outline="black", width=2)
                
                qr_payload = f"Tag ID: {item['tag_id']}\nPID: {item['tool_id']}\nName: {item['name']}\nLocation: {item['location']}\nStatus: {item['condition']}"
                qr = qrcode.QRCode(version=1, box_size=10, border=1)
                qr.add_data(qr_payload)
                qr.make(fit=True)
                qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
                
                if qr_img.width > cell_w - 40:
                    qr_img = qr_img.resize((cell_w - 40, cell_w - 40), Image.NEAREST)
                
                qr_x = x + (cell_w - qr_img.width) // 2
                qr_y = y + 25
                canvas.paste(qr_img, (qr_x, qr_y))
                
                text_y = qr_y + qr_img.height + 15
                tag_text = f"Tag: {item['tag_id']}"
                name_text = f"{item['name'][:22]}" 
                
                bbox1 = draw.textbbox((0, 0), tag_text, font=font)
                draw.text((x + (cell_w - (bbox1[2] - bbox1[0])) // 2, text_y), tag_text, fill="black", font=font)
                bbox2 = draw.textbbox((0, 0), name_text, font=font_small)
                draw.text((x + (cell_w - (bbox2[2] - bbox2[0])) // 2, text_y + 45), name_text, fill="#555555", font=font_small)
                
            pages.append(canvas)

            temp_dir = tempfile.gettempdir()
            file_path = os.path.join(temp_dir, f"Batch_Print_Tags_{datetime.now().strftime('%H%M%S')}.pdf")
            
            if len(pages) > 1:
                pages[0].save(file_path, "PDF", resolution=300.0, save_all=True, append_images=pages[1:])
            else:
                pages[0].save(file_path, "PDF", resolution=300.0)
            
            import time
            time.sleep(0.5)
            os.startfile(file_path)

            self.selected_for_print.clear()
            self.load_inventory_data(self.search_entry.get().strip(), self.sort_menu.get(), keep_page=True)

        except Exception as e:
            messagebox.showerror("Print Error", f"Failed to generate batch print document.\n{e}", parent=self.winfo_toplevel())

    def open_test_scanner(self):
        from views.scan_dialog import open_scan_dialog
        if getattr(self, "_scan_win", None) is not None:
            try:
                if self._scan_win.winfo_exists():
                    return
            except Exception:
                pass
        self._scan_win = open_scan_dialog(self.winfo_toplevel(), self.fetch_and_display_scanned_tool, "Scan & Test QR")

    def fetch_and_display_scanned_tool(self, tag_id):
        conn = get_connection()
        if not conn: return
        
        try:
            cursor = conn.cursor()
            query = """
                SELECT t.tool_id, t.name, t.category, t.supplier, t.condition, t.location, IFNULL(i.quantity_available, 0)
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
                    f"Product Name:   {result[1]}\n"
                    f"Category:       {result[2]}\n"
                    f"Supplier:       {result[3]}\n"
                    f"Condition:      {result[4]}\n"
                    f"Storage Loc:    {result[5]}\n"
                    f"Qty Available:  {result[6]}\n"
                )
                if messagebox.askyesno("Tool Successfully Identified", info + "\nDo you want to open this item in the Inventory?", parent=self.winfo_toplevel()):
                    self.open_tool_modal(str(result[0]))
            else:
                messagebox.showwarning("Unknown Tag", f"The tag '{tag_id}' was scanned, but it is not linked to any active tool in the database.", parent=self.winfo_toplevel())
        except Exception as e:
            messagebox.showerror("Database Error", friendly_message(e), parent=self.winfo_toplevel())
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    INV_COLUMNS = [("Print", 1, 40), ("PID", 1, 50), ("Type", 2, 80), ("Name", 4, 150), ("Tag ID", 3, 120),
                   ("Qty Avail.", 2, 80), ("UoM", 1, 50), ("Location", 4, 150), ("Status", 2, 80)]

    def load_inventory_data(self, query=None, sort_type=None, keep_page=False):
        """(Re)load the table from page 1. The table is built once and its rows are recycled (views/paged_table.py)."""
        if not hasattr(self, 'selected_for_print'):
            self.selected_for_print = set()
        if query is None:
            query = getattr(self, "_inv_query", "")
        if sort_type is None:
            sort_type = getattr(self, "_inv_sort", "Most Recent")
        self._inv_query, self._inv_sort = query, sort_type
        if getattr(self, "_inv_table", None) is None or not self._inv_table.winfo_exists():
            for widget in self.data_scroll.winfo_children():
                widget.destroy()
            self._inv_table = PagedTable(
                self.data_scroll, self.INV_COLUMNS, fetch=self._fetch_inventory_page, cells=self._inventory_cells,
                row_bg=self._inventory_row_bg, cell_style=self._inventory_cell_style, on_row_click=lambda r: self.open_tool_modal(str(r['tool_id'])),
                on_loaded=self._inventory_loaded, empty_text="No inventory found.", font_size=12, cell_pady=8, uniform="inv_cols",
                checkbox={"col": 0, "state": self._inventory_check_state, "toggle": lambda r, on: self.toggle_print_selection(str(r['tool_id']), "on" if on else "off")})
            self._inv_table.pack(fill="x", expand=True)
        self._inv_table.reload(self._inv_table.page if keep_page else 0)

    def _fetch_inventory_page(self, page, size):
        """Runs in the worker thread (own connection, own cursor; reads the filter values saved on the main thread)."""
        query, sort_type = self._inv_query, self._inv_sort
        low_only = getattr(self, 'highlight_low_stock', False)
        where, params = "WHERE t.is_archived = 0", []
        if low_only:
            where += " AND i.minimum_stock > 0 AND i.quantity_available < i.minimum_stock"
        if query:
            where += (" AND (t.name LIKE %s OR CAST(t.tool_id AS CHAR) LIKE %s OR t.category LIKE %s OR t.item_type LIKE %s OR t.supplier LIKE %s"
                      " OR IFNULL(t.tag_id,'') LIKE %s OR t.location LIKE %s OR t.description LIKE %s)")
            params += [like_pattern(query)] * 8
        if sort_type == "Needs Tag":
            where += " AND (t.tag_id IS NULL OR t.tag_id = '')"
        elif sort_type == "Already Tagged":
            where += " AND t.tag_id IS NOT NULL AND t.tag_id != ''"
        order = {"Oldest": "t.tool_id ASC", "PID (Low-High)": "t.tool_id ASC", "A-Z (Name)": "t.name ASC, t.tool_id ASC",
                 "Z-A (Name)": "t.name DESC, t.tool_id DESC"}.get(sort_type, "t.tool_id DESC")
        select = """SELECT t.tool_id, IFNULL(t.item_type, 'Equipment') as item_type,
                           IFNULL(t.unit_of_measure, 'pcs') as uom,
                           t.name, IFNULL(t.description, '') as description, t.price,
                           IFNULL(i.quantity_available, 0) as qty_avail,
                           IFNULL(i.quantity_total, 0) as qty_tot,
                           IFNULL(i.minimum_stock, 0) as min_stock,
                           IFNULL(t.location, 'N/A') as base_location, t.`condition` as status,
                           IFNULL(t.category, 'Uncategorized') as category,
                           IFNULL(t.supplier, 'N/A') as supplier,
                           t.tag_id,
                           DATE_FORMAT(t.date_acquired, '%Y-%m-%d') as date_acquired,
                           (SELECT DATE_FORMAT(MAX(flagged_at), '%Y-%m-%d') FROM tool_issues WHERE tool_id = t.tool_id) as last_checked_date,
                           (SELECT p.name FROM transaction tr
                            JOIN projects p ON tr.project_id = p.project_id
                            WHERE tr.tool_id = t.tool_id AND tr.status = 'Active'
                            LIMIT 1) as active_project"""
        conn = get_connection()
        if not conn:
            raise ConnectionError("The database is not reachable.")
        try:
            cursor = conn.cursor(dictionary=True)
            return fetch_page(cursor, select, f"FROM tool t LEFT JOIN inventory i ON t.tool_id = i.tool_id {where}", params,
                              f"ORDER BY {order}", page, size)
        finally:
            if conn.is_connected():
                conn.close()

    def _inventory_loaded(self, rows, info):
        """Main thread: remember the shown rows by id (the row-click and the panel read them), open a requested item, log searches."""
        self.tool_hash_table.clear()
        for row in rows:
            row['location'] = row['base_location']
            self.tool_hash_table[str(row['tool_id'])] = row
        if getattr(self, 'highlight_tool_id', None):
            self.after(100, lambda t=self.highlight_tool_id: self.open_tool_modal(str(t)))
            self.highlight_tool_id = None
        uid = self.user_info.get("user_id")
        if uid and self._inv_query and not getattr(self, "_inv_search_logged", None) == (self._inv_query, self._inv_sort):
            self._inv_search_logged = (self._inv_query, self._inv_sort)
            log_action(uid, "Searched", "Inventory", f"Searched inventory: '{self._inv_query}' (Sort: {self._inv_sort})")

    @staticmethod
    def _is_low(row):
        return row.get('min_stock', 0) > 0 and row['qty_avail'] < row['min_stock']

    def _inventory_cells(self, row):
        avail = fmt_qty(row['qty_avail'])
        tot = fmt_qty(row['qty_tot'])
        display_loc = row['base_location']
        if row.get('active_project') and float(row['qty_avail']) < float(row['qty_tot']):
            display_loc = f"Deployed: {row['active_project']}"
        qty = f"⚠ {avail}/{tot}" if self._is_low(row) else f"{avail}/{tot}"
        return ["", str(row['tool_id']), row['item_type'], row['name'], row['tag_id'] or "Unassigned", qty, row['uom'], display_loc, row['status']]

    def _inventory_row_bg(self, row, i):
        if self._is_low(row):
            return "#FFF3F3" if i % 2 == 0 else "#FFEBEB"
        return "#F9FAFB" if i % 2 == 0 else "white"

    def _inventory_cell_style(self, row, col, val):
        low = self._is_low(row)
        if col == 7 and "Deployed:" in val:
            return "#2980B9", True
        if col == 2:
            return ("#D37F00" if val == "Consumable" else "#1A1A1A"), True
        if col == 4:
            return ("#D8000C" if val == "Unassigned" else "#1A1A1A"), True
        if col == 5:
            return ("#D8000C" if low else "#1A1A1A"), low
        return "#1A1A1A", False

    def _inventory_check_state(self, row):
        return bool(row['tag_id']), str(row['tool_id']) in self.selected_for_print

    def perform_search(self):
        self.load_inventory_data(
            self.search_entry.get().strip(), self.sort_menu.get())

    def reset_search(self):
        self.search_entry.delete(0, 'end')
        self.sort_menu.set("Most Recent")
        self.highlight_low_stock = False
        self.load_inventory_data("", "Most Recent")

    def validate_and_save(self):
        itype = self.type_menu.get()
        uom = self.uom_menu.get()
        cat = self.cat_menu.get()
        sup = self.sup_menu.get()
        name = self.name_entry.get().strip()
        desc = self.desc_entry.get().strip()
        loc = self.loc_entry.get().strip()

        if not name:
            messagebox.showerror(
                "Validation Error", "Product Name is required.", parent=self.add_modal)
            return

        if not cat or cat == "Type or select...":
            messagebox.showerror(
                "Validation Error", "Category is required.", parent=self.add_modal)
            return

        sup = "" if sup in ("", "Type or select...") else sup
        try:
            # name clash / typo check (read-only helper); the service re-checks the exact duplicate under lock
            exact, similar = inv_svc.find_similar_names(name)
        except Exception as e:
            messagebox.showerror("Validation Error", friendly_message(e), parent=self.add_modal)
            return
        if exact:
            messagebox.showerror("Duplicate Name", f"A product named '{name}' already exists in active inventory.", parent=self.add_modal)
            return
        if similar:
            sim_list = "\n".join([f"• {sn}" for sn in similar])
            msg = f"Wait! Similar product names already exist:\n\n{sim_list}\n\nAre you sure you want to add '{name}' as a new distinct item?"
            if not messagebox.askyesno("Similar Name Detected", msg, parent=self.add_modal):
                return
        try:
            # [RBAC][CONCURRENCY] Admin only; validated server-side (numbers, whole units for equipment, limits); one transaction
            res = inv_svc.add_item(self.user_info, name=name, category=cat, supplier=sup, description=desc, location=loc,
                                   item_type=itype, unit_of_measure=uom, price=self.price_entry.get(),
                                   quantity=self.qty_entry.get())
        except Exception as e:
            messagebox.showerror("Could not add item", friendly_message(e), parent=self.add_modal)
            return
        uid = self.user_info.get("user_id")
        if uid:
            log_action(uid, "Added", "Inventory",
                       f"Added new {itype}: '{name}' (PID: {res['tool_id']}), Qty: {fmt_qty(res['quantity'])} {uom}")
        messagebox.showinfo("Success", f"{itype} '{name}' added successfully.", parent=self.add_modal)
        self.add_modal.destroy()
        self.load_inventory_data()

    def open_tool_modal(self, lookup_id):
        data = self.tool_hash_table.get(str(lookup_id))
        if not data:
            conn = get_connection()
            if conn:
                try:
                    cursor = conn.cursor(dictionary=True)
                    cursor.execute("""
                        SELECT t.tool_id, IFNULL(t.item_type, 'Equipment') as item_type,
                               IFNULL(t.unit_of_measure, 'pcs') as uom,
                               t.name, IFNULL(t.description, '') as description, t.price,
                               IFNULL(i.quantity_available, 0) as qty_avail,
                               IFNULL(i.quantity_total, 0) as qty_tot,
                               IFNULL(i.minimum_stock, 0) as min_stock,
                               IFNULL(t.location, 'N/A') as location, t.`condition` as status,
                               IFNULL(t.category, 'Uncategorized') as category,
                               IFNULL(t.supplier, 'N/A') as supplier,
                               t.tag_id, t.is_archived,
                               DATE_FORMAT(t.date_acquired, '%Y-%m-%d') as date_acquired,
                               (SELECT DATE_FORMAT(MAX(flagged_at), '%Y-%m-%d') FROM tool_issues WHERE tool_id = t.tool_id) as last_checked_date
                        FROM tool t LEFT JOIN inventory i ON t.tool_id = i.tool_id
                        WHERE t.tool_id = %s
                    """, (lookup_id,))
                    data = cursor.fetchone()
                finally:
                    if conn.is_connected():
                        cursor.close()
                        conn.close()
            if not data:
                return

        is_arch = data.get('is_archived', 0)
        is_staff_modal = self.user_info.get("role", "").lower() == "staff"

        modal = ctk.CTkToplevel(self)
        modal.title(f"Manage Item: {lookup_id}")
        modal.geometry("550x750")
        modal.configure(fg_color="white")
        modal.attributes("-topmost", True)
        modal.update_idletasks()
        x = (modal.winfo_screenwidth() // 2) - (550 // 2)
        y = (modal.winfo_screenheight() // 2) - (750 // 2)
        modal.geometry(f"550x750+{x}+{y}")
        modal.grab_set()

        ctk.CTkLabel(modal, text=f"Item Details — PID: {lookup_id}", font=(
            "Inter", 16, "bold"), text_color="black").pack(pady=(20, 3))
        ctk.CTkLabel(modal, text=f"{data['name']}", font=(
            "Inter", 13), text_color="#555555").pack(pady=(0, 10))

        form_scroll = ctk.CTkScrollableFrame(modal, fg_color="transparent")
        form_scroll.pack(fill="both", expand=True, padx=25)

        def create_modal_row(parent, label, value):
            frame = ctk.CTkFrame(parent, fg_color="transparent")
            frame.pack(fill="x", pady=4)
            ctk.CTkLabel(frame, text=label, width=90, anchor="w", font=(
                "Inter", 11, "bold"), text_color="gray").pack(side="left")
            entry = ctk.CTkEntry(frame)
            entry.pack(side="left", fill="x", expand=True)
            entry.insert(0, str(value) if value else "")
            return entry

        type_frame = ctk.CTkFrame(form_scroll, fg_color="transparent")
        type_frame.pack(fill="x", pady=4)
        ctk.CTkLabel(type_frame, text="Item Type", width=90, anchor="w", font=(
            "Inter", 11, "bold"), text_color="gray").pack(side="left")
        type_menu = ctk.CTkOptionMenu(type_frame, values=[
                                      "Equipment", "Consumable"], fg_color="#F9FAFB", text_color="black")
        type_menu.pack(side="left", fill="x", expand=True)
        type_menu.set(data['item_type'])

        name_entry = create_modal_row(form_scroll, "Name", data['name'])
        desc_entry = create_modal_row(
            form_scroll, "Description", data['description'])
        cat_entry = create_modal_row(form_scroll, "Category", data['category'])
        sup_entry = create_modal_row(form_scroll, "Supplier", data['supplier'])

        # --- FIX C: Added Missing Price Field ---
        price_entry = create_modal_row(form_scroll, "Price", data['price'])

        qty_entry = create_modal_row(
            form_scroll, "Total Qty", f"{fmt_qty(data['qty_tot'])}")
        min_stock_entry = create_modal_row(
            form_scroll, "Min Stock", f"{fmt_qty(data.get('min_stock', 0))}")

        uom_frame = ctk.CTkFrame(form_scroll, fg_color="transparent")
        uom_frame.pack(fill="x", pady=4)
        ctk.CTkLabel(uom_frame, text="UoM", width=90, anchor="w", font=(
            "Inter", 11, "bold"), text_color="gray").pack(side="left")
        uom_menu = ctk.CTkOptionMenu(uom_frame, values=[
                                     "pcs", "boxes", "sets", "kg", "rolls", "packs", "liters", "meters", "feet"], fg_color="#F9FAFB", text_color="black")
        uom_menu.pack(side="left", fill="x", expand=True)
        uom_menu.set(data['uom'])

        loc_entry = create_modal_row(form_scroll, "Location", data['location'])

        date_acq_entry = create_modal_row(form_scroll, "Acquired On", data.get('date_acquired') or 'N/A')
        date_acq_entry.configure(state="disabled", fg_color="#F9FAFB")
        last_chk_entry = create_modal_row(form_scroll, "Last Checked", data.get('last_checked_date') or 'No Maintenance Record')
        last_chk_entry.configure(state="disabled", fg_color="#F9FAFB")

        ctk.CTkLabel(form_scroll, text="ℹ  For consumables (boxes, kg, sets): fractional quantities are supported.\n   e.g., set Total Qty to 2.5 if half a box was partially used.", font=(
            "Inter", 10), text_color="gray", justify="left", wraplength=450).pack(anchor="w", pady=(3, 5))

        status_frame = ctk.CTkFrame(form_scroll, fg_color="transparent")
        status_frame.pack(fill="x", pady=4)
        ctk.CTkLabel(status_frame, text="Condition", width=90, anchor="w", font=(
            "Inter", 11, "bold"), text_color="gray").pack(side="left")
        status_menu = ctk.CTkOptionMenu(status_frame, values=[
                                        "Good", "Needs Repair", "Damaged", "Lost"], fg_color="#F9FAFB", text_color="black")
        status_menu.pack(side="left", fill="x", expand=True)
        status_menu.set(data['status'])
        status_menu.configure(state="disabled")          # [RBAC] display only: conditions change through Maintenance
        ctk.CTkLabel(form_scroll, text="ℹ  Condition is set by Maintenance tickets (flag or resolve an issue there).",
                     font=("Inter", 10), text_color="gray", justify="left", wraplength=450).pack(anchor="w", pady=(0, 5))

        # --- TAGGING SECTION ---
        ctk.CTkFrame(form_scroll, height=2, fg_color="#E0E0E0").pack(
            fill="x", pady=15)
        ctk.CTkLabel(form_scroll, text="QR Tag Management", font=(
            "Inter", 13, "bold"), text_color="#1E4528").pack(anchor="w", pady=(0, 10))

        tag_row = ctk.CTkFrame(form_scroll, fg_color="transparent")
        tag_row.pack(fill="x", pady=4)
        ctk.CTkLabel(tag_row, text="Tag ID", width=90, anchor="w", font=(
            "Inter", 11, "bold"), text_color="gray").pack(side="left")
        tag_entry = ctk.CTkEntry(tag_row)
        tag_entry.pack(side="left", fill="x", expand=True)
        current_tag = data.get('tag_id') or ''
        tag_entry.insert(0, current_tag)

        # [RBAC] Admin: assign, relink, unlink.  Staff: may generate/assign a tag ONLY while the tool has none (and can always print).
        staff_can_tag = is_staff_modal and not current_tag
        tag_ui = {"save_btn": None}

        def generate_smart_tag():
            import re
            tag_entry.configure(state="normal")
            tag_entry.delete(0, 'end')
            clean = lambda v, fallback: re.sub(r"[^A-Z0-9]", "", str(v or "").upper())[:3] or fallback   # tags allow letters, digits, dashes
            smart_tag = f"TAG-{str(lookup_id).zfill(3)}-{clean(cat_entry.get(), 'GEN')}-{clean(sup_entry.get(), 'UNK')}"
            tag_entry.insert(0, smart_tag)
            update_preview()

        if not is_staff_modal or staff_can_tag:
            ctk.CTkButton(tag_row, text="↻ Auto-Gen", width=80, fg_color="#F1C40F", text_color="black",
                          hover_color="#D4AC0D", font=("Inter", 11, "bold"), command=generate_smart_tag).pack(side="left", padx=(5, 0))

        def save_tag():
            new_tag = tag_entry.get().strip()
            if not new_tag:
                return messagebox.showwarning("Tag ID", "Enter a tag ID, or use 'Unlink Current Tag'.", parent=modal)
            try:
                res = inv_svc.assign_tag(self.user_info, lookup_id, new_tag)     # [RBAC] Admin may relink; Staff only if untagged
            except Exception as e:
                return messagebox.showerror("Tag not saved", friendly_message(e), parent=modal)
            data['tag_id'] = res['tag_id']
            tag_entry.delete(0, 'end'); tag_entry.insert(0, res['tag_id'])
            uid = self.user_info.get("user_id")
            if uid and res['changed']:
                log_action(uid, "Edited", "Inventory", f"Linked tag {res['tag_id']} to '{res['name']}' (PID: {lookup_id})")
            if is_staff_modal:                                   # a Staff member cannot change it again
                tag_entry.configure(state="disabled")
                if tag_ui["save_btn"] is not None:
                    tag_ui["save_btn"].configure(state="disabled", text="Tag saved")
            update_preview()
            messagebox.showinfo("Success", "Tag successfully linked to tool.", parent=modal)
            self.load_inventory_data(keep_page=True)

        def unlink_tag():
            if messagebox.askyesno("Remove Tag", "Unlink the tag from this tool?", parent=modal):
                try:
                    res = inv_svc.unlink_tag(self.user_info, lookup_id)
                except Exception as e:
                    return messagebox.showerror("Tag not removed", friendly_message(e), parent=modal)
                tag_entry.delete(0, 'end')
                data['tag_id'] = ''
                uid = self.user_info.get("user_id")
                if uid:
                    log_action(uid, "Edited", "Inventory", f"Unlinked tag {res['old_tag']} from '{res['name']}' (PID: {lookup_id})")
                update_preview()
                self.load_inventory_data(keep_page=True)

        if not is_staff_modal or staff_can_tag:
            tag_btn_row = ctk.CTkFrame(form_scroll, fg_color="transparent")
            tag_btn_row.pack(fill="x", pady=10)
            tag_ui["save_btn"] = ctk.CTkButton(tag_btn_row, text="Save Tag Link", width=120, fg_color="#1E4528", hover_color="#14301C", font=(
                "Inter", 11, "bold"), command=save_tag)
            tag_ui["save_btn"].pack(side="left", expand=True, fill="x", padx=(0, 5))
            if not is_staff_modal:                               # unlinking is Admin only
                ctk.CTkButton(tag_btn_row, text="Unlink Current Tag", width=120, fg_color="white", border_width=1, border_color="#D8000C", text_color="#D8000C",
                              hover_color="#FFD2D2", font=("Inter", 11, "bold"), command=unlink_tag).pack(side="right", expand=True, fill="x", padx=(5, 0))
        elif is_staff_modal and current_tag:
            ctk.CTkLabel(form_scroll, text="This tool already has a tag. Only an administrator can change or remove it. You can still print it.",
                         font=("Inter", 10), text_color="gray", justify="left", wraplength=450).pack(anchor="w", pady=(0, 5))

        preview_frame = ctk.CTkFrame(
            form_scroll, fg_color="#F9FAFB", corner_radius=10)
        preview_frame.pack(fill="x", pady=10)

        ctk.CTkLabel(preview_frame, text="Live QR Preview", font=(
            "Inter", 11, "bold"), text_color="gray").pack(pady=(10, 5))
        qr_img_lbl = ctk.CTkLabel(preview_frame, text="")
        qr_img_lbl.pack(pady=5)

        def update_preview(event=None):
            current_val = tag_entry.get().strip()
            if not current_val:
                qr_img_lbl.configure(image=None, text="No Tag Assigned")
                return

            qr_payload = f"Tag ID: {current_val}\nPID: {lookup_id}\nName: {name_entry.get()}\nLocation: {loc_entry.get()}\nStatus: {status_menu.get()}"

            qr = qrcode.QRCode(version=1, box_size=4, border=1)
            qr.add_data(qr_payload)
            qr.make(fit=True)
            raw_img = qr.make_image(
                fill_color="#1E4528", back_color="#F9FAFB").get_image()

            qr_ctk_img = ctk.CTkImage(light_image=raw_img, size=(100, 100))
            qr_img_lbl.configure(image=qr_ctk_img, text="")

        tag_entry.bind("<KeyRelease>", update_preview)
        name_entry.bind("<KeyRelease>", update_preview)
        loc_entry.bind("<KeyRelease>", update_preview)
        status_menu.configure(command=lambda e: update_preview())
        update_preview()

        def execute_print():
            current_val = tag_entry.get().strip()
            if not current_val:
                return messagebox.showwarning("Warning", "No tag assigned to print.", parent=modal)
            try:
                modal.attributes("-topmost", False)
                qr_payload = f"Tag ID: {current_val}\nPID: {lookup_id}\nName: {name_entry.get()}\nLocation: {loc_entry.get()}\nStatus: {status_menu.get()}"

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
                    font = ImageFont.truetype("arial.ttf", 40)
                except IOError:
                    font = ImageFont.load_default()

                text_str = f"{current_val}"
                bbox = draw.textbbox((0, 0), text_str, font=font)
                text_w = bbox[2] - bbox[0]
                text_x = (canvas_width - text_w) // 2
                text_y = qr_img.height + 60

                draw.text((text_x, text_y), text_str, fill="black", font=font)

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
                    "Print Error", f"Failed to generate document.\n{e}", parent=modal)
                modal.attributes("-topmost", True)

        ctk.CTkButton(preview_frame, text="⎙ Generate Print File", fg_color="#1E4528", hover_color="#14301C", font=(
            "Inter", 11, "bold"), command=execute_print).pack(pady=(5, 10))
        # --- END TAGGING SECTION ---

        def execute_update():
            new_name = name_entry.get().strip()
            try:
                exact, similar = inv_svc.find_similar_names(new_name, exclude_tool_id=lookup_id)
            except Exception as e:
                return messagebox.showerror("Error", friendly_message(e), parent=modal)
            if exact:
                return messagebox.showerror("Duplicate Name", f"Another product named '{new_name}' already exists.", parent=modal)
            if similar and new_name.lower() != data['name'].lower():
                sim_list = "\n".join([f"• {sn}" for sn in similar])
                if not messagebox.askyesno("Similar Name Detected",
                                           f"Similar product names already exist:\n\n{sim_list}\n\nAre you sure you want to rename this to '{new_name}'?",
                                           parent=modal):
                    return
            if not messagebox.askyesno("Confirm Update", "Save all changes to the database?", parent=modal):
                return
            try:
                # [RBAC][CONCURRENCY] Admin only; the "cannot go below deployed" rule is checked against the LOCKED row
                inv_svc.update_item(self.user_info, lookup_id, name=name_entry.get(), category=cat_entry.get(),
                                    supplier=sup_entry.get(), description=desc_entry.get(), location=loc_entry.get(),
                                    item_type=type_menu.get(), unit_of_measure=uom_menu.get(), price=price_entry.get(),
                                    quantity=qty_entry.get(), min_stock=min_stock_entry.get(), tag_id=tag_entry.get())
            except Exception as e:
                return messagebox.showerror("Could not update", friendly_message(e), parent=modal)
            uid = self.user_info.get("user_id")
            if uid:
                log_action(uid, "Edited", "Inventory", f"Edited item '{name_entry.get()}' (PID: {lookup_id})")
            modal.destroy()
            self.load_inventory_data(keep_page=True)

        def execute_archive():
            if is_arch:
                msg = "Restore this item to active inventory?"
            else:
                msg = "Archive this item? It will be hidden from active inventory."
            if not messagebox.askyesno("Confirm", msg, parent=modal):
                return
            try:
                if is_arch:
                    inv_svc.restore_tool(self.user_info, lookup_id)
                else:
                    inv_svc.archive_tool(self.user_info, lookup_id)     # refused while units are deployed / in maintenance
            except Exception as e:
                return messagebox.showerror("Could not " + ("restore" if is_arch else "archive"), friendly_message(e), parent=modal)
            uid = self.user_info.get("user_id")
            action_str = "Restored" if is_arch else "Archived"
            if uid:
                log_action(uid, action_str, "Inventory", f"{action_str} item '{data['name']}'")
            modal.destroy()
            self.load_inventory_data(keep_page=True)
            dashboard = self.winfo_toplevel()
            if hasattr(dashboard, "show_toast"):
                dashboard.show_toast("✓ Tool restored successfully." if is_arch else "✓ Tool archived and passed to Maintenance.")

        # Modal Focus Traversal
        name_entry.bind("<Return>", lambda e: desc_entry.focus_set())
        desc_entry.bind("<Return>", lambda e: cat_entry.focus_set())
        cat_entry.bind("<Return>", lambda e: sup_entry.focus_set())
        # --- FIX C: Adjusted bindings to include Price Field ---
        sup_entry.bind("<Return>", lambda e: price_entry.focus_set())
        price_entry.bind("<Return>", lambda e: qty_entry.focus_set())
        qty_entry.bind("<Return>", lambda e: min_stock_entry.focus_set())
        min_stock_entry.bind("<Return>", lambda e: loc_entry.focus_set())
        loc_entry.bind("<Return>", lambda e: execute_update())

        btn_row = ctk.CTkFrame(modal, fg_color="transparent")
        btn_row.pack(side="bottom", fill="x", padx=25, pady=15)

        if is_staff_modal:
            # Staff: lock all fields — view-only. QR Print File button remains accessible.
            for entry_widget in [name_entry, desc_entry, cat_entry, sup_entry,
                                 price_entry, qty_entry, min_stock_entry, loc_entry] + ([] if staff_can_tag else [tag_entry]):
                entry_widget.configure(state="disabled")      # (an untagged tool's tag box stays open for Staff: see staff_can_tag)
            type_menu.configure(state="disabled")
            uom_menu.configure(state="disabled")
            status_menu.configure(state="disabled")
        else:
            ctk.CTkButton(btn_row, text="Update", fg_color="#F1C40F", text_color="black", hover_color="#D4AC0D", font=(
                "Inter", 11, "bold"), command=execute_update).pack(side="left", padx=5)

            arch_btn_text = "Restore" if is_arch else "Archive"
            ctk.CTkButton(btn_row, text=arch_btn_text, fg_color="#D3B8A7", text_color="black", hover_color="#BFA595", font=(
                "Inter", 11, "bold"), command=execute_archive).pack(side="left", padx=5)

        ctk.CTkButton(btn_row, text="Close", fg_color="#E0E0E0", text_color="black", hover_color="#CCCCCC", font=(
            "Inter", 11, "bold"), command=modal.destroy).pack(side="right", padx=5)

    def clear_form(self):
        self.type_menu.set("Equipment")
        self.uom_menu.set("pcs")
        self.cat_menu.set("Type or select...")
        self.sup_menu.set("Type or select...")
        self.name_entry.delete(0, 'end')
        self.desc_entry.delete(0, 'end')
        self.price_entry.delete(0, 'end')
        self.qty_entry.delete(0, 'end')
        self.loc_entry.delete(0, 'end')
