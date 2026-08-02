from PIL import Image
import os

def resize_with_pad(img, target_size):
    """
    Resizes image to fit within target_size (square), maintaining aspect ratio,
    and pads the rest with transparent pixels.
    """
    target_w, target_h = target_size
    img.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)
    
    # Create a transparent background image
    new_img = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    
    # Paste the resized image onto the center of the transparent background
    paste_x = (target_w - img.width) // 2
    paste_y = (target_h - img.height) // 2
    new_img.paste(img, (paste_x, paste_y))
    return new_img

if __name__ == "__main__":
    logo_path = "app/static/logo.png"
    if not os.path.exists(logo_path):
        print(f"File not found: {logo_path}")
        exit(1)
        
    img = Image.open(logo_path).convert("RGBA")
    
    icon_192 = resize_with_pad(img, (192, 192))
    icon_192.save("app/static/icon-192.png", format="PNG")
    print("Created app/static/icon-192.png")
    
    icon_512 = resize_with_pad(img, (512, 512))
    icon_512.save("app/static/icon-512.png", format="PNG")
    print("Created app/static/icon-512.png")
