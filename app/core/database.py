"""
V4 Independent CRM Local Database
Manages the SQLite connection and state machine for the local pipeline.
"""

from __future__ import annotations

import sqlite3
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
    return Path(get_settings().get_db_path)

class JobStatus(str, Enum):
    # PROCESSING STATES (ARQ workers may write these autonomously)
    LEAD_CAPTURED = "LEAD_CAPTURED"
    CONTINGENCY_SIGNED = "CONTINGENCY_SIGNED"
    CLAIM_FILED = "CLAIM_FILED"
    ADJUSTER_MEETING_COMPLETED = "ADJUSTER_MEETING_COMPLETED"
    PHOTOS_UPLOADED = "PHOTOS_UPLOADED"
    EV_PARSED = "EV_PARSED"
    STATEMENT_OF_LOSS_RECEIVED = "STATEMENT_OF_LOSS_RECEIVED"
    PENDING_OPERATOR_REVIEW = "PENDING_OPERATOR_REVIEW"
    PENDING_MANUAL_REVIEW = "PENDING_MANUAL_REVIEW"
    PIPELINE_FAILED = "PIPELINE_FAILED"
    INSPECTION_FAILED = "INSPECTION_FAILED"

    # BUSINESS STATES (Operator-only manual gates)
    SUPPLEMENT_GENERATED = "SUPPLEMENT_GENERATED"
    SUPPLEMENT_SUBMITTED = "SUPPLEMENT_SUBMITTED"
    SUPPLEMENT_DENIED = "SUPPLEMENT_DENIED"
    SUPPLEMENT_APPROVED = "SUPPLEMENT_APPROVED"
    SCOPE_APPROVED = "SCOPE_APPROVED"
    MATERIAL_ORDERED = "MATERIAL_ORDERED"
    MATERIALS_ON_SITE = "MATERIALS_ON_SITE"
    INSTALL_SCHEDULED = "INSTALL_SCHEDULED"
    INSTALL_COMPLETED = "INSTALL_COMPLETED"
    INSPECTION_COMPLETED = "INSPECTION_COMPLETED"
    FINAL_INSPECTION = "FINAL_INSPECTION"
    INVOICED = "INVOICED"
    PAYMENT_RECEIVED = "PAYMENT_RECEIVED"
    CLOSED = "CLOSED"

    @classmethod
    def is_operator_gate(cls, status: "JobStatus") -> bool:
        _OPERATOR_GATES = {
            cls.SUPPLEMENT_GENERATED, cls.SUPPLEMENT_SUBMITTED,
            cls.SUPPLEMENT_DENIED, cls.SUPPLEMENT_APPROVED,
            cls.SCOPE_APPROVED, cls.MATERIAL_ORDERED,
            cls.MATERIALS_ON_SITE, cls.INSTALL_SCHEDULED,
            cls.INSTALL_COMPLETED, cls.INSPECTION_COMPLETED,
            cls.FINAL_INSPECTION, cls.INVOICED,
            cls.PAYMENT_RECEIVED, cls.CLOSED
        }
        return status in _OPERATOR_GATES

