import customtkinter as ctk
from views.ui_thread import UiMixin
from tkinter import messagebox
from services import help_service as help_svc
from services.errors import friendly_message
from ui import components as C
from ui import intro as intro_module
from ui import prefs
from ui import theme as T

class HelpView(UiMixin, ctk.CTkFrame):
    """
    Help Module — Figure 4 in the procedural flowchart.
    Provides Help Guide, FAQs, and System Requirements.
    Keyword search uses a linear scan (O(n)) over section/FAQ text.
    Admin-only sections are hidden from Staff users.
    """

    # Sections tagged True are shown only to Admins
    GUIDE_SECTIONS = [
        (False, "1. Logging In & System Roles", [
            "Enter your Employee ID (username) and password on the login screen.",
            "The system has three operational tiers: Admin, Staff, and Worker.",
            "Admin — Full system access: approvals, role management, maintenance, and reporting.",
            "Staff — Issue and return tools, view projects and inventory, and print tool labels.",
            "Worker — Field personnel. Workers do NOT log into the desktop system. They are registered so their IDs can be scanned for tool accountability on project sites.",
            "Use 'Forgot Password?' to send a reset request directly to the Admin Dashboard.",
        ]),
        (False, "2. Dashboard", [
            "The four cards show tools currently out, overdue projects or available tools, open tool issues or active projects, and low stock.",
            "Click a card to open the related section. Recent activity shows the latest changes.",
            "Admins can open System status details when they need more information.",
            "For security, inactivity for 15 minutes triggers a warning; if ignored for 30 seconds, auto-logout executes.",
        ]),
        (True, "3. Products / Inventory (Admin)", [
            "Use the left form to register new tools or consumables into the system.",
            "Equipment and consumables measured in pieces (pcs) use whole numbers. Consumables measured in boxes, sets, kg, packs, liters, rolls, meters or feet can use up to 2 decimal places (e.g., 0.5 kg).",
            "Click any row in the table to open the Edit/Archive modal.",
            "'Archive' safely removes a tool from active use and sends it to Maintenance → Archived Tools. The tool can be restored at any time.",
            "Archiving a tool does NOT delete transaction history — borrow/return records remain auditable.",
            "If quantity available is lower than total and tied to an active transaction, location may show as deployed to project.",
            "To print labels, first assign each tool a Tag ID in its details. Only tagged rows have Print checkboxes.",
            "Select tagged rows, or select all tagged rows on the current page, then choose Print Selected Tags beside the selection count. Untagged rows say Tag first.",
        ]),
        (False, "4. Project Management (Requisition Workflow)", [
            "Admins create and approve projects. Enter a project name and client, then assign workers by their Employee IDs.",
            "Enter both dates in YYYY-MM-DD format, or leave both blank. End Date must be on or after Start Date.",
            "Add at least one item and its required quantity. Equipment and consumables measured in pcs use whole numbers. Divisible consumables can use up to 2 decimal places.",
            "In the item catalog, In stock / Total shows current warehouse stock and company stock. Click + Add and confirm to put an amount in the project plan. This does not remove stock; stock changes when an item is issued or returned.",
            "A request can exceed stock currently available, but issuance waits for stock to return. It cannot exceed the company's total stock.",
            "Admin projects start Approved. The project becomes Ongoing when all required tool quantities are issued. Admins can complete and archive it later.",
            "A worker must be assigned to the project. Only approved or ongoing projects can issue tools, within their tool requirements.",
        ]),
        (False, "5. QR Tag & Badge Format Explained", [
            "Tool Tag IDs generally follow organization-defined patterns (example: CFT-XXXX or TAG-###-CAT-SUP).",
            "PID means Product ID (internal tool_id in the database).",
            "TID/Tag ID is the scannable identifier attached to the physical item.",
            "A tool QR payload may include Tag ID, PID, Name, Location, and current Status/Condition.",
            "Employee QR badges include Employee ID and identity fields used for issuance/retrieval verification.",
            "TRN means Transaction Receipt Number used to trace issuance/retrieval records.",
            "If a QR label is damaged, manual entry of Tag ID, PID, Employee ID, or TRN is supported.",
        ]),
        (False, "6. Tool Tags in Inventory", [
            "In Inventory, choose Needs Tag or Already Tagged to find tools.",
            "Open a tool to assign, change, or remove its Tag ID. A Tag ID identifies one tool record.",
            "Use Scan QR in Inventory to check a printed tag.",
            "For labels, select tagged rows in the Print column and choose Batch Print Tags.",
        ]),
        (False, "7. Tool Issuance (Deployment)", [
            "Issuance is project-gated: only approved/ongoing projects can receive tools.",
            "Step 1: Scan/enter assignee Employee ID and verify identity.",
            "Step 2: Select an eligible project assigned to that worker.",
            "Step 3: Review the required tools and remaining quantities for that project.",
            "Step 4: Scan or enter a linked Tool Tag. Only tools on the project list may be issued.",
            "For divisible consumables, enter the amount to issue after scanning (e.g., 0.5 kg). Use the quantity controls to adjust the cart before confirming.",
            "Step 5: The system checks stock, remaining approved quantity, worker assignment and project dates again when saving.",
            "Step 6: Confirm issuance to create transactions and update stock.",
            "A receipt is generated with TRN range and printable PDF preview.",
        ]),
        (False, "8. Tool Retrieval", [
            "Step 1: Scan surrendering Employee ID to authenticate return context.",
            "Step 2: Scan Tool Tag or enter TRN to locate active deployment records.",
            "Step 3: Set return condition (Good, Needs Repair, Damaged, Lost).",
            "Step 4: Add Condition Details for maintenance context.",
            "Step 5: Enter quantity to return. Partial decimal returns are allowed only for divisible consumables; equipment and pcs use whole numbers.",
            "Step 6: Confirm retrieval. Good units return to available stock; repair or damaged units go to maintenance; lost units reduce total stock.",
            "A return frees that project's issued quantity. A replacement can be issued while the project remains eligible and stock is available.",
        ]),
        (False, "9. Tool Condition System", [
            "Good — Item is fully operational and available for normal deployment.",
            "Needs Repair — Item has a serviceable defect; route to maintenance workflow.",
            "Damaged — Item has major damage requiring repair or replacement decision.",
            "Lost — Item is missing/unrecoverable and should be flagged for accountability action.",
            "Returns and maintenance issues update tool condition and stock across Inventory, Dashboard and Reports.",
            "Maintenance issue rows can be resolved with updated condition and resolution notes.",
        ]),
        (True, "10. Tracking & Accountability (Admin)", [
            "Borrow/Return Logs — chronological record of tool movements; click rows for receipt detail.",
            "Audit Records — compare Active vs Returned states to detect discrepancies.",
            "Activity Log — full trail of logins, edits, searches, and navigation events.",
            "Use filters and keyword search to isolate users, tools, statuses, modules, or date-time context.",
        ]),
        (False, "11. Reports", [
            "The six reports cover tool use, employee activity, project allocation, damage and loss, low stock, and overdue transactions. Wear forecasts are under Maintenance.",
            "Search within a report by name, ID or status and press Search or Enter. The PDF uses the same search and dates as the screen. The Tool Usage tab also has a tool search.",
            "Dates are optional for historical reports; Low Stock shows current stock and has no date filter. Notes in the export dialog appear on the PDF but do not filter results.",
        ]),
        (True, "12. Maintenance & Centralized Archive (Admin Only)", [
            "Issues & Repairs: Submit flags (Damaged, Lost, Needs Repair, etc.) and investigate active issues.",
            "Important connectivity: flagging a tool updates tool.condition in database immediately.",
            "Open issues appear on the Admin Dashboard and in Inventory condition information.",
            "Archived Tools: restore previously archived inventory items.",
            "Archived Employees: restore deactivated users back to active status.",
            "Archived Projects: only explicitly archived projects appear; restore sets project back to active workflow state.",
        ]),
        (True, "13. Role Management (Admin Only)", [
            "Register users as Admin, Staff, or Worker.",
            "Workers are assignable/scannable personnel and do not receive desktop login credentials by default.",
            "Edit users to change role, update profile fields, and reset password policies.",
            "Deactivated users move to Maintenance → Archived Employees and can be restored later.",
        ]),
        (False, "14. Profile", [
            "View/update your name and email.",
            "Change password with current-password verification.",
            "Upload avatar image from local files.",
            "Print your Employee ID QR badge for site verification workflows.",
            "Borrowing history table shows your recent transactions and statuses.",
        ]),
    ]

    FAQS = [
        (False, "How do I issue a tool to a worker?",
         "Verify employee ID, select an approved/ongoing assigned project, scan tools listed in requisition, then click Issue to generate TRN and update stock."),
        (False, "What is the 'Worker' role and why can't they log in?",
         "Workers are field personnel identifiers used for accountability scanning. They are typically non-login accounts unless role is changed by Admin."),
        (False, "How do I add a description when returning a tool?",
         "Use the Condition Details box in Tool Retrieval before confirming return."),
        (True, "Where do completed projects or broken tools go?",
         "Archived objects go to Maintenance archive tabs; broken/repair/lost states are managed in Issues & Repairs."),
        (True, "Why is a project still showing in Project Management after I archived it?",
         "A project must be explicitly archived; status alone (Completed/Cancelled) does not move it to archive list."),
        (False, "I scanned a QR code but it didn't read. What do I do?",
         "Improve lighting/alignment and retry; if label is damaged, type Tag ID/PID/TRN manually."),
        (False, "Why can't I approve a Project Requisition?",
         "Only Admin accounts can approve pending requisitions."),
        (False, "Can I return only a partial amount of consumables?",
         "Yes, enter the exact return quantity (e.g., 0.5) where supported by the retrieval workflow."),
        (False, "How do I filter reports by date when exporting to PDF?",
         "Choose From/To dates on the Reports screen and click Apply. The exported PDF uses the same dates and search. Low Stock shows current stock without a date filter."),
        (False, "Is my password stored securely?",
         "Yes, password hashes use bcrypt; plaintext passwords are not stored."),
        (False, "What does the Tag ID format look like and what do the parts mean?",
         "Tag formats are organization-defined (e.g., CFT-XXXX or TAG-###-CAT-SUP). Segments commonly represent sequence, category, and supplier tokens."),
        (False, "What happens when I mark a tool as 'Damaged' on return?",
         "The transaction closes and the returned units go to maintenance, not available stock. An issue is opened with your condition details."),
        (False, "Can I issue the same tool to multiple projects simultaneously?",
         "Only within available quantity and requisition approvals. The system enforces stock and requirement constraints."),
        (False, "How do I see which tools are currently deployed and where?",
         "Use Inventory and Tracking logs; deployed items may display active project location/context."),
        (False, "What is the difference between 'Archive' and 'Delete' for a tool?",
         "Archive hides from active operations but preserves history and enables restore; delete is destructive and generally avoided for auditable assets."),
        (False, "Can a Worker be assigned to multiple projects at once?",
         "Yes, assignment depends on project planning and administrative controls."),
        (False, "What happens if I lose a physical QR tag label?",
         "Use the tool's Inventory details to check or replace its Tag ID, then print a new label."),
        (False, "Where is the tool wear forecast?",
         "Open Maintenance, then Wear Forecast. It shows service intervals and tools that may need attention."),
        (True, "Who can see the Activity Log?",
         "Admins can access full activity logs in Tracking & Accountability."),
        (False, "What does 'Overdue' mean for a project?",
         "Project end date has passed while project is still active/not archived."),
        (True, "How do I restore an archived tool/employee/project?",
         "Go to Maintenance archive tabs and click Restore on the corresponding row."),
        (False, "What is a TRN and where do I find it?",
         "TRN is Transaction Receipt Number shown during issuance/retrieval history and receipt output."),
        (False, "Can I export reports without setting a date range?",
         "Yes, leave dates blank to export all records."),
        (False, "Why does a tool show as 'unavailable' even though it's in the warehouse?",
         "Its available quantity may be zero because units are out or in maintenance. Check Inventory for the stock count."),
        (False, "Why can't I select a tool to print its label?",
         "Assign a Tag ID in the tool's Inventory details first. Only tagged rows can be selected; Select all includes tagged rows on the current page."),
        (False, "Does maintenance flagging really update inventory data?",
         "Yes. Maintenance flagging writes to tool.condition; connected modules reflect the change immediately."),
        (False, "Why can't I enter only one project date?",
         "Enter both Start Date and End Date, or leave both blank. End Date must be on or after Start Date."),
        (False, "Can I issue a replacement after returning a tool?",
         "Yes, returning a tool frees its project's approved quantity. The project must still be eligible and stock must be available."),
    ]

    LEGACY_GUIDE_HASHES = [
        ('1. Logging In & System Roles', '3893e2a14ddea477e3563c04f9f2ed9a1fed5a7330c9edc5f44b4689561144e8'),
        ('2. Dashboard', '4f9bf4638c7f65fb31e6d11211e700bd81e6735257e0f8c2ab5cc9d507b786ea'),
        ('3. Products / Inventory (Admin)', ('f2e6fbfe426444bd10adf374c096d9bd649777120cc88b1c27ef81f961eed692', 'e03b3efc4771011cc03564d7fd60e345b9b53cd6c4c7c63927aa3da7b25c6db8')),
        ('4. Project Management (Requisition Workflow)', ('cf52335c70b0b9292257b700c35aa4a2994318d9ede26d6d6cecc6a7f27f29a7', '0af43b9a5cc4f670bfaf4cbae66c4db06d27d540168c523d5876c110b1d6747a')),
        ('5. QR Tag & Badge Format Explained', 'ca8fb814b5c144ce55fcd54a0ba33ef42f5733fe191bf0bd7965feb8578e18b0'),
        ('6. Tagging (Tool Identity Management)', 'f454558c4c7a6f253fd542f53374f47f4b4d3b4dee1d2f569b2b679291df3789'),
        ('7. Tool Issuance (Deployment)', ('d49c568c95506ba2282107c88e3fb76e59e1e6b81897b12bb7dcadffc8fe3098', 'e491dd3584107db842eccb7220fd10fbf098e32799881799b4047b14bf44db9e')),
        ('8. Tool Retrieval', ('3e28307c9646a9d5cfad2bcf0ca61e0e314a9c4d3620949a72c5fa64127782ec', '22e900f505f39bc36296a2c3dc405fd58890d0e9e5b7838e12f6d889685d4bd5')),
        ('9. Tool Condition System', 'c82543b9c338bb8d09bac3ea758c2dd2d381c6539b56eec281e8d8a531837753'),
        ('10. Tracking & Accountability (Admin)', 'e4cbba001d9634f78dac88c79ac6a24ca7385020aa6b6426d3f9d61c7af0759c'),
        ('11. Reports', ('bca6a274304b0febacdd334973d155454988c94c71d5a54c39f3c77933330535', '04a43acf76930292f726baeffbb9391f7601a68244dc9372d7257750ab4c2d65')),
        ('12. Maintenance & Centralized Archive (Admin Only)', '544244cdb5cdf95c4a44564a3d08c3940f9a3bd21c2d27a43e418aebdf171de8'),
        ('13. Role Management (Admin Only)', '1b78d1d6363f49e09ef67ddc134ea18cc84bcc3904934cb7a44b34450aa8070e'),
        ('14. Profile', '3c7b13cdea900ed76a133d50781092e20a19ee6b0bf11ff6b07f83ef53b9128b'),
    ]

    LEGACY_FAQ_HASHES = [
        ('How do I issue a tool to a worker?', 'f912ec3c8b7eea540a2830ba08534e6d21f39c4958d10511c3282653355d0286'),
        ("What is the 'Worker' role and why can't they log in?", 'c612557573a74d4bff6b2bd9492429f5868e34a7bcba125943ed9a46cb4fef55'),
        ('How do I add a description when returning a tool?', '300aa51be68b2306cf7d0430906ee9b375e805091ea6234a413de94d62bee277'),
        ('Where do completed projects or broken tools go?', 'fab3ff97269b03591e82e7e6a1b4b7d8ed504b3349cfe8c2bee67b90991fd0b0'),
        ('Why is a project still showing in Project Management after I archived it?', 'aa8667461994857907a7e978a7310486981355498fdbc3d829d077cf42ec4491'),
        ("I scanned a QR code but it didn't read. What do I do?", '832648ac493753ec24bf25a84be999076eb3179ea372d47ab7ee40d6760f03d9'),
        ("Why can't I approve a Project Requisition?", '927d6e5bbc0d775370b001d6820f872ecbc299921f8895c69a009f9e83f29e92'),
        ('Can I return only a partial amount of consumables?', '2927f4f2cb45a037b980c6839fcf3a108e3e2ac3c1f885672e57e2905c337d16'),
        ('How do I filter reports by date when exporting to PDF?', '94072840f26c0e779c128a684644b34dc1814532e45af18e5c994c171eee38be'),
        ('Is my password stored securely?', '769e669a6a12a03e7cdfc44da9d6fed1eeae3e967e586b71d9d8e4c613c452b7'),
        ('What does the Tag ID format look like and what do the parts mean?', '74340e785c7dc52e91ca82d79cefa49475fdc867270f2cd4e6ef899fef290411'),
        ("What happens when I mark a tool as 'Damaged' on return?", '8059d6beffd500393ff716692ee1238cbee3f91bf182cb86100dafb7d612e09a'),
        ('Can I issue the same tool to multiple projects simultaneously?', 'fc46c98ac774886f40d1f471c3c7feae559cb4c4108312ca5d1ef69a8506c466'),
        ('How do I see which tools are currently deployed and where?', 'f2a49adc77897173e3fda270e34704551e920501fb6079b7f22416edce485d22'),
        ("What is the difference between 'Archive' and 'Delete' for a tool?", '000757c3b4443a5f87ab7f01f07d61fb10790b5e4829efe41c2d796c4254fd86'),
        ('Can a Worker be assigned to multiple projects at once?', '06324103097f72538f7cd8e4b2f098be138739199829d4e84c088adee4f9e68e'),
        ('What happens if I lose a physical QR tag label?', 'd170e316f91de9f84ee2b641f34a5ee9540a25d37804af431cd0b88def48a045'),
        ('How does the ABC analysis categorize tools?', '773958c2f72371d69e7fdd22f67d26bb5bf9a74fad736fa35bf5351b1638758b'),
        ('Who can see the Activity Log?', 'fc5c367224a3bc51a96dbc9751033f97ac700fc83970375574bf0d92d0055949'),
        ("What does 'Overdue' mean for a project?", '25daeed5971fbf744d4afdc3ed4361199c9b6bd4767b5f5b772f8c4298e5254e'),
        ('How do I restore an archived tool/employee/project?', 'ba9c6e9c001a23c7c42e529eff0319d4a6e17a22b1be7a347ecdf22d2ff5484b'),
        ('What is a TRN and where do I find it?', '3f7107cdbe4c4e312f06b60649be38d9866a5bbede25ea31a25ac24919b656ac'),
        ('Can I export reports without setting a date range?', 'df4f2e603fb5c485348e3feee692038222c0bf6a25f7425bef790c237a0f5a12'),
        ("Why does a tool show as 'unavailable' even though it's in the warehouse?", '87797868cef353e157fd0c752d60e97d7a84d33f11886a6b2e458e962bbc2c5a'),
        ('Why is Action Items non-zero on the dashboard?', 'd9b78134957dd22d1d37ea756d4258939b68cb6c673a60a4bdc874901d1c2e9b'),
        ('Does maintenance flagging really update inventory data?', '3bad78a440588a057ad3cfe1d90a532736f8b323c966c724bf90238bbde4b27a'),
    ]

    def __init__(self, parent, user_info=None):
        super().__init__(parent, fg_color="transparent")
        self._ui_init()

        self.user_info = user_info or {}
        self.is_admin = self.user_info.get("role", "Staff") == "Admin"

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        import threading
        def _init():
            self._ensure_custom_tables()
            self.post_ui(self.build_ui)
        threading.Thread(target=_init, daemon=True).start()

    HARDWARE_SPECS = [
    ("Processor",        "Intel Core i3 or equivalent (64-bit)"),
    ("RAM",              "Minimum 8 GB"),
    ("Storage",          "At least 500 MB free disk space"),
    ("Operating System", "Windows 10 (64-bit) — recommended and tested"),
    ("Display",          "Minimum 1280×720 resolution (1920×1080 recommended)"),
    ("Webcam",           "HD Webcam 1080P — required for QR scanning features"),
    ("Printer",          "Any standard printer — required for label and receipt printing"),
    ("Network",          "LAN connection for database access (no internet required)"),
    ]
    SOFTWARE_SPECS = [
    ("Python",            "3.11"),
    ("Database",          "MySQL 8.0"),
    ("GUI Framework",     "Tkinter 8.6 + CustomTkinter 5.2.2"),
    ("IDE (Dev)",         "PyCharm Community Edition 2023.3"),
    ("QR Code Library",   "qrcode, pyzbar"),
    ("Image Processing",  "Pillow (PIL)"),
    ("CV Scanner",        "OpenCV (cv2)"),
    ("Password Hashing",  "bcrypt"),
    ]

    def _ensure_custom_tables(self):
        """Seed new installs and refresh untouched older defaults while keeping Admin edits."""
        try:
            help_svc.seed_defaults(self.user_info, self.GUIDE_SECTIONS, self.FAQS, self.HARDWARE_SPECS, self.SOFTWARE_SPECS,
                                   self.LEGACY_GUIDE_HASHES, self.LEGACY_FAQ_HASHES)
        except Exception as e:
            from services.errors import get_logger
            get_logger().warning("Help content could not be seeded: %s", friendly_message(e))

    def build_ui(self):
        top_bar = ctk.CTkFrame(self, fg_color="transparent")
        top_bar.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        C.PageHeader(top_bar, "Help & Support Hub", "Guides, answers and a way to reach an administrator").pack(side="left", padx=20)

        tabs = [
            "    ▤ Help Guide    ", 
            "         💬 FAQs         ", 
            " ⛭ System Requirements ", 
            "   ✉ Support Tickets   ",
            "     ℹ About     "
        ]
        self.tab_var = ctk.StringVar(value=tabs[0])

        self.seg_btn = ctk.CTkSegmentedButton(
            top_bar, values=tabs, variable=self.tab_var, command=self.switch_tab,
            fg_color=T.SURFACE_MUTED, selected_color=T.PRIMARY, selected_hover_color=T.PRIMARY_HOVER
        )
        self.seg_btn.pack(side="right", padx=20)
        self.seg_btn.set(tabs[0])

        self.tab_content = ctk.CTkFrame(self, fg_color=T.SURFACE, corner_radius=10)
        self.tab_content.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))
        self.tab_content.grid_columnconfigure(0, weight=1)
        self.tab_content.grid_rowconfigure(0, weight=1)

        self.switch_tab(tabs[0])

    def switch_tab(self, selected_tab):
        for widget in self.tab_content.winfo_children():
            widget.destroy()
        if "Help Guide" in selected_tab:
            self.render_guide_tab()
        elif "FAQs" in selected_tab:
            self.render_faq_tab()
        elif "System Requirements" in selected_tab:
            self.render_sysreq_tab()
        elif "Support Tickets" in selected_tab:
            self.render_tickets_tab()
        elif "About" in selected_tab:
            self.render_about_tab()

    def _build_search_bar(self, parent, on_search, placeholder="Search keywords..."):
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.pack(fill="x", padx=20, pady=(4, 4))
        entry_var = ctk.StringVar()
        entry = C.field(bar, placeholder_text=placeholder, width=300, textvariable=entry_var)
        entry.pack(side="left", padx=(0, 10))
        
        entry._search_timer = None
        def _do_search(*args):
            if entry._search_timer: parent.after_cancel(entry._search_timer)
            entry._search_timer = parent.after(300, lambda: on_search(entry.get().strip()))
            
        entry_var.trace_add("write", _do_search)
        return entry

    @staticmethod
    def _section_matches(title, points, keyword):
        kw = keyword.lower()
        if kw in title.lower():
            return True
        for p in points:
            if kw in p.lower():
                return True
        return False

    def render_guide_tab(self):
        outer = ctk.CTkFrame(self.tab_content, fg_color=T.SURFACE, corner_radius=10)
        outer.grid(row=0, column=0, sticky="nsew")
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(2, weight=1)

        hdr = ctk.CTkFrame(outer, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=20, pady=(10, 0))
        ctk.CTkLabel(hdr, text="User Guide — Automated Management System", font=T.font(16, "bold"), text_color=T.PRIMARY).pack(side="left")
        
        if self.is_admin:
            C.button(hdr, kind="primary", text="+ Add Guide", width=140, command=lambda: self.open_guide_modal()).pack(side="right", padx=(10, 0))

        search_container = ctk.CTkFrame(outer, fg_color="transparent")
        search_container.grid(row=1, column=0, sticky="ew")
        self._guide_search_entry = self._build_search_bar(search_container, self._filter_guide, "Search guide sections...")

        self._guide_scroll = ctk.CTkScrollableFrame(outer, fg_color="transparent")
        self._guide_scroll.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))

        self._render_guide_sections("")

    def _filter_guide(self, keyword):
        self._render_guide_sections(keyword)

    def _render_guide_sections(self, keyword):
        scroll = self._guide_scroll
        for w in scroll.winfo_children():
            w.destroy()

        found_any = False

        try:
            db_guides = help_svc.list_guides(self.user_info)
            for row in db_guides:
                if row["is_admin_only"] and not self.is_admin:
                    continue
                points_db = [p.strip() for p in row["steps"].split("|||") if p.strip()]
                if keyword and not self._section_matches(row["title"], points_db, keyword):
                    continue

                found_any = True
                card = ctk.CTkFrame(scroll, fg_color=T.SURFACE_ALT, corner_radius=8, border_width=1, border_color=T.BORDER)
                card.pack(fill="x", padx=10, pady=(0, 6))

                title_row = ctk.CTkFrame(card, fg_color="transparent")
                title_row.pack(fill="x", padx=14, pady=(8, 3))
                
                admin_tag = "[Admin Only] " if row["is_admin_only"] else ""
                ctk.CTkLabel(title_row, text=f"{admin_tag}{row['title']}", font=T.font(12, "bold"), text_color=T.PRIMARY).pack(side="left")
                
                if self.is_admin:
                    btn_frame = ctk.CTkFrame(title_row, fg_color="transparent")
                    btn_frame.pack(side="right")
                    C.button(btn_frame, compact=True, kind="primary", text="✎ Edit", width=60, command=lambda r=row: self.open_guide_modal(r)).pack(side="left", padx=(0, 5))
                    C.button(btn_frame, compact=True, kind="danger", text="🗑 Remove", width=60, command=lambda r_id=row['id']: self.delete_guide(r_id)).pack(side="left")

                for point in points_db:
                    ctk.CTkLabel(card, text=f"  •  {point}", font=T.font(12), text_color=T.TEXT, wraplength=780, justify="left").pack(anchor="w", padx=14, pady=1)
                ctk.CTkFrame(card, height=6, fg_color="transparent").pack()
        except Exception as e:
            ctk.CTkLabel(scroll, text=friendly_message(e), text_color=T.DANGER_TEXT).pack(pady=10)

        if not found_any:
            ctk.CTkLabel(scroll, text=f'No sections found for "{keyword}".', text_color=T.TEXT_MUTED).pack(pady=20)
            
    def delete_guide(self, guide_id):
        if not C.confirm("Confirm Delete", "Are you sure you want to remove this guide?", parent=self.winfo_toplevel()): return
        try:
            help_svc.delete_guide(self.user_info, guide_id)
            self._render_guide_sections(self._guide_search_entry.get().strip() if hasattr(self, '_guide_search_entry') else "")
        except Exception as e:
            messagebox.showerror("Error", friendly_message(e), parent=self.winfo_toplevel())

    def open_guide_modal(self, existing_row=None):
        modal = ctk.CTkToplevel(self)
        modal.title("Edit Guide" if existing_row else "Add Guide")
        modal.configure(fg_color=T.SURFACE)
        modal.attributes("-topmost", True)
        modal.grab_set()
        
        modal.update_idletasks()
        x = (modal.winfo_screenwidth() // 2) - (500 // 2)
        y = (modal.winfo_screenheight() // 2) - (600 // 2)
        modal.geometry(f"500x600+{x}+{y}")

        ctk.CTkLabel(modal, text="Guide Title:", font=T.font(12, "bold"), text_color=T.TEXT).pack(anchor="w", padx=20, pady=(20, 5))
        title_entry = C.field(modal, placeholder_text="e.g., How to Issue Tools")
        title_entry.pack(fill="x", padx=20)

        ctk.CTkLabel(modal, text="Display Sequence (1, 2, 3...):", font=T.font(12, "bold"), text_color=T.TEXT).pack(anchor="w", padx=20, pady=(10, 5))
        seq_entry = C.field(modal, placeholder_text="0")
        seq_entry.pack(fill="x", padx=20)

        admin_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(modal, text="Hide from Staff (Admin Only)", variable=admin_var, fg_color=T.PRIMARY).pack(anchor="w", padx=20, pady=10)

        ctk.CTkLabel(modal, text="Steps (Bullet Points):", font=T.font(12, "bold"), text_color=T.TEXT).pack(anchor="w", padx=20, pady=(10, 5))
        
        steps_frame = ctk.CTkScrollableFrame(modal, fg_color=T.SURFACE_ALT, height=150)
        steps_frame.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        
        step_entries = []

        def add_step_field(content=""):
            row = ctk.CTkFrame(steps_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            e = C.field(row, placeholder_text="Step description...")
            e.pack(side="left", fill="x", expand=True)
            e.insert(0, content)
            step_entries.append(e)
            ctk.CTkButton(row, text="✕", width=25, fg_color=T.DANGER_BG_STRONG, text_color=T.DANGER_TEXT, hover_color=T.DANGER_BORDER, command=lambda: [row.destroy(), step_entries.remove(e)]).pack(side="right", padx=5)

        if existing_row:
            title_entry.insert(0, existing_row['title'])
            seq_entry.insert(0, str(existing_row['display_order']))
            admin_var.set(bool(existing_row['is_admin_only']))
            for step in existing_row['steps'].split("|||"):
                if step.strip():
                    add_step_field(step.strip())
        if not step_entries:
            add_step_field() # Add first empty field
            
        C.button(modal, kind="secondary", text="+ Add Another Step", command=add_step_field).pack(padx=20, pady=5)

        def save_guide():
            t = title_entry.get().strip()
            s = seq_entry.get().strip()
            s = int(s) if s.isdigit() else 0
            steps = "|||".join([e.get().strip() for e in step_entries if e.get().strip()])
            
            if not t or not steps:
                return messagebox.showerror("Error", "Title and at least one step are required.", parent=modal)
            if not C.confirm("Save guide", f"{'Update' if existing_row else 'Add'} guide '{t}' with {len([e for e in step_entries if e.get().strip()])} steps?", parent=modal):
                return
                
            try:
                help_svc.save_guide(self.user_info, existing_row['id'] if existing_row else None, t, [e.get() for e in step_entries], admin_var.get(), s)
                modal.destroy()
                if hasattr(self, '_guide_search_entry'):
                    self._render_guide_sections(self._guide_search_entry.get().strip())
            except Exception as e:
                messagebox.showerror("Error", friendly_message(e), parent=modal)

        btn_row = ctk.CTkFrame(modal, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=20)
        C.button(btn_row, kind="primary", text="Update Guide" if existing_row else "Save Guide", command=save_guide).pack(side="left", expand=True, fill="x", padx=(0, 5))
        C.button(btn_row, kind="secondary", text="Cancel", command=modal.destroy).pack(side="right", expand=True, fill="x", padx=(5, 0))

    def render_faq_tab(self):
        outer = ctk.CTkFrame(self.tab_content, fg_color=T.SURFACE, corner_radius=10)
        outer.grid(row=0, column=0, sticky="nsew")
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(2, weight=1)

        hdr = ctk.CTkFrame(outer, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=20, pady=(10, 0))
        ctk.CTkLabel(hdr, text="Frequently Asked Questions", font=T.font(16, "bold"), text_color=T.PRIMARY).pack(side="left")
        
        if self.is_admin:
            C.button(hdr, kind="primary", text="+ Add FAQ", width=140, command=lambda: self.open_faq_modal()).pack(side="right", padx=(10, 0))

        search_container = ctk.CTkFrame(outer, fg_color="transparent")
        search_container.grid(row=1, column=0, sticky="ew")
        self._faq_search_entry = self._build_search_bar(search_container, self._filter_faq, "Search FAQs...")

        self._faq_scroll = ctk.CTkScrollableFrame(outer, fg_color="transparent")
        self._faq_scroll.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))

        self._render_faq_items("")

    def _filter_faq(self, keyword):
        self._render_faq_items(keyword)

    def _render_faq_items(self, keyword):
        scroll = self._faq_scroll
        for w in scroll.winfo_children():
            w.destroy()

        idx = 1
        found_any = False

        try:
            db_faqs = help_svc.list_faqs(self.user_info)
            for row in db_faqs:
                if row["is_admin_only"] and not self.is_admin:
                    continue
                if keyword and not self._section_matches(row["question"], [row["answer"]], keyword):
                    continue

                found_any = True
                card = ctk.CTkFrame(scroll, fg_color=T.SURFACE_ALT, corner_radius=8, border_width=1, border_color=T.BORDER)
                card.pack(fill="x", padx=10, pady=(0, 6))

                q_row = ctk.CTkFrame(card, fg_color="transparent")
                q_row.pack(fill="x", padx=14, pady=(10, 2))
                
                admin_tag = "[Admin Only] " if row["is_admin_only"] else ""
                ctk.CTkLabel(q_row, text=f"Q{idx}.  {admin_tag}{row['question']}", font=T.font(12, "bold"), text_color=T.PRIMARY, wraplength=650, justify="left").pack(side="left")

                if self.is_admin:
                    btn_frame = ctk.CTkFrame(q_row, fg_color="transparent")
                    btn_frame.pack(side="right")
                    C.button(btn_frame, compact=True, kind="primary", text="✎ Edit", width=60, command=lambda r=row: self.open_faq_modal(r)).pack(side="left", padx=(0, 5))
                    C.button(btn_frame, compact=True, kind="danger", text="🗑 Remove", width=60, command=lambda r_id=row['id']: self.delete_faq(r_id)).pack(side="left")

                ctk.CTkLabel(card, text=f"      {row['answer']}", font=T.font(12), text_color=T.TEXT, wraplength=780, justify="left").pack(anchor="w", padx=14, pady=(0, 10))
                idx += 1
        except Exception as e:
            ctk.CTkLabel(scroll, text=friendly_message(e), text_color=T.DANGER_TEXT).pack(pady=10)

        if not found_any:
            ctk.CTkLabel(scroll, text=f'No FAQs found for "{keyword}".', text_color=T.TEXT_MUTED).pack(pady=20)
            
    def delete_faq(self, faq_id):
        if not C.confirm("Confirm Delete", "Are you sure you want to remove this FAQ?", parent=self.winfo_toplevel()): return
        try:
            help_svc.delete_faq(self.user_info, faq_id)
            self._render_faq_items(self._faq_search_entry.get().strip() if hasattr(self, '_faq_search_entry') else "")
        except Exception as e:
            messagebox.showerror("Error", friendly_message(e), parent=self.winfo_toplevel())

    def open_faq_modal(self, existing_row=None):
        modal = ctk.CTkToplevel(self)
        modal.title("Edit FAQ" if existing_row else "Add FAQ")
        modal.configure(fg_color=T.SURFACE)
        modal.attributes("-topmost", True)
        modal.grab_set()
        
        modal.update_idletasks()
        x = (modal.winfo_screenwidth() // 2) - (500 // 2)
        y = (modal.winfo_screenheight() // 2) - (600 // 2)
        modal.geometry(f"500x600+{x}+{y}")

        ctk.CTkLabel(modal, text="Question:", font=T.font(12, "bold"), text_color=T.TEXT).pack(anchor="w", padx=20, pady=(20, 5))
        q_entry = C.field(modal)
        q_entry.pack(fill="x", padx=20)

        ctk.CTkLabel(modal, text="Answer:", font=T.font(12, "bold"), text_color=T.TEXT).pack(anchor="w", padx=20, pady=(10, 5))
        a_entry = ctk.CTkTextbox(modal, height=100)
        a_entry.pack(fill="both", expand=True, padx=20)

        ctk.CTkLabel(modal, text="Display Sequence:", font=T.font(12, "bold"), text_color=T.TEXT).pack(anchor="w", padx=20, pady=(10, 5))
        seq_entry = C.field(modal, placeholder_text="0")
        seq_entry.pack(fill="x", padx=20)

        admin_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(modal, text="Hide from Staff (Admin Only)", variable=admin_var, fg_color=T.PRIMARY).pack(anchor="w", padx=20, pady=10)

        if existing_row:
            q_entry.insert(0, existing_row['question'])
            a_entry.insert("1.0", existing_row['answer'])
            seq_entry.insert(0, str(existing_row['display_order']))
            admin_var.set(bool(existing_row['is_admin_only']))
        else:
            seq_entry.insert(0, "0")

        def save_faq():
            q = q_entry.get().strip()
            a = a_entry.get("1.0", "end-1c").strip()
            s = seq_entry.get().strip()
            s = int(s) if s.isdigit() else 0
            if not q or not a: return messagebox.showerror("Error", "Question and Answer required.", parent=modal)
            if not C.confirm("Save FAQ", f"{'Update' if existing_row else 'Add'} the answer to '{q}'?", parent=modal):
                return
            
            try:
                help_svc.save_faq(self.user_info, existing_row['id'] if existing_row else None, q, a, admin_var.get(), s)
                modal.destroy()
                if hasattr(self, '_faq_search_entry'):
                    self._render_faq_items(self._faq_search_entry.get().strip())
            except Exception as e:
                messagebox.showerror("Error", friendly_message(e), parent=modal)

        btn_row = ctk.CTkFrame(modal, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=20)
        C.button(btn_row, kind="primary", text="Update FAQ" if existing_row else "Save FAQ", command=save_faq).pack(side="left", expand=True, fill="x", padx=(0, 5))
        C.button(btn_row, kind="secondary", text="Cancel", command=modal.destroy).pack(side="right", expand=True, fill="x", padx=(5, 0))

    def render_about_tab(self):
        outer = ctk.CTkFrame(self.tab_content, fg_color=T.SURFACE, corner_radius=10)
        outer.grid(row=0, column=0, sticky="nsew")
        ctk.CTkLabel(outer, text="About the Champion Management System", font=T.font(16, "bold"), text_color=T.PRIMARY).pack(anchor="w", padx=20, pady=(16, 8))
        lines = ["Automated tool issuance, retrieval, inventory and maintenance for Champion Fine Tooling Corporation.",
                 "Built by Cayper Tech, Technological Institute of the Philippines (Software Engineering 2 and Project Management 3).",
                 intro_module.ABOUT_TEAM_NOTE]
        for line in lines:
            ctk.CTkLabel(outer, text=line, font=T.font(12), text_color=T.TEXT, wraplength=820, justify="left", anchor="w").pack(anchor="w", padx=20, pady=3)
        row = ctk.CTkFrame(outer, fg_color="transparent")
        row.pack(anchor="w", padx=20, pady=(16, 4))
        C.button(row, kind="primary", text="▶ Replay the intro", width=160,
                 command=lambda: intro_module.IntroWindow(self.winfo_toplevel(), first_run=False)).pack(side="left")
        self.about_status = ctk.CTkLabel(outer, text="", font=T.font(12), text_color=T.TEXT_MUTED)

        def reset_intro():
            if not C.confirm("Show introduction", "Show the introduction again the next time this program starts?", parent=self.winfo_toplevel()):
                return
            ok = prefs.set("intro_seen", False)
            self.about_status.configure(text="The intro will be shown the next time the program starts." if ok else "Could not save this setting on this computer.")
        C.button(row, kind="secondary", text="Show it again at next start", width=200, command=reset_intro).pack(side="left", padx=(10, 0))
        self.about_status.pack(anchor="w", padx=20, pady=4)

    def render_sysreq_tab(self):
        outer = ctk.CTkFrame(self.tab_content, fg_color=T.SURFACE, corner_radius=10)
        outer.grid(row=0, column=0, sticky="nsew")
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(1, weight=1)

        hdr = ctk.CTkFrame(outer, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 4))
        ctk.CTkLabel(hdr, text="System Requirements", font=T.font(16, "bold"), text_color=T.PRIMARY).pack(side="left")
        
        if self.is_admin:
            C.button(hdr, kind="primary", text="+ Add Requirement", width=140, command=lambda: self.open_sysreq_modal()).pack(side="right", padx=(10, 0))

        self._sysreq_scroll_frame = ctk.CTkScrollableFrame(outer, fg_color="transparent")
        self._sysreq_scroll_frame.grid(row=1, column=0, sticky="nsew")

        self._render_sysreq_content()

    def _render_sysreq_content(self):
        frame = self._sysreq_scroll_frame
        for w in frame.winfo_children():
            w.destroy()

        def render_table(parent, title, req_type):
            try:
                db_rows = help_svc.list_requirements(self.user_info, req_type)
                if not db_rows: return

                ctk.CTkLabel(parent, text=title, font=T.font(14, "bold"), text_color=T.TEXT).pack(anchor="w", padx=20, pady=(6, 4))
                card = ctk.CTkFrame(parent, fg_color=T.SURFACE_ALT, corner_radius=8, border_width=1, border_color=T.BORDER)
                card.pack(fill="x", padx=20, pady=(0, 12))
    
                for row_idx, db_row in enumerate(db_rows):
                    row = ctk.CTkFrame(card, fg_color=T.SURFACE_MUTED if row_idx % 2 == 0 else "transparent", height=34)
                    row.pack(fill="x")
                    row.pack_propagate(False)
                    row.grid_columnconfigure(0, weight=1)
                    row.grid_columnconfigure(1, weight=2)
                    row.grid_columnconfigure(2, weight=0)
                    
                    ctk.CTkLabel(row, text=db_row["component"], font=T.font(12, "bold"), text_color=T.PRIMARY).grid(row=0, column=0, padx=14, pady=6, sticky="w")
                    ctk.CTkLabel(row, text=db_row["specification"], font=T.font(12), text_color=T.TEXT).grid(row=0, column=1, padx=14, pady=6, sticky="w")
                    
                    if self.is_admin:
                        act = ctk.CTkFrame(row, fg_color="transparent")
                        act.grid(row=0, column=2, padx=8, pady=4, sticky="e")
                        C.button(act, compact=True, kind="primary", text="✎ Edit", width=50, command=lambda r=db_row: self.open_sysreq_modal(r)).pack(side="left", padx=(0, 4))
                        C.button(act, compact=True, kind="danger", text="🗑 Remove", width=50, command=lambda r_id=db_row["id"]: self.delete_sysreq(r_id)).pack(side="left")
            except Exception as e:
                ctk.CTkLabel(parent, text=friendly_message(e), text_color=T.DANGER_TEXT).pack(pady=10)

        render_table(frame, "Hardware Requirements", "Hardware")
        render_table(frame, "Software Requirements", "Software")

        ctk.CTkLabel(
            frame,
            text="Note: The system is a LAN-based desktop application. No internet connection is required "
                 "for normal operation. All data is stored locally in the MySQL database.",
            font=T.font(12), text_color=T.TEXT_MUTED, wraplength=780, justify="left"
        ).pack(anchor="w", padx=20, pady=(0, 20))

    def delete_sysreq(self, req_id):
        if not C.confirm("Confirm Delete", "Are you sure you want to remove this requirement?", parent=self.winfo_toplevel()): return
        try:
            help_svc.delete_requirement(self.user_info, req_id)
            self._render_sysreq_content()
        except Exception as e:
            messagebox.showerror("Error", friendly_message(e), parent=self.winfo_toplevel())

    def open_sysreq_modal(self, existing_row=None):
        dialog = ctk.CTkToplevel(self.winfo_toplevel())
        dialog.title("Edit Requirement" if existing_row else "Add Requirement")
        dialog.configure(fg_color=T.SURFACE)
        dialog.attributes("-topmost", True)
        dialog.grab_set()
        
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (500 // 2)
        y = (dialog.winfo_screenheight() // 2) - (600 // 2)
        dialog.geometry(f"500x600+{x}+{y}")

        ctk.CTkLabel(dialog, text="Requirement Type:", font=T.font(12, "bold"), text_color=T.TEXT).pack(anchor="w", padx=20, pady=(20, 5))
        type_var = ctk.StringVar(value="Hardware")
        rad_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        rad_frame.pack(fill="x", padx=20)
        ctk.CTkRadioButton(rad_frame, text="Hardware", variable=type_var, value="Hardware", fg_color=T.PRIMARY).pack(side="left", padx=(0, 20))
        ctk.CTkRadioButton(rad_frame, text="Software", variable=type_var, value="Software", fg_color=T.PRIMARY).pack(side="left")

        ctk.CTkLabel(dialog, text="Component / Label:", font=T.font(12, "bold"), text_color=T.TEXT).pack(anchor="w", padx=20, pady=(10, 5))
        comp_entry = C.field(dialog, placeholder_text="e.g., RAM")
        comp_entry.pack(fill="x", padx=20)

        ctk.CTkLabel(dialog, text="Specification / Value:", font=T.font(12, "bold"), text_color=T.TEXT).pack(anchor="w", padx=20, pady=(10, 5))
        spec_entry = C.field(dialog, placeholder_text="e.g., Minimum 8 GB")
        spec_entry.pack(fill="x", padx=20)
        
        ctk.CTkLabel(dialog, text="Display Sequence:", font=T.font(12, "bold"), text_color=T.TEXT).pack(anchor="w", padx=20, pady=(10, 5))
        seq_entry = C.field(dialog, placeholder_text="0")
        seq_entry.pack(fill="x", padx=20)

        if existing_row:
            type_var.set(existing_row['req_type'])
            comp_entry.insert(0, existing_row['component'])
            spec_entry.insert(0, existing_row['specification'])
            seq_entry.insert(0, str(existing_row['display_order']))
        else:
            seq_entry.insert(0, "0")

        def save_req():
            t = type_var.get()
            c_val = comp_entry.get().strip()
            s_val = spec_entry.get().strip()
            seq = seq_entry.get().strip()
            seq = int(seq) if seq.isdigit() else 0
            if not c_val or not s_val: return messagebox.showerror("Error", "All fields required.", parent=dialog)
            if not C.confirm("Save requirement", f"{'Update' if existing_row else 'Add'} the requirement for {c_val}?", parent=dialog):
                return
            
            try:
                help_svc.save_requirement(self.user_info, existing_row['id'] if existing_row else None, t, c_val, s_val, seq)
                dialog.destroy()
                self._render_sysreq_content()
            except Exception as e:
                messagebox.showerror("Error", friendly_message(e), parent=dialog)

        btn_row = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=20)
        C.button(btn_row, kind="primary", text="Update Requirement" if existing_row else "Save Requirement", command=save_req).pack(side="left", expand=True, fill="x", padx=(0, 5))
        C.button(btn_row, kind="secondary", text="Cancel", command=dialog.destroy).pack(side="right", expand=True, fill="x", padx=(5, 0))

    def render_tickets_tab(self):
        frame = ctk.CTkFrame(self.tab_content, fg_color=T.SURFACE, corner_radius=10)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)

        if not self.is_admin:
            form_bg = ctk.CTkFrame(frame, fg_color=T.SURFACE_ALT, corner_radius=10)
            form_bg.pack(fill="x", padx=20, pady=(20, 10))

            ctk.CTkLabel(form_bg, text="Submit an Inquiry", font=T.font(14, "bold"), text_color=T.TEXT).pack(anchor="w", padx=15, pady=(15, 5))

            subj_entry = C.field(form_bg, placeholder_text="Subject...")
            subj_entry.pack(fill="x", padx=15, pady=5)

            msg_entry = ctk.CTkTextbox(form_bg, height=60)
            msg_entry.pack(fill="x", padx=15, pady=5)

            def submit_ticket():
                subj = subj_entry.get().strip()
                msg = msg_entry.get("1.0", "end-1c").strip()
                if not subj or not msg:
                    messagebox.showerror("Error", "Subject and message required.", parent=self.winfo_toplevel())
                    return
                if not C.confirm("Send support request", f"Send '{subj}' to the administrator?", parent=self.winfo_toplevel()):
                    return

                try:
                    help_svc.submit_ticket(self.user_info, subj, msg)
                except Exception as e:
                    messagebox.showerror("Could not send", friendly_message(e), parent=self.winfo_toplevel())
                    return
                C.notify(self, "Ticket submitted to the Admin.")
                subj_entry.delete(0, 'end'); msg_entry.delete("1.0", "end")
                load_ticket_list()

            C.button(form_bg, kind="primary", text="Send to Admin", command=submit_ticket).pack(anchor="e", padx=15, pady=(5, 15))

        ctk.CTkLabel(frame, text="Ticket Inbox" if self.is_admin else "My Previous Tickets", font=T.font(14, "bold"), text_color=T.TEXT).pack(anchor="w", padx=20, pady=(10, 5))

        scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        def load_ticket_list():
            for w in scroll.winfo_children(): w.destroy()
            try:
                tickets = help_svc.list_tickets(self.user_info)
            except Exception as e:
                ctk.CTkLabel(scroll, text=friendly_message(e), text_color=T.DANGER_TEXT).pack(pady=10)
                return
            try:
                for t in tickets:
                    card = ctk.CTkFrame(scroll, fg_color=T.SURFACE_ALT, corner_radius=8, border_width=1, border_color=T.BORDER)
                    card.pack(fill="x", pady=5)

                    header = ctk.CTkFrame(card, fg_color="transparent")
                    header.pack(fill="x", padx=15, pady=(10, 5))

                    status_col=T.DANGER if t['status'] == 'Open' else T.SUCCESS_TEXT
                    ctk.CTkLabel(header, text=f"[{t['status']}]", font=T.font(12, "bold"), text_color=status_col).pack(side="left", padx=(0, 10))
                    ctk.CTkLabel(header, text=t['subject'], font=T.font(12, "bold"), text_color=T.TEXT).pack(side="left")
                    if self.is_admin:
                        ctk.CTkLabel(header, text=f"From: {t['full_name']}", font=T.font(12), text_color=T.TEXT_MUTED).pack(side="right")

                    ctk.CTkLabel(card, text=t['message'], font=T.font(12), text_color=T.TEXT_SECONDARY, justify="left", wraplength=700).pack(anchor="w", padx=15, pady=5)

                    if t['admin_reply']:
                        reply_box = ctk.CTkFrame(card, fg_color=T.INFO_BG, corner_radius=5)
                        reply_box.pack(fill="x", padx=15, pady=(5, 10))
                        ctk.CTkLabel(reply_box, text=f"Admin Reply: {t['admin_reply']}", font=T.font(12, "bold"), text_color=T.PRIMARY, justify="left", wraplength=650).pack(anchor="w", padx=10, pady=10)
                    elif self.is_admin and t['status'] == 'Open':
                        reply_entry = C.field(card, placeholder_text="Type reply here...")
                        reply_entry.pack(fill="x", padx=15, pady=5)

                        def send_reply(tid=t['ticket_id'], e=reply_entry):
                            rep = e.get().strip()
                            if not rep: return
                            try:
                                help_svc.reply_ticket(self.user_info, tid, rep)
                            except Exception as ex:
                                messagebox.showerror("Could not reply", friendly_message(ex), parent=self.winfo_toplevel())
                                return
                            load_ticket_list()

                        C.button(card, compact=True, kind="primary", text="Reply & Resolve", width=120, command=send_reply).pack(anchor="e", padx=15, pady=(0, 10))
            except Exception as e:
                ctk.CTkLabel(scroll, text=friendly_message(e), text_color=T.DANGER_TEXT).pack(pady=10)

        load_ticket_list()
