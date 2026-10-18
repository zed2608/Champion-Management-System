"""Help module data: guides, FAQs, system requirements and support tickets.

[RBAC] Everyone who can log in (Admin, Staff) may READ help content and open a support ticket; only an Admin may edit the content
or answer a ticket. A Staff member sees only their own tickets. Every function re-checks the role in MySQL (see services/security.py).
"""
from db import db
from services.errors import NotFound, ServiceError
from services.security import require_role
from services.validators import ValidationError, clean_text

STEP_SEPARATOR = "|||"
REQ_TYPES = ("Hardware", "Software")


def _int(value, field, low=0, high=10_000):
    try:
        n = int(str(value).strip() or 0)
    except ValueError:
        raise ValidationError(f"{field} must be a whole number.")
    if not low <= n <= high:
        raise ValidationError(f"{field} must be between {low} and {high}.")
    return n


# ---- seeding -------------------------------------------------------------------------------------------------------------------
@require_role("Admin", "Staff")
def seed_defaults(actor, guides, faqs, hardware, software):
    """Fill EMPTY help tables from the built-in text (never overwrites anything). guides: [(admin_only, title, [points])],
    faqs: [(admin_only, question, answer)], hardware/software: [(component, specification)]."""
    with db.transaction() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM help_guides")
        if cur.fetchone()["n"] == 0:
            for i, (admin_only, title, points) in enumerate(guides):
                cur.execute("INSERT INTO help_guides (title, steps, is_admin_only, display_order) VALUES (%s,%s,%s,%s)",
                            (title, STEP_SEPARATOR.join(points), int(bool(admin_only)), i))
        cur.execute("SELECT COUNT(*) AS n FROM help_faqs")
        if cur.fetchone()["n"] == 0:
            for i, (admin_only, q, a) in enumerate(faqs):
                cur.execute("INSERT INTO help_faqs (question, answer, is_admin_only, display_order) VALUES (%s,%s,%s,%s)", (q, a, int(bool(admin_only)), i))
        cur.execute("SELECT COUNT(*) AS n FROM system_requirements")
        if cur.fetchone()["n"] == 0:
            for kind, specs in (("Hardware", hardware), ("Software", software)):
                for i, (comp, spec) in enumerate(specs):
                    cur.execute("INSERT INTO system_requirements (req_type, component, specification, display_order) VALUES (%s,%s,%s,%s)", (kind, comp, spec, i))


# ---- reading -------------------------------------------------------------------------------------------------------------------
@require_role("Admin", "Staff")
def list_guides(actor):
    """Admin-only sections are returned to Admins only."""
    with db.read() as cur:
        cur.execute("SELECT * FROM help_guides ORDER BY display_order ASC, id ASC")
        rows = cur.fetchall()
    return rows if actor["role"] == "Admin" else [r for r in rows if not r["is_admin_only"]]


@require_role("Admin", "Staff")
def list_faqs(actor):
    with db.read() as cur:
        cur.execute("SELECT * FROM help_faqs ORDER BY display_order ASC, id ASC")
        rows = cur.fetchall()
    return rows if actor["role"] == "Admin" else [r for r in rows if not r["is_admin_only"]]


@require_role("Admin", "Staff")
def list_requirements(actor, req_type):
    if req_type not in REQ_TYPES:
        raise ValidationError("Unknown requirement type.")
    with db.read() as cur:
        cur.execute("SELECT * FROM system_requirements WHERE req_type=%s ORDER BY display_order ASC, id ASC", (req_type,))
        return cur.fetchall()


# ---- editing (Admin) ---------------------------------------------------------------------------------------------------------
@require_role("Admin")
def save_guide(actor, guide_id, title, points, admin_only, display_order):
    title = clean_text(title, max_len=200, field="Title")
    steps = [clean_text(p, max_len=1000, field="Step", required=False, multiline=True) for p in (points or [])]
    steps = [p for p in steps if p]
    if not steps:
        raise ValidationError("Add at least one step.")
    if any(STEP_SEPARATOR in p for p in steps):
        raise ValidationError("A step cannot contain '|||'.")
    order = _int(display_order, "Display order")
    with db.transaction() as cur:
        if guide_id:
            cur.execute("UPDATE help_guides SET title=%s, steps=%s, is_admin_only=%s, display_order=%s WHERE id=%s",
                        (title, STEP_SEPARATOR.join(steps), int(bool(admin_only)), order, int(guide_id)))
            if cur.rowcount == 0:
                cur.execute("SELECT 1 FROM help_guides WHERE id=%s", (int(guide_id),))
                if cur.fetchone() is None:
                    raise NotFound("That guide no longer exists.")
        else:
            cur.execute("INSERT INTO help_guides (title, steps, is_admin_only, display_order) VALUES (%s,%s,%s,%s)",
                        (title, STEP_SEPARATOR.join(steps), int(bool(admin_only)), order))
    return {"title": title}


