"""
Operations-only restricted API routes.
Scott (Operations) can ONLY toggle material flags via this router.
He cannot access supplement data, financials, or job creation.
All routes require the ops-specific internal token.
"""
from __future__ import annotations

import uuid
import structlog
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

from app.core.database import (
    transition_material_flags,
    update_job_status,
    JobStatus,
    get_connection,
)

from app.api.auth import verify_operations

logger = structlog.get_logger("app.api.operations_routes")
router = APIRouter(prefix="/api/operations", tags=["operations"])

class MaterialFlagUpdate(BaseModel):
    materials_ordered: Optional[bool] = None
    materials_on_site: Optional[bool] = None


@router.patch("/job/{job_id}/materials", dependencies=[Depends(verify_operations)])
async def patch_material_flags(job_id: str, body: MaterialFlagUpdate):
    """
    The ONLY write endpoint Scott can reach. Toggles material
    confirmation flags. Drives MATERIALS_ON_SITE state transition.

    This endpoint is the sole mechanism by which INSTALL_SCHEDULED
    becomes unblocked — see Phase 1 state machine blocker.
    """
    # Validate UUID to prevent path injection
    try:
        uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job_id format.")

    if body.materials_ordered is None and body.materials_on_site is None:
        raise HTTPException(
            status_code=422,
            detail="Provide at least one flag: materials_ordered or materials_on_site.",
        )

    try:
        transition_material_flags(
            job_id=job_id,
            materials_ordered=body.materials_ordered,
            materials_on_site=body.materials_on_site,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))

    logger.info(
        "ops_material_flags_patched",
        job_id=job_id,
        ordered=body.materials_ordered,
        on_site=body.materials_on_site,
    )
    return {"status": "ok", "job_id": job_id}


from fastapi.responses import HTMLResponse, JSONResponse
from fastapi import Request, Body
from app.api.office_routes import templates

@router.get(
    "/board",
    response_class=HTMLResponse
)
async def operations_board(request: Request):
    conn = get_connection()
    try:
        # List 1: Jobs needing materials ordered
        # (SUPPLEMENT_APPROVED, materials_ordered = 0)
        needs_materials = [dict(r) for r in conn.execute("""
            SELECT j.id, j.invoice_id, j.homeowner_name,
                   j.address_line1, j.city, j.state,
                   j.materials_ordered, j.materials_on_site,
                   m.supplier_name, m.delivery_date,
                   m.bom_json
            FROM jobs j
            LEFT JOIN material_orders m ON j.id = m.job_id
            WHERE j.status = 'SUPPLEMENT_APPROVED'
              AND j.materials_ordered = 0
            ORDER BY j.created_at ASC
        """).fetchall()]

        # List 2: Jobs ready to schedule
        # (MATERIALS_ON_SITE, no crew date yet)
        ready_to_build = [dict(r) for r in conn.execute("""
            SELECT j.id, j.invoice_id, j.homeowner_name,
                   j.address_line1, j.city, j.state,
                   s.crew_name, s.install_date
            FROM jobs j
            LEFT JOIN schedule s ON j.id = s.job_id
            WHERE j.status = 'MATERIALS_ON_SITE'
            ORDER BY j.created_at ASC
        """).fetchall()]
    finally:
        conn.close()

    return templates.TemplateResponse(
        request,
        "operations_dashboard.html",
        {
            "needs_materials": needs_materials,
            "ready_to_build": ready_to_build,
            "auth_token": request.cookies.get("auth_token", "")
        }
    )

@router.post(
    "/jobs/{job_id}/schedule",
    response_class=JSONResponse,
    dependencies=[Depends(verify_operations)]
)
async def assign_crew(
    job_id: str, payload: dict = Body(...)
):
    crew_name = payload.get("crew_name", "").strip()
    install_date = payload.get("install_date", "").strip()
    if not crew_name or not install_date:
        raise HTTPException(
            400,
            "crew_name and install_date are required."
        )
    from app.core.database import (
        insert_schedule
    )
    insert_schedule(
        job_id=job_id,
        crew_name=crew_name,
        install_date=install_date,
        delivery_date=install_date,
        status="SCHEDULED"
    )
    update_job_status(
        job_id,
        JobStatus.INSTALL_SCHEDULED,
        f"Crew '{crew_name}' scheduled for {install_date}."
    )
    return {"status": "scheduled", "job_id": job_id}
