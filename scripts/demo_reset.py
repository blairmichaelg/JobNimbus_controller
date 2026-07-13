import os
import sqlite3
from pathlib import Path

# Connect to DB
db_path = "truck_server.db"

# Directories to clear
directories_to_clear = [
    "signed_agreements",
    "field_photos",
    "generated_exports",
    "field_docs"
]

def main():
    print("WARNING: This will wipe all demo data from the database and delete generated files.")
    confirm = input("Are you sure you want to wipe the database for the demo? (y/n): ")
    if confirm.lower() != 'y':
        print("Aborted.")
        return

    # Delete records from tables
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        tables = [
            "jobs",
            "job_agreements",
            "storm_verifications",
            "supplement_flags",
            "supplements"
        ]
        
        for table in tables:
            try:
                cursor.execute(f"DELETE FROM {table}")
                print(f"Cleared table: {table}")
            except sqlite3.OperationalError as e:
                print(f"Skipped {table}: {e}")
        
        conn.commit()
        conn.close()
    else:
        print(f"Database {db_path} not found.")

    # Delete files in directories
    for dir_name in directories_to_clear:
        dir_path = Path(dir_name)
        if dir_path.exists() and dir_path.is_dir():
            count = 0
            for file_path in dir_path.iterdir():
                if file_path.is_file() and file_path.name != ".gitkeep":
                    file_path.unlink()
                    count += 1
            print(f"Cleared {count} files from {dir_name}/")
        else:
            print(f"Directory {dir_name}/ not found, skipping.")

    print("Demo reset complete! Clean slate ready.")

if __name__ == "__main__":
    main()
