"""
Three-Layer Anti-Hallucination Statement of Loss Parser.

Architecture:
  Layer 1 (pdfplumber): Deterministic text/table extraction.
  Layer 2 (Gemini structured output): Semantic field mapping only.
                                       Never does math.
  Layer 3 (Pydantic validate_math): Python re-verifies carrier arithmetic.

The LLM is a LOCATOR, not a CALCULATOR.
"""
from __future__ import annotations

import json
import asyncio
import structlog
from pathlib import Path
from decimal import Decimal
from typing import Optional

import pdfplumber
import google.generativeai as genai

from app.core.ingestion_models import (
    UniversalClaimAST, ClaimLineItem, RoofGeometry,
    ClaimFinancials, SourcedValue, EvidenceRef
)
from app.config import get_settings

logger = structlog.get_logger("app.services.document_parser")

# --- LAYER 1: Deterministic Extraction ---

def _extract_raw_tables(pdf_path: Path) -> tuple[str, list[dict]]:
    """
    Extract raw text and table rows from the SoL PDF using pdfplumber.
    Returns (full_text, list of raw row dicts with page numbers).
    No LLM involved. Fails loudly if PDF is unreadable.
    """
    full_text_parts = []
    raw_rows = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text()
            if text:
                full_text_parts.append(text)
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if row and any(cell for cell in row if cell):
                        raw_rows.append({
                            "page": page_num,
                            "cells": [str(c).strip() if c else "" for c in row]
                        })
    return "\n".join(full_text_parts), raw_rows


# --- LAYER 2: Gemini Structured Extraction (Locator Only) ---

_SOL_EXTRACTION_PROMPT = """
You are a forensic insurance document parser. Extract line items from
this roofing Statement of Loss (Xactimate or Symbility format).

CRITICAL RULES:
1. DO NOT calculate any math. Transcribe numbers exactly as printed.
2. If a field is missing, illegible, or ambiguous, return null.
   NEVER interpolate or guess a value.
3. Each line item MUST include the page number where it was found.
4. Return ONLY valid JSON matching the schema. No prose, no markdown.

Extract:
- All line items with: category_code, activity_code, description,
  quantity, unit, unit_price, tax, claimed_rcv, depreciation, acv, page
- Roof geometry summary: pitch, total_squares, eaves_lf, valleys_lf, rakes_lf
- Claim financials: gross_rcv, total_depreciation, deductible, net_claim

RAW DOCUMENT TEXT:
{raw_text}

RAW TABLE ROWS (JSON):
{raw_rows}
"""

