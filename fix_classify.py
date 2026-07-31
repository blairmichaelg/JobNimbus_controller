filepath = 'app/services/ai_service.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace the whole classify_carrier method
old_method = '''    def classify_carrier(self, file_info, job_id: str | None = None) -> str:
        \"\"\"
        Classify the carrier estimating software from the PDF.
        \"\"\"
        prompt = (
            "Analyze the first page or headers of this PDF and identify the estimating software used. "
            "Return ONLY a single string: 'xactimate', 'symbility', or 'unknown'."
        )
        response = self._call_with_backoff(
            self.client.models.generate_content,
            model=self.model_name,
            contents=[await asyncio.to_thread(self._call_with_backoff, self.client.files.get, name=file_name), prompt],
            config=genai_types.GenerateContentConfig(
                response_mime_type="text/plain",
                temperature=0.0,
            ),
        )'''

new_method = '''    async def classify_carrier(self, file_name: str, job_id: str | None = None) -> str:
        \"\"\"
        Classify the carrier estimating software from the PDF.
        \"\"\"
        prompt = (
            "Analyze the first page or headers of this PDF and identify the estimating software used. "
            "Return ONLY a single string: 'xactimate', 'symbility', or 'unknown'."
        )
        
        file_info = await asyncio.to_thread(self._call_with_backoff, self.client.files.get, name=file_name)
        
        response = await asyncio.to_thread(
            self._call_with_backoff,
            self.client.models.generate_content,
            model=self.model_name,
            contents=[file_info, prompt],
            config=genai_types.GenerateContentConfig(
                response_mime_type="text/plain",
                temperature=0.0,
            ),
        )'''
content = content.replace(old_method, new_method)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print("classify_carrier fixed.")
