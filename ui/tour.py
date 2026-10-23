"""Short guided tour of the live desktop screens.

The tour never clicks Save or changes operational records (navigation is audited). It follows the real sidebar,
uses the signed-in role to choose screens, and can be exited at any time.
"""
from dataclasses import dataclass

import customtkinter as ctk

from ui import components as C
from ui import theme as T


@dataclass(frozen=True)
class Step:
    page: str
    title: str
    detail: str
    target: str = "page"
    tab: str = ""


COMMON = (
    Step("Dashboard", "Find your way", "The left menu opens each section. Your current section stays highlighted.", "nav:Dashboard"),
    Step("Dashboard", "Your overview", "The four cards show the numbers that need attention. Choose a card to open its section.", "cards"),
    Step("Project Management", "Projects", "See project dates, assigned workers and the tools each project needs.", "nav:Project Management"),
    Step("Project Management", "Project rules", "Admins create projects. A worker must be assigned before tools can be issued. End Date must be on or after Start Date."),
    Step("Inventory", "Inventory", "Search and sort tools here. Available stock goes down when tools are issued and rises when good tools return.", "search"),
    Step("Inventory", "Tags and labels", "Only tools with a Tag ID can be selected for printing. Untagged rows say “Tag first.”", "print"),
    Step("Inventory", "Tool details", "Choose a row to see its stock, condition and tag. Admins can edit tools; Staff can tag tools without a tag."),
    Step("Issuance & Retrieval", "Issue tools", "Verify the worker's Employee ID, choose an assigned project, then scan a tool tag. The system checks stock and the approved quantity.", "button:Issue Tools", "📋 Deployment History"),
    Step("Issuance & Retrieval", "Return tools", "Find the worker's active tool, enter how many came back and choose its condition. Damaged or lost returns need details.", "button:Retrieve Tools", "📋 Deployment History"),
    Step("Issuance & Retrieval", "Deployment schedule", "This calendar shows which projects are planned for each day. Move between months to see future work.", "tabs", "📅 Deployment Schedule"),
    Step("Issuance & Retrieval", "Connected records", "Each issue and return updates inventory and the movement history. A return frees the project's quantity for a replacement.", "tabs", "📋 Deployment History"),
    Step("Tracking & Accountability", "Tool history", "Use this section to check who received a tool, when it was issued and whether it was returned.", "tabs", "📋 Issuance & Retrieval Logs"),
    Step("Help", "Help Guide", "The guide explains sign-in, projects, inventory, tool movement and other sections step by step.", "tabs", "    ▤ Help Guide    "),
    Step("Help", "Common questions", "FAQs answer frequent questions about tags, dates, returns and reports.", "tabs", "         💬 FAQs         "),
    Step("Help", "Ask for help", "Use Support Tickets to send a question to an Admin and read the answer later.", "tabs", "   ✉ Support Tickets   "),
    Step("Profile", "Your profile", "Choose your name at the top to update your details, change your password or print your badge.", "profile"),
)

