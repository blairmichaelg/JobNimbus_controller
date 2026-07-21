from fastapi import HTTPException
import structlog
from app.core.database import get_connection

logger = structlog.get_logger("app.services.field_access")

def assert_field_rep_owns_job(claims: dict, job_id: str) -> None:
    """
    Ensure the requesting field rep owns the specified job.
    Admins are allowed to bypass this check.
    Raises 403 Forbidden if not.
    """
    if claims.get("role") == "admin":
        return
        
    field_rep_id = claims.get("rep_id")
    if not field_rep_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this job. Missing rep_id.")
        
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM jobs WHERE id = ? AND canvasser_rep_id = ?",
            (job_id, field_rep_id)
        ).fetchone()
        
        if not row:
            logger.warning("field_rep_access_denied", job_id=job_id, field_rep_id=field_rep_id)
            raise HTTPException(
                status_code=403, 
                detail="Not authorized to access this job."
            )
    finally:
        conn.close()
