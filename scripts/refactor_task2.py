import os
import re
from pathlib import Path

def main():
    root = Path("c:/Users/Michael/projects/JobNimbus_controller")
    db_path = root / "app" / "core" / "database.py"
    migrations_dir = root / "app" / "core" / "migrations"
    migrations_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Read database.py
    content = db_path.read_text()
    
    # Extract init_db block to replace it
    match = re.search(r'def init_db\(\) -> None:(.*?)def seed_default_pricing\(\) -> None:', content, re.DOTALL)
    if not match:
        print("Could not find init_db block")
        return
        
    init_db_full_body = match.group(0)
    # The actual body inside init_db
    init_db_body = match.group(1)
    
    # Clean up init_db body to create up(conn) for 0001_initial_schema.py
    up_code = """import sqlite3
import structlog

logger = structlog.get_logger("app.core.migrations.0001_initial_schema")

def up(conn: sqlite3.Connection) -> None:
    \"\"\"Apply the initial schema.\"\"\"
    logger.info("applying_migration", version=1, name="initial_schema")
""" + init_db_body.replace("conn = get_connection()", "").replace("try:\n        conn.execute(\"BEGIN IMMEDIATE\")", "try:\n        pass").replace("        logger.info(\"database_initialized\", db_path=str(get_db_path()))", "        pass")
    
    # Write to 0001_initial_schema.py
    migration_file = migrations_dir / "0001_initial_schema.py"
    migration_file.write_text(up_code)
    
    # 2. Add run_migrations and PRAGMA consolidation to database.py
    
    run_migrations_code = """def run_migrations() -> None:
    \"\"\"Run versioned migrations.\"\"\"
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute('''
            CREATE TABLE IF NOT EXISTS schema_version (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                version INTEGER NOT NULL DEFAULT 0,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.execute("INSERT OR IGNORE INTO schema_version (id, version) VALUES (1, 0)")
        
        row = conn.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
        current_version = row["version"] if row else 0
        
        # Apply migrations
        if current_version < 1:
            import importlib
            m1 = importlib.import_module("app.core.migrations.0001_initial_schema")
            m1.up(conn)
            
            # Since seed logic was removed from up(), do it here
            seed_default_pricing()
            seed_supplement_rules()
            
            conn.execute("UPDATE schema_version SET version = 1, applied_at = CURRENT_TIMESTAMP WHERE id = 1")
            
        conn.execute("COMMIT")
        logger.info("migrations_applied", current_version=current_version, target_version=1)
    except Exception as e:
        conn.execute("ROLLBACK")
        logger.error("migration_failed", error=str(e))
        raise
    finally:
        conn.close()

def seed_default_pricing() -> None:"""

    new_content = content.replace(init_db_full_body, run_migrations_code)

    old_get_connection = """def get_connection() -> sqlite3.Connection:
    \"\"\"Get a SQLite connection with WAL mode enabled for concurrency.\"\"\"
    conn = sqlite3.connect(get_db_path(), check_same_thread=False, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None  # Explicit transaction control
    
    # Pragma injection for maximum WAL concurrency
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA temp_store=MEMORY;")
    conn.execute("PRAGMA mmap_size=268435456;")
    conn.execute("PRAGMA busy_timeout=15000;")
    
    return conn"""

    new_get_connection = """def _configure_connection(conn: sqlite3.Connection) -> None:
    \"\"\"Configure PRAGMA settings for maximum WAL concurrency.\"\"\"
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA temp_store=MEMORY;")
    conn.execute("PRAGMA mmap_size=268435456;")
    conn.execute("PRAGMA busy_timeout=15000;")

def get_connection() -> sqlite3.Connection:
    \"\"\"Get a SQLite connection with WAL mode enabled for concurrency.\"\"\"
    conn = sqlite3.connect(get_db_path(), check_same_thread=False, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None  # Explicit transaction control
    _configure_connection(conn)
    return conn"""

    new_content = new_content.replace(old_get_connection, new_get_connection)
    
    # Fix backup logic
    backup_old = """            # VACUUM INTO safely copies a live DB without locking it down
            conn.execute(f"VACUUM INTO '{backup_path}';")"""
            
    backup_new = """            with sqlite3.connect(get_db_path()) as source_conn:
                with sqlite3.connect(backup_path) as dest_conn:
                    source_conn.backup(dest_conn)"""
            
    new_content = new_content.replace(backup_old, backup_new)
    # also remove conn = get_connection() from _do_backup()
    new_content = new_content.replace("        conn = get_connection()\\n        try:\\n", "        try:\\n")
    
    # Rename init_db to run_migrations in app/main.py if used
    main_path = root / "app" / "main.py"
    if main_path.exists():
        main_content = main_path.read_text()
        main_content = main_content.replace("from app.core.database import init_db", "from app.core.database import run_migrations as init_crm_db")
        main_content = main_content.replace("init_db()", "init_crm_db()")
        main_path.write_text(main_content)
        
    db_path.write_text(new_content)
    print("Done")

if __name__ == "__main__":
    main()
