"""Sound Bath Calendar — venue pages (CAL-03).

Curated room profiles: the place a session happens. Denser than practitioners
(nearly every event carries a venue + address), so a page's core — address, an
embedded map, and every upcoming session there across all operators — is real
content without curation; the notes (parking, accessibility, "what the room is
like", photo) are the enrichment. The admin holds the entity (draft until
published); the site reads the PUBLISHED set from /feeds/venues.json.

Same graceful-feed discipline + assembly split as practitioners.py: a missing
feed never breaks the build, and build.py owns the <head>/publisher schema.
"""

import json
import os
import urllib.request
from urllib.parse import quote_plus

from _src.lib import external_events as X

DEFAULT_FEED_URL = 'https://admin.soundbathcalendar.com/feeds/venues.json'
CACHE_REL_PATH = os.path.join('data', 'venues.json')
FETCH_TIMEOUT_S = 10

_esc = X._esc


# ---------------------------------------------------------------------------
# Feed load (mirror practitioners.load_feed) — never raises.
# ---------------------------------------------------------------------------

def empty_feed():
    return {'generated_at': None, 'venues': []}


def validate_feed(feed):
    if not isinstance(feed, dict):
        raise ValueError('feed root is not an object')
    if not isinstance(feed.get('venues'), list):
        raise ValueError('feed.venues is not a list')
    for i, v in enumerate(feed['venues']):
        where = f'venues[{i}]'
        if not isinstance(v, dict):
            raise ValueError(f'{where} is not an object')
        for key in ('slug', 'name'):
            if not isinstance(v.get(key), str) or not v[key]:
                raise ValueError(f'{where}.{key} missing or not a string')
    return feed


def _write_cache(cache_path, feed):
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, 'w', encoding='utf-8') as f:
        f.write(json.dumps(feed, indent=2, sort_keys=True, ensure_ascii=False) + '\n')


def _load_cache(cache_path, log):
    try:
        with open(cache_path, 'r', encoding='utf-8') as f:
            return validate_feed(json.load(f))
    except Exception as exc:
        log(f'  ⚠ venues cache unusable ({exc.__class__.__name__}: {exc}) — building with no venues')
        return empty_feed()


def load_feed(repo_root, log=print):
    cache_path = os.path.join(repo_root, CACHE_REL_PATH)

    fixture = os.environ.get('VENUES_FEED_FILE')
    if fixture:
        try:
            with open(fixture, 'r', encoding='utf-8') as f:
                feed = validate_feed(json.load(f))
            log(f'  ✓ venues feed from fixture {fixture} ({len(feed["venues"])}; committed file untouched)')
            return feed
        except Exception as exc:
            log(f'  ⚠ VENUES_FEED_FILE unusable ({exc.__class__.__name__}: {exc}) — using committed cache')
            return _load_cache(cache_path, log)

    url = os.environ.get('VENUES_FEED_URL', DEFAULT_FEED_URL)
    try:
        with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT_S) as resp:
            feed = validate_feed(json.loads(resp.read().decode('utf-8')))
    except Exception as exc:
        log(f'  ⚠ venues feed unavailable at {url} ({exc.__class__.__name__}) — using committed cache')
        return _load_cache(cache_path, log)

    if url.startswith(('http://', 'https://')):
        _write_cache(cache_path, feed)
        log(f'  ✓ venues feed fetched ({len(feed["venues"])}) — committed file refreshed')
    else:
        log(f'  ✓ venues feed from {url} ({len(feed["venues"])}; committed file untouched)')
    return feed


def published_venues(feed):
    seen, out = set(), []
    for v in (feed or {}).get('venues', []):
        slug = (v.get('slug') or '').strip()
        if not slug or slug in seen:
            continue
        seen.add(slug)
        out.append(v)
    out.sort(key=lambda v: (v.get('name') or '').lower())
    return out


# ---------------------------------------------------------------------------
# URLs + session aggregation
# ---------------------------------------------------------------------------

