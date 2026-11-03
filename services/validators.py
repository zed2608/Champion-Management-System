"""Input rules shared by every view and service.

[RBAC][UNHAPPY-PATH] The UI may pre-check, but this module is the single source of truth, so a value that reaches the
database layer by any route (typed, scanned, pasted, scripted) obeys the same rules.
All errors are ``ValidationError`` with a message that is safe to show to the user.
"""
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import bcrypt

# ---- limits (match column sizes in db/schema.sql) ------------------------------------------------------------------
MAX_NAME = 100
MAX_NOTES = 1000
MAX_SEARCH = 64
MAX_QTY = Decimal("100000")
MAX_PRICE = Decimal("99999999.99")      # DECIMAL(10,2)
MAX_PASSWORD_BYTES = 72                 # bcrypt hard limit; bcrypt 5.0 raises ValueError above it
DIVISIBLE_UNITS = frozenset({"boxes", "sets", "kg", "packs", "liters", "rolls", "meters", "feet"})
UNITS = DIVISIBLE_UNITS | {"pcs"}

TAG_ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{2,31}$")
EMPLOYEE_ID_RE = re.compile(r"^(ADM|STF|WKR)-\d{4}-\d{3,}$")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")       # keeps \t and \n
_CONTROL_SINGLELINE_RE = re.compile(r"[\x00-\x1f\x7f]")


class ValidationError(ValueError):
    """Message is user-safe."""


# ---- text ---------------------------------------------------------------------------------------------------------
def clean_text(value, *, max_len: int = MAX_NAME, field: str = "Value", required: bool = True,
               multiline: bool = False) -> str:
    """Strip control characters, trim, enforce non-empty and a length cap."""
    if value is None:
        value = ""
    if not isinstance(value, str):
        value = str(value)
    value = unicodedata.normalize("NFC", value)
    value = (_CONTROL_RE if multiline else _CONTROL_SINGLELINE_RE).sub(" " if not multiline else "", value)
    value = re.sub(r"[ ]{2,}", " ", value).strip() if not multiline else value.strip()
    if required and not value:
        raise ValidationError(f"{field} is required.")
    if len(value) > max_len:
        raise ValidationError(f"{field} must be at most {max_len} characters.")
    return value


def clean_person_name(value, *, field="Full Name", required=True, max_len=MAX_NAME):
    """Names may contain spaces and common punctuation, but never digits or control text."""
    name = clean_text(value, max_len=max_len, field=field, required=required)
    if name and (not any(ch.isalpha() for ch in name) or
                 any(not (ch.isalpha() or ch.isspace() or ch in "-'.’,") for ch in name)):
        raise ValidationError(f"{field} must use letters, spaces, apostrophes, commas, periods or hyphens; no numbers.")
    return name


def clean_named_label(value, *, field, max_len=MAX_NAME, required=True):
    """A project/tool name needs a word; digits are allowed for phases and sizes."""
    name = clean_text(value, max_len=max_len, field=field, required=required)
    if name and not any(ch.isalpha() for ch in name):
        raise ValidationError(f"{field} must include a name, not just numbers or symbols.")
    return name


def clean_search(query) -> str:
    """Search box text: control chars removed, trimmed, capped at 64 characters (never raises)."""
    try:
        return clean_text(query, max_len=10 ** 6, required=False)[:MAX_SEARCH]
    except ValidationError:
        return ""


