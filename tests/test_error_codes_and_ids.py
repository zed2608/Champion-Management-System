"""Unexpected errors are diagnosable without a terminal (code + log file), and text ids from screens are understood."""
import re

import pytest

from services import errors
from services.errors import error_code, friendly_message, short_reason
from services.security import _normalise_ids
from services.validators import ValidationError, parse_id


@pytest.mark.parametrize("value,expected", [(1, 1), ("1", 1), (" 42 ", 42), ("007", 7)])
def test_parse_id_accepts_numbers_and_their_text(value, expected):
    assert parse_id(value) == expected


@pytest.mark.parametrize("value", ["", "abc", "1.5", "-3", "0", 0, -1, None, True, 1.0, "9" * 30, "1; DROP TABLE tool"])
def test_parse_id_rejects_everything_else(value):
    with pytest.raises(ValidationError):
        parse_id(value)


def test_only_database_id_parameters_are_converted():
    def fn(actor, tool_id, tag_id=None, employee_id=None): ...
    import inspect
    args, kwargs = _normalise_ids(inspect.signature(fn), {}, ("5",), {"tag_id": "CAL-001", "employee_id": "ADM-2026-001"})
    assert args == (5, "CAL-001", "ADM-2026-001") and kwargs == {}      # tag / employee ids stay text


def test_unexpected_error_shows_code_and_reason_and_logs_the_traceback(tmp_path, monkeypatch):
    errors.configure_logging(tmp_path)
    try:
        {}["1"]
    except KeyError as exc:
        text = friendly_message(exc)
        code = error_code(exc)
    assert re.match(r"^ERR-[A-Z]{2,3}-\d{4}$", code)
    assert f"({code})" in text and "KeyError" in text and "Nothing was saved" in text
    for h in errors.get_logger().handlers:
        h.flush()
    log = (tmp_path / "app.log").read_text(encoding="utf-8")
    assert code in log and "Traceback" in log and "KeyError" in log      # same code next to the traceback


def test_the_dialog_never_carries_sql_or_driver_text():
    import mysql.connector
    exc = mysql.connector.errors.ProgrammingError(msg="1054 (42S22): Unknown column 'x' in 'field list' SELECT secret FROM tool", errno=1054)
    shown = friendly_message(exc)
    assert "SELECT" not in shown and "secret" not in shown and "1054" in shown
    assert "SELECT" not in short_reason(RuntimeError("SELECT * FROM user WHERE pw = 'x'"))


def test_same_kind_of_error_gets_the_same_code():
    def boom():
        raise KeyError("a")
    codes = set()
    for _ in range(2):
        try:
            boom()
        except KeyError as exc:
            codes.add(error_code(exc))
    assert len(codes) == 1
