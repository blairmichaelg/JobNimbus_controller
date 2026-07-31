filepath = 'app/workers/inspection_processor.py'
with open(filepath, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
skip_next = False
for i, line in enumerate(lines):
    if skip_next:
        skip_next = False
        continue
        
    if "uploaded_file = await asyncio.to_thread(ai.client.files.upload, file=ai_file_path)" in line:
        new_lines.append(line.replace("uploaded_file = await asyncio.to_thread(ai.client.files.upload, file=ai_file_path)", "uploaded_name = await ai.upload_media_file(ai_file_path)"))
        skip_next = True # skips uploaded_name = uploaded_file.name
    elif "file_info = await asyncio.to_thread(ai.client.files.get, name=uploaded_name)" in line:
        new_lines.append(line.replace("file_info = await asyncio.to_thread(ai.client.files.get, name=uploaded_name)", "file_status = await ai.get_file_status(uploaded_name)"))
    elif "assert file_info.state is not None" in line:
        new_lines.append(line.replace("assert file_info.state is not None", "assert file_status is not None"))
    elif "file_info.state.name == \"PROCESSING\"" in line:
        new_lines.append(line.replace("file_info.state.name == \"PROCESSING\"", "file_status == \"PROCESSING\""))
    elif "file_info.state.name == \"FAILED\"" in line:
        new_lines.append(line.replace("file_info.state.name == \"FAILED\"", "file_status == \"FAILED\""))
    elif "await ai.analyze_roof_photo(file_info, photo.filepath.name, job.job_id)" in line:
        new_lines.append(line.replace("await ai.analyze_roof_photo(file_info, photo.filepath.name, job.job_id)", "await ai.analyze_roof_photo(uploaded_name, photo.filepath.name, job.job_id)"))
    elif "await asyncio.to_thread(ai.client.files.delete, name=uploaded_name)" in line:
        new_lines.append(line.replace("await asyncio.to_thread(ai.client.files.delete, name=uploaded_name)", "await ai.delete_file(uploaded_name)"))
    else:
        new_lines.append(line)

with open(filepath, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print("inspection_processor fully updated.")
