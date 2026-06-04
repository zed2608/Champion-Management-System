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
                host=os.getenv("DB_HOST"),
                port=os.getenv("DB_PORT"),
                user=os.getenv("DB_USER"),
                password=os.getenv("DB_PASS"),
                database=os.getenv("DB_NAME")
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


def generate_id_badge(emp_id, emp_name, emp_role, company_name="Champion Fine Tooling Corp.", output_dir=None):
    """
    Generate a professional QR ID badge with company header.
    
    PIXEL-PERFECT BADGE SPECIFICATION:
    - Canvas: 420 × (QR height + 220px)
    - Header band: 50px green (#1E4528) with company name centered
    - QR code: Centered, 60px below header
    - Employee info: Name (28pt bold), Role (18pt), ID (14pt) below QR
    - Resolution: 150 DPI for crisp PDF output
    - All text centered horizontally
    
    Args:
        emp_id: Employee ID (converted to string)
        emp_name: Full employee name
        emp_role: Job role/title
        company_name: Organization name for header (default: "Champion Fine Tooling Corp.")
        output_dir: Output directory (default: temp directory)
    
    Returns:
        Path to generated PDF file
    """
    try:
        emp_id = str(emp_id)
        
        # Generate QR code with professional appearance
        qr = qrcode.QRCode(version=1, box_size=14, border=2)
        qr.add_data(emp_id)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="#1E4528", back_color="white").convert("RGB")
        
        # Canvas dimensions
        canvas_w = 420
        canvas_h = qr_img.height + 220
        canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
        
        # Draw header band
        draw_bg = ImageDraw.Draw(canvas)
        draw_bg.rectangle([(0, 0), (canvas_w, 50)], fill="#1E4528")
        
        # Paste QR centered below header
        qr_x = (canvas_w - qr_img.width) // 2
        canvas.paste(qr_img, (qr_x, 60))
        
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
                return ImageFont.load_default(size=size)
            except TypeError:
                return ImageFont.load_default()
        
        f_company = _load_font("arialbd.ttf", 16)
        f_name = _load_font("arialbd.ttf", 28)
        f_role = _load_font("arial.ttf", 18)
        f_id = _load_font("arial.ttf", 14)
        
        def center_x(text, font):
            bbox = draw.textbbox((0, 0), text, font=font)
            return (canvas_w - (bbox[2] - bbox[0])) // 2
        
        # Header text (company name)
        draw.text((center_x(company_name, f_company), 14),
                  company_name, fill="white", font=f_company)
        
        # Employee info below QR
        y_base = qr_img.height + 75
        draw.text((center_x(emp_name, f_name), y_base),
                  emp_name, fill="#1A1A1A", font=f_name)
        draw.text((center_x(emp_role, f_role), y_base + 42),
                  emp_role, fill="#1E4528", font=f_role)
        draw.text((center_x(f"ID: {emp_id}", f_id), y_base + 76),
                  f"ID: {emp_id}", fill="gray", font=f_id)
        
        # Save PDF
        if output_dir is None:
            output_dir = tempfile.gettempdir()
        
        file_path = os.path.join(output_dir, f"Badge_{emp_id}.pdf")
        canvas.save(file_path, "PDF", resolution=150.0)
        
        return file_path
    
    except Exception as e:
        raise Exception(f"Badge generation failed: {e}")