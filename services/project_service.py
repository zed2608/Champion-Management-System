"""Project lifecycle: create, edit, status changes, archive and restore.

[STATE-MACHINE] Allowed status changes live in the ``project_transitions`` table (shared with the database trigger
``trg_projects_bu``). Every change is ``UPDATE ... WHERE project_id = %s AND status = <expected>`` and the row count is checked,
so a stale screen can never overwrite a newer state ("changed by someone else").
[4-DATE] start <= end is a hard rule. Once any tool has been issued to a project (or it is Ongoing/Completed) its dates, workers
and requirements are read-only: the service says so in plain words and the trigger enforces it for any other route.
[CONCURRENCY] Editing DIFFS the requirement lines instead of deleting and re-inserting them (the old way wiped the Fulfilled flags).
[RBAC] Admin only. An Admin-created project is auto-approved: there is no separate approve step (the manuscript's "remove double
validation" recommendation). Staff have read-only Project Management; to let Staff save drafts again add "Staff" to DRAFT_ROLES
(a Staff-created project would then start as Pending and need an Admin to approve it).
"""
import difflib
from decimal import Decimal

from db import db
from services import validators as v
from services.errors import Conflict, NotFound
from services.security import require_role

DRAFT_ROLES = ("Admin",)
EDITABLE_STATUSES = ("Pending", "Approved")
FINISHED_STATUSES = ("Completed", "Declined", "Cancelled")
MAX_PROJECT_TEXT = 255


def find_similar_names(name, exclude_project_id=None):
    """Read-only helper for the "Similar name detected" prompt: (exact_match, similar_names[:3]) among active projects."""
    name = v.clean_named_label(name, max_len=MAX_PROJECT_TEXT, field="Project Name")
    with db.read() as cur:
        cur.execute("SELECT name FROM projects WHERE archived_at IS NULL AND project_id <> %s", (exclude_project_id or 0,))
        existing = [r["name"] for r in cur.fetchall() if r["name"]]
    exact = any(n.lower() == name.lower() for n in existing)
    similar = [n for n in existing if n.lower() != name.lower()
               and difflib.SequenceMatcher(None, name.lower(), n.lower()).ratio() > 0.85]
    return exact, similar[:3]


def _normalise(cur, data, exclude_project_id=None):
    """Validate and normalise the form. Returns a dict with cleaned scalars, worker rows and requirement lines."""
    f = {
        "name": v.clean_named_label(data.get("name"), max_len=MAX_PROJECT_TEXT, field="Project Name"),
        "client": v.clean_named_label(data.get("client"), max_len=MAX_PROJECT_TEXT, field="Client"),
        "project_head": v.clean_person_name(data.get("project_head"), max_len=MAX_PROJECT_TEXT,
                                              field="Project Head", required=False) or None,
        "location": v.clean_text(data.get("location"), max_len=MAX_PROJECT_TEXT, field="Location", required=False) or None,
        "description": v.clean_text(data.get("description"), max_len=2000, field="Description", required=False, multiline=True) or None,
        "start_date": v.parse_iso_date(data.get("start_date"), field="Start Date", required=False),
        "end_date": v.parse_iso_date(data.get("end_date"), field="End Date", required=False),
    }
    v.validate_date_range(f["start_date"], f["end_date"])

    cur.execute("SELECT 1 AS x FROM projects WHERE archived_at IS NULL AND name = %s AND project_id <> %s",
                (f["name"], exclude_project_id or 0))
    if cur.fetchone():
        raise Conflict(f"An active project named '{f['name']}' already exists.")

    # workers: exact employee ids of ACTIVE accounts (typed or scanned), no duplicates
    wanted, seen = [], set()
    for raw in data.get("workers") or []:
        emp = v.clean_text(raw, max_len=50, field="Worker ID")
        if emp.upper() in seen:
            continue
        seen.add(emp.upper())
        wanted.append(emp)
    workers = []
    for emp in wanted:
        cur.execute("SELECT user_id, employee_id, status FROM `user` WHERE employee_id = %s", (emp,))
        u = cur.fetchone()
        if not u:
            raise v.ValidationError(f"Employee ID '{emp}' was not found.")
        if u["status"] != "Active":
            raise v.ValidationError(f"Employee {u['employee_id']} is {u['status']} and cannot be assigned to a project.")
        workers.append(u)
    f["workers"] = workers

    # requirements: active tools, valid quantities (whole for equipment), one line per tool
    lines = {}
    for item in data.get("requirements") or []:
        cur.execute("SELECT tool_id, name, item_type, is_archived FROM tool WHERE tool_id = %s", (item.get("tool_id"),))
        t = cur.fetchone()
        if not t:
            raise v.ValidationError("A required tool no longer exists.")
        if t["is_archived"]:
            raise v.ValidationError(f"'{t['name']}' is archived and cannot be required by a project.")
        qty = v.parse_quantity(item.get("qty"), whole=(t["item_type"] or "Equipment") != "Consumable", field=f"Quantity for {t['name']}")
        line = lines.setdefault(t["tool_id"], {"tool_id": t["tool_id"], "qty": Decimal(0), "warning": False, "name": t["name"]})
        line["qty"] += qty
        line["warning"] = line["warning"] or bool(item.get("needs_retrieval"))
    if not lines:
        raise v.ValidationError("Please add at least one tool requirement.")
    f["requirements"] = list(lines.values())
    return f


