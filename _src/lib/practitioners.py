"""Sound Bath Calendar — practitioner pages (CAL-02).

Curated facilitator profiles: the person people follow. The admin holds the
entity (draft until published); the site reads the PUBLISHED set from
/feeds/practitioners.json and builds one durable, indexable /practitioner/<slug>/
page each, cross-linked from the events that person leads. Same graceful-feed
discipline as external_events: a missing feed never breaks the build (falls back
to the committed data/practitioners.json cache, then to nothing).

Assembly (base layout, <head>, publisher schema) is build.py's job; this module
returns the <main> body + the page-specific ProfilePage/Person schema, mirroring
the external-event permalink pipeline.
"""

import json
import os
import urllib.request

from _src.lib import external_events as X

DEFAULT_FEED_URL = 'https://admin.soundbathcalendar.com/feeds/practitioners.json'
CACHE_REL_PATH = os.path.join('data', 'practitioners.json')
FETCH_TIMEOUT_S = 10

_esc = X._esc


# ---------------------------------------------------------------------------
# Feed load (mirror external_events.load_feed) — never raises.
# ---------------------------------------------------------------------------

def empty_feed():
    return {'generated_at': None, 'practitioners': []}


def validate_feed(feed):
    """Shape-check a parsed practitioners feed. Raises ValueError on any problem.
    Load-bearing fields only: each practitioner needs a non-empty string slug +
    name; everything else has a safe render-time default."""
    if not isinstance(feed, dict):
        raise ValueError('feed root is not an object')
    if not isinstance(feed.get('practitioners'), list):
        raise ValueError('feed.practitioners is not a list')
    for i, p in enumerate(feed['practitioners']):
        where = f'practitioners[{i}]'
        if not isinstance(p, dict):
            raise ValueError(f'{where} is not an object')
        for key in ('slug', 'name'):
            if not isinstance(p.get(key), str) or not p[key]:
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
        log(f'  ⚠ practitioners cache unusable ({exc.__class__.__name__}: {exc}) — building with no practitioners')
        return empty_feed()


def load_feed(repo_root, log=print):
    """Return the practitioners feed dict, never raising. Precedence:
    PRACTITIONERS_FEED_FILE fixture > PRACTITIONERS_FEED_URL fetch (refreshes the
    committed cache) > committed data/practitioners.json > empty."""
    cache_path = os.path.join(repo_root, CACHE_REL_PATH)

    fixture = os.environ.get('PRACTITIONERS_FEED_FILE')
    if fixture:
        try:
            with open(fixture, 'r', encoding='utf-8') as f:
                feed = validate_feed(json.load(f))
            log(f'  ✓ practitioners feed from fixture {fixture} ({len(feed["practitioners"])}; committed file untouched)')
            return feed
        except Exception as exc:
            log(f'  ⚠ PRACTITIONERS_FEED_FILE unusable ({exc.__class__.__name__}: {exc}) — using committed cache')
            return _load_cache(cache_path, log)

    url = os.environ.get('PRACTITIONERS_FEED_URL', DEFAULT_FEED_URL)
    try:
        with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT_S) as resp:
            feed = validate_feed(json.loads(resp.read().decode('utf-8')))
    except Exception as exc:
        log(f'  ⚠ practitioners feed unavailable at {url} ({exc.__class__.__name__}) — using committed cache')
        return _load_cache(cache_path, log)

    if url.startswith(('http://', 'https://')):
        _write_cache(cache_path, feed)
        log(f'  ✓ practitioners feed fetched ({len(feed["practitioners"])}) — committed file refreshed')
    else:
        log(f'  ✓ practitioners feed from {url} ({len(feed["practitioners"])}; committed file untouched)')
    return feed


def published_practitioners(feed):
    """The feed already carries PUBLISHED only (the service filters), deduped by
    slug and name-sorted for a stable index + sitemap."""
    seen, out = set(), []
    for p in (feed or {}).get('practitioners', []):
        slug = (p.get('slug') or '').strip()
        if not slug or slug in seen:
            continue
        seen.add(slug)
        out.append(p)
    out.sort(key=lambda p: (p.get('name') or '').lower())
    return out


# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

def practitioner_path(slug):
    return f'practitioner/{slug}/'


def practitioner_url(slug, site_url):
    return f'{site_url}/{practitioner_path(slug)}'


# ---------------------------------------------------------------------------
# Sessions this person leads (from the shared event rows) — the aggregation
# that gives the page its reason to exist ("when is she playing next").
# ---------------------------------------------------------------------------

def row_practitioner_slug(row):
    p = row.get('practitioner')
    return (p or {}).get('slug') if isinstance(p, dict) else None


def sessions_for(slug, cal_rows):
    """Upcoming rows this practitioner leads, chronological."""
    out = [r for r in cal_rows if row_practitioner_slug(r) == slug]
    out.sort(key=lambda r: X.parse_iso(r['starts_at']))
    return out


def _practitioner_tag_slugs(session_rows):
    """Union of the canonical tags across this person's sessions, vocab-ordered."""
    present = set()
    for r in session_rows:
        present.update(X.row_tag_slugs(r))
    from _src.lib import taxonomy
    return [s for s, _l, _a in taxonomy.TAGS if s in present]


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

