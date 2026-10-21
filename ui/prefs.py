"""Small per-computer settings (intro already seen, colour mode) in ``ui_prefs.json`` next to the program. The file is git-ignored.

Nothing here is data the business depends on: if the file is missing, unreadable or read-only, the defaults are used and the program carries on.
"""
import json
import os
import sys
import threading
from pathlib import Path

_lock = threading.Lock()


def path():
    override = os.getenv("CHAMPION_UI_PREFS")
    if override:
        return Path(override)
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    return base / "ui_prefs.json"


def load():
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def get(key, default=None):
    return load().get(key, default)


def set(key, value):          # noqa: A001  (same name as the builtin on purpose: prefs.set("intro_seen", True))
    """Store one setting. Returns False (and changes nothing) when the file cannot be written."""
    with _lock:
        data = load()
        data[key] = value
        target = path()
        tmp = target.with_name(target.name + ".part")
        try:
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(tmp, target)
            return True
        except OSError:
            try:
                tmp.unlink()
            except OSError:
                pass
            return False
