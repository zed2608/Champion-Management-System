"""Database error types and user-safe messages.

[UNHAPPY-PATH] Views must never show raw driver text ("2005 (HY000): Unknown MySQL server host ...").
Catch ``DatabaseUnavailable`` / ``TransactionFailed`` and show ``user_message(exc)`` instead.
"""
from mysql.connector import errors as mysql_errors

# MySQL error numbers we treat specially.
ER_LOCK_WAIT_TIMEOUT = 1205
ER_LOCK_DEADLOCK = 1213
RETRYABLE_ERRNOS = frozenset({ER_LOCK_WAIT_TIMEOUT, ER_LOCK_DEADLOCK})

# Client/server "connection is gone" errors (CR_* and ER_* codes).
CONNECTION_ERRNOS = frozenset({
    2002,  # CR_CONNECTION_ERROR
    2003,  # CR_CONN_HOST_ERROR
    2005,  # CR_UNKNOWN_HOST (the DNS failure seen on this project)
    2006,  # CR_SERVER_GONE_ERROR
    2013,  # CR_SERVER_LOST
    2055,  # CR_SERVER_LOST_EXTENDED
    1053,  # ER_SERVER_SHUTDOWN
    1927,  # ER_CONNECTION_KILLED
})


class DatabaseUnavailable(Exception):
    """The server cannot be reached (or the pool cannot give out a connection)."""


class DatabaseOffline(DatabaseUnavailable):
    """Server unreachable: DNS, network, server down, bad credentials."""


class PoolExhausted(DatabaseUnavailable):
    """All pooled connections stayed busy for the whole wait window (usually a leak)."""


class TransactionFailed(Exception):
    """A multi-statement write was rolled back; nothing was saved."""


def is_connection_error(exc: BaseException) -> bool:
    if isinstance(exc, DatabaseUnavailable):
        return True
    if isinstance(exc, (mysql_errors.InterfaceError, mysql_errors.OperationalError)):
        errno = getattr(exc, "errno", None)
        return errno is None or errno in CONNECTION_ERRNOS or isinstance(exc, mysql_errors.InterfaceError)
    return getattr(exc, "errno", None) in CONNECTION_ERRNOS


def is_retryable(exc: BaseException) -> bool:
    """Deadlock (1213) or lock wait timeout (1205): safe to rerun the whole transaction once."""
    return getattr(exc, "errno", None) in RETRYABLE_ERRNOS


def user_message(exc: BaseException) -> str:
    """Plain-language text that is safe to show in a dialog or toast."""
    if isinstance(exc, PoolExhausted):
        return "The system is busy. Please wait a moment and try again."
    if is_connection_error(exc):
        return "Connection lost. Nothing was saved. Please retry."
    if is_retryable(exc):
        return "Another terminal is updating the same item. Nothing was saved. Please retry."
    if isinstance(exc, TransactionFailed):
        return "The action could not be completed and nothing was saved."
    return "Something went wrong and nothing was saved. If it keeps happening, contact an administrator."
