"""Inactivity auto-logout settings.

Default: log out after 15 minutes without a click, key press or mouse move, with a 30-second warning first. Both can be changed per
computer in ``.env`` (CHAMPION_IDLE_MINUTES, CHAMPION_IDLE_WARNING_SECONDS); out-of-range or non-numeric values fall back to the
defaults, so a typo can neither disable the timeout nor log people out every few seconds.
"""
import os

DEFAULT_IDLE_MINUTES = 15
DEFAULT_WARNING_SECONDS = 30
IDLE_MINUTES_RANGE = (1, 240)
WARNING_SECONDS_RANGE = (5, 300)


def _read(name, default, low, high):
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        n = int(str(raw).strip())
    except ValueError:
        return default
    return n if low <= n <= high else default


def idle_minutes():
    return _read("CHAMPION_IDLE_MINUTES", DEFAULT_IDLE_MINUTES, *IDLE_MINUTES_RANGE)


def warning_seconds():
    return _read("CHAMPION_IDLE_WARNING_SECONDS", DEFAULT_WARNING_SECONDS, *WARNING_SECONDS_RANGE)
