"""
Phase 9 database.py patcher.
Applies all needed changes to database.py in a single pass.
"""
import re

with open(r'app\core\database.py', 'rb') as f:
    content = f.read().decode('utf-8')

# ─────────────────────────────────────────────────────────────
# Patch 1: Add canvasser_rep_id to Phase 5 & 6 migration list
# ─────────────────────────────────────────────────────────────
CARRIER_SLA_OLD = '"carrier_sla_days INTEGER DEFAULT 14"'
CARRIER_SLA_NEW = '"carrier_sla_days INTEGER DEFAULT 14",\r\n            "canvasser_rep_id TEXT"'
if CARRIER_SLA_OLD in content and CARRIER_SLA_NEW not in content:
    content = content.replace(CARRIER_SLA_OLD, CARRIER_SLA_NEW, 1)
    print('Patch 1 applied: canvasser_rep_id migration column')
else:
    if CARRIER_SLA_NEW in content:
        print('Patch 1 already applied (skip)')
    else:
        print('Patch 1 FAILED')

# ─────────────────────────────────────────────────────────────
# Patch 2: Add field_reps CREATE TABLE after job_tasks block
# ─────────────────────────────────────────────────────────────
FIELD_REPS_MARKER = "CREATE TABLE IF NOT EXISTS field_reps"
if FIELD_REPS_MARKER not in content:
    JOB_TASKS_ANCHOR = "PRIMARY KEY(job_id, task_type)\r\n            )\r\n        ''')\r\n        \r\n        conn.execute(\"CREATE INDEX"
    JOB_TASKS_ANCHOR_ALT = "PRIMARY KEY(job_id, task_type)\r\n            )\r\n        ''')\r\n\r\n        conn.execute(\"CREATE INDEX"
    
    field_reps_block = (
        "\r\n\r\n        # V5 MIGRATION: field_reps table introduced Phase 9.\r\n"
        "        # No data migration required. Existing static field_pin\r\n"
        "        # in config.py remains as a config-level default only.\r\n"
        "        conn.execute('''\r\n"
        "            CREATE TABLE IF NOT EXISTS field_reps (\r\n"
        "                id          TEXT PRIMARY KEY,\r\n"
        "                name        TEXT NOT NULL,\r\n"
        "                pin         TEXT NOT NULL UNIQUE,\r\n"
        "                is_active   INTEGER NOT NULL DEFAULT 1,\r\n"
        "                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,\r\n"
        "                updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP\r\n"
        "            )\r\n"
        "        ''')"
    )
    
    # Find job_tasks anchor
    idx = content.find("PRIMARY KEY(job_id, task_type)")
    if idx != -1:
        # Find the closing ''') after it
        close_idx = content.find("''')", idx)
        if close_idx != -1:
            insert_pos = close_idx + len("''')")
            content = content[:insert_pos] + field_reps_block + content[insert_pos:]
            print('Patch 2 applied: field_reps CREATE TABLE')
        else:
            print('Patch 2 FAILED: could not find closing quote')
    else:
        print('Patch 2 FAILED: job_tasks anchor not found')
else:
    print('Patch 2 already applied (skip)')

# ─────────────────────────────────────────────────────────────
# Patch 3: Add idx_field_reps_pin index after supp_flags index
# ─────────────────────────────────────────────────────────────
SUPP_FLAGS_IDX = 'conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_supp_flags_unique ON supplement_flags(job_id, rule_id)")'
FIELD_REPS_IDX = '\r\n        conn.execute(\r\n            "CREATE UNIQUE INDEX IF NOT EXISTS "\r\n            "idx_field_reps_pin ON field_reps(pin)"\r\n        )'

if "idx_field_reps_pin" not in content:
    if SUPP_FLAGS_IDX in content:
        content = content.replace(
            SUPP_FLAGS_IDX,
            SUPP_FLAGS_IDX + FIELD_REPS_IDX,
            1
        )
        print('Patch 3 applied: idx_field_reps_pin index')
    else:
        print('Patch 3 FAILED: supp_flags index anchor not found')
else:
    print('Patch 3 already applied (skip)')

# ─────────────────────────────────────────────────────────────
# Patch 4: Append CRUD functions at end of file
# ─────────────────────────────────────────────────────────────
CRUD_MARKER = "def create_field_rep"
if CRUD_MARKER not in content:
    crud_block = '''

# ============================================================
# FIELD REP CRUD \u2014 Phase 9
# ============================================================

def create_field_rep(name: str, pin: str) -> dict:
    """
    Create a new field rep. Raises ValueError if the PIN is already in
    use by another rep OR if the PIN conflicts with any static system
    PIN (admin_pin, accounting_pin, operations_pin) in config.py.
    PIN must be exactly 4 digits.
    Returns the created rep as a dict.
    """
    if not pin.isdigit() or len(pin) != 4:
        raise ValueError("PIN must be exactly 4 digits.")
    settings = get_settings()
    reserved = {
        settings.admin_pin,
        settings.accounting_pin,
        settings.operations_pin,
    }
    if pin in reserved:
        raise ValueError("PIN conflicts with a reserved system PIN.")
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        rep_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO field_reps
               (id, name, pin, is_active)
               VALUES (?, ?, ?, 1)""",
            (rep_id, name.strip(), pin)
        )
        conn.execute("COMMIT")
        logger.info("field_rep_created", rep_id=rep_id, name=name)
        return {"id": rep_id, "name": name.strip(),
                "pin": pin, "is_active": 1}
    except sqlite3.IntegrityError:
        conn.execute("ROLLBACK")
        raise ValueError("PIN is already in use.")
    finally:
        conn.close()


def list_field_reps(include_inactive: bool = False) -> list[dict]:
    """Return all field reps, active only by default."""
    conn = get_connection()
    try:
        if include_inactive:
            cursor = conn.execute(
                "SELECT * FROM field_reps "
                "ORDER BY name ASC"
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM field_reps "
                "WHERE is_active = 1 "
                "ORDER BY name ASC"
            )
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def get_field_rep_by_pin(pin: str) -> dict | None:
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
        conn.close()


def update_field_rep(
    rep_id: str,
    name: str | None = None,
    pin: str | None = None,
    is_active: bool | None = None,
) -> dict:
    """
    Update a field rep\'s name, PIN, and/or active status.
    PIN uniqueness and system-PIN conflict checks apply.
    Returns the updated rep dict.
    Raises ValueError if rep_id not found.
    """
    if pin is not None:
        if not pin.isdigit() or len(pin) != 4:
            raise ValueError("PIN must be exactly 4 digits.")
        settings = get_settings()
        reserved = {
            settings.admin_pin,
            settings.accounting_pin,
            settings.operations_pin,
        }
        if pin in reserved:
            raise ValueError("PIN conflicts with a reserved system PIN.")
    conn = get_connection()
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
        conn.close()
'''
    content = content.rstrip() + crud_block
    print('Patch 4 applied: CRUD functions appended')
else:
    print('Patch 4 already applied (skip)')

# Write out
with open(r'app\core\database.py', 'wb') as f:
    f.write(content.encode('utf-8'))

print('All patches complete. File written.')
