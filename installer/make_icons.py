"""Draw the app icon (two-column paper page + check mark) and save it as
.ico (Windows), .icns (macOS) and .png (Linux)."""
import os
from PIL import Image, ImageDraw

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
os.makedirs(out, exist_ok=True)
S = 1024
im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(im)
# page with folded corner
d.rounded_rectangle([170, 70, 854, 954], radius=60, fill=(255, 255, 255, 255),
                    outline=(40, 70, 120, 255), width=28)
d.polygon([(694, 70), (854, 230), (694, 230)], fill=(205, 218, 238, 255))
# title bar + two text columns
d.rounded_rectangle([270, 170, 640, 215], radius=20, fill=(40, 70, 120, 255))
for col_x in (270, 527):
    for i in range(9):
        y = 290 + i * 62
        w = 200 if i % 4 != 3 else 130
        d.rounded_rectangle([col_x, y, col_x + w, y + 26], radius=13, fill=(150, 165, 190, 255))
# green check badge
d.ellipse([520, 560, 940, 980], fill=(46, 160, 67, 255), outline=(255, 255, 255, 255), width=24)
d.line([(615, 775), (705, 865), (850, 680)], fill=(255, 255, 255, 255), width=64, joint="curve")
im.save(os.path.join(out, "icon.png"))
im.resize((256, 256), Image.LANCZOS).save(os.path.join(out, "icon_256.png"))
im.save(os.path.join(out, "icon.ico"),
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
im.save(os.path.join(out, "icon.icns"))
print("icons written to", out)
