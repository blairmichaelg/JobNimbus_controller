import re

with open("app/api/office_routes.py", "r") as f:
    content = f.read()

# Remove verify_admin from router definition
content = content.replace(
    'router = APIRouter(prefix="/api/office", tags=["office_ux"], dependencies=[Depends(verify_admin)])',
    'router = APIRouter(prefix="/api/office", tags=["office_ux"])'
)

# Ensure verify_accounting is imported
if 'verify_accounting' not in content:
    content = content.replace(
        'from app.api.auth import verify_admin',
        'from app.api.auth import verify_admin, verify_accounting'
    )

# Use regex to find all @router decorators that do not already have dependencies
# This matches lines starting with @router. followed by anything up to the closing parenthesis.
# It handles multi-line decorators by matching up to the last closing parenthesis before `def`.
import ast

class RouteVisitor(ast.NodeTransformer):
    def __init__(self):
        super().__init__()
        
    def visit_FunctionDef(self, node):
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                if isinstance(dec.func.value, ast.Name) and dec.func.value.id == 'router':
                    # It's a router decorator. Check if it has 'dependencies'.
                    has_deps = any(k.arg == 'dependencies' for k in dec.keywords)
                    if not has_deps:
                        # Determine which dependency to use.
                        # Look at the path (args[0] of the decorator)
                        path = dec.args[0].value if dec.args else ""
                        if '/accounting' in path or '/commission' in path:
                            dep = "verify_accounting"
                        else:
                            dep = "verify_admin"
                        
                        # Add keyword argument
                        # Actually manipulating AST and unparsing is tricky if we want to preserve formatting.
                        pass
        return node

# We'll do it purely via regex to preserve formatting.
# Find @router.[method](...)
pattern = re.compile(r'(@router\.(get|post|patch|put|delete)\([^)]*?)(\))')

def replacer(match):
    inner = match.group(1)
    if 'dependencies=' in inner:
        return match.group(0)
    
    # Check if accounting route
    if '/accounting' in inner or '/commission' in inner:
        dep = 'verify_accounting'
    else:
        dep = 'verify_admin'
        
    if inner.endswith('('):
        return inner + f"dependencies=[Depends({dep})])"
    else:
        return inner + f", dependencies=[Depends({dep})])"

new_content = pattern.sub(replacer, content)

with open("app/api/office_routes.py", "w") as f:
    f.write(new_content)
