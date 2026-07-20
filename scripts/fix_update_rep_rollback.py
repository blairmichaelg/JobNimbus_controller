with open(r'app\core\database.py', 'rb') as f:
    content = f.read().decode('utf-8')

# Fix: update_field_rep must ROLLBACK before re-raising ValueError for "rep not found"
OLD = '''    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM field_reps WHERE id = ?",
            (rep_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"Rep {rep_id} not found.")
        new_name   = name      if name      is not None else row["name"]
        new_pin    = pin       if pin       is not None else row["pin"]
        new_active = (1 if is_active else 0) \\
                     if is_active is not None \\
                     else row["is_active"]
        conn.execute(
            """UPDATE field_reps
               SET name = ?, pin = ?,
                   is_active = ?,
                   updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (new_name, new_pin, new_active, rep_id)
        )
        conn.execute("COMMIT")
        return {"id": rep_id, "name": new_name,
                "pin": new_pin, "is_active": new_active}
    except sqlite3.IntegrityError:
        conn.execute("ROLLBACK")
        raise ValueError("PIN is already in use.")
    finally:
        conn.close()'''

NEW = '''    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM field_reps WHERE id = ?",
            (rep_id,)
        ).fetchone()
        if not row:
            conn.execute("ROLLBACK")
            raise ValueError(f"Rep {rep_id} not found.")
        new_name   = name      if name      is not None else row["name"]
        new_pin    = pin       if pin       is not None else row["pin"]
        new_active = (1 if is_active else 0) \\
                     if is_active is not None \\
                     else row["is_active"]
        conn.execute(
            """UPDATE field_reps
               SET name = ?, pin = ?,
                   is_active = ?,
                   updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (new_name, new_pin, new_active, rep_id)
        )
        conn.execute("COMMIT")
        return {"id": rep_id, "name": new_name,
                "pin": new_pin, "is_active": new_active}
    except sqlite3.IntegrityError:
        conn.execute("ROLLBACK")
        raise ValueError("PIN is already in use.")
    finally:
        conn.close()'''

if OLD in content:
    content = content.replace(OLD, NEW, 1)
    with open(r'app\core\database.py', 'wb') as f:
        f.write(content.encode('utf-8'))
    print('Fixed: update_field_rep ROLLBACK on not found')
else:
    print('NOT FOUND - searching...')
    idx = content.find('def update_field_rep')
    print(repr(content[idx:idx+1000]))
