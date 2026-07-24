"""Harvest candidate VENUE photos from Google Places → a review contact sheet.

Venues are physical places, so the right source is their Google listing, not an
og:image scrape (an operator's og:image is a logo or a face, never the room).
For each venue this does one Places text search and pulls its first Place
Photo, writes the candidates to .venue-review/ and a single contact sheet, and
writes NOTHING to the repo or the feed. You review the sheet, then the good
ones get copied to img/venues/<slug>.jpg by hand.

LOCAL ONLY, like scripts/og.py — never runs in CI. Needs Pillow and a Google
Maps Platform API key with the **Places API (New)** enabled.

    export GOOGLE_MAPS_API_KEY='AIza...'        # or you'll be prompted
    python3 scripts/harvest_venue_photos.py

COST: ~41 text searches + ~41 photo fetches per full run — a few cents,
comfortably inside Google's $200/month free credit. The key is read from the
environment (or a hidden prompt) and never printed or logged.
"""
import concurrent.futures
import getpass
import io
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REVIEW = os.path.join(ROOT, '.venue-review')
FONT = os.path.join(ROOT, 'scripts', 'assets', 'fonts', 'SpaceGrotesk-VF.ttf')

VENUE_FEED = 'https://admin.soundbathcalendar.com/feeds/venues.json'
SEARCH_URL = 'https://places.googleapis.com/v1/places:searchText'
TIMEOUT = 20
PHOTO_W = 1200        # max width fetched; cards only need 1080

# Only the fields we use, so the search bills at the cheapest tier that
# still returns photos.
FIELD_MASK = 'places.id,places.displayName,places.formattedAddress,places.photos'


def _fetch_feed():
    with urllib.request.urlopen(VENUE_FEED, timeout=TIMEOUT) as r:
        d = json.loads(r.read().decode())
    return d.get('venues', d) if isinstance(d, dict) else d


def search_place(venue, key):
    """First Places match for a venue. Returns the place dict or None."""
    name = (venue.get('name') or '').strip()
    city = (venue.get('city') or '').strip()
    addr = (venue.get('address') or '').strip()
    # Address when we have one (disambiguates generic names); else name + city.
    query = f'{name}, {addr}' if addr else f'{name}, {city}, CO'
    body = json.dumps({'textQuery': query, 'maxResultCount': 1}).encode()
    req = urllib.request.Request(SEARCH_URL, data=body, method='POST', headers={
        'Content-Type': 'application/json',
        'X-Goog-Api-Key': key,
        'X-Goog-FieldMask': FIELD_MASK,
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            places = json.loads(r.read().decode()).get('places', [])
        return places[0] if places else None
    except urllib.error.HTTPError as exc:
        # Surface auth/enablement errors once, loudly — they are the same for
        # every venue, so no point repeating 41 times.
        body = exc.read().decode(errors='replace')[:200]
        raise RuntimeError(f'Places search failed ({exc.code}): {body}') from None
    except urllib.error.URLError as exc:
        return None


def fetch_photo(photo_name, key):
    """Download the bytes behind a Place Photo resource name."""
    url = (f'https://places.googleapis.com/v1/{photo_name}/media'
           f'?maxWidthPx={PHOTO_W}&key={urllib.parse.quote(key)}')
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
            raw = r.read(12 * 1024 * 1024)
        im = Image.open(io.BytesIO(raw))
        im.load()
        return im.convert('RGB')
    except Exception:
        return None


def slugify(s):
    return re.sub(r'[^a-z0-9]+', '-', (s or '').lower()).strip('-')


def harvest_one(args):
    venue, key = args
    name = (venue.get('name') or '').strip()
    slug = venue.get('slug') or slugify(name)
    res = {'name': name, 'slug': slug, 'img': None, 'addr': ''}
    place = search_place(venue, key)
    if not place:
        return res
    res['addr'] = place.get('formattedAddress', '')
    photos = place.get('photos') or []
    if not photos:
        return res
    im = fetch_photo(photos[0]['name'], key)
    if im and min(im.size) >= 200:
        im.save(os.path.join(REVIEW, f'{slug}.jpg'), 'JPEG', quality=88)
        res['img'] = im
    return res


def _font(sz, w=400):
    f = ImageFont.truetype(FONT, sz)
    f.set_variation_by_axes([w])
    return f


def contact_sheet(results):
    cols, cell, pad, lab = 5, 260, 16, 74
    rows = (len(results) + cols - 1) // cols
    W = cols * cell + (cols + 1) * pad
    H = rows * (cell + lab) + (rows + 1) * pad
    sheet = Image.new('RGB', (W, H), (24, 24, 26))
    d = ImageDraw.Draw(sheet)
    fn = _font(19, 600)
    for i, r in enumerate(results):
        x = pad + (i % cols) * (cell + pad)
        y = pad + (i // cols) * (cell + lab + pad)
        if r['img'] is not None:
            im = r['img'].copy()
            s = cell / min(im.size)
            im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
            sheet.paste(im.crop((0, 0, cell, cell)), (x, y))
        else:
            d.rectangle([x, y, x + cell, y + cell], fill=(40, 40, 44))
            d.text((x + 78, y + cell // 2), 'no photo', font=fn, fill=(120, 120, 128))
        name = r['name']
        d.text((x, y + cell + 6), name[:26], font=fn, fill=(240, 240, 242))
        if len(name) > 26:
            d.text((x, y + cell + 30), name[26:52], font=fn, fill=(240, 240, 242))
    out = os.path.join(REVIEW, 'contact_sheet.jpg')
    sheet.save(out, 'JPEG', quality=90)
    return out


def main():
    key = os.environ.get('GOOGLE_MAPS_API_KEY', '').strip()
    if not key:
        try:
            key = getpass.getpass('Google Maps API key (input hidden): ').strip()
        except (EOFError, KeyboardInterrupt):
            print('\nCancelled.')
            return 2
    if not key:
        print('A Places API (New) key is required.')
        return 2

    os.makedirs(REVIEW, exist_ok=True)
    venues = _fetch_feed()
    print(f'{len(venues)} venues; querying Google Places...')

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
            results = list(ex.map(harvest_one, [(v, key) for v in venues]))
    except RuntimeError as exc:
        # A shared auth/enablement failure — one clear message, not 41.
        print(f'\nFAIL — {exc}')
        print('Check: the key has "Places API (New)" enabled, and any key '
              'restriction allows it.')
        return 1

    got = [r for r in results if r['img'] is not None]
    print(f'  got a photo for {len(got)}/{len(venues)}')
    sheet = contact_sheet(results)
    print(f'  contact sheet: {sheet}')
    print('\nReview the sheet, then copy the good ones:')
    print('  cp .venue-review/<slug>.jpg img/venues/<slug>.jpg')
    return 0


if __name__ == '__main__':
    sys.exit(main())
