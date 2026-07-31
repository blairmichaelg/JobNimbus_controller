filepath = 'app/services/ai_service.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix docstring placement
bad_docstring = '''    \"\"\"
    Gemini AI integration for cognitive processing of CRM data.

    Uses the google-genai unified SDK with:
    - Strict JSON output via response_mime_type
    - Low temperature for deterministic responses
    - Pydantic schema enforcement on AI output
    \"\"\"'''

if bad_docstring in content:
    content = content.replace(bad_docstring, "")
    class_def = "class GeminiClient(AiClient):"
    good_docstring = f'''class GeminiClient(AiClient):
{bad_docstring}'''
    content = content.replace(class_def, good_docstring)

# Add abstract methods
abc_insert = '''    @abstractmethod
    async def extract_sol_structured_data(self, prompt: str) -> str: ...

    @abstractmethod
    async def upload_media_file(self, file_path: str) -> str: ...
    
    @abstractmethod
    async def get_file_status(self, file_name: str) -> str: ...
    
    @abstractmethod
    async def delete_file(self, file_name: str) -> None: ...
'''
content = content.replace("    @abstractmethod\n    async def extract_sol_structured_data(self, prompt: str) -> str: ...\n", abc_insert)

# Implement methods in GeminiClient
impl_insert = '''    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = genai.Client(api_key=self.settings.gemini_api_key)
        self.model_name = "gemini-2.5-flash"
        logger.info("ai_service_initialized", model=self.model_name)

    async def upload_media_file(self, file_path: str) -> str:
        uploaded_file = await asyncio.to_thread(self._call_with_backoff, self.client.files.upload, file=file_path)
        return uploaded_file.name

    async def get_file_status(self, file_name: str) -> str:
        file_info = await asyncio.to_thread(self._call_with_backoff, self.client.files.get, name=file_name)
        return file_info.state.name

    async def delete_file(self, file_name: str) -> None:
        try:
            await asyncio.to_thread(self._call_with_backoff, self.client.files.delete, name=file_name)
        except Exception as e:
            logger.warning("gemini_file_cleanup_failed", file_name=file_name, error=str(e))
'''
content = content.replace('''    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = genai.Client(api_key=self.settings.gemini_api_key)
        self.model_name = "gemini-2.5-flash"
        logger.info("ai_service_initialized", model=self.model_name)''', impl_insert)

# Refactor classify_carrier, extract_sol_from_pdf, analyze_roof_photo to use file_name
content = content.replace("async def classify_carrier(self, file_info, job_id: str | None = None) -> str:", "async def classify_carrier(self, file_name: str, job_id: str | None = None) -> str:")
content = content.replace("contents=[file_info, prompt],", "contents=[await asyncio.to_thread(self._call_with_backoff, self.client.files.get, name=file_name) if 'file_name' in locals() else file_info, prompt],")

# Actually, it's safer to just replace exactly what we need. 
with open('app/services/ai_service.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated AiClient and GeminiClient class definitions.")
