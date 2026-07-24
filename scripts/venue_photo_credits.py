"""Capture Google Places photo attributions for the committed venue photos
(CAL-25 → attribution).

WHY THIS EXISTS: the venue photos in img/venues/<slug>.jpg were harvested from
each venue's Google listing, and Google Places policy requires the contributor's
attribution to be shown wherever the photo appears. The harvester
(scripts/harvest_venue_photos.py) downloaded the image but NOT its
authorAttributions, so this script fetches just the attribution for each photo
we actually committed and writes it to img/venues/credits.json.

That file is the render gate: _src/lib/venues.py shows a venue photo ONLY when a
credit exists for its slug (see load_credits / photo_with_credit). No credit →
no photo. So this script must succeed for a venue before its photo can ship.

CAVEAT (honest): we re-query Places for the venue's *current first* photo and
take its attribution. The committed JPGs were harvested the same way, so this is
the same photo in almost every case — but Google can reorder a listing's photos,
so a mismatch is possible. Review credits.json against the images before
committing (the contact sheet in .venue-review/ shows what was harvested).

LOCAL ONLY, like the harvester — never runs in CI. Needs a Google Maps Platform
key with the **Places API (New)** enabled:

    export GOOGLE_MAPS_API_KEY='AIza...'        # or you'll be prompted
    python3 scripts/venue_photo_credits.py

Then review + commit img/venues/credits.json. COST: one text search per
committed venue (~27) — a few cents, inside Google's free credit.
"""
import getpass
import glob
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENUES_DIR = os.path.join(ROOT, 'img', 'venues')
CREDITS_PATH = os.path.join(VENUES_DIR, 'credits.json')

VENUE_FEED = 'https://admin.soundbathcalendar.com/feeds/venues.json'
SEARCH_URL = 'https://places.googleapis.com/v1/places:searchText'
TIMEOUT = 20
# photos carries authorAttributions (displayName + uri) — the only thing we want.
FIELD_MASK = 'places.id,places.displayName,places.photos'


def _fetch_feed():
    with urllib.request.urlopen(VENUE_FEED, timeout=TIMEOUT) as r:
        d = json.loads(r.read().decode())
    return d.get('venues', d) if isinstance(d, dict) else d


def _committed_slugs():
    """The slugs with a committed photo file (credits.json itself excluded)."""
    out = []
    for p in sorted(glob.glob(os.path.join(VENUES_DIR, '*.jpg'))):
        out.append(os.path.splitext(os.path.basename(p))[0])
    return out


def _query_for(venue):
    """Identical to the harvester's query: address when we have one (it
    disambiguates generic names), else name + city."""
    name = (venue.get('name') or '').strip()
    city = (venue.get('city') or '').strip()
    addr = (venue.get('address') or '').strip()
    return f'{name}, {addr}' if addr else f'{name}, {city}, CO'


def first_photo_attribution(venue, key):
    """The first Place Photo's contributor attribution for a venue:
    {"author", "authorUrl"} or None (no place / no photo / no attribution)."""
    body = json.dumps({'textQuery': _query_for(venue), 'maxResultCount': 1}).encode()
    req = urllib.request.Request(SEARCH_URL, data=body, method='POST', headers={
        'Content-Type': 'application/json',
        'X-Goog-Api-Key': key,
        'X-Goog-FieldMask': FIELD_MASK,
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            places = json.loads(r.read().decode()).get('places', [])
    except urllib.error.HTTPError as exc:
        # A shared auth/enablement failure — surface once, loudly.
        detail = exc.read().decode(errors='replace')[:200]
        raise RuntimeError(f'Places search failed ({exc.code}): {detail}') from None
    except urllib.error.URLError:
        return None
    if not places:
        return None
    photos = places[0].get('photos') or []
    if not photos:
        return None
    attrs = photos[0].get('authorAttributions') or []
    if not attrs:
        return None
    a = attrs[0]
    author = (a.get('displayName') or '').strip()
    if not author:
        return None
    return {'author': author, 'authorUrl': (a.get('uri') or '').strip()}


def _load_existing():
    try:
        with open(CREDITS_PATH, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


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
    if not key.isascii():
        # A real Google key is ASCII (AIza… alphanumeric + -_). Non-ASCII means
        # the placeholder 'AIza…your-key…' got pasted verbatim — catch it here
        # rather than as a latin-1 header-encoding traceback mid-fetch.
        print('That key contains non-ASCII characters — looks like the placeholder '
              'was pasted instead of your real key. Re-run with your actual key.')
        return 2

    slugs = _committed_slugs()
    if not slugs:
        print(f'No committed photos in {VENUES_DIR} — nothing to attribute.')
        return 0
    feed_by_slug = {v.get('slug'): v for v in _fetch_feed()}
    existing = _load_existing()

    print(f'{len(slugs)} committed venue photo(s); fetching Google attribution...')
    credits, kept, missing_venue, no_attr = {}, [], [], []
    try:
        for slug in slugs:
            venue = feed_by_slug.get(slug)
            if not venue:
                # A committed image whose slug is no longer in the feed — keep any
                # prior credit, but flag it (the venue page won't build either).
                missing_venue.append(slug)
                if slug in existing:
                    credits[slug] = existing[slug]
                continue
            attr = first_photo_attribution(venue, key)
            if attr:
                credits[slug] = attr
                print(f'  ✓ {slug:<40} {attr["author"]}')
            elif slug in existing:
                # A transient miss must not wipe a good credit → carry it forward.
                credits[slug] = existing[slug]
                kept.append(slug)
                print(f'  · {slug:<40} (kept existing: {existing[slug].get("author","")})')
            else:
                no_attr.append(slug)
                print(f'  ✗ {slug:<40} NO attribution — this photo will NOT ship')
    except RuntimeError as exc:
        print(f'\nFAIL — {exc}')
        print('Check: the key has "Places API (New)" enabled and any key '
              'restriction allows it.')
        return 1

    with open(CREDITS_PATH, 'w', encoding='utf-8') as f:
        f.write(json.dumps(credits, indent=2, sort_keys=True, ensure_ascii=False) + '\n')

    print(f'\nWrote {CREDITS_PATH}')
    print(f'  credited:            {len(credits)}')
    if kept:
        print(f'  kept existing:       {len(kept)} ({", ".join(kept)})')
    if no_attr:
        print(f'  NO attribution:      {len(no_attr)} — WILL NOT render: {", ".join(no_attr)}')
    if missing_venue:
        print(f'  not in feed:         {len(missing_venue)} — {", ".join(missing_venue)}')
    print('\nReview credits.json against the photos, then commit it. Photos ship '
          'only for slugs credited here.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
