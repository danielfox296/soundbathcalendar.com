"""Generate the on-page warm imagery set (CAL-22 — the WARMTH RULE half of
CAL-14 that CAL-17's OG cards didn't cover).

Web-optimized crops of the same license-clean stock the OG cards use
(provenance: img/og/SOURCES.md), committed under img/warm/. Each surface
reuses its OG card's photograph so a shared link and the page it opens
feel like one thing. Photos are natural — no scrim, no type; the dark
scheme dims them slightly via CSS, not here.

LOCAL-only, like scripts/og.py and geocode.py: needs Pillow + the assets
in scripts/assets/stock/; the JPEGs are committed and CI never runs this.
Run from the repo root:

    python3 scripts/warm.py
"""
import os

from PIL import Image

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
STOCK = os.path.join(ASSETS, 'stock')


def _cover(photo, w, h, focal):
    """Scale-and-crop to w x h around a focal point (cx, cy as 0..1)."""
    sw, sh = photo.size
    scale = max(w / sw, h / sh)
    nw, nh = round(sw * scale), round(sh * scale)
    photo = photo.resize((nw, nh), Image.LANCZOS)
    cx, cy = focal
    left = min(max(round(cx * nw - w / 2), 0), nw - w)
    top = min(max(round(cy * nh - h / 2), 0), nh - h)
    return photo.crop((left, top, left + w, top + h))


def emit(name, photo_file, ratio_w, ratio_h, focal):
    """One surface: a 1600w master + an 800w variant for srcset."""
    photo = Image.open(os.path.join(STOCK, photo_file)).convert('RGB')
    for width in (1600, 800):
        height = round(width * ratio_h / ratio_w)
        img = _cover(photo, width, height, focal)
        path = f'img/warm/{name}-{width}.jpg'
        os.makedirs(os.path.dirname(path), exist_ok=True)
        img.save(path, quality=80, optimize=True, progressive=True)
        print(f'  ok {path} ({width}x{height})')


# (name, source photo, aspect w:h, focal) — photos match the surface's OG card.
SURFACES = [
    # /what-to-expect/ hero: the first-timer on the mat (matches its OG card).
    ('what-to-expect', 'pexels-6914822.jpg', 21, 10, (0.5, 0.55)),
    # City-page warm bands (16:5 strips; the listing ROOT stays utilitarian).
    ('denver', 'pexels-6013488.jpg', 16, 5, (0.5, 0.80)),
    ('boulder', 'pexels-6997998.jpg', 16, 5, (0.5, 0.55)),
    ('fort-collins', 'pexels-5602465.jpg', 16, 5, (0.5, 0.68)),
    ('colorado-springs', 'pexels-6013474.jpg', 16, 5, (0.5, 0.72)),
]

for _name, _photo, _rw, _rh, _focal in SURFACES:
    emit(_name, _photo, _rw, _rh, _focal)
print('warm done')