def escape_like(text: str) -> str:
    """Escape LIKE wildcards so '%' and '_' typed by a user are matched literally. Use with the default ESCAPE '\\'."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def like_pattern(query) -> str:
    """'%escaped-query%' ready to pass as a bound parameter."""
    return f"%{escape_like(clean_search(query))}%"


# ---- identifiers -------------------------------------------------------------------------------------------------
def validate_tag_id(value) -> str:
    v = clean_text(value, max_len=32, field="Tag ID").upper()
    if not TAG_ID_RE.match(v):
        raise ValidationError("Tag ID must be 3-32 characters: letters, numbers and dashes, starting with a letter or number.")
    return v


def validate_employee_id(value) -> str:
    v = clean_text(value, max_len=50, field="Employee ID").upper()
    if not EMPLOYEE_ID_RE.match(v):
        raise ValidationError("Employee ID must look like ADM-2026-001, STF-2026-001 or WKR-2026-001.")
    return v


def validate_email(value, *, required: bool = True):
    v = clean_text(value, max_len=100, field="Email", required=required)
    if not v:
        return None
    if not EMAIL_RE.match(v):
        raise ValidationError("Please enter a valid email address.")
    return v.lower()


def parse_id(value, field: str = "ID") -> int:
    """A database id from a screen: an int, or the text of one ('42', as widgets and table rows hand it over).
    [UNHAPPY-PATH] The Inventory panel passes the row's id as TEXT; looking it up in a dict keyed by int raised KeyError('1') and every
    Update failed with a generic error. Ids are converted and validated HERE, once, instead of trusting each caller."""
    if isinstance(value, bool):
        raise ValidationError(f"{field} is not valid.")
    if isinstance(value, int):
        n = value
    elif isinstance(value, str) and value.strip().isdigit() and len(value.strip()) <= 18:
        n = int(value.strip())
    else:
        raise ValidationError(f"{field} is not valid.")
    if n <= 0:
        raise ValidationError(f"{field} is not valid.")
    return n


@dataclass(frozen=True)
class Scan:
    kind: str          # 'tool' | 'worker' | 'unknown'
    value: str


def parse_scan(raw) -> Scan:
    """ONE place that understands what a QR code or a keyboard-wedge scanner delivers.

    Tool sticker:  "Tag ID: X\\nPID: 12\\nName: ...\\n..."      -> Scan('tool', 'X')
    Worker badge:  "WKR-2026-001"  or  "Employee ID: WKR-..."   -> Scan('worker', 'WKR-2026-001')
    Bare value that fits a pattern is classified by pattern; worker patterns win over tag patterns.
    """
    text = (raw or "")
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    first = next((ln.strip() for ln in str(text).replace("\r", "").split("\n") if ln.strip()), "")
    first = _CONTROL_SINGLELINE_RE.sub("", first)
    if not first or len(first) > 200:
        return Scan("unknown", "")
    m = re.match(r"(?i)^tag\s*id\s*:\s*(.+)$", first)
    if m:
        return Scan("tool", m.group(1).strip().upper())
    m = re.match(r"(?i)^employee\s*id\s*:\s*(.+)$", first)
    if m:
        return Scan("worker", m.group(1).strip().upper())
    up = first.upper()
    if EMPLOYEE_ID_RE.match(up):
        return Scan("worker", up)
    if TAG_ID_RE.match(up):
        return Scan("tool", up)
    return Scan("unknown", first)


# ---- numbers -----------------------------------------------------------------------------------------------------
def parse_quantity(value, *, whole: bool = False, field: str = "Quantity", allow_zero: bool = False) -> Decimal:
    """> 0 (or >= 0 with ``allow_zero``, used for stock levels), at most 2 decimals, at most 100,000; whole numbers only when
    ``whole`` (Equipment)."""
    try:
        q = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ValidationError(f"{field} must be a number.")
    if not q.is_finite():
        raise ValidationError(f"{field} must be a number.")
    if q < 0 or (q == 0 and not allow_zero):
        raise ValidationError(f"{field} must be greater than zero." if not allow_zero else f"{field} cannot be negative.")
    if q > MAX_QTY:
        raise ValidationError(f"{field} cannot exceed {MAX_QTY:,}.")
    if q != q.quantize(Decimal("0.01")):
        raise ValidationError(f"{field} can have at most 2 decimal places.")
    if whole and q != q.to_integral_value():
        raise ValidationError(f"{field} must be a whole number for equipment.")
    return q.quantize(Decimal("0.01"))


def whole_quantity_only(item_type, unit_of_measure) -> bool:
    """Equipment and consumables counted in pieces use whole units throughout the system."""
    return (item_type or "Equipment") != "Consumable" or (unit_of_measure or "pcs").strip().lower() not in DIVISIBLE_UNITS


def item_quantity(value, item_type, unit_of_measure, *, field="Quantity", allow_zero=False) -> Decimal:
    whole = whole_quantity_only(item_type, unit_of_measure)
    q = parse_quantity(value, field=field, allow_zero=allow_zero)
    if whole and q != q.to_integral_value():
        label = "equipment" if item_type != "Consumable" else f"{unit_of_measure or 'pcs'}"
        raise ValidationError(f"{field} must be a whole number for {label}.")
    return q


def fmt_qty(x) -> str:
    """Quantity for people: 2.00 -> '2', 2.50 -> '2.5', 100 -> '100'. (Decimal's own ``:g`` keeps trailing zeros: '2.00'.)"""
    try:
        s = format(Decimal(str(x)), "f")
    except (InvalidOperation, ValueError):
        return str(x)
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def parse_price(value, *, field: str = "Price") -> Decimal:
    try:
        p = Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError):
        raise ValidationError(f"{field} must be a number.")
    if not p.is_finite() or p < 0:
        raise ValidationError(f"{field} cannot be negative.")
    if p > MAX_PRICE:
        raise ValidationError(f"{field} is too large.")
    if p != p.quantize(Decimal("0.01")):
        raise ValidationError(f"{field} can have at most 2 decimal places.")
    return p.quantize(Decimal("0.01"))


