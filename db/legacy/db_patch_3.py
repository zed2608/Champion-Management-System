"""
db_patch_3.py  — Champion Fine Tooling AMS
Compatible with MySQL 5.7 and 8.0.
Tries each ALTER TABLE and silently skips if the column already exists.
Run this ONCE to sync the full schema.
"""
from database import get_connection


def try_alter(cursor, sql, label):
    try:
        cursor.execute(sql)
        print(f"  ✅ Added: {label}")
    except Exception as e:
        err = str(e)
        if "Duplicate column name" in err or "already exists" in err:
            print(f"  ⏭  Already exists, skipped: {label}")
        else:
            print(f"  ⚠  {label} → {e}")


def patch_database_v3():
    print("Running DB Patch v3 — Full schema sync (MySQL 5.7 compatible)...\n")
    conn = get_connection()
    if not conn:
        print("❌ ABORTED: Cannot connect to database.")
        return

    try:
        cursor = conn.cursor()

        print("── projects table ──────────────────────────────")
        try_alter(cursor, "ALTER TABLE projects ADD COLUMN description TEXT", "projects.description")
        try_alter(cursor, "ALTER TABLE projects ADD COLUMN project_head VARCHAR(255)", "projects.project_head")
        try_alter(cursor, "ALTER TABLE projects ADD COLUMN workers_assigned TEXT", "projects.workers_assigned")
        try_alter(cursor, "ALTER TABLE projects ADD COLUMN tools_needed TEXT", "projects.tools_needed")
        try_alter(cursor, "ALTER TABLE projects ADD COLUMN approved_by INT NULL", "projects.approved_by")

        print("\n── tool table ──────────────────────────────────")
        try_alter(cursor, "ALTER TABLE tool ADD COLUMN item_type VARCHAR(50) DEFAULT 'Equipment'", "tool.item_type")
        try_alter(cursor, "ALTER TABLE tool ADD COLUMN unit_of_measure VARCHAR(20) DEFAULT 'pcs'", "tool.unit_of_measure")
        try_alter(cursor, "ALTER TABLE tool ADD COLUMN description TEXT", "tool.description")

        print("\n── inventory — fractional quantities ───────────")
        try_alter(cursor, "ALTER TABLE inventory MODIFY quantity_total DECIMAL(10,2)", "inventory.quantity_total → DECIMAL")
        try_alter(cursor, "ALTER TABLE inventory MODIFY quantity_available DECIMAL(10,2)", "inventory.quantity_available → DECIMAL")
        try_alter(cursor, "ALTER TABLE project_requirements MODIFY quantity DECIMAL(10,2)", "project_requirements.quantity → DECIMAL")

        print("\n── transaction table ───────────────────────────")
        try_alter(cursor, "ALTER TABLE transaction ADD COLUMN issued_by INT NULL", "transaction.issued_by")
        try_alter(cursor, "ALTER TABLE transaction ADD COLUMN received_by INT NULL", "transaction.received_by")

        print("\n── system_logs table ───────────────────────────")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_logs (
                log_id      INT AUTO_INCREMENT PRIMARY KEY,
                user_id     INT,
                action_type VARCHAR(100),
                module      VARCHAR(100),
                details     TEXT,
                timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_user   (user_id),
                INDEX idx_ts     (timestamp),
                INDEX idx_module (module)
            )
        """)
        print("  ✅ system_logs table ready")

        print("\n── tool_issues table ───────────────────────────")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tool_issues (
                issue_id       INT AUTO_INCREMENT PRIMARY KEY,
                tool_id        INT NOT NULL,
                reported_by    VARCHAR(100),
                condition_flag VARCHAR(100),
                notes          TEXT,
                flagged_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_resolved    TINYINT(1) DEFAULT 0,
                FOREIGN KEY (tool_id) REFERENCES tool(tool_id)
            )
        """)
        print("  ✅ tool_issues table ready")

        conn.commit()
        print("\n🎉 DB Patch v3 Complete! All columns and tables are in sync.")
        print("   You can now delete this file.\n")

    except Exception as e:
        print(f"\n❌ Critical Error: {e}")
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()


if __name__ == "__main__":
    patch_database_v3()