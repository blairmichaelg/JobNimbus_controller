import re

filepath = 'app/services/ai_service.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix classify_carrier signature
content = content.replace(
    "async def classify_carrier(self, file_info, job_id: str | None = None) -> str:",
    "async def classify_carrier(self, file_name: str, job_id: str | None = None) -> str:"
)
content = content.replace(
    "contents=[await asyncio.to_thread(self._call_with_backoff, self.client.files.get, name=file_name) if 'file_name' in locals() else file_info, prompt],",
    "contents=[await asyncio.to_thread(self._call_with_backoff, self.client.files.get, name=file_name), prompt],"
)
content = content.replace(
    "def classify_carrier(self, file_name: str, job_id: str | None = None) -> str:",
    "async def classify_carrier(self, file_name: str, job_id: str | None = None) -> str:"
)

# In abstract class, it should be file_name
content = content.replace(
    "async def classify_carrier(self, file_info, job_id: str | None = None) -> str: ...",
    "async def classify_carrier(self, file_name: str, job_id: str | None = None) -> str: ..."
)

# Fix analyze_roof_photo signature in abstract class
content = content.replace(
    "async def analyze_roof_photo(self, file_info, original_filename: str, job_id: str | None = None) -> PhotoAnalysis: ...",
    "async def analyze_roof_photo(self, file_name: str, original_filename: str, job_id: str | None = None) -> PhotoAnalysis: ..."
)

# Fix analyze_roof_photo signature in GeminiClient
content = content.replace(
    "async def analyze_roof_photo(self, file_info, original_filename: str, job_id: str | None = None) -> PhotoAnalysis:",
    "async def analyze_roof_photo(self, file_name: str, original_filename: str, job_id: str | None = None) -> PhotoAnalysis:\n        file_info = await asyncio.to_thread(self._call_with_backoff, self.client.files.get, name=file_name)"
)

# Fix extract_sol_from_pdf to use abstraction if possible, but extract_sol_from_pdf is already in GeminiClient and it can use self.client internally.
# Wait, extract_sol_from_pdf is a method of GeminiClient. It can use self.client.files internally because it's part of the implementation!
# We just need to make sure external callers (like photo_processor) don't use ai.client.

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print("ai_service.py refactored for file_name")