def get_connection() -> sqlite3.Connection:
    """Get a SQLite connection with WAL mode enabled for concurrency."""
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
        conn.execute("BEGIN IMMEDIATE")
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
                ice_barrier_required BOOLEAN,
                jurisdiction_code_version TEXT DEFAULT '2021_IRC',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Lightweight migration if jobs existed before inspection fields
        for col in ["inspector_name TEXT", "inspection_date TIMESTAMP", "inspection_notes TEXT",
                    "job_type TEXT DEFAULT 'INSURANCE'", "policy_type TEXT", "adjuster_name TEXT", "adjuster_phone TEXT",
                    "adjuster_email TEXT", "canvasser_name TEXT", "qbo_customer_id TEXT",
                    "ice_barrier_required BOOLEAN", "jurisdiction_code_version TEXT DEFAULT '2021_IRC'", "invoiced_at TIMESTAMP"]:
            try:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass # Column already exists
                
        # Operations material confirmation flags on the jobs table
        for col in [
            "materials_ordered INTEGER NOT NULL DEFAULT 0",
            "materials_on_site INTEGER NOT NULL DEFAULT 0",
        ]:
            try:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass  # Column already exists
                
        # Operations material confirmation flags on the jobs table
        for col in [
            "materials_ordered INTEGER NOT NULL DEFAULT 0",
            "materials_on_site INTEGER NOT NULL DEFAULT 0",
        ]:
            try:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass  # Column already exists
                
        # Phase 5: Operations columns on the jobs table
        for col in [
            "supplement_sent_at TIMESTAMP",
            "acv_received INTEGER DEFAULT 0",
            "supplement_received INTEGER DEFAULT 0",
            "acv_received_at TIMESTAMP",
            "supplement_received_at TIMESTAMP",
            "pipeline_error_message TEXT",
            "ev_total_area_sf REAL",
            "ev_predominant_pitch TEXT",
            "ev_ridge_lf REAL",
            "ev_hip_lf REAL",
            "ev_valley_lf REAL",
            "ev_eaves_lf REAL",
            "ev_rakes_lf REAL"
        ]:
            try:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass
        
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
        
        # Lightweight migration if financials existed before permits_fee and others
        for col in ["permits_fee REAL NOT NULL DEFAULT 0.0", "deductible REAL DEFAULT 0.0",
                    "acv_payment REAL DEFAULT 0.0", "recoverable_depreciation REAL DEFAULT 0.0",
                    "qbo_invoice_id TEXT"]:
            try:
                conn.execute(f"ALTER TABLE financials ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass # Column already exists
                
        # Idempotency lock on financials for QBO batch export
        try:
            conn.execute(
                "ALTER TABLE financials ADD COLUMN "
                "qbo_exported INTEGER NOT NULL DEFAULT 0"
            )
            conn.execute(
                "ALTER TABLE financials ADD COLUMN "
                "qbo_exported_at TIMESTAMP"
            )
        except sqlite3.OperationalError:
            pass
            
        conn.execute('''
            CREATE TABLE IF NOT EXISTS qbo_credentials (
                realm_id TEXT PRIMARY KEY,
                access_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                token_expires_at TIMESTAMP NOT NULL,
                refresh_expires_at TIMESTAMP NOT NULL
            )
        ''')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS job_agreements (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                type TEXT NOT NULL,
                pdf_path TEXT,
                signature_image_path TEXT,
                signed_at TIMESTAMP NOT NULL,
                signed_by_name TEXT,
                signed_by_ip TEXT,
                user_agent TEXT,
                FOREIGN KEY(job_id) REFERENCES jobs(id)
            )
        ''')
            
        conn.execute('''
            CREATE TABLE IF NOT EXISTS supplements (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                round_number INTEGER NOT NULL,
                pdf_path TEXT,
                submitted_at TIMESTAMP,
                status TEXT,
                FOREIGN KEY(job_id) REFERENCES jobs(id)
            )
        ''')
            
        conn.execute('''
            CREATE TABLE IF NOT EXISTS qbo_mappings (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                qbo_customer_id TEXT,
                qbo_invoice_id TEXT,
                FOREIGN KEY(job_id) REFERENCES jobs(id)
            )
        ''')
            
        conn.execute('''
            CREATE TABLE IF NOT EXISTS job_documents (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                file_type TEXT NOT NULL,
                storage_path TEXT NOT NULL,
                sha256_hash TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(job_id) REFERENCES jobs(id)
            )
        ''')
        
        # Lightweight migration for job_documents sha256_hash
        try:
            conn.execute("ALTER TABLE job_documents ADD COLUMN sha256_hash TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_job_documents_hash ON job_documents(job_id, sha256_hash)")
        except sqlite3.OperationalError:
            pass # Column already exists
            
        conn.execute('''
            CREATE TABLE IF NOT EXISTS supplement_reports (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL REFERENCES jobs(id),
                report_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_supplement_reports_job "
            "ON supplement_reports(job_id, created_at DESC)"
        )
            
        conn.execute('''
            CREATE TABLE IF NOT EXISTS ai_usage_logs (
                id TEXT PRIMARY KEY,
                job_id TEXT,
                tokens_used INTEGER NOT NULL,
                model_name TEXT NOT NULL,
                operation_type TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS pricing (
                item_key TEXT PRIMARY KEY,
                default_rate REAL NOT NULL
            )
        ''')
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS storm_verifications (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                loss_date TIMESTAMP NOT NULL,
                event_type TEXT NOT NULL,
                magnitude REAL,
                begin_lat REAL NOT NULL,
                begin_lon REAL NOT NULL,
                distance_miles REAL,
                match_confidence TEXT NOT NULL,
                FOREIGN KEY(job_id) REFERENCES jobs(id)
            )
        ''')
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS supplement_rules (
                id TEXT PRIMARY KEY,
                parent_code TEXT NOT NULL,
                required_child_code TEXT NOT NULL,
                citation_text TEXT NOT NULL,
                citation_type TEXT NOT NULL CHECK(citation_type IN ('IRC', 'MFG_SPEC', 'INTERNAL_POLICY')),
                trigger_logic_name TEXT NOT NULL,
                climate_dependent BOOLEAN DEFAULT 0
            )
        ''')
        
        try:
            conn.execute("ALTER TABLE supplement_rules ADD COLUMN climate_dependent BOOLEAN DEFAULT 0")
        except sqlite3.OperationalError:
            pass # Column already exists
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS supplement_flags (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                rule_id TEXT NOT NULL,
                triggered INTEGER NOT NULL DEFAULT 0,
                quantity_delta REAL NOT NULL DEFAULT 0.0,
                notes TEXT,
                FOREIGN KEY(job_id) REFERENCES jobs(id),
                FOREIGN KEY(rule_id) REFERENCES supplement_rules(id)
            )
        ''')
        
        # STATE MACHINE V2 MIGRATION NOTE:
        # JobStatus.PENDING_OPERATOR_REVIEW and MATERIALS_ON_SITE are new 
        # TEXT values. Existing rows are unaffected. No ALTER TABLE required.
        # The is_operator_gate() classmethod enforces the two-track boundary
        # at the application layer, not the DB layer.
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS job_tasks (
                job_id TEXT,
                task_type TEXT,
                phase TEXT CHECK(phase IN ('queued','running','completed','failed')),
                last_error TEXT,
                PRIMARY KEY(job_id, task_type)
            )
        ''')
        
        conn.execute("CREATE INDEX IF NOT EXISTS idx_job_docs_job ON job_documents(job_id)")
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_job_docs_hash ON job_documents(job_id, sha256_hash)")
        except sqlite3.OperationalError:
            pass
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_supp_flags_unique ON supplement_flags(job_id, rule_id)")

        conn.execute('''
            CREATE VIEW IF NOT EXISTS live_material_board AS
            SELECT 
                j.id as job_id,
                j.homeowner_name,
                j.status,
                m.supplier_name,
                m.delivery_date,
                CAST(json_extract(m.bom_json, '$.total_squares') * 1.15 + 0.99 AS INTEGER) AS shingle_squares_required,
                CAST((json_extract(m.bom_json, '$.eaves_lf') + json_extract(m.bom_json, '$.valleys_lf')) / 66.0 + 0.99 AS INTEGER) AS ice_and_water_rolls,
                CAST((json_extract(m.bom_json, '$.eaves_lf') + json_extract(m.bom_json, '$.rakes_lf')) / 10.0 + 0.99 AS INTEGER) AS drip_edge_pieces_10ft,
                CAST((json_extract(m.bom_json, '$.eaves_lf') + json_extract(m.bom_json, '$.rakes_lf')) / 100.0 + 0.99 AS INTEGER) AS starter_bundles
            FROM jobs j
            JOIN material_orders m ON j.id = m.job_id
        ''')
        
        for col in ["carrier_initial_rcv REAL", "carrier_supplemented_rcv REAL"]:
            try:
                conn.execute(f"ALTER TABLE financials ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass
                
        conn.execute('''
            CREATE VIEW IF NOT EXISTS financial_delta_view AS
            SELECT 
                j.id as job_id,
                j.homeowner_name,
                f.carrier_initial_rcv,
                f.carrier_supplemented_rcv,
                f.revenue,
                (f.carrier_supplemented_rcv - f.carrier_initial_rcv) AS carrier_rcv_delta,
                (f.revenue - f.carrier_supplemented_rcv) AS contractor_over_carrier
            FROM jobs j
            JOIN financials f ON j.id = f.job_id
        ''')

        conn.execute("COMMIT")
        logger.info("database_initialized", db_path=str(get_db_path()))
        seed_default_pricing()
        seed_supplement_rules()
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
        conn.execute("BEGIN IMMEDIATE")
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
        conn.execute("COMMIT")
    except Exception as e:
        logger.error("pricing_seed_failed", error=str(e))

def seed_supplement_rules() -> None:
    """Seed the supplement_rules table with baseline rules."""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        baseline_rules = [
            (str(uuid.uuid4()), "RFG 300S", "RFG START", "Manufacturer Shingle High-Wind Installation Specifications", "MFG_SPEC", "eval_rfg_start", False),
            (str(uuid.uuid4()), "RFG 300S", "RFG DRIP", "IRC R905.2.8.5", "IRC", "eval_rfg_drip", False),
            (str(uuid.uuid4()), "RFG 300S", "RFG IWS", "IRC R905.1.2", "IRC", "eval_rfg_iws", True),
            (str(uuid.uuid4()), "RFG TEAR", "DMO PU", "Debris Haul-off and Tonnage Regulatory Compliance", "INTERNAL_POLICY", "eval_dmo_pu", False)
        ]
        conn.executemany('''
            INSERT INTO supplement_rules (id, parent_code, required_child_code, citation_text, citation_type, trigger_logic_name, climate_dependent)
            SELECT ?, ?, ?, ?, ?, ?, ?
            WHERE NOT EXISTS (
                SELECT 1 FROM supplement_rules 
                WHERE parent_code = ? AND required_child_code = ?
            )
        ''', [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[1], r[2]) for r in baseline_rules])
        conn.execute("COMMIT")
    except Exception as e:
        logger.error("supplement_rules_seed_failed", error=str(e))
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
        conn.execute("BEGIN IMMEDIATE")
        # Get current status history
        cursor = conn.execute("SELECT status, status_history FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Job {job_id} not found.")

        current_status = row["status"]

        # ---------------------------------------------------------
        # STATE MACHINE ENFORCEMENT
        # ---------------------------------------------------------
        if new_status == JobStatus.MATERIAL_ORDERED:
            fin_cursor = conn.execute("SELECT revenue FROM financials WHERE job_id = ?", (job_id,))
            if not fin_cursor.fetchone():
                raise RuntimeError("ILLEGAL TRANSITION: Cannot order materials without calculated financials.")
        elif new_status == JobStatus.INSTALL_SCHEDULED:
            sched_cursor = conn.execute(
                "SELECT status FROM jobs WHERE id = ?", (job_id,)
            )
            row = sched_cursor.fetchone()
            if not row or row["status"] != JobStatus.MATERIALS_ON_SITE:
                raise RuntimeError(
                    "ILLEGAL TRANSITION: Cannot schedule install until "
                    "MATERIALS_ON_SITE is confirmed."
                )

        elif new_status == JobStatus.INVOICED:
            # Ensure the pipeline doesn't invoice a lead that wasn't built
            valid_priors = [JobStatus.MATERIAL_ORDERED, JobStatus.INSTALL_SCHEDULED, JobStatus.INSTALL_COMPLETED, JobStatus.FINAL_INSPECTION, JobStatus.INVOICED]
            if current_status not in valid_priors:
                raise RuntimeError(f"ILLEGAL TRANSITION: Cannot invoice from state {current_status}.")

        elif new_status == JobStatus.CLOSED:
            if current_status != JobStatus.PAYMENT_RECEIVED:
                raise RuntimeError("ILLEGAL TRANSITION: Cannot close job before PAYMENT_RECEIVED.")
        # ---------------------------------------------------------

        # Update DB with atomic JSON append to prevent race conditions
        timestamp_str = datetime.utcnow().isoformat() + "Z"
        cursor = conn.execute(
            """
            UPDATE jobs 
            SET status = ?, 
                status_history = json_insert(
                    COALESCE(status_history, '[]'), 
                    '$[#]', 
                    json_object('status', ?, 'timestamp', ?, 'note', ?)
                )
            WHERE id = ?
            """,
            (new_status, new_status, timestamp_str, note, job_id)
        )
            
        if new_status == JobStatus.INVOICED:
            conn.execute("UPDATE jobs SET invoiced_at = CURRENT_TIMESTAMP WHERE id = ?", (job_id,))
            
        if cursor.rowcount == 0:
            raise ValueError(f"Job {job_id} not found during update")
            
        conn.execute("COMMIT")
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
            INSERT INTO financials 
            (job_id, revenue, carrier_rcv, material_cost, labor_cost, overhead_pct, canvasser_commission_pct, permits_fee)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                revenue = excluded.revenue,
                carrier_rcv = excluded.carrier_rcv,
                material_cost = excluded.material_cost,
                labor_cost = excluded.labor_cost,
                overhead_pct = excluded.overhead_pct,
                canvasser_commission_pct = excluded.canvasser_commission_pct,
                permits_fee = excluded.permits_fee
        ''', (job_id, revenue, carrier_rcv, material_cost, labor_cost, overhead_pct, canvasser_commission_pct, permits_fee))
        conn.execute("COMMIT")
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
        conn.execute("BEGIN IMMEDIATE")
        order_id = str(uuid.uuid4())
        conn.execute('''
            INSERT INTO material_orders (id, job_id, supplier_name, delivery_date, bom_json)
            VALUES (?, ?, ?, ?, ?)
        ''', (order_id, job_id, supplier_name, delivery_date, bom_json))
        conn.execute("COMMIT")
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
        conn.execute("BEGIN IMMEDIATE")
        schedule_id = str(uuid.uuid4())
        conn.execute('''
            INSERT OR REPLACE INTO schedule (id, job_id, crew_name, install_date, delivery_date, status)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (schedule_id, job_id, crew_name, install_date, delivery_date, status))
        conn.execute("COMMIT")
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
    def _do_backup() -> None:
        backup_dir = Path("data/backups")
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = uuid.uuid4().hex[:6]
        backup_path = backup_dir / f"crm_backup_{timestamp}_{unique_id}.db"
        
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