def parse_iso_date(value, *, field: str = "Date", required: bool = True):
    v = clean_text(value, max_len=10, field=field, required=required)
    if not v:
        return None
    try:
        return datetime.strptime(v, "%Y-%m-%d").date()
    except ValueError:
        raise ValidationError(f"{field} must be in YYYY-MM-DD format.")


def validate_date_range(start, end, *, field_start="Start date", field_end="End date"):
    """[4-DATE] start <= end (hard rule, mirrored by CHECK constraint chk_projects_dates)."""
    if (start is None) != (end is None):
        raise ValidationError(f"Enter both {field_start.lower()} and {field_end.lower()}, or leave both blank.")
    if isinstance(start, date) and isinstance(end, date) and start > end:
        raise ValidationError(f"{field_start} must be on or before {field_end.lower()}.")


# ---- passwords ---------------------------------------------------------------------------------------------------
def password_problems(pw: str) -> list:
    """Unmet strength rules (same four the registration screen shows): 8+ chars, number, uppercase, special."""
    problems = []
    if len(pw) < 8:
        problems.append("at least 8 characters")
    if not re.search(r"\d", pw):
        problems.append("a number")
    if not re.search(r"[A-Z]", pw):
        problems.append("an uppercase letter")
    if not re.search(r"[^A-Za-z0-9]", pw):
        problems.append("a special character")
    return problems


def validate_new_password(pw) -> str:
    """Passwords are NEVER stripped (a trailing space is part of the secret). Rejects > 72 bytes (bcrypt limit)."""
    if not isinstance(pw, str) or pw == "":
        raise ValidationError("Password is required.")
    if len(pw.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValidationError("Password is too long (maximum 72 bytes).")
    problems = password_problems(pw)
    if problems:
        raise ValidationError("Password needs " + ", ".join(problems) + ".")
    return pw


def hash_password(pw: str) -> str:
    validate_new_password(pw)
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(pw, password_hash) -> bool:
    """False (never an exception) for Workers (NULL hash), over-long input or a malformed hash."""
    if not pw or not password_hash or len(pw.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return False
    try:
        return bcrypt.checkpw(pw.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False