@require_role("Admin")
def delete_guide(actor, guide_id):
    return _delete("help_guides", guide_id, "guide")


@require_role("Admin")
def save_faq(actor, faq_id, question, answer, admin_only, display_order):
    question = clean_text(question, max_len=500, field="Question")
    answer = clean_text(answer, max_len=4000, field="Answer", multiline=True)
    order = _int(display_order, "Display order")
    with db.transaction() as cur:
        if faq_id:
            cur.execute("UPDATE help_faqs SET question=%s, answer=%s, is_admin_only=%s, display_order=%s WHERE id=%s",
                        (question, answer, int(bool(admin_only)), order, int(faq_id)))
            if cur.rowcount == 0:
                cur.execute("SELECT 1 FROM help_faqs WHERE id=%s", (int(faq_id),))
                if cur.fetchone() is None:
                    raise NotFound("That FAQ no longer exists.")
        else:
            cur.execute("INSERT INTO help_faqs (question, answer, is_admin_only, display_order) VALUES (%s,%s,%s,%s)",
                        (question, answer, int(bool(admin_only)), order))
    return {"question": question}


@require_role("Admin")
def delete_faq(actor, faq_id):
    return _delete("help_faqs", faq_id, "FAQ")


@require_role("Admin")
def save_requirement(actor, req_id, req_type, component, specification, display_order):
    if req_type not in REQ_TYPES:
        raise ValidationError("Type must be Hardware or Software.")
    component = clean_text(component, max_len=100, field="Component")
    specification = clean_text(specification, max_len=500, field="Specification")
    order = _int(display_order, "Display order")
    with db.transaction() as cur:
        if req_id:
            cur.execute("UPDATE system_requirements SET req_type=%s, component=%s, specification=%s, display_order=%s WHERE id=%s",
                        (req_type, component, specification, order, int(req_id)))
            if cur.rowcount == 0:
                cur.execute("SELECT 1 FROM system_requirements WHERE id=%s", (int(req_id),))
                if cur.fetchone() is None:
                    raise NotFound("That requirement no longer exists.")
        else:
            cur.execute("INSERT INTO system_requirements (req_type, component, specification, display_order) VALUES (%s,%s,%s,%s)",
                        (req_type, component, specification, order))
    return {"component": component}


@require_role("Admin")
def delete_requirement(actor, req_id):
    return _delete("system_requirements", req_id, "requirement")


def _delete(table, row_id, noun):
    allowed = {"help_guides", "help_faqs", "system_requirements"}
    if table not in allowed:                                  # table names are never user input; this is a belt-and-braces check
        raise ServiceError("Not allowed.")
    with db.transaction() as cur:
        cur.execute(f"DELETE FROM {table} WHERE id=%s", (int(row_id),))
        if cur.rowcount == 0:
            raise NotFound(f"That {noun} no longer exists.")
    return {"deleted": int(row_id)}


# ---- support tickets ---------------------------------------------------------------------------------------------------------
@require_role("Admin", "Staff")
def submit_ticket(actor, subject, message):
    subject = clean_text(subject, max_len=200, field="Subject")
    message = clean_text(message, max_len=4000, field="Message", multiline=True)
    with db.transaction() as cur:
        cur.execute("INSERT INTO help_tickets (user_id, subject, message) VALUES (%s,%s,%s)", (actor["user_id"], subject, message))
        return {"ticket_id": cur.lastrowid}


@require_role("Admin", "Staff")
def list_tickets(actor):
    """Admin: every ticket, open first. Staff: only their own."""
    base = "SELECT h.*, u.full_name FROM help_tickets h JOIN user u ON h.user_id = u.user_id"
    with db.read() as cur:
        if actor["role"] == "Admin":
            cur.execute(base + " ORDER BY h.status ASC, h.created_at DESC, h.ticket_id DESC")
        else:
            cur.execute(base + " WHERE h.user_id = %s ORDER BY h.created_at DESC, h.ticket_id DESC", (actor["user_id"],))
        return cur.fetchall()


@require_role("Admin")
def reply_ticket(actor, ticket_id, reply):
    reply = clean_text(reply, max_len=4000, field="Reply", multiline=True)
    with db.transaction() as cur:
        cur.execute("UPDATE help_tickets SET admin_reply=%s, status='Resolved' WHERE ticket_id=%s", (reply, int(ticket_id)))
        if cur.rowcount == 0:
            cur.execute("SELECT 1 FROM help_tickets WHERE ticket_id=%s", (int(ticket_id),))
            if cur.fetchone() is None:
                raise NotFound("That ticket no longer exists.")
    return {"ticket_id": int(ticket_id)}
