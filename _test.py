from database import get_connection
conn = get_connection()
c = conn.cursor(dictionary=True)
c.execute('SELECT tr.condition_at_return as cond_flag FROM transaction tr WHERE tr.type=\
Retrieval\ LIMIT 3')
print('query OK:', c.fetchall())
conn.close()

