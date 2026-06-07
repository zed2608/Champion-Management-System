from dotenv import load_dotenv
import os, mysql.connector

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

conn = mysql.connector.connect(
    host=os.getenv('DB_HOST'), port=int(os.getenv('DB_PORT')),
    user=os.getenv('DB_USER'), password=os.getenv('DB_PASS'),
    database=os.getenv('DB_NAME')
)
cursor = conn.cursor()

sd, ed = '2026-06-01', '2026-06-03'

print(f"=== ABC query with filter {sd} to {ed} ===")
cursor.execute("""
    SELECT t.tool_id, t.name, COUNT(tr.transaction_id) as usage_count
    FROM tool t
    LEFT JOIN transaction tr ON t.tool_id = tr.tool_id AND tr.type = 'Issue'
        AND DATE(DATE_ADD(tr.borrow_date, INTERVAL 8 HOUR)) >= %s
        AND DATE(DATE_ADD(tr.borrow_date, INTERVAL 8 HOUR)) <= %s
    WHERE t.is_archived = 0
    GROUP BY t.tool_id, t.name
    HAVING usage_count > 0
    ORDER BY usage_count DESC
""", (sd, ed))
rows = cursor.fetchall()
print(f"Rows returned: {len(rows)}")
for r in rows[:5]:
    print(r)

print(f"\n=== Raw Issue transactions between {sd} and {ed} ===")
cursor.execute("""
    SELECT transaction_id, tool_id, borrow_date,
           DATE(DATE_ADD(borrow_date, INTERVAL 8 HOUR)) as local_date
    FROM transaction
    WHERE type='Issue'
      AND DATE(DATE_ADD(borrow_date, INTERVAL 8 HOUR)) BETWEEN %s AND %s
    LIMIT 10
""", (sd, ed))
rows2 = cursor.fetchall()
print(f"Issue transactions in range: {len(rows2)}")
for r in rows2:
    print(r)

print("\n=== All Issue transaction dates (distinct local dates) ===")
cursor.execute("""
    SELECT DISTINCT DATE(DATE_ADD(borrow_date, INTERVAL 8 HOUR)) as local_date, COUNT(*) as cnt
    FROM transaction WHERE type='Issue'
    GROUP BY local_date ORDER BY local_date DESC LIMIT 10
""")
for r in cursor.fetchall():
    print(r)

cursor.close()
conn.close()
