import sys
import os
import uuid
import sqlite3

# Ensure project root is in sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import get_connection

def bootstrap():
    conn = get_connection()
    jobs = [
        (str(uuid.uuid4()), "John Doe", "123 Main St", "Atlanta", "GA", "30301", "555-0100", "john@example.com", "CLM-001", "StateFarm", "LEAD_CAPTURED"),
        (str(uuid.uuid4()), "Jane Smith", "456 Oak Ln", "Atlanta", "GA", "30302", "555-0101", "jane@example.com", "CLM-002", "Allstate", "INSPECTION_COMPLETED"),
        (str(uuid.uuid4()), "Bob Johnson", "789 Pine Rd", "Decatur", "GA", "30030", "555-0102", "bob@example.com", "CLM-003", "Geico", "FINAL_INSPECTION"),
        (str(uuid.uuid4()), "Alice Williams", "321 Cedar Dr", "Marietta", "GA", "30060", "555-0103", "alice@example.com", "CLM-004", "Travelers", "MATERIAL_ORDERED"),
        (str(uuid.uuid4()), "Charlie Brown", "654 Elm St", "Roswell", "GA", "30075", "555-0104", "charlie@example.com", "CLM-005", "Liberty Mutual", "LEAD_CAPTURED"),
    ]
    
    try:
        conn.executemany('''
            INSERT OR IGNORE INTO jobs (id, homeowner_name, address_line1, city, state, postal_code, phone, email, claim_number, insurer_name, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', jobs)
        conn.commit()
        print(f"Successfully bootstrapped {len(jobs)} mock jobs for the demo.")
    except Exception as e:
        print(f"Failed to bootstrap data: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    bootstrap()