ADMIN_ONLY = (
    Step("Dashboard", "System status", "Admins see a short backup, records and tool service summary. Choose Show details for more.", "status"),
    Step("Project Management", "Manage projects", "Add a project, assign workers and request tools. Once tools have been issued, its dates and requirements are locked.", "button:Add Project"),
    Step("Tracking & Accountability", "Audit records", "Compare tools that are out with those that were returned and review differences.", "tabs", "🔎 Audit Records"),
    Step("Tracking & Accountability", "Activity Log", "See actions taken in the system and verify that the audit record is intact.", "tabs", "⚙️ Activity Log"),
    Step("Reports", "Inventory ABC", "See which tools are used most often and which need closer stock attention.", "tabs", "▤ Inventory ABC Analysis"),
    Step("Reports", "Tool use", "See how often each tool was borrowed and how much stock remains.", "tabs", "⛭ Tool Usage Report"),
    Step("Reports", "Worker activity", "Review issues and returns by employee.", "tabs", "🖹 Employee Activity"),
    Step("Reports", "Project allocation", "See which tools have been assigned or issued to each project.", "tabs", "📋 Project Allocation"),
    Step("Reports", "Damage and loss", "See damaged and lost units and their costs.", "tabs", "⚠ Damage & Loss"),
    Step("Reports", "Low stock", "Find items near or below their minimum stock level.", "tabs", "⭣ Low Stock"),
    Step("Reports", "Overdue tools", "See tools still out after their project due date.", "tabs", "⧖ Overdue Transactions"),
    Step("Reports", "Tool wear", "See equipment that may be due for service.", "tabs", "🔧 Wear"),
    Step("Reports", "Unusual activity", "See repeated stock shortages or patterns that need a closer look.", "tabs", "🔎 Anomalies"),
    Step("Reports", "Export a PDF", "Choose a date range if needed, then choose Export PDF. Empty dates include all records.", "button:Export PDF"),
    Step("Maintenance", "Tool issues", "Review repairs, damage and lost tools. Resolving an issue updates stock and condition.", "tabs", "🔧 Issues & Repairs"),
    Step("Maintenance", "Archived tools", "Restore a tool that was archived after all of its units were returned or resolved.", "tabs", "📦 Archived Tools"),
    Step("Maintenance", "Archived people", "Admins can review and restore accounts that were deactivated.", "tabs", "👥 Archived Employees"),
    Step("Maintenance", "Archived projects", "Completed or cancelled projects can be archived while keeping their history.", "tabs", "📋 Archived Projects"),
    Step("Maintenance", "Service forecast", "Review hours used and which equipment is due for attention.", "tabs", "📈 Wear Forecast"),
    Step("Maintenance", "Backup and restore", "Backups protect the database. Restore replaces its data, so use the correct file and database.", "tabs", "💾 Backup & Restore"),
    Step("Role Management", "People and roles", "Admins register Staff and Workers, update accounts and print Worker badges. Workers do not sign in.", "button:Register New User"),
)


def steps_for(role):
    """Follow the sidebar in a useful order; Staff never sees Admin-only pages."""
    by_page = {}
    for step in COMMON + (ADMIN_ONLY if role == "Admin" else ()):
        by_page.setdefault(step.page, []).append(step)
    order = ("Dashboard", "Project Management", "Inventory", "Issuance & Retrieval",
             "Tracking & Accountability", "Reports", "Maintenance", "Role Management", "Help", "Profile")
    return tuple(step for page in order for step in by_page.get(page, ()))


