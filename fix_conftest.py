filepath = 'tests/conftest.py'
with open(filepath, 'a', encoding='utf-8') as f:
    f.write('''
@pytest.fixture(autouse=True)
def clear_rate_limits():
    \"\"\"Clear rate limits before every test.\"\"\"
    try:
        from app.services.rate_limit import _request_history
        _request_history.clear()
    except ImportError:
        pass
''')
print("Added clear_rate_limits to conftest.py")