def venue_path(slug):
    return f'venue/{slug}/'


def venue_url(slug, site_url):
    return f'{site_url}/{venue_path(slug)}'


def row_venue_slug(row):
    v = row.get('venue_ref')
    return (v or {}).get('slug') if isinstance(v, dict) else None


def sessions_for(slug, cal_rows):
    out = [r for r in cal_rows if row_venue_slug(r) == slug]
    out.sort(key=lambda r: X.parse_iso(r['starts_at']))
    return out


def _map_query(v):
    """The best address string for a maps query: street address + city, else
    the venue name + city, always with the state so the pin lands in Colorado."""
    bits = [x for x in (v.get('address'), v.get('city')) if x]
    if not v.get('address'):
        bits = [x for x in (v.get('name'), v.get('city')) if x]
    q = ', '.join(bits)
    return f'{q}, CO' if q else ''


def _map_embed_src(v):
    q = _map_query(v)
    return f'https://maps.google.com/maps?q={quote_plus(q)}&z=15&output=embed' if q else ''


def _map_link(v):
    q = _map_query(v)
    return f'https://www.google.com/maps/search/?api=1&query={quote_plus(q)}' if q else ''


def _venue_tag_slugs(session_rows):
    present = set()
    for r in session_rows:
        present.update(X.row_tag_slugs(r))
    from _src.lib import taxonomy
    return [s for s, _l, _a in taxonomy.TAGS if s in present]


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

VENUE_PAGE_STYLE = """<style>
    .venue__crumbs { font-size: 0.82rem; color: rgba(var(--ink-rgb),0.55); margin: 0 0 2rem; }
    .venue__crumbs a { color: var(--accent-on-light); text-decoration: none; }
    .venue__crumbs a:hover { text-decoration: underline; }
    .venue__h1 { font-size: clamp(2rem, 4vw, 3rem); margin: 0.2rem 0 0.4rem; }
    .venue__where { font-size: 1.05rem; color: rgba(var(--ink-rgb),0.72); margin: 0 0 1.2rem; }
    .venue__links { display: flex; flex-wrap: wrap; gap: 0.4rem 1.2rem; margin: 0 0 1.6rem; }
    .venue__links a { color: var(--accent-on-light); font: 600 0.9rem var(--font-body); text-decoration: none; }
    .venue__links a:hover { text-decoration: underline; }
    .venue__photo { width: 100%; max-width: 640px; aspect-ratio: 3 / 2; object-fit: cover; background: rgba(var(--ink-rgb),0.06); display: block; margin: 0 0 1.6rem; }
    .venue__map { width: 100%; max-width: 640px; aspect-ratio: 16 / 9; border: 1px solid rgba(var(--ink-rgb),0.14); margin: 0 0 1.6rem; }
    .venue__desc p { font-size: 1.08rem; line-height: 1.7; color: rgba(var(--ink-rgb),0.82); max-width: 42rem; margin: 0 0 1rem; }
    .venue__notes { display: grid; grid-template-columns: max-content 1fr; gap: 0.6rem 1.6rem; margin: 1.6rem 0; max-width: 42rem; }
    .venue__notes dt { font: 600 0.72rem var(--font-body); letter-spacing: 0.13em; text-transform: uppercase; color: var(--gray); align-self: baseline; }
    .venue__notes dd { margin: 0; color: var(--ink); }
    .venue__section-h { font-size: clamp(1.3rem, 2.4vw, 1.7rem); margin: 2.4rem 0 1rem; }
    .venue__empty { color: rgba(var(--ink-rgb),0.55); }
    .venue__back { margin: 2.4rem 0 0; padding-top: 2rem; border-top: 1px solid rgba(var(--ink-rgb),0.14); }
    .venue__back a { color: var(--accent-on-light); text-decoration: none; }
    @media (max-width: 640px) { .venue__notes { grid-template-columns: 1fr; gap: 0.2rem; } .venue__notes dd { margin-bottom: 0.8rem; } }
  </style>"""


