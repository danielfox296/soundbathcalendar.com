"""Sound Bath Calendar — operator pages (CAL-08).

Curated organizer profiles: the org/host running the session (every event
carries an `operator` string + `operatorUrl`). Completes the entity trio —
Person = practitioner, Place = venue, Organization = operator. Leaner than a
venue (an operator is not a place): no address, map, or notes — just who they
are, their own site, and every upcoming session they run ACROSS ALL VENUES,
each row already cross-linking the venue + practitioner involved.

DUPLICATE-CONTENT GUARD: many operators are owner-operated (operator name == a
venue name), so this page would duplicate that venue page. The publish gate in
admin handles it — Daniel publishes only the operators worth a DISTINCT page
(traveling organizers running at multiple venues). The site only ever sees the
PUBLISHED set from /feeds/operators.json.

Same graceful-feed discipline + assembly split as venues.py: a missing feed
never breaks the build, and build.py owns the <head>/publisher schema.
"""

import json
import os
import urllib.request

from _src.lib import external_events as X

DEFAULT_FEED_URL = 'https://admin.soundbathcalendar.com/feeds/operators.json'
CACHE_REL_PATH = os.path.join('data', 'operators.json')
FETCH_TIMEOUT_S = 10

_esc = X._esc


# ---------------------------------------------------------------------------
# Feed load (mirror venues.load_feed) — never raises.
# ---------------------------------------------------------------------------

def empty_feed():
    return {'generated_at': None, 'operators': []}


def validate_feed(feed):
    if not isinstance(feed, dict):
        raise ValueError('feed root is not an object')
    if not isinstance(feed.get('operators'), list):
        raise ValueError('feed.operators is not a list')
    for i, o in enumerate(feed['operators']):
        where = f'operators[{i}]'
        if not isinstance(o, dict):
            raise ValueError(f'{where} is not an object')
        for key in ('slug', 'name'):
            if not isinstance(o.get(key), str) or not o[key]:
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
        log(f'  ⚠ operators cache unusable ({exc.__class__.__name__}: {exc}) — building with no operators')
        return empty_feed()


def load_feed(repo_root, log=print):
    cache_path = os.path.join(repo_root, CACHE_REL_PATH)

    fixture = os.environ.get('OPERATORS_FEED_FILE')
    if fixture:
        try:
            with open(fixture, 'r', encoding='utf-8') as f:
                feed = validate_feed(json.load(f))
            log(f'  ✓ operators feed from fixture {fixture} ({len(feed["operators"])}; committed file untouched)')
            return feed
        except Exception as exc:
            log(f'  ⚠ OPERATORS_FEED_FILE unusable ({exc.__class__.__name__}: {exc}) — using committed cache')
            return _load_cache(cache_path, log)

    url = os.environ.get('OPERATORS_FEED_URL', DEFAULT_FEED_URL)
    try:
        with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT_S) as resp:
            feed = validate_feed(json.loads(resp.read().decode('utf-8')))
    except Exception as exc:
        log(f'  ⚠ operators feed unavailable at {url} ({exc.__class__.__name__}) — using committed cache')
        return _load_cache(cache_path, log)

    if url.startswith(('http://', 'https://')):
        _write_cache(cache_path, feed)
        log(f'  ✓ operators feed fetched ({len(feed["operators"])}) — committed file refreshed')
    else:
        log(f'  ✓ operators feed from {url} ({len(feed["operators"])}; committed file untouched)')
    return feed


def published_operators(feed):
    seen, out = set(), []
    for o in (feed or {}).get('operators', []):
        slug = (o.get('slug') or '').strip()
        if not slug or slug in seen:
            continue
        seen.add(slug)
        out.append(o)
    out.sort(key=lambda o: (o.get('name') or '').lower())
    return out


# ---------------------------------------------------------------------------
# URLs + session aggregation
# ---------------------------------------------------------------------------

def operator_path(slug):
    return f'operator/{slug}/'


def operator_url(slug, site_url):
    return f'{site_url}/{operator_path(slug)}'


def row_operator_slug(row):
    o = row.get('operator_ref')
    return (o or {}).get('slug') if isinstance(o, dict) else None


def sessions_for(slug, cal_rows):
    out = [r for r in cal_rows if row_operator_slug(r) == slug]
    out.sort(key=lambda r: X.parse_iso(r['starts_at']))
    return out


def _venue_names(session_rows):
    """The distinct rooms this operator runs, in first-seen order — the 'across
    all venues' fact that earns an operator its own page vs. a venue page."""
    seen, names = set(), []
    for r in session_rows:
        v = (r.get('venue') or '').strip()
        key = v.lower()
        if v and key not in seen:
            seen.add(key)
            names.append(v)
    return names


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

