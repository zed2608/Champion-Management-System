"""Service-layer errors and the ONE place that turns any exception into text a person can read.

[UNHAPPY-PATH] Views must show ``friendly_message(exc)`` and never ``str(exc)`` of a driver error: raw text such as
"1451 (23000): Cannot delete or update a parent row ..." or "CHAMPION: ..." means nothing to a storekeeper and can leak
host, table and column names.
"""
import re

from mysql.connector import errors as mysql_errors

from db import user_message
from db.errors import is_connection_error
from services.validators import ValidationError


class ServiceError(Exception):
    """Business-rule failure. The message is written for the user and is always safe to show."""


class PermissionDenied(ServiceError):
    pass


class NotFound(ServiceError):
    pass


class Conflict(ServiceError):
    """The request is valid but the current state of the data does not allow it (stale screen, limit reached, ...)."""


_CHAMPION = re.compile(r"CHAMPION:\s*(.+)$", re.S)


def friendly_message(exc: BaseException) -> str:
    """User-safe text for any exception raised below the UI."""
    if isinstance(exc, (ServiceError, ValidationError)):
        return str(exc)
    if isinstance(exc, mysql_errors.Error):
        text = str(getattr(exc, "msg", "") or exc)
        m = _CHAMPION.search(text)
        if m:                                             # our own trigger rule: "CHAMPION: Dates and workers are locked ..."
            return m.group(1).strip().rstrip(".") + "."
        errno = getattr(exc, "errno", None)
        if errno == 1062:
            return "That value already exists."
        if errno in (1451, 1452):
            return "This record is linked to other records, so that change is not allowed."
        if errno in (3819, 4025, 1264, 1366, 1406):       # CHECK violated / out of range / bad or too-long value
            return "A value is outside the allowed range."
    # Anything else is a bug or an unexpected failure: the USER gets the safe sentence, the DEVELOPER gets the real traceback
    # on the console (otherwise "Something went wrong" would hide the cause forever).
    if not is_connection_error(exc):
        import sys
        import traceback
        print("UNEXPECTED ERROR (shown to the user as a generic message):", file=sys.stderr)
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
    return user_message(exc)
