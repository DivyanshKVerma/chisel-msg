"""
Generate every CHISEL icon from the two source artworks (v1.1):
  web/icons/chisel-icon.svg      → rasterised to web/icons/chisel-icon-source.png (1080², blue square)
  web/icons/chisel-wordmark.svg  → rasterised to web/icons/chisel-wordmark.png (white wordmark, transparent)
Outputs: web icons + favicon, Android launcher icons (legacy, round, adaptive),
splash screens, and the white status-bar icon used by notifications.
Run from mobile/:  ../.venv/bin/python make-icons.py
"""
import base64
import re
from pathlib import Path

from PIL import Image, ImageDraw

WEB = Path("../web/icons")
RES = Path("android/app/src/main/res")
BLUE = (29, 112, 184, 255)  # #1d70b8, CHISEL blue
ICON = Image.open(WEB / "chisel-icon-source.png").convert("RGBA")
WORD = Image.open(WEB / "chisel-wordmark.png").convert("RGBA")
DENSITIES = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}


def icon(size):
    return ICON.resize((size, size), Image.LANCZOS)


def wordmark_on(w, h, word_w, bg):
    """The wordmark centred on a w×h canvas, word_w pixels wide."""
    canvas = Image.new("RGBA", (w, h), bg)
    wm = WORD.resize((word_w, round(WORD.height * word_w / WORD.width)), Image.LANCZOS)
    canvas.alpha_composite(wm, ((w - wm.width) // 2, (h - wm.height) // 2))
    return canvas


# ── web ───────────────────────────────────────────────────
icon(192).convert("RGB").save(WEB / "icon-192.png", optimize=True)
icon(512).convert("RGB").save(WEB / "icon-512.png", optimize=True)
icon(180).convert("RGB").save(WEB / "apple-touch-icon.png", optimize=True)
# Maskable: keep the wordmark inside the 80% safe circle
wordmark_on(512, 512, round(512 * 0.62), BLUE).convert("RGB").save(WEB / "icon-maskable-512.png", optimize=True)
icon(48).save(Path("../web/favicon.ico"), sizes=[(16, 16), (32, 32), (48, 48)])
wordmark_on(1024, 1024, round(1024 * 0.555), (0, 0, 0, 0)).save(WEB / "android-foreground-1024.png", optimize=True)

# ── Android launcher icons ────────────────────────────────
for name, scale in DENSITIES.items():
    d = RES / f"mipmap-{name}"
    legacy = round(48 * scale)
    icon(legacy).convert("RGB").save(d / "ic_launcher.png", optimize=True)
    mask = Image.new("L", (legacy, legacy), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, legacy - 1, legacy - 1), fill=255)
    rnd = Image.new("RGBA", (legacy, legacy), (0, 0, 0, 0))
    rnd.paste(icon(legacy), (0, 0), mask)
    rnd.save(d / "ic_launcher_round.png", optimize=True)
    # Adaptive foreground: 108dp canvas; the wordmark (60dp wide) stays inside
    # the 66dp safe circle that every launcher mask keeps visible.
    fg = round(108 * scale)
    wordmark_on(fg, fg, round(fg * 0.555), (0, 0, 0, 0)).save(d / "ic_launcher_foreground.png", optimize=True)

(RES / "values" / "ic_launcher_background.xml").write_text(
    '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <color name="ic_launcher_background">#1D70B8</color>\n</resources>\n'
)

# Splash screens: wordmark on CHISEL blue, 55% of the shorter side wide
for png in RES.glob("drawable*/splash.png"):
    w, h = Image.open(png).size
    wordmark_on(w, h, round(min(w, h) * 0.55), BLUE).convert("RGB").save(png, optimize=True)

# ── Notification (status-bar) icon ────────────────────────
# Android draws small icons as a white silhouette, so use the chisel tool from
# the wordmark artwork (its first embedded image) on a transparent 24dp square.
svg = (WEB / "chisel-wordmark.svg").read_text()
tool_b64 = re.search(r'id="img1" href="data:image/png;base64,([^"]+)"', svg).group(1)
tool = Image.open(__import__("io").BytesIO(base64.b64decode(tool_b64))).convert("RGBA")
tool = tool.crop(tool.getbbox())
white = Image.new("RGBA", tool.size, (255, 255, 255, 255))
white.putalpha(tool.getchannel("A"))
for name, scale in DENSITIES.items():
    side = round(24 * scale)
    inner = round(20 * scale)
    t = white.resize((round(white.width * inner / white.height), inner), Image.LANCZOS)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.alpha_composite(t, ((side - t.width) // 2, (side - t.height) // 2))
    out = RES / f"drawable-{name}"
    out.mkdir(exist_ok=True)
    canvas.save(out / "ic_stat_chisel.png", optimize=True)

print("Web icons, Android launcher icons, splash screens and notification icon generated")
