filepath = 'tests/test_inspection_engine.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace("mock_ai.delete_file.assert_called_once_with('files/error')", "mock_ai.delete_file.assert_called_once_with('files/test123')")

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print("Assertion fixed.")
