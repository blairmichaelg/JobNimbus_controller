import sqlite3

conn = sqlite3.connect('data/wickham.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
for row in cur.fetchall():
    print(f"--- {row['name']} ---")
    print(row['sql'])

