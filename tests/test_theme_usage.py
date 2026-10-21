"""Screens must take colours and fonts from ui/theme.py, never write them directly. Static check over every screen file.

EXCEPTIONS lists (file, text) pairs that are allowed to contain a literal on purpose. It is empty: if you need one, add it here with a reason."""
import ast
import re
from pathlib import Path

from ui import theme as T

ROOT = Path(__file__).resolve().parent.parent
SCREENS = sorted((ROOT / "views").glob("*.py")) + [ROOT / "dashboard.py", ROOT / "main.py"]
EXCEPTIONS = set()       # {(file name, literal)}

HEX = re.compile(r"""(["'])#[0-9A-Fa-f]{3}(?:[0-9A-Fa-f]{3})?\1""")
FONT_TUPLE = re.compile(r"""font\s*=\s*\(\s*["']""")            # font=("Inter", 12) instead of T.font(12)


def sources():
    for f in SCREENS:
        yield f, f.read_text(encoding="utf-8")


def test_the_list_of_screens_is_not_empty():
    assert len(SCREENS) >= 12


def test_no_screen_writes_a_hex_colour_directly():
    bad = [(f.name, m.group(0)) for f, text in sources() for m in HEX.finditer(text) if (f.name, m.group(0)) not in EXCEPTIONS]
    assert not bad, f"use ui.theme colours instead of literals: {bad[:10]}"


def test_no_screen_names_a_font_family_or_a_literal_font_tuple():
    bad = [(f.name, text[:m.start()].count("\n") + 1) for f, text in sources() for m in FONT_TUPLE.finditer(text)]
    assert not bad, f"use T.font(size, weight) / T.mono(...): {bad[:10]}"
    for f, text in sources():
        assert '"Inter"' not in text and "'Inter'" not in text, f.name


def test_every_font_size_is_on_the_scale_and_every_token_exists():
    for f, text in sources():
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) \
                    and node.func.value.id == "T" and node.func.attr in ("font", "mono"):
                if node.args and isinstance(node.args[0], ast.Constant):
                    assert node.args[0].value in T.SIZES, (f.name, node.lineno, node.args[0].value)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "T":
                assert hasattr(T, node.attr), f"{f.name}:{node.lineno} uses a token that does not exist: T.{node.attr}"


def test_the_checker_catches_a_violation():
    assert HEX.search('fg_color="#1E4528"') and FONT_TUPLE.search('font=("Inter", 12, "bold")') and not FONT_TUPLE.search("font=T.font(12)")
