with open(r'tests\test_phase8.py', 'rb') as f:
    content = f.read().decode('utf-8')

OLD = (
    '@pytest.fixture(scope="module")\n'
    'def field_cookie():\n'
    '    res = client.post(\n'
    '        "/auth/login",\n'
    '        data={"pin": "3333", "redirect_url": "/"},\n'
    '        follow_redirects=False,\n'
    '    )\n'
    '    return res.cookies.get("auth_token")\n'
)

NEW = (
    '@pytest.fixture(scope="module")\n'
    'def field_cookie():\n'
    '    # Phase 9: static field_pin is retired from auth.\n'
    '    # Seed a field rep with PIN 3333 so the login succeeds.\n'
    '    from app.core.database import create_field_rep, get_field_rep_by_pin\n'
    '    if not get_field_rep_by_pin("3333"):\n'
    '        try:\n'
    '            create_field_rep("Phase8 Test Rep", "3333")\n'
    '        except ValueError:\n'
    '            pass  # Already exists\n'
    '    res = client.post(\n'
    '        "/auth/login",\n'
    '        data={"pin": "3333", "redirect_url": "/"},\n'
    '        follow_redirects=False,\n'
    '    )\n'
    '    return res.cookies.get("auth_token")\n'
)

if OLD in content:
    content = content.replace(OLD, NEW, 1)
    with open(r'tests\test_phase8.py', 'wb') as f:
        f.write(content.encode('utf-8'))
    print('Patch applied successfully.')
else:
    print('OLD string NOT FOUND.')
    print('Searching for partial match...')
    idx = content.find('def field_cookie')
    print(repr(content[idx:idx+300]))