def insert_job_document(job_id: str, filename: str, file_type: str, storage_path: str, sha256_hash: str | None = None) -> str:
    """Register a generated or uploaded file in the universal document vault."""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        doc_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO job_documents (id, job_id, filename, file_type, storage_path, sha256_hash) 
            VALUES (?, ?, ?, ?, ?, ?)""",
            (doc_id, job_id, filename, file_type, storage_path, sha256_hash)
        )
        conn.execute("COMMIT")
        logger.info("job_document_registered", doc_id=doc_id, job_id=job_id, file_type=file_type)
        return doc_id
    except Exception as e:
        logger.error("job_document_registration_failed", error=str(e))
        raise
    finally:
        conn.close()

def get_job_documents(job_id: str, file_type: str | None = None) -> list[dict]:
    """Return all document versions for a job, newest first.
    
    This is the canonical read path. Because documents are append-only,
    the most recent row for a given filename is the authoritative version.
    Pass file_type to filter (e.g., 'SUPPLEMENT_PDF', 'EAGLEVIEW_PDF').
    """
    conn = get_connection()
    try:
        if file_type:
            cursor = conn.execute(
                """SELECT * FROM job_documents 
                   WHERE job_id = ? AND file_type = ?
                   ORDER BY created_at DESC""",
                (job_id, file_type)
            )
        else:
            cursor = conn.execute(
                """SELECT * FROM job_documents 
                   WHERE job_id = ? 
                   ORDER BY created_at DESC""",
                (job_id,)
            )
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()

def get_job_document_by_hash(job_id: str, sha256_hash: str) -> dict | None:
    """Lookup an existing document by its content hash to prevent duplicate processing."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT * FROM job_documents WHERE job_id = ? AND sha256_hash = ?",
            (job_id, sha256_hash)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
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

