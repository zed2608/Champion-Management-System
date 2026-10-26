import customtkinter as ctk
from views.ui_thread import UiMixin
from tkinter import messagebox, ttk
from database import get_connection, log_action
from datetime import datetime
import cv2
from pyzbar.pyzbar import decode, ZBarSymbol
import difflib
from services.validators import fmt_qty
from services import validators as v
from services.errors import friendly_message
from services import project_service as ps
from ui import components as C
from ui import theme as T


class ProjectsView(UiMixin, ctk.CTkFrame):
    def __init__(self, parent, user_info):
        super().__init__(parent, fg_color="transparent")
        self._ui_init()

        self.user_info = user_info
        self.is_admin = self.user_info.get("role", "Staff") == "Admin"

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)

        self.req_cart = []

        self.build_top_tabs()

        uid = self.user_info.get("user_id")
        if uid:
            log_action(uid, "Viewed", "Projects",
                       "Opened Project Management module")

    def build_top_tabs(self):
        top_bar = ctk.CTkFrame(self, fg_color="transparent")
        top_bar.grid(row=0, column=0, sticky="ew", padx=20, pady=(10, 15))

        self.page_header = C.PageHeader(top_bar, "Project Management", "Plan, approve and track every deployment",
                                        primary=("+ Add Project", self.open_draft_project_modal) if self.is_admin else None)
        self.page_header.pack(fill="x")

        self.inner = ctk.CTkFrame(self, fg_color="transparent")
        self.inner.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 20))

        self.inner.grid_columnconfigure(0, weight=1)
        self.inner.grid_rowconfigure(0, weight=1)

        self.build_table_panel()

    def open_draft_project_modal(self, edit_row=None, reqs=None):
        # A new form must never render the previous project's cart. Clearing
        # after creating its row buttons leaves stale callbacks behind.
        self._begin_project_form()
        self.draft_modal = ctk.CTkToplevel(self)
        self.draft_modal.title(
            "Edit Project" if edit_row else "Draft Project Plan")
        C.fit_window(self.draft_modal, 500, 750)
        self.draft_modal.configure(fg_color=T.SURFACE)
        C.keep_above(self.draft_modal)
        self.draft_modal.grab_set()

        form_card = ctk.CTkScrollableFrame(
            self.draft_modal, fg_color=T.SURFACE, corner_radius=0)
        form_card.pack(fill="both", expand=True)

        ctk.CTkLabel(form_card, text="Edit Project Plan" if edit_row else "Draft Project Plan", font=T.font(16, "bold"), text_color=T.TEXT).pack(anchor="w", padx=20, pady=(20, 10))

        def field(label, ph):
            ctk.CTkLabel(form_card, text=label, font=T.font(12, "bold"), text_color=T.TEXT).pack(anchor="w", padx=20)
            e = C.field(form_card, placeholder_text=ph, takefocus=True)
            e.pack(fill="x", padx=20, pady=(5, 10))
            return e

        self.p_name = field("Project Name *", "e.g., Ayala Alabang Phase 2")

        ctk.CTkLabel(form_card, text="Project Description", font=T.font(12, "bold"), text_color=T.TEXT).pack(anchor="w", padx=20)
        self.p_desc = ctk.CTkTextbox(
            form_card, height=80, fg_color=T.SURFACE_ALT, border_width=1, border_color=T.BORDER)
        self.p_desc.pack(fill="x", padx=20, pady=(5, 10))

        self.p_head = field("Project Manager (optional)",
                            "e.g., Engr. Juan Santos")
        self.p_client = field("Client / Company *", "e.g., Makati Dev Corp")
        self.p_location = field("Site Location", "e.g., Block 4, Alabang")

        ctk.CTkLabel(form_card, text="Assigned Workers", font=T.font(12, "bold"), text_color=T.TEXT).pack(anchor="w", padx=20)

        worker_input_row = ctk.CTkFrame(form_card, fg_color="transparent")
        worker_input_row.pack(fill="x", padx=20, pady=(5, 5))

        self.worker_single_entry = C.field(worker_input_row, placeholder_text="Employee ID or name...", takefocus=True)
        self.worker_single_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        self.btn_add_worker = C.button(worker_input_row, compact=True, kind="primary", text="+ Add", width=55, command=self._add_worker_from_entry)
        self.btn_add_worker.pack(side="left", padx=(0, 5))
        self.btn_scan_worker = C.button(worker_input_row, compact=True, kind="primary", text="📷 Scan", width=65, command=self.scan_worker)
        self.btn_scan_worker.pack(side="left")

        self.worker_tags_frame = ctk.CTkScrollableFrame(
            form_card, fg_color=T.SURFACE_ALT, corner_radius=6, height=80)
        self.worker_tags_frame.pack(fill="x", padx=20, pady=(0, 12))
        self.workers_list = []
        self._refresh_worker_tags()

        ctk.CTkLabel(form_card, text="Tools & Equipment Needed *", font=T.font(12, "bold"), text_color=T.TEXT).pack(anchor="w", padx=20)
        self.browse_btn = C.button(form_card, kind="secondary", text="🔍 Browse Inventory Catalog", command=self.open_tool_picker)
        self.browse_btn.pack(fill="x", padx=20, pady=(5, 10))

        cart_bg = ctk.CTkFrame(form_card, fg_color=T.SURFACE_ALT, corner_radius=8)
        cart_bg.pack(fill="x", padx=20, pady=(0, 15))
        self.cart_scroll = ctk.CTkScrollableFrame(
            cart_bg, fg_color=T.SURFACE, height=120)
        self.cart_scroll.pack(fill="x", padx=10, pady=10)
        self.refresh_req_cart()

        row_dates = ctk.CTkFrame(form_card, fg_color="transparent")
        row_dates.pack(fill="x", padx=20, pady=(5, 10))
        row_dates.grid_columnconfigure(0, weight=1)
        row_dates.grid_columnconfigure(1, weight=1)

        start_f = ctk.CTkFrame(row_dates, fg_color="transparent")
        start_f.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        ctk.CTkLabel(start_f, text="Start Date (enter both dates)", font=T.font(12, "bold"), text_color=T.TEXT).pack(anchor="w")
        start_input_row = ctk.CTkFrame(start_f, fg_color="transparent")
        start_input_row.pack(fill="x", pady=(5, 0))
        self.p_start = C.field(
            start_input_row, placeholder_text="YYYY-MM-DD", takefocus=True)
        self.p_start.pack(side="left", fill="x", expand=True)
        self.p_start.bind(
            "<KeyRelease>", lambda e: self._format_date_mask(e, self.p_start))
        C.button(start_input_row, kind="secondary", text="📅", width=35, 
                      command=lambda: self.open_date_picker(self.p_start)).pack(side="left", padx=(5, 0))

        end_f = ctk.CTkFrame(row_dates, fg_color="transparent")
        end_f.grid(row=0, column=1, sticky="ew", padx=(5, 0))
        ctk.CTkLabel(end_f, text="End Date", font=T.font(12, "bold"), text_color=T.TEXT).pack(anchor="w")
        end_input_row = ctk.CTkFrame(end_f, fg_color="transparent")
        end_input_row.pack(fill="x", pady=(5, 0))
        self.p_end = C.field(
            end_input_row, placeholder_text="YYYY-MM-DD", takefocus=True)
        self.p_end.pack(side="left", fill="x", expand=True)
        self.p_end.bind(
            "<KeyRelease>", lambda e: self._format_date_mask(e, self.p_end))
        C.button(end_input_row, kind="secondary", text="📅", width=35, 
                      command=lambda: self.open_date_picker(self.p_end)).pack(side="left", padx=(5, 0))

        self.p_name.bind("<Return>", lambda e: self.p_head.focus_set())
        self.p_head.bind("<Return>", lambda e: self.p_client.focus_set())
        self.p_client.bind("<Return>", lambda e: self.p_location.focus_set())
        self.p_location.bind(
            "<Return>", lambda e: self.worker_single_entry.focus_set())
        self.worker_single_entry.bind("<Return>", lambda e: [
                                      self._add_worker_from_entry(), self.worker_single_entry.focus_set()])
        self.p_start.bind("<Return>", lambda e: self.p_end.focus_set())
        self.p_end.bind("<Return>", lambda e: self.save_project())

        btn_row = ctk.CTkFrame(self.draft_modal, fg_color="transparent")
        btn_row.pack(side="bottom", fill="x", padx=20, pady=(8, 16))
        btn_text = "Update Project" if edit_row else ("Save & Approve (Ready for Deployment)" if self.is_admin else "Save as Draft")
        self.btn_save = C.button(btn_row, kind="primary", text=btn_text, command=self.save_project)
        self.btn_save.pack(side="left", fill="x", expand=True, padx=(0, 5))
        C.button(btn_row, kind="secondary", text="Cancel", width=90, command=self.draft_modal.destroy).pack(side="right")

        if edit_row:
            self.editing_project_id = edit_row['project_id']
            self.editing_project_status = edit_row['status']

            self.p_name.insert(0, edit_row['name'])
            self.p_desc.insert("1.0", edit_row.get('description') or "")
            self.p_head.insert(0, edit_row.get('project_head') or "")
            self.p_client.insert(0, edit_row['client'])
            self.p_location.insert(0, edit_row['location'])
            self.p_start.insert(
                0, str(edit_row['start_date']) if edit_row.get('start_date') else "")
            self.p_end.insert(
                0, str(edit_row['end_date']) if edit_row.get('end_date') else "")

            self.workers_list = [w.strip() for w in (edit_row.get(
                'workers_assigned') or "").split(',') if w.strip()]
            self._refresh_worker_tags()
            
            self.req_cart = [{'tool_id': r['tool_id'], 'name': r['name'], 'uom': r['unit_of_measure'], 'qty': r['quantity'], 'needs_retrieval': r['status'] == 'Warning'} for r in (reqs or [])]
            
            raw_status = edit_row['status'].replace(' (OVERDUE)', '')
            if raw_status in ['Ongoing', 'Completed', 'Cancelled', 'Declined']:
                self.p_name.configure(state="disabled", fg_color=T.SURFACE_ALT)
                self.p_client.configure(state="disabled", fg_color=T.SURFACE_ALT)
                self.p_head.configure(state="disabled", fg_color=T.SURFACE_ALT)
                self.p_location.configure(state="disabled", fg_color=T.SURFACE_ALT)
                self.p_start.configure(state="disabled", fg_color=T.SURFACE_ALT)
                self.p_end.configure(state="disabled", fg_color=T.SURFACE_ALT)
                self.worker_single_entry.configure(state="disabled", fg_color=T.SURFACE_ALT)
                self.btn_add_worker.configure(state="disabled")
                self.btn_scan_worker.configure(state="disabled")
                self.browse_btn.configure(state="disabled")
                self.btn_save.configure(state="disabled")
                self._is_cart_locked = True
            else:
                self._is_cart_locked = False
            self.refresh_req_cart()

            # --- DATA INTEGRITY: Lock fields for confirmed/deployed projects ---
            raw_edit_status = (edit_row.get('status')
                               or '').replace(' (OVERDUE)', '')
            is_locked = raw_edit_status in ('Approved', 'Ongoing')
            if is_locked:
                lock_color=T.SURFACE_MUTED
                for widget in (self.p_client, self.p_head, self.p_location):
                    widget.configure(state="disabled", fg_color=lock_color)
                ctk.CTkLabel(form_card, text="Client, Head & Location are locked for confirmed projects.\nDates, Workers and Tools can still be updated.",
                             font=T.font(12), text_color=T.DANGER_TEXT, wraplength=440).pack(anchor="w", padx=20, pady=(0, 5))
            # ----------------------------------------------------------------------
        else:
            self.refresh_req_cart()

        self.p_name.focus_set()

    def _begin_project_form(self):
        self.editing_project_id = None
        self.editing_project_status = None
        self.workers_list = []
        self.req_cart = []
        self._is_cart_locked = False

    def _format_date_mask(self, event, entry_widget):
        if event.keysym in ('BackSpace', 'Delete', 'Left', 'Right', 'Up', 'Down', 'Tab'):
            return

        text = entry_widget.get().replace('-', '')
        if not text.isdigit() and text != "":
            text = ''.join(filter(str.isdigit, text))

        formatted = ''
        for i, char in enumerate(text[:8]):
            if i == 4 or i == 6:
                formatted += '-'
            formatted += char

        current_val = entry_widget.get()
        if current_val != formatted:
            entry_widget.delete(0, 'end')
            entry_widget.insert(0, formatted)

    def open_date_picker(self, entry_widget):
        try:
            from tkcalendar import Calendar
        except ImportError:
            messagebox.showerror(
                "Dependency Missing", "Please install the calendar module by running in your terminal:\n\npip install tkcalendar", parent=self.draft_modal)
            return

        top = ctk.CTkToplevel(self.draft_modal)
        top.title("Select Date")
        C.keep_above(top, self.draft_modal)
        top.grab_set()
        top.resizable(False, False)

        top.update_idletasks()
        sw = top.winfo_screenwidth()
        sh = top.winfo_screenheight()
        x = (sw - 280) // 2
        y = (sh - 260) // 2
        top.geometry(f"280x260+{x}+{y}")

        current_date = entry_widget.get().strip()
        sel_date = datetime.now()
        if current_date:
            try:
                sel_date = datetime.strptime(current_date, "%Y-%m-%d")
            except ValueError:
                pass

        cal_kwargs = {
            'selectmode': 'day', 'date_pattern': 'y-mm-dd',
            'year': sel_date.year, 'month': sel_date.month, 'day': sel_date.day,
            'background': T.PRIMARY, 'foreground': 'white', 'borderwidth': 0,
            'headersbackground': T.SURFACE_ALT, 'headersforeground': 'black',
            'normalbackground': 'white', 'normalforeground': 'black',
            'weekendbackground': 'white', 'weekendforeground': 'black',
            'othermonthforeground': 'gray', 'othermonthweforeground': 'gray'
        }

        if entry_widget == getattr(self, "p_end", None):
            start_val = self.p_start.get().strip()
            if start_val:
                try:
                    min_dt = datetime.strptime(start_val, "%Y-%m-%d")
                    cal_kwargs['mindate'] = min_dt.date()
                    if sel_date < min_dt:
                        cal_kwargs.update(
                            {'year': min_dt.year, 'month': min_dt.month, 'day': min_dt.day})
                except ValueError:
                    pass
        elif entry_widget == getattr(self, "p_start", None):
            end_val = self.p_end.get().strip()
            if end_val:
                try:
                    max_dt = datetime.strptime(end_val, "%Y-%m-%d")
                    cal_kwargs['maxdate'] = max_dt.date()
                    if sel_date > max_dt:
                        cal_kwargs.update(
                            {'year': max_dt.year, 'month': max_dt.month, 'day': max_dt.day})
                except ValueError:
                    pass

        cal = Calendar(top, **cal_kwargs)
        cal.pack(fill="both", expand=True, padx=10, pady=(10, 5))

        def set_date():
            entry_widget.delete(0, "end")
            entry_widget.insert(0, cal.get_date())
            top.destroy()

        C.button(top, kind="primary", text="Confirm", command=set_date).pack(pady=(0, 10), padx=10, fill="x")

    def _add_worker_from_entry(self):
        val = self.worker_single_entry.get().strip()
        if val and val not in self.workers_list:
            self.workers_list.append(val)
            self._refresh_worker_tags()
        self.worker_single_entry.delete(0, 'end')

    def _refresh_worker_tags(self):
        for w in self.worker_tags_frame.winfo_children():
            w.destroy()
        if not self.workers_list:
            ctk.CTkLabel(self.worker_tags_frame, text="No workers added yet.",
                         text_color=T.TEXT_MUTED, font=T.font(12)).pack(pady=8)
            return
        for idx, worker in enumerate(self.workers_list):
            tag_row = ctk.CTkFrame(
                self.worker_tags_frame, fg_color=T.SURFACE, corner_radius=5, height=28)
            tag_row.pack(fill="x", pady=2, padx=5)
            tag_row.pack_propagate(False)
            ctk.CTkLabel(tag_row, text=f"👷 {worker}", font=T.font(12), text_color=T.PRIMARY).pack(side="left", padx=8)
            if not getattr(self, '_is_cart_locked', False):
                C.button(tag_row, text="✕", kind="danger", compact=True, width=28,
                         command=lambda i=idx: self._remove_worker(i)).pack(side="right", padx=5)

    def _remove_worker(self, idx):
        if 0 <= idx < len(self.workers_list):
            self.workers_list.pop(idx)
            self._refresh_worker_tags()

    def open_tool_picker(self):
        modal = ctk.CTkToplevel(self)
        modal.title("Inventory Requisition Catalog")
        C.fit_window(modal, 900, 600)
        modal.configure(fg_color=T.SURFACE)
        C.keep_above(modal, self.draft_modal)
        modal.grab_set()
        # The catalog remains above the edit form until the catalog closes.
        ctk.CTkLabel(modal, text="Select Items for Project Requisition", font=T.font(16, "bold"), text_color=T.TEXT).pack(pady=(20, 5))
        ctk.CTkLabel(modal, text="Choose a quantity and click + Add. This plans items for the project; stock changes when items are issued.",
                     font=T.font(12), text_color=T.TEXT_MUTED).pack(pady=(0, 10))

        search_frame = ctk.CTkFrame(modal, fg_color="transparent")
        search_frame.pack(fill="x", padx=20, pady=(0, 5))
        search_controls = ctk.CTkFrame(search_frame, fg_color="transparent")
        search_controls.pack(side="right")

        ctk.CTkLabel(search_controls, text="Name:", font=T.font(12, "bold"), text_color=T.TEXT_MUTED).pack(side="left")
        search_name = C.field(
            search_controls, placeholder_text="Item name...", width=180, takefocus=True)
        search_name.pack(side="left", padx=(5, 10))

        ctk.CTkLabel(search_controls, text="PID:", font=T.font(12, "bold"), text_color=T.TEXT_MUTED).pack(side="left")
        search_pid = C.field(
            search_controls, placeholder_text="Product ID...", width=100, takefocus=True)
        search_pid.pack(side="left", padx=(5, 10))

        def do_search(): load_catalog(name_q=search_name.get().strip(),
                                      pid_q=search_pid.get().strip())

        def do_reset():
            if (search_name.get() or search_pid.get()) and not C.confirm(
                    "Reset item search", "Clear the item search and show all items?", parent=modal):
                return
            search_name.delete(0, 'end'); search_pid.delete(0, 'end'); load_catalog()

        C.button(search_controls, kind="primary", text="Search", width=80, command=do_search).pack(side="left", padx=5)
        C.button(search_controls, kind="secondary", text="↻ Reset", width=80,
                      command=do_reset).pack(side="left", padx=5)

        search_name.bind("<Return>", lambda e: do_search())
        search_pid.bind("<Return>", lambda e: do_search())
        search_name.focus_set()

        # Reverted back to safe default vertical scrolling
        list_scroll = ctk.CTkScrollableFrame(modal, fg_color="transparent")
        list_scroll.pack(fill="both", expand=True, padx=20, pady=(10, 10))

        def load_catalog(name_q="", pid_q=""):
            for w in list_scroll.winfo_children():
                w.destroy()

            cat_inner = ctk.CTkFrame(list_scroll, fg_color="transparent")
            cat_inner.pack(fill="x", expand=True)

            cols = ["PID", "Type", "Item Name", "UoM",
                    "In stock / Total", "Needed", "Action"]
            weights = [1, 1, 3, 1, 1, 1, 1]

            for col, w in enumerate(weights):
                cat_inner.grid_columnconfigure(col, weight=w, uniform="c_cols")

            # Render Headers
            for col, text in enumerate(cols):
                cell = ctk.CTkFrame(
                    cat_inner, fg_color=T.PRIMARY, corner_radius=0)
                cell.grid(row=0, column=col, sticky="nsew", pady=(0, 2))
                ctk.CTkLabel(cell, text=text, font=T.font(12, "bold"), text_color=T.WHITE, anchor="center").pack(fill="both", expand=True, padx=5, pady=8)

            conn = get_connection()
            if not conn:
                return
            try:
                cursor = conn.cursor(dictionary=True)
                query = """
                    SELECT t.tool_id, t.name, IFNULL(t.item_type,'Equipment') as type,
                           IFNULL(t.unit_of_measure,'pcs') as uom,
                           IFNULL(i.quantity_available, 0) as avail,
                           IFNULL(i.quantity_total, 0) as total
                    FROM tool t JOIN inventory i ON t.tool_id = i.tool_id
                    WHERE t.is_archived = 0
                """
                params = []
                if name_q and pid_q:
                    query += " AND (t.name LIKE %s AND t.tool_id LIKE %s)"
                    params = [f"%{name_q}%", f"%{pid_q}%"]
                elif name_q:
                    query += " AND t.name LIKE %s"
                    params = [f"%{name_q}%"]
                elif pid_q:
                    query += " AND t.tool_id LIKE %s"
                    params = [f"%{pid_q}%"]

                cursor.execute(query, params)
                results = cursor.fetchall()

                if not results:
                    ctk.CTkLabel(cat_inner, text="No items found. Try a different search.", text_color=T.TEXT_MUTED).grid(
                        row=1, column=0, columnspan=len(cols), pady=20)
                    return

                for i, row in enumerate(results):
                    r_idx = i + 1
                    bg=T.SURFACE_ALT if i % 2 == 0 else "white"

                    def make_cell(col_idx, text, color, bold=False, wrap=0):
                        cell = ctk.CTkFrame(
                            cat_inner, fg_color=bg, corner_radius=0)
                        cell.grid(row=r_idx, column=col_idx, sticky="nsew")
                        
                        l = ctk.CTkLabel(cell, text=str(text), font=T.font(12, "bold" if bold else "normal"), text_color=color, justify="center")
                        if wrap > 0:
                            l.configure(wraplength=wrap)
                        l.pack(fill="both", expand=True, padx=5, pady=10)

                    make_cell(0, row['tool_id'], "gray")
                    make_cell(1, row['type'], T.WARNING_STRONG if row['type']
                              == "Consumable" else T.TEXT, bold=True)
                    # Safe fixed wraplength ensures it wraps gracefully without lagging the UI
                    make_cell(2, row['name'], "black", bold=True, wrap=200)
                    make_cell(3, row['uom'], "gray")

                    avail = f"{fmt_qty(row['avail'])}" if row['avail'] else "0"
                    tot = f"{fmt_qty(row['total'])}" if row['total'] else "0"
                    stock_color=T.DANGER if float(
                        row['avail']) <= 0 else T.SUCCESS_TEXT
                    make_cell(4, f"{avail}/{tot}", stock_color, bold=True)

                    inp_cell = ctk.CTkFrame(
                        cat_inner, fg_color=bg, corner_radius=0)
                    inp_cell.grid(row=r_idx, column=5, sticky="nsew")
                    qty_entry = C.field(
                        inp_cell, width=55, justify="center")
                    # pack(expand=True) forces it into dead center of the cell
                    qty_entry.pack(expand=True, pady=10)
                    qty_entry.bind("<Return>", lambda e, r=row,
                                   q_e=qty_entry: self.add_from_catalog(r, q_e, modal))

                    btn_cell = ctk.CTkFrame(
                        cat_inner, fg_color=bg, corner_radius=0)
                    btn_cell.grid(row=r_idx, column=6, sticky="nsew")
                    btn = C.button(btn_cell, compact=True, kind="primary", text="+ Add", width=55, command=lambda r=row, q_e=qty_entry: self.add_from_catalog(r, q_e, modal))
                    # Perfectly centered inside cell
                    btn.pack(expand=True, pady=10)

            except Exception as e:
                ctk.CTkLabel(cat_inner, text=friendly_message(e), text_color=T.DANGER_TEXT).grid(
                    row=1, column=0, columnspan=len(cols), pady=10)
            finally:
                if conn.is_connected():
                    cursor.close()
                    conn.close()

        modal.catalog_status = ctk.CTkLabel(modal, text="In stock stays the same until an item is issued.",
                                               font=T.font(12), text_color=T.TEXT_SECONDARY)
        modal.catalog_status.pack(side="bottom", pady=(0, 8))
        load_catalog()
        C.button(modal, kind="secondary", text="Done / Close Catalog", 
                      command=modal.destroy).pack(pady=(5, 15))

    def add_from_catalog(self, row_data, qty_entry, modal):
        try:
            req_qty = v.item_quantity(qty_entry.get(), row_data['type'], row_data['uom'])
        except v.ValidationError as e:
            return messagebox.showwarning("Check quantity", str(e), parent=modal)

        existing = next((item for item in self.req_cart if item['tool_id'] == row_data['tool_id']), None)
        new_qty = req_qty + (v.parse_quantity(existing['qty']) if existing else 0)
        if new_qty > v.parse_quantity(row_data['total'], allow_zero=True):
            return messagebox.showerror("Quantity too high", f"The company owns {fmt_qty(row_data['total'])} {row_data['uom']} in total.", parent=modal)

        needs_retrieval = new_qty > v.parse_quantity(row_data['avail'], allow_zero=True)
        action = "Update" if existing else "Add"
        message = (f"{action} {fmt_qty(req_qty)} {row_data['uom']} of {row_data['name']} to this project?\n\n"
                   "This is a planned requirement. The stock count changes when the item is issued.")
        if needs_retrieval:
            message += (f"\n\nOnly {fmt_qty(row_data['avail'])} {row_data['uom']} are currently in stock. "
                        "The remaining items must be returned before they can be issued.")
        if not C.confirm("Confirm project requirement", message, parent=modal):
            return

        if existing:
            existing['qty'] = new_qty
            existing['needs_retrieval'] = existing['needs_retrieval'] or needs_retrieval
            self.refresh_req_cart()
            qty_entry.delete(0, 'end')
            self._catalog_added(modal, row_data, new_qty)
            return

        self.req_cart.append({
            'tool_id': row_data['tool_id'], 'name': row_data['name'],
            'uom': row_data['uom'], 'qty': req_qty, 'needs_retrieval': needs_retrieval
        })
        self.refresh_req_cart()
        qty_entry.delete(0, 'end')
        self._catalog_added(modal, row_data, new_qty)

    @staticmethod
    def _catalog_added(modal, row_data, total_qty):
        modal.catalog_status.configure(
            text=f"Added to project: {row_data['name']} ({fmt_qty(total_qty)} {row_data['uom']}). Stock is unchanged.",
            text_color=T.SUCCESS_TEXT)

    def refresh_req_cart(self):
        for w in self.cart_scroll.winfo_children():
            w.destroy()
        if not self.req_cart:
            ctk.CTkLabel(self.cart_scroll, text="No items selected.",
                         text_color=T.TEXT_MUTED, font=T.font(12)).pack(pady=20)
            return
        for item in self.req_cart:
            row = ctk.CTkFrame(self.cart_scroll, fg_color="transparent")
            row.pack(fill="x", pady=2)
            warning_icon = "⚠️ " if item.get('needs_retrieval') else "✓ "
            text_col=T.WARNING_STRONG if item.get('needs_retrieval') else "black"
            info = f"{warning_icon}{item['name']} ({fmt_qty(item['qty'])} {item['uom']})"
            ctk.CTkLabel(row, text=info, font=T.font(12, "bold"), text_color=text_col).pack(side="left", padx=5)
            if not getattr(self, '_is_cart_locked', False):
                C.button(row, text="✕", compact=True, width=28, kind="danger",
                         command=lambda tool_id=item['tool_id']: self.remove_req_from_cart(tool_id)).pack(side="right")

    def remove_req_from_cart(self, tool_id):
        item = next((r for r in self.req_cart if r['tool_id'] == tool_id), None)
        if item is None or getattr(self, '_is_cart_locked', False):
            return
        if not C.confirm("Remove project item", f"Remove {item['name']} from this project plan?",
                         parent=self.draft_modal):
            return
        self.req_cart.remove(item)
        self.refresh_req_cart()

    def scan_worker(self):
        try:
            cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        except Exception:
            cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            return messagebox.showerror("Camera Error", "No webcam detected.", parent=self.draft_modal)

        detected_data = None
        cv2.namedWindow('Scan Worker ID', cv2.WINDOW_NORMAL)
        cv2.setWindowProperty('Scan Worker ID', cv2.WND_PROP_TOPMOST, 1)

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            cv2.putText(frame, "Scan Employee ID (Press 'Q' to Cancel)",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            for barcode in decode(frame, symbols=[ZBarSymbol.QRCODE]):
                raw_data = barcode.data.decode('utf-8').strip()
                if "Employee ID:" in raw_data:
                    first_line = raw_data.split('\n')[0]
                    detected_data = first_line.replace(
                        "Employee ID:", "").strip()
                elif "Tag ID:" in raw_data:
                    detected_data = "INVALID_TOOL_TAG"
                else:
                    detected_data = raw_data
                break
            cv2.imshow('Scan Worker ID', frame)
            if detected_data or cv2.waitKey(1) & 0xFF == ord('q'):
                break

        cap.release()
        cv2.destroyAllWindows()

        if detected_data == "INVALID_TOOL_TAG":
            return messagebox.showwarning("Invalid Scan", "You scanned a Tool Tag. Please scan a valid Employee ID Badge.", parent=self.draft_modal)

        if detected_data:
            if detected_data not in self.workers_list:
                self.workers_list.append(detected_data)
                self._refresh_worker_tags()

    def _validate_date(self, date_str, field_name, parent_win=None):
        if not date_str:
            return True
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
            return True
        except ValueError:
            messagebox.showerror("Invalid Date",
                                 f"{field_name} must be in YYYY-MM-DD format (e.g., 2025-01-15).",
                                 parent=parent_win or self.winfo_toplevel())
            return False

    def save_project(self, publish=True):
        name = self.p_name.get().strip()
        client = self.p_client.get().strip()
        project_head = self.p_head.get().strip()
        workers_str = ", ".join(self.workers_list) if self.workers_list else ""
        desc_text = self.p_desc.get("1.0", "end-1c").strip()
        start_date = self.p_start.get().strip() or None
        end_date = self.p_end.get().strip() or None

        if not name or not client:
            return messagebox.showerror("Error", "Project Name and Client are required.", parent=self.draft_modal)
        if not self._validate_date(start_date, "Start Date", self.draft_modal):
            return
        if not self._validate_date(end_date, "End Date", self.draft_modal):
            return

        if bool(start_date) != bool(end_date):
            return messagebox.showerror("Missing Date", "Enter both Start Date and End Date, or leave both blank.", parent=self.draft_modal)

        if start_date and end_date:
            if datetime.strptime(end_date, "%Y-%m-%d") < datetime.strptime(start_date, "%Y-%m-%d"):
                return messagebox.showerror("Invalid Date Range", "The End Date cannot be earlier than the Start Date.", parent=self.draft_modal)

        if not self.req_cart:
            return messagebox.showerror("Error", "Please add at least one tool requirement.", parent=self.draft_modal)

        editing_id = getattr(self, "editing_project_id", None)
        try:
            exact, similar = ps.find_similar_names(name, exclude_project_id=editing_id)
        except Exception as e:
            return messagebox.showerror("Error", friendly_message(e), parent=self.draft_modal)
        if exact:
            return messagebox.showerror("Duplicate Name", f"An active project named '{name}' already exists.", parent=self.draft_modal)
        if similar:
            sim_list = "\n".join([f"• {sn}" for sn in similar])
            msg = f"Similar active project names already exist:\n\n{sim_list}\n\nAre you sure you want to save '{name}'?"
            if not C.confirm("Similar Name Detected", msg, parent=self.draft_modal):
                return

        data = {
            "name": name, "client": client, "project_head": project_head, "location": self.p_location.get(),
            "description": desc_text, "start_date": start_date, "end_date": end_date,
            "workers": list(self.workers_list),
            "requirements": [{"tool_id": it["tool_id"], "qty": it["qty"], "needs_retrieval": it.get("needs_retrieval")}
                             for it in self.req_cart],
        }
        summary = "\n".join(f"• {it['name']}: {fmt_qty(it['qty'])} {it['uom']}" for it in self.req_cart)
        verb = "Save changes to" if editing_id else "Create and approve"
        if not C.confirm("Confirm project", f"{verb} '{name}'?\n\nClient: {client}\nDates: {start_date or 'Not set'} to {end_date or 'Not set'}\nRequired items:\n{summary}", parent=self.draft_modal):
            return
        try:
            # [STATE-MACHINE][RBAC] Admin only; validated server-side; edit DIFFS the requirement lines (no delete-and-reinsert);
            # an Admin-created project is auto-approved (no separate approve step).
            if editing_id:
                expected = (getattr(self, "editing_project_status", None) or "Pending").replace(" (OVERDUE)", "")
                res = ps.update_project(self.user_info, editing_id, data, expected)
                action_text = "Updated"
            else:
                res = ps.create_project(self.user_info, data)
                action_text = "Drafted & Approved" if res["status"] == "Approved" else "Drafted"
        except Exception as e:
            return messagebox.showerror("Could not save project", friendly_message(e), parent=self.draft_modal)
        project_id = res["project_id"]

        if self.user_info.get("user_id"):
            log_action(self.user_info['user_id'], action_text, "Projects",
                       f"{action_text} project '{name}' (ID: {project_id}).")
        messagebox.showinfo("Success", f"Project successfully {action_text.lower()}!", parent=self.draft_modal)

        self.p_name.delete(0, 'end')
        self.p_desc.delete("1.0", "end")
        self.p_head.delete(0, 'end')
        self.p_client.delete(0, 'end')
        self.p_location.delete(0, 'end')
        self.p_start.delete(0, 'end')
        self.p_end.delete(0, 'end')
        self.workers_list.clear()
        self._refresh_worker_tags()
        self.req_cart.clear()
        self.refresh_req_cart()
        self.editing_project_id = None
        self.editing_project_status = None
        self.draft_modal.destroy()
        self.load_projects()

    def build_table_panel(self):
        table_card = ctk.CTkFrame(
            self.inner, fg_color=T.SURFACE, corner_radius=10)
        table_card.grid(row=0, column=0, sticky="nsew", padx=0)
        table_card.grid_columnconfigure(0, weight=1)
        table_card.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(table_card, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(20, 10))
        ctk.CTkLabel(top, text="Project Deployment Plans", font=T.font(16, "bold"), text_color=T.TEXT).pack(side="left")

        self.proj_search_var = ctk.StringVar()
        self.proj_search = C.field(top, placeholder_text="Search project or client...", width=C.SEARCH_WIDTH, takefocus=True, textvariable=self.proj_search_var)
        self.proj_search.pack(side="right", padx=(5, 0))

        self._proj_search_timer = None
        def on_proj_search(*args):
            if self._proj_search_timer: self.after_cancel(self._proj_search_timer)
            self._proj_search_timer = self.after(300, lambda: self.load_projects(self.proj_search.get().strip()))
        self.proj_search_var.trace_add("write", on_proj_search)
        
        if not self.is_admin:
            ctk.CTkLabel(top, text="View only: ask an administrator to create or change projects.", font=T.font(12, "italic"),
                         text_color=T.TEXT_MUTED).pack(side="right", padx=(10, 10))

        # Removed the crashing "both" orientation - back to safe standard vertical scrolling
        self.project_scroll = ctk.CTkScrollableFrame(
            table_card, fg_color="transparent")
        self.project_scroll.pack(
            fill="both", expand=True, padx=20, pady=(5, 20))

        self.load_projects()

    def load_projects(self, search_q=""):
        for w in self.project_scroll.winfo_children():
            w.destroy()

        # --- NEW SAFE UNIFORM GRID ---
        table_inner = ctk.CTkFrame(self.project_scroll, fg_color="transparent")
        table_inner.pack(fill="x", expand=True)

        headers = ["ID", "Project Name", "Client",
                   "Project Head", "Status", "Actions"]
        weights = [1, 3, 2, 2, 2, 1]
        min_sizes = [50, 180, 120, 120, 100, 80]

        # Enforce exact column alignment
        for col, (w, min_w) in enumerate(zip(weights, min_sizes)):
            table_inner.grid_columnconfigure(
                col, weight=w, minsize=min_w, uniform="p_cols")

        # Header Row
        for col, text in enumerate(headers):
            cell = ctk.CTkFrame(
                table_inner, fg_color=T.PRIMARY, corner_radius=0)
            cell.grid(row=0, column=col, sticky="nsew", pady=(0, 2))
            lbl = ctk.CTkLabel(cell, text=text, font=T.font(12, "bold"), text_color=T.WHITE, anchor="center")
            lbl.pack(fill="both", expand=True, padx=5, pady=10)

        conn = get_connection()
        if not conn:
            return
        try:
            cursor = conn.cursor(dictionary=True)
            sql = '''
                SELECT p.*, a.full_name as admin_approver,
                       CASE
                           WHEN p.status IN ('Approved', 'Ongoing') AND p.end_date < CURDATE() THEN CONCAT(p.status, ' (OVERDUE)')
                           ELSE p.status
                       END as display_status
                FROM projects p
                LEFT JOIN user a ON p.approved_by = a.user_id
                WHERE p.archived_at IS NULL
            '''
            params = []
            if search_q:
                sql += " AND (p.name LIKE %s OR p.client LIKE %s OR p.project_head LIKE %s)"
                params = [f"%{search_q}%", f"%{search_q}%", f"%{search_q}%"]

            sql += " ORDER BY p.project_id DESC"
            cursor.execute(sql, tuple(params))
            results = cursor.fetchall()

            if not results:
                ctk.CTkLabel(table_inner, text="No projects found.", text_color=T.TEXT_MUTED).grid(
                    row=1, column=0, columnspan=len(headers), pady=20)
                return

            for i, row in enumerate(results):
                row["status"] = row["display_status"]
                r_idx = i + 1
                bg=T.SURFACE_ALT if i % 2 == 0 else "white"

                # Define data
                vals = [
                    str(row["project_id"]),
                    row["name"],
                    row["client"],
                    row.get("project_head") or "—",
                    row["status"]
                ]

                # Render Data Cells
                for col, val in enumerate(vals):
                    cell = ctk.CTkFrame(
                        table_inner, fg_color=bg, corner_radius=0)
                    cell.grid(row=r_idx, column=col, sticky="nsew")

                    txt_color=T.TEXT_MUTED if col == 4 and "Draft" in val else (
                        T.WARNING_STRONG if col == 4 and "Pending" in val else (T.SUCCESS_TEXT if col == 4 and "Approved" in val else T.TEXT))
                    font_w = "bold" if col == 4 else "normal"

                    lbl = ctk.CTkLabel(cell, text=val, font=T.font(12, font_w), text_color=txt_color, justify="center", anchor="center")
                    # Set wrap to ensure long text stacks downward instead of pushing grid wide
                    lbl.configure(wraplength=min_sizes[col] - 10)

                    lbl.pack(fill="both", expand=True, padx=10, pady=12)

                # Render Actions Cell Button
                btn_cell = ctk.CTkFrame(
                    table_inner, fg_color=bg, corner_radius=0)
                btn_cell.grid(row=r_idx, column=5, sticky="nsew")
                
                btn_color=T.INFO if row['status'] == 'Pending' else T.BORDER_STRONG
                btn_text = "Review" if row['status'] == 'Pending' else "View"
                
                btn = ctk.CTkButton(btn_cell, text=btn_text, width=65, height=28, fg_color=btn_color, text_color=T.ON_INFO if row['status'] == 'Pending' else T.TEXT,
                                    hover_color=T.INFO_HOVER, font=T.font(12, "bold"), command=lambda r=row: self.open_project_modal(r))
                # expand=True forces the button perfectly into the horizontal and vertical center
                btn.pack(expand=True, pady=10)

        except Exception as e:
            ctk.CTkLabel(table_inner, text=friendly_message(e), text_color=T.DANGER_TEXT).grid(
                row=1, column=0, columnspan=len(headers), pady=20)
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    def open_project_modal(self, row):
        modal = ctk.CTkToplevel(self)
        modal.title(f"Project Overview: {row['name']}")
        # Added extra space so description doesn't clip
        modal.geometry("650x750")
        modal.configure(fg_color=T.SURFACE)
        C.keep_above(modal)
        modal.grab_set()
        modal.update_idletasks()
        x = (modal.winfo_screenwidth() // 2) - (650 // 2)
        y = (modal.winfo_screenheight() // 2) - (750 // 2)
        modal.geometry(f"650x750+{x}+{y}")

        ctk.CTkLabel(modal, text=row['name'], font=T.font(16, "bold"), text_color=T.TEXT).pack(pady=(20, 3))
        status_color=T.WARNING_STRONG if row['status'] == "Pending" else T.SUCCESS_TEXT
        ctk.CTkLabel(modal, text=f"Status: {row['status']}", font=T.font(12, "bold"), text_color=status_color).pack(pady=(0, 5))

        scroll = ctk.CTkScrollableFrame(modal, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=20, pady=(0, 10))

        details_frame = ctk.CTkFrame(
            scroll, fg_color=T.SURFACE_ALT, corner_radius=8)
        details_frame.pack(fill="x", pady=(0, 10))

        def add_detail(lbl, val):
            row_f = ctk.CTkFrame(details_frame, fg_color="transparent")
            row_f.pack(fill="x", padx=15, pady=(5, 0))
            ctk.CTkLabel(row_f, text=lbl, font=T.font(12, "bold"),
                         text_color=T.PRIMARY, width=140, anchor="w").pack(side="left")
            ctk.CTkLabel(row_f, text=val or "None specified", font=T.font(12), text_color=T.TEXT,
                         wraplength=400, justify="left").pack(side="left", fill="x", expand=True)

        add_detail("Client:", row['client'])
        add_detail("Site Location:", row['location'])
        add_detail("Description:", row.get('description') or "—")
        add_detail("Project Head:", row.get('project_head') or "—")
        add_detail("Assigned Workers:", row.get(
            'workers_assigned') or "None assigned")
        add_detail(
            "Schedule:", f"Start: {row['start_date']}   →   End: {row['end_date']}")

        ctk.CTkFrame(details_frame, height=8, fg_color="transparent").pack()

        ctk.CTkLabel(scroll, text="Tools & Equipment Requisition", font=T.font(12, "bold"), text_color=T.PRIMARY).pack(anchor="w", pady=(8, 3))
        tools_scroll = ctk.CTkScrollableFrame(
            scroll, fg_color=T.SURFACE, corner_radius=8, height=160)
        tools_scroll.pack(fill="x", pady=(0, 10))

        reqs = []
        conn = get_connection()
        if conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute('''
                SELECT t.tool_id, t.name, t.item_type, t.unit_of_measure, pr.quantity, pr.status
                FROM project_requirements pr
                JOIN tool t ON pr.tool_id = t.tool_id
                WHERE pr.project_id = %s
            ''', (row['project_id'],))
            reqs = cursor.fetchall()
            cursor.close()
            conn.close()

        if reqs:
            for req in reqs:
                warning_icon = "⚠️ " if req['status'] == 'Warning' else "✓ "
                text_col=T.WARNING_STRONG if req['status'] == 'Warning' else T.TEXT
                row_str = f"{warning_icon}{req['name']}  |  {fmt_qty(req['quantity'])} {req['unit_of_measure']} ({req['item_type']})"
                req_row = ctk.CTkFrame(
                    tools_scroll, fg_color="transparent", height=30)
                req_row.pack(fill="x", pady=1)
                ctk.CTkLabel(req_row, text=row_str, font=T.font(12, "bold" if req['status'] == 'Warning' else "normal"), text_color=text_col).pack(anchor="w", padx=8)
        else:
            ctk.CTkLabel(tools_scroll, text="No tools listed.",
                         text_color=T.TEXT_MUTED).pack(pady=10)

        if 'Approved' in row['status'] and row.get('admin_approver'):
            ctk.CTkLabel(scroll, text=f"✅ Approved by: {row['admin_approver']}", font=T.font(12, "bold"), text_color=T.SUCCESS_TEXT).pack(anchor="w", pady=(0, 5))

        btn_frame = ctk.CTkFrame(modal, fg_color="transparent")
        btn_frame.pack(side="bottom", fill="x", padx=20, pady=15)

        def update_proj_status(new_status):
            current = row['status'].replace(' (OVERDUE)', '')
            has_warnings = any(r['status'] == 'Warning' for r in reqs)
            msg = f"Mark this project as {new_status}?"
            if new_status == 'Approved' and has_warnings:
                msg = "⚠️ WARNING: Some required tools are deployed elsewhere and currently out of stock.\n\nMark as Ready for Deployment anyway?"
            if not C.confirm("Confirm Status", msg, parent=modal):
                return
            try:
                # [STATE-MACHINE] only allowed edges, and only if the project is still in the status this screen showed
                res = ps.transition(self.user_info, row['project_id'], new_status, current)
            except Exception as e:
                return messagebox.showerror("Could not change status", friendly_message(e), parent=modal)
            if self.user_info.get("user_id"):
                log_action(self.user_info['user_id'], "Updated", "Projects", f"Project '{row['name']}' status changed to {res['status']}.")
            modal.destroy()
            self.load_projects()

        def trigger_edit_mode():
            modal.destroy()
            self.open_draft_project_modal(edit_row=row, reqs=reqs)

        raw_status = row['status'].replace(' (OVERDUE)', '')
        if raw_status in ['Pending', 'Approved'] and self.is_admin:
            C.button(btn_frame, kind="secondary", text="Edit Project", width=90, command=trigger_edit_mode).pack(side="left", padx=5)
            
        if raw_status == 'Pending' and self.is_admin:
            C.button(btn_frame, kind="primary", text="Ready for Deployment", command=lambda: update_proj_status('Approved')).pack(side="left", padx=5)
            
        if raw_status == 'Approved' and self.is_admin:
            C.button(btn_frame, kind="primary", text="Deploy / Mark Ongoing", command=lambda: update_proj_status('Ongoing')).pack(side="left", padx=5)
            
        if raw_status == 'Ongoing' and self.is_admin:
            C.button(btn_frame, kind="primary", text="Complete Project", command=lambda: update_proj_status('Completed')).pack(side="left", padx=5)
            
        if raw_status in ['Pending', 'Approved', 'Ongoing'] and self.is_admin:
            btn_text = "Decline Project" if raw_status == 'Pending' else "Cancel Project"
            cmd_status = "Declined" if raw_status == 'Pending' else "Cancelled"
            C.button(btn_frame, kind="danger", text=btn_text, command=lambda s=cmd_status: update_proj_status(s)).pack(side="left", padx=5)
            
        if raw_status in ['Completed', 'Declined', 'Cancelled'] and self.is_admin:
            C.button(btn_frame, kind="secondary", text="Archive", command=lambda: self.archive_project(row['project_id'], row['name'], modal, raw_status)).pack(side="left", padx=5)
            
        C.button(btn_frame, kind="secondary", text="Close", width=70, command=modal.destroy).pack(side="right", padx=5)

    def archive_project(self, project_id, project_name, modal, current_status=None):
        if not C.confirm("Confirm Archive", f"Archive project '{project_name}' to the archive vault?\n\nIt will be moved to Maintenance > Archived Projects.", parent=modal):
            return
        try:
            ps.archive_project(self.user_info, project_id, (current_status or "").replace(" (OVERDUE)", ""))
        except Exception as e:
            messagebox.showerror("Could not archive", friendly_message(e), parent=modal)
            return
        uid = self.user_info.get("user_id")
        if uid:
            log_action(uid, "Archived", "Projects", f"Archived project '{project_name}' (PID: {project_id})")
        modal.destroy()
        self.load_projects()
        dashboard = self.winfo_toplevel()
        if hasattr(dashboard, "show_toast"):
            dashboard.show_toast(f"✓ Project '{project_name}' archived.")
