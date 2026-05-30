"""
Rebuild AsanMinds app icons from the master logo1.png.

Why this exists: a raw photo-style PNG (1254x1254 RGB, no alpha)
breaks Android's WebAPK install path — Chrome falls back to the
chevron-badged shortcut. We need square, transparent, exact-size
PNGs in both 'any' and 'maskable' purposes.

Output (all RGBA, exact pixel sizes):
    assets/brand/logo-192.png            192x192   any (cream tile + logo)
    assets/brand/logo-512.png            512x512   any
    assets/brand/logo-192-maskable.png   192x192   maskable (forest tile, 60% safe-zone)
    assets/brand/logo-512-maskable.png   512x512   maskable
    assets/brand/apple-touch-icon.png    180x180   iOS Add-to-Home
"""

from __future__ import annotations

from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets" / "brand" / "logo1.png"
DST = ROOT / "assets" / "brand"

CREAM = (245, 242, 235, 255)   # #F5F2EB
FOREST = (15, 61, 46, 255)     # #0F3D2E


def open_master() -> Image.Image:
    im = Image.open(SRC).convert("RGBA")
    print(f"source: {im.size} mode={im.mode}")
    return im


def square_pad(im: Image.Image) -> Image.Image:
    """Pad to a perfect square, centred."""
    w, h = im.size
    side = max(w, h)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(im, ((side - w) // 2, (side - h) // 2), im)
    return canvas


def make_any(size: int) -> Image.Image:
    """Standard launcher icon: cream tile + logo at 84% scale.
    Cream gives a clean square edge on the launcher grid even on
    devices that don't apply adaptive masking."""
    src = square_pad(open_master())
    inner = int(size * 0.84)
    logo = src.resize((inner, inner), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), CREAM)
    canvas.paste(logo, ((size - inner) // 2, (size - inner) // 2), logo)
    return canvas


def make_maskable(size: int) -> Image.Image:
    """Maskable icon: forest tile + logo at 60% scale, centred.
    Adaptive icons crop ~20% from each edge to fit a circle/squircle
    mask. The 60% safe-zone guarantees no logo gets clipped on any
    device shape."""
    src = square_pad(open_master())
    inner = int(size * 0.60)
    logo = src.resize((inner, inner), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), FOREST)
    canvas.paste(logo, ((size - inner) // 2, (size - inner) // 2), logo)
    return canvas


def make_apple_touch() -> Image.Image:
    """iOS Add-to-Home-Screen icon, 180x180. iOS rounds the corners
    automatically — we want a flat opaque square with the logo edge-
    to-edge, no padding."""
    src = square_pad(open_master())
    logo = src.resize((180, 180), Image.LANCZOS)
    canvas = Image.new("RGBA", (180, 180), CREAM)
    canvas.paste(logo, (0, 0), logo)
    return canvas


def write(im: Image.Image, name: str) -> None:
    out = DST / name
    im.save(out, "PNG", optimize=True)
    print(f"  -> {name} ({im.size[0]}x{im.size[1]}, mode={im.mode}, {out.stat().st_size // 1024} KB)")


def main() -> None:
    print("Rebuilding AsanMinds app icons from logo1.png ...")
    print()
    write(make_any(192), "logo-192.png")
    write(make_any(512), "logo-512.png")
    write(make_maskable(192), "logo-192-maskable.png")
    write(make_maskable(512), "logo-512-maskable.png")
    write(make_apple_touch(), "apple-touch-icon.png")
    print()
    print("All icons regenerated. Check the launcher tile in the manifest.")


if __name__ == "__main__":
    main()
