"""
V4 Independent CRM Local Database
Manages the SQLite connection and state machine for the local pipeline.
"""

import sqlite3
import json
import structlog
from datetime import datetime
from pathlib import Path

logger = structlog.get_logger("app.core.database")

DB_PATH = Path("truck_server.db")

def get_connection() -> sqlite3.Connection:
    """Get a SQLite connection with WAL mode enabled for concurrency."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Enable Write-Ahead Logging to allow concurrent read/writes between FastAPI and ARQ
    conn.execute("PRAGMA journal_mode=WAL;")
    # Ensure foreign keys are enforced if we add them later
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    """Initialize the jobs table if it does not exist."""
    conn = get_connection()
    try:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                homeowner_name TEXT NOT NULL,
                address_line1 TEXT NOT NULL,
                city TEXT NOT NULL,
                state TEXT NOT NULL,
                postal_code TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT,
                claim_number TEXT,
                insurer_name TEXT,
                status TEXT DEFAULT 'LEAD_CAPTURED',
                status_history TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        logger.info("database_initialized", db_path=str(DB_PATH))
    except Exception as e:
        logger.error("database_initialization_failed", error=str(e))
        raise
    finally:
        conn.close()

def update_job_status(job_id: str, new_status: str, note: str = ""):
    """
    Enforces logical state transitions and appends to the JSON status history.
    """
    conn = get_connection()
    try:
        # Get current status history
        cursor = conn.execute("SELECT status_history FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Job {job_id} not found.")

        history_str = row["status_history"]
        history = json.loads(history_str) if history_str else []

        # Create new history entry
        entry = {
            "status": new_status,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "note": note
        }
        history.append(entry)

        # Update DB
        conn.execute(
            "UPDATE jobs SET status = ?, status_history = ? WHERE id = ?",
            (new_status, json.dumps(history), job_id)
        )
        conn.commit()
        logger.info("job_status_updated", job_id=job_id, status=new_status)
    except Exception as e:
        logger.error("job_status_update_failed", job_id=job_id, error=str(e))
        raise
    finally:
        conn.close()
