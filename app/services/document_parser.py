import structlog
from pathlib import Path
from typing import Dict, Any

logger = structlog.get_logger("app.services.document_parser")

class DocumentParser:
    """
    Tiered extraction pipeline for incoming documents.
    Prevents blindly sending large PDFs to LLMs by routing based on document structure.
    """
    
    @staticmethod
    def classify_and_route_document(file_path: Path) -> Dict[str, Any]:
        """
        Classifies a document and routes it to the appropriate extraction tier.
        """
        suffix = file_path.suffix.lower()
        
        # Tier 0: Deterministic XML/Archive
        if suffix in ['.esx', '.xml']:
            return DocumentParser._tier_0_parse_esx(file_path)
            
        # For PDFs, we need to determine if it's digital or scanned
        if suffix == '.pdf':
            if DocumentParser._is_digital_pdf(file_path):
                return DocumentParser._tier_1_parse_digital_pdf(file_path)
            else:
                return DocumentParser._tier_2_parse_scanned_pdf(file_path)
                
        raise ValueError(f"Unsupported document format: {suffix}")

    @staticmethod
    def _is_digital_pdf(file_path: Path) -> bool:
        """
        Heuristic check: Try to extract text using pdfplumber. 
        If we get meaningful text, it's digital. If empty, it's a scanned image.
        """
        try:
            import pdfplumber
            with pdfplumber.open(file_path) as pdf:
                if len(pdf.pages) > 0:
                    text = pdf.pages[0].extract_text()
                    if text and len(text.strip()) > 50:
                        return True
        except Exception as e:
            logger.warning("digital_pdf_check_failed", error=str(e))
        return False

    @staticmethod
    def _tier_0_parse_esx(file_path: Path) -> Dict[str, Any]:
        """Bypass AI entirely. Parse Xactimate ESX/XML deterministically."""
        logger.info("routing_tier_0_esx", path=str(file_path))
        # Simulated parsing logic
        return {"tier": 0, "status": "parsed_esx"}

    @staticmethod
    def _tier_1_parse_digital_pdf(file_path: Path) -> Dict[str, Any]:
        """Extract structured text/tables using pdfplumber."""
        logger.info("routing_tier_1_digital_pdf", path=str(file_path))
        # Simulated extraction
        return {"tier": 1, "status": "parsed_digital_pdf"}

    @staticmethod
    def _tier_2_parse_scanned_pdf(file_path: Path) -> Dict[str, Any]:
        """
        Extract OCR bounding boxes and table layouts via Docling.
        Simulated here. If confidence is low or tables are ambiguous, route to Tier 3.
        """
        logger.info("routing_tier_2_scanned_pdf", path=str(file_path))
        
        # Simulated layout extraction
        confidence = 0.95
        
        if confidence < 0.80:
            return DocumentParser._tier_3_gemini_fallback(file_path)
            
        return {"tier": 2, "status": "parsed_scanned_pdf"}

    @staticmethod
    def _tier_3_gemini_fallback(file_path: Path) -> Dict[str, Any]:
        """
        Targeted Gemini 2.5 Pro fallback using structured JSON schema coercion.
        Only sends cropped/ambiguous regions, forces Gemini to return ONLY raw strings/boxes.
        """
        logger.info("routing_tier_3_gemini", path=str(file_path))
        # Simulated Gemini call using strict JSON schema coercion
        return {"tier": 3, "status": "parsed_gemini"}
