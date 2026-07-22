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
    .venue__links { display: flex; flex-wrap: wrap; gap: 0.4rem 1.2rem; margin: 0 0 1.6rem; }
    .detail-card .venue__links { margin: 1.1rem 0 0; }
    .venue__links a { color: var(--accent-on-light); font: 600 0.9rem var(--font-body); text-decoration: none; }
    .venue__links a:hover { text-decoration: underline; }
    .venue__photo { width: 100%; max-width: 640px; aspect-ratio: 3 / 2; object-fit: cover; background: rgba(var(--ink-rgb),0.06); display: block; margin: 0 0 1.6rem; }
    .venue__desc p { font-size: 1.08rem; line-height: 1.7; color: rgba(var(--ink-rgb),0.82); max-width: var(--measure); margin: 0 0 1rem; }
    /* CAL-13/CAL-21: the decision facts live in the sticky aside card. */
    .venue__facts { display: grid; grid-template-columns: max-content 1fr; gap: 0.6rem 1.2rem; margin: 0; }
    .venue__facts dt { font: 600 0.72rem var(--font-body); letter-spacing: 0.13em; text-transform: uppercase; color: var(--gray); align-self: baseline; }
    .venue__facts dd { margin: 0; color: var(--ink); min-width: 0; overflow-wrap: anywhere; }
    .venue__facts a { color: var(--accent-on-light); text-decoration: none; font-weight: 600; }
    .venue__facts a:hover { text-decoration: underline; }
    .venue__section-h { font-size: clamp(1.3rem, 2.4vw, 1.7rem); margin: 2.4rem 0 1rem; }
    .venue__empty { color: rgba(var(--ink-rgb),0.55); }
    .venue__back { margin: 2.4rem 0 0; padding-top: 2rem; border-top: 1px solid rgba(var(--ink-rgb),0.14); }
    .venue__back a { color: var(--accent-on-light); text-decoration: none; }
    @media (max-width: 640px) { .venue__facts { grid-template-columns: 1fr; gap: 0.2rem; } .venue__facts dd { margin-bottom: 0.8rem; } }
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

    # Two-column detail shell (CAL-10 primitive, CAL-13/21 adoption): identity
    # + narrative in the reading column; the decision card (address · notes ·
    # map · next session · links) in the sticky aside. Collapses <900px.
    out.append('    <div class="detail-shell">')
    out.append('      <div class="detail-main">')
    out.append('    <span class="eyebrow">Venue</span>')
    out.append(f'    <h1 class="venue__h1">{_esc(name)}</h1>')

    place = v['neighborhood'] if v.get('city') == 'Denver' and v.get('neighborhood') else None
    area = f'{place}, {v["city"]}' if place else v.get('city', '')

    photo = X._safe_ext_url(v.get('photo_url') or '')
    if photo:
        out.append(
            f'    <img class="venue__photo" src="{_esc(photo)}" alt="{_esc(name)}" '
            f'loading="lazy" decoding="async" referrerpolicy="no-referrer">')

    # The reading column always carries a paragraph: the curated description
    # when Daniel has written one, else an honest factual line — most of the
    # published set is import-seeded, and a bare H1 next to a full aside would
    # read as a broken column.
    out.append('    <div class="venue__desc">')
    if (v.get('description') or '').strip():
        out.append(_paras(v['description']))
    else:
        n = len(session_rows)
        fallback = (
            f'{name} is one of the rooms on the Front Range sound bath '
            f'calendar{" in " + area if area else ""}. '
            + (f'It has {n} upcoming session{"s" if n != 1 else ""} listed — '
               f'dates, prices, and ticket links below.' if n else
               'Nothing is listed here right now — the calendar below has '
               'every upcoming session in the area.'))
        out.append(f'      <p>{_esc(fallback)}</p>')
    out.append('    </div>')

    # End the reading column; open the sticky decision aside.
    out.append('      </div>')  # .detail-main
    out.append('      <aside class="detail-aside">')
    out.append('        <div class="detail-card">')

    out.append('    <dl class="venue__facts">')
    if v.get('address'):
        out.append(f'      <dt>Address</dt><dd>{_esc(v["address"])}</dd>')
    if area:
        out.append(f'      <dt>Area</dt><dd>{_esc(area)}</dd>')
    if (v.get('parking_notes') or '').strip():
        out.append(f'      <dt>Getting there</dt><dd>{_esc(v["parking_notes"])}</dd>')
    if (v.get('accessibility_notes') or '').strip():
        out.append(f'      <dt>Accessibility</dt><dd>{_esc(v["accessibility_notes"])}</dd>')
    next_up = X.entity_next_up(session_rows, nav_prefix)
    if next_up:
        out.append(f'      <dt>Next up</dt><dd>{next_up}</dd>')
    if len(session_rows) > 1:
        out.append(f'      <dt>Upcoming</dt><dd>{len(session_rows)} sessions</dd>')
    # Cross-link the entity trio (CAL-13): the published practitioners who
    # play this room, from its own session rows. Dormant until profiles publish.
    practs = {}
    for r in session_rows:
        pr = r.get('practitioner') or {}
        if isinstance(pr, dict) and pr.get('slug') and pr.get('name'):
            practs.setdefault(pr['slug'], pr['name'])
    if practs:
        links = ', '.join(
            f'<a href="{_esc(f"{nav_prefix}practitioner/{s}/")}">{_esc(n_)}</a>'
            for s, n_ in sorted(practs.items(), key=lambda kv: kv[1].lower()))
        out.append(f'      <dt>Facilitators</dt><dd>{links}</dd>')
    out.append('    </dl>')

    map_src = _map_embed_src(v)
    if map_src:
        out.append(
            f'    <iframe class="detail-card__map" src="{_esc(map_src)}" loading="lazy" '
            f'referrerpolicy="no-referrer-when-downgrade" '
            f'title="Map of {_esc(name)}"></iframe>')

    links = []
    map_link = _map_link(v)
    if map_link:
        links.append(f'<a href="{_esc(map_link)}" target="_blank" rel="noopener">Open in Maps</a>')
    web = X._safe_ext_url(v.get('website_url') or '')
    if web:
        links.append(f'<a href="{_esc(web)}" target="_blank" rel="noopener">Website</a>')
    if links:
        out.append('    <p class="venue__links">' + ' '.join(links) + '</p>')

    out.append('        </div>')  # .detail-card
    out.append('      </aside>')  # .detail-aside
    out.append('    </div>')      # .detail-shell

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
