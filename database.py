import os
import mysql.connector
from mysql.connector import pooling
from dotenv import load_dotenv
import qrcode
import tempfile
from PIL import Image, ImageDraw, ImageFont

# Load the secret credentials from the .env file
# DB_HOST can be a LAN MySQL host/IP, a remote server, or localhost.
# Using a LAN host preserves the app logic and only changes which database server is targeted.
load_dotenv()

_db_pool = None

def get_connection():
    global _db_pool
    try:
        if _db_pool is None:
            _db_pool = pooling.MySQLConnectionPool(
                pool_name="champion_pool",
                pool_size=10,
                pool_reset_session=True,
                host=os.getenv("DB_HOST", "localhost"),
                port=int(os.getenv("DB_PORT") or 3306),
                user=os.getenv("DB_USER", "root"),
                password=os.getenv("DB_PASS", ""),
                database=os.getenv("DB_NAME", "champion_db")
            )
        return _db_pool.get_connection()
    except mysql.connector.Error as err:
        print(f"Database Connection Error: {err}")
        return None

def log_action(user_id, action_type, module, details):
    """
    Universal logger — logs ALL system activity.
    Auto-prunes to keep only the latest 10,000 records (storage safety net for 1 GB DB).
    Call this from any module: log_action(user_id, "Viewed", "Inventory", "Opened inventory list")
    """
    conn = get_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # 1. Insert the new log
            cursor.execute(
                "INSERT INTO system_logs (user_id, action_type, module, details) VALUES (%s, %s, %s, %s)",
                (user_id, action_type, module, details)
            )
            # 2. Storage Safety Net: Keep only the latest 10,000 records to prevent DB bloat
            #    At ~500 bytes per log, 10,000 logs ≈ 5 MB — negligible on a 1 GB DB.
            cursor.execute("""
                DELETE FROM system_logs
                WHERE log_id NOT IN (
                    SELECT log_id FROM (
                        SELECT log_id FROM system_logs ORDER BY timestamp DESC LIMIT 10000
                    ) foo
                )
            """)
            conn.commit()
        except Exception as e:
            print(f"Log Error: {e}")
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()


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