"""
V4 Independent CRM Local Database
Manages the SQLite connection and state machine for the local pipeline.
"""

import sqlite3
import json
import structlog
from datetime import datetime
from pathlib import Path
from enum import Enum
import uuid

logger = structlog.get_logger("app.core.database")

DB_PATH = Path("truck_server.db")

class JobStatus(str, Enum):
    LEAD_CAPTURED = "LEAD_CAPTURED"
    PHOTOS_UPLOADED = "PHOTOS_UPLOADED"
    EV_PARSED = "EV_PARSED"
    SUPPLEMENT_SUBMITTED = "SUPPLEMENT_SUBMITTED"
    SCOPE_APPROVED = "SCOPE_APPROVED"
    MATERIAL_ORDERED = "MATERIAL_ORDERED"
    INSTALL_SCHEDULED = "INSTALL_SCHEDULED"
    INSTALL_COMPLETED = "INSTALL_COMPLETED"
    FINAL_INSPECTION = "FINAL_INSPECTION"
    INVOICED = "INVOICED"
    PAYMENT_RECEIVED = "PAYMENT_RECEIVED"
    CLOSED = "CLOSED"

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
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS material_orders (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                supplier_name TEXT NOT NULL,
                delivery_date TIMESTAMP,
                bom_json TEXT NOT NULL,
                FOREIGN KEY(job_id) REFERENCES jobs(id)
            )
        ''')
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS schedule (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                crew_name TEXT NOT NULL,
                install_date TIMESTAMP,
                status TEXT NOT NULL,
                FOREIGN KEY(job_id) REFERENCES jobs(id)
            )
        ''')
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS financials (
                job_id TEXT PRIMARY KEY,
                carrier_rcv REAL NOT NULL,
                material_cost REAL NOT NULL,
                labor_cost REAL NOT NULL,
                overhead_pct REAL NOT NULL,
                canvasser_commission_pct REAL NOT NULL,
                FOREIGN KEY(job_id) REFERENCES jobs(id)
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
    try:
        # Validate against Enum
        JobStatus(new_status)
    except ValueError:
        raise ValueError(f"Invalid job status: {new_status}")

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

def upsert_financials(job_id: str, carrier_rcv: float, material_cost: float, labor_cost: float, overhead_pct: float, canvasser_commission_pct: float):
    """
    Upsert financial pre-build parameters into the financials table.
    """
    conn = get_connection()
    try:
        conn.execute('''
            INSERT INTO financials (job_id, carrier_rcv, material_cost, labor_cost, overhead_pct, canvasser_commission_pct)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                carrier_rcv=excluded.carrier_rcv,
                material_cost=excluded.material_cost,
                labor_cost=excluded.labor_cost,
                overhead_pct=excluded.overhead_pct,
                canvasser_commission_pct=excluded.canvasser_commission_pct
        ''', (job_id, carrier_rcv, material_cost, labor_cost, overhead_pct, canvasser_commission_pct))
        conn.commit()
        logger.info("financials_upserted", job_id=job_id)
    except Exception as e:
        logger.error("financials_upsert_failed", job_id=job_id, error=str(e))
        raise
    finally:
        conn.close()

def insert_material_order(job_id: str, supplier_name: str, delivery_date: str, bom_json: str):
    """
    Insert a material order and generate a UUID for the record.
    """
    conn = get_connection()
    try:
        order_id = str(uuid.uuid4())
        conn.execute('''
            INSERT INTO material_orders (id, job_id, supplier_name, delivery_date, bom_json)
            VALUES (?, ?, ?, ?, ?)
        ''', (order_id, job_id, supplier_name, delivery_date, bom_json))
        conn.commit()
        logger.info("material_order_inserted", order_id=order_id, job_id=job_id)
    except Exception as e:
        logger.error("material_order_insert_failed", job_id=job_id, error=str(e))
        raise
    finally:
        conn.close()
