import asyncio
import os
import shutil
from unittest.mock import patch, MagicMock
from dotenv import load_dotenv

from app.workers.supplement_processor import process_supplement_event

async def main():
    load_dotenv()
    
    # Mock settings
    mock_settings = MagicMock()
    mock_settings.gemini_api_key = os.getenv('GEMINI_API_KEY')
    mock_settings.jobnimbus_api_key = 'test'
    mock_settings.jobnimbus_base_url = 'https://test'
    mock_settings.webhook_secret = 'test'
    mock_settings.redis_url = 'redis://localhost'
    mock_settings.app_env = 'development'
    mock_settings.log_level = 'DEBUG'
    mock_settings.quarantine_status = 'API TEST LAB'
    mock_settings.dry_run = True

    print("Starting full Supplement Engine Pipeline...")
    with patch('app.config.get_settings', return_value=mock_settings), \
         patch('app.services.ai_service.get_settings', return_value=mock_settings):
        
        # We don't provide jn_client in ctx so the temp file isn't deleted, allowing us to inspect it.
        ctx = {}
        
        result = await process_supplement_event(
            ctx=ctx,
            jnid="TEST-100",
            ev_pdf_path="EagleView-Sample-Premium_Roof_Report.pdf",
            sol_pdf_path="xactimate-sample.pdf"
        )
        
        temp_pdf = result["pdf_path"]
        final_pdf = "supplement_output.pdf"
        
        if temp_pdf and os.path.exists(temp_pdf):
            shutil.copy(temp_pdf, final_pdf)
            print(f"\nPipeline complete! Supplement PDF saved to: {final_pdf}")
        else:
            print("\nPipeline failed to generate PDF.")

if __name__ == "__main__":
    asyncio.run(main())
