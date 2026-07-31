import ast

filepath = 'tests/test_ai_service.py'
with open(filepath, 'a', encoding='utf-8') as f:
    f.write('''
def test_photo_processor_abstraction():
    \"\"\"Verify that photo_processor.py does not import google.genai directly.\"\"\"
    import ast
    with open("app/workers/photo_processor.py", "r") as f:
        tree = ast.parse(f.read())
        
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "google.genai" not in alias.name, "Found direct google.genai import!"
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert "google.genai" not in node.module, "Found direct google.genai import!"
        elif isinstance(node, ast.Attribute):
            # Also ensure ai.client is not accessed
            if getattr(node, "attr", "") == "client":
                if isinstance(node.value, ast.Name) and getattr(node.value, "id", "") == "ai":
                    pytest.fail("Found direct ai.client access!")
''')
print("Added test to test_ai_service.py")
