"""Print the WCAG contrast ratio of every text/background pair in ui/theme.py, for light and dark mode, and list the failures.

    python scripts/check_contrast.py          (exit code 1 if any pair is below 4.5:1)

Target: 4.5:1 minimum (WCAG AA for normal text), 7:1 where practical (AAA).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ui import theme as T      # noqa: E402


def _lin(c):
    c /= 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hexcolor):
    h = hexcolor.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def ratio(fg, bg):
    a, b = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def value(name, mode):
    return T.DARK.get(name, getattr(T, name)) if mode == "dark" else getattr(T, name)


def report():
    rows, failures = [], []
    for mode in ("light", "dark"):
        for fg, bg in T.TEXT_PAIRS:
            r = ratio(value(fg, mode), value(bg, mode))
            grade = "AAA" if r >= 7 else "AA" if r >= 4.5 else "FAIL"
            rows.append((mode, fg, bg, r, grade))
            if grade == "FAIL":
                failures.append((mode, fg, bg, r))
    return rows, failures


def main():
    rows, failures = report()
    for mode, fg, bg, r, grade in rows:
        print(f"{mode:5}  {fg:16} on {bg:16} {r:5.2f}:1  {grade}")
    print()
    print(f"{len(rows)} pairs, {sum(1 for r in rows if r[4] == 'AAA')} reach 7:1, {len(failures)} below 4.5:1")
    for mode, fg, bg, r in failures:
        print(f"  FAIL {mode}: {fg} on {bg} = {r:.2f}:1")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
