import shutil
import sqlite3
import os
import hashlib
import glob
from pathlib import Path
from app.core.backup import backup_database
from app.core.database import get_db_path

def hash_db_contents(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get all tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    tables = [row[0] for row in cursor.fetchall() if row[0] != 'sqlite_sequence']
    
    all_data_str = ""
    total_rows = 0
    
    print(f"Hashing {len(tables)} tables: {', '.join(tables)}")
    
    for table in tables:
        # Find primary key for deterministic ordering
        cursor.execute(f"PRAGMA table_info({table})")
        columns = cursor.fetchall()
        pk_cols = [col[1] for col in columns if col[5] > 0]
        order_clause = f"ORDER BY {', '.join(pk_cols)}" if pk_cols else "ORDER BY rowid"
        
        cursor.execute(f"SELECT * FROM {table} {order_clause}")
        rows = cursor.fetchall()
        total_rows += len(rows)
        all_data_str += str(rows)
        
    conn.close()
    
    return hashlib.sha256(all_data_str.encode('utf-8')).hexdigest(), total_rows, len(tables)

def run_test():
    original_db = "data/wickham.db"
    staging_db = "data/wickham_staging.db"
    
    # Create a staging db by copying the original
    shutil.copy2(original_db, staging_db)
    print("1. Staging DB cloned from wickham.db")
    
    # Checksum before
    pre_hash, pre_total_rows, pre_num_tables = hash_db_contents(staging_db)
    print(f"Pre-backup hash: {pre_hash} (Rows: {pre_total_rows}, Tables: {pre_num_tables})")
    
    # Temporarily override get_db_path to use staging_db
    import app.core.backup
    app.core.backup.get_db_path = lambda: Path(staging_db)
    
    # 2. Run backup process
    backup_database()
    
    # Find the backup file
    backup_dir = Path("data/backups")
    backups = glob.glob(str(backup_dir / "wickham_staging_*.db"))
        
    # Get the latest backup
    backups.sort(key=os.path.getmtime)
    backup_file = backups[-1]
    print(f"2. Backup completed: {backup_file}")
    
    # 3. Deliberately delete staging DB
    os.remove(staging_db)
    print("3. Staging DB deleted/corrupted")
    
    # 4. Restore from backup
    shutil.copy2(backup_file, staging_db)
    print(f"4. Restored DB to: {staging_db}")
    
    # Checksum after
    post_hash, post_total_rows, post_num_tables = hash_db_contents(staging_db)
    print(f"Post-restore hash: {post_hash} (Rows: {post_total_rows}, Tables: {post_num_tables})")
    
    if pre_hash == post_hash:
        print("\nSUCCESS: 100% Data Integrity Verified!")
    else:
        print("\nFAILURE: Checksums do not match.")

if __name__ == "__main__":
    run_test()
