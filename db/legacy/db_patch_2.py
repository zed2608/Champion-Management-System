from database import get_connection

def patch_database_v2():
    print("Patching database for Fractional Consumables, Descriptions, and Audit Logs...")
    conn = get_connection()
    if not conn: return
    try:
        cursor = conn.cursor()
        commands = [
            # 1. Allow fractional returns (e.g., 0.5 boxes)
            "ALTER TABLE inventory MODIFY quantity_total DECIMAL(10,2)",
            "ALTER TABLE inventory MODIFY quantity_available DECIMAL(10,2)",
            "ALTER TABLE project_requirements MODIFY quantity DECIMAL(10,2)",
            # 2. Add missing project fields
            "ALTER TABLE projects ADD COLUMN description TEXT",
            "ALTER TABLE projects ADD COLUMN project_head VARCHAR(255)",
            # 3. Create the massive System Log table
            """CREATE TABLE IF NOT EXISTS system_logs (
                log_id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT,
                action_type VARCHAR(100),
                module VARCHAR(100),
                details TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )"""
        ]
        for cmd in commands:
            try: cursor.execute(cmd)
            except Exception as e: print(f"⏭️ {e}")
        conn.commit()
        print("🎉 DB Patch V2 Complete!")
    finally:
        if conn.is_connected(): cursor.close(); conn.close()

if __name__ == "__main__":
    patch_database_v2()