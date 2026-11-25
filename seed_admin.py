"""Create the first administrator only; never reset an existing account."""
from getpass import getpass
from datetime import datetime
import bcrypt
from database import get_connection

def seed_admin():
    conn = get_connection()
    if conn is None:
        raise SystemExit("Database unavailable.")
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT user_id FROM user WHERE role = 'Admin' LIMIT 1")
        if cursor.fetchone():
            print("An administrator already exists. No changes made.")
            return
        password = getpass("New administrator password (12+ characters, max 72 UTF-8 bytes): ")
        if len(password) < 12 or len(password.encode("utf-8")) > 72:
            raise SystemExit("Password length is invalid.")
        if password != getpass("Confirm password: "):
            raise SystemExit("Passwords do not match.")
        emp_id = f"ADM-{datetime.now().year}-001"
        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        cursor.execute("INSERT INTO user (employee_id, full_name, role, password_hash, status, failed_attempts, reset_requested) VALUES (%s,%s,%s,%s,%s,0,0)", (emp_id, "System Administrator", "Admin", hashed, "Active"))
        conn.commit()
        print(f"Administrator created: {emp_id}")
    except BaseException:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    seed_admin()