def update_material_flags(
    job_id: str,
    materials_ordered: bool | None = None,
    materials_on_site: bool | None = None,
) -> None:
    """
    Restricted toggle for operational material confirmation flags.
    Called exclusively by PATCH /api/operations/job/{id}/materials.

    If materials_on_site transitions to True, this function ALSO
    calls update_job_status() to advance the job to MATERIALS_ON_SITE,
    making it eligible for crew scheduling.

    If materials_on_site transitions to False (rollback), the job
    status is reverted to MATERIAL_ORDERED.

    Raises ValueError if job_id not found.
    """
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            "SELECT id FROM jobs WHERE id = ?", (job_id,)
        )
        if not cursor.fetchone():
            raise ValueError(f"Job {job_id} not found.")

        if materials_ordered is not None:
            conn.execute(
                "UPDATE jobs SET materials_ordered = ? WHERE id = ?",
                (1 if materials_ordered else 0, job_id),
            )
        if materials_on_site is not None:
            conn.execute(
                "UPDATE jobs SET materials_on_site = ? WHERE id = ?",
                (1 if materials_on_site else 0, job_id),
            )
        conn.execute("COMMIT")

        # Drive the state machine from the flag transitions
        if materials_on_site is True:
            update_job_status(
                job_id,
                JobStatus.MATERIALS_ON_SITE,
                "Materials confirmed on-site via Operations Board toggle.",
            )
        elif materials_on_site is False:
            update_job_status(
                job_id,
                JobStatus.MATERIAL_ORDERED,
                "Materials on-site confirmation rolled back via Operations Board.",
            )

        logger.info(
            "material_flags_updated",
            job_id=job_id,
            ordered=materials_ordered,
            on_site=materials_on_site,
        )
    except Exception as e:
        logger.error("material_flags_update_failed", job_id=job_id, error=str(e))
        raise
    finally:
        conn.close()


