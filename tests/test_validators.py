from decimal import Decimal

import pytest

from services import validators as v


# ---- scans ----------------------------------------------------------------------------------------------------
def test_scan_tool_sticker_payload():
    s = v.parse_scan("Tag ID: cal-001\nPID: 12\nName: Digital Caliper\nLocation: A1\nStatus: Good")
    assert (s.kind, s.value) == ("tool", "CAL-001")


def test_scan_worker_badge_plain_and_prefixed():
    assert v.parse_scan("WKR-2026-001") == v.Scan("worker", "WKR-2026-001")
    assert v.parse_scan("Employee ID: stf-2026-014\nName: x") == v.Scan("worker", "STF-2026-014")


def test_scan_worker_pattern_wins_over_tag_pattern():
    # WKR-2026-001 also fits the tag regex; it must be classified as a worker
    assert v.parse_scan("WKR-2026-001").kind == "worker"


def test_scan_garbage_and_control_characters():
    assert v.parse_scan("").kind == "unknown"
    assert v.parse_scan(None).kind == "unknown"
    assert v.parse_scan("\x00\x01\x02").kind == "unknown"
    assert v.parse_scan("x" * 500).kind == "unknown"
    assert v.parse_scan(b"Tag ID: ABC-123").value == "ABC-123"


@pytest.mark.parametrize("tag", ["AB", "-ABC", "ab c", "A" * 33, "AB$1", ""])
def test_tag_id_rejects(tag):
    with pytest.raises(v.ValidationError):
        v.validate_tag_id(tag)


def test_tag_id_normalises():
    assert v.validate_tag_id("  cal-001 ") == "CAL-001"


@pytest.mark.parametrize("eid", ["ADM-2026-001", "stf-2026-1234", "WKR-2026-99999"])
def test_employee_id_ok(eid):
    assert v.validate_employee_id(eid) == eid.upper()


@pytest.mark.parametrize("eid", ["ADM-26-001", "XYZ-2026-001", "WKR-2026-01", "WKR 2026 001", "WKR-2026-001; DROP TABLE x"])
def test_employee_id_rejects(eid):
    with pytest.raises(v.ValidationError):
        v.validate_employee_id(eid)


# ---- quantities / prices --------------------------------------------------------------------------------------
def test_quantity_rules():
    assert v.parse_quantity("2") == Decimal("2.00")
    assert v.parse_quantity("2.5") == Decimal("2.50")
    assert v.parse_quantity("100000") == Decimal("100000.00")
    for bad in ["0", "-1", "abc", "", "1.234", "100000.01", "NaN", "Infinity", None]:
        with pytest.raises(v.ValidationError):
            v.parse_quantity(bad)


def test_equipment_must_be_whole():
    assert v.parse_quantity("3", whole=True) == Decimal("3.00")
    with pytest.raises(v.ValidationError):
        v.parse_quantity("2.5", whole=True)


def test_price_rules():
    assert v.parse_price("1,250.50") == Decimal("1250.50")
    assert v.parse_price("0") == Decimal("0.00")
    for bad in ["-0.01", "x", "1.005", "100000000"]:
        with pytest.raises(v.ValidationError):
            v.parse_price(bad)


# ---- text / search -------------------------------------------------------------------------------------------
def test_clean_text_strips_control_chars_and_caps():
    assert v.clean_text("  hello\x00 \x07world  ") == "hello world"
    with pytest.raises(v.ValidationError):
        v.clean_text("   ")
    with pytest.raises(v.ValidationError):
        v.clean_text("x" * 101, max_len=100)
    assert v.clean_text("", required=False) == ""


def test_multiline_keeps_newlines():
    assert v.clean_text("a\nb", max_len=1000, multiline=True) == "a\nb"


def test_names_reject_numbers_but_tool_and_project_names_keep_sizes_and_phases():
    assert v.clean_person_name("María D. Reyes-Jr.") == "María D. Reyes-Jr."
    for value in ("123", "John 2", "Jane; DROP TABLE user"):
        with pytest.raises(v.ValidationError):
            v.clean_person_name(value)
    assert v.clean_named_label("10 mm drill", field="Product Name") == "10 mm drill"
    assert v.clean_named_label("Phase 2", field="Project Name") == "Phase 2"
    with pytest.raises(v.ValidationError):
        v.clean_named_label("123", field="Project Name")


def test_search_is_capped_and_escaped():
    assert len(v.clean_search("a" * 500)) == 64
    assert v.escape_like("50%_off\\") == "50\\%\\_off\\\\"
    assert v.like_pattern("100%") == "%100\\%%"


# ---- passwords -----------------------------------------------------------------------------------------------
def test_password_not_stripped_and_72_byte_limit():
    pw = "Abcdef1! "                               # trailing space is part of the secret
    assert v.validate_new_password(pw) == pw
    with pytest.raises(v.ValidationError):
        v.validate_new_password("Aa1!" + "x" * 69)   # 73 bytes
    with pytest.raises(v.ValidationError):
        v.validate_new_password("Aa1!" + "é" * 35)   # 4 + 70 bytes = 74


def test_password_strength_messages():
    with pytest.raises(v.ValidationError) as e:
        v.validate_new_password("abc")
    assert "8 characters" in str(e.value) and "uppercase" in str(e.value)


def test_hash_and_verify_roundtrip_and_safe_failures():
    h = v.hash_password("Str0ng!pass")
    assert v.verify_password("Str0ng!pass", h)
    assert not v.verify_password("Str0ng!pass ", h)          # no stripping
    assert not v.verify_password("x", None)                   # Worker: NULL hash
    assert not v.verify_password("x" * 100, h)                # > 72 bytes: no ValueError
    assert not v.verify_password("x", "not-a-bcrypt-hash")


def test_date_helpers():
    from datetime import date
    assert v.parse_iso_date("2026-02-28") == date(2026, 2, 28)
    with pytest.raises(v.ValidationError):
        v.parse_iso_date("28/02/2026")
    with pytest.raises(v.ValidationError):
        v.validate_date_range(date(2026, 3, 1), date(2026, 2, 1))
    with pytest.raises(v.ValidationError, match="both"):
        v.validate_date_range(date(2026, 3, 1), None)
    v.validate_date_range(date(2026, 2, 1), date(2026, 2, 1))   # equal is fine


def test_email():
    assert v.validate_email("A@Example.com") == "a@example.com"
    assert v.validate_email("", required=False) is None
    with pytest.raises(v.ValidationError):
        v.validate_email("nope")
