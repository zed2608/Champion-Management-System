import customtkinter as ctk
from views.ui_thread import UiMixin
from tkinter import messagebox
from database import get_connection, log_action
from datetime import datetime
import os
import tempfile
import threading
from services import audit_chain
from services.errors import friendly_message
from utils.pdf_table import render_pdf
from services.paging import fetch_page
from services.validators import like_pattern
from views.paged_table import PagedTable
from ui import components as C
from ui import theme as T



def _status_style(status_col, tag_col):
    """Cell colours shared by the transaction tables: Active in red, Retrieved in green, an untagged tool in red."""
    def style(row, col, val):
        if col == status_col:
            return (T.DANGER if val == "Active" else T.SUCCESS_TEXT), True
        if col == tag_col and val == "Unassigned":
            return T.DANGER, True
        return T.TEXT, False
    return style


def _with_quantity(rows):
    """[QUANTITIES] A consumable issued as 2.5 kg is ONE record: show 'Grease x2.5' so the amount is visible (equipment, quantity 1, is unchanged)."""
    from services.validators import fmt_qty
    for r in rows:
        q = r.get("quantity")
        if q is not None and q != 1:
            r["tool_name"] = f"{r['tool_name']} x{fmt_qty(q)}"
    return rows


class TrackingView(UiMixin, ctk.CTkFrame):
    def __init__(self, parent, user_info=None):
        super().__init__(parent, fg_color="transparent")
        self._ui_init()

        self.user_info = user_info or {}
        self.is_admin = self.user_info.get("role", "Staff") == "Admin"

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)

        if self.is_admin:
            self.build_admin_view()
        else:
            self.build_staff_view()

        uid = self.user_info.get("user_id")
        if uid:
            log_action(uid, "Viewed", "Tracking & Accountability",
                       "Opened Tracking module")

    # ==========================================
    # MODAL FIX (Deployment Details)
    # ==========================================
    def view_deployment_details(self, row):
        modal = ctk.CTkToplevel(self)
        trans_id = row.get("transaction_id", "N/A")
        modal.title(f"Deployment History - Receipt #{trans_id}")

        modal.minsize(500, 500)
        C.keep_above(modal)
        modal.grab_set()
        
        modal.update_idletasks()
        x = (modal.winfo_screenwidth() // 2) - (500 // 2)
        y = (modal.winfo_screenheight() // 2) - (600 // 2)
        modal.geometry(f"500x600+{x}+{y}")

        bottom_frame = ctk.CTkFrame(modal, fg_color="transparent")
        bottom_frame.pack(fill="x", side="bottom", padx=20, pady=20)

        scroll_container = ctk.CTkScrollableFrame(
            modal, fg_color="transparent")
        scroll_container.pack(fill="both", expand=True, padx=20, pady=(20, 0))

        ctk.CTkLabel(scroll_container, text="Champion Fine Tooling", font=T.font(20, "bold"), text_color=T.PRIMARY).pack(pady=(0, 2))
        ctk.CTkLabel(scroll_container, text="Official Issuance Receipt", font=T.font(14), text_color=T.TEXT_MUTED).pack(pady=(0, 20))

        issued_to = row.get("full_name", self.user_info.get("username", "N/A"))
        trans_type = row.get("type", "Issuance")

        details = (
            f"Transaction ID: {trans_id}\n"
            f"Type: {trans_type}\n"
            f"Date Out: {row.get('borrow_date', 'N/A')}\n"
            f"Date In: {row.get('return_date', 'N/A')}\n"
            f"Issued To: {issued_to}\n"
        )
        ctk.CTkLabel(scroll_container, text=details, justify="left",
                     font=T.font(14)).pack(anchor="w", pady=(0, 20))

        ctk.CTkLabel(scroll_container, text="Items Deployed:", font=T.font(14, "bold")).pack(anchor="w", pady=(0, 5))

        tool_name = row.get("tool_name", "N/A")
        tag_id = row.get("tag_id", "N/A")
        status = row.get("status", "N/A")
        ctk.CTkLabel(scroll_container, text=f"• {tool_name} (Tag: {tag_id}) - {status}", font=T.font(12)).pack(anchor="w", padx=10, pady=2)

    def build_admin_view(self):
        top_bar = ctk.CTkFrame(self, fg_color="transparent")
        top_bar.grid(row=0, column=0, sticky="ew", padx=20, pady=(10, 15))

        C.PageHeader(top_bar, "Tracking & Accountability", "Who had what, when, and the tamper-evident record of it").pack(side="left")

        tabs = ["📋 Issuance & Retrieval Logs", "🔎 Audit Records", "⚙️ Activity Log"]
        self.tab_var = ctk.StringVar(value=tabs[0])

        self.seg_btn = ctk.CTkSegmentedButton(
            top_bar, values=tabs, variable=self.tab_var, command=self.switch_tab,
            fg_color=T.SURFACE_MUTED, selected_color=T.PRIMARY, selected_hover_color=T.PRIMARY_HOVER
        )
        self.seg_btn.pack(side="right")

        self.tab_content = ctk.CTkFrame(self, fg_color="transparent")
        self.tab_content.grid(
            row=1, column=0, sticky="nsew", padx=10, pady=(0, 20))
        self.tab_content.grid_columnconfigure(0, weight=1)
        self.tab_content.grid_rowconfigure(0, weight=1)

        self.cached_tabs = {}
        self.switch_tab(tabs[0])

    def switch_tab(self, selected_tab):
        if hasattr(self, "current_tab") and self.current_tab:
            self.current_tab.grid_remove()

        if selected_tab not in self.cached_tabs:
            if "Issuance" in selected_tab:
                self.cached_tabs[selected_tab] = self.render_logs_tab()
            elif "Audit" in selected_tab:
                self.cached_tabs[selected_tab] = self.render_audit_tab()
            elif "Activity" in selected_tab:
                self.cached_tabs[selected_tab] = self.render_activity_tab()

        self.current_tab = self.cached_tabs[selected_tab]
        self.current_tab.grid(row=0, column=0, sticky="nsew")

        if "Issuance" in selected_tab:
            self.load_logs()
            self.log_search.focus_set()
        elif "Audit" in selected_tab:
            self.load_audit()
            self.audit_search.focus_set()
        elif "Activity" in selected_tab:
            self.load_activity()
            self.act_search.focus_set()

    # ------------------------------------------
    # TAB 1: Borrow/Return Logs
    # ------------------------------------------
    def render_logs_tab(self):
        frame = ctk.CTkFrame(
            self.tab_content, fg_color=T.SURFACE, corner_radius=10)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(20, 5))
        ctk.CTkLabel(top, text="Issuance & Retrieval Logs",
                     font=T.font(16, "bold"), text_color=T.TEXT).pack(side="left")

        self.log_search_var = ctk.StringVar()
        self.log_search = C.field(
            top, placeholder_text="Search employee or tool...", width=220, textvariable=self.log_search_var)
        self.log_search.pack(side="right", padx=(5, 0))

        self._log_timer = None
        def on_log_search(*args):
            if self._log_timer:
                self.after_cancel(self._log_timer)
            self._log_timer = self.after(300, self.load_logs)
        self.log_search_var.trace_add("write", on_log_search)

        ctk.CTkLabel(frame, text="An endless, chronological history book. Records exactly what happened and when (e.g., 'John took a hammer on Tuesday').",
                     font=T.font(12, "italic"), text_color=T.TEXT_MUTED).pack(anchor="w", padx=20, pady=(0, 8))

        self._log_scroll = ctk.CTkScrollableFrame(
            frame, fg_color="transparent")
        self._log_scroll.pack(fill="both", expand=True, padx=20, pady=(5, 20))
        return frame

    def _format_tx_dates(self, rows):
        """Receipt / table text for the two dates (done in the worker thread, so the Tk thread only copies strings)."""
        for r in rows:
            for key in ("borrow_date", "return_date"):
                if hasattr(r[key], 'strftime'):
                    r[key] = r[key].strftime('%b %d, %Y %I:%M %p')
                elif not r[key]:
                    r[key] = "—"
        return rows

    LOG_COLUMNS = [("TRN", 1, 50), ("Type", 1, 70), ("Tool Name", 3, 160), ("Tag ID", 2, 100), ("Assignee", 2, 120),
                   ("Date Issued", 3, 150), ("Date Retrieved", 3, 150), ("Status", 1, 80)]

    def load_logs(self):
        self._log_query = self.log_search.get().strip() if hasattr(self, "log_search") else ""     # read on the main thread
        if getattr(self, "_log_table", None) is None or not self._log_table.winfo_exists():
            for w in self._log_scroll.winfo_children():
                w.destroy()
            self._log_table = PagedTable(
                self._log_scroll, self.LOG_COLUMNS, fetch=self._fetch_logs_page,
                cells=lambda r: [str(r["transaction_id"]), r["type"], r["tool_name"], r["tag_id"], r["full_name"], r["borrow_date"], r["return_date"], r["status"]],
                cell_style=_status_style(7, 3), on_row_click=self.view_deployment_details, empty_text="No transaction records found.",
                font_size=12, cell_pady=12, uniform="log_cols")
            self._log_table.pack(fill="x", expand=True)
        self._log_table.reload(0)

    def _fetch_logs_page(self, page, size):
        q = self._log_query
        where, params = "WHERE 1=1", []
        if q:
            where += " AND (u.full_name LIKE %s OR t.name LIKE %s OR t.tag_id LIKE %s)"
            params = [like_pattern(q)] * 3
        conn = get_connection()
        if not conn:
            raise ConnectionError("The database is not reachable.")
        try:
            cur = conn.cursor(dictionary=True)
            rows, info = fetch_page(
                cur, """SELECT tr.transaction_id, tr.quantity, tr.type, t.name as tool_name, IFNULL(t.tag_id,'Unassigned') as tag_id,
                               u.full_name, tr.borrow_date, tr.return_date, tr.status""",
                f"FROM transaction tr JOIN tool t ON tr.tool_id = t.tool_id JOIN user u ON tr.user_id = u.user_id {where}", params,
                "ORDER BY tr.borrow_date DESC, tr.transaction_id DESC", page, size)
            return self._format_tx_dates(_with_quantity(rows)), info
        finally:
            if conn.is_connected():
                conn.close()

    # ------------------------------------------
    # TAB 2: Audit Records
    # ------------------------------------------
    def render_audit_tab(self):
        frame = ctk.CTkFrame(
            self.tab_content, fg_color=T.SURFACE, corner_radius=10)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(20, 5))
        ctk.CTkLabel(top, text="Audit Trail — Issuance & Retrieval Records",
                     font=T.font(16, "bold"), text_color=T.TEXT).pack(side="left")

        ctk.CTkLabel(frame, text="Investigating Missing Items: An active math equation. Cross-references Total Inventory vs. Available Stock vs. Active Transactions to flag discrepancies.",
                     font=T.font(12, "italic"), text_color=T.TEXT_MUTED).pack(anchor="w", padx=20, pady=(0, 8))

        filter_row = ctk.CTkFrame(frame, fg_color="transparent")
        filter_row.pack(fill="x", padx=20, pady=(0, 8))

        ctk.CTkLabel(filter_row, text="Filter by Status:",
                     font=T.font(12), text_color=T.TEXT_MUTED).pack(side="left")
        self.audit_filter = ctk.CTkOptionMenu(
            filter_row, values=["All", "Active", "Retrieved"],
            width=120, fg_color=T.SURFACE_ALT, text_color=T.TEXT, command=lambda e: self.load_audit()
        )
        self.audit_filter.pack(side="left", padx=8)

        self.audit_search_var = ctk.StringVar()
        self.audit_search = C.field(
            filter_row, placeholder_text="Search name / tool...", width=200, textvariable=self.audit_search_var)
        self.audit_search.pack(side="right")

        self._audit_timer = None
        def on_audit_search(*args):
            if self._audit_timer:
                self.after_cancel(self._audit_timer)
            self._audit_timer = self.after(300, self.load_audit)
        self.audit_search_var.trace_add("write", on_audit_search)

        self.audit_summary = ctk.CTkLabel(frame, text="", font=T.font(12, "bold"),
                                          text_color=T.PRIMARY)
        self.audit_summary.pack(anchor="w", padx=20, pady=(0, 5))

        self._audit_scroll = ctk.CTkScrollableFrame(
            frame, fg_color="transparent")
        self._audit_scroll.pack(
            fill="both", expand=True, padx=20, pady=(5, 20))
        return frame

    AUDIT_COLUMNS = [("TRN", 1, 50), ("Assignee", 2, 120), ("Tool", 3, 150), ("Tag ID", 2, 100), ("Date Issued", 3, 150), ("Date Retrieved", 3, 150),
                     ("Cond@Issuance", 2, 90), ("Cond@Retrieval", 2, 90), ("Status", 1, 80)]

    def load_audit(self):
        self._audit_status = self.audit_filter.get() if hasattr(self, "audit_filter") else "All"      # read on the main thread
        self._audit_query = self.audit_search.get().strip() if hasattr(self, "audit_search") else ""
        if getattr(self, "_audit_table", None) is None or not self._audit_table.winfo_exists():
            for w in self._audit_scroll.winfo_children():
                w.destroy()
            self._audit_table = PagedTable(
                self._audit_scroll, self.AUDIT_COLUMNS, fetch=self._fetch_audit_page,
                cells=lambda r: [str(r["transaction_id"]), r["full_name"], r["tool_name"], r["tag_id"], r["borrow_date"], r["return_date"],
                                 r["cond_borrow"], r["cond_return"], r["status"]],
                row_bg=lambda r, i: T.WARNING_BG if r["status"] == "Active" else (T.SURFACE_ALT if i % 2 == 0 else "white"),
                cell_style=_status_style(8, 3), on_loaded=self._audit_loaded, empty_text="No records match the audit criteria.",
                font_size=12, cell_pady=12, uniform="audit_cols")
            self._audit_table.pack(fill="x", expand=True)
        self._audit_table.reload(0)

    def _fetch_audit_page(self, page, size):
        where, params = "WHERE 1=1", []
        if self._audit_status != "All":
            where += " AND tr.status = %s"
            params.append("Returned" if self._audit_status == "Retrieved" else self._audit_status)
        if self._audit_query:
            where += " AND (u.full_name LIKE %s OR t.name LIKE %s)"
            params += [like_pattern(self._audit_query)] * 2
        frm = f"FROM transaction tr JOIN tool t ON tr.tool_id = t.tool_id JOIN user u ON tr.user_id = u.user_id {where}"
        conn = get_connection()
        if not conn:
            raise ConnectionError("The database is not reachable.")
        try:
            cur = conn.cursor(dictionary=True)
            rows, info = fetch_page(
                cur, """SELECT tr.transaction_id, tr.quantity, u.full_name, t.name as tool_name, IFNULL(t.tag_id,'Unassigned') as tag_id,
                               tr.borrow_date, tr.return_date, IFNULL(tr.condition_at_borrow,'N/A') as cond_borrow,
                               IFNULL(tr.condition_at_return,'N/A') as cond_return, tr.status""",
                frm, params, "ORDER BY tr.borrow_date DESC, tr.transaction_id DESC", page, size)
            cur.execute(f"SELECT SUM(tr.status = 'Active') AS active, SUM(tr.status = 'Returned') AS returned {frm}", tuple(params))
            c = cur.fetchone() or {}
            self._audit_counts = (info.total, int(c.get("active") or 0), int(c.get("returned") or 0))     # whole result set, not just this page
            return self._format_tx_dates(_with_quantity(rows)), info
        finally:
            if conn.is_connected():
                conn.close()

    def _audit_loaded(self, rows, info):
        total, active, returned = getattr(self, "_audit_counts", (info.total, 0, 0))
        if hasattr(self, "audit_summary") and self.audit_summary.winfo_exists():
            self.audit_summary.configure(text=f"  Total: {total}   |   Active: {active}   |   Retrieved: {returned}")

    # ------------------------------------------
    # TAB 3: Activity Log
    # ------------------------------------------
    def render_activity_tab(self):
        frame = ctk.CTkFrame(
            self.tab_content, fg_color=T.SURFACE, corner_radius=10)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(20, 5))
        ctk.CTkLabel(top, text="Full System Activity Log",
                     font=T.font(16, "bold"), text_color=T.TEXT).pack(side="left")

        ctk.CTkLabel(frame,
                     text="Records every login, logout, module visit, edit, search, and transaction. "
                          "Older entries are archived, never deleted.",
                     font=T.font(12), text_color=T.TEXT_MUTED,
                     wraplength=900, justify="left").pack(anchor="w", padx=20, pady=(0, 8))

        filter_row = ctk.CTkFrame(frame, fg_color="transparent")
        filter_row.pack(fill="x", padx=20, pady=(0, 8))

        ctk.CTkLabel(filter_row, text="Module:", font=T.font(12), text_color=T.TEXT_MUTED).pack(side="left")
        self.act_module_filter = ctk.CTkOptionMenu(
            filter_row,
            values=["All", "Authentication", "Dashboard", "Inventory", "Projects",
                    "Tagging", "Issuance & Retrieval", "Tracking & Accountability",
                    "Reports", "Maintenance", "Role Management", "Profile"],
            width=180, fg_color=T.SURFACE_ALT, text_color=T.TEXT
        )
        self.act_module_filter.pack(side="left", padx=8)
        self.act_module_filter.configure(command=lambda e: self.do_act_search())

        self.act_search_var = ctk.StringVar()
        self.act_search = C.field(
            filter_row, placeholder_text="Search user or details...", width=200, textvariable=self.act_search_var)
        self.act_search.pack(side="right")

        self._act_timer = None
        def on_act_search(*args):
            if self._act_timer:
                self.after_cancel(self._act_timer)
            self._act_timer = self.after(300, self.do_act_search)
        self.act_search_var.trace_add("write", on_act_search)

        # [PANEL-AWE] tamper-evidence: recompute the hash chain on demand and print it
        action_row = ctk.CTkFrame(frame, fg_color="transparent")
        action_row.pack(fill="x", padx=20, pady=(0, 8))
        self.verify_btn = C.button(action_row, kind="primary", text="🔐 Verify Audit Chain", width=150,
                                        command=self.verify_audit_chain)
        self.verify_btn.pack(side="left", padx=(10, 5))
        self.audit_pdf_btn = C.button(action_row, kind="secondary", text="⎙ Audit Report PDF", width=140,
                                           command=self.export_audit_pdf)
        self.audit_pdf_btn.pack(side="left", padx=5)
        self.chain_lbl = ctk.CTkLabel(frame, text="", font=T.font(12, "bold"), text_color=T.TEXT_MUTED, wraplength=900, justify="left")
        self.chain_lbl.pack(anchor="w", padx=20, pady=(0, 4))

        self.act_summary = ctk.CTkLabel(frame, text="", font=T.font(12, "bold"), text_color=T.PRIMARY)
        self.act_summary.pack(anchor="w", padx=20, pady=(0, 5))

        self._act_scroll = ctk.CTkScrollableFrame(
            frame, fg_color="transparent")
        self._act_scroll.pack(fill="both", expand=True, padx=20, pady=(5, 5))
        
        return frame

    ACT_COLORS = {"Login": T.SUCCESS_TEXT, "Logout": T.DANGER_SOFT, "Added": T.INFO, "Edited": T.WARNING_ALT, "Archived": T.TEXT_MUTED, "Searched": T.PURPLE_ALT,
                  "Viewed": T.TEXT, "Issued": T.SUCCESS_DARK, "Retrieved": T.SUCCESS_DARK, "Submitted": T.INFO_HOVER, "Approved": T.SUCCESS_DARK,
                  "Flagged": T.DANGER, "Resolved": T.SUCCESS_TEXT}

    # ---- [PANEL-AWE] audit chain ---------------------------------------------------------------------------------------------------
    def verify_audit_chain(self):
        self.verify_btn.configure(state="disabled", text="Checking…")
        self.chain_lbl.configure(text="Recomputing every hash, please wait…", text_color=T.TEXT_MUTED)

        def work():
            try:
                result = audit_chain.verify_chain(self.user_info)
            except Exception as e:
                msg = friendly_message(e)
                self.post_ui(lambda: self._chain_done(None, msg))
                return
            self.post_ui(lambda: self._chain_done(result, None))
        threading.Thread(target=work, daemon=True).start()

    def _chain_done(self, result, error):
        self.verify_btn.configure(state="normal", text="🔐 Verify Audit Chain")
        if error:
            self.chain_lbl.configure(text=f"Could not verify: {error}", text_color=T.DANGER_TEXT)
            return
        head = f"   Head: {result['head_hash']}" if result.get("head_hash") else ""
        self.chain_lbl.configure(text=("✓ " if result["intact"] else "✗ ") + audit_chain.describe(result) + head,
                                 text_color=T.PRIMARY if result["intact"] else T.DANGER)

    def export_audit_pdf(self):
        self.audit_pdf_btn.configure(state="disabled", text="Preparing…")

        def work():
            try:
                data = audit_chain.audit_report(self.user_info)
            except Exception as e:
                msg = friendly_message(e)
                self.post_ui(lambda: self._audit_pdf_done(None, msg))
                return
            self.post_ui(lambda: self._audit_pdf_done(data, None))
        threading.Thread(target=work, daemon=True).start()

    def _audit_pdf_done(self, data, error):
        self.audit_pdf_btn.configure(state="normal", text="⎙ Audit Report PDF")
        if error:
            messagebox.showerror("Export Error", error, parent=self.winfo_toplevel())
            return
        try:
            path = self.write_audit_pdf(data)
            os.startfile(path)
        except Exception as e:
            messagebox.showerror("Export Error", friendly_message(e), parent=self.winfo_toplevel())

    @staticmethod
    def audit_pdf_sections(data):
        """(notes, sections) for the printed audit report: the chain verdict and head hash first, then the newest entries."""
        res = data["verify"]
        verdict = [["Result", audit_chain.describe(res)], ["Entries checked", str(res["checked"])],
                   ["Chain head (SHA-256)", res.get("head_hash") or "—"],
                   ["First broken entry", "none" if res["intact"] else f"#{res['first_broken_log_id']}"]]
        entries = [[str(r["log_id"]), r["ts"].strftime("%Y-%m-%d %H:%M:%S") if hasattr(r["ts"], "strftime") else str(r["ts"] or ""),
                    r["employee"], r["action_type"] or "", r["module"] or "", r["details"], (r["session_id"] or "")[:8]] for r in data["rows"]]
        notes = ["AUDIT CHAIN " + ("INTACT" if res["intact"] else "BROKEN") + " - head " + (res.get("head_hash") or "-")[:16] + "…"]
        return notes, [("Audit chain verification", ["Check", "Value"], verdict),
                       (f"Newest {len(entries)} audit entries", ["ID", "Time", "Employee", "Action", "Module", "Details", "Session"], entries)]

    def write_audit_pdf(self, data):
        notes, sections = self.audit_pdf_sections(data)
        path = os.path.join(tempfile.gettempdir(), f"Audit_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
        return render_pdf("Audit Trail Report", "Tamper-evident hash-chained audit log", sections, path, notes)

    def do_act_search(self):
        self.load_activity()

    def load_activity(self):
        self._act_module = self.act_module_filter.get() if hasattr(self, "act_module_filter") else "All"      # read on the main thread
        self._act_query = self.act_search.get().strip() if hasattr(self, "act_search") else ""
        if getattr(self, "_act_table", None) is None or not self._act_table.winfo_exists():
            for w in self._act_scroll.winfo_children():
                w.destroy()
            self._act_table = PagedTable(
                self._act_scroll, [("Log ID", 1, 60), ("Timestamp", 3, 150), ("Employee", 3, 150), ("Action Type", 2, 100), ("Module", 2, 120),
                                   ("Details", 5, 250)],
                fetch=self._fetch_activity_page,
                cells=lambda r: [str(r["log_id"]), r["ts"], r["employee"], r["action_type"], r["module"], r["details"]],
                cell_style=lambda r, c, v: (self.ACT_COLORS.get(v, T.TEXT_SECONDARY), True) if c == 3 else (T.TEXT, False),
                on_loaded=lambda rows, info: self.act_summary.configure(text=f"  {info.label()} entries") if self.act_summary.winfo_exists() else None,
                empty_text="No activity records found.", page_size=50, font_size=12, cell_pady=12, uniform="act_cols")
            self._act_table.pack(fill="x", expand=True)
        self._act_table.reload(0)

    def _fetch_activity_page(self, page, size):
        where, params = "WHERE 1=1", []
        if self._act_module != "All":
            where += " AND sl.module = %s"
            params.append(self._act_module)
        if self._act_query:
            where += " AND (u.full_name LIKE %s OR sl.details LIKE %s OR sl.action_type LIKE %s)"
            params += [like_pattern(self._act_query)] * 3
        conn = get_connection()
        if not conn:
            raise ConnectionError("The database is not reachable.")
        try:
            cur = conn.cursor(dictionary=True)
            rows, info = fetch_page(
                cur, """SELECT sl.log_id, sl.timestamp as ts, IFNULL(u.full_name, CONCAT('UID:', sl.user_id)) as employee,
                               sl.action_type, sl.module, IFNULL(sl.details,'—') as details""",
                f"FROM system_logs sl LEFT JOIN user u ON sl.user_id = u.user_id {where}", params, "ORDER BY sl.log_id DESC", page, size)
        finally:
            if conn.is_connected():
                conn.close()
        for r in rows:
            if hasattr(r["ts"], 'strftime'):
                r["ts"] = r["ts"].strftime('%b %d, %Y %I:%M %p')
        return rows, info

    def build_staff_view(self):
        top_bar = ctk.CTkFrame(self, fg_color="transparent")
        top_bar.grid(row=0, column=0, sticky="ew", padx=20, pady=(10, 15))

        C.PageHeader(top_bar, "Tracking & Accountability", "Your own deployment history").pack(side="left")

        tabs = ["👤 My History"]
        self.tab_var = ctk.StringVar(value=tabs[0])

        self.seg_btn = ctk.CTkSegmentedButton(
            top_bar, values=tabs, variable=self.tab_var,
            fg_color=T.SURFACE_MUTED, selected_color=T.PRIMARY, selected_hover_color=T.PRIMARY_HOVER
        )
        self.seg_btn.pack(side="right")

        self.tab_content = ctk.CTkFrame(self, fg_color="transparent")
        self.tab_content.grid(
            row=1, column=0, sticky="nsew", padx=10, pady=(0, 20))
        self.tab_content.grid_columnconfigure(0, weight=1)
        self.tab_content.grid_rowconfigure(0, weight=1)

        frame = ctk.CTkFrame(
            self.tab_content, fg_color=T.SURFACE, corner_radius=10)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(20, 10))
        ctk.CTkLabel(top, text="My Deployment History", font=T.font(16, "bold"), text_color=T.TEXT).pack(side="left")
        ctk.CTkLabel(frame, text="Click on any transaction record below to view its Deployment Receipt.", font=T.font(12), text_color=T.TEXT_MUTED).pack(anchor="w", padx=20, pady=(0, 10))

        scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=20, pady=(5, 20))

        user_id = self.user_info.get("user_id")
        if not user_id:
            emp_id = self.user_info.get("employee_id")
            if emp_id:
                conn2 = get_connection()
                if conn2:
                    try:
                        c2 = conn2.cursor(dictionary=True)
                        c2.execute("SELECT user_id FROM user WHERE employee_id = %s", (emp_id,))
                        row2 = c2.fetchone()
                        if row2:
                            user_id = row2["user_id"]
                    except Exception:
                        pass
                    finally:
                        if conn2.is_connected():
                            conn2.close()

        if not user_id:
            ctk.CTkLabel(scroll, text="Could not resolve user session. Please log out and log back in.", text_color=T.DANGER_TEXT).pack(pady=20)
            return

        def fetch(page, size):
            conn = get_connection()
            if not conn:
                raise ConnectionError("The database is not reachable.")
            try:
                cur = conn.cursor(dictionary=True)
                rows, info = fetch_page(
                    cur, """SELECT tr.transaction_id, tr.quantity, t.name as tool_name, IFNULL(t.tag_id,'Unassigned') as tag_id,
                                   tr.borrow_date, tr.return_date, IFNULL(tr.condition_at_return,'—') as cond_return, tr.status""",
                    "FROM transaction tr JOIN tool t ON tr.tool_id = t.tool_id WHERE tr.user_id = %s", [user_id],
                    "ORDER BY tr.borrow_date DESC, tr.transaction_id DESC", page, size)
                return self._format_tx_dates(_with_quantity(rows)), info
            finally:
                if conn.is_connected():
                    conn.close()

        self._my_table = PagedTable(
            scroll, [("TRN", 1, 50), ("Tool Name", 3, 160), ("Tag ID", 2, 100), ("Date Issued", 3, 150), ("Date Retrieved", 3, 150),
                     ("Cond@Retrieval", 2, 100), ("Status", 1, 80)],
            fetch=fetch,
            cells=lambda r: [str(r["transaction_id"]), r["tool_name"], r["tag_id"], r["borrow_date"], r["return_date"], r["cond_return"], r["status"]],
            cell_style=_status_style(6, 2), on_row_click=self.view_deployment_details, empty_text="You have no deployment history.",
            font_size=12, cell_pady=12, uniform="staff_cols")
        self._my_table.pack(fill="x", expand=True)
        self._my_table.reload(0)