def _write_workers(cur, project_id, workers):
    cur.execute("DELETE FROM project_workers WHERE project_id = %s", (project_id,))
    for u in workers:
        cur.execute("INSERT IGNORE INTO project_workers (project_id, user_id) VALUES (%s, %s)", (project_id, u["user_id"]))


@require_role(*DRAFT_ROLES)
def create_project(actor, data) -> dict:
    """Create a project. Created by an Admin it is Approved straight away (no approve step); otherwise Pending."""
    def work(cur):
        f = _normalise(cur, data)
        status = "Approved" if actor["role"] == "Admin" else "Pending"
        cur.execute("""INSERT INTO projects (name, description, project_head, client, location, workers_assigned, start_date, end_date,
                                             manager_id, status, approved_by)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (f["name"], f["description"], f["project_head"], f["client"], f["location"],
                     ", ".join(u["employee_id"] for u in f["workers"]) or None, f["start_date"], f["end_date"],
                     actor["user_id"], status, actor["user_id"] if status == "Approved" else None))
        pid = cur.lastrowid
        _write_workers(cur, pid, f["workers"])
        for r in f["requirements"]:
            cur.execute("INSERT INTO project_requirements (project_id, tool_id, quantity, status) VALUES (%s, %s, %s, %s)",
                        (pid, r["tool_id"], r["qty"], "Warning" if r["warning"] else "Clear"))
        return {"project_id": pid, "name": f["name"], "status": status}

    return db.run_in_transaction(work)


def _lock_project(cur, project_id, expected_status=None):
    cur.execute("SELECT * FROM projects WHERE project_id = %s FOR UPDATE", (project_id,))
    p = cur.fetchone()
    if not p:
        raise NotFound("Project not found.")
    if p["archived_at"] is not None:
        raise Conflict("This project is archived. Restore it from Maintenance first.")
    if expected_status is not None and p["status"] != expected_status:
        raise Conflict(f"This project was changed by someone else (it is now {p['status']}). Please reload and try again.")
    return p


@require_role("Admin")
def update_project(actor, project_id, data, expected_status) -> dict:
    """Edit a Pending or Approved project. Schedule, workers and requirement lines are only editable while nothing has been issued."""
    def work(cur):
        p = _lock_project(cur, project_id, expected_status)
        if p["status"] not in EDITABLE_STATUSES:
            raise Conflict(f"This project is {p['status']} and can no longer be edited.")
        f = _normalise(cur, data, exclude_project_id=project_id)

        cur.execute("SELECT EXISTS(SELECT 1 FROM `transaction` WHERE project_id = %s) AS issued", (project_id,))
        issued = bool(cur.fetchone()["issued"])
        cur.execute("SELECT req_id, tool_id, quantity, status FROM project_requirements WHERE project_id = %s FOR UPDATE", (project_id,))
        existing = {r["tool_id"]: r for r in cur.fetchall()}
        cur.execute("SELECT user_id FROM project_workers WHERE project_id = %s", (project_id,))
        old_workers = {r["user_id"] for r in cur.fetchall()}

        new_workers = {u["user_id"] for u in f["workers"]}
        new_reqs = {r["tool_id"]: r for r in f["requirements"]}
        schedule_changed = (f["start_date"] != p["start_date"] or f["end_date"] != p["end_date"] or new_workers != old_workers
                            or set(new_reqs) != set(existing)
                            or any(Decimal(str(new_reqs[t]["qty"])) != Decimal(str(existing[t]["quantity"])) for t in new_reqs if t in existing))
        if issued and schedule_changed:
            raise Conflict("Tools have already been issued to this project, so its dates, workers and required tools can no longer "
                           "be changed. You can still edit the name, client, head, location and description.")

        cur.execute("""UPDATE projects SET name=%s, description=%s, project_head=%s, client=%s, location=%s WHERE project_id=%s""",
                    (f["name"], f["description"], f["project_head"], f["client"], f["location"], project_id))
        if not issued:
            cur.execute("UPDATE projects SET start_date=%s, end_date=%s, workers_assigned=%s WHERE project_id=%s",
                        (f["start_date"], f["end_date"], ", ".join(u["employee_id"] for u in f["workers"]) or None, project_id))
            _write_workers(cur, project_id, f["workers"])
            # diff the lines: unchanged lines keep their Fulfilled flag (the old delete-and-reinsert wiped it)
            for tool_id, r in new_reqs.items():
                flag = "Warning" if r["warning"] else "Clear"
                if tool_id in existing:
                    if Decimal(str(existing[tool_id]["quantity"])) != r["qty"]:
                        cur.execute("UPDATE project_requirements SET quantity=%s, status=%s WHERE req_id=%s", (r["qty"], flag, existing[tool_id]["req_id"]))
                    elif existing[tool_id]["status"] in ("Warning", "Clear") and existing[tool_id]["status"] != flag:
                        cur.execute("UPDATE project_requirements SET status=%s WHERE req_id=%s", (flag, existing[tool_id]["req_id"]))
                else:
                    cur.execute("INSERT INTO project_requirements (project_id, tool_id, quantity, status) VALUES (%s, %s, %s, %s)",
                                (project_id, tool_id, r["qty"], flag))
            for tool_id, row in existing.items():
                if tool_id not in new_reqs:
                    cur.execute("DELETE FROM project_requirements WHERE req_id = %s", (row["req_id"],))
        return {"project_id": project_id, "name": f["name"], "status": p["status"]}

    return db.run_in_transaction(work)


@require_role("Admin")
def transition(actor, project_id, new_status, expected_status) -> dict:
    """Move a project along an allowed edge of the state machine. ``expected_status`` is what the screen showed."""
    def work(cur):
        p = _lock_project(cur, project_id, expected_status)
        cur.execute("SELECT 1 AS x FROM project_transitions WHERE from_status = %s AND to_status = %s", (p["status"], new_status))
        if not cur.fetchone():
            raise Conflict(f"A project that is {p['status']} cannot be changed to {new_status}.")
        if new_status in ("Cancelled", "Completed"):
            cur.execute("SELECT COALESCE(SUM(quantity), 0) AS n FROM `transaction` WHERE project_id = %s AND status = 'Active'", (project_id,))
            out = Decimal(str(cur.fetchone()["n"]))
            if out > 0:
                verb = "cancelling" if new_status == "Cancelled" else "completing"
                raise Conflict(f"This project still has {v.fmt_qty(out)} tool(s) deployed. Please retrieve all tools before {verb} it.")
        sets, args = "status = %s", [new_status]
        if new_status == "Approved":
            sets += ", approved_by = %s"
            args.append(actor["user_id"])
        cur.execute(f"UPDATE projects SET {sets} WHERE project_id = %s AND status = %s AND archived_at IS NULL",
                    (*args, project_id, expected_status))
        if cur.rowcount != 1:
            raise Conflict("This project was changed by someone else. Please reload and try again.")
        return {"project_id": project_id, "name": p["name"], "status": new_status, "was": p["status"]}

    return db.run_in_transaction(work)


@require_role("Admin")
def archive_project(actor, project_id, expected_status) -> dict:
    """Archive a finished project (Completed / Declined / Cancelled). The trigger remembers the status it had."""
    def work(cur):
        p = _lock_project(cur, project_id, expected_status)
        if p["status"] not in FINISHED_STATUSES:
            raise Conflict("Only Completed, Declined or Cancelled projects can be archived.")
        cur.execute("UPDATE projects SET archived_at = NOW() WHERE project_id = %s AND archived_at IS NULL", (project_id,))
        return {"project_id": project_id, "name": p["name"], "status": p["status"]}

    return db.run_in_transaction(work)


@require_role("Admin")
def restore_project(actor, project_id) -> dict:
    """Restore an archived project to the status it had before it was archived (never blindly 'Approved')."""
    def work(cur):
        cur.execute("SELECT name, status, archived_at, status_before_archive FROM projects WHERE project_id = %s FOR UPDATE", (project_id,))
        p = cur.fetchone()
        if not p:
            raise NotFound("Project not found.")
        if p["archived_at"] is None:
            raise Conflict("This project is not archived.")
        cur.execute("UPDATE projects SET archived_at = NULL WHERE project_id = %s", (project_id,))
        cur.execute("SELECT status FROM projects WHERE project_id = %s", (project_id,))
        return {"project_id": project_id, "name": p["name"], "status": cur.fetchone()["status"]}

    return db.run_in_transaction(work)
