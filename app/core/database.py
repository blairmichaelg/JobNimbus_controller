"""
V4 Independent CRM Local Database
Manages the SQLite connection and state machine for the local pipeline.
"""

from __future__ import annotations

import sqlite3
import json
import structlog
import uuid
from typing import Optional
from datetime import datetime
from pathlib import Path
from enum import Enum
import asyncio

from app.config import get_settings

logger = structlog.get_logger("app.core.database")

def get_db_path() -> Path:
    return Path(get_settings().DB_PATH)

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
    PIPELINE_FAILED = "PIPELINE_FAILED"

def get_connection() -> sqlite3.Connection:
    """Get a SQLite connection with WAL mode enabled for concurrency."""
    conn = sqlite3.connect(get_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Enable Write-Ahead Logging to allow concurrent read/writes between FastAPI and ARQ
    conn.execute("PRAGMA journal_mode=WAL;")
    # Ensure foreign keys are enforced if we add them later
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db() -> None:
    """Initialize the jobs table and associated schemas if they do not exist.
    
    Creates the jobs, material_orders, schedule, financials, and pricing tables.
    Also seeds the database with default pricing values.
    
    Raises:
        Exception: If database initialization fails.
    """
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
                inspector_name TEXT,
                inspection_date TIMESTAMP,
                inspection_notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Lightweight migration if jobs existed before inspection fields
        for col in ["inspector_name TEXT", "inspection_date TIMESTAMP", "inspection_notes TEXT"]:
            try:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass # Column already exists
        
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
                delivery_date TIMESTAMP,
                status TEXT NOT NULL,
                FOREIGN KEY(job_id) REFERENCES jobs(id)
            )
        ''')
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS financials (
                job_id TEXT PRIMARY KEY,
                revenue REAL NOT NULL DEFAULT 0.0,
                carrier_rcv REAL NOT NULL,
                material_cost REAL NOT NULL,
                labor_cost REAL NOT NULL,
                overhead_pct REAL NOT NULL,
                canvasser_commission_pct REAL NOT NULL,
                permits_fee REAL NOT NULL DEFAULT 0.0,
                FOREIGN KEY(job_id) REFERENCES jobs(id)
            )
        ''')
        
        # Lightweight migration if financials existed before permits_fee
        try:
            conn.execute("ALTER TABLE financials ADD COLUMN permits_fee REAL NOT NULL DEFAULT 0.0")
        except sqlite3.OperationalError:
            pass # Column already exists
            
        conn.execute('''
            CREATE TABLE IF NOT EXISTS job_documents (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                file_type TEXT NOT NULL,
                storage_path TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(job_id) REFERENCES jobs(id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS pricing (
                item_key TEXT PRIMARY KEY,
                default_rate REAL NOT NULL
            )
        ''')
        conn.commit()
        logger.info("database_initialized", db_path=str(get_db_path()))
        seed_default_pricing()
    except Exception as e:
        logger.error("database_initialization_failed", error=str(e))
        raise
    finally:
        conn.close()

def seed_default_pricing() -> None:
    """Seed the pricing table with baseline material/labor rates.
    
    Inserts default Wickham Roofing pricing values if they do not already exist.
    """
    conn = get_connection()
    try:
        # Default Wickham Roofing baselines
        baseline_pricing = [
            ("field_shingle_bundles", 105.0),
            ("starter_bundles", 45.0),
            ("ridge_cap_bundles", 55.0),
            ("ice_water_rolls", 80.0),
            ("underlayment_rolls", 65.0),
            ("drip_edge_pieces", 15.0),
            ("labor_per_sq", 85.0), # Example labor metric
        ]
        conn.executemany('''
            INSERT OR IGNORE INTO pricing (item_key, default_rate)
            VALUES (?, ?)
        ''', baseline_pricing)
        conn.commit()
    except Exception as e:
        logger.error("pricing_seed_failed", error=str(e))
    finally:
        conn.close()

