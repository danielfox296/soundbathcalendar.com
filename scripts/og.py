"""Generate the 1200x630 OG share cards for Sound Bath Calendar (CAL-17,
regenerated for v5 "Broadcast" — CAL-26, ratified 2026-07-25).

Split cards on the Night ground: a duotone-and-grain photo panel (indigo
shadows -> warm-white highlights, the v5 imagery treatment; CAL-28's
scripts/treat.py should share this ramp) beside a near-black text panel — the
coral slab kicker, the title in condensed-caps Archivo, a muted sub. The ∿
wave mark is retired. Copy reuses each page's own H1/meta language — no new
claims. Photo provenance: img/og/SOURCES.md.

LOCAL-only, like scripts/geocode.py: needs Pillow + the vendored assets in
scripts/assets/ (stock JPGs + Archivo-VF.ttf). The JPEGs are committed under
img/og/ and CI never runs this. Run from the repo root:

    python3 scripts/og.py
"""
import os

from PIL import Image, ImageDraw, ImageFont, ImageOps

W, H = 1200, 630
PANEL_W = 540            # the photo panel, right side
NIGHT = (14, 12, 18)     # --paper dark: #0E0C12, near-black violet-cast
TEXT = (245, 242, 237)   # --ink dark: #F5F2ED white-hot
MUTED = (171, 168, 163)  # --muted dark: #ABA8A3
SIGNAL = (185, 58, 43)   # --signal: #B93A2B coral
INK = (53, 47, 92)       # --ink light: #352F5C — the duotone shadow end
PAPER = (245, 242, 237)  # --paper light — the duotone highlight end

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
FONT_PATH = os.path.join(ASSETS, 'fonts', 'Archivo-VF.ttf')
STOCK = os.path.join(ASSETS, 'stock')


def _font(size, weight=400, width=100):
    """Archivo variable — axis order in the file is (wght, wdth)."""
    f = ImageFont.truetype(FONT_PATH, size)
    f.set_variation_by_axes([weight, width])
    return f


def _cover(photo, focal, w, h):
    """Scale-and-crop a photo to fill w x h around a focal point (cx, cy as
    0..1 fractions of the source)."""
    sw, sh = photo.size
    scale = max(w / sw, h / sh)
    nw, nh = round(sw * scale), round(sh * scale)
    photo = photo.resize((nw, nh), Image.LANCZOS)
    cx, cy = focal
    left = min(max(round(cx * nw - w / 2), 0), nw - w)
    top = min(max(round(cy * nh - h / 2), 0), nh - h)
    return photo.crop((left, top, left + w, top + h))


def _duotone_grain(photo):
    """The v5 imagery treatment: luminance mapped indigo -> warm white, plus a
    film grain (blended within the same two-color ramp, so the palette holds)."""
    g = ImageOps.autocontrast(photo.convert('L'), cutoff=2)
    duo = ImageOps.colorize(g, black=INK, white=PAPER)
    noise = ImageOps.colorize(
        Image.effect_noise(photo.size, 60), black=INK, white=PAPER)
    return Image.blend(duo, noise, 0.10)


def _kicker(draw, x, y, text, tracking=3):
    """The coral slab kicker: white caps on a signal fill."""
    f = _font(22, 700)
    widths = [draw.textlength(ch, font=f) + tracking for ch in text]
    pad_x, pad_y = 14, 9
    box_w = sum(widths) - tracking + 2 * pad_x
    box_h = 22 + 2 * pad_y
    draw.rectangle((x, y, x + box_w, y + box_h), fill=SIGNAL)
    cx = x + pad_x
    for ch, cw in zip(text, widths):
        draw.text((cx, y + pad_y - 2), ch, font=f, fill=(255, 255, 255))
        cx += cw
    return y + box_h


def card(path, photo_file, focal, title_lines, sub,
         eyebrow='SOUND BATH CALENDAR'):
    img = Image.new('RGB', (W, H), NIGHT)
    photo = Image.open(os.path.join(STOCK, photo_file)).convert('RGB')
    img.paste(_duotone_grain(_cover(photo, focal, PANEL_W, H)), (W - PANEL_W, 0))
    d = ImageDraw.Draw(img)

    title_lines = [l.upper() for l in title_lines]
    margin, text_w = 72, W - PANEL_W - 72 - 44

    _kicker(d, margin, 64, eyebrow)

    # Condensed-caps monument title, shrink-to-fit against the text panel.
    size = 78
    while size > 40:
        f_title = _font(size, 800, 72)
        if all(d.textlength(l, font=f_title) <= text_w for l in title_lines):
            break
        size -= 3
    line_h = round(size * 1.02)
    sub_y = H - 96
    title_y = sub_y - 46 - line_h * len(title_lines)
    for i, line in enumerate(title_lines):
        d.text((margin, title_y + i * line_h), line, font=f_title, fill=TEXT)

    for f_sub in (_font(25, 500), _font(22, 500)):
        if d.textlength(sub, font=f_sub) <= text_w + 30:
            break
    d.text((margin, sub_y), sub, font=f_sub, fill=MUTED)

    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    # JPEG, not PNG: cards must stay well under ~600KB (WhatsApp drops link
    # previews above that).
    img.save(path, quality=82, optimize=True, progressive=True)
    kb = os.path.getsize(path) // 1024
    assert kb < 600, f'{path} is {kb}KB — over the share-preview cap'
    print(f'  ok {path} ({kb}KB)')


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
     ['Sound baths', 'in Denver &', 'the Front Range'],
     'Denver · Boulder · Fort Collins · Colorado Springs'),
    ('img/og/map.jpg', 'pexels-8617327.jpg', (0.5, 0.50),
     ['Sound baths', 'on the map'],
     'Every upcoming session, pinned by venue'),
    ('img/og/tags.jpg', 'pexels-6013471.jpg', (0.5, 0.55),
     ['Browse', 'by tag'],
     'What makes the sound · why people come'),
    ('img/og/tag-gong-bath.jpg', 'pexels-6013490.jpg', (0.55, 0.40),
     ['Gong baths on', 'the Front Range'], CITY_SUB),
    ('img/og/tag-breathwork-sound.jpg', 'pexels-8617327.jpg', (0.5, 0.62),
     ['Breathwork', '+ sound on the', 'Front Range'], CITY_SUB),
    ('img/og/venues.jpg', 'pexels-5602498.jpg', (0.5, 0.45),
     ['Sound bath', 'venues'],
     'Every venue worth knowing · what is on next'),
    ('img/og/practitioners.jpg', 'pexels-3544322.jpg', (0.5, 0.50),
     ['Practitioners'],
     'The facilitators leading Front Range sound baths'),
    ('img/og/operators.jpg', 'pexels-6997998.jpg', (0.42, 0.55),
     ['Organizers'],
     'The collectives and studios running sound baths'),
    ('img/og/what-to-expect.jpg', 'pexels-6914822.jpg', (0.5, 0.55),
     ['What to expect', 'at a sound bath'],
     "The first-timer's guide"),
]

if __name__ == '__main__':
    for _output, _photo, _focal, _title, _sub in CARDS:
        card(_output, _photo, _focal, _title, _sub)
    for _city, _slug in CITY_SLUGS.items():
        _photo, _focal = CITY_PHOTOS[_slug]
        card(f'img/og/{_slug}.jpg', _photo, _focal, ['Sound baths', f'in {_city}'],
             CITY_SUB)
    print('og done')
