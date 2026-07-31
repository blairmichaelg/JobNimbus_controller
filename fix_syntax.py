filepath = 'app/services/ai_service.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace("async async def", "async def")

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print("Fixed double async")