def get_pricing_ledger() -> dict[str, float]:
    """Fetch all default rates from the pricing table.
    
    Returns:
        dict[str, float]: A dictionary mapping item keys to their default rates.
    """
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT item_key, default_rate FROM pricing")
        return {row["item_key"]: row["default_rate"] for row in cursor}
    except Exception as e:
        logger.error("failed_to_fetch_pricing", error=str(e))
        return {}
    finally:
        conn.close()

def update_job_status(job_id: str, new_status: str, note: str = "") -> None:
    """Enforces logical state transitions and appends to the JSON status history.

    Args:
        job_id (str): The unique identifier for the job.
        new_status (str): The new JobStatus to transition to.
        note (str, optional): An optional note to append to the status history. Defaults to "".
        
    Raises:
        ValueError: If the new_status is invalid or the job_id does not exist.
        Exception: If the database update fails.
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

        # Update DB with Optimistic Concurrency
        if history_str is None:
            cursor = conn.execute(
                "UPDATE jobs SET status = ?, status_history = ? WHERE id = ? AND status_history IS NULL",
                (new_status, json.dumps(history), job_id)
            )
        else:
            cursor = conn.execute(
                "UPDATE jobs SET status = ?, status_history = ? WHERE id = ? AND status_history = ?",
                (new_status, json.dumps(history), job_id, history_str)
            )
            
        if cursor.rowcount == 0:
            raise RuntimeError("Concurrent status update detected")
            
        conn.commit()
        logger.info("job_status_updated", job_id=job_id, status=new_status)
    except Exception as e:
        logger.error("job_status_update_failed", job_id=job_id, error=str(e))
        raise
    finally:
        conn.close()

def upsert_financials(
    job_id: str, 
    revenue: float, 
    carrier_rcv: float, 
    material_cost: float, 
    labor_cost: float, 
    overhead_pct: float, 
    canvasser_commission_pct: float,
    permits_fee: float = 0.0
) -> None:
    """Upsert financial pre-build parameters into the financials table.

    Args:
        job_id (str): The unique identifier for the job.
        revenue (float): Total contract price or revenue.
        carrier_rcv (float): The carrier's Replacement Cost Value.
        material_cost (float): Total material cost.
        labor_cost (float): Total labor cost.
        overhead_pct (float): Overhead percentage.
        canvasser_commission_pct (float): Commission percentage.
        permits_fee (float): Cost of permits.
        
    Raises:
        Exception: If the upsert operation fails.
    """
    conn = get_connection()
    try:
        conn.execute('''
            INSERT OR REPLACE INTO financials 
            (job_id, revenue, carrier_rcv, material_cost, labor_cost, overhead_pct, canvasser_commission_pct, permits_fee)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (job_id, revenue, carrier_rcv, material_cost, labor_cost, overhead_pct, canvasser_commission_pct, permits_fee))
        conn.commit()
        logger.info("financials_upserted", job_id=job_id)
    except Exception as e:
        logger.error("financials_upsert_failed", job_id=job_id, error=str(e))
        raise
    finally:
        conn.close()

def insert_material_order(job_id: str, supplier_name: str, delivery_date: str, bom_json: str) -> None:
    """Insert a material order and generate a UUID for the record.

    Args:
        job_id (str): The unique identifier for the job.
        supplier_name (str): The name of the material supplier.
        delivery_date (str): The requested delivery date.
        bom_json (str): The bill of materials encoded as a JSON string.
        
    Raises:
        Exception: If the database insertion fails.
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

