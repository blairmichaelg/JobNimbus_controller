
with open("app/api/field_routes.py", "r") as f:
    content = f.read()

if "assert_field_rep_owns_job" not in content:
    content = content.replace(
        "from app.core.climate_lookup import is_ice_barrier_required",
        "from app.services.field_access import assert_field_rep_owns_job\nfrom app.core.climate_lookup import is_ice_barrier_required"
    )

# Inject claims = Depends(get_current_claims) and assert_field_rep_owns_job(claims, job_id)
# 1. async def upload_field_photo
content = content.replace(
    'async def upload_field_photo(job_id: str, file: UploadFile = File(...)):',
    'async def upload_field_photo(job_id: str, file: UploadFile = File(...), claims: dict = Depends(get_current_claims)):\n    assert_field_rep_owns_job(claims, job_id)'
)

# 2. async def get_inspection_summary
content = content.replace(
    'async def get_inspection_summary(job_id: str):',
    'async def get_inspection_summary(job_id: str, claims: dict = Depends(get_current_claims)):\n    assert_field_rep_owns_job(claims, job_id)'
)

# 3. async def resume_supplement (this one already has role)
content = content.replace(
    'async def resume_supplement(job_id: str, request: Request, background_tasks: BackgroundTasks, role: str = Depends(get_current_role)):',
    'async def resume_supplement(job_id: str, request: Request, background_tasks: BackgroundTasks, role: str = Depends(get_current_role), claims: dict = Depends(get_current_claims)):\n    assert_field_rep_owns_job(claims, job_id)'
)

# 4. async def resolve_flag
content = content.replace(
    'async def resolve_flag(job_id: str, flag_id: str, payload: FlagResolutionPayload):',
    'async def resolve_flag(job_id: str, flag_id: str, payload: FlagResolutionPayload, claims: dict = Depends(get_current_claims)):\n    assert_field_rep_owns_job(claims, job_id)'
)

# 5. async def contingency_sign
content = content.replace(
    'async def contingency_sign(job_id: str, payload: ContingencySignaturePayload):',
    'async def contingency_sign(job_id: str, payload: ContingencySignaturePayload, claims: dict = Depends(get_current_claims)):\n    assert_field_rep_owns_job(claims, job_id)'
)

# Note: _sync_* functions don't receive requests directly, they are called by the async endpoints.
# _sync_resolve_flag, _sync_fetch_job_contingency, _sync_process_image, _sync_insert_agreement
# Wait, contingency_sign calls _sync_fetch_job_contingency. Wait, is there a GET for contingency?
# Let's check for @router.get("/jobs/{job_id}...")
with open("app/api/field_routes.py", "w") as f:
    f.write(content)
