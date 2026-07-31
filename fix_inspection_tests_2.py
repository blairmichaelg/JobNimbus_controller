import re

filepath = 'tests/test_inspection_engine.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace all mock setups
def replace_setup(match):
    return "        mock_ai.upload_media_file = AsyncMock(return_value='files/test123')\n        mock_ai.delete_file = AsyncMock()\n        mock_ai.get_file_status = AsyncMock(return_value='ACTIVE')"

content = re.sub(
    r"        mock_ai\.upload_media_file = AsyncMock\(return_value='files/test123'\)\n        mock_ai\.delete_file = AsyncMock\(return_value=None\)\n        mock_ai\.get_file_status = AsyncMock\(return_value='ACTIVE'\)",
    replace_setup,
    content
)

# Actually, let's just make a targeted regex for the mock setup in those 4 tests.
content = content.replace("mock_ai.upload_media_file = AsyncMock(return_value='files/test123')\n        mock_ai.delete_file = AsyncMock(return_value=None)", "mock_ai.upload_media_file = AsyncMock(return_value='files/test123')\n        mock_ai.delete_file = AsyncMock()\n        mock_ai.get_file_status = AsyncMock(return_value='ACTIVE')")

# For test_failed_processing_skips_photo
content = content.replace(
    "        mock_ai.upload_media_file = AsyncMock(return_value='files/bad')\n        mock_ai.get_file_status = AsyncMock(return_value='FAILED')",
    "        mock_ai.upload_media_file = AsyncMock(return_value='files/bad')\n        mock_ai.get_file_status = AsyncMock(return_value='FAILED')\n        mock_ai.delete_file = AsyncMock()"
)

# For test_multiple_photos_sequential
content = content.replace(
    "        mock_ai.upload_media_file = AsyncMock(return_value='files/test123')",
    "        mock_ai.upload_media_file = AsyncMock(return_value='files/test123')\n        mock_ai.delete_file = AsyncMock()\n        mock_ai.get_file_status = AsyncMock(return_value='ACTIVE')"
)
# Cleanup duplicates
content = content.replace(
    "        mock_ai.delete_file = AsyncMock()\n        mock_ai.get_file_status = AsyncMock(return_value='ACTIVE')\n        mock_ai.delete_file = AsyncMock()\n        mock_ai.get_file_status = AsyncMock(return_value='ACTIVE')",
    "        mock_ai.delete_file = AsyncMock()\n        mock_ai.get_file_status = AsyncMock(return_value='ACTIVE')"
)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated test mocks.")
