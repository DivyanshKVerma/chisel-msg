"""
Generate Android launcher icons and splash screens from the Chisel logo.
Run from mobile/:  ../.venv/bin/python make-icons.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

LOGO = Image.open("../web/icons/chisel-logo-source.webp").convert("RGBA")
RES = Path("android/app/src/main/res")
BLACK = (0, 0, 0, 255)

DENSITIES = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}


def logo(size):
    return LOGO.resize((size, size), Image.LANCZOS)


def on_canvas(w, h, logo_px, bg=BLACK):
    canvas = Image.new("RGBA", (w, h), bg)
    lg = logo(logo_px)
    canvas.alpha_composite(lg, ((w - logo_px) // 2, (h - logo_px) // 2))
    return canvas


for name, scale in DENSITIES.items():
    d = RES / f"mipmap-{name}"
    legacy = round(48 * scale)
    logo(legacy).convert("RGB").save(d / "ic_launcher.png", optimize=True)
    # Round icon: circular crop of the full logo
    rnd = logo(legacy)
    mask = Image.new("L", (legacy, legacy), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, legacy - 1, legacy - 1), fill=255)
    out = Image.new("RGBA", (legacy, legacy), (0, 0, 0, 0))
    out.paste(rnd, (0, 0), mask)
    out.save(d / "ic_launcher_round.png", optimize=True)
    # Adaptive foreground: 108dp canvas, logo inside the 72dp-ish visible area,
    # on transparent so it sits on the black adaptive background layer.
    fg = round(108 * scale)
    on_canvas(fg, fg, round(fg * 0.70), bg=(0, 0, 0, 0)).save(d / "ic_launcher_foreground.png", optimize=True)

(RES / "values" / "ic_launcher_background.xml").write_text(
    '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <color name="ic_launcher_background">#000000</color>\n</resources>\n'
)

# Splash screens: logo centred on black, 35% of the shorter side
for png in RES.glob("drawable*/splash.png"):
    w, h = Image.open(png).size
    on_canvas(w, h, round(min(w, h) * 0.35)).convert("RGB").save(png, optimize=True)

print("Android icons and splash screens generated")