def insert_schedule(job_id: str, crew_name: str, install_date: str, delivery_date: str, status: str) -> None:
    """Insert a production schedule and generate a UUID for the record.

    Args:
        job_id (str): The unique identifier for the job.
        crew_name (str): The assigned installation crew.
        install_date (str): The scheduled installation date.
        delivery_date (str): The scheduled material delivery date.
        status (str): The current schedule status.
        
    Raises:
        Exception: If the database insertion fails.
    """
    conn = get_connection()
    try:
        schedule_id = str(uuid.uuid4())
        conn.execute('''
            INSERT INTO schedule (id, job_id, crew_name, install_date, delivery_date, status)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (schedule_id, job_id, crew_name, install_date, delivery_date, status))
        conn.commit()
        logger.info("schedule_inserted", schedule_id=schedule_id, job_id=job_id)
    except Exception as e:
        logger.error("schedule_insert_failed", job_id=job_id, error=str(e))
        raise
    finally:
        conn.close()

async def backup_database() -> None:
    """Safely creates a hot snapshot of the SQLite WAL database.
    
    Saves to data/backups/crm_backup_{timestamp}.db.
    Enforces a backup retention limit based on application settings.
    Runs asynchronously to avoid locking the event loop.
    """
    def _do_backup():
        backup_dir = Path("data/backups")
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"crm_backup_{timestamp}.db"
        
        conn = get_connection()
        try:
            # VACUUM INTO safely copies a live DB without locking it down
            conn.execute(f"VACUUM INTO '{backup_path}';")
            logger.info("database_backup_created", path=str(backup_path))
            
            # Enforce backup retention policy
            limit = get_settings().BACKUP_RETENTION_LIMIT
            backups = sorted(backup_dir.glob("crm_backup_*.db"), key=lambda p: p.stat().st_mtime)
            while len(backups) > limit:
                oldest = backups.pop(0)
                try:
                    oldest.unlink()
                    logger.info("old_backup_pruned", path=str(oldest))
                except Exception as prune_err:
                    logger.warning("failed_to_prune_backup", path=str(oldest), error=str(prune_err))
                    
        except Exception as e:
            logger.error("database_backup_failed", error=str(e))
        finally:
            conn.close()

    await asyncio.to_thread(_do_backup)

def insert_job_document(job_id: str, filename: str, file_type: str, storage_path: str) -> str:
    """Insert a new document tracking record into the vault."""
    conn = get_connection()
    doc_id = str(uuid.uuid4())
    try:
        conn.execute(
            "INSERT INTO job_documents (id, job_id, filename, file_type, storage_path) VALUES (?, ?, ?, ?, ?)",
            (doc_id, job_id, filename, file_type, storage_path)
        )
        conn.commit()
        return doc_id
    except Exception as e:
        logger.error("insert_job_document_failed", error=str(e))
        raise
    finally:
        conn.close()

def get_financials(job_id: str) -> Optional[dict]:
    """Fetch the raw financial parameters for a given job."""
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT * FROM financials WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error("get_financials_failed", error=str(e))
        raise
    finally:
        conn.close()

def get_monthly_financials(month: int, year: int) -> list[dict]:
    """Aggregate all INVOICED or CLOSED jobs for a specific month and year."""
    conn = get_connection()
    try:
        cursor = conn.execute("""
            SELECT j.id, j.homeowner_name, j.status, f.revenue, f.material_cost, 
                   f.labor_cost, f.overhead_pct, f.canvasser_commission_pct, f.permits_fee
            FROM jobs j
            JOIN financials f ON j.id = f.job_id
            WHERE j.status IN ('INVOICED', 'CLOSED')
            AND cast(strftime('%m', j.created_at) as integer) = ?
            AND cast(strftime('%Y', j.created_at) as integer) = ?
        """, (month, year))
        return [dict(r) for r in cursor]
    except Exception as e:
        logger.error("get_monthly_financials_failed", error=str(e))
        return []
    finally:
        conn.close()

def update_job_metadata(job_id: str, inspector_name: str, inspection_date: str, inspection_notes: str) -> None:
    """Update inspection-related metadata for a specific job."""
    conn = get_connection()
    try:
        conn.execute('''
            UPDATE jobs 
            SET inspector_name = ?, inspection_date = ?, inspection_notes = ? 
            WHERE id = ?
        ''', (inspector_name, inspection_date, inspection_notes, job_id))
        conn.commit()
        logger.info("job_metadata_updated", job_id=job_id)
    except Exception as e:
        logger.error("update_job_metadata_failed", job_id=job_id, error=str(e))
        raise
    finally:
        conn.close()
