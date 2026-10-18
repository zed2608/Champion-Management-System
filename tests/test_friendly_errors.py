"""[UNHAPPY-PATH] Every rule the database can refuse must reach the user as a plain sentence."""
import re
from pathlib import Path

import mysql.connector
import pytest

from services.errors import Conflict, NotFound, PermissionDenied, friendly_message
from services.validators import ValidationError

TRIGGERS = (Path(__file__).resolve().parent.parent / "db" / "triggers.sql").read_text(encoding="utf-8")
MESSAGES = re.findall(r"MESSAGE_TEXT = '(CHAMPION: [^']+)'", TRIGGERS)


def trigger_error(text):
    return mysql.connector.errors.DatabaseError(msg=text, errno=1644, sqlstate="45000")


def test_every_trigger_message_is_translated_to_a_plain_sentence():
    assert len(MESSAGES) >= 10, "the trigger messages were not found"
    for raw in MESSAGES:
        out = friendly_message(trigger_error(raw))
        assert "CHAMPION" not in out and "1644" not in out and "45000" not in out
        assert out[0].isupper() and out.endswith("."), out
        assert out.rstrip(".") == raw.replace("CHAMPION: ", "").rstrip("."), (raw, out)


def test_the_cases_users_actually_hit():
    locked = friendly_message(trigger_error("CHAMPION: Dates and workers are locked once a project is Ongoing or Completed, or has issued tools."))
    assert locked == "Dates and workers are locked once a project is Ongoing or Completed, or has issued tools."
    assert "archived" in friendly_message(trigger_error("CHAMPION: Only Completed, Declined or Cancelled projects can be archived."))


def test_driver_codes_are_translated_and_never_leak_internals():
    cases = {
        1451: "linked", 1452: "linked", 1062: "already exists", 3819: "outside the allowed range", 4025: "outside the allowed range",
    }
    for errno, expect in cases.items():
        msg = friendly_message(mysql.connector.errors.IntegrityError(msg=f"{errno} (23000): Cannot delete or update a parent row: "
                                                                          "a foreign key constraint fails (`champion_db`.`transaction`)", errno=errno))
        assert expect in msg and "champion_db" not in msg and "constraint" not in msg and str(errno) not in msg
    lost = friendly_message(mysql.connector.errors.OperationalError(msg="Lost connection to MySQL server at '10.0.0.5:3306'", errno=2013))
    assert "Connection lost" in lost and "10.0.0.5" not in lost
    dead_lock = friendly_message(mysql.connector.errors.DatabaseError(msg="Deadlock found when trying to get lock", errno=1213))
    assert "Another terminal" in dead_lock and "Deadlock" not in dead_lock


def test_our_own_errors_pass_through_and_unknown_ones_are_generic():
    for exc in (Conflict("Project is Pending."), NotFound("Project not found."), PermissionDenied("No."), ValidationError("Bad.")):
        assert friendly_message(exc) == str(exc)
    generic = friendly_message(KeyError("secret_column"))
    assert "secret_column" not in generic and "nothing was saved" in generic.lower()
