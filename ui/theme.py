"""Design tokens: the ONE place for colours, fonts, sizes, spacing, radii and animation timings.

Screens never write a hex colour or a font family; they use these names (a test enforces it).  Keep the brand: dark green + yellow accent.

Colours
    Every name below is a LIGHT-mode value, a plain string, so it works everywhere (CustomTkinter, PIL receipts, Matplotlib).
    ``DARK`` holds the dark-mode value for the same names; ``ui.mode`` swaps them (see step "dark/light switch").
    Text colours are chosen so every pair in ``TEXT_PAIRS`` reaches at least 4.5:1 (scripts/check_contrast.py prints the ratios).
Fonts
    One family (Segoe UI) for everything, Consolas for IDs and numbers.  Sizes come from a fixed scale: 12 / 14 / 16 / 20 / 28 / 40.
Spacing / radius / motion
    A 4 px grid, three radii, three animation timings (120 / 200 / 320 ms).
"""

# ---------------------------------------------------------------- colours (light mode)
# surfaces and lines
BG = "#F4F6F8"                  # page background
SURFACE = "#FFFFFF"             # cards, dialogs
SURFACE_ALT = "#F9FAFB"         # zebra rows, quiet panels
SURFACE_MUTED = "#F0F0F0"       # disabled / chips
BORDER = "#E0E0E0"
BORDER_STRONG = "#CCCCCC"
WHITE = "#FFFFFF"
BLACK = "#000000"

# text
TEXT = "#1A1A1A"
TEXT_SECONDARY = "#4B5563"
TEXT_MUTED = "#5B6470"          # hints, captions (>= 4.5:1 on every surface above)
TEXT_PLACEHOLDER = "#6B7280"    # placeholder text inside inputs (white input only)

# brand
PRIMARY = "#1E4528"             # dark green
PRIMARY_HOVER = "#14301C"
SIDEBAR = "#1A3B22"
SIDEBAR_ACTIVE = "#285733"
ON_PRIMARY = "#FFFFFF"
GREEN_TINT = "#A8D5BA"          # light green text on the dark sidebar / header
ACCENT = "#F1C40F"              # yellow
ACCENT_HOVER = "#D4AC0D"
ON_ACCENT = "#1A1A1A"

# status colours: a FILL colour (badges, bars), a TEXT colour that is readable on white, and a soft background
SUCCESS = "#17803F"
SUCCESS_BRIGHT = "#2ECC71"      # decoration only (dots, chart bars); never carries text
SUCCESS_DARK = "#146C38"
SUCCESS_TEXT = "#146C38"
SUCCESS_BG = "#E8F5E9"
ON_SUCCESS = "#FFFFFF"

WARNING = "#E67E22"
WARNING_ALT = "#F39C12"
WARNING_STRONG = "#D35400"
WARNING_TEXT = "#955500"
WARNING_BG = "#FFF8F0"
WARNING_BORDER = "#F5CBA7"
ON_WARNING = "#1A1A1A"

DANGER = "#D8000C"
DANGER_SOFT = "#E74C3C"
DANGER_HOVER = "#C0392B"
DANGER_DARK = "#B00000"
DANGER_BG = "#FFF3F3"
DANGER_BG_STRONG = "#FFEAEA"
DANGER_BORDER = "#FFC0C0"
ON_DANGER = "#FFFFFF"

INFO = "#26709E"
INFO_HOVER = "#2980B9"
INFO_DARK = "#1F618D"
INFO_TEXT = "#1F618D"
INFO_BG = "#E8F8F5"
ON_INFO = "#FFFFFF"

PURPLE = "#8E44AD"
PURPLE_ALT = "#9B59B6"
PURPLE_HOVER = "#732D91"
ON_PURPLE = "#FFFFFF"

