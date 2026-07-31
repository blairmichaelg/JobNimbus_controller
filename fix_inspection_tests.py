filepath = 'tests/test_inspection_engine.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace("mock_ai.client.files.upload.return_value = mock_uploaded", "mock_ai.upload_media_file = AsyncMock(return_value='files/test123')")
content = content.replace("mock_ai.client.files.get.return_value = mock_file_info", "mock_ai.get_file_status = AsyncMock(return_value='ACTIVE')")
content = content.replace("mock_ai.client.files.upload.assert_called_once()", "mock_ai.upload_media_file.assert_called_once()")
content = content.replace("mock_ai.client.files.get.assert_called_with(name=\"files/test123\")", "mock_ai.get_file_status.assert_called_with('files/test123')")
content = content.replace("mock_ai.client.files.delete.assert_called_once_with(name=\"files/test123\")", "mock_ai.delete_file.assert_called_once_with('files/test123')")

content = content.replace("mock_ai.client.files.delete.assert_called_once_with(name=\"files/bad\")", "mock_ai.delete_file.assert_called_once_with('files/bad')")
content = content.replace("mock_ai.client.files.delete.assert_called_once_with(name=\"files/error\")", "mock_ai.delete_file.assert_called_once_with('files/error')")
content = content.replace("mock_ai.client.files.upload.assert_not_called()", "mock_ai.upload_media_file.assert_not_called()")
content = content.replace("assert mock_ai.client.files.upload.call_count == 3", "assert mock_ai.upload_media_file.call_count == 3")
content = content.replace("assert mock_ai.client.files.delete.call_count == 3", "assert mock_ai.delete_file.call_count == 3")

content = content.replace("mock_ai.upload_media_file = AsyncMock(return_value='files/test123')", "mock_ai.upload_media_file = AsyncMock(return_value='files/test123')\n        mock_ai.delete_file = AsyncMock(return_value=None)")
# We have multiple tests setting up the mock, so we should just ensure delete_file is mocked as async.
# Actually, if we just set mock_ai = MagicMock(), any method called on it will return a MagicMock, not an AsyncMock.
# We need to set them to AsyncMock explicitly.

# A better way is just replacing the exact strings.
content = content.replace("mock_ai._call_with_backoff.side_effect", "mock_ai.analyze_roof_photo.side_effect")

# Let's write a targeted script to just ensure the mock methods are AsyncMocks in all 4 tests
with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated test mocks in test_inspection_engine.py")
