import customtkinter as ctk
from tkinter import messagebox
from database import get_connection, log_action

class InventoryView(ctk.CTkFrame):
    def __init__(self, parent, user_info=None):
        super().__init__(parent, fg_color="transparent")

        self.user_info = user_info or {}

        # 1. Main Wrapper Expansion
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0) 
        self.grid_rowconfigure(1, weight=1) 

        self.tool_hash_table = {}

        self.build_top_tabs()

    def build_top_tabs(self):
        top_bar = ctk.CTkFrame(self, fg_color="transparent")
        top_bar.grid(row=0, column=0, sticky="ew", padx=20, pady=(10, 15))

        ctk.CTkLabel(top_bar, text="Products / Inventory", font=("Inter", 16, "bold"), text_color="#1E4528").pack(side="left")

        self.tab_content = ctk.CTkFrame(self, fg_color="transparent")
        self.tab_content.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 20))
        
        # PROPORTIONAL SPLIT: Using 'uniform' forces the left form and right table 
        # to strictly maintain a 1:3 ratio at all window sizes.
        self.tab_content.grid_columnconfigure(0, weight=1, minsize=380, uniform="main_split")
        self.tab_content.grid_columnconfigure(1, weight=3, minsize=750, uniform="main_split")
        self.tab_content.grid_rowconfigure(0, weight=1)

        self.switch_tab()

    def switch_tab(self):
        for widget in self.tab_content.winfo_children():
            widget.destroy()

        self.build_left_form(self.tab_content)
        self.build_right_table(self.tab_content)
        self.load_inventory_data()
        self.load_dynamic_dropdowns()
        self.name_entry.focus_set()

    def build_left_form(self, parent):
        form_card = ctk.CTkScrollableFrame(parent, fg_color="white", corner_radius=10)
        form_card.grid(row=0, column=0, sticky="nsew", padx=(10, 5))

        ctk.CTkLabel(form_card, text="Add New Item", font=("Inter", 16, "bold"), text_color="#1A1A1A").pack(anchor="w", padx=20, pady=(20, 10))

        row_type = ctk.CTkFrame(form_card, fg_color="transparent")
        row_type.pack(fill="x", padx=20, pady=(5, 10))
        row_type.grid_columnconfigure(0, weight=1)
        row_type.grid_columnconfigure(1, weight=1)

        t_frame = ctk.CTkFrame(row_type, fg_color="transparent")
        t_frame.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        ctk.CTkLabel(t_frame, text="Item Type", font=("Inter", 11, "bold"), text_color="#1E4528").pack(anchor="w")
        self.type_menu = ctk.CTkOptionMenu(t_frame, values=["Equipment", "Consumable"], fg_color="#E8F8F5", text_color="black")
        self.type_menu.pack(fill="x", pady=(5, 0))

        uom_frame = ctk.CTkFrame(row_type, fg_color="transparent")
        uom_frame.grid(row=0, column=1, sticky="ew", padx=(5, 0))
        ctk.CTkLabel(uom_frame, text="Unit (UoM)", font=("Inter", 11, "bold"), text_color="#1E4528").pack(anchor="w")
        self.uom_menu = ctk.CTkOptionMenu(uom_frame, values=["pcs", "boxes", "sets", "kg", "rolls", "packs", "liters", "meters", "feet"], fg_color="#E8F8F5", text_color="black")
        self.uom_menu.pack(fill="x", pady=(5, 0))

        ctk.CTkLabel(form_card, text="💡 Consumables (e.g. boxes of nails) support fractional returns. (e.g., return 0.5 for half box).", font=("Inter", 10), text_color="gray", justify="left", wraplength=300).pack(anchor="w", padx=20, pady=(0, 10))

        ctk.CTkLabel(form_card, text="Product Name *", font=("Inter", 11, "bold"), text_color="#1A1A1A").pack(anchor="w", padx=20)
        self.name_entry = ctk.CTkEntry(form_card, placeholder_text="e.g., #2 Nails (Box)")
        self.name_entry.pack(fill="x", padx=20, pady=(5, 10))

        ctk.CTkLabel(form_card, text="Description", font=("Inter", 11, "bold"), text_color="#1A1A1A").pack(anchor="w", padx=20)
        self.desc_entry = ctk.CTkEntry(form_card, placeholder_text="Brief details about the item...")
        self.desc_entry.pack(fill="x", padx=20, pady=(5, 10))

        ctk.CTkLabel(form_card, text="Category", font=("Inter", 11, "bold"), text_color="#1A1A1A").pack(anchor="w", padx=20)
        self.cat_menu = ctk.CTkComboBox(form_card, values=["Loading..."], fg_color="#F9FAFB", text_color="black")
        self.cat_menu.pack(fill="x", padx=20, pady=(5, 10))

        ctk.CTkLabel(form_card, text="Supplier", font=("Inter", 11, "bold"), text_color="#1A1A1A").pack(anchor="w", padx=20)
        self.sup_menu = ctk.CTkComboBox(form_card, values=["Loading..."], fg_color="#F9FAFB", text_color="black")
        self.sup_menu.pack(fill="x", padx=20, pady=(5, 10))

        row_frame = ctk.CTkFrame(form_card, fg_color="transparent")
        row_frame.pack(fill="x", padx=20, pady=(5, 10))
        row_frame.grid_columnconfigure(0, weight=1)
        row_frame.grid_columnconfigure(1, weight=1)

        p_frame = ctk.CTkFrame(row_frame, fg_color="transparent")
        p_frame.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        ctk.CTkLabel(p_frame, text="Price", font=("Inter", 11, "bold"), text_color="#1A1A1A").pack(anchor="w")
        self.price_entry = ctk.CTkEntry(p_frame, placeholder_text="0.00")
        self.price_entry.pack(fill="x", pady=(5, 0))

        q_frame = ctk.CTkFrame(row_frame, fg_color="transparent")
        q_frame.grid(row=0, column=1, sticky="ew", padx=(5, 0))
        ctk.CTkLabel(q_frame, text="Quantity", font=("Inter", 11, "bold"), text_color="#1A1A1A").pack(anchor="w")
        self.qty_entry = ctk.CTkEntry(q_frame, placeholder_text="0")
        self.qty_entry.pack(fill="x", pady=(5, 0))

        ctk.CTkLabel(form_card, text="Storage Location", font=("Inter", 11, "bold"), text_color="#1A1A1A").pack(anchor="w", padx=20)
        self.loc_entry = ctk.CTkEntry(form_card, placeholder_text="e.g., Shelf A1")
        self.loc_entry.pack(fill="x", padx=20, pady=(5, 15))

        self.name_entry.bind("<Return>", lambda e: self.desc_entry.focus_set())
        self.desc_entry.bind("<Return>", lambda e: self.price_entry.focus_set())
        self.price_entry.bind("<Return>", lambda e: self.qty_entry.focus_set())
        self.qty_entry.bind("<Return>", lambda e: self.loc_entry.focus_set())
        self.loc_entry.bind("<Return>", lambda e: self.validate_and_save())

        btn_row = ctk.CTkFrame(form_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(10, 20))
        btn_row.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkButton(btn_row, text="Save Item", fg_color="#1E4528", hover_color="#14301C", font=("Inter", 12, "bold"), command=self.validate_and_save).grid(row=0, column=0, padx=(0, 5), sticky="ew")
        ctk.CTkButton(btn_row, text="Clear", fg_color="#E0E0E0", text_color="black", hover_color="#CCCCCC", font=("Inter", 12, "bold"), command=self.clear_form).grid(row=0, column=1, padx=(5, 0), sticky="ew")

    def load_dynamic_dropdowns(self):
        conn = get_connection()
        if not conn: return
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT category FROM tool WHERE category IS NOT NULL AND category != 'Uncategorized' AND category != ''")
            cats = [row[0] for row in cursor.fetchall()]
            
            cursor.execute("SELECT DISTINCT supplier FROM tool WHERE supplier IS NOT NULL AND supplier != 'N/A' AND supplier != ''")
            sups = [row[0] for row in cursor.fetchall()]
            
            if not cats: cats = ["Tools", "Measuring", "Power Tools", "Consumables"]
            if not sups: sups = ["ACME", "Global Tooling"]
            
            self.cat_menu.configure(values=cats)
            self.sup_menu.configure(values=sups)
            self.cat_menu.set("Type or select...")
            self.sup_menu.set("Type or select...")
        except Exception as e:
            print(f"Dropdown Load Error: {e}")
        finally:
            if conn.is_connected(): cursor.close(); conn.close()

    def build_right_table(self, parent):
        table_card = ctk.CTkFrame(parent, fg_color="white", corner_radius=10)
        table_card.grid(row=0, column=1, sticky="nsew", padx=(5, 10))

        search_frame = ctk.CTkFrame(table_card, fg_color="transparent")
        search_frame.pack(fill="x", padx=20, pady=(20, 10))

        self.filter_menu = ctk.CTkOptionMenu(search_frame, values=["All Fields", "By: PID", "By: Name", "By: Type", "By: Supplier"], width=150, fg_color="#F9FAFB", text_color="black")
        self.filter_menu.pack(side="left", padx=(0, 10))

        self.search_entry = ctk.CTkEntry(search_frame, placeholder_text="Search inventory...", width=250)
        self.search_entry.pack(side="left")
        self.search_entry.bind("<Return>", lambda e: self.perform_search())

        self.search_btn = ctk.CTkButton(search_frame, text="Search", width=80, fg_color="#F1C40F", text_color="black", hover_color="#D4AC0D", font=("Inter", 11, "bold"), command=self.perform_search)
        self.search_btn.pack(side="left", padx=10)

        self.reset_btn = ctk.CTkButton(search_frame, text="↻ Reset", width=70, fg_color="#E0E0E0", text_color="black", hover_color="#CCCCCC", font=("Inter", 11, "bold"), command=self.reset_search)
        self.reset_btn.pack(side="left", padx=(0, 0))
        
        ctk.CTkLabel(search_frame, text="💡 Click any row to View/Edit", font=("Inter", 11, "italic"), text_color="gray").pack(side="right")

        self.data_scroll = ctk.CTkScrollableFrame(table_card, fg_color="transparent")
        self.data_scroll.pack(fill="both", expand=True, padx=20, pady=(5, 20))

    def load_inventory_data(self, query="", filter_type="All Fields"):
        for widget in self.data_scroll.winfo_children():
            widget.destroy()
        self.tool_hash_table.clear()

        table_inner = ctk.CTkFrame(self.data_scroll, fg_color="transparent")
        table_inner.pack(fill="x", expand=True)

        headers = ["PID", "Type", "Name", "Category", "Supplier", "Qty Avail.", "UoM", "Location", "Status"]
        
        # DYNAMIC PROPORTIONS: Weights determine the exact ratio relative to each other.
        # Adding 'uniform' guarantees these specific proportions lock in place during resizing.
        weights = [1, 2, 4, 3, 3, 2, 1, 4, 2]
        min_sizes = [50, 80, 150, 100, 100, 80, 50, 150, 80]

        for col, (w, min_w) in enumerate(zip(weights, min_sizes)):
            # uniform="inv_cols" strictly ties the columns together mathematically
            table_inner.grid_columnconfigure(col, weight=w, minsize=min_w, uniform="inv_cols")

        # Header Row
        for col, text in enumerate(headers):
            cell = ctk.CTkFrame(table_inner, fg_color="#1E4528", corner_radius=0)
            cell.grid(row=0, column=col, sticky="nsew", pady=(0, 2))
            lbl = ctk.CTkLabel(cell, text=text, font=("Inter", 11, "bold"), text_color="white", anchor="center")
            lbl.pack(fill="both", expand=True, padx=2, pady=10)

        is_archived = 0
        conn = get_connection()
        if not conn:
            return

        try:
            cursor = conn.cursor(dictionary=True)
            base_query = """
                SELECT t.tool_id, IFNULL(t.item_type, 'Equipment') as item_type,
                       IFNULL(t.unit_of_measure, 'pcs') as uom,
                       t.name, IFNULL(t.description, '') as description, t.price,
                       IFNULL(i.quantity_available, 0) as qty_avail,
                       IFNULL(i.quantity_total, 0) as qty_tot,
                       IFNULL(t.location, 'N/A') as base_location, t.`condition` as status,
                       IFNULL(t.category, 'Uncategorized') as category,
                       IFNULL(t.supplier, 'N/A') as supplier,
                       (SELECT p.name FROM transaction tr 
                        JOIN projects p ON tr.project_id = p.project_id 
                        WHERE tr.tool_id = t.tool_id AND tr.status = 'Active' 
                        LIMIT 1) as active_project
                FROM tool t LEFT JOIN inventory i ON t.tool_id = i.tool_id
                WHERE t.is_archived = %s
            """
            params = [is_archived]
            
            if query:
                if filter_type == "All Fields":
                    base_query += " AND (t.name LIKE %s OR t.tool_id LIKE %s OR t.category LIKE %s OR t.item_type LIKE %s OR t.supplier LIKE %s)"
                    params.extend([f"%{query}%"] * 5)
                elif filter_type == "By: PID":
                    base_query += " AND t.tool_id LIKE %s"
                    params.append(f"%{query}%")
                elif filter_type == "By: Name":
                    base_query += " AND t.name LIKE %s"
                    params.append(f"%{query}%")
                elif filter_type == "By: Type":
                    base_query += " AND t.item_type LIKE %s"
                    params.append(f"%{query}%")
                elif filter_type == "By: Supplier":
                    base_query += " AND t.supplier LIKE %s"
                    params.append(f"%{query}%")

            base_query += " ORDER BY t.tool_id DESC LIMIT 100"
            cursor.execute(base_query, tuple(params))
            results = cursor.fetchall()

            if not results:
                ctk.CTkLabel(table_inner, text="No inventory found.", text_color="gray").grid(row=1, column=0, columnspan=len(headers), pady=20)
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

                vals = [
                    pid,
                    row['item_type'],
                    row['name'],
                    row['category'],
                    row['supplier'],
                    f"{avail}/{tot}",
                    row['uom'],
                    display_loc,
                    row['status']
                ]

                r_idx = i + 1
                bg = "#F9FAFB" if i % 2 == 0 else "white"

                for col, val in enumerate(vals):
                    cell = ctk.CTkFrame(table_inner, fg_color=bg, corner_radius=0, cursor="hand2")
                    cell.grid(row=r_idx, column=col, sticky="nsew")

                    txt_col = "#1A1A1A"
                    if col == 7 and "Deployed:" in val: 
                        txt_col = "#2980B9"
                    elif col == 1 and val == "Consumable": 
                        txt_col = "#D35400"
                        
                    font_w = "bold" if col == 1 or (col == 7 and "Deployed:" in val) else "normal"

                    lbl = ctk.CTkLabel(cell, text=val, font=("Inter", 11, font_w), text_color=txt_col, justify="center", anchor="center", cursor="hand2")
                    
                    # DYNAMIC WRAP: Calculates live wrap boundaries as the window expands/shrinks
                    def set_wrap(e, l=lbl, min_w=min_sizes[col]):
                        target_wrap = max(min_w - 15, e.width - 15)
                        if not hasattr(l, '_last_wrap') or abs(l._last_wrap - target_wrap) > 10:
                            l.configure(wraplength=target_wrap)
                            l._last_wrap = target_wrap
                    cell.bind("<Configure>", set_wrap)
                    
                    lbl.pack(fill="both", expand=True, padx=4, pady=12)

                    cell.bind("<Button-1>", lambda e, lookup_id=pid: self.open_tool_modal(lookup_id))
                    lbl.bind("<Button-1>", lambda e, lookup_id=pid: self.open_tool_modal(lookup_id))

            uid = self.user_info.get("user_id")
            if uid and query:
                log_action(uid, "Searched", "Inventory", f"Searched inventory: '{query}' by {filter_type}")

        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    def perform_search(self):
        self.load_inventory_data(self.search_entry.get().strip(), self.filter_menu.get())

    def reset_search(self):
        self.search_entry.delete(0, 'end')
        self.filter_menu.set("All Fields")
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
            messagebox.showerror("Validation Error", "Product Name is required.", parent=self.winfo_toplevel())
            return

        try:
            price_val = self.price_entry.get().strip()
            price = float(price_val) if price_val else 0.00
            qty = float(self.qty_entry.get())
            
            if qty < 0 or price < 0:
                messagebox.showerror("Validation Error", "Price and Quantity cannot be negative values.", parent=self.winfo_toplevel())
                return
            
        except ValueError:
            messagebox.showerror("Type Error", "Price and Quantity must be numbers.", parent=self.winfo_toplevel())
            return

        conn = get_connection()
        if not conn:
            return
        try:
            cursor = conn.cursor()
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
                log_action(uid, "Added", "Inventory", f"Added new {itype}: '{name}' (PID: {new_tool_id}), Qty: {qty} {uom}")

            messagebox.showinfo("Success", f"{itype} '{name}' added successfully.", parent=self.winfo_toplevel())
            self.clear_form()
            self.load_inventory_data()
            self.load_dynamic_dropdowns() 
        except Exception as e:
            messagebox.showerror("Database Error", str(e), parent=self.winfo_toplevel())
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    def open_tool_modal(self, lookup_id):
        data = self.tool_hash_table.get(lookup_id)
        if not data: return
        
        is_arch = 0

        modal = ctk.CTkToplevel(self)
        modal.title(f"Manage Item: {lookup_id}")
        modal.geometry("550x750")
        modal.configure(fg_color="white")
        modal.attributes("-topmost", True)
        modal.update_idletasks()
        x = (modal.winfo_screenwidth() // 2) - (550 // 2)
        y = (modal.winfo_screenheight() // 2) - (750 // 2)
        modal.geometry(f"+{x}+{y}")
        modal.grab_set()

        ctk.CTkLabel(modal, text=f"Item Details — PID: {lookup_id}", font=("Inter", 16, "bold"), text_color="black").pack(pady=(20, 3))
        ctk.CTkLabel(modal, text=f"{data['name']}", font=("Inter", 13), text_color="#555555").pack(pady=(0, 10))

        form_scroll = ctk.CTkScrollableFrame(modal, fg_color="transparent")
        form_scroll.pack(fill="both", expand=True, padx=25)

        def create_modal_row(parent, label, value):
            frame = ctk.CTkFrame(parent, fg_color="transparent")
            frame.pack(fill="x", pady=4)
            ctk.CTkLabel(frame, text=label, width=90, anchor="w", font=("Inter", 11, "bold"), text_color="gray").pack(side="left")
            entry = ctk.CTkEntry(frame)
            entry.pack(side="left", fill="x", expand=True)
            entry.insert(0, str(value) if value else "")
            return entry

        type_frame = ctk.CTkFrame(form_scroll, fg_color="transparent")
        type_frame.pack(fill="x", pady=4)
        ctk.CTkLabel(type_frame, text="Item Type", width=90, anchor="w", font=("Inter", 11, "bold"), text_color="gray").pack(side="left")
        type_menu = ctk.CTkOptionMenu(type_frame, values=["Equipment", "Consumable"], fg_color="#F9FAFB", text_color="black")
        type_menu.pack(side="left", fill="x", expand=True)
        type_menu.set(data['item_type'])

        name_entry = create_modal_row(form_scroll, "Name", data['name'])
        desc_entry = create_modal_row(form_scroll, "Description", data['description'])
        cat_entry = create_modal_row(form_scroll, "Category", data['category'])
        sup_entry = create_modal_row(form_scroll, "Supplier", data['supplier'])
        
        # --- FIX C: Added Missing Price Field ---
        price_entry = create_modal_row(form_scroll, "Price", data['price'])
        
        qty_entry = create_modal_row(form_scroll, "Total Qty", f"{data['qty_tot']:g}")

        uom_frame = ctk.CTkFrame(form_scroll, fg_color="transparent")
        uom_frame.pack(fill="x", pady=4)
        ctk.CTkLabel(uom_frame, text="UoM", width=90, anchor="w", font=("Inter", 11, "bold"), text_color="gray").pack(side="left")
        uom_menu = ctk.CTkOptionMenu(uom_frame, values=["pcs", "boxes", "sets", "kg", "rolls", "packs", "liters", "meters", "feet"], fg_color="#F9FAFB", text_color="black")
        uom_menu.pack(side="left", fill="x", expand=True)
        uom_menu.set(data['uom'])

        loc_entry = create_modal_row(form_scroll, "Location", data['location'])

        ctk.CTkLabel(form_scroll, text="ℹ  For consumables (boxes, kg, sets): fractional quantities are supported.\n   e.g., set Total Qty to 2.5 if half a box was partially used.", font=("Inter", 10), text_color="gray", justify="left", wraplength=450).pack(anchor="w", pady=(3, 5))

        status_frame = ctk.CTkFrame(form_scroll, fg_color="transparent")
        status_frame.pack(fill="x", pady=4)
        ctk.CTkLabel(status_frame, text="Condition", width=90, anchor="w", font=("Inter", 11, "bold"), text_color="gray").pack(side="left")
        status_menu = ctk.CTkOptionMenu(status_frame, values=["Good", "Needs Repair", "Damaged", "Lost"], fg_color="#F9FAFB", text_color="black")
        status_menu.pack(side="left", fill="x", expand=True)
        status_menu.set(data['status'])

        def execute_update():
            try:
                new_qty = float(qty_entry.get())
                # --- FIX C: Capture and Validate Price Update ---
                new_price = float(price_entry.get()) if price_entry.get().strip() else 0.00
                if new_qty < 0 or new_price < 0:
                    return messagebox.showerror("Error", "Quantity and Price cannot be negative.", parent=modal)
            except ValueError:
                return messagebox.showerror("Error", "Quantity and Price must be valid numbers.", parent=modal)

            qty_diff = new_qty - float(data['qty_tot'])
            new_avail = float(data['qty_avail']) + qty_diff
            
            if new_avail < 0:
                borrowed_out = float(data['qty_tot']) - float(data['qty_avail'])
                return messagebox.showerror("Warning", f"Invalid adjustment.\n\nYou cannot lower the Total Quantity to {new_qty} because there are {borrowed_out} unit(s) currently deployed to workers.\n\nThis would result in a negative Available Qty ({new_avail}).", parent=modal)

            if messagebox.askyesno("Confirm Update", "Save all changes to the database?", parent=modal):
                conn = get_connection()
                if not conn: return
                try:
                    cursor = conn.cursor()
                    # --- FIX C: Added price to the UPDATE statement ---
                    cursor.execute("""
                        UPDATE tool SET name=%s, description=%s, category=%s, supplier=%s, location=%s, item_type=%s, unit_of_measure=%s, `condition`=%s, price=%s
                        WHERE tool_id=%s
                    """, (name_entry.get(), desc_entry.get(), cat_entry.get(), sup_entry.get(), loc_entry.get(), type_menu.get(), uom_menu.get(), status_menu.get(), new_price, lookup_id))

                    cursor.execute("""
                        UPDATE inventory SET quantity_total=%s, quantity_available=quantity_available + %s WHERE tool_id=%s
                    """, (new_qty, qty_diff, lookup_id))
                    conn.commit()

                    uid = self.user_info.get("user_id")
                    if uid:
                        log_action(uid, "Edited", "Inventory", f"Edited item '{name_entry.get()}' (PID: {lookup_id})")

                    modal.destroy()
                    self.load_inventory_data()
                    self.load_dynamic_dropdowns() 
                except Exception as e:
                    messagebox.showerror("Database Error", str(e), parent=modal)
                finally:
                    if conn.is_connected(): cursor.close(); conn.close()

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
                    cursor.execute("UPDATE tool SET is_archived=%s, archived_at=NOW() WHERE tool_id=%s", (new_state, lookup_id))
                    conn.commit()
                    cursor.close(); conn.close()
                    
                    uid = self.user_info.get("user_id")
                    action_str = "Restored" if new_state == 0 else "Archived"
                    if uid: log_action(uid, action_str, "Inventory", f"{action_str} item '{data['name']}'")
                    
                    modal.destroy()
                    self.load_inventory_data()

        # Modal Focus Traversal
        name_entry.bind("<Return>", lambda e: desc_entry.focus_set())
        desc_entry.bind("<Return>", lambda e: cat_entry.focus_set())
        cat_entry.bind("<Return>", lambda e: sup_entry.focus_set())
        # --- FIX C: Adjusted bindings to include Price Field ---
        sup_entry.bind("<Return>", lambda e: price_entry.focus_set())
        price_entry.bind("<Return>", lambda e: qty_entry.focus_set())
        qty_entry.bind("<Return>", lambda e: loc_entry.focus_set())
        loc_entry.bind("<Return>", lambda e: execute_update())

        btn_row = ctk.CTkFrame(modal, fg_color="transparent")
        btn_row.pack(side="bottom", fill="x", padx=25, pady=15)
        
        ctk.CTkButton(btn_row, text="Update", fg_color="#F1C40F", text_color="black", hover_color="#D4AC0D", font=("Inter", 11, "bold"), command=execute_update).pack(side="left", padx=5)
        
        arch_btn_text = "Restore" if is_arch else "Archive"
        ctk.CTkButton(btn_row, text=arch_btn_text, fg_color="#D3B8A7", text_color="black", hover_color="#BFA595", font=("Inter", 11, "bold"), command=execute_archive).pack(side="left", padx=5)
        
        ctk.CTkButton(btn_row, text="Close", fg_color="#E0E0E0", text_color="black", hover_color="#CCCCCC", font=("Inter", 11, "bold"), command=modal.destroy).pack(side="right", padx=5)

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