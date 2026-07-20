with open(r'app\core\database.py', 'rb') as f:
    content = f.read().decode('utf-8')

OLD = '''def get_field_rep_by_pin(pin: str) -> dict | None:
    """
    Look up an active field rep by their PIN.
    Returns None if not found or rep is inactive.
    This is the auth hot path -- keep it fast.
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM field_reps "
            "WHERE pin = ? AND is_active = 1",
            (pin,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()'''

NEW = '''def get_field_rep_by_pin(pin: str) -> dict | None:
    """
    Look up an active field rep by their PIN.
    Returns None if not found, if rep is inactive,
    or if the field_reps table does not yet exist
    (graceful degradation during first-run migration).
    This is the auth hot path -- keep it fast.
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM field_reps "
            "WHERE pin = ? AND is_active = 1",
            (pin,)
        ).fetchone()
        return dict(row) if row else None
    except sqlite3.OperationalError:
        # Table may not exist yet (first-run before init_db completes)
        return None
    finally:
        conn.close()'''

if OLD in content:
    content = content.replace(OLD, NEW, 1)
    with open(r'app\core\database.py', 'wb') as f:
        f.write(content.encode('utf-8'))
    print('Patch applied: get_field_rep_by_pin graceful degradation')
else:
    print('OLD string NOT FOUND')
    idx = content.find('def get_field_rep_by_pin')
    if idx != -1:
        print(repr(content[idx:idx+500]))
