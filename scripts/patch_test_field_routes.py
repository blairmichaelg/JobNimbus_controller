with open(r'tests\test_field_routes.py', 'rb') as f:
    content = f.read().decode('utf-8')

OLD = (
    'client = TestClient(app)\n'
    'response = client.post("/auth/login", data={"pin": "3333", "redirect_url": "/"}, follow_redirects=False)\n'
    'auth_cookie = response.cookies.get("auth_token")\n'
    'client.cookies.set("auth_token", auth_cookie)\n'
)

NEW = (
    'client = TestClient(app)\n'
    '\n'
    '# Phase 9: static field_pin is retired. Seed a field rep before login.\n'
    'from app.core.database import create_field_rep, get_field_rep_by_pin  # noqa: E402\n'
    'from app.core.cache import init_db as _init_cache\n'
    'from app.core.database import init_db as _init_crm\n'
    '_init_cache()\n'
    '_init_crm()\n'
    'if not get_field_rep_by_pin("3333"):\n'
    '    try:\n'
    '        create_field_rep("Field Test Rep", "3333")\n'
    '    except Exception:\n'
    '        pass  # Already exists or other error\n'
    'response = client.post("/auth/login", data={"pin": "3333", "redirect_url": "/"}, follow_redirects=False)\n'
    'auth_cookie = response.cookies.get("auth_token")\n'
    'client.cookies.set("auth_token", auth_cookie)\n'
)

if OLD in content:
    content = content.replace(OLD, NEW, 1)
    with open(r'tests\test_field_routes.py', 'wb') as f:
        f.write(content.encode('utf-8'))
    print('Patch applied: test_field_routes.py module-level rep seed')
else:
    print('OLD not found')
    idx = content.find('client = TestClient(app)')
    print(repr(content[idx:idx+300]))
