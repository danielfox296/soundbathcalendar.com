"""Generate the 1200x630 OG share cards for Sound Bath Calendar (CAL-17).

Stock-photography cards: a warm, license-clean photo (provenance in
img/og/SOURCES.md) under the site's dark tokens — an ink scrim for text
legibility, the ice waveform + wordmark eyebrow, titles in Space Grotesk.
Copy reuses each page's own H1/meta language — no new claims.

LOCAL-only, like scripts/geocode.py: needs Pillow + the vendored assets in
scripts/assets/ (stock JPGs + SpaceGrotesk-VF.ttf). The PNGs are committed
under img/og/ and CI never runs this. Run from the repo root:

    python3 scripts/og.py
"""
import math
import os

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
INK = (10, 11, 13)         # --ink: the card ground the scrim pulls toward
TEXT = (245, 247, 250)     # dark-mode text token (#F5F7FA)
MUTED = (167, 175, 185)    # dark-mode muted token (#A7AFB9)
ICE = (98, 182, 232)       # accent (#62B6E8): holds AA on the ink ground

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
FONT_PATH = os.path.join(ASSETS, 'fonts', 'SpaceGrotesk-VF.ttf')
STOCK = os.path.join(ASSETS, 'stock')


def _font(size, weight=400):
    f = ImageFont.truetype(FONT_PATH, size)
    f.set_variation_by_axes([weight])
    return f


def _cover(photo, focal):
    """Scale-and-crop a photo to fill 1200x630 around a focal point (cx, cy
    as 0..1 fractions of the source)."""
    sw, sh = photo.size
    scale = max(W / sw, H / sh)
    nw, nh = round(sw * scale), round(sh * scale)
    photo = photo.resize((nw, nh), Image.LANCZOS)
    cx, cy = focal
    left = min(max(round(cx * nw - W / 2), 0), nw - W)
    top = min(max(round(cy * nh - H / 2), 0), nh - H)
    return photo.crop((left, top, left + W, top + H))


def _scrim(photo):
    """The brand treatment: pull the photo toward ink overall, then deepen
    the lower-left where the type sits (bottom + left linear scrims)."""
    base = Image.blend(photo, Image.new('RGB', (W, H), INK), 0.30)
    ink = Image.new('RGB', (W, H), INK)

    # Bottom scrim: transparent at 30% height -> strong at the bottom edge.
    ramp = Image.new('L', (1, H))
    for y in range(H):
        t = max(0.0, (y / H - 0.30) / 0.70)
        ramp.putpixel((0, y), int(215 * t ** 1.4))
    base.paste(ink, (0, 0), ramp.resize((W, H)))

    # Left scrim: strong at the left edge -> transparent by 78% width.
    ramp = Image.new('L', (W, 1))
    for x in range(W):
        t = max(0.0, 1 - x / (W * 0.78))
        ramp.putpixel((x, 0), int(120 * t ** 1.6))
    base.paste(ink, (0, 0), ramp.resize((W, H)))
    return base


def _wave(draw, x, y, width=64, amp=7, color=ICE):
    """The site's small waveform mark, drawn as a line segment."""
    pts = [(x + i, y + amp * math.sin(i / width * 2 * math.pi))
           for i in range(0, width + 1, 2)]
    draw.line(pts, fill=color, width=3)


def _eyebrow(draw, x, y, text, font, tracking=3):
    """Letterspaced eyebrow (PIL has no tracking of its own)."""
    for ch in text:
        draw.text((x, y), ch, font=font, fill=ICE)
        x += draw.textlength(ch, font=font) + tracking
    return x