def get_qbo_export_batch() -> list[dict]:
    """
    Returns all jobs eligible for QBO batch export:
    status IN (SUPPLEMENT_APPROVED, INVOICED) AND qbo_exported = 0.
    Joins jobs + financials. Returns empty list if none pending.
    """
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            SELECT j.id as job_id, j.homeowner_name, j.status,
                   f.revenue, f.carrier_rcv, f.material_cost,
                   f.labor_cost, f.overhead_pct,
                   f.canvasser_commission_pct, f.permits_fee
            FROM jobs j
            JOIN financials f ON j.id = f.job_id
            WHERE j.status IN ('SUPPLEMENT_APPROVED', 'INVOICED')
              AND f.qbo_exported = 0
            ORDER BY j.created_at ASC
            """
        )
        return [dict(r) for r in cursor.fetchall()]
    except Exception as e:
        logger.error("get_qbo_export_batch_failed", error=str(e))
        return []
    finally:
        conn.close()


def mark_qbo_exported(job_ids: list[str]) -> None:
    """
    Idempotency lock: mark a batch of jobs as QBO-exported.
    Sets qbo_exported=1 and qbo_exported_at=NOW for each job_id.
    Safe to call multiple times — subsequent calls are no-ops due
    to the qbo_exported=0 filter in get_qbo_export_batch().
    """
    if not job_ids:
        return
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.executemany(
            """UPDATE financials
               SET qbo_exported = 1,
                   qbo_exported_at = CURRENT_TIMESTAMP
               WHERE job_id = ?""",
            [(jid,) for jid in job_ids],
        )
        conn.execute("COMMIT")
        logger.info("qbo_batch_marked_exported", count=len(job_ids))
    except Exception as e:
        logger.error("qbo_mark_exported_failed", error=str(e))
        raise
    finally:
        conn.close()

def update_job_metadata(job_id: str, inspector_name: str, inspection_date: str, inspection_notes: str) -> None:
    """Update inspection-related metadata for a specific job."""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute('''
            UPDATE jobs 
            SET inspector_name = ?, inspection_date = ?, inspection_notes = ? 
            WHERE id = ?
        ''', (inspector_name, inspection_date, inspection_notes, job_id))
        conn.execute("COMMIT")
        logger.info("job_metadata_updated", job_id=job_id)
    except Exception as e:
        logger.error("update_job_metadata_failed", job_id=job_id, error=str(e))
        raise
    finally:
        conn.close()

def log_ai_usage(job_id: str | None, tokens_used: int, model_name: str, operation_type: str) -> None:
    """Synchronously log AI token consumption to the database."""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        log_id = str(uuid.uuid4())
        conn.execute('''
            INSERT INTO ai_usage_logs (id, job_id, tokens_used, model_name, operation_type)
            VALUES (?, ?, ?, ?, ?)
        ''', (log_id, job_id, tokens_used, model_name, operation_type))
        conn.execute("COMMIT")
    except Exception as e:
        logger.error("failed_to_log_ai_usage", error=str(e))
    finally:
        conn.close()

def atomic_qbo_export() -> list[dict]:
    """
    Atomically fetch all QBO-eligible jobs and mark them exported
    in a single IMMEDIATE transaction, preventing double-export
    race conditions from concurrent requests.

    Returns the batch rows (as dicts) that were locked.
    Returns empty list if nothing pending.
    """
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute("""
            SELECT j.id as job_id, j.homeowner_name, j.status,
                   f.revenue, f.carrier_rcv, f.material_cost,
                   f.labor_cost, f.overhead_pct,
                   f.canvasser_commission_pct, f.permits_fee
            FROM jobs j
            JOIN financials f ON j.id = f.job_id
            WHERE j.status IN ('SUPPLEMENT_APPROVED', 'INVOICED')
              AND f.qbo_exported = 0
            ORDER BY j.created_at ASC
        """)
        batch = [dict(r) for r in cursor.fetchall()]
        if batch:
            job_ids = [r["job_id"] for r in batch]
            conn.executemany(
                """UPDATE financials
                   SET qbo_exported = 1,
                       qbo_exported_at = CURRENT_TIMESTAMP
                   WHERE job_id = ?""",
                [(jid,) for jid in job_ids],
            )
        conn.execute("COMMIT")
        logger.info("atomic_qbo_export_complete", count=len(batch))
        return batch
    except Exception as e:
        conn.execute("ROLLBACK")
        logger.error("atomic_qbo_export_failed", error=str(e))
        raise
    finally:
        conn.close()

def mark_supplement_sent(job_id: str) -> None:
    """
    Transitions job from SUPPLEMENT_GENERATED to
    AWAITING_CARRIER_RESPONSE and records the sent timestamp.
    Idempotent — safe to call multiple times.
    """
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE jobs
            SET status = 'AWAITING_CARRIER_RESPONSE',
                supplement_sent_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND status = 'SUPPLEMENT_GENERATED'
        """, (job_id,))
        conn.commit()
    finally:
        conn.close()

def toggle_payment_flag(job_id: str, flag: str) -> dict:
    """
    Toggles acv_received or supplement_received for a job.
    Returns the new state. flag must be one of the two allowed
    values — hard-coded whitelist, no dynamic SQL construction.
    """
    allowed = {"acv_received", "supplement_received"}
    if flag not in allowed:
        raise ValueError(f"Invalid flag: {flag}")

    ts_col = flag + "_at"
    conn = get_connection()
    try:
        cursor = conn.execute(
            f"SELECT {flag} FROM jobs WHERE id = ?", (job_id,)
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Job {job_id} not found.")

        new_val = 0 if row[flag] else 1
        ts_val = "CURRENT_TIMESTAMP" if new_val else "NULL"
        conn.execute(
            f"""UPDATE jobs
                SET {flag} = ?,
                    {ts_col} = {ts_val}
                WHERE id = ?""",
            (new_val, job_id)
        )
        conn.commit()
        return {"flag": flag, "new_value": new_val,
                "job_id": job_id}
    finally:
        conn.close()