OPERATOR_PAGE_STYLE = """<style>
    .operator__crumbs { font-size: 0.82rem; color: rgba(var(--ink-rgb),0.55); margin: 0 0 2rem; }
    .operator__crumbs a { color: var(--accent-on-light); text-decoration: none; }
    .operator__crumbs a:hover { text-decoration: underline; }
    .operator__h1 { font-size: clamp(2rem, 4vw, 3rem); margin: 0.2rem 0 0.4rem; }
    .operator__links { display: flex; flex-wrap: wrap; gap: 0.4rem 1.2rem; margin: 1.1rem 0 0; }
    .operator__links a { color: var(--accent-on-light); font: 600 0.9rem var(--font-body); text-decoration: none; }
    .operator__links a:hover { text-decoration: underline; }
    .operator__desc p { font-size: 1.08rem; line-height: 1.7; color: rgba(var(--ink-rgb),0.82); max-width: var(--measure); margin: 0 0 1rem; }
    /* CAL-13/CAL-21: decision facts in the sticky aside card. */
    .operator__facts { display: grid; grid-template-columns: max-content 1fr; gap: 0.6rem 1.2rem; margin: 0; }
    .operator__facts dt { font: 600 0.72rem var(--font-body); letter-spacing: 0.13em; text-transform: uppercase; color: var(--gray); align-self: baseline; }
    .operator__facts dd { margin: 0; color: var(--ink); min-width: 0; overflow-wrap: anywhere; }
    .operator__facts a { color: var(--accent-on-light); text-decoration: none; font-weight: 600; }
    .operator__facts a:hover { text-decoration: underline; }
    @media (max-width: 640px) { .operator__facts { grid-template-columns: 1fr; gap: 0.2rem; } .operator__facts dd { margin-bottom: 0.8rem; } }
    .operator__section-h { font-size: clamp(1.3rem, 2.4vw, 1.7rem); margin: 2.4rem 0 1rem; }
    .operator__empty { color: rgba(var(--ink-rgb),0.55); }
    .operator__back { margin: 2.4rem 0 0; padding-top: 2rem; border-top: 1px solid rgba(var(--ink-rgb),0.14); }
    .operator__back a { color: var(--accent-on-light); text-decoration: none; }
  </style>"""


def _paras(text):
    blocks = [b.strip() for b in (text or '').split('\n\n') if b.strip()]
    return '\n'.join(f'      <p>{_esc(b)}</p>' for b in blocks)