def card(path, photo_file, focal, title_lines, sub,
         eyebrow='SOUND BATH CALENDAR'):
    photo = Image.open(os.path.join(STOCK, photo_file)).convert('RGB')
    img = _scrim(_cover(photo, focal))
    d = ImageDraw.Draw(img)

    f_title = _font(74, 500)
    f_sub = _font(27, 400)
    f_eyebrow = _font(24, 600)

    # Text block sits lower-left on the scrim, bottom-anchored.
    line_h = 86
    sub_y = H - 95
    title_y0 = sub_y - 41 - line_h * len(title_lines)
    eyebrow_y = title_y0 - 52

    _wave(d, 80, eyebrow_y + 15)
    _eyebrow(d, 160, eyebrow_y, eyebrow, f_eyebrow)

    for i, line in enumerate(title_lines):
        y = title_y0 + i * line_h
        d.text((80, y), line, font=f_title, fill=TEXT)
        if d.textlength(line, font=f_title) > W - 160:
            print(f'  !! title overflows: {line!r} ({path})')
    d.text((80, sub_y), sub, font=f_sub, fill=MUTED)

    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    # JPEG, not PNG: photographic cards land ~200KB (WhatsApp drops link
    # previews whose image exceeds ~600KB; the old flat PNGs were fine).
    img.save(path, quality=82, optimize=True, progressive=True)
    print(f'  ok {path}')


# City page slugs — keep in sync with external_events.CITY_ANCHOR.
CITY_SLUGS = {
    'Denver': 'denver', 'Boulder': 'boulder',
    'Fort Collins': 'fort-collins', 'Colorado Springs': 'colorado-springs',
}

CITY_PHOTOS = {
    'denver': ('pexels-6013488.jpg', (0.5, 0.55)),
    'boulder': ('pexels-6997998.jpg', (0.5, 0.50)),
    'fort-collins': ('pexels-5602465.jpg', (0.5, 0.60)),
    'colorado-springs': ('pexels-6013474.jpg', (0.5, 0.55)),
}

CITY_SUB = 'Dates · times · venues · prices · updated weekly'

# (output, photo, focal, title lines, sub) — copy lifted from each page's own
# H1/meta line. Per-tag cards exist only for tags with live pages; new tag
# pages fall back to tags.png until this script is re-run locally.
CARDS = [
    ('img/og-default.jpg', 'pexels-6013471.jpg', (0.5, 0.62),
     ['Sound baths in Denver', '& the Front Range'],
     'Denver · Boulder · Fort Collins · Colorado Springs · updated weekly'),
    ('img/og/map.jpg', 'pexels-8617327.jpg', (0.5, 0.50),
     ['Sound baths', 'on the map'],
     'Every upcoming session, pinned by venue'),
    ('img/og/tags.jpg', 'pexels-6013471.jpg', (0.5, 0.55),
     ['Browse by tag'],
     'What makes the sound · why people come · the setting'),
    ('img/og/tag-gong-bath.jpg', 'pexels-6013490.jpg', (0.55, 0.40),
     ['Gong baths on', 'the Front Range'], CITY_SUB),
    ('img/og/tag-breathwork-sound.jpg', 'pexels-8617327.jpg', (0.5, 0.62),
     ['Breathwork + sound', 'on the Front Range'], CITY_SUB),
    ('img/og/venues.jpg', 'pexels-5602498.jpg', (0.5, 0.45),
     ['Sound bath venues'],
     'Every venue worth knowing · directions · what is on next'),
    ('img/og/practitioners.jpg', 'pexels-3544322.jpg', (0.5, 0.50),
     ['Practitioners'],
     'The facilitators leading sound baths on the Front Range'),
    ('img/og/operators.jpg', 'pexels-6997998.jpg', (0.42, 0.55),
     ['Organizers'],
     'The collectives and studios running sound baths'),
    ('img/og/what-to-expect.jpg', 'pexels-6914822.jpg', (0.5, 0.55),
     ['What to expect', 'at a sound bath'],
     "An honest first-timer's guide"),
]

for _output, _photo, _focal, _title, _sub in CARDS:
    card(_output, _photo, _focal, _title, _sub)
for _city, _slug in CITY_SLUGS.items():
    _photo, _focal = CITY_PHOTOS[_slug]
    card(f'img/og/{_slug}.jpg', _photo, _focal, ['Sound baths in', _city],
         CITY_SUB)
print('og done')
