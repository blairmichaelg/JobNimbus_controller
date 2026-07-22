
def patch_file(filepath, imports, replacements):
    with open(filepath, "r") as f:
        content = f.read()

    # Add imports
    if "check_rate_limit" not in content:
        content = content.replace("from fastapi import APIRouter", f"from fastapi import APIRouter\n{imports}")

    # Add dependencies
    for original, replacement in replacements:
        content = content.replace(original, replacement)

    with open(filepath, "w") as f:
        f.write(content)

# Update office_routes.py
patch_file(
    "app/api/office_routes.py",
    "from app.services.rate_limit import check_rate_limit\n",
    [
        (
            'async def upload_supplement_docs(',
            '@router.post("/jobs/{job_id}/supplement_docs", dependencies=[Depends(check_rate_limit)])\nasync def upload_supplement_docs('
        ),
        (
            'async def generate_material_order(',
            '@router.post("/jobs/{job_id}/material_order", dependencies=[Depends(check_rate_limit)])\nasync def generate_material_order('
        ),
        (
            '@router.post("/jobs/{job_id}/supplement_docs")\n@router.post("/jobs/{job_id}/supplement_docs", dependencies=[Depends(check_rate_limit)])',
            '@router.post("/jobs/{job_id}/supplement_docs", dependencies=[Depends(check_rate_limit)])'
        ),
        (
            '@router.post("/jobs/{job_id}/material_order")\n@router.post("/jobs/{job_id}/material_order", dependencies=[Depends(check_rate_limit)])',
            '@router.post("/jobs/{job_id}/material_order", dependencies=[Depends(check_rate_limit)])'
        )
    ]
)

# Wait, the endpoints might already have decorators. I need to modify the existing decorators.
# Let's fix that.
