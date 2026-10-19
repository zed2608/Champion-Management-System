import os
import mysql.connector
from db import db, DatabaseUnavailable
from dotenv import load_dotenv
import qrcode
import tempfile
from PIL import Image, ImageDraw, ImageFont

# Load the secret credentials from the .env file
# DB_HOST can be a LAN MySQL host/IP, a remote server, or localhost.
# Using a LAN host preserves the app logic and only changes which database server is targeted.
load_dotenv()

class _LegacyConnection:
    """What the older screens receive from get_connection().
    [UNHAPPY-PATH] Their cursors are BUFFERED by default, so a query whose rows are not all fetched can no longer leave an
    "Unread result" behind (which used to make close() raise, leak the connection, and poison the pool for the next save).
    close() is also guaranteed to return the connection."""

    def __init__(self, conn):
        object.__setattr__(self, "_c", conn)

    def cursor(self, *args, **kwargs):
        kwargs.setdefault("buffered", True)
        return self._c.cursor(*args, **kwargs)

    def close(self):
        try:
            self._c.close()
        except Exception:
            from db.pool import _heal
            _heal(self._c)
            try:
                self._c.close()
            except Exception:
                pass

    def __getattr__(self, name):
        return getattr(self._c, name)

    def __setattr__(self, name, value):
        setattr(self._c, name, value)


def get_connection():
    """Legacy entry point kept so existing views keep working.
    [CONCURRENCY] Backed by db.pool: ping + reconnect on checkout, strict session, +08:00 time zone.
    New code should use ``from db import db`` with ``db.read()`` / ``db.transaction()``.
    Returns None (as before) when the database cannot be reached."""
    try:
        return _LegacyConnection(db.raw_connection())
    except DatabaseUnavailable as err:
        print(f"Database Connection Error: {err}")
        return None

# [PANEL-AWE] One login = one session id, written into every audit row of that login. This process serves one user at a time.
_session = {"user_id": None, "sid": None}


def start_session(user_id):
    """Call right after a successful login (before the 'Login' entry is logged). Returns the new session id."""
    import uuid
    _session["user_id"], _session["sid"] = user_id, str(uuid.uuid4())
    return _session["sid"]


def end_session():
    _session["user_id"] = _session["sid"] = None


def current_session_id(user_id):
    if user_id is None or _session["user_id"] != user_id:
        return None                      # another actor (or nobody) never borrows this login's session
    return _session["sid"]


def log_action(user_id, action_type, module, details):
    """
    Universal logger: records ALL system activity in the tamper-evident audit chain (services/audit_chain.py).
    Nothing is ever deleted: old rows are moved to system_logs_archive.
    Call this from any module: log_action(user_id, "Viewed", "Inventory", "Opened inventory list")
    """
    from services import audit_chain
    audit_chain.record(user_id, action_type, module, details, current_session_id(user_id))


def generate_id_badge(emp_id, emp_name, emp_role, company_name="CHAMPION", output_dir=None):
    """
    Generate a 1.5x1.0 inch professional QR ID badge.
    
    PIXEL-PERFECT BADGE SPECIFICATION:
    - Canvas: 450 × 300px (1.5x1.0 inch at 300 DPI)
    - QR code: Centered
    - Employee info: Name and ID below QR
    - Resolution: 300 DPI for crisp PDF label output
    - All text centered horizontally
    
    Args:
        emp_id: Employee ID (converted to string)
        emp_name: Full employee name
        emp_role: Job role/title
        company_name: Organization name for header (default: "CHAMPION")
        output_dir: Output directory (default: temp directory)
    
    Returns:
        Path to generated PDF file
    """
    try:
        emp_id = str(emp_id)
        
        # Generate QR code
        qr = qrcode.QRCode(version=1, box_size=6, border=1)
        qr.add_data(emp_id)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        
        # Canvas dimensions 1.5x1.0 inch @ 300 DPI
        canvas_w = 450
        canvas_h = 300
        canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
        
        draw = ImageDraw.Draw(canvas)
        
        # Load fonts with Windows system fallback
        fonts_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        def _load_font(filename, size):
            for path in [os.path.join(fonts_dir, filename), filename]:
                try:
                    return ImageFont.truetype(path, size)
                except (IOError, OSError):
                    continue
            try:
                return ImageFont.load_default()
            except TypeError:
                return ImageFont.load_default()
        
        f_company = _load_font("arialbd.ttf", 16)
        f_name = _load_font("arialbd.ttf", 20)
        f_id = _load_font("arial.ttf", 14)
        
        def center_x(text, font):
            bbox = draw.textbbox((0, 0), text, font=font)
            return (canvas_w - (bbox[2] - bbox[0])) // 2
        
        # Header text
        draw.text((center_x(company_name, f_company), 10),
                  company_name, fill="black", font=f_company)
        
        # Paste QR
        qr_x = (canvas_w - qr_img.width) // 2
        qr_y = 30
        canvas.paste(qr_img, (qr_x, qr_y))
        
        # Employee info below QR
        y_base = qr_y + qr_img.height + 10
        
        name_str = emp_name
        if len(name_str) > 30: name_str = name_str[:27] + "..."
        
        draw.text((center_x(emp_name, f_name), y_base),
                  name_str, fill="#1A1A1A", font=f_name)
        draw.text((center_x(f"ID: {emp_id}", f_id), y_base + 24),
                  f"ID: {emp_id}", fill="#555555", font=f_id)
        
        # Save PDF
        if output_dir is None:
            output_dir = tempfile.gettempdir()
        
        file_path = os.path.join(output_dir, f"Badge_{emp_id}.pdf")
        canvas.save(file_path, "PDF", resolution=300.0)
        
        return file_path
    
    except Exception as e:
        raise Exception(f"Badge generation failed: {e}")