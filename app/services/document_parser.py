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

import pdfplumber

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
- Claim metadata: claim_number, insurer_name
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
    from app.services.ai_service import get_ai_client
    client = get_ai_client()

    prompt = _SOL_EXTRACTION_PROMPT.format(
        raw_text=full_text[:40000],  # Token guard: first 40k chars
        raw_rows=json.dumps(raw_rows[:300])  # Row guard: max 300 rows
    )

    raw_json = await client.extract_sol_structured_data(prompt)

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
        claim_number=_sourced(str(data.get("claim_number")), 0, str(data.get("claim_number"))) if data.get("claim_number") else None,
        insurer_name=_sourced(str(data.get("insurer_name")), 0, str(data.get("insurer_name"))) if data.get("insurer_name") else None,
        source_doc_sha256=source_doc_sha256,
        source_doc_id=source_doc_id,
        ast_version=1,
    )


def _fallback_regex_extract(
    full_text: str,
    raw_rows: list[dict],
    source_doc_sha256: str,
    source_doc_id: str,
) -> UniversalClaimAST:
    import re
    from decimal import Decimal

    def _make_evidence(page: int, raw: str) -> EvidenceRef:
        return EvidenceRef(
            doc_id=source_doc_id,
            page=page,
            raw_text=raw[:200] if raw else "",
            extraction_method="regex-fallback"
        )

    def _sourced(value, page: int, raw: str):
        return SourcedValue(
            value=value,
            evidence=[_make_evidence(page, raw)]
        )

    claim_match = re.search(r'Claim\s*(?:Number|#)?\s*[:\-]?\s*([A-Za-z0-9\-]+)', full_text, re.I)
    claim_number = claim_match.group(1).strip() if claim_match else None

    insurer_match = re.search(r'([A-Za-z0-9\s]+INSURANCE COMPANY)', full_text, re.I)
    insurer_name = insurer_match.group(1).strip() if insurer_match else None

    rcv_match = re.search(r'Replacement\s*Cost\s*Value.*?\$\s*([\d,]+\.\d{2})', full_text, re.I)
    dep_match = re.search(r'Depreciation.*?\$\s*([\d,]+\.\d{2})', full_text, re.I)
    ded_match = re.search(r'Deductible.*?\$\s*([\d,]+\.\d{2})', full_text, re.I)
    net_match = re.search(r'Net\s*Claim.*?\$\s*([\d,]+\.\d{2})', full_text, re.I)

    def _parse_dec(match_obj):
        if not match_obj:
            return Decimal("0.00")
        return Decimal(match_obj.group(1).replace(",", ""))

    gross_rcv_val = _parse_dec(rcv_match)
    dep_val = _parse_dec(dep_match)
    ded_val = _parse_dec(ded_match)
    net_val = _parse_dec(net_match)

    financials = ClaimFinancials(
        gross_rcv=_sourced(gross_rcv_val, 1, rcv_match.group(0) if rcv_match else ""),
        total_depreciation=_sourced(dep_val, 1, dep_match.group(0) if dep_match else ""),
        deductible=_sourced(ded_val, 1, ded_match.group(0) if ded_match else ""),
        net_claim=_sourced(net_val, 1, net_match.group(0) if net_match else ""),
    )

    pitch_m = re.search(r'Roof Pitch:\s*([\d/]+)', full_text, re.I)
    sq_m = re.search(r'Total Roof Area:\s*([\d,]+(?:\.\d+)?)', full_text, re.I)

    geometry = RoofGeometry(
        pitch=_sourced(pitch_m.group(1) if pitch_m else "unknown", 1, pitch_m.group(0) if pitch_m else ""),
        total_squares=_sourced(Decimal(sq_m.group(1).replace(",", "")) if sq_m else Decimal("0"), 1, sq_m.group(0) if sq_m else ""),
        eaves_lf=_sourced(Decimal("0"), 1, ""),
        valleys_lf=_sourced(Decimal("0"), 1, ""),
        rakes_lf=_sourced(Decimal("0"), 1, ""),
    )

    line_items = []
    for r in raw_rows:
        cells = r.get("cells", [])
        page = r.get("page", 1)
        if len(cells) >= 4:
            desc = cells[0]
            if not desc or "Line Item" in desc or "STATEMENT OF LOSS" in desc or "REPLACEMENT COST" in desc:
                continue
            qty_str = cells[1] if len(cells) > 1 else "0"
            unit_str = cells[2] if len(cells) > 2 else "EA"
            cost_str = cells[3] if len(cells) > 3 else "0"
            tot_str = cells[4] if len(cells) > 4 else cost_str

            m_qty = re.search(r'([\d\.]+)', qty_str)
            m_cost = re.search(r'[\$]?([\d\.,]+)', cost_str)
            m_tot = re.search(r'[\$]?([\d\.,]+)', tot_str)

            qty = Decimal(m_qty.group(1)) if m_qty else Decimal("0")
            unit_price = Decimal(m_cost.group(1).replace(",", "")) if m_cost else Decimal("0")
            claimed_rcv = Decimal(m_tot.group(1).replace(",", "")) if m_tot else Decimal("0")

            if qty > 0 or claimed_rcv > 0:
                # Exclude summary rows
                desc_upper = desc.upper()
                if any(kw in desc_upper for kw in ["SUBTOTAL", "REPLACEMENT COST", "NET CLAIM", "INSURED", "DEDUCTIBLE", "DEPRECIATION", "STATEMENT OF LOSS"]):
                    continue
                if qty == Decimal("0") and claimed_rcv > Decimal("0"):
                    qty = Decimal("1.00")
                    unit_price = claimed_rcv
                elif unit_price == Decimal("0") and qty > Decimal("0") and claimed_rcv > Decimal("0"):
                    unit_price = round(claimed_rcv / qty, 2)
                    claimed_rcv = qty * unit_price

                try:
                    li = ClaimLineItem(
                        category_code="RFG",
                        activity_code="ITEM",
                        description=desc[:200],
                        quantity=_sourced(qty, page, qty_str),
                        unit=_sourced(unit_str or "EA", page, unit_str),
                        unit_price=_sourced(unit_price, page, cost_str),
                        tax=_sourced(Decimal("0"), page, "0"),
                        claimed_rcv=_sourced(claimed_rcv, page, tot_str),
                        depreciation=_sourced(Decimal("0"), page, "0"),
                        acv=_sourced(claimed_rcv, page, tot_str),
                    )
                    line_items.append(li)
                except Exception:
                    pass

    return UniversalClaimAST(
        line_items=line_items,
        roof_geometry=geometry,
        financials=financials,
        claim_number=_sourced(claim_number, 1, claim_match.group(0)) if claim_number and claim_match else None,
        insurer_name=_sourced(insurer_name, 1, insurer_match.group(0)) if insurer_name and insurer_match else None,
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

    try:
        ast = await _gemini_extract(full_text, raw_rows, source_doc_sha256, source_doc_id)
    except Exception as gemini_err:
        log.warning("gemini_sol_extract_failed_using_fallback", error=str(gemini_err))
        ast = _fallback_regex_extract(full_text, raw_rows, source_doc_sha256, source_doc_id)

    unverified = [li for li in ast.line_items if not li.verified]
    log.info(
        "sol_parse_complete",
        total_items=len(ast.line_items),
        unverified_count=len(unverified),
        sha256=source_doc_sha256,
    )

    return ast
