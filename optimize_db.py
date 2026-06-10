"""
optimize_db.py — Run once to add performance indexes to champion_db.
Safe to re-run: uses IF NOT EXISTS / ignores duplicate key errors.
"""
from database import get_connection

INDEXES = [
    # transaction — most queried table (issuance, tracking, audit, dashboard)
    ("transaction", "idx_tr_tool_id",       "tool_id"),
    ("transaction", "idx_tr_user_id",       "user_id"),
    ("transaction", "idx_tr_project_id",    "project_id"),
    ("transaction", "idx_tr_status",        "status"),
    ("transaction", "idx_tr_borrow_date",   "borrow_date"),
    ("transaction", "idx_tr_type",          "type"),

    # tool — filtered heavily in inventory, tagging, maintenance
    ("tool",        "idx_tool_is_archived", "is_archived"),
    ("tool",        "idx_tool_condition",   "`condition`"),
    ("tool",        "idx_tool_tag_id",      "tag_id"),
    ("tool",        "idx_tool_category",    "category"),
    ("tool",        "idx_tool_name",        "name"),

    # inventory — joined on tool_id in almost every inventory query
    ("inventory",   "idx_inv_tool_id",      "tool_id"),

    # projects — filtered by status, archived_at, end_date
    ("projects",    "idx_proj_status",      "status"),
    ("projects",    "idx_proj_archived_at", "archived_at"),
    ("projects",    "idx_proj_end_date",    "end_date"),

    # user — searched by status, email, full_name
    ("user",        "idx_user_status",      "status"),
    ("user",        "idx_user_email",       "email"),
    ("user",        "idx_user_full_name",   "full_name"),

    # system_logs — paginated & filtered by module, timestamp
    ("system_logs", "idx_log_module",       "module"),
    ("system_logs", "idx_log_timestamp",    "timestamp"),
    ("system_logs", "idx_log_user_id",      "user_id"),
]

def optimize():
    conn = get_connection()
    if not conn:
        print("❌ Could not connect to database.")
        return

    cursor = conn.cursor()
    ok, skipped, failed = 0, 0, 0

    for table, index_name, column in INDEXES:
        # Check if index already exists
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.statistics
            WHERE table_schema = DATABASE()
              AND table_name = %s
              AND index_name = %s
        """, (table, index_name))
        exists = cursor.fetchone()[0]

        if exists:
            print(f"  SKIP  {table}.{index_name} (already exists)")
            skipped += 1
            continue

        try:
            cursor.execute(f"CREATE INDEX {index_name} ON `{table}` ({column})")
            conn.commit()
            print(f"  ✓     {table}.{index_name} ({column})")
            ok += 1
        except Exception as e:
            print(f"  ✗     {table}.{index_name} — {e}")
            failed += 1

    cursor.close()
    conn.close()
    print(f"\nDone: {ok} created, {skipped} skipped, {failed} failed.")

if __name__ == "__main__":
    optimize()
