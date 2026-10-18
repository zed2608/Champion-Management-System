from database import get_connection

def upgrade_database():
    print("Connecting to upgrade database schema for ERP features...")
    try:
        conn = get_connection()
        if not conn:
            print("❌ ABORTED: Could not reach the database.")
            return
            
        cursor = conn.cursor()
        
        # 1. Alter existing tables (Consumables & Accountability)
        alter_commands = [
            "ALTER TABLE tool ADD COLUMN item_type VARCHAR(50) DEFAULT 'Equipment'", 
            "ALTER TABLE tool ADD COLUMN unit_of_measure VARCHAR(20) DEFAULT 'pcs'",
            "ALTER TABLE transaction ADD COLUMN issued_by INT NULL",
            "ALTER TABLE transaction ADD COLUMN received_by INT NULL"
        ]

        print("Executing schema alterations...")
        for cmd in alter_commands:
            try:
                cursor.execute(cmd)
                print("✅ Added new column!")
            except Exception as e:
                if "Duplicate column name" in str(e):
                    print("⏭️ Column already exists, skipping.")
                else:
                    print(f"⚠️ Error: {e}")

        # 2. Create New Tables (Projects & Issues)
        create_commands = [
            """CREATE TABLE IF NOT EXISTS projects (
                project_id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                client VARCHAR(255),
                location VARCHAR(255),
                start_date DATE,
                end_date DATE,
                status VARCHAR(50) DEFAULT 'Pending',
                manager_id INT
            )""",
            """CREATE TABLE IF NOT EXISTS project_requirements (
                req_id INT AUTO_INCREMENT PRIMARY KEY,
                project_id INT,
                tool_id INT,
                quantity INT,
                status VARCHAR(50) DEFAULT 'Pending'
            )""",
            """CREATE TABLE IF NOT EXISTS issues_log (
                issue_id INT AUTO_INCREMENT PRIMARY KEY,
                tool_id INT,
                reported_by INT,
                issue_desc TEXT,
                status VARCHAR(50) DEFAULT 'Open',
                reported_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )"""
        ]

        print("Creating new ERP tables...")
        for cmd in create_commands:
            cursor.execute(cmd)
            print("✅ Verified table exists.")
        
        conn.commit()
        print("🎉 ERP Database upgrade finished perfectly!")
        
    except Exception as e:
        print(f"Critical Error: {e}")
    finally:
        if 'conn' in locals() and conn is not None and conn.is_connected():
            cursor.close()
            conn.close()

if __name__ == "__main__":
    upgrade_database()