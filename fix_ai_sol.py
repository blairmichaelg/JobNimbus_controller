filepath = 'app/services/ai_service.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix extract_sol_from_pdf
content = content.replace("source_system = await asyncio.to_thread(self.classify_carrier, file_info, job_id)", "source_system = await self.classify_carrier(uploaded_file.name, job_id)")
content = content.replace("contents=[await asyncio.to_thread(self._call_with_backoff, self.client.files.get, name=file_name), prompt]", "contents=[await asyncio.to_thread(self._call_with_backoff, self.client.files.get, name=uploaded_file.name), prompt]")

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print("extract_sol_from_pdf fixed")
