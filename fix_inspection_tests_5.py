filepath = 'tests/test_inspection_engine.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace("from unittest.mock import AsyncMock", "")

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print("Removed local AsyncMock imports.")
