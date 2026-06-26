import os
import re
from pathlib import Path
import structlog
from app.core.supplement_models import DiscrepancyReport

logger = structlog.get_logger("app.core.code_router")

# Map discrepancy categories to specific XML tags required for justification
DISCREPANCY_TO_CODE_MAP = {
    "Missing Drip Edge": ["SECTION_R905_2_8_5", "GA_R905_2_8_5"],
    "Missing Ice & Water Shield": ["SECTION_R905_2_8_2"],
    "Area Shortage": ["SECTION_R905_2_2"],
    "Ridge/Hip Cap Shortage": ["SECTION_R905_2_2"],
    "Missing O&P": []
}

def parse_code_files(directory_path: str = "building_codes") -> dict[str, str]:
    """
    Reads all .txt files in the directory and extracts XML tags and their contents.
    Returns a dictionary mapping tag names to their inner text.
    """
    code_index = {}
    dir_path = Path(directory_path)
    
    if not dir_path.exists():
        logger.warning("code_router_dir_not_found", path=directory_path)
        return code_index
        
    # Match <TAG_NAME>content</TAG_NAME> across multiple lines
    tag_pattern = re.compile(r"<([A-Z0-9_]+)>(.*?)</\1>", re.DOTALL)
    
    for txt_file in dir_path.glob("*.txt"):
        try:
            content = txt_file.read_text(encoding="utf-8")
            matches = tag_pattern.findall(content)
            for tag, text in matches:
                code_index[tag.strip()] = text.strip()
        except Exception as e:
            logger.error("code_router_parse_error", file=txt_file.name, error=str(e))
            
    return code_index

def get_relevant_codes(report: DiscrepancyReport, code_index: dict[str, str]) -> str:
    """
    Looks up required XML tags based on the report's discrepancies,
    retrieves the text from the index, and concatenates them.
    Ensures no duplicate codes are appended.
    """
    required_tags = set()
    for disc in report.discrepancies:
        if disc.category in DISCREPANCY_TO_CODE_MAP:
            for tag in DISCREPANCY_TO_CODE_MAP[disc.category]:
                required_tags.add(tag)
                
    relevant_texts = []
    for tag in sorted(list(required_tags)): # Sort for deterministic output
        if tag in code_index:
            relevant_texts.append(f"<{tag}>\n{code_index[tag]}\n</{tag}>")
            
    return "\n\n".join(relevant_texts)
