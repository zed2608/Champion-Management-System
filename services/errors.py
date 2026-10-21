"""Service-layer errors and the ONE place that turns any exception into text a person can read.

[UNHAPPY-PATH] Views must show ``friendly_message(exc)`` and never ``str(exc)`` of a driver error: raw text such as
"1451 (23000): Cannot delete or update a parent row ..." or "CHAMPION: ..." means nothing to a storekeeper and can leak
host, table and column names.

Anything UNEXPECTED (a bug, an unknown database error) is handled like this, so it can be diagnosed without a terminal:
  * the full traceback is written to ``logs/app.log`` (rotating file) next to a short code such as ``ERR-INV-0417``;
  * the dialog shows that same code and one short, safe line ("KeyError: '1'" or "database error 1054"), never SQL or driver text.
The code is stable for the same kind of error in the same function (it hashes the exception type and the function, not the line number).
"""
import logging
import os
import re
import sys
import zlib
from logging.handlers import RotatingFileHandler
from pathlib import Path

from mysql.connector import errors as mysql_errors

from db import user_message
from db.errors import is_connection_error, is_retryable
from services.validators import ValidationError

PROJECT_ROOT = (Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent)
LOG_NAME = "app.log"
_logger = None


class ServiceError(Exception):
    """Business-rule failure. The message is written for the user and is always safe to show."""


class PermissionDenied(ServiceError):
    pass


class NotFound(ServiceError):
    pass


class Conflict(ServiceError):
    """The request is valid but the current state of the data does not allow it (stale screen, limit reached, ...)."""


# ---- logging ------------------------------------------------------------------------------------------------------------
def log_dir() -> Path:
    return Path(os.environ.get("CHAMPION_LOG_DIR") or PROJECT_ROOT / "logs")


def configure_logging(directory=None):
    """(Re)attach the rotating file handler. Idempotent; tests point it at a temporary folder."""
    global _logger
    path = Path(directory) if directory else log_dir()
    path.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("champion")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for h in list(logger.handlers):
        logger.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass
    fh = RotatingFileHandler(path / LOG_NAME, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)
    sh = logging.StreamHandler(sys.stderr)                # developers still see it on the console
    sh.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(sh)
    _logger = logger
    return logger


def get_logger():
    return _logger or configure_logging()


# ---- error codes ----------------------------------------------------------------------------------------------------------
_AREAS = {"inventory_service": "INV", "issuance_service": "ISS", "maintenance_service": "MNT", "project_service": "PRJ",
          "user_service": "USR", "auth_service": "AUT", "report_service": "RPT", "dashboard_service": "DSH", "help_service": "HLP",
          "backup_service": "BAK", "stock_ledger": "STK", "tool_cache": "CCH", "validators": "VAL", "security": "SEC",
          "pool": "DB", "scanner": "SCN", "migrate": "MIG"}


def _origin(exc):
    """(area code, function name) of the innermost frame that belongs to THIS project (not the Python or driver libraries)."""
    area, func = "GEN", "?"
    tb = exc.__traceback__
    while tb is not None:
        f = Path(tb.tb_frame.f_code.co_filename)
        try:
            inside = PROJECT_ROOT in f.resolve().parents and ".venv" not in str(f) and "site-packages" not in str(f)
        except OSError:
            inside = False
        if inside:
            stem = f.stem
            area = _AREAS.get(stem, "UI" if f.parent.name == "views" else "GEN")
            func = tb.tb_frame.f_code.co_name
        tb = tb.tb_next
    return area, func


def error_code(exc) -> str:
    area, func = _origin(exc)
    digits = zlib.crc32(f"{type(exc).__name__}|{area}|{func}".encode()) % 10000
    return f"ERR-{area}-{digits:04d}"


_SQLISH = re.compile(r"\b(select|insert|update|delete|from|where|join|values|set)\b|`|%s", re.I)


def short_reason(exc) -> str:
    """One short line that is safe to show: no SQL, no host names, no driver text."""
    if isinstance(exc, mysql_errors.Error):
        return f"database error {getattr(exc, 'errno', None) or 'unknown'}"
    name = type(exc).__name__
    msg = " ".join(str(exc).split())
    if _SQLISH.search(msg):
        msg = ""
    msg = msg[:80]
    return f"{name}: {msg}" if msg else name


_CHAMPION = re.compile(r"CHAMPION:\s*(.+)$", re.S)


def _file_problem(exc: OSError):
    """Plain words for a file that could not be written (full disk, read-only or forbidden folder, folder gone), else None."""
    import errno
    code = getattr(exc, "errno", None)
    if code == errno.ENOSPC or getattr(exc, "winerror", None) in (39, 112):
        return "The disk is full, so the file could not be saved. Free some space and try again. Nothing was saved."
    if isinstance(exc, PermissionError) or code in (errno.EACCES, errno.EROFS, errno.EPERM):
        return "This folder does not allow saving files (it may be read-only or protected). Choose another folder and try again. Nothing was saved."
    if isinstance(exc, FileNotFoundError) or code == errno.ENOENT:
        return "The folder for this file could not be found. Choose another folder and try again. Nothing was saved."
    return None


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
    if is_connection_error(exc) or is_retryable(exc):
        get_logger().warning("%s: %s", type(exc).__name__, short_reason(exc))
        return user_message(exc)
    if isinstance(exc, OSError) and not isinstance(exc, (ConnectionError, TimeoutError)):
        text = _file_problem(exc)
        if text:
            get_logger().warning("%s: %s", type(exc).__name__, short_reason(exc))
            return text
    # Unexpected: log the full traceback under a code, show the code and one safe line.
    code = error_code(exc)
    get_logger().error("%s %s", code, short_reason(exc), exc_info=(type(exc), exc, exc.__traceback__))
    return (f"({code}) {short_reason(exc)}\n\nNothing was saved. If it keeps happening, send the file logs\\{LOG_NAME} "
            f"and this code to an administrator.")
