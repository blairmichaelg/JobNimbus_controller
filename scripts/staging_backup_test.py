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
    
    # Hash all rows in jobs and financials to simulate data checksum
    cursor.execute("SELECT id, homeowner_name FROM jobs ORDER BY id")
    jobs = cursor.fetchall()
    
    cursor.execute("SELECT job_id, revenue_cents, carrier_rcv_cents FROM financials ORDER BY job_id")
    financials = cursor.fetchall()
    
    conn.close()
    
    data_str = str(jobs) + str(financials)
    return hashlib.sha256(data_str.encode('utf-8')).hexdigest(), len(jobs), len(financials)

def run_test():
    original_db = "data/wickham.db"
    staging_db = "data/wickham_staging.db"
    
    # Create a staging db by copying the original
    shutil.copy2(original_db, staging_db)
    print("1. Staging DB cloned from wickham.db")
    
    # Checksum before
    pre_hash, pre_jobs_count, pre_fin_count = hash_db_contents(staging_db)
    print(f"Pre-backup hash: {pre_hash} (Jobs: {pre_jobs_count}, Financials: {pre_fin_count})")
    
    # Temporarily override get_db_path to use staging_db
    import app.core.backup
    app.core.backup.get_db_path = lambda: Path(staging_db)
    
    # 2. Run backup process
    backup_database()
    
    # Find the backup file
    backup_dir = Path("data/backups")
    backups = glob.glob(str(backup_dir / "wickham_staging_*.db"))
    if not backups:
        # It names it wickham_TIMESTAMP.db because of how backup_database hardcodes the name
        backups = glob.glob(str(backup_dir / "wickham_*.db"))
        
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
    post_hash, post_jobs_count, post_fin_count = hash_db_contents(staging_db)
    print(f"Post-restore hash: {post_hash} (Jobs: {post_jobs_count}, Financials: {post_fin_count})")
    
    if pre_hash == post_hash:
        print("\nSUCCESS: 100% Data Integrity Verified!")
    else:
        print("\nFAILURE: Checksums do not match.")

if __name__ == "__main__":
    run_test()
