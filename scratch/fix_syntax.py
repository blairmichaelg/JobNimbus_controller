
with open("app/api/office_routes.py", "r") as f:
    content = f.read()

content = content.replace(
    '@router.post("/admin/triage/{job_id}/resolve",(dependencies=[Depends(verify_admin)])\n             response_class=JSONResponse)',
    '@router.post("/admin/triage/{job_id}/resolve",\n             response_class=JSONResponse, dependencies=[Depends(verify_admin)])'
)

# Also check for other similar syntax errors
content = content.replace(',(dependencies=[Depends(', ', dependencies=[Depends(')
content = content.replace('] (dependencies=[Depends(', '], dependencies=[Depends(')
content = content.replace(')\n(dependencies=[Depends(', ',\n dependencies=[Depends(')

with open("app/api/office_routes.py", "w") as f:
    f.write(content)
