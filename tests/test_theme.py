"""The design tokens: every text/background pair is readable (4.5:1) in light and dark mode, and fonts only come from the scale."""
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from ui import theme as T       # noqa: E402
from ui import components as C   # noqa: E402
import check_contrast as cc      # noqa: E402


def test_every_text_pair_reaches_4_5_to_1_in_both_modes():
    rows, failures = cc.report()
    assert len(rows) >= 60
    assert not failures, failures


def test_the_contrast_script_runs_and_exits_zero():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_contrast.py")], capture_output=True, text=True)
    assert r.returncode == 0 and "below 4.5:1" in r.stdout


def test_the_checker_really_detects_a_bad_pair():
    assert cc.ratio("#AAAAAA", "#FFFFFF") < 4.5 and cc.ratio("#1A1A1A", "#FFFFFF") > 15


def test_every_colour_is_a_hex_string_and_every_dark_name_exists():
    for name in dir(T):
        if name.isupper() and isinstance(getattr(T, name), str) and name not in ("FAMILY", "MONO"):
            assert re.fullmatch(r"#[0-9A-F]{6}", getattr(T, name)), name
    for name, value in T.DARK.items():
        assert re.fullmatch(r"#[0-9A-F]{6}", value), name
    for fg, bg in T.TEXT_PAIRS:
        assert hasattr(T, fg) and hasattr(T, bg)


def test_fonts_come_from_the_scale_only():
    assert T.font(12, "bold") == ("Segoe UI", 12, "bold") and T.mono(14)[0] == "Consolas"
    for bad in (10, 11, 13, 15, 18):
        with pytest.raises(ValueError):
            T.font(bad)
    assert T.SIZES == (12, 14, 16, 20, 28, 40)
    assert (T.ANIM_FAST, T.ANIM_NORMAL, T.ANIM_SLOW) == (120, 200, 320)
    assert all(v % 4 == 0 for v in T.SPACE.values())


@pytest.mark.parametrize("label,expected", [
    ("+ Add Project", "accent"), ("+ Add New Item", "accent"),
    ("📤 Issue Tools", "accent"), ("+ Register New User", "accent"),
    ("+ Add Guide", "accent"), ("⎙ Export PDF", "accent"),
    ("Confirm Retrieval & Restock", "accent"), ("📥 Retrieve Tools", "info"),
    ("Cancel", "danger"), ("Remove", "danger"), ("Delete", "danger"),
    ("Clear", "danger"), ("Apply", "primary"), ("Search", "secondary"),
])
def test_action_labels_choose_consistent_colors(label, expected):
    assert C.action_kind(label, "secondary" if label == "Search" else "primary") == expected
