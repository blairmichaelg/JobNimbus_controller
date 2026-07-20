import re

with open('scripts/install_google_drive.ps1', 'r', encoding='utf-8') as f:
    content = f.read()

content = re.sub(r'[\u201c\u201d\u201e\u201f]', '"', content)
content = re.sub(r'[\u2018\u2019\u201a\u201b]', "'", content)

with open('scripts/install_google_drive.ps1', 'w', encoding='utf-8') as f:
    f.write(content)