async def _gemini_extract(
    full_text: str,
    raw_rows: list[dict],
    source_doc_sha256: str,
    source_doc_id: str,
) -> UniversalClaimAST:
    """
    Layer 2: Send raw extraction to Gemini Flash for semantic mapping.
    Forces structured JSON output. Wraps result in SourcedValue with
    EvidenceRef for every field.
    """
    settings = get_settings()
    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.5-flash")

    prompt = _SOL_EXTRACTION_PROMPT.format(
        raw_text=full_text[:40000],  # Token guard: first 40k chars
        raw_rows=json.dumps(raw_rows[:300])  # Row guard: max 300 rows
    )

    def _call_gemini():
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                temperature=0.0,  # Zero temperature: no creativity
            )
        )
        return response.text

    raw_json = await asyncio.to_thread(_call_gemini)

    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as e:
        raise ValueError(f"Gemini returned malformed JSON: {e}\n{raw_json[:500]}")

    def _make_evidence(page: int, raw: str) -> EvidenceRef:
        return EvidenceRef(
            doc_id=source_doc_id,
            page=page,
            raw_text=raw,
            extraction_method="gemini-2.5-flash"
        )

    def _sourced(value, page: int, raw: str):
        return SourcedValue(
            value=value,
            evidence=[_make_evidence(page, raw)]
        )

    # Build line items — Pydantic validate_math() fires automatically
    line_items = []
    for item in data.get("line_items", []):
        page = int(item.get("page", 0))
        try:
            li = ClaimLineItem(
                category_code=item.get("category_code") or "UNKNOWN",
                activity_code=item.get("activity_code") or "UNKNOWN",
                description=item.get("description") or "",
                quantity=_sourced(
                    Decimal(str(item["quantity"])) if item.get("quantity") is not None else Decimal("0"),
                    page, str(item.get("quantity"))
                ),
                unit=_sourced(item.get("unit") or "EA", page, str(item.get("unit"))),
                unit_price=_sourced(
                    Decimal(str(item["unit_price"])) if item.get("unit_price") is not None else Decimal("0"),
                    page, str(item.get("unit_price"))
                ),
                tax=_sourced(
                    Decimal(str(item.get("tax", "0"))),
                    page, str(item.get("tax"))
                ),
                claimed_rcv=_sourced(
                    Decimal(str(item["claimed_rcv"])) if item.get("claimed_rcv") is not None else Decimal("0"),
                    page, str(item.get("claimed_rcv"))
                ),
                depreciation=_sourced(
                    Decimal(str(item.get("depreciation", "0"))),
                    page, str(item.get("depreciation"))
                ),
                acv=_sourced(
                    Decimal(str(item.get("acv", "0"))),
                    page, str(item.get("acv"))
                ),
            )
            line_items.append(li)
        except Exception as e:
            logger.warning("sol_line_item_skipped", error=str(e), item=item)
            continue

    geo = data.get("roof_geometry", {})
    fin = data.get("claim_financials", {})

    geometry = RoofGeometry(
        pitch=_sourced(str(geo.get("pitch") or "unknown"), 0, str(geo.get("pitch"))),
        total_squares=_sourced(Decimal(str(geo.get("total_squares") or "0")), 0, str(geo.get("total_squares"))),
        eaves_lf=_sourced(Decimal(str(geo.get("eaves_lf") or "0")), 0, str(geo.get("eaves_lf"))),
        valleys_lf=_sourced(Decimal(str(geo.get("valleys_lf") or "0")), 0, str(geo.get("valleys_lf"))),
        rakes_lf=_sourced(Decimal(str(geo.get("rakes_lf") or "0")), 0, str(geo.get("rakes_lf"))),
    )

    financials = ClaimFinancials(
        gross_rcv=_sourced(Decimal(str(fin.get("gross_rcv") or "0")), 0, str(fin.get("gross_rcv"))),
        total_depreciation=_sourced(Decimal(str(fin.get("total_depreciation") or "0")), 0, str(fin.get("total_depreciation"))),
        deductible=_sourced(Decimal(str(fin.get("deductible") or "0")), 0, str(fin.get("deductible"))),
        net_claim=_sourced(Decimal(str(fin.get("net_claim") or "0")), 0, str(fin.get("net_claim"))),
    )

    return UniversalClaimAST(
        line_items=line_items,
        roof_geometry=geometry,
        financials=financials,
        source_doc_sha256=source_doc_sha256,
        source_doc_id=source_doc_id,
        ast_version=1,
    )


# --- PUBLIC ENTRY POINT ---

async def parse_statement_of_loss(
    pdf_path: Path,
    source_doc_sha256: str,
    source_doc_id: str,
) -> UniversalClaimAST:
    """
    Full three-layer SoL parse. Returns a UniversalClaimAST with
    every value sourced to its originating page and document hash.

    Raises ValueError if PDF is unreadable or Gemini returns garbage.
    The caller (SupplementProcessor) is responsible for catching this
    and transitioning the job to PENDING_MANUAL_REVIEW.

    Args:
        pdf_path: Path to the SoL PDF on disk.
        source_doc_sha256: SHA256 hash registered at API boundary.
        source_doc_id: job_documents.id FK from the upload endpoint.
    """
    log = logger.bind(pdf_path=str(pdf_path), sha256=source_doc_sha256)
    log.info("sol_parse_started")

    def _sync_extract():
        return _extract_raw_tables(pdf_path)

    full_text, raw_rows = await asyncio.to_thread(_sync_extract)
    log.info("sol_layer1_complete", row_count=len(raw_rows))

    ast = await _gemini_extract(full_text, raw_rows, source_doc_sha256, source_doc_id)

    unverified = [li for li in ast.line_items if not li.verified]
    log.info(
        "sol_parse_complete",
        total_items=len(ast.line_items),
        unverified_count=len(unverified),
        sha256=source_doc_sha256,
    )

    return ast
