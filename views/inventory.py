import customtkinter as ctk
from tkinter import messagebox
from database import get_connection, log_action
import os
import tempfile
import qrcode
from PIL import Image, ImageDraw, ImageFont
import difflib
import threading


class InventoryView(ctk.CTkFrame):
    def __init__(self, parent, user_info=None, navigate_to=None, highlight_low_stock=False, highlight_tool_id=None, *args, **kwargs):
        super().__init__(parent, fg_color="transparent", *args, **kwargs)

        self.user_info = user_info or {}
        self.navigate_to = navigate_to
        self.highlight_low_stock = highlight_low_stock
        self.highlight_tool_id = highlight_tool_id

        # 1. Main Wrapper Expansion
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)

        self.tool_hash_table = {}

        self._ensure_inventory_floats()
        self.build_top_tabs()

    def _ensure_inventory_floats(self):
        """Ensures that the database can actually store fractional quantities for consumables."""
        conn = get_connection()
        if conn:
            try:
                c = conn.cursor()
                c.execute(
                    "ALTER TABLE inventory MODIFY quantity_total FLOAT, MODIFY quantity_available FLOAT, MODIFY minimum_stock FLOAT")
                conn.commit()
            except Exception:
                pass
            finally:
                if conn.is_connected():
                    c.close()
                    conn.close()

    def build_top_tabs(self):
        top_bar = ctk.CTkFrame(self, fg_color="transparent")
        top_bar.grid(row=0, column=0, sticky="ew", padx=20, pady=(10, 15))

        ctk.CTkLabel(top_bar, text="Inventory", font=(
            "Inter", 16, "bold"), text_color="#1E4528").pack(side="left")

        tabs = ["📦 Inventory Catalog", "🏷️ Tag Management Hub"]
        self.tab_var = ctk.StringVar(value=tabs[0])

        self.seg_btn = ctk.CTkSegmentedButton(
            top_bar, values=tabs, variable=self.tab_var, command=self.switch_tab,
            fg_color="#F0F0F0", selected_color="#1E4528", selected_hover_color="#14301C"
        )
        self.seg_btn.pack(side="right")

        self.tab_content = ctk.CTkFrame(self, fg_color="transparent")
        self.tab_content.grid(
            row=1, column=0, sticky="nsew", padx=10, pady=(0, 20))

        self.tab_content.grid_columnconfigure(0, weight=1)
        self.tab_content.grid_rowconfigure(0, weight=1)

        self.switch_tab(tabs[0])

    def switch_tab(self, selected_tab="📦 Inventory Catalog"):
        for widget in self.tab_content.winfo_children():
            widget.destroy()

        if "Inventory Catalog" in selected_tab:
            self.build_main_table(self.tab_content)
            self.load_inventory_data()
        elif "Tag Management Hub" in selected_tab:
            from views.tagging import TaggingView
            self.tag_view = TaggingView(
                self.tab_content, user_info=self.user_info)
            self.tag_view.pack(fill="both", expand=True)

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

    def build_main_table(self, parent):
        table_card = ctk.CTkFrame(parent, fg_color="white", corner_radius=10)
        table_card.grid(row=0, column=0, sticky="nsew", padx=0)

        search_frame = ctk.CTkFrame(table_card, fg_color="transparent")
        search_frame.pack(fill="x", padx=20, pady=(20, 10))

        self.search_entry = ctk.CTkEntry(
            search_frame, placeholder_text="Universal search (Name, Tag, ID, Supplier, Loc, Desc)...", width=350, height=38)
        self.search_entry.pack(side="left", padx=(0, 10))
        self.search_entry.bind("<Return>", lambda e: self.perform_search())

        self.sort_menu = ctk.CTkOptionMenu(search_frame, values=["Most Recent", "Oldest", "A-Z (Name)", "Z-A (Name)", "PID (Low-High)"],
                                           width=140, height=38, fg_color="#F9FAFB", text_color="black", command=lambda e: self.perform_search())
        self.sort_menu.pack(side="left", padx=(0, 10))

        self.search_btn = ctk.CTkButton(search_frame, text="Search", width=90, height=38, fg_color="#3498DB",
                                        text_color="black", hover_color="#D4AC0D", font=("Inter", 12, "bold"), command=self.perform_search)
        self.search_btn.pack(side="left", padx=10)

        self.reset_btn = ctk.CTkButton(search_frame, text="↻ Reset", width=80, height=38, fg_color="#E0E0E0",
                                       text_color="black", hover_color="#CCCCCC", font=("Inter", 12, "bold"), command=self.reset_search)
        self.reset_btn.pack(side="left", padx=(0, 0))

        is_staff = self.user_info.get("role", "").lower() == "staff"

        if not is_staff:
            ctk.CTkButton(search_frame, text="+ Add New Item", width=120, height=38, fg_color="#1E4528", hover_color="#14301C",
                          font=("Inter", 12, "bold"), command=self.open_add_item_modal).pack(side="right", padx=(10, 0))

        hint_text = "💡 Click any row to View" if is_staff else "💡 Click any row to View/Edit"
        ctk.CTkLabel(search_frame, text=hint_text,
                     font=("Inter", 12, "italic"), text_color="gray").pack(side="right", padx=10)

        self.data_scroll = ctk.CTkScrollableFrame(
            table_card, fg_color="transparent")
        self.data_scroll.pack(fill="both", expand=True, padx=20, pady=(5, 20))

    def load_inventory_data(self, query="", sort_type="Most Recent"):
        for widget in self.data_scroll.winfo_children():
            widget.destroy()
        self.tool_hash_table.clear()

        table_inner = ctk.CTkFrame(self.data_scroll, fg_color="transparent")
        table_inner.pack(fill="x", anchor="n")

        headers = ["PID", "Type", "Name", "Tag ID",
                   "Qty Avail.", "UoM", "Location", "Status"]

        # DYNAMIC PROPORTIONS: Weights determine the exact ratio relative to each other.
        # Adding 'uniform' guarantees these specific proportions lock in place during resizing.
        weights = [1, 2, 4, 3, 2, 1, 4, 2]
        min_sizes = [50, 80, 150, 120, 80, 50, 150, 80]

        for col, (w, min_w) in enumerate(zip(weights, min_sizes)):
            # uniform="inv_cols" strictly ties the columns together mathematically
            table_inner.grid_columnconfigure(
                col, weight=w, minsize=min_w, uniform="inv_cols")

        # Header Row
        for col, text in enumerate(headers):
            cell = ctk.CTkFrame(
                table_inner, fg_color="#1E4528", corner_radius=0)
            cell.grid(row=0, column=col, sticky="nsew", pady=(0, 2))
            lbl = ctk.CTkLabel(cell, text=text, font=(
                "Inter", 13, "bold"), text_color="white", anchor="center")
            lbl.pack(fill="both", expand=True, padx=4, pady=14)

        loading_lbl = ctk.CTkLabel(table_inner, text="Fetching data from database, please wait...",
                                   text_color="gray", font=("Inter", 12, "italic"))
        loading_lbl.grid(row=1, column=0, columnspan=len(headers), pady=20)

        def fetch_data():
            is_archived = 0
            conn = get_connection()
            if not conn:
                self.after(0, lambda: self._render_inventory_data(
                    None, table_inner, loading_lbl, headers, min_sizes, query, sort_type))
                return

            try:
                cursor = conn.cursor(dictionary=True)
                base_query = """
                    SELECT t.tool_id, IFNULL(t.item_type, 'Equipment') as item_type,
                           IFNULL(t.unit_of_measure, 'pcs') as uom,
                           t.name, IFNULL(t.description, '') as description, t.price,
                           IFNULL(i.quantity_available, 0) as qty_avail,
                           IFNULL(i.quantity_total, 0) as qty_tot,
                           IFNULL(i.minimum_stock, 0) as min_stock,
                           IFNULL(t.location, 'N/A') as base_location, t.`condition` as status,
                           IFNULL(t.category, 'Uncategorized') as category,
                           IFNULL(t.supplier, 'N/A') as supplier,
                           t.tag_id,
                           (SELECT p.name FROM transaction tr 
                            JOIN projects p ON tr.project_id = p.project_id 
                            WHERE tr.tool_id = t.tool_id AND tr.status = 'Active' 
                            LIMIT 1) as active_project
                    FROM tool t LEFT JOIN inventory i ON t.tool_id = i.tool_id
                    WHERE t.is_archived = %s
                """
                params = [is_archived]

                if getattr(self, 'highlight_low_stock', False):
                    base_query += " AND i.minimum_stock > 0 AND i.quantity_available < i.minimum_stock"

                if query:
                    base_query += " AND (t.name LIKE %s OR CAST(t.tool_id AS CHAR) LIKE %s OR t.category LIKE %s OR t.item_type LIKE %s OR t.supplier LIKE %s OR IFNULL(t.tag_id,'') LIKE %s OR t.location LIKE %s OR t.description LIKE %s)"
                    params.extend([f"%{query}%"] * 8)

                if sort_type == "Oldest":
                    base_query += " ORDER BY t.tool_id ASC"
                elif sort_type == "A-Z (Name)":
                    base_query += " ORDER BY t.name ASC"
                elif sort_type == "Z-A (Name)":
                    base_query += " ORDER BY t.name DESC"
                elif sort_type == "PID (Low-High)":
                    base_query += " ORDER BY t.tool_id ASC"
                else:
                    base_query += " ORDER BY t.tool_id DESC"

                base_query += " LIMIT 100"
                cursor.execute(base_query, tuple(params))
                results = cursor.fetchall()

                self.after(0, lambda: self._render_inventory_data(
                    results, table_inner, loading_lbl, headers, min_sizes, query, sort_type))
            except Exception as e:
                print(f"Fetch Error: {e}")
                self.after(0, lambda: self._render_inventory_data(
                    None, table_inner, loading_lbl, headers, min_sizes, query, sort_type))
            finally:
                if conn.is_connected():
                    cursor.close()
                    conn.close()

        threading.Thread(target=fetch_data, daemon=True).start()

    def _render_inventory_data(self, results, table_inner, loading_lbl, headers, min_sizes, query, sort_type):
        if not self.winfo_exists() or not table_inner.winfo_exists():
            return

        loading_lbl.destroy()

        if results is None:
            ctk.CTkLabel(table_inner, text="Failed to fetch inventory data.", text_color="red").grid(
                row=1, column=0, columnspan=len(headers), pady=20)
            return

        if not results:
            ctk.CTkLabel(table_inner, text="No inventory found.", text_color="gray").grid(
                row=1, column=0, columnspan=len(headers), pady=20)
            return

        for i, row in enumerate(results):
            pid = str(row['tool_id'])
            row['location'] = row['base_location']
            self.tool_hash_table[pid] = row

            avail = f"{row['qty_avail']:g}" if row['qty_avail'] else "0"
            tot = f"{row['qty_tot']:g}" if row['qty_tot'] else "0"

            display_loc = row['base_location']
            if row.get('active_project') and float(row['qty_avail']) < float(row['qty_tot']):
                display_loc = f"Deployed: {row['active_project']}"

            tag_display = row['tag_id'] if row['tag_id'] else "Unassigned"

            is_low_stock = row.get(
                'min_stock', 0) > 0 and row['qty_avail'] < row['min_stock']
            qty_display = f"⚠ {avail}/{tot}" if is_low_stock else f"{avail}/{tot}"

            vals = [
                pid,
                row['item_type'],
                row['name'],
                tag_display,
                qty_display,
                row['uom'],
                display_loc,
                row['status']
            ]

            r_idx = i + 1
            if is_low_stock:
                bg = "#FFF3F3" if i % 2 == 0 else "#FFEBEB"
            else:
                bg = "#F9FAFB" if i % 2 == 0 else "white"

            for col, val in enumerate(vals):
                cell = ctk.CTkFrame(table_inner, fg_color=bg,
                                    corner_radius=0, cursor="hand2")
                cell.grid(row=r_idx, column=col, sticky="nsew")

                txt_col = "#1A1A1A"
                if col == 6 and "Deployed:" in val:
                    txt_col = "#2980B9"
                elif col == 1 and val == "Consumable":
                    txt_col = "#D37F00"
                elif col == 3 and val == "Unassigned":
                    txt_col = "#D8000C"
                elif col == 4 and is_low_stock:
                    txt_col = "#D8000C"

                font_w = "bold" if col == 1 or col == 3 or (col == 4 and is_low_stock) or (
                    col == 6 and "Deployed:" in val) else "normal"

                lbl = ctk.CTkLabel(cell, text=val, font=(
                    "Inter", 11, font_w), text_color=txt_col, justify="center", anchor="center", cursor="hand2")

                lbl.configure(wraplength=min_sizes[col] - 10)

                lbl.pack(fill="both", expand=True, padx=4, pady=12)

                cell.bind("<Button-1>", lambda e,
                          lookup_id=pid: self.open_tool_modal(lookup_id))
                lbl.bind("<Button-1>", lambda e,
                         lookup_id=pid: self.open_tool_modal(lookup_id))

        if getattr(self, 'highlight_tool_id', None):
            self.after(
                100, lambda t=self.highlight_tool_id: self.open_tool_modal(str(t)))
            self.highlight_tool_id = None

        uid = self.user_info.get("user_id")
        if uid and query:
            log_action(uid, "Searched", "Inventory",
                       f"Searched inventory: '{query}' (Sort: {sort_type})")

    def perform_search(self):
        self.load_inventory_data(
            self.search_entry.get().strip(), self.sort_menu.get())

    def reset_search(self):
        self.search_entry.delete(0, 'end')
        self.sort_menu.set("Most Recent")
        self.highlight_low_stock = False
        self.load_inventory_data()

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

        try:
            price_val = self.price_entry.get().strip()
            price = float(price_val) if price_val else 0.00

            qty_val = self.qty_entry.get().strip()
            if not qty_val:
                messagebox.showerror(
                    "Validation Error", "Quantity is required.", parent=self.add_modal)
                return
            qty = float(qty_val)

            if qty < 0 or price < 0:
                messagebox.showerror(
                    "Validation Error", "Price and Quantity cannot be negative values.", parent=self.winfo_toplevel())
                return

        except ValueError:
            messagebox.showerror(
                "Type Error", "Price and Quantity must be numbers.", parent=self.add_modal)
            return

        conn = get_connection()
        if not conn:
            return
        try:
            cursor = conn.cursor()

            # --- DUPLICATE & TYPO CHECK ---
            cursor.execute("SELECT name FROM tool WHERE is_archived = 0")
            existing_names = [r[0] for r in cursor.fetchall()]
            exact_match = False
            similar_names = []

            for en in existing_names:
                if en.lower() == name.lower():
                    exact_match = True
                    break
                if difflib.SequenceMatcher(None, name.lower(), en.lower()).ratio() > 0.85:
                    similar_names.append(en)

            if exact_match:
                messagebox.showerror(
                    "Duplicate Name", f"A product named '{name}' already exists in active inventory.", parent=self.add_modal)
                return

            if similar_names:
                sim_list = "\n".join([f"• {sn}" for sn in similar_names[:3]])
                msg = f"Wait! Similar product names already exist:\n\n{sim_list}\n\nAre you sure you want to add '{name}' as a new distinct item?"
                if not messagebox.askyesno("Similar Name Detected", msg, parent=self.add_modal):
                    return
            # -----------------------------

            cursor.execute("""
                INSERT INTO tool (category, supplier, name, description, price, location,
                                  item_type, unit_of_measure, `condition`, date_acquired, is_archived)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Good', NOW(), 0)
            """, (cat, sup, name, desc, price, loc, itype, uom))

            new_tool_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO inventory (tool_id, quantity_total, quantity_available) VALUES (%s, %s, %s)",
                (new_tool_id, qty, qty)
            )
            conn.commit()

            uid = self.user_info.get("user_id")
            if uid:
                log_action(uid, "Added", "Inventory",
                           f"Added new {itype}: '{name}' (PID: {new_tool_id}), Qty: {qty} {uom}")

            messagebox.showinfo(
                "Success", f"{itype} '{name}' added successfully.", parent=self.add_modal)
            self.add_modal.destroy()
            self.load_inventory_data()
        except Exception as e:
            messagebox.showerror("Database Error", str(e),
                                 parent=self.add_modal)
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

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
                               t.tag_id, t.is_archived
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
            form_scroll, "Total Qty", f"{data['qty_tot']:g}")
        min_stock_entry = create_modal_row(
            form_scroll, "Min Stock", f"{data.get('min_stock', 0):g}")

        uom_frame = ctk.CTkFrame(form_scroll, fg_color="transparent")
        uom_frame.pack(fill="x", pady=4)
        ctk.CTkLabel(uom_frame, text="UoM", width=90, anchor="w", font=(
            "Inter", 11, "bold"), text_color="gray").pack(side="left")
        uom_menu = ctk.CTkOptionMenu(uom_frame, values=[
                                     "pcs", "boxes", "sets", "kg", "rolls", "packs", "liters", "meters", "feet"], fg_color="#F9FAFB", text_color="black")
        uom_menu.pack(side="left", fill="x", expand=True)
        uom_menu.set(data['uom'])

        loc_entry = create_modal_row(form_scroll, "Location", data['location'])

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

        def generate_smart_tag():
            tag_entry.delete(0, 'end')
            cat_prefix = str(cat_entry.get())[
                :3].upper() if cat_entry.get() else "GEN"
            sup_prefix = str(sup_entry.get())[
                :3].upper() if sup_entry.get() else "UNK"
            smart_tag = f"TAG-{str(lookup_id).zfill(3)}-{cat_prefix}-{sup_prefix}"
            tag_entry.insert(0, smart_tag)
            update_preview()

        if not is_staff_modal:
            ctk.CTkButton(tag_row, text="↻ Auto-Gen", width=80, fg_color="#F1C40F", text_color="black",
                          hover_color="#D4AC0D", font=("Inter", 11, "bold"), command=generate_smart_tag).pack(side="left", padx=(5, 0))

        def save_tag():
            new_tag = tag_entry.get().strip()
            conn = get_connection()
            if not conn:
                return
            try:
                c = conn.cursor()
                if new_tag:
                    c.execute(
                        "SELECT tool_id FROM tool WHERE tag_id = %s AND tool_id != %s", (new_tag, lookup_id))
                    if c.fetchone():
                        return messagebox.showerror("Duplicate Tag", f"Tag '{new_tag}' is already used!", parent=modal)
                c.execute("UPDATE tool SET tag_id = %s WHERE tool_id = %s",
                          (new_tag or None, lookup_id))
                conn.commit()
                data['tag_id'] = new_tag
                messagebox.showinfo(
                    "Success", "Tag successfully linked to tool.", parent=modal)
                self.load_inventory_data()
            except Exception as e:
                messagebox.showerror("Error", str(e), parent=modal)
            finally:
                if conn.is_connected():
                    c.close()
                    conn.close()

        def unlink_tag():
            if messagebox.askyesno("Remove Tag", "Unlink the tag from this tool?", parent=modal):
                tag_entry.delete(0, 'end')
                save_tag()
                update_preview()

        if not is_staff_modal:
            tag_btn_row = ctk.CTkFrame(form_scroll, fg_color="transparent")
            tag_btn_row.pack(fill="x", pady=10)
            ctk.CTkButton(tag_btn_row, text="Save Tag Link", width=120, fg_color="#1E4528", hover_color="#14301C", font=(
                "Inter", 11, "bold"), command=save_tag).pack(side="left", expand=True, fill="x", padx=(0, 5))
            ctk.CTkButton(tag_btn_row, text="Unlink Current Tag", width=120, fg_color="white", border_width=1, border_color="#D8000C", text_color="#D8000C",
                          hover_color="#FFD2D2", font=("Inter", 11, "bold"), command=unlink_tag).pack(side="right", expand=True, fill="x", padx=(5, 0))

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
                qr_img_lbl.configure(image="", text="No Tag Assigned")
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
            try:
                new_qty = float(qty_entry.get())
                new_min_stock = float(min_stock_entry.get(
                )) if min_stock_entry.get().strip() else 0.0
                # --- FIX C: Capture and Validate Price Update ---
                new_price = float(
                    price_entry.get()) if price_entry.get().strip() else 0.00
                if new_qty < 0 or new_price < 0 or new_min_stock < 0:
                    return messagebox.showerror("Error", "Quantity, Min Stock, and Price cannot be negative.", parent=modal)
            except ValueError:
                return messagebox.showerror("Error", "Quantity, Min Stock, and Price must be valid numbers.", parent=modal)

            qty_diff = new_qty - float(data['qty_tot'])
            new_avail = float(data['qty_avail']) + qty_diff

            if new_avail < 0:
                borrowed_out = float(data['qty_tot']) - \
                    float(data['qty_avail'])
                return messagebox.showerror("Warning", f"Invalid adjustment.\n\nYou cannot lower the Total Quantity to {new_qty} because there are {borrowed_out} unit(s) currently deployed to workers.\n\nThis would result in a negative Available Qty ({new_avail}).", parent=modal)

            if messagebox.askyesno("Confirm Update", "Save all changes to the database?", parent=modal):
                conn = get_connection()
                if not conn:
                    return
                try:
                    cursor = conn.cursor()

                    # --- DUPLICATE & TYPO CHECK FOR EDITS ---
                    new_name = name_entry.get().strip()
                    cursor.execute(
                        "SELECT tool_id, name FROM tool WHERE is_archived = 0 AND tool_id != %s", (lookup_id,))
                    existing_tools = cursor.fetchall()
                    exact_match = False
                    similar_names = []

                    for et in existing_tools:
                        en_name = et[1]
                        if en_name.lower() == new_name.lower():
                            exact_match = True
                            break
                        if difflib.SequenceMatcher(None, new_name.lower(), en_name.lower()).ratio() > 0.85:
                            similar_names.append(en_name)

                    if exact_match:
                        return messagebox.showerror("Duplicate Name", f"Another product named '{new_name}' already exists.", parent=modal)

                    if similar_names and new_name.lower() != data['name'].lower():
                        sim_list = "\n".join(
                            [f"• {sn}" for sn in similar_names[:3]])
                        msg = f"Similar product names already exist:\n\n{sim_list}\n\nAre you sure you want to rename this to '{new_name}'?"
                        if not messagebox.askyesno("Similar Name Detected", msg, parent=modal):
                            return
                    # -----------------------------

                    new_tag = tag_entry.get().strip() or None
                    if new_tag:
                        cursor.execute(
                            "SELECT tool_id FROM tool WHERE tag_id = %s AND tool_id != %s", (new_tag, lookup_id))
                        if cursor.fetchone():
                            return messagebox.showerror("Duplicate Tag", "Tag ID is already used by another tool.", parent=modal)

                    cursor.execute("""
                        UPDATE tool SET name=%s, description=%s, category=%s, supplier=%s, location=%s, item_type=%s, unit_of_measure=%s, `condition`=%s, tag_id=%s
                        WHERE tool_id=%s
                    """, (name_entry.get(), desc_entry.get(), cat_entry.get(), sup_entry.get(), loc_entry.get(), type_menu.get(), uom_menu.get(), status_menu.get(), new_tag, lookup_id))

                    cursor.execute("""
                        UPDATE inventory SET quantity_total=%s, quantity_available=quantity_available + %s, minimum_stock=%s WHERE tool_id=%s
                    """, (new_qty, qty_diff, new_min_stock, lookup_id))
                    conn.commit()

                    uid = self.user_info.get("user_id")
                    if uid:
                        log_action(
                            uid, "Edited", "Inventory", f"Edited item '{name_entry.get()}' (PID: {lookup_id})")

                    modal.destroy()
                    self.load_inventory_data()
                except Exception as e:
                    messagebox.showerror(
                        "Database Error", str(e), parent=modal)
                finally:
                    if conn.is_connected():
                        cursor.close()
                        conn.close()

        def execute_archive():
            if is_arch:
                msg = "Restore this item to active inventory?"
                new_state = 0
            else:
                msg = "Archive this item? It will be hidden from active inventory."
                new_state = 1

            if messagebox.askyesno("Confirm", msg, parent=modal):
                conn = get_connection()
                if conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE tool SET is_archived=%s, archived_at=NOW() WHERE tool_id=%s", (new_state, lookup_id))
                    conn.commit()
                    cursor.close()
                    conn.close()

                    uid = self.user_info.get("user_id")
                    action_str = "Restored" if new_state == 0 else "Archived"
                    if uid:
                        log_action(uid, action_str, "Inventory",
                                   f"{action_str} item '{data['name']}'")

                    modal.destroy()
                    self.load_inventory_data()

                    dashboard = self.winfo_toplevel()
                    if hasattr(dashboard, "show_toast"):
                        msg_str = "✓ Tool archived and passed to Maintenance." if new_state == 1 else "✓ Tool restored successfully."
                        dashboard.show_toast(msg_str)

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
                                 price_entry, qty_entry, min_stock_entry, loc_entry, tag_entry]:
                entry_widget.configure(state="disabled")
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