class GuidedTour:
    """A small docked panel with a four-edge outline around the relevant live control."""

    def __init__(self, app):
        self.app = app
        self.steps = steps_for(app.user_info.get("role", "Staff"))
        self.index = 0
        self._job = None
        self.panel = C.card(app, width=440)
        self.panel.place(relx=1, rely=1, x=-18, y=-18, anchor="se")
        ctk.CTkLabel(self.panel, text="GUIDED TOUR", font=T.font(12, "bold"),
                     text_color=T.PRIMARY).pack(anchor="w", padx=18, pady=(15, 0))
        self.title = ctk.CTkLabel(self.panel, text="", font=T.font(18, "bold"),
                                  text_color=T.TEXT, anchor="w")
        self.title.pack(fill="x", padx=18, pady=(4, 2))
        self.detail = ctk.CTkLabel(self.panel, text="", font=T.font(13),
                                   text_color=T.TEXT, justify="left", anchor="w", wraplength=400)
        self.detail.pack(fill="x", padx=18, pady=(0, 8))
        self.progress = ctk.CTkLabel(self.panel, text="", font=T.font(12), text_color=T.TEXT_SECONDARY)
        self.progress.pack(anchor="w", padx=18)
        controls = ctk.CTkFrame(self.panel, fg_color="transparent")
        controls.pack(fill="x", padx=14, pady=(5, 14))
        C.button(controls, text="Exit tour", command=self.close, kind="ghost", compact=True).pack(side="left")
        C.button(controls, text="Next section", command=self.next_section, kind="ghost", compact=True).pack(side="left", padx=(3, 0))
        self.next_button = C.button(controls, text="Next", command=self.next, kind="primary", compact=True, width=90)
        self.next_button.pack(side="right")
        self.back_button = C.button(controls, text="Back", command=self.back, kind="secondary", compact=True, width=75)
        self.back_button.pack(side="right", padx=(0, 8))
        self.edges = [ctk.CTkFrame(app, fg_color=T.ACCENT, corner_radius=0) for _ in range(4)]
        self.show()

    def _target(self, target):
        if target.startswith("nav:"):
            return self.app.nav_buttons.get(target[4:])
        if target == "profile":
            return self.app.user_frame
        frame = self.app.current_frame
        if target == "tabs":
            return getattr(frame, "seg_btn", frame)
        if target.startswith("button:"):
            label = target[7:]
            pending = [frame]
            while pending:
                widget = pending.pop(0)
                if isinstance(widget, ctk.CTkButton) and label in str(widget.cget("text")):
                    return widget
                pending.extend(widget.winfo_children())
            return frame
        if target == "cards":
            return getattr(self.app, "dash_cards_frame", frame)
        if target == "status":
            return getattr(self.app, "ins_summary", frame)
        if target == "search":
            return getattr(frame, "search_entry", frame)
        if target == "print":
            return getattr(frame, "batch_print_btn", frame)
        return frame

    def _outline(self):
        self._job = None
        if not self.panel.winfo_exists():
            return
        widget = self._target(self.steps[self.index].target)
        for edge in self.edges:
            edge.place_forget()
        try:
            if widget is None or not widget.winfo_exists() or not widget.winfo_ismapped():
                return
            self.app.update_idletasks()
            x = widget.winfo_rootx() - self.app.winfo_rootx()
            y = widget.winfo_rooty() - self.app.winfo_rooty()
            w, h = widget.winfo_width(), widget.winfo_height()
            if w < 2 or h < 2:
                return
            t = 3
            for edge, (ex, ey, ew, eh) in zip(self.edges, ((x, y, w, t), (x, y + h - t, w, t),
                                                             (x, y, t, h), (x + w - t, y, t, h))):
                edge.place(x=ex, y=ey, width=ew, height=eh)
                edge.lift()
            self.panel.lift()
        except Exception:
            pass  # A view may have been replaced by its asynchronous loader.

    def show(self):
        step = self.steps[self.index]
        if self.app.current_page_name != step.page:
            self.app.show_frame(step.page, tour_navigation=True)
        frame = self.app.current_frame
        if step.tab and hasattr(frame, "seg_btn") and frame.tab_var.get() != step.tab:
            frame.seg_btn.set(step.tab)
            frame.switch_tab(step.tab)
        self.title.configure(text=step.title)
        self.detail.configure(text=step.detail)
        self.progress.configure(text=f"Step {self.index + 1} of {len(self.steps)}  •  {step.page}")
        self.back_button.configure(state="normal" if self.index else "disabled")
        self.next_button.configure(text="Finish" if self.index == len(self.steps) - 1 else "Next")
        self._outline()
        if self._job is not None:
            self.app.after_cancel(self._job)
        self._job = self.app.after(350, self._outline)  # let async screens build their controls

    def next(self):
        if self.index == len(self.steps) - 1:
            self.close()
        else:
            self.index += 1
            self.show()

    def back(self):
        if self.index:
            self.index -= 1
            self.show()

    def next_section(self):
        page = self.steps[self.index].page
        following = next((i for i in range(self.index + 1, len(self.steps))
                          if self.steps[i].page != page), None)
        if following is None:
            self.close()
        else:
            self.index = following
            self.show()

    def close(self):
        if self._job is not None:
            self.app.after_cancel(self._job)
            self._job = None
        for edge in self.edges:
            edge.destroy()
        self.panel.destroy()
        if getattr(self.app, "guided_tour", None) is self:
            self.app.guided_tour = None
