"""
Operations-only restricted API routes.
Scott (Operations) can ONLY toggle material flags via this router.
He cannot access supplement data, financials, or job creation.
All routes require the ops-specific internal token.
"""
from __future__ import annotations

import uuid
import structlog
from fastapi import APIRouter, HTTPException, Header, Depends
from pydantic import BaseModel
from typing import Optional

from app.core.database import (
    update_material_flags,
    update_job_status,
    JobStatus,
    get_connection,
)
from app.config import get_settings

logger = structlog.get_logger("app.api.operations_routes")
router = APIRouter(prefix="/api/operations", tags=["operations"])


def _verify_ops_token(x_internal_token: str = Header(...)):
    """Dependency: verify the caller holds the ops-role token."""
    settings = get_settings()
    if x_internal_token != settings.INTERNAL_API_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")
    return x_internal_token


class MaterialFlagUpdate(BaseModel):
    materials_ordered: Optional[bool] = None
    materials_on_site: Optional[bool] = None


@router.patch("/job/{job_id}/materials", dependencies=[Depends(_verify_ops_token)])
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
        update_material_flags(
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
