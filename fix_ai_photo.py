filepath = 'app/services/ai_service.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the analyze_roof_photo duplicate fetch and undefined variable
old_str = "contents=[await asyncio.to_thread(self._call_with_backoff, self.client.files.get, name=uploaded_file.name), prompt]"
new_str = "contents=[file_info, prompt]"

content = content.replace(old_str, new_str)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print("Fixed analyze_roof_photo in ai_service.py")