PRACTITIONER_PAGE_STYLE = """<style>
    .pract { }
    .pract__crumbs { font-size: 0.82rem; color: rgba(10,11,13,0.55); margin: 0 0 2rem; }
    .pract__crumbs a { color: var(--accent-on-light); text-decoration: none; }
    .pract__crumbs a:hover { text-decoration: underline; }
    .pract__head { display: flex; gap: 1.6rem; align-items: flex-start; flex-wrap: wrap; margin: 0 0 1.6rem; }
    .pract__photo { flex: 0 0 auto; width: 132px; height: 132px; object-fit: cover; background: rgba(10,11,13,0.06); }
    .pract__headtext { flex: 1 1 16rem; min-width: 14rem; }
    .pract__h1 { font-size: clamp(2rem, 4vw, 3rem); margin: 0.2rem 0 0.6rem; }
    .pract__links { display: flex; flex-wrap: wrap; gap: 0.4rem 1.2rem; margin: 0.4rem 0 0; }
    .pract__links a { color: var(--accent-on-light); font: 600 0.9rem var(--font-body); text-decoration: none; }
    .pract__links a:hover { text-decoration: underline; }
    .pract__bio, .pract__interview { max-width: 42rem; }
    .pract__bio p, .pract__interview p { font-size: 1.08rem; line-height: 1.7; color: rgba(10,11,13,0.82); margin: 0 0 1rem; }
    .pract__section-h { font-size: clamp(1.3rem, 2.4vw, 1.7rem); margin: 2.4rem 0 1rem; }
    .pract__empty { color: rgba(10,11,13,0.55); }
    .pract__back { margin: 2.4rem 0 0; padding-top: 2rem; border-top: 1px solid rgba(10,11,13,0.14); }
    .pract__back a { color: var(--accent-on-light); text-decoration: none; }
    .pract__back a:hover { text-decoration: underline; }
    @media (max-width: 560px) { .pract__photo { width: 96px; height: 96px; } }
  </style>"""


def _paras(text):
    """Split a free-text block into <p> paragraphs on blank lines (escaped)."""
    blocks = [b.strip() for b in (text or '').split('\n\n') if b.strip()]
    return '\n'.join(f'      <p>{_esc(b)}</p>' for b in blocks)


def render_practitioner_page(pract, session_rows, nav_prefix, site_url, now=None):
    """The <main> body for one practitioner's profile page."""
    now = X._now_utc(now)
    name = pract['name']
    out = ['<section class="section section--light pract">', '  <div class="container">']

    out.append('    <nav class="pract__crumbs" aria-label="Breadcrumb">')
    out.append(
        f'      <a href="{nav_prefix}">Calendar</a> <span aria-hidden="true">/</span> '
        f'<a href="{nav_prefix}practitioners/">Practitioners</a> '
        f'<span aria-hidden="true">/</span> <span>{_esc(name)}</span>')
    out.append('    </nav>')

    out.append('    <div class="pract__head">')
    photo = X._safe_ext_url(pract.get('photo_url') or '')
    if photo:
        out.append(
            f'      <img class="pract__photo" src="{_esc(photo)}" '
            f'alt="{_esc(name)}" loading="lazy" decoding="async" referrerpolicy="no-referrer">')
    out.append('      <div class="pract__headtext">')
    out.append('        <span class="eyebrow">Practitioner</span>')
    out.append(f'        <h1 class="pract__h1">{_esc(name)}</h1>')
    # Modality chips from their sessions.
    tag_slugs = _practitioner_tag_slugs(session_rows)
    if tag_slugs:
        from _src.lib import taxonomy
        chips = ''.join(
            f'<span class="cal-tag">{_esc(taxonomy.label_for(s))}</span>' for s in tag_slugs)
        out.append(f'        <p class="cal-event__tags">{chips}</p>')
    # External links.
    links = []
    web = X._safe_ext_url(pract.get('website_url') or '')
    if web:
        links.append(f'<a href="{_esc(web)}" target="_blank" rel="noopener">Website</a>')
    ig = X._safe_ext_url(pract.get('instagram_url') or '')
    if ig:
        links.append(f'<a href="{_esc(ig)}" target="_blank" rel="noopener">Instagram</a>')
    if links:
        out.append('        <p class="pract__links">' + ' '.join(links) + '</p>')
    out.append('      </div>')  # headtext
    out.append('    </div>')  # head

    if (pract.get('bio') or '').strip():
        out.append('    <div class="pract__bio">')
        out.append(_paras(pract['bio']))
        out.append('    </div>')

    if (pract.get('interview') or '').strip():
        out.append('    <h2 class="pract__section-h">In their words</h2>')
        out.append('    <div class="pract__interview">')
        out.append(_paras(pract['interview']))
        out.append('    </div>')

    # Upcoming sessions this person leads.
    out.append('    <h2 class="pract__section-h">Upcoming sessions</h2>')
    if session_rows:
        out.append('    ' + X._render_rows(session_rows, True, nav_prefix))
    else:
        out.append(
            f'    <p class="pract__empty">No upcoming sessions listed right now. '
            f'<a href="{nav_prefix}">See the full calendar →</a></p>')

    out.append(
        f'    <p class="pract__back"><a href="{nav_prefix}practitioners/">'
        'All practitioners →</a></p>')

    out.append('  </div>')
    out.append('</section>')
    return '\n'.join(out)


