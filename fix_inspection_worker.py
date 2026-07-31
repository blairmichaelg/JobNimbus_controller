filepath = 'app/workers/inspection_processor.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(
    "uploaded_file = await asyncio.to_thread(ai.client.files.upload, file=ai_file_path)\n                        uploaded_name = uploaded_file.name",
    "uploaded_name = await ai.upload_media_file(ai_file_path)"
)
content = content.replace(
    "file_info = await asyncio.to_thread(ai.client.files.get, name=uploaded_name)",
    "file_status = await ai.get_file_status(uploaded_name)"
)
content = content.replace(
    "file_info.state.name == \"PROCESSING\"",
    "file_status == \"PROCESSING\""
)
content = content.replace(
    "file_info.state.name == \"FAILED\"",
    "file_status == \"FAILED\""
)
content = content.replace(
    "await ai.analyze_roof_photo(file_info, original_filename, job_id)",
    "await ai.analyze_roof_photo(uploaded_name, original_filename, job_id)"
)
content = content.replace(
    "await asyncio.to_thread(ai.client.files.delete, name=uploaded_name)",
    "await ai.delete_file(uploaded_name)"
)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print("inspection_processor updated.")
