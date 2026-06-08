import bcrypt
from database import get_connection
import datetime

def seed_admin():
    conn = get_connection()
    if not conn:
        print("Failed to connect to the local database.")
        return

    try:
        cursor = conn.cursor()
        
        # Check if an admin already exists
        cursor.execute("SELECT * FROM user WHERE role = 'Admin'")
        if cursor.fetchone():
            print("An Admin account already exists.")
            return

        # Securely hash the default password
        default_password = "admin"
        hashed = bcrypt.hashpw(default_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        # Insert the Admin user
        current_year = datetime.datetime.now().year
        emp_id = f"ADM-{current_year}-001"
        cursor.execute("""
            INSERT INTO user (employee_id, full_name, email, role, password_hash, status)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (emp_id, "System Administrator", "admin@champion.com", "Admin", hashed, "Active"))
        
        conn.commit()
        print("Default Admin account successfully created!")
        print(f"Username: {emp_id}")
        print("Password: admin")

    except Exception as e:
        print(f"Error seeding database: {e}")
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()

if __name__ == "__main__":
    seed_admin()
