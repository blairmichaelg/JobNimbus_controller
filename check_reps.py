import sqlite3

conn = sqlite3.connect('data/wickham.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Get reps
cur.execute("SELECT id, name FROM field_reps WHERE name IN ('Field Test Rep', 'Test Mike Rep')")
reps = cur.fetchall()

for r in reps:
    print(f"Deleting {r['name']} ({r['id']})")
    cur.execute("DELETE FROM field_reps WHERE id = ?", (r['id'],))

conn.commit()

cur.execute("SELECT count(*) as c FROM field_reps")
remaining = cur.fetchone()['c']
print(f"Remaining field_reps row count: {remaining}")

