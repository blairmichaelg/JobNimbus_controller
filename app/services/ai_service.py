"""
Google Gemini AI service wrapper.

Wraps the google-genai SDK to:
- Accept translated (human-readable) job data as context
- Apply strict prompt templates for specific cognitive tasks
- Return structured JSON decisions
- Handle API errors and rate limits gracefully

V3 additions:
- _call_with_backoff: Exponential backoff for free-tier rate limiting (429)
- analyze_roof_photo: Multimodal damage detection with flat PhotoAnalysis schema

SDK Migration: Moved from deprecated google-generativeai to google-genai.
The new SDK uses a Client() pattern with client.models.generate_content().
"""

import json
import time
import random
import asyncio
import structlog
from google import genai
from google.genai import types as genai_types
from pydantic import BaseModel, ValidationError
from typing import Literal

from app.config import get_settings
from app.core.supplement_models import StatementOfLoss, DiscrepancyReport
from app.core.inspection_models import PhotoAnalysis

logger = structlog.get_logger("app.services.ai_service")


class DocumentData(BaseModel):
    materials: list[str] = []
    total_cost: float = 0.0


class Decision(BaseModel):
    action: Literal["generate_document", "update_status", "ignore", "error"]
    reasoning: str
    document_data: DocumentData


class AIService:
    """
    Gemini AI integration for cognitive processing of CRM data.

    Uses the google-genai unified SDK with:
    - Strict JSON output via response_mime_type
    - Low temperature for deterministic responses
    - Pydantic schema enforcement on AI output
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = genai.Client(api_key=self.settings.gemini_api_key)
        self.model_name = "gemini-2.5-flash"
        logger.info("ai_service_initialized", model=self.model_name)

    def _call_with_backoff(self, func, *args, max_retries: int = 5, **kwargs):
        """
        Rate-limit-aware wrapper for Gemini API calls.

        Catches 429 RESOURCE_EXHAUSTED errors and retries with exponential
        backoff + jitter. Essential for free-tier quota protection when
        processing 40+ roof photos sequentially.

        Args:
            func: The callable (e.g., self.client.models.generate_content).
            *args: Positional args forwarded to func.
            max_retries: Maximum retry attempts before raising. Default 5.
            **kwargs: Keyword args forwarded to func.

        Returns:
            The return value of func(*args, **kwargs).

        Raises:
            RuntimeError: If all retries are exhausted.
            Exception: Any non-rate-limit error is re-raised immediately.
        """
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    wait = (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(
                        "rate_limited_backoff",
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        wait_seconds=round(wait, 2),
                    )
                    time.sleep(wait)
                else:
                    raise
        raise RuntimeError(
            f"Gemini API rate limit exceeded after {max_retries} retries."
        )

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
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.model_name,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2,
                ),
            )

            result_text = response.text
            decision_obj = Decision.model_validate_json(result_text)
            decision = decision_obj.model_dump()

            log.info(
                "ai_analysis_complete",
                action=decision.get("action"),
                reasoning=decision.get("reasoning"),
            )
            return decision

        except ValidationError as exc:
            log.error(
                "ai_schema_validation_error",
                error=str(exc),
                response_text=response.text if "response" in locals() else None,
            )
            return {
                "action": "error",
                "reasoning": f"Schema Validation Error: {str(exc)}",
                "document_data": {},
            }
        except Exception as exc:
            log.error("ai_unexpected_error", error=str(exc))
            return {
                "action": "error",
                "reasoning": f"Unexpected error: {str(exc)}",
                "document_data": {},
            }

    def classify_carrier(self, file_info) -> str:
        """
        Classify the carrier estimating software from the PDF.
        """
        prompt = (
            "Analyze the first page or headers of this PDF and identify the estimating software used. "
            "Return ONLY a single string: 'xactimate', 'symbility', or 'unknown'."
        )
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=[file_info, prompt],
            config=genai_types.GenerateContentConfig(
                response_mime_type="text/plain",
                temperature=0.0,
            ),
        )
        result = response.text.strip().lower()
        if result in ("xactimate", "symbility"):
            return result
        return "unknown"

    async def extract_sol_from_pdf(self, pdf_path: str) -> StatementOfLoss:
        """
        Multimodal extraction of a Statement of Loss PDF using Gemini File API.
        Enforces structured extraction using the StatementOfLoss Pydantic schema.
        """
        log = logger.bind(pdf_path=str(pdf_path))
        log.info("sol_extraction_started")

        def _extract():
            import time
            # 1. Upload file
            uploaded_file = self.client.files.upload(file=pdf_path)
            
            # 2. Wait for processing
            file_info = self.client.files.get(name=uploaded_file.name)
            while file_info.state.name == "PROCESSING":
                time.sleep(2)
                file_info = self.client.files.get(name=uploaded_file.name)
            
            if file_info.state.name == "FAILED":
                raise RuntimeError("File processing failed on Gemini servers.")

            # 3. Classify the Carrier
            source_system = self.classify_carrier(file_info)
            
            # 4. Set targeted prompt
            if source_system == "xactimate":
                prompt = """
                You are an expert Xactimate estimator. Analyze this Statement of Loss (SoL) document.
                Extract ONLY the line items located under the "Roof" grouping (ignore any other rooms, general demolition, or recap tables).
                Pay special attention to descriptions that wrap across multiple lines (e.g., "Remove 3 tab 25 yr. composition shingle roofing - incl. felt").
                If a quantity, unit of measure, or price is blank or missing, you MUST return null, not guess or hallucinate.
                DO NOT infer or calculate quantities. Extract the exact numerical value printed in the quantity column.
                If Overhead and Profit (O&P) is not explicitly listed in the summaries, set overhead_and_profit_included to false.
                """
            elif source_system == "symbility":
                prompt = """
                You are an expert Symbility estimator. Analyze this Statement of Loss (SoL) document.
                Extract ONLY the line items located under the "Roof" grouping.
                Symbility formats line items differently. Explicitly look for phrases like "Includes 10% waste on quantity" in the item notes.
                If you find a waste percentage in the notes, map that float (e.g., 0.10) to the waste_percent_included field.
                DO NOT infer or calculate quantities. Extract the exact numerical value printed in the quantity column.
                If a quantity, unit of measure, or price is blank or missing, you MUST return null.
                """
            else:
                logger.warning("WARNING: Unknown Carrier Format Detected")
                prompt = """
                Analyze this roofing Statement of Loss document.
                Extract ONLY the line items related to roof replacement.
                DO NOT infer or calculate quantities. Extract the exact numerical value printed in the quantity column.
                If a quantity, unit of measure, or price is blank or missing, you MUST return null.
                """

            # 5. Generate content with structured output
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=[file_info, prompt],
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=StatementOfLoss,
                    temperature=0.1,
                    max_output_tokens=8192,
                ),
            )
            
            # 6. Clean up the file (best effort)
            try:
                self.client.files.delete(name=uploaded_file.name)
            except Exception:
                pass
                
            parsed = response.parsed
            parsed.source_system = source_system
            return parsed

        try:
            result = await asyncio.to_thread(_extract)
            log.info("sol_extraction_complete")
            return result
        except Exception as exc:
            log.error("sol_extraction_failed", error=str(exc))
            raise

    async def generate_supplement_narrative(self, report: DiscrepancyReport, codes: str) -> str:
        """
        Generate a professional, assertive supplement request narrative.
        Uses the deterministic discrepancies and raw XML building codes as context.
        """
        log = logger.bind(job_id=report.job_id)
        log.info("supplement_narrative_started")

        prompt = f"""
        You are an expert, assertive roofing contractor writing a supplement justification letter to an insurance desk adjuster.
        
        You have analyzed the EagleView measurement report and the Carrier's Statement of Loss and found the following numerical shortages.
        You MUST explicitly state the mathematical shortages found in the report below.
        Only cite the building codes provided below if they directly relate to the identified discrepancies.
        You MUST use the exact `code_citation` string provided as a bolded header before quoting the building code. Do not hallucinate or alter the citation.
        
        --- DISCREPANCY REPORT ---
        {report.model_dump_json(indent=2)}
        
        --- BUILDING CODES ---
        {codes}
        
        Write the letter now. Do not use placeholders for the company name, just use "Wickham Roofing LLC". Do not include a date or address block at the top, just jump straight into "Dear Adjuster," and the body of the letter.
        """

        try:
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.model_name,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    temperature=0.3,
                ),
            )
            
            log.info("supplement_narrative_complete")
            return response.text
        except Exception as exc:
            log.error("supplement_narrative_failed", error=str(exc))
            raise

    def analyze_roof_photo(self, file_info) -> PhotoAnalysis:
        """
        Multimodal damage analysis of a single roof photo using Gemini 2.5 Flash.

        Uses the flat PhotoAnalysis Pydantic schema via response_schema to enforce
        structured JSON output. The schema is intentionally non-nested to avoid
        400 Bad Request errors from Gemini's structured output API.

        Called synchronously within the inspection_processor's sequential loop.
        Wrapped by _call_with_backoff at the call site for rate-limit protection.

        Args:
            file_info: A Gemini File API file reference (from client.files.get()).

        Returns:
            PhotoAnalysis: Validated forensic damage assessment.
        """
        prompt = (
            "You are Wickham Roofing's senior forensic inspector. "
            "Analyze this roof photo for hail impact bruises, wind crease lines, "
            "granule loss, and exposed fiberglass mat. "
            "Output the exact damage classifications and a highly technical, "
            "2-3 sentence forensic narrative designed to definitively prove "
            "storm damage to an insurance adjuster."
        )

        response = self.client.models.generate_content(
            model=self.model_name,
            contents=[file_info, prompt],
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=PhotoAnalysis,
                temperature=0.1,
            ),
        )
        return response.parsed
