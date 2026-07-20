with open(r'tests\test_phase8.py', 'rb') as f:
    content = f.read().decode('utf-8')

# Find the field_cookie fixture and show it
idx = content.find('def field_cookie')
if idx != -1:
    print(repr(content[idx-30:idx+300]))
else:
    print('NOT FOUND')
