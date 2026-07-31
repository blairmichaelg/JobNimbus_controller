import asyncio
from PIL import Image, ImageDraw
import os

# Create a realistic dummy image
img = Image.new('RGB', (800, 600), color = (100, 100, 100))
d = ImageDraw.Draw(img)
d.text((10,10), "Simulated Roof with hail impacts", fill=(255,255,0))
for i in range(50):
    d.ellipse((i*15, i*10, i*15+10, i*10+10), fill=(50,50,50))
img.save('test_hail_roof.jpg')

from app.services.ai_service import get_ai_client

async def main():
    ai = get_ai_client()
    print("Uploading file...")
    uploaded_name = await ai.upload_media_file("test_hail_roof.jpg")
    print(f"Uploaded: {uploaded_name}")
    
    print("Polling status...")
    status = await ai.get_file_status(uploaded_name)
    while status == "PROCESSING":
        await asyncio.sleep(2)
        status = await ai.get_file_status(uploaded_name)
    
    print(f"Status: {status}")
    if status == "ACTIVE":
        print("Analyzing...")
        analysis = await ai.analyze_roof_photo(uploaded_name, "test_hail_roof.jpg", "TEST-001")
        print("\n=== ANALYSIS RESULT ===")
        print(analysis.model_dump_json(indent=2))
        
    print("Cleaning up...")
    await ai.delete_file(uploaded_name)
    os.remove('test_hail_roof.jpg')
    print("Done.")

if __name__ == '__main__':
    asyncio.run(main())
