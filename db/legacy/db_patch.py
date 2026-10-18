from database import get_connection

def patch_database():
    print("Patching projects table with missing ERP fields...")
    conn = get_connection()
    if not conn: return
    try:
        cursor = conn.cursor()
        commands = [
            "ALTER TABLE projects ADD COLUMN workers_assigned TEXT",
            "ALTER TABLE projects ADD COLUMN tools_needed TEXT",
            "ALTER TABLE projects ADD COLUMN approved_by INT NULL"
        ]
        for cmd in commands:
            try:
                cursor.execute(cmd)
                print("✅ Field added!")
            except Exception as e:
                print(f"⏭️ {e}")
        conn.commit()
        print("🎉 DB Patch Complete! You can delete this file now.")
    finally:
        if conn.is_connected(): cursor.close(); conn.close()

if __name__ == "__main__":
    patch_database()