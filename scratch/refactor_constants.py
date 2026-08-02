import os
import re

constants_code = """from pathlib import Path
COMPANY_NAME = "Wickham Roofing"
COMPANY_PHONE = "1-800-ROOFING"
COMPANY_EMAIL = "billing@wickhamroofing.com"
FIELD_DOCS_DIR = Path("data/field_docs")
"""

with open("app/services/pdf/constants.py", "w", encoding="utf-8") as f:
    f.write(constants_code)

files = ["engine.py", "invoice.py", "commission.py", "supplement.py", "documents.py"]
for fn in files:
    path = f"app/services/pdf/{fn}"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Remove the constants definition
    content = re.sub(r'COMPANY_NAME = "Wickham Roofing"\nCOMPANY_PHONE = "1-800-ROOFING"\nCOMPANY_EMAIL = "billing@wickhamroofing.com"\n\nFIELD_DOCS_DIR = Path\("data/field_docs"\)', '', content)
    
    # Add import
    content = content.replace('logger = structlog.get_logger("app.services.pdf_generator")', 'logger = structlog.get_logger("app.services.pdf")\nfrom app.services.pdf.constants import COMPANY_NAME, COMPANY_PHONE, COMPANY_EMAIL, FIELD_DOCS_DIR')
    
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
        
print("Constants refactored!")