def _paras(text):
    blocks = [b.strip() for b in (text or '').split('\n\n') if b.strip()]
    return '\n'.join(f'      <p>{_esc(b)}</p>' for b in blocks)


def render_venue_page(v, session_rows, nav_prefix, site_url, now=None):
    now = X._now_utc(now)
    name = v['name']
    out = ['<section class="section section--light venue">', '  <div class="container">']

    out.append('    <nav class="venue__crumbs" aria-label="Breadcrumb">')
    out.append(
        f'      <a href="{nav_prefix}">Calendar</a> <span aria-hidden="true">/</span> '
        f'<a href="{nav_prefix}venues/">Venues</a> '
        f'<span aria-hidden="true">/</span> <span>{_esc(name)}</span>')
    out.append('    </nav>')

    out.append('    <span class="eyebrow">Venue</span>')
    out.append(f'    <h1 class="venue__h1">{_esc(name)}</h1>')

    place = v['neighborhood'] if v.get('city') == 'Denver' and v.get('neighborhood') else None
    area = f'{place}, {v["city"]}' if place else v.get('city', '')
    where = ' · '.join(x for x in (v.get('address'), area) if x)
    if where:
        out.append(f'    <p class="venue__where">{_esc(where)}</p>')

    links = []
    map_link = _map_link(v)
    if map_link:
        links.append(f'<a href="{_esc(map_link)}" target="_blank" rel="noopener">Open in Maps</a>')
    web = X._safe_ext_url(v.get('website_url') or '')
    if web:
        links.append(f'<a href="{_esc(web)}" target="_blank" rel="noopener">Website</a>')
    if links:
        out.append('    <p class="venue__links">' + ' '.join(links) + '</p>')

    photo = X._safe_ext_url(v.get('photo_url') or '')
    if photo:
        out.append(
            f'    <img class="venue__photo" src="{_esc(photo)}" alt="{_esc(name)}" '
            f'loading="lazy" decoding="async" referrerpolicy="no-referrer">')

    map_src = _map_embed_src(v)
    if map_src:
        out.append(
            f'    <iframe class="venue__map" src="{_esc(map_src)}" loading="lazy" '
            f'referrerpolicy="no-referrer-when-downgrade" '
            f'title="Map of {_esc(name)}"></iframe>')

    if (v.get('description') or '').strip():
        out.append('    <div class="venue__desc">')
        out.append(_paras(v['description']))
        out.append('    </div>')

    notes = []
    if (v.get('parking_notes') or '').strip():
        notes.append(('Getting there', v['parking_notes']))
    if (v.get('accessibility_notes') or '').strip():
        notes.append(('Accessibility', v['accessibility_notes']))
    if notes:
        out.append('    <dl class="venue__notes">')
        for dt, dd in notes:
            out.append(f'      <dt>{_esc(dt)}</dt><dd>{_esc(dd)}</dd>')
        out.append('    </dl>')

    out.append('    <h2 class="venue__section-h">Upcoming sessions here</h2>')
    if session_rows:
        out.append('    ' + X._render_rows(session_rows, True, nav_prefix))
    else:
        out.append(
            f'    <p class="venue__empty">No upcoming sessions listed here right now. '
            f'<a href="{nav_prefix}">See the full calendar →</a></p>')

    out.append(
        f'    <p class="venue__back"><a href="{nav_prefix}venues/">All venues →</a></p>')

    out.append('  </div>')
    out.append('</section>')
    return '\n'.join(out)


