filepath = 'tests/test_inspection_engine.py'
with open(filepath, 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if "def test_failed_processing_skips_photo" in line:
        for j in range(i, i+30):
            if "mock_ai.upload_media_file = AsyncMock(return_value='files/test123')" in lines[j]:
                lines[j] = "        mock_ai.upload_media_file = AsyncMock(return_value='files/bad')\n"
            if "mock_ai.get_file_status = AsyncMock(return_value='ACTIVE')" in lines[j] and j > i+20:
                lines[j] = "        mock_ai.get_file_status = AsyncMock(return_value='FAILED')\n"
        break

with open(filepath, 'w', encoding='utf-8') as f:
    f.writelines(lines)
print("test_failed_processing_skips_photo fixed.")
