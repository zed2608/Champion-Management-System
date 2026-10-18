"""Help module through the service layer (no SQL in the screen any more) and the ticket rules."""
import pytest

from services import help_service as hs
from services.errors import NotFound, PermissionDenied
from services.validators import ValidationError

pytestmark = pytest.mark.db


def run(db, sql, params=()):
    with db.transaction() as cur:
        cur.execute(sql, params)
        return cur.lastrowid


@pytest.fixture
def people(svc):
    a = run(svc, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('ADM-2026-001','Admin','Admin','Active')")
    s1 = run(svc, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('STF-2026-001','Stacy','Staff','Active')")
    s2 = run(svc, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('STF-2026-002','Sam','Staff','Active')")
    return {"user_id": a}, {"user_id": s1}, {"user_id": s2}


def test_seed_fills_empty_tables_once_and_never_overwrites(svc, people):
    admin, staff, _ = people
    guides = [(False, "Basics", ["one", "two"]), (True, "Admin stuff", ["secret step"])]
    faqs = [(False, "Q1?", "A1"), (True, "Q2?", "A2")]
    hs.seed_defaults(staff, guides, faqs, [("CPU", "i3")], [("Python", "3.11")])
    hs.seed_defaults(admin, [(False, "Other", ["x"])], [(False, "Q?", "A")], [("RAM", "8")], [("DB", "MySQL")])     # second call changes nothing
    assert [g["title"] for g in hs.list_guides(admin)] == ["Basics", "Admin stuff"]
    assert [r["component"] for r in hs.list_requirements(admin, "Hardware")] == ["CPU"]


def test_staff_never_receive_admin_only_content(svc, people):
    admin, staff, _ = people
    hs.seed_defaults(admin, [(False, "Basics", ["one"]), (True, "Admin stuff", ["s"])], [(False, "Q1?", "A1"), (True, "Q2?", "A2")], [], [])
    assert [g["title"] for g in hs.list_guides(staff)] == ["Basics"]
    assert [f["question"] for f in hs.list_faqs(staff)] == ["Q1?"]
    assert len(hs.list_guides(admin)) == 2 and len(hs.list_faqs(admin)) == 2


def test_only_admin_edits_content(svc, people):
    admin, staff, _ = people
    for call in (lambda: hs.save_guide(staff, None, "T", ["s"], False, 0), lambda: hs.delete_guide(staff, 1),
                 lambda: hs.save_faq(staff, None, "Q", "A", False, 0), lambda: hs.delete_faq(staff, 1),
                 lambda: hs.save_requirement(staff, None, "Hardware", "c", "s", 0), lambda: hs.delete_requirement(staff, 1),
                 lambda: hs.reply_ticket(staff, 1, "r")):
        with pytest.raises(PermissionDenied):
            call()


def test_guide_faq_requirement_lifecycle_with_text_ids(svc, people):
    admin, _, _ = people
    hs.save_guide(admin, None, "  How to scan ", ["step 1", "", "step 2"], True, "3")
    g = hs.list_guides(admin)[0]
    assert g["title"] == "How to scan" and g["steps"] == "step 1|||step 2" and g["is_admin_only"] == 1 and g["display_order"] == 3
    hs.save_guide(admin, str(g["id"]), "Renamed", ["only"], False, 0)                     # id arrives as text from a widget
    assert hs.list_guides(admin)[0]["title"] == "Renamed"
    hs.delete_guide(admin, str(g["id"]))
    assert hs.list_guides(admin) == []
    with pytest.raises(NotFound):
        hs.delete_guide(admin, 999)
    hs.save_faq(admin, None, "Why?", "Because", False, 0)
    f = hs.list_faqs(admin)[0]
    hs.save_faq(admin, f["id"], "Why not?", "Because", False, 1)
    assert hs.list_faqs(admin)[0]["question"] == "Why not?"
    hs.save_requirement(admin, None, "Software", "Python", "3.11", 0)
    r = hs.list_requirements(admin, "Software")[0]
    hs.save_requirement(admin, r["id"], "Hardware", "Python", "3.12", 0)
    assert hs.list_requirements(admin, "Software") == [] and hs.list_requirements(admin, "Hardware")[0]["specification"] == "3.12"


@pytest.mark.parametrize("call", [
    lambda a: hs.save_guide(a, None, "", ["s"], False, 0), lambda a: hs.save_guide(a, None, "T", [], False, 0),
    lambda a: hs.save_guide(a, None, "T", ["a|||b"], False, 0), lambda a: hs.save_guide(a, None, "T", ["s"], False, "abc"),
    lambda a: hs.save_faq(a, None, "", "A", False, 0), lambda a: hs.save_faq(a, None, "Q", "", False, 0),
    lambda a: hs.save_requirement(a, None, "Bogus", "c", "s", 0), lambda a: hs.save_requirement(a, None, "Hardware", "", "s", 0),
    lambda a: hs.list_requirements(a, "Bogus"),
])
def test_bad_input_is_a_clear_message(svc, people, call):
    with pytest.raises(ValidationError):
        call(people[0])


def test_tickets_staff_see_only_their_own_and_only_admin_replies(svc, people):
    admin, s1, s2 = people
    t1 = hs.submit_ticket(s1, " Scanner broken ", "It does not scan")["ticket_id"]
    hs.submit_ticket(s2, "Other", "Other message")
    hs.submit_ticket(admin, "Admin note", "Admin message")
    assert [t["subject"] for t in hs.list_tickets(s1)] == ["Scanner broken"]
    assert len(hs.list_tickets(s2)) == 1 and len(hs.list_tickets(admin)) == 3
    assert {t["status"] for t in hs.list_tickets(admin)} == {"Open"}
    hs.reply_ticket(admin, str(t1), "Try another camera")
    mine = hs.list_tickets(s1)[0]
    assert mine["status"] == "Resolved" and mine["admin_reply"] == "Try another camera"
    with pytest.raises(NotFound):
        hs.reply_ticket(admin, 9999, "x")
    with pytest.raises(ValidationError):
        hs.submit_ticket(s1, "", "m")
    with pytest.raises(ValidationError):
        hs.submit_ticket(s1, "s", "")


def test_archived_or_unknown_users_are_refused(svc, people):
    admin, staff, _ = people
    run(svc, "UPDATE `user` SET status='Inactive' WHERE user_id=%s", (staff["user_id"],))
    with pytest.raises(PermissionDenied):
        hs.list_guides(staff)
    with pytest.raises(PermissionDenied):
        hs.submit_ticket({"user_id": 99999}, "s", "m")
