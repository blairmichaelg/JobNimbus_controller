import os

original = "app/services/pdf_generator.py"
with open(original, "r", encoding="utf-8") as f:
    lines = f.readlines()
    
header_imports = "".join(lines[9:34])

files = ["engine.py", "invoice.py", "commission.py", "supplement.py", "documents.py"]
for fn in files:
    path = f"app/services/pdf/{fn}"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # remove the existing header (everything before 'logger = structlog...')
    idx = content.find('logger = structlog.get_logger("app.services.pdf")')
    if idx != -1:
        new_content = header_imports + "\n" + content[idx:]
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
    
print("Imports fixed!")
