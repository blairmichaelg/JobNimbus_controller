import ast
import os
import shutil

source_file = "app/services/pdf_generator.py"
with open(source_file, "r", encoding="utf-8") as f:
    lines = f.readlines()
    source_code = "".join(lines)

tree = ast.parse(source_code)
class_node = None
for node in tree.body:
    if isinstance(node, ast.ClassDef) and node.name == "PDFGenerator":
        class_node = node
        break

methods = []
for node in class_node.body:
    if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
        methods.append({"name": node.name, "start": node.lineno - 1, "node": node})

for i, m in enumerate(methods):
    if i < len(methods) - 1:
        m["end"] = methods[i+1]["start"]
    else:
        m["end"] = class_node.end_lineno

def get_method_code(name):
    for m in methods:
        if m["name"] == name:
            start_line = m["node"].lineno - 1
            if m["node"].decorator_list:
                start_line = m["node"].decorator_list[0].lineno - 1
            return "".join(lines[start_line:m["end"]])
    return ""

def get_base_methods():
    code = ""
    for m in methods:
        if m["name"].startswith("_") or m["name"] == "__init__":
            start_line = m["node"].lineno - 1
            if m["node"].decorator_list:
                start_line = m["node"].decorator_list[0].lineno - 1
            code += "".join(lines[start_line:m["end"]]) + "\n"
    return code

header_imports = "".join(lines[9:34])

engine_code = header_imports + "\nclass PDFEngine:\n" + get_base_methods()

invoice_code = header_imports + "from app.services.pdf.engine import PDFEngine\n\nclass InvoiceGenerator(PDFEngine):\n"
for name in ["generate_retail_quote", "generate_monthly_financial_summary", "generate_material_po", "generate_estimate_pdf"]:
    code = get_method_code(name)
    if code: invoice_code += code + "\n"

commission_code = header_imports + "from app.services.pdf.engine import PDFEngine\n\nclass CommissionGenerator(PDFEngine):\n"
for name in ["generate_commission_statement"]:
    code = get_method_code(name)
    if code: commission_code += code + "\n"

supplement_code = header_imports + "from app.services.pdf.engine import PDFEngine\n\nclass SupplementGenerator(PDFEngine):\n"
for name in ["generate_evidence_grid", "generate_inspection_letter", "generate_rebuttal_letter", "generate_escalation_letter", "generate_supplement_pdf"]:
    code = get_method_code(name)
    if code: supplement_code += code + "\n"

documents_code = header_imports + "from app.services.pdf.engine import PDFEngine\n\nclass DocumentsGenerator(PDFEngine):\n"
for name in ["generate_contingency_pdf", "generate_notice_of_cancellation", "generate_certificate_of_completion", "generate_contingency_agreement"]:
    code = get_method_code(name)
    if code: documents_code += code + "\n"

init_code = """from app.services.pdf.invoice import InvoiceGenerator
from app.services.pdf.supplement import SupplementGenerator
from app.services.pdf.commission import CommissionGenerator
from app.services.pdf.documents import DocumentsGenerator

class PDFGenerator(InvoiceGenerator, SupplementGenerator, CommissionGenerator, DocumentsGenerator):
    pass
"""

os.makedirs("app/services/pdf", exist_ok=True)
with open("app/services/pdf/engine.py", "w", encoding="utf-8") as f: f.write(engine_code)
with open("app/services/pdf/invoice.py", "w", encoding="utf-8") as f: f.write(invoice_code)
with open("app/services/pdf/supplement.py", "w", encoding="utf-8") as f: f.write(supplement_code)
with open("app/services/pdf/commission.py", "w", encoding="utf-8") as f: f.write(commission_code)
with open("app/services/pdf/documents.py", "w", encoding="utf-8") as f: f.write(documents_code)
with open("app/services/pdf/__init__.py", "w", encoding="utf-8") as f: f.write(init_code)

print("Split completed successfully!")
