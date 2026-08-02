"""
Admin Job Management API.

Provides emergency override endpoints for managing jobs.
All endpoints are admin-only.
"""

from fastapi import APIRouter, Body, HTTPException, Depends
from fastapi.responses import JSONResponse
from app.api.auth import verify_admin
from app.core.database import force_override_status
import structlog

logger = structlog.get_logger("app.api.admin_jobs")
router = APIRouter(
    prefix="/api/admin/jobs",
    tags=["admin-jobs"],
    dependencies=[Depends(verify_admin)]
)

@router.post("/{job_id}/override", response_class=JSONResponse, status_code=200)
def override_job_status(
    job_id: str,
    payload: dict = Body(...),
):
    """
    Emergency override to forcefully transition a job's status.
    Body: {"new_status": "CLOSED", "note": "Override for specific reason."}
    """
    new_status = payload.get("new_status", "").strip()
    note = payload.get("note", "").strip()
    
    if not new_status:
        raise HTTPException(status_code=400, detail="new_status is required.")
    if not note:
        raise HTTPException(status_code=400, detail="A reason (note) is required for all overrides.")
        
    try:
        force_override_status(job_id=job_id, new_status=new_status, note=note)
        return {"status": "success", "message": f"Job {job_id} overridden to {new_status}"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("api_override_failed", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

import json
from pathlib import Path
from app.core.database import get_connection

@router.get("/storm-canvassing-map", response_class=JSONResponse)
def get_storm_canvassing_map():
    """Returns job locations for the storm canvassing map by joining against zipcodes.json."""
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT id, homeowner_name, canvasser_name, address_line1, city, state, postal_code, status FROM jobs WHERE status != 'CLOSED'")
        jobs = cursor.fetchall()
        
        zip_path = Path("data/zipcodes.json")
        zip_data = {}
        if zip_path.exists():
            with open(zip_path, "r", encoding="utf-8") as f:
                zip_data = json.load(f)
                
        map_points = []
        for j in jobs:
            zc = str(j["postal_code"]).strip()
            if zc in zip_data:
                coords = zip_data[zc]
                map_points.append({
                    "job_id": j["id"],
                    "homeowner_name": j["homeowner_name"],
                    "canvasser_name": j["canvasser_name"],
                    "address": f"{j['address_line1']}, {j['city']}, {j['state']} {j['postal_code']}",
                    "status": j["status"],
                    "lat": coords["lat"],
                    "lon": coords["lon"]
                })
        return {"status": "success", "data": map_points}
    except Exception as e:
        logger.error("map_query_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Internal Server Error")
    finally:
        conn.close()

@router.get("/rep-activity", response_class=JSONResponse)
def get_rep_activity():
    """Returns aggregated pipeline metrics per sales rep."""
    conn = get_connection()
    try:
        cursor = conn.execute('''
            SELECT canvasser_name, status, COUNT(id) as count 
            FROM jobs 
            WHERE canvasser_name IS NOT NULL AND canvasser_name != ''
            GROUP BY canvasser_name, status
        ''')
        rows = cursor.fetchall()
        
        reps = {}
        for r in rows:
            name = r["canvasser_name"]
            st = r["status"]
            cnt = r["count"]
            if name not in reps:
                reps[name] = {"total_leads": 0, "active_pipeline": 0, "closed_won": 0}
                
            reps[name]["total_leads"] += cnt
            if st == "CLOSED":
                reps[name]["closed_won"] += cnt
            else:
                reps[name]["active_pipeline"] += cnt
                
        activity = [{"canvasser_name": k, **v} for k, v in reps.items()]
        # Sort by total leads descending
        activity.sort(key=lambda x: x["total_leads"], reverse=True)
        return {"status": "success", "data": activity}
    except Exception as e:
        logger.error("rep_activity_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Internal Server Error")
    finally:
        conn.close()
