"""Generate platform icon files from the master icon `assets/icon.png`.

    python tools/make_icons.py

Outputs (in assets/icons/):
  lecture-studio.ico                      Windows (16-256 px, multi-resolution)
  lecture-studio.icns                     macOS  (16-1024 px)
  hicolor/<N>x<N>/apps/lecture-studio.png Linux freedesktop icon theme sizes
  lecture-studio-256.png                  runtime window icon
"""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "assets" / "icon.png"
OUT = ROOT / "assets" / "icons"
NAME = "lecture-studio"
LINUX_SIZES = [16, 24, 32, 48, 64, 128, 256, 512]


def square(img: Image.Image) -> Image.Image:
    """Centre-crop to a square and convert to RGBA."""
    img = img.convert("RGBA")
    w, h = img.size
    s = min(w, h)
    return img.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))


def main() -> None:
    base = square(Image.open(MASTER))
    big = base.resize((1024, 1024), Image.LANCZOS)
    OUT.mkdir(parents=True, exist_ok=True)
    big.save(OUT / f"{NAME}.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    big.save(OUT / f"{NAME}.icns")
    for s in LINUX_SIZES:
        d = OUT / "hicolor" / f"{s}x{s}" / "apps"
        d.mkdir(parents=True, exist_ok=True)
        base.resize((s, s), Image.LANCZOS).save(d / f"{NAME}.png", optimize=True)
    base.resize((256, 256), Image.LANCZOS).save(OUT / f"{NAME}-256.png", optimize=True)
    print(f"Icons written to {OUT}")


if __name__ == "__main__":
    main()