def place_schema(v, canonical_url, session_rows):
    """A Place for the venue (accurate — we don't assert we own the business).
    PostalAddress + hasMap; amenity flags surfaced when curated."""
    place = {
        '@context': 'https://schema.org',
        '@type': 'Place',
        'name': v['name'],
        'url': canonical_url,
    }
    addr = {'@type': 'PostalAddress', 'addressRegion': 'CO', 'addressCountry': 'US'}
    if v.get('address'):
        addr['streetAddress'] = v['address']
    if v.get('city'):
        addr['addressLocality'] = v['city']
    place['address'] = addr
    mp = _map_link(v)
    if mp:
        place['hasMap'] = mp
    photo = X._safe_ext_url(v.get('photo_url') or '')
    if photo:
        place['photo'] = photo
    if (v.get('description') or '').strip():
        place['description'] = ' '.join(v['description'].split())
    if (v.get('accessibility_notes') or '').strip():
        # A human-readable accessibility summary (schema.org accepts text here).
        place['accessibilityFeature'] = ' '.join(v['accessibility_notes'].split())
    return place


# ---------------------------------------------------------------------------
# Index (/venues/)
# ---------------------------------------------------------------------------

INDEX_STYLE = """<style>
    .venues__crumbs { font-size: 0.82rem; color: rgba(var(--ink-rgb),0.55); margin: 0 0 2rem; }
    .venues__crumbs a { color: var(--accent-on-light); text-decoration: none; }
    .venues__h1 { font-size: clamp(2rem, 4vw, 3rem); margin: 0.2rem 0 0.8rem; }
    .venues__lede { font-size: 1.1rem; color: rgba(var(--ink-rgb),0.75); max-width: 40rem; margin: 0 0 2rem; }
    .venues__grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr)); gap: 1.4rem; }
    .venues__card { display: block; text-decoration: none; color: inherit; border: 1px solid rgba(var(--ink-rgb),0.14); padding: 1rem; }
    .venues__card:hover { border-color: var(--accent-on-light); }
    .venues__name { font: 500 1.1rem var(--font-display); color: var(--ink); }
    .venues__meta { font-size: 0.85rem; color: rgba(var(--ink-rgb),0.6); margin-top: 0.2rem; }
  </style>"""


def render_index(venues, count_by_slug, nav_prefix):
    out = ['<section class="section section--light venues">', '  <div class="container">']
    out.append('    <nav class="venues__crumbs" aria-label="Breadcrumb">')
    out.append(f'      <a href="{nav_prefix}">Calendar</a> <span aria-hidden="true">/</span> '
               '<span>Venues</span>')
    out.append('    </nav>')
    out.append('    <span class="eyebrow">Front Range calendar</span>')
    out.append('    <h1 class="venues__h1">Venues</h1>')
    out.append('    <p class="venues__lede">The rooms hosting sound baths across Denver and '
               'the Front Range — where they are, what to expect, and what is on there next.</p>')
    if not venues:
        out.append(X.render_empty_state(
            nav_prefix,
            'The first venue profiles are being written — where each room is, how to '
            'get there, and what it is like inside. Every room is already on the '
            'calendar and the map.'))
    else:
        out.append('    <div class="venues__grid">')
        for v in venues:
            slug = v['slug']
            href = f'{nav_prefix}{venue_path(slug)}'
            place = v['neighborhood'] if v.get('city') == 'Denver' and v.get('neighborhood') else None
            area = f'{place}, {v["city"]}' if place else v.get('city', '')
            n = count_by_slug.get(slug, 0)
            meta = ' · '.join(x for x in (area, (f'{n} upcoming' if n else '')) if x) or 'Venue'
            out.append(
                f'      <a class="venues__card" href="{_esc(href)}">'
                f'<span class="venues__name">{_esc(v["name"])}</span>'
                f'<span class="venues__meta">{_esc(meta)}</span></a>')
        out.append('    </div>')
    out.append('  </div>')
    out.append('</section>')
    return '\n'.join(out)


def index_itemlist(venues, site_url):
    if not venues:
        return None
    items = []
    for i, v in enumerate(venues, start=1):
        items.append({'@type': 'ListItem', 'position': i,
                      'name': v['name'], 'url': venue_url(v['slug'], site_url)})
    return {
        '@context': 'https://schema.org',
        '@type': 'ItemList',
        'name': 'Sound bath venues on the Front Range',
        'itemListElement': items,
    }