def render_operator_page(o, session_rows, nav_prefix, site_url, now=None):
    now = X._now_utc(now)
    name = o['name']
    out = ['<section class="section section--light operator">', '  <div class="container">']

    out.append('    <nav class="operator__crumbs" aria-label="Breadcrumb">')
    out.append(
        f'      <a href="{nav_prefix}">Calendar</a> <span aria-hidden="true">/</span> '
        f'<a href="{nav_prefix}operators/">Organizers</a> '
        f'<span aria-hidden="true">/</span> <span>{_esc(name)}</span>')
    out.append('    </nav>')

    # Two-column detail shell (CAL-10 primitive, CAL-13/21 adoption): identity
    # + narrative in the reading column; rooms · next session · website in the
    # sticky aside card. Collapses <900px.
    out.append('    <div class="detail-shell">')
    out.append('      <div class="detail-main">')
    out.append('    <span class="eyebrow">Organizer</span>')
    out.append(f'    <h1 class="operator__h1">{_esc(name)}</h1>')

    # The reading column always carries a paragraph: the curated description
    # when written, else an honest factual line (most operators are
    # import-seeded and description-less).
    out.append('    <div class="operator__desc">')
    if (o.get('description') or '').strip():
        out.append(_paras(o['description']))
    else:
        n = len(session_rows)
        rooms_n = len(_venue_names(session_rows))
        fallback = (
            f'{name} runs sound baths on the Front Range calendar'
            + (f' across {rooms_n} rooms' if rooms_n > 1 else '')
            + ('. ' + f'{n} upcoming session{"s" if n != 1 else ""} listed — '
               f'dates, prices, and ticket links below.' if n else
               '. Nothing is listed right now — the full calendar has every '
               'upcoming session in the area.'))
        out.append(f'      <p>{_esc(fallback)}</p>')
    out.append('    </div>')

    # End the reading column; open the sticky decision aside.
    out.append('      </div>')  # .detail-main

    # Rooms: linked to their venue page when the session rows carry a published
    # venue_ref (CAL-03), plain names otherwise — the entity-trio cross-link.
    rooms, seen = [], set()
    for r in session_rows:
        vname = (r.get('venue') or '').strip()
        if not vname or vname.lower() in seen:
            continue
        seen.add(vname.lower())
        vr = r.get('venue_ref') or {}
        slug = vr.get('slug') if isinstance(vr, dict) else None
        if slug:
            rooms.append(f'<a href="{_esc(f"{nav_prefix}venue/{slug}/")}">{_esc(vname)}</a>')
        else:
            rooms.append(_esc(vname))
    facts = []
    if rooms:
        shown = rooms[:6]
        rooms_dd = ', '.join(shown)
        if len(rooms) > len(shown):
            rooms_dd += f' + {len(rooms) - len(shown)} more'
        facts.append(f'      <dt>Rooms</dt><dd>{rooms_dd}</dd>')
    next_up = X.entity_next_up(session_rows, nav_prefix)
    if next_up:
        facts.append(f'      <dt>Next up</dt><dd>{next_up}</dd>')
    if len(session_rows) > 1:
        facts.append(f'      <dt>Upcoming</dt><dd>{len(session_rows)} sessions</dd>')

    web = X._safe_ext_url(o.get('website_url') or '')

    # An organizer with nothing upcoming and no website gets no card at all —
    # never an empty bordered box in the aside.
    if facts or web:
        out.append('      <aside class="detail-aside">')
        out.append('        <div class="detail-card">')
        if facts:
            out.append('    <dl class="operator__facts">')
            out.extend(facts)
            out.append('    </dl>')
        if web:
            out.append('    <p class="operator__links">'
                       f'<a href="{_esc(web)}" target="_blank" rel="noopener">Website</a></p>')
        out.append('        </div>')  # .detail-card
        out.append('      </aside>')  # .detail-aside
    out.append('    </div>')      # .detail-shell

    out.append('    <h2 class="operator__section-h">Upcoming sessions</h2>')
    if session_rows:
        out.append('    ' + X._render_rows(session_rows, True, nav_prefix))
    else:
        out.append(
            f'    <p class="operator__empty">No upcoming sessions listed right now. '
            f'<a href="{nav_prefix}">See the full calendar →</a></p>')

    out.append(
        f'    <p class="operator__back"><a href="{nav_prefix}operators/">All organizers →</a></p>')

    out.append('  </div>')
    out.append('</section>')
    return '\n'.join(out)


def organization_schema(o, canonical_url):
    """An Organization for the operator (accurate — we don't assert we run it).
    url is the calendar's page for them; sameAs points at their own site so
    search/AI can reconcile this entity with the operator's real presence."""
    org = {
        '@context': 'https://schema.org',
        '@type': 'Organization',
        'name': o['name'],
        'url': canonical_url,
    }
    if (o.get('description') or '').strip():
        org['description'] = ' '.join(o['description'].split())
    same_as = [u for u in (X._safe_ext_url(o.get('website_url') or ''),) if u]
    if same_as:
        org['sameAs'] = same_as
    return org


# ---------------------------------------------------------------------------
# Index (/operators/)
# ---------------------------------------------------------------------------

# The directory design (.dir-*) is shared with /practitioners/ and /venues/
# and lives in styles.css; no page-specific style block remains.
INDEX_STYLE = ''


def render_index(operators, count_by_slug, nav_prefix, art_by_slug=None):
    from _src.lib import directory
    art_by_slug = art_by_slug or {}
    out = ['<section class="section section--light operators">', '  <div class="container">']
    out.append(directory.render_head(
        nav_prefix, 'Organizers', 'Organizers',
        'The collectives and studios running sound baths across Denver and the '
        'Front Range — who they are, and where you can catch them next.'))
    if not operators:
        out.append(X.render_empty_state(
            nav_prefix,
            'The first organizer profiles are being written — the collectives and '
            'studios running these rooms, with every session they host in one place. '
            'For now, browse them by session on the calendar.'))
    else:
        out.append('    <div class="dir-grid">')
        for o in operators:
            slug = o['slug']
            href = f'{nav_prefix}{operator_path(slug)}'
            n = count_by_slug.get(slug, 0)
            meta = (f'{n} upcoming' if n else 'Organizer')
            out.append(directory.render_card(
                href, o['name'], meta, art_by_slug.get(slug, '')))
        out.append('    </div>')
    out.append('  </div>')
    out.append('</section>')
    return '\n'.join(out)


def index_itemlist(operators, site_url):
    if not operators:
        return None
    items = []
    for i, o in enumerate(operators, start=1):
        items.append({'@type': 'ListItem', 'position': i,
                      'name': o['name'], 'url': operator_url(o['slug'], site_url)})
    return {
        '@context': 'https://schema.org',
        '@type': 'ItemList',
        'name': 'Sound bath organizers on the Front Range',
        'itemListElement': items,
    }
