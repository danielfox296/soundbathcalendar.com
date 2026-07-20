"""Generate the 1200x630 OG default card for Sound Bath Calendar.

Design: paper ground (the light utility register of this brand — deliberately
NOT Firstwater's ink cards), ink headline, ice waveform line, wordmark eyebrow.
Titles reuse the page's own H1 language — no new copy.

Event permalink pages use the operator's listing image when one exists and
fall back to this default. Run from the repo root: python3 scripts/og.py
(needs Pillow; the image is committed, CI never runs this).
"""
import math
import os

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
INK = (10, 11, 13)
ICE = (31, 111, 168)     # accent-on-light: holds contrast on paper
PAPER = (245, 247, 250)
GRAY = (110, 119, 129)


def _fonts():
    try:
        f_title = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 72)
        f_sub = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 30)
        f_eyebrow = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 26)
    except Exception:
        f_title = f_sub = f_eyebrow = ImageFont.load_default()
    return f_title, f_sub, f_eyebrow


def _wave(draw):
    pts = [(x, 505 + 48 * math.sin(x / 70) * math.exp(-((x - 700) / 420) ** 2))
           for x in range(0, W, 4)]
    draw.line(pts, fill=ICE, width=3)


# City page slugs — keep in sync with external_events.CITY_ANCHOR.
CITY_SLUGS = {
    'Denver': 'denver', 'Boulder': 'boulder',
    'Fort Collins': 'fort-collins', 'Colorado Springs': 'colorado-springs',
}


def _base(d):
    """Shared card furniture: waveform + wordmark eyebrow."""
    _wave(d)
    return _fonts()


def card(path):
    """The default/root OG card."""
    img = Image.new('RGB', (W, H), PAPER)
    d = ImageDraw.Draw(img)
    f_title, f_sub, f_eyebrow = _base(d)
    d.text((80, 150), 'SOUND BATH CALENDAR', font=f_eyebrow, fill=ICE)
    d.text((80, 205), 'Sound baths in Denver', font=f_title, fill=INK)
    d.text((80, 290), '& the Front Range', font=f_title, fill=INK)
    d.text((80, 396), 'Denver · Boulder · Fort Collins · Colorado Springs · updated weekly',
           font=f_sub, fill=GRAY)
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    img.save(path, optimize=True)
    print(f'  ok {path}')


def city_card(path, city):
    """A per-city OG card (Track B B.7): 'Sound baths in {City}'."""
    img = Image.new('RGB', (W, H), PAPER)
    d = ImageDraw.Draw(img)
    f_title, f_sub, f_eyebrow = _base(d)
    d.text((80, 150), 'SOUND BATH CALENDAR', font=f_eyebrow, fill=ICE)
    d.text((80, 205), 'Sound baths in', font=f_title, fill=INK)
    d.text((80, 290), city, font=f_title, fill=INK)
    d.text((80, 396), 'Dates · times · venues · prices · updated weekly',
           font=f_sub, fill=GRAY)
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    img.save(path, optimize=True)
    print(f'  ok {path}')


card('img/og-default.png')
for _city, _slug in CITY_SLUGS.items():
    city_card(f'img/og/{_slug}.png', _city)
print('og done')