def person_schema(pract, canonical_url, session_rows):
    """ProfilePage wrapping a Person — the entity surface for search + AI."""
    from _src.lib import taxonomy
    person = {
        '@type': 'Person',
        'name': pract['name'],
        'url': canonical_url,
    }
    bio = (pract.get('bio') or '').strip()
    if bio:
        person['description'] = ' '.join(bio.split())
    photo = X._safe_ext_url(pract.get('photo_url') or '')
    if photo:
        person['image'] = photo
    same_as = [X._safe_ext_url(pract.get('website_url') or ''),
               X._safe_ext_url(pract.get('instagram_url') or '')]
    same_as = [u for u in same_as if u]
    if same_as:
        person['sameAs'] = same_as
    knows = [taxonomy.label_for(s) for s in _practitioner_tag_slugs(session_rows)]
    if knows:
        person['knowsAbout'] = knows
    return {
        '@context': 'https://schema.org',
        '@type': 'ProfilePage',
        'mainEntity': person,
    }


# ---------------------------------------------------------------------------
# Index page (/practitioners/) — a simple directory. Doorway-page discipline:
# the caller noindexes it until enough profiles exist to be a real page.
# ---------------------------------------------------------------------------

INDEX_STYLE = """<style>
    .practs__crumbs { font-size: 0.82rem; color: rgba(10,11,13,0.55); margin: 0 0 2rem; }
    .practs__crumbs a { color: var(--accent-on-light); text-decoration: none; }
    .practs__h1 { font-size: clamp(2rem, 4vw, 3rem); margin: 0.2rem 0 0.8rem; }
    .practs__lede { font-size: 1.1rem; color: rgba(10,11,13,0.75); max-width: 40rem; margin: 0 0 2rem; }
    .practs__grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr)); gap: 1.4rem; }
    .practs__card { display: flex; gap: 0.9rem; align-items: center; text-decoration: none; color: inherit; border: 1px solid rgba(10,11,13,0.14); padding: 0.9rem; }
    .practs__card:hover { border-color: var(--accent-on-light); }
    .practs__thumb { flex: 0 0 auto; width: 56px; height: 56px; object-fit: cover; background: rgba(10,11,13,0.06); }
    .practs__name { font: 500 1.05rem var(--font-display); color: var(--ink); }
    .practs__meta { font-size: 0.85rem; color: rgba(10,11,13,0.6); }
  </style>"""


def render_index(practs, count_by_slug, nav_prefix):
    """The <main> for /practitioners/ — a directory card per published profile."""
    out = ['<section class="section section--light practs">', '  <div class="container">']
    out.append('    <nav class="practs__crumbs" aria-label="Breadcrumb">')
    out.append(f'      <a href="{nav_prefix}">Calendar</a> <span aria-hidden="true">/</span> '
               '<span>Practitioners</span>')
    out.append('    </nav>')
    out.append('    <span class="eyebrow">Front Range calendar</span>')
    out.append('    <h1 class="practs__h1">Practitioners</h1>')
    out.append('    <p class="practs__lede">The facilitators leading sound baths across '
               'the Front Range — who they are, and where to find them next.</p>')
    if not practs:
        out.append(X.render_empty_state(
            nav_prefix,
            'The first facilitator profiles are being written — who they are, the '
            'instruments they play, and when they are next leading a room. Until then, '
            'find them by session on the calendar.'))
    else:
        out.append('    <div class="practs__grid">')
        for p in practs:
            slug = p['slug']
            href = f'{nav_prefix}{practitioner_path(slug)}'
            photo = X._safe_ext_url(p.get('photo_url') or '')
            n = count_by_slug.get(slug, 0)
            meta = f'{n} upcoming session{"" if n == 1 else "s"}' if n else 'Profile'
            thumb = (f'<img class="practs__thumb" src="{_esc(photo)}" alt="{_esc(p["name"])}" '
                     f'loading="lazy" referrerpolicy="no-referrer">') if photo else ''
            out.append(
                f'      <a class="practs__card" href="{_esc(href)}">{thumb}'
                f'<span><span class="practs__name">{_esc(p["name"])}</span><br>'
                f'<span class="practs__meta">{_esc(meta)}</span></span></a>')
        out.append('    </div>')
    out.append('  </div>')
    out.append('</section>')
    return '\n'.join(out)


def index_itemlist(practs, site_url):
    """ItemList of ProfilePage links for the index (or None when empty)."""
    if not practs:
        return None
    items = []
    for i, p in enumerate(practs, start=1):
        items.append({'@type': 'ListItem', 'position': i,
                      'name': p['name'],
                      'url': practitioner_url(p['slug'], site_url)})
    return {
        '@context': 'https://schema.org',
        '@type': 'ItemList',
        'name': 'Sound bath practitioners on the Front Range',
        'itemListElement': items,
    }
