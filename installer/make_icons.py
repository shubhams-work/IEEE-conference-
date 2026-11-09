"""Build the app icons (.ico Windows, .icns macOS, .png Linux / window) and the
logo shown in the app window.

If installer/assets/logo_source.(png|jpg) exists, the icons are made from that
logo (cropped to its content, centred on a white rounded square so it is
visible on dark and light backgrounds). Otherwise a default icon is drawn.
"""
import os

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "assets")
S = 1024


def find_source():
    for name in ("logo_source.png", "logo_source.jpg", "logo_source.jpeg"):
        p = os.path.join(OUT, name)
        if os.path.isfile(p):
            return p
    return None


def crop_logo(path):
    """Crop to the main logo: the largest band of non-white rows (drops stray text)."""
    im = Image.open(path).convert("RGB")
    a = np.asarray(im.convert("L"))
    ink_rows = (a < 200).sum(axis=1) > 0
    bands, start = [], None
    for i, v in enumerate(ink_rows):
        if v and start is None:
            start = i
        elif not v and start is not None:
            bands.append((start, i))
            start = None
    if start is not None:
        bands.append((start, len(ink_rows)))
    top, bottom = max(bands, key=lambda b: b[1] - b[0])
    cols = np.where((a[top:bottom] < 200).sum(axis=0) > 0)[0]
    left, right = int(cols.min()), int(cols.max()) + 1
    return im.crop((left, top, right, bottom))


def icon_from_logo(logo):
    canvas = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.2), fill=255)
    white = Image.new("RGBA", (S, S), (255, 255, 255, 255))
    canvas.paste(white, (0, 0), mask)
    pad = int(S * 0.06)
    box = S - 2 * pad
    scale = box / max(logo.width, logo.height)          # enlarge or shrink to fill the box
    lg = logo.resize((max(1, round(logo.width * scale)), max(1, round(logo.height * scale))),
                     Image.LANCZOS)
    canvas.paste(lg, ((S - lg.width) // 2, (S - lg.height) // 2))
    return canvas


def default_icon():
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([170, 70, 854, 954], radius=60, fill=(255, 255, 255, 255),
                        outline=(40, 70, 120, 255), width=28)
    d.polygon([(694, 70), (854, 230), (694, 230)], fill=(205, 218, 238, 255))
    d.rounded_rectangle([270, 170, 640, 215], radius=20, fill=(40, 70, 120, 255))
    for col_x in (270, 527):
        for i in range(9):
            y = 290 + i * 62
            w = 200 if i % 4 != 3 else 130
            d.rounded_rectangle([col_x, y, col_x + w, y + 26], radius=13, fill=(150, 165, 190, 255))
    d.ellipse([520, 560, 940, 980], fill=(46, 160, 67, 255), outline=(255, 255, 255, 255), width=24)
    d.line([(615, 775), (705, 865), (850, 680)], fill=(255, 255, 255, 255), width=64, joint="curve")
    return im


def main():
    os.makedirs(OUT, exist_ok=True)
    src = find_source()
    if src:
        logo = crop_logo(src)
        icon = icon_from_logo(logo)
        banner = logo.copy()
        banner.thumbnail((400, 120), Image.LANCZOS)
        rgba = np.asarray(banner.convert("RGBA")).copy()
        light = rgba[..., :3].min(axis=2)                  # white background -> transparent
        rgba[..., 3] = np.clip((255 - light.astype(int)) * 6, 0, 255).astype(np.uint8)
        banner = Image.fromarray(rgba, "RGBA")
        banner.save(os.path.join(OUT, "logo_banner.png"))       # shown in the app window
    else:
        icon = default_icon()
        icon.resize((256, 256), Image.LANCZOS).save(os.path.join(OUT, "logo_banner.png"))
    icon.save(os.path.join(OUT, "icon.png"))
    icon.resize((256, 256), Image.LANCZOS).save(os.path.join(OUT, "icon_256.png"))
    icon.save(os.path.join(OUT, "icon.ico"),
              sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    icon.save(os.path.join(OUT, "icon.icns"))
    print("icons written to", OUT, "(from logo)" if src else "(default)")


if __name__ == "__main__":
    main()
