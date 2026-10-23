"""Check the guided tour's role boundaries and sample records before DB writes."""
from scripts.add_mock_data import PROJECTS, TOOLS, WORKERS
from services import validators as v
from ui.tour import steps_for


def test_tour_covers_every_visible_section_without_admin_pages_for_staff():
    staff = steps_for("Staff")
    admin = steps_for("Admin")
    assert {s.page for s in staff} == {"Dashboard", "Project Management", "Inventory",
                                        "Issuance & Retrieval", "Tracking & Accountability", "Help", "Profile"}
    assert {"Reports", "Maintenance", "Role Management"} <= {s.page for s in admin}
    assert [s.page for s in staff] == sorted((s.page for s in staff),
                                            key=lambda page: ["Dashboard", "Project Management", "Inventory",
                                                              "Issuance & Retrieval", "Tracking & Accountability",
                                                              "Help", "Profile"].index(page))
    assert all(s.title and s.detail for s in admin)


def test_mock_catalog_has_valid_unique_tags_and_usable_project_links():
    names = {row[0] for row in TOOLS}
    assert len(names) == len(TOOLS) and len({row[0] for row in PROJECTS}) == len(PROJECTS)
    assert len({row[9] for row in TOOLS if row[9]}) == sum(bool(row[9]) for row in TOOLS)
    assert all(v.clean_person_name(worker) == worker for worker in WORKERS)
    for name, category, supplier, location, kind, unit, price, stock, minimum, tag in TOOLS:
        assert v.clean_named_label(name, field="Name") == name
        assert v.parse_quantity(stock, whole=kind == "Equipment") > 0
        assert v.parse_quantity(minimum, whole=kind == "Equipment") >= 0
        assert tag is None or v.validate_tag_id(tag) == tag
    for name, client, site, head, start, end, worker, needs in PROJECTS:
        assert start <= end and 0 <= worker < len(WORKERS)
        assert v.clean_person_name(head) == head
        assert all(tool in names and v.parse_quantity(qty) > 0 for tool, qty in needs)
