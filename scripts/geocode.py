#!/usr/bin/env python3
"""Geocode venue addresses into data/geocode.json (CAL-04 map).

LOCAL TOOLING ONLY — never run in CI (the deploy workflow excludes scripts/).
Reads the committed external-events cache, collects one representative address
per venue, and geocodes any not already cached via OpenStreetMap Nominatim
(rate-limited, cached forever). The build reads the cache and never geocodes, so
CI stays hermetic and Nominatim is hit at most once per new venue.

Usage:
    python3 scripts/geocode.py          # fill missing
    python3 scripts/geocode.py --retry  # also retry past failures

Cache shape (data/geocode.json), keyed by the venue string:
    { "Singing Bowls of the Rockies": {"lat": 38.8, "lng": -104.8,
                                        "query": "76 S Sierra Madre St, Colorado Springs, CO"},
      "Some Room": {"ok": false, "query": "..."} }
"""

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

# An address that already carries a state/zip is complete — appending ", city,
# CO" again ("...Fort Collins, CO 80524, Fort Collins, CO") breaks the match.
_COMPLETE_RE = re.compile(r'\b(CO|Colorado)\b|\b\d{5}\b', re.I)

# Nominatim can't resolve a unit within a building — strip suite/unit fragments
# so the street address itself matches ("76 S Sierra Madre St Suite C" → "76 S
# Sierra Madre St"). Applied as a fallback only when the full query misses.
_UNIT_RE = re.compile(r',?\s*\b(suites?|ste|unit|apt|apartment|#|no\.?)\b\.?\s*[\w-]*',
                      re.I)


def strip_unit(query):
    stripped = _UNIT_RE.sub('', query)
    stripped = re.sub(r'\s{2,}', ' ', stripped).replace(' ,', ',').strip()
    return stripped if stripped != query else None

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVENTS = os.path.join(REPO, 'data', 'external-events.json')
CACHE = os.path.join(REPO, 'data', 'geocode.json')
UA = 'soundbathcalendar-geocode/1.0 (https://soundbathcalendar.com; danielchristopherfox@gmail.com)'
RATE_S = 1.1  # Nominatim usage policy: <= 1 request/second.


def venue_queries(events):
    """One representative 'address, city, CO' query per distinct venue string.
    Prefers a real street address; falls back to venue name + city."""
    out = {}
    for e in events:
        if e.get('status') != 'approved':
            continue
        venue = (e.get('venue') or '').strip()
        if not venue or venue in out:
            continue
        addr = (e.get('address') or '').strip()
        city = (e.get('city') or '').strip()
        if addr and _COMPLETE_RE.search(addr):
            out[venue] = addr  # already carries state/zip — use verbatim
        else:
            base = addr if addr else venue
            out[venue] = ', '.join(p for p in (base, city, 'CO') if p)
    return out


def geocode(query):
    """Nominatim → (lat, lng) or None."""
    url = ('https://nominatim.openstreetmap.org/search?'
           + urllib.parse.urlencode({'format': 'json', 'q': query,
                                     'limit': 1, 'countrycodes': 'us'}))
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    if not data:
        return None
    return float(data[0]['lat']), float(data[0]['lon'])


def main():
    retry = '--retry' in sys.argv
    with open(EVENTS, encoding='utf-8') as f:
        events = json.load(f)['events']
    queries = venue_queries(events)

    cache = {}
    if os.path.exists(CACHE):
        with open(CACHE, encoding='utf-8') as f:
            cache = json.load(f)

    todo = [v for v, q in queries.items()
            if v not in cache or (retry and not cache[v].get('lat'))]
    print(f'{len(queries)} venues; {len(todo)} to geocode'
          f'{" (incl. retries)" if retry else ""}.')

    for i, venue in enumerate(todo, 1):
        q = queries[venue]
        try:
            hit = geocode(q)
            # Fallback: retry without the suite/unit fragment (a second call, so
            # still rate-limited below), which resolves the containing building.
            if not hit:
                alt = strip_unit(q)
                if alt:
                    time.sleep(RATE_S)
                    hit = geocode(alt)
                    if hit:
                        q = alt
        except Exception as exc:  # network / rate: leave uncached, try next run
            print(f'  ! {venue}: {exc.__class__.__name__} — skipped')
            continue
        if hit:
            cache[venue] = {'lat': round(hit[0], 6), 'lng': round(hit[1], 6), 'query': q}
            print(f'  ✓ {venue} → {hit[0]:.5f}, {hit[1]:.5f}')
        else:
            cache[venue] = {'ok': False, 'query': q}
            print(f'  ∅ {venue}: no match for "{q}"')
        if i < len(todo):
            time.sleep(RATE_S)

    with open(CACHE, 'w', encoding='utf-8') as f:
        f.write(json.dumps(cache, indent=2, sort_keys=True, ensure_ascii=False) + '\n')
    located = sum(1 for v in cache.values() if v.get('lat'))
    print(f'Wrote {CACHE}: {located}/{len(cache)} located.')


if __name__ == '__main__':
    main()
