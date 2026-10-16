"""Draw the app's artwork with Pillow, so every pixel is reproducible:

    python assets/make_assets.py

logo.png     1024 px – navy rounded square, a cyan spectrum with its peak marked (the family
             look of the kayEi TwinStudio logo); the window icon, About box and exe icon
favicon.png  64 px version of the logo
check.png    the tick inside a checked QCheckBox (the style sheet needs a file)
icons/*.png  small line icons for the panel buttons (save, open, folder)
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
NAVY = (0, 26, 69, 255)
NAVY_DARK = (0, 20, 55, 255)
CYAN = (34, 211, 238, 255)
PALE = (230, 237, 247, 255)
ORANGE = (249, 115, 22, 255)
GRID = (30, 58, 110, 255)


def _spectrum(x: float) -> float:
    """0..1 -> 0..1: a laser line on a pedestal with a Raman bump and a floor."""
    def g(c, w, a):
        return a * math.exp(-0.5 * ((x - c) / w) ** 2)
    return min(1.0, 0.06 + g(0.42, 0.028, 0.92) + g(0.42, 0.11, 0.10) + g(0.70, 0.05, 0.22) + g(0.20, 0.03, 0.06))


def logo(size: int = 1024) -> Image.Image:
    s = 8                                               # supersampling
    n = size * s
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, n - 1, n - 1), radius=int(n * 0.22), fill=NAVY)
    # a faint grid, like the plot
    pad = int(n * 0.16)
    bottom, top = n - pad, pad
    for i in range(1, 5):
        y = top + (bottom - top) * i / 5
        d.line((pad, y, n - pad, y), fill=GRID, width=max(1, n // 400))
    # the spectrum
    pts = []
    for i in range(401):
        x = i / 400
        y = _spectrum(x)
        pts.append((pad + x * (n - 2 * pad), bottom - y * (bottom - top)))
    fill_pts = [(pad, bottom), *pts, (n - pad, bottom)]
    d.polygon(fill_pts, fill=(34, 211, 238, 60))
    d.line(pts, fill=CYAN, width=int(n * 0.028), joint="curve")
    # the FWHM bar in pale ink and the peak marker in orange
    peak_x = pad + 0.42 * (n - 2 * pad)
    peak_y = bottom - _spectrum(0.42) * (bottom - top)
    half_y = bottom - (_spectrum(0.42) * 0.72) * (bottom - top)
    d.line((peak_x - n * 0.075, half_y, peak_x + n * 0.075, half_y), fill=PALE, width=int(n * 0.018))
    r = int(n * 0.045)
    d.ellipse((peak_x - r, peak_y - r, peak_x + r, peak_y + r), fill=ORANGE)
    return img.resize((size, size), Image.LANCZOS)


def check(size: int = 32) -> Image.Image:
    s = 8
    n = size * s
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    w = int(n * 0.14)
    d.line([(n * 0.22, n * 0.52), (n * 0.42, n * 0.72), (n * 0.78, n * 0.30)], fill=(0, 34, 56, 255), width=w, joint="curve")
    return img.resize((size, size), Image.LANCZOS)


def icon(kind: str, size: int = 128) -> Image.Image:
    s = 8
    n = size * s
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    w = int(n * 0.07)
    if kind == "save":                                  # a floppy outline
        d.rounded_rectangle((n * .14, n * .14, n * .86, n * .86), radius=n * .08, outline=PALE, width=w)
        d.rectangle((n * .30, n * .14, n * .70, n * .40), outline=PALE, width=w)
        d.rectangle((n * .28, n * .58, n * .72, n * .86), fill=CYAN)
    elif kind == "open":                                # a folder, open
        d.polygon([(n * .10, n * .26), (n * .40, n * .26), (n * .48, n * .36), (n * .90, n * .36), (n * .90, n * .80),
                   (n * .10, n * .80)], outline=PALE, width=w)
        d.polygon([(n * .20, n * .46), (n * .96, n * .46), (n * .86, n * .80), (n * .10, n * .80)], fill=CYAN)
    elif kind == "folder":
        d.polygon([(n * .10, n * .24), (n * .40, n * .24), (n * .48, n * .34), (n * .90, n * .34), (n * .90, n * .80),
                   (n * .10, n * .80)], fill=CYAN)
    elif kind == "play":
        d.polygon([(n * .28, n * .18), (n * .82, n * .50), (n * .28, n * .82)], fill=CYAN)
    elif kind == "stop":
        d.rounded_rectangle((n * .22, n * .22, n * .78, n * .78), radius=n * .08, fill=PALE)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    lg = logo()
    lg.save(HERE / "logo.png")
    lg.resize((64, 64), Image.LANCZOS).save(HERE / "favicon.png")
    check().save(HERE / "check.png")
    (HERE / "icons").mkdir(exist_ok=True)
    for kind in ("save", "open", "folder", "play", "stop"):
        icon(kind).save(HERE / "icons" / f"{kind}.png")
    print("artwork written to", HERE)


if __name__ == "__main__":
    main()