DARK = {      # dark-mode value of every colour that changes; names missing here keep their light value
    "BG": "#12171B", "SURFACE": "#1B2228", "SURFACE_ALT": "#20292F", "SURFACE_MUTED": "#2A343B",
    "BORDER": "#334049", "BORDER_STRONG": "#44525C", "WHITE": "#FFFFFF",
    "TEXT": "#ECEFF1", "TEXT_SECONDARY": "#B8C2C9", "TEXT_MUTED": "#9AA6AE", "TEXT_PLACEHOLDER": "#9AA6AE",
    "PRIMARY": "#2F7D47", "PRIMARY_HOVER": "#256A3B", "SIDEBAR": "#0F1A13", "SIDEBAR_ACTIVE": "#1E4528", "ON_PRIMARY": "#FFFFFF",
    "GREEN_TINT": "#A8D5BA", "ACCENT": "#F1C40F", "ACCENT_HOVER": "#D4AC0D", "ON_ACCENT": "#1A1A1A",
    "SUCCESS": "#2FA865", "SUCCESS_TEXT": "#5FD38D", "SUCCESS_BG": "#17301F", "SUCCESS_DARK": "#2FA865", "ON_SUCCESS": "#0B1F12",
    "WARNING_TEXT": "#F0A44B", "WARNING_BG": "#33271A", "WARNING_BORDER": "#6B4A26",
    "DANGER": "#CF3A40", "DANGER_TEXT": "#FF8A8E", "DANGER_BG": "#351C1E", "DANGER_BG_STRONG": "#47262A", "DANGER_BORDER": "#7A3A3E",
    "DANGER_HOVER": "#C93A3F", "DANGER_DARK": "#B33237", "ON_DANGER": "#FFFFFF",
    "INFO": "#3B8FD0", "INFO_TEXT": "#7DBBEA", "INFO_BG": "#16303D", "INFO_HOVER": "#2E7AB8", "INFO_DARK": "#2E7AB8", "ON_INFO": "#0B1A24",
}
DANGER_TEXT = DANGER            # readable on white already (7.4:1)

# (text colour, background colour) pairs that the contrast check measures, in light mode and (via DARK) in dark mode
TEXT_PAIRS = [
    ("TEXT", "BG"), ("TEXT", "SURFACE"), ("TEXT", "SURFACE_ALT"), ("TEXT", "SURFACE_MUTED"),
    ("TEXT_SECONDARY", "SURFACE"), ("TEXT_SECONDARY", "BG"), ("TEXT_SECONDARY", "SURFACE_ALT"),
    ("TEXT_MUTED", "SURFACE"), ("TEXT_MUTED", "BG"), ("TEXT_MUTED", "SURFACE_ALT"), ("TEXT_PLACEHOLDER", "SURFACE"),
    ("ON_PRIMARY", "PRIMARY"), ("ON_PRIMARY", "PRIMARY_HOVER"), ("ON_PRIMARY", "SIDEBAR"), ("ON_PRIMARY", "SIDEBAR_ACTIVE"),
    ("GREEN_TINT", "SIDEBAR"), ("ACCENT", "SIDEBAR"), ("ACCENT", "SIDEBAR_ACTIVE"), ("ON_ACCENT", "ACCENT"), ("ON_ACCENT", "ACCENT_HOVER"),
    ("ON_SUCCESS", "SUCCESS"), ("SUCCESS_TEXT", "SURFACE"), ("SUCCESS_TEXT", "SUCCESS_BG"), ("SUCCESS_TEXT", "BG"),
    ("ON_WARNING", "WARNING"), ("WARNING_TEXT", "SURFACE"), ("WARNING_TEXT", "WARNING_BG"),
    ("ON_DANGER", "DANGER"), ("ON_DANGER", "DANGER_HOVER"), ("DANGER_TEXT", "SURFACE"), ("DANGER_TEXT", "DANGER_BG"), ("DANGER_TEXT", "DANGER_BG_STRONG"),
    ("ON_INFO", "INFO"), ("INFO_TEXT", "SURFACE"), ("INFO_TEXT", "INFO_BG"), ("ON_PURPLE", "PURPLE"),
]

# ---------------------------------------------------------------- fonts
FAMILY = "Segoe UI"
MONO = "Consolas"
SIZES = (12, 14, 16, 20, 28, 40)          # the only sizes screens may use (caption, body, subtitle, title, display, hero)
SIZE_CAPTION, SIZE_BODY, SIZE_SUBTITLE, SIZE_TITLE, SIZE_DISPLAY, SIZE_HERO = SIZES


def font(size=14, weight="normal"):
    """('Segoe UI', size, weight) for CustomTkinter.  ``size`` must be on the scale (12/14/16/20/28/40)."""
    if size not in SIZES:
        raise ValueError(f"font size {size} is not on the scale {SIZES}")
    return (FAMILY, size, weight)


def mono(size=14, weight="normal"):
    """Consolas, for IDs, tags and numbers that must line up."""
    if size not in SIZES:
        raise ValueError(f"font size {size} is not on the scale {SIZES}")
    return (MONO, size, weight)


# ---------------------------------------------------------------- spacing (4 px grid), radii, motion
SPACE = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "xxl": 32}
S1, S2, S3, S4, S6, S8 = 4, 8, 12, 16, 24, 32
RADIUS_SM, RADIUS_MD, RADIUS_LG = 6, 10, 14
ANIM_FAST, ANIM_NORMAL, ANIM_SLOW = 120, 200, 320        # milliseconds
BUTTON_HEIGHT = 36
FIELD_HEIGHT = 36
ROW_HEIGHT = 44
