"""
Google Gemini AI service wrapper.

Wraps the google-generativeai SDK to:
- Accept translated (human-readable) job data as context
- Apply strict prompt templates for specific cognitive tasks
- Return structured JSON decisions
- Handle API errors and rate limits gracefully

Implementation: Phase 5
"""

import json
import asyncio
import structlog
import google.generativeai as genai
from google.api_core.exceptions import GoogleAPIError

from app.config import get_settings

logger = structlog.get_logger("app.services.ai_service")


class AIService:
    """
    Gemini AI integration for cognitive processing of CRM data.

    Phase 5 implementation will provide:
    - extract_materials(job_data) -> dict: Parse material lists from job notes
    - draft_customer_message(job_data, template) -> str: Draft SMS/email content
    - determine_pipeline_stage(job_data) -> str: AI-driven workflow routing
    - _build_prompt(task, context) -> str: Template-based prompt construction
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        genai.configure(api_key=self.settings.gemini_api_key)

        # Configure model to strictly return JSON
        generation_config = genai.types.GenerationConfig(
            response_mime_type="application/json",
            temperature=0.2,  # Low temperature for more deterministic output
        )

        self.model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            generation_config=generation_config,
        )
        logger.info("ai_service_initialized", model="gemini-2.5-flash")

    async def analyze_job_data(self, payload: dict) -> dict:
        """
        Analyze the translated CRM payload using Gemini and return a structured decision.
        """
        log = logger.bind(jnid=payload.get("id"))
        log.info("ai_analysis_started")

        prompt = f"""
You are an expert roofing estimator and workflow orchestrator for Wickham Roofing.
Analyze the following CRM job data and determine the next action.

CRM Data:
{json.dumps(payload, indent=2)}

You MUST output a valid JSON object matching exactly this schema:
{{
  "action": "generate_document" | "update_status" | "ignore",
  "reasoning": "A brief explanation of why you chose this action.",
  "document_data": {{
    "materials": ["Item 1", "Item 2"],
    "total_cost": 0.0
  }}
}}

Rules:
- If there is enough information to generate an estimate (e.g., measurements, scope of work in notes), set action to "generate_document" and populate document_data.
- If the data is incomplete or requires review, set action to "update_status".
- Otherwise, set action to "ignore".
"""

        try:
            # Run the synchronous API call in an executor to avoid blocking the event loop
            response = await asyncio.to_thread(self.model.generate_content, prompt)

            result_text = response.text
            decision = json.loads(result_text)

            log.info(
                "ai_analysis_complete",
                action=decision.get("action"),
                reasoning=decision.get("reasoning"),
            )
            return decision

        except json.JSONDecodeError as exc:
            log.error(
                "ai_json_parse_error",
                error=str(exc),
                response_text=response.text if "response" in locals() else None,
            )
            return {
                "action": "error",
                "reasoning": "Failed to parse AI response as JSON",
                "document_data": {},
            }
        except GoogleAPIError as exc:
            log.error("ai_api_error", error=str(exc))
            return {
                "action": "error",
                "reasoning": f"Google API Error: {str(exc)}",
                "document_data": {},
            }
        except Exception as exc:
            log.error("ai_unexpected_error", error=str(exc))
            return {
                "action": "error",
                "reasoning": f"Unexpected error: {str(exc)}",
                "document_data": {},
            }
