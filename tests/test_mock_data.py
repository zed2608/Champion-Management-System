"""Check sample records before DB writes."""
from scripts.add_mock_data import PROJECTS, TOOLS, WORKERS
from services import validators as v


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
