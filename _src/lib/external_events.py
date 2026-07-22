"""External sound-events feed loader + calendar renderer for build.py.

SOUND BATH CALENDAR fork (2026-07-19 port): the calendar lives at the ROOT of
soundbathcalendar.com — permalinks at /event/<slug>/ — and Firstwater is one
operator among many (its rows link out to thefirstwater.co session pages).
Divergences from the site/ original are marked with `# [port]`.

The Front Range calendar lists sound events run by other operators alongside
Firstwater's own dated sessions. At build time we:
  1. fetch the calendar feed (env CALENDAR_FEED_URL, default: the events
     service /feeds/calendar.json, which serves APPROVED events only),
  2. validate its shape and write it to data/external-events.json
     (committed, deterministic formatting) so every future build has a
     known-good copy,
  3. on ANY fetch/parse/validation failure: warn and fall back to the
     committed data/external-events.json, then to an empty feed. A broken
     feed never breaks the build.

INTERIM (Week 1) note: /feeds/calendar.json does not exist yet. Until the
service ships it, the fetch fails on every build and we fall back to the
committed data/external-events.json — which the pull agent writes as a PR
and Daniel reviews. That committed file is BOTH the interim source of truth
AND the eventual cache: once the service serves the feed, a successful HTTP
fetch overwrites it (same discipline as sessions_feed + data/sessions-cache.json).
Set CALENDAR_FEED_FILE=/abs/path to build against a local fixture without
ever touching the committed file.

Stdlib only — no new dependencies. Date/time formatting and the Firstwater
Event builder are reused from sessions_feed so the two feeds never drift.

FEED CONTRACT (GET {CALENDAR_FEED_URL}), shape:
{ "generated_at": "<ISO>", "events": [ {
    "name","operator","starts_at","venue","address",
    "city": "Denver|Boulder|Fort Collins|Colorado Springs",
    "neighborhood": <str|null>,
    "price","ticket_url","source_url","tags":[...],
    "confidence": <0..1>, "dedup_key","status","note","rejection_note",
    # v2 (all optional; "" when unknown):
    "image_url",       # listing image / flyer (og:image). http(s) only, scrubbed.
    "facilitator",     # the PERSON leading the session (distinct from operator).
    "operator_url",    # the operator's OWN page. http(s) only, scrubbed.
    "venue_url",       # the venue's OWN page, when distinct. http(s) only, scrubbed.
    "description" } ] }# factual, original 1-2 sentence description of the event.
Timestamps ISO-8601 with offset (America/Denver local). Only status="approved"
events are ever rendered; candidate/rejected never leave the service and are
filtered here too as a belt-and-braces guard.

NOTE vs DESCRIPTION: `note` is Daniel's editorial one-liner (his opinion, his
voice, verbatim only, usually empty) — the moat. `description` is a NEUTRAL
FACTUAL sentence stating what the event IS, never whether it's good. When
`description` is empty the build synthesizes a deterministic TEMPLATE
description from the structured fields (see template_description) so no row or
permalink is ever thin. Precedence for any descriptive text: `note` is the
editorial line (rendered distinctly), description-or-template is the factual
line (always rendered).
"""

import html
import json
import os
import re
import unicodedata
import urllib.request
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus, urlencode

from _src.lib import ics as ics_lib
from _src.lib import taxonomy
from _src.lib import sessions_feed
from _src.lib.sessions_feed import DENVER, parse_iso

DEFAULT_FEED_URL = 'https://admin.soundbathcalendar.com/feeds/calendar.json'
CACHE_REL_PATH = os.path.join('data', 'external-events.json')
FETCH_TIMEOUT_S = 10

# [port] Firstwater's own session pages stay on the artist site; every
# Firstwater row on this calendar links out to them absolutely.
FIRSTWATER_URL = 'https://thefirstwater.co'

# The calendar's own origin — used for absolute webcal:// + https .ics subscribe
# URLs (the site is static, so every .ics is a build-emitted file served here).
CALENDAR_ORIGIN = 'soundbathcalendar.com'

# Canonical section keys, in the fixed render order (geography → time).
CITIES = ('Denver', 'Boulder', 'Fort Collins', 'Colorado Springs')
# Anchor ids for the in-page jump nav (must match sections/01-content.html).
CITY_ANCHOR = {
    'Denver': 'denver',
    'Boulder': 'boulder',
    'Fort Collins': 'fort-collins',
    'Colorado Springs': 'colorado-springs',
}
# Query-language H2 per area ("sound baths", the attendee word — never
# "sound healing", which splits intent on a transactional surface).
CITY_H2 = {
    'Denver': 'Sound baths in Denver this week',
    'Boulder': 'Sound baths in Boulder this week',
    'Fort Collins': 'Sound baths in Fort Collins this week',
    'Colorado Springs': 'Sound baths in Colorado Springs this week',
}

# Nearby suburbs fold into the nearest canonical section (spec mapping). Only
# used when a row's city is not already canonical, or to place a Firstwater
# session from its free-text venue address.
_SUBURB_TO_CITY = {
    'lakewood': 'Denver', 'arvada': 'Denver', 'aurora': 'Denver',
    'centennial': 'Denver', 'englewood': 'Denver', 'littleton': 'Denver',
    'wheat ridge': 'Denver', 'golden': 'Denver', 'thornton': 'Denver',
    'westminster': 'Denver', 'commerce city': 'Denver', 'broomfield': 'Denver',
    'highlands ranch': 'Denver', 'parker': 'Denver', 'castle rock': 'Denver',
    'lone tree': 'Denver', 'brighton': 'Denver', 'northglenn': 'Denver',
    'longmont': 'Boulder', 'louisville': 'Boulder', 'lafayette': 'Boulder',
    'superior': 'Boulder', 'nederland': 'Boulder', 'erie': 'Boulder',
    'loveland': 'Fort Collins', 'windsor': 'Fort Collins',
    'greeley': 'Fort Collins', 'wellington': 'Fort Collins',
    'berthoud': 'Fort Collins', 'timnath': 'Fort Collins',
    'manitou springs': 'Colorado Springs', 'monument': 'Colorado Springs',
    'fountain': 'Colorado Springs', 'woodland park': 'Colorado Springs',
}

# Statuses that render. Anything else (candidate/rejected/unknown) is dropped.
RENDER_STATUS = 'approved'


# ---------------------------------------------------------------------------
# Normalization / dedup key (contract algorithm — also used by the pull agent
# and the seed generator, kept here as the single source of truth)
# ---------------------------------------------------------------------------

def normalize(s):
    """lowercase, strip accents/diacritics, drop non-alphanumeric-non-space
    chars, collapse whitespace to single spaces, trim.

    Whitespace is collapsed to a single space BEFORE the non-alnum strip so that
    a scrape artifact — a tab/newline/exotic-space wedged between two words —
    becomes a separator, not a glue: "Full Moon\nSound" -> "full moon sound",
    never "full moonsound". This keeps the dedup_key byte-identical to the
    authoritative service impl (TS `[^a-z0-9\\s]`), which is the whole point of
    the shared key. (Python `\\s` matches the whitespace a real listing produces;
    a zero-width U+FEFF between words is the one theoretical residual and does not
    occur in listing data.)"""
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'[^a-z0-9 ]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def make_dedup_key(name, date_yyyy_mm_dd, venue):
    """normalize(name) + '|' + YYYY-MM-DD (America/Denver) + '|' + normalize(venue)."""
    return f'{normalize(name)}|{date_yyyy_mm_dd}|{normalize(venue)}'


def map_city(text):
    """Fold a free-text city/address to one canonical section key.

    Exact canonical match wins; then a known-suburb substring; else Denver
    (the metro that anchors the calendar). Only used for non-canonical input.
    """
    if not text:
        return 'Denver'
    t = text.strip().lower()
    for c in CITIES:
        if c.lower() in t:
            return c
    for suburb, city in _SUBURB_TO_CITY.items():
        if suburb in t:
            return city
    return 'Denver'


# ---------------------------------------------------------------------------
# Loading (mirrors sessions_feed.load_feed precedence + graceful fallback)
# ---------------------------------------------------------------------------

def empty_feed():
    return {'generated_at': None, 'events': []}


def validate_feed(feed):
    """Shape-check a parsed feed. Raises ValueError on any problem.

    Load-bearing fields only: each event needs a non-empty string name, a
    parseable offset-aware starts_at, a string status, and a string city.
    Everything else has a safe render-time default.
    """
    if not isinstance(feed, dict):
        raise ValueError('feed root is not an object')
    if not isinstance(feed.get('events'), list):
        raise ValueError('feed.events is not a list')
    for i, e in enumerate(feed['events']):
        where = f'events[{i}]'
        if not isinstance(e, dict):
            raise ValueError(f'{where} is not an object')
        for key in ('name', 'starts_at', 'status', 'city'):
            if not isinstance(e.get(key), str) or not e[key]:
                raise ValueError(f'{where}.{key} missing or not a string')
        parse_iso(e['starts_at'])
    return feed


def _write_cache(cache_path, feed):
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, 'w', encoding='utf-8') as f:
        f.write(json.dumps(feed, indent=2, sort_keys=True, ensure_ascii=False) + '\n')


def _load_cache(cache_path, log):
    try:
        with open(cache_path, 'r', encoding='utf-8') as f:
            return validate_feed(json.load(f))
    except Exception as exc:  # missing or corrupt cache: build must still succeed
        log(f'  ⚠ external-events cache unusable ({exc.__class__.__name__}: {exc}) — building with no external events')
        return empty_feed()


def load_feed(repo_root, log=print):
    """Return the external-events feed dict, never raising.

    Order of precedence:
      CALENDAR_FEED_FILE (local fixture, committed file untouched)
      > CALENDAR_FEED_URL fetch (http(s) success refreshes the committed file)
      > committed data/external-events.json
      > empty feed.
    """
    cache_path = os.path.join(repo_root, CACHE_REL_PATH)

    fixture = os.environ.get('CALENDAR_FEED_FILE')
    if fixture:
        try:
            with open(fixture, 'r', encoding='utf-8') as f:
                feed = validate_feed(json.load(f))
            log(f'  ✓ calendar feed from fixture {fixture} ({len(feed["events"])} event(s); committed file untouched)')
            return feed
        except Exception as exc:
            log(f'  ⚠ CALENDAR_FEED_FILE unusable ({exc.__class__.__name__}: {exc}) — using committed data/external-events.json')
            return _load_cache(cache_path, log)

    url = os.environ.get('CALENDAR_FEED_URL', DEFAULT_FEED_URL)
    try:
        with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT_S) as resp:
            feed = validate_feed(json.loads(resp.read().decode('utf-8')))
    except Exception as exc:
        log(f'  ⚠ calendar feed unavailable at {url} ({exc.__class__.__name__}) — using committed data/external-events.json')
        return _load_cache(cache_path, log)

    if url.startswith(('http://', 'https://')):
        _write_cache(cache_path, feed)
        log(f'  ✓ calendar feed fetched ({len(feed["events"])} event(s)) — committed file refreshed')
    else:
        log(f'  ✓ calendar feed from {url} ({len(feed["events"])} event(s); committed file untouched)')
    return feed


# ---------------------------------------------------------------------------
# Time helpers (America/Denver) — thin wrappers over sessions_feed idioms so
# both feeds format dates identically.
# ---------------------------------------------------------------------------

def _denver(ts):
    return sessions_feed._denver(ts)


def _day(n):
    return sessions_feed._day(n)


def fmt_row_date(ts):
    """Compact dated-row label: 'Fri, Jul 24'."""
    d = _denver(ts)
    return f'{d.strftime("%a")}, {d.strftime("%b")} {_day(d.strftime("%d"))}'


def fmt_row_dow(ts):
    """Weekday abbreviation for the tear-off date rail: 'Sat'."""
    return _denver(ts).strftime('%a')


def fmt_row_daynum(ts):
    """Day-of-month numeral for the date rail: '25' (no leading zero)."""
    return _day(_denver(ts).strftime('%d'))


def fmt_time(ts):
    return sessions_feed.fmt_time(ts)


def fmt_stamp_date(now):
    """'Last updated' stamp date in America/Denver: 'July 19, 2026'."""
    d = now.astimezone(DENVER)
    return f'{d.strftime("%B")} {_day(d.strftime("%d"))}, {d.year}'


def stamp_date_iso(now):
    """The same stamp date as an ISO date (America/Denver): '2026-07-19'.
    Used for schema.org dateModified so it matches the visible stamp."""
    return now.astimezone(DENVER).date().isoformat()


def _now_utc(now):
    return now or datetime.now(timezone.utc)


def current_now():
    """Shared build-time 'now' (UTC-aware) so the weekend window, past-event
    drop, and 'Last updated' stamp all agree within one build."""
    return datetime.now(timezone.utc)


def weekend_window(now=None):
    """(start, end) datetimes bounding the relevant weekend in America/Denver.

    Mon–Thu -> the upcoming Fri 00:00 through Sun 23:59.
    Fri/Sat/Sun -> the weekend in progress (its own Fri 00:00 through Sun 23:59).
    """
    local = _now_utc(now).astimezone(DENVER)
    # weekday(): Mon=0 .. Fri=4, Sat=5, Sun=6. days_to_fri is 0 or negative on
    # Fri/Sat/Sun (this weekend's Friday), positive Mon–Thu (upcoming Friday).
    days_to_fri = 4 - local.weekday()
    fri = (local + timedelta(days=days_to_fri)).date()
    sun = fri + timedelta(days=2)
    start = datetime(fri.year, fri.month, fri.day, 0, 0, 0, tzinfo=DENVER)
    end = datetime(sun.year, sun.month, sun.day, 23, 59, 59, tzinfo=DENVER)
    return start, end


# ---------------------------------------------------------------------------
# Row model — one normalized dict per rendered event, external or Firstwater.
# ---------------------------------------------------------------------------

def _external_row(e):
    city = e.get('city') if e.get('city') in CITIES else map_city(e.get('city') or e.get('address') or '')
    return {
        'kind': 'external',
        'name': e.get('name', ''),
        'operator': e.get('operator', ''),
        'starts_at': e['starts_at'],
        'city': city,
        'venue': e.get('venue', ''),
        'neighborhood': e.get('neighborhood') or None,
        'address': e.get('address', ''),
        'price': e.get('price', ''),
        'note': e.get('note', '') or '',
        'ticket_url': e.get('ticket_url', '') or e.get('source_url', ''),
        'source_url': e.get('source_url', ''),
        'tags': e.get('tags', []) or [],
        'dedup_key': e.get('dedup_key', ''),
        # v2 fields — the three URLs are scheme-scrubbed exactly like ticket_url
        # (attacker-influenced third-party listing data on a public page).
        'image_url': _safe_ext_url(e.get('image_url', '')),
        'facilitator': (e.get('facilitator', '') or '').strip(),
        'operator_url': _safe_ext_url(e.get('operator_url', '')),
        'venue_url': _safe_ext_url(e.get('venue_url', '')),
        'description': (e.get('description', '') or '').strip(),
        # CAL-02: {slug, name} of the linked PUBLISHED practitioner, or None. The
        # feed only ever carries a published practitioner here (drafts stay in
        # the service), so a slug present means /practitioner/<slug>/ exists.
        'practitioner': (e.get('practitioner')
                         if isinstance(e.get('practitioner'), dict) else None),
        # CAL-03: {slug, name} of the linked PUBLISHED venue, or None.
        'venue_ref': (e.get('venue_ref')
                      if isinstance(e.get('venue_ref'), dict) else None),
        # CAL-08: {slug, name} of the linked PUBLISHED operator (org/host), or None.
        'operator_ref': (e.get('operator_ref')
                         if isinstance(e.get('operator_ref'), dict) else None),
        '_ext': e,
        '_sess': None,
        '_event_title': None,
    }


# Nicer display names for the known Firstwater session slugs; any other slug
# falls back to a title-cased form of the slug itself.
_SESSION_TITLES = {
    'healing-from-breakups': 'Healing from Breakups',
    'sunday-downshift': 'Sunday Downshift',
    'grief': 'Grief',
    'new-to-denver': 'New to Denver',
    'couples': 'Couples Reconnection',
    'quiet-new-years': "Quiet New Year's",
    'laid-off': 'Laid Off',
    'singles': 'Singles',
    'sleep': 'Sleep Descent',
}


def _session_title(slug):
    return _SESSION_TITLES.get(slug) or slug.replace('-', ' ').title()


def _session_price(s):
    """Cheapest-tier price string for a Firstwater row, or ''."""
    tiers = s.get('tiers') or []
    cents = None
    for t in tiers:
        if t.get('mode') == 'sliding':
            amt = t.get('min_amount') or t.get('suggested_amount') or t.get('amount')
            prefix = 'from '
        else:
            amt = t.get('amount')
            prefix = 'from ' if len(tiers) > 1 else ''
        if amt is None:
            continue
        if cents is None or amt < cents:
            cents = amt
            best_prefix = prefix
    if cents is None:
        return ''
    money = sessions_feed.fmt_money(cents)
    return f'{best_prefix}{money}' if money else ''


def _firstwater_row(s):
    slug = s.get('event_slug', '')
    venue = (s.get('venue') or {}).get('name', '') or ''
    address = (s.get('venue') or {}).get('address', '') or ''
    title = _session_title(slug)
    return {
        'kind': 'firstwater',
        'name': title,
        'operator': 'Firstwater',
        'starts_at': s['starts_at'],
        'city': map_city(address or venue),
        'venue': venue,
        'neighborhood': None,
        'address': address,
        'price': _session_price(s),
        'note': '',
        # [port] absolute: the session page lives on the artist site now
        'ticket_url': f'{FIRSTWATER_URL}/sessions/{slug}/',
        'source_url': '',
        'tags': [],
        'dedup_key': f'firstwater|{slug}|{_denver(s["starts_at"]).strftime("%Y-%m-%d")}',
        # v2 fields — Firstwater rows carry no listing image (their distinction is
        # treatment, not a flyer) and link to their own rich session page; the
        # factual line still renders from the template. facilitator/urls stay
        # empty here (the session page is authoritative for its own detail).
        'image_url': '',
        'facilitator': '',
        'operator_url': '',
        'venue_url': '',
        'description': '',
        '_ext': None,
        '_sess': s,
        '_event_title': title,
    }


def build_rows(cal_feed, sessions_feed_data, now=None):
    """Normalized, future, de-duplicated rows for the calendar.

    External: status='approved' AND starts in the future.
    Firstwater: sessions_feed DISPLAY_STATUSES AND future.
    Rejected/candidate external events and past events never appear.
    """
    now = _now_utc(now)
    rows = []

    for e in (cal_feed or {}).get('events', []):
        if e.get('status') != RENDER_STATUS:
            continue
        try:
            if parse_iso(e['starts_at']) <= now:
                continue
        except (KeyError, ValueError):
            continue
        rows.append(_external_row(e))

    for s in (sessions_feed_data or {}).get('sessions', []):
        if s.get('status') not in sessions_feed.DISPLAY_STATUSES:
            continue
        try:
            if parse_iso(s['starts_at']) <= now:
                continue
        except (KeyError, ValueError):
            continue
        rows.append(_firstwater_row(s))

    # Defensive de-dup within the external feed (server already dedups; this
    # guards a hand-edited feed): first occurrence by dedup_key, then by
    # ticket_url, wins.
    #
    # Cross-feed guard: external and Firstwater rows use structurally disjoint
    # dedup_keys (content-based vs 'firstwater|slug|date') and disjoint
    # ticket_urls (Eventbrite vs internal session path), so the two guards above
    # never catch the SAME real event surfacing in both feeds — e.g. a Firstwater
    # session an operator also cross-posts to Eventbrite. Firstwater is
    # authoritative for its own sessions, so drop any external row whose canonical
    # normalize(name)+date+normalize(venue) matches a Firstwater row. Best-effort:
    # a scraped listing whose title/venue text differs from the session's curated
    # title/venue won't match — source-level exclusion in the pull agent is the
    # primary guard; this only catches the clean, identical cross-post.
    def _content_key(r):
        day = _denver(r['starts_at']).strftime('%Y-%m-%d')
        return make_dedup_key(r['name'], day, r['venue'])

    firstwater_content = {
        _content_key(r) for r in rows if r['kind'] == 'firstwater'
    }

    seen_keys, seen_urls, deduped = set(), set(), []
    for r in rows:
        k = r.get('dedup_key') or ''
        u = r.get('ticket_url') or ''
        if k and k in seen_keys:
            continue
        if u and r['kind'] == 'external' and u in seen_urls:
            continue
        if r['kind'] == 'external' and _content_key(r) in firstwater_content:
            continue
        if k:
            seen_keys.add(k)
        if u and r['kind'] == 'external':
            seen_urls.add(u)
        deduped.append(r)

    deduped.sort(key=lambda r: parse_iso(r['starts_at']))
    return deduped


def group_by_city(rows):
    """OrderedDict city -> rows (chronological), fixed CITIES order, all keys present."""
    groups = OrderedDict((c, []) for c in CITIES)
    for r in rows:
        groups.get(r['city'], groups['Denver']).append(r)
    for c in groups:
        groups[c].sort(key=lambda r: parse_iso(r['starts_at']))
    return groups


def weekend_rows(rows, now=None):
    """Rows whose start falls inside the relevant weekend window, chronological."""
    start, end = weekend_window(now)
    out = [r for r in rows if start <= parse_iso(r['starts_at']).astimezone(DENVER) <= end]
    out.sort(key=lambda r: parse_iso(r['starts_at']))
    return out


def week_rows(rows, now=None):
    """Rows starting within the next seven days — the 'this week' answer window
    used by the machine-extractable summary sentence."""
    now = _now_utc(now)
    end = now + timedelta(days=7)
    out = [r for r in rows if now < parse_iso(r['starts_at']) <= end]
    out.sort(key=lambda r: parse_iso(r['starts_at']))
    return out


# ---------------------------------------------------------------------------
# Factual description (field-or-template), editorial note, alt text, slugs.
# The template is the deterministic FALLBACK used when a row carries no authored
# `description`: a clean, factual sentence built from the structured fields so
# every row and permalink renders non-thin. It never evaluates the event (no
# praise, no woo) — that is `note`'s job, and `note` is Daniel's verbatim alone.
# ---------------------------------------------------------------------------

# Tag -> lead noun phrase, most specific first. Theme modifiers (e.g.
# "moon-themed") are intentionally skipped: the lead states the FORMAT.
_LEAD_PHRASES = (
    ('gong', 'A gong bath'),
    ('breathwork+sound', 'A breathwork and sound session'),
    ('guided-meditation', 'A guided meditation with sound'),
    ('meditation+sound', 'A guided meditation with sound'),
    ('sound-forward yoga', 'A sound-forward yoga session'),
    ('yoga+sound', 'A sound-forward yoga session'),
    ('singing-bowl', 'A singing-bowl session'),
    ('sound healing', 'A sound healing session'),
    ('sound bath', 'A sound bath'),
)


def _lead_phrase(tags):
    tset = {str(t).lower() for t in (tags or [])}
    for tag, phrase in _LEAD_PHRASES:
        if tag in tset:
            return phrase
    return 'A sound session'


def _price_phrase(price):
    """A factual price sentence, or '' when the price is unknown. Mirrors the
    JSON-LD price reading (accurate or absent) so the sentence never guesses."""
    kind = _parse_price(price)
    if kind[0] == 'free':
        return 'Free to attend.'
    if kind[0] == 'fixed':
        return f'Tickets are ${_fmt_price_num(kind[1])}.'
    if kind[0] == 'range':
        return f'Tickets ${_fmt_price_num(kind[1])}–${_fmt_price_num(kind[2])}.'
    if price and _DONATION_RE.search(price):
        return 'Offered by donation.'
    return ''


def template_description(row):
    """Deterministic factual sentence for a row from its structured fields.

    Shape: "{lead}{ led by F}{ at V}{ in P}, {Weekday} at {time}. {price}."
    Clean and natural, never robotic, never editorial. Always non-empty (the
    lead and day/time always resolve), so it is a safe fallback for an empty
    authored `description`.
    """
    clause = [_lead_phrase(row.get('tags'))]
    facilitator = (row.get('facilitator') or '').strip()
    if facilitator:
        clause.append(f'led by {facilitator}')
    venue = (row.get('venue') or '').strip()
    if venue:
        clause.append(f'at {venue}')
    place = row.get('neighborhood') if row.get('city') == 'Denver' else row.get('city')
    if place and normalize(place) not in normalize(venue):
        clause.append(f'in {place}')
    d = _denver(row['starts_at'])
    when = f'{d.strftime("%A")} at {fmt_time(row["starts_at"])}'
    sentence = f'{" ".join(clause)}, {when}.'
    price = _price_phrase(row.get('price', ''))
    return f'{sentence} {price}' if price else sentence


def factual_description(row):
    """The factual line: the authored `description` when present, else the
    deterministic template. Always non-empty."""
    return (row.get('description') or '').strip() or template_description(row)


def editorial_note(row):
    """Daniel's verbatim one-liner, or '' — never synthesized. External rows
    only (a Firstwater row speaks on its own session page)."""
    if row.get('kind') == 'external':
        return (row.get('note') or '').strip()
    return ''


def alt_text(row):
    """Factual ALT/caption text: '{name} — {operator} at {venue}, {place}'.
    Degrades cleanly when operator/venue/place are missing (functional locator
    string, not body copy; the em dash follows the spec's mandated shape)."""
    name = (row.get('name') or '').strip()
    op = (row.get('operator') or '').strip()
    venue = (row.get('venue') or '').strip()
    place = row.get('neighborhood') if row.get('city') == 'Denver' else row.get('city')
    place = (place or row.get('city') or '').strip()
    loc = op
    # An operator running its own room (operator == venue) shows the name once.
    if venue and normalize(venue) != normalize(op):
        loc = f'{loc} at {venue}' if loc else venue
    if place:
        loc = f'{loc}, {place}' if loc else place
    return f'{name} — {loc}' if loc else name


# dedup_key is already normalized (lowercase alnum + spaces + '|'); collapse
# every run of non-alnum to one hyphen for a stable, URL-safe permalink slug.
_SLUG_STRIP_RE = re.compile(r'[^a-z0-9]+')


def event_slug(row):
    """Stable URL-safe slug from the dedup_key. Deterministic across builds."""
    return _SLUG_STRIP_RE.sub('-', (row.get('dedup_key') or '').lower()).strip('-')


def event_permalink_path(row):
    """Site-relative permalink path for an external event page (trailing slash).
    [port] The calendar is the site root here, so permalinks sit at /event/."""
    return f'event/{event_slug(row)}/'


def event_permalink_url(row, site_url):
    return f'{site_url}/{event_permalink_path(row)}'


def _price_span(rows):
    """(low_label, high_num) across rows' readable prices, or ('', None).
    Free counts as 0; unreadable/donation prices are skipped."""
    lo = hi = None
    for r in rows:
        kind = _parse_price(r.get('price', ''))
        nums = []
        if kind[0] == 'free':
            nums = [0.0]
        elif kind[0] == 'fixed':
            nums = [kind[1]]
        elif kind[0] == 'range':
            nums = [kind[1], kind[2]]
        for n in nums:
            lo = n if lo is None else min(lo, n)
            hi = n if hi is None else max(hi, n)
    if hi is None:
        return ('', None)
    lo_label = 'free' if lo == 0 else f'${_fmt_price_num(lo)}'
    return (lo_label, hi)


def build_summary_sentence(rows, now=None):
    """Machine-extractable answer-first sentence for the top of /calendar/.

    Counts sessions starting in the next seven days, per city, with a price
    span. Rebuilt every build so it always matches the live list.
    """
    wk = week_rows(rows, now)
    n = len(wk)
    if n == 0:
        # [port] "sound baths", the attendee query word (pivot-memo P0 fix b).
        return ('No sound baths are on the Front Range calendar for the next '
                'seven days yet; the weeks ahead are listed below.')
    counts = OrderedDict((c, 0) for c in CITIES)
    for r in wk:
        counts[r['city']] = counts.get(r['city'], 0) + 1
    parts = [f'{cnt} in {c}' for c, cnt in counts.items() if cnt]
    if len(parts) > 1:
        breakdown = ', '.join(parts[:-1]) + ', and ' + parts[-1]
    else:
        breakdown = parts[0]
    # [port] "sound baths" not "sound sessions" (pivot-memo P0 fix b).
    noun = 'bath' if n == 1 else 'baths'
    sent = f'This week on the Front Range: {n} sound {noun}, {breakdown}'
    lo_label, hi = _price_span(wk)
    if hi is not None:
        sent += f', priced {lo_label} to ${_fmt_price_num(hi)}'
    return sent + '.'


# Register-passable PLACEHOLDER FAQ (flagged for Daniel). Factual, no praise,
# no woo — the GEO/AIO citation surface. Answers double as FAQPage JSON-LD.
CALENDAR_FAQ = (
    {
        'q': 'What is a sound bath?',
        'a': ('A sound bath is a session where you lie down, usually on a mat, '
              'while a facilitator plays instruments such as gongs, singing '
              'bowls, and chimes. Most run 45 to 75 minutes, and you stay '
              'clothed and still the whole time. This calendar also covers close '
              'relatives like gong baths, breathwork with sound, and guided '
              'meditations played on live instruments.'),
    },
    {
        'q': 'How much do sound baths cost on the Front Range?',
        'a': ('Most sessions in Denver, Boulder, Fort Collins, and Colorado '
              'Springs run between $20 and $55. Some are offered by donation or '
              'free. Each listing shows its own price, and the ticket link goes '
              'straight to the operator.'),
    },
    {
        'q': 'What should I bring to a sound bath?',
        'a': ('Wear clothes you can lie down in. Many rooms provide mats, '
              'bolsters, and blankets, though your own blanket, a pillow, and '
              'water are never wrong. When in doubt, the operator’s listing '
              'says what the room supplies.'),
    },
)


def _render_faq(items):
    """Always-visible FAQ block (better for AI extraction than a collapsed
    accordion). The FAQPage JSON-LD is built from the same items."""
    out = ['<section class="cal-faq" id="faq">',
           '  <h2 class="cal-band__h2">Common questions</h2>']
    for item in items:
        out.append('  <div class="cal-faq__item">')
        out.append(f'    <h3 class="cal-faq__q">{_esc(item["q"])}</h3>')
        out.append(f'    <p class="cal-faq__a">{_esc(item["a"])}</p>')
        out.append('  </div>')
    out.append('</section>')
    return '\n'.join(out)


def render_faq_html():
    return _render_faq(CALENDAR_FAQ)


# ---------------------------------------------------------------------------
# HTML rendering (light ground; reuses design tokens via calendar/style.css)
# ---------------------------------------------------------------------------

def _esc(v):
    return html.escape(str(v), quote=True)


# External ticket/source URLs come from third-party listings a pull scraped, so
# they are attacker-influenced. They are rendered as hrefs on this PUBLIC page and
# emitted into the Event JSON-LD — allow only http(s) so a javascript:/data:
# scheme can neither execute in a visitor's browser nor poison structured data.
# Browsers ignore ASCII control chars inside a scheme ("java\tscript:"), so those
# are stripped from the probe before the check. Unsafe -> '' (no link, no url).
_SAFE_URL_PROBE_RE = re.compile(r'[\x00-\x20]')


def _safe_ext_url(v):
    # Scheme guard ONLY — never a URL normalizer. Return the input verbatim
    # (stripped) for http(s); do NOT re-parse/re-serialize (e.g. urlsplit ->
    # urlunsplit dropping the query, or origin+path). Signed image CDN URLs
    # (img.evbuc.com / imgix) 403 without their `?...&s=<signature>` query, so
    # dropping the query silently breaks the image. Mirrors safeHttpUrl in
    # service/src/lib/externalEvents.ts (2026-07-19 regression).
    if not v:
        return ''
    s = str(v).strip()
    probe = _SAFE_URL_PROBE_RE.sub('', s).lower()
    return s if probe.startswith(('http://', 'https://')) else ''


# Register-passable PLACEHOLDER empty-state lines. Flagged for Daniel.
# Per-city (reserved for the Track B city pages, B.2):
EMPTY_STATE = 'No rooms on the calendar in {city} this week.'
# Whole calendar (feed entirely dry — rare; the committed cache holds weeks):
ALL_EMPTY = 'No sound baths on the Front Range calendar right now. Check back soon.'


def _city_tag(row):
    """The per-row geography chip. Now that time is the axis (Track B), every
    root row is city-tagged; Denver rows append a known neighborhood."""
    if row['city'] == 'Denver' and row.get('neighborhood'):
        return f'Denver · {row["neighborhood"]}'
    return row['city']


def _is_free_or_donation(row):
    """True when a row is free OR donation/sliding/pay-what — drives the B.5
    free/donation filter chip (data-free on each row). Uses the same price
    reading as the schema so the chip and the JSON-LD never disagree."""
    price = row.get('price', '') or ''
    if _parse_price(price)[0] == 'free':
        return True
    return bool(_DONATION_RE.search(price))


def _facil_venue_link(row):
    """The 'their own page' link beside the ticket link: the operator's own site
    when known, else the venue's. URLs are already scheme-scrubbed at row build.
    Returns (url, label) or (None, None)."""
    if row.get('operator_url'):
        return row['operator_url'], (row.get('operator') or 'Operator')
    if row.get('venue_url'):
        return row['venue_url'], (row.get('venue') or 'Venue')
    return None, None


# ---------------------------------------------------------------------------
# Tags (CAL-01) — the controlled-vocabulary chips + filter facet. Feed rows may
# still carry legacy free-form tags; taxonomy.normalize_tags folds them to
# canonical slugs (and an already-canonical slug maps to itself), so the site
# renders one clean vocabulary regardless of what a given row was tagged with.
# ---------------------------------------------------------------------------

def row_tag_slugs(row):
    """Canonical tag slugs for a row, order-preserved and de-duplicated."""
    return taxonomy.normalize_tags(row.get('tags'))


# CAL-09: slugs that have a live tag landing page → {slug: site-relative path}.
# Set once per build (build.py, before any chip renders) so a chip links to
# /<slug>/ when that page exists and stays an inert <span> otherwise. Empty by
# default, so any caller that doesn't set it renders plain chips (no regression).
_LINKED_TAG_PAGES = {}


def set_linked_tag_pages(mapping):
    """Register the tag→page-path map used to turn chips into links (CAL-09)."""
    global _LINKED_TAG_PAGES
    _LINKED_TAG_PAGES = dict(mapping or {})


def row_primary_modality(row):
    """The row's primary modality slug (first in vocabulary order), or None.
    Surfaced as the row's kicker mark (CAL-12) so 'what kind of sound bath' is
    scannable at the top of the row without reading down to the chips."""
    for s in row_tag_slugs(row):
        if taxonomy.AXIS_BY_SLUG.get(s) == 'modality':
            return s
    return None


def render_tag_chips(row, cls='cal-tags', nav_prefix='', skip=None):
    """Tag chips for a row/page, or '' when the row carries no known tags. A tag
    with a live landing page (CAL-09) renders as a link; the rest stay inert
    <span>s. nav_prefix resolves the link from the caller's depth. `skip` drops
    slugs already shown elsewhere (CAL-12: the modality kicker), so the row's
    chip set doesn't repeat the kicker."""
    slugs = row_tag_slugs(row)
    if skip:
        slugs = [s for s in slugs if s not in skip]
    if not slugs:
        return ''
    parts = []
    for s in slugs:
        label = _esc(taxonomy.label_for(s))
        path = _LINKED_TAG_PAGES.get(s)
        if path:
            parts.append(
                f'<a class="cal-tag cal-tag--link" '
                f'href="{_esc(nav_prefix + path)}">{label}</a>')
        else:
            parts.append(f'<span class="cal-tag">{label}</span>')
    return f'<p class="{cls}">{"".join(parts)}</p>'


def render_empty_state(nav_prefix, lead):
    """A first-class empty state (CAL-13) for an entity index with no published
    instances: a quiet mark, one honest line of what the section will hold, two
    redirects (calendar + map), and a get-listed seed — never a bare
    '…on the way.' line floating above the footer."""
    return (
        '    <div class="cal-emptystate">\n'
        '      <p class="cal-emptystate__glyph" aria-hidden="true">∿</p>\n'
        f'      <p class="cal-emptystate__lead">{_esc(lead)}</p>\n'
        f'      <p class="cal-emptystate__links">'
        f'<a href="{nav_prefix}">Browse this week’s calendar</a> '
        f'<span aria-hidden="true">·</span> '
        f'<a href="{nav_prefix}map/">See the map</a></p>\n'
        '      <p class="cal-emptystate__seed">Run a room or lead sessions? '
        '<a href="mailto:hello@soundbathcalendar.com?subject='
        'A%20listing%20for%20the%20calendar">Get listed</a>.</p>\n'
        '    </div>')


def present_tag_slugs(rows):
    """The canonical slugs actually present across rows, in vocabulary order —
    so the filter facet only ever offers a tag that will match something."""
    present = set()
    for r in rows:
        present.update(row_tag_slugs(r))
    return [slug for slug, _label, _axis in taxonomy.TAGS if slug in present]


def add_to_calendar_urls(row, site_url, now=None):
    """Prefilled one-click 'add to calendar' launch URLs for one event.
    Reuses event_ics_input (same title/window/location/description the .ics
    carries) so Google/Outlook/Apple all agree. Apple = the local event.ics."""
    ev = event_ics_input(row, site_url, now)
    start_utc = ics_lib.ics_utc(ev['start'])            # 20260724T190000Z
    end_utc = ics_lib.ics_utc(ev['end'])
    iso_start = ev['start'].astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    iso_end = ev['end'].astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    google = 'https://calendar.google.com/calendar/render?' + urlencode({
        'action': 'TEMPLATE',
        'text': ev['title'],
        'dates': f'{start_utc}/{end_utc}',
        'details': ev['description'],
        'location': ev['location'],
    })
    outlook = 'https://outlook.live.com/calendar/0/deeplink/compose?' + urlencode({
        'path': '/calendar/action/compose',
        'rru': 'addevent',
        'subject': ev['title'],
        'startdt': iso_start,
        'enddt': iso_end,
        'location': ev['location'],
        'body': ev['description'],
    })
    return {'google': google, 'outlook': outlook, 'apple': 'event.ics'}


def _render_row(row, show_date=True, nav_prefix='', geocode=None):
    is_fw = row['kind'] == 'firstwater'
    cls = 'cal-row cal-row--firstwater' if is_fw else 'cal-row'
    # Filter hooks: area + free/donation (B.5) + tags (CAL-01), read by
    # filters.js. data-tags is a space-joined slug list (empty when untagged).
    _slugs = row_tag_slugs(row)
    data = (f' data-city="{_esc(city_slug(row["city"]))}"'
            f' data-free="{"1" if _is_free_or_donation(row) else "0"}"'
            f' data-tags="{_esc(" ".join(_slugs))}"')
    # CAL-05 near-me sort: venue coordinates from the committed geocode cache
    # (same source as the map). A row whose venue isn't located carries no
    # coords — filters.js sorts it last and gives it no distance chip.
    coord = (geocode or {}).get((row.get('venue') or '').strip())
    if coord:
        data += f' data-lat="{coord["lat"]}" data-lng="{coord["lng"]}"'
    parts = [f'<article class="{cls}"{data}>']
    # Tear-off date rail: weekday over numeral over time. The Today/Tonight band
    # omits the date (its heading already says "today"); every other band spans
    # multiple days, so its rows carry day + numeral.
    parts.append('  <div class="cal-row__when">')
    if show_date:
        parts.append(f'    <span class="cal-row__dow">{_esc(fmt_row_dow(row["starts_at"]))}</span>')
        parts.append(f'    <span class="cal-row__dnum">{_esc(fmt_row_daynum(row["starts_at"]))}</span>')
    parts.append(f'    <span class="cal-row__time">{_esc(fmt_time(row["starts_at"]))}</span>')
    parts.append('  </div>')
    parts.append('  <div class="cal-row__body">')

    # Event image — one consistent frame (fixed ratio, object-fit cover, lazy)
    # so heterogeneous operator flyers sit coherently. The frame is Firstwater's,
    # the content is the operator's (RA-style). CAL-12: the media column is now
    # RESERVED for every external row — an image-less row draws a quiet
    # placeholder tile instead of collapsing, so every text column shares one
    # left edge (mirrors digest.ts `showThumb`). FW rows keep their border+tint
    # identity and carry no media tile.
    img = row.get('image_url')
    if not is_fw:
        if img:
            parts.append('    <div class="cal-row__media">')
            parts.append(
                f'      <img src="{_esc(img)}" alt="{_esc(alt_text(row))}" '
                f'loading="lazy" decoding="async">'
            )
            parts.append('    </div>')
        else:
            parts.append('    <div class="cal-row__media cal-row__media--empty"'
                         ' aria-hidden="true"></div>')

    parts.append('    <div class="cal-row__text">')

    # Marks line: the city chip (every row) + the primary modality kicker (CAL-12,
    # 'what kind of sound bath' at a glance, linked to its tag page when one
    # exists) + Firstwater's own-room marker on its own rows.
    mod = None if is_fw else row_primary_modality(row)
    parts.append('      <div class="cal-row__marks">')
    parts.append(f'        <span class="cal-row__city">{_esc(_city_tag(row))}</span>')
    if mod:
        _mlabel = _esc(taxonomy.label_for(mod))
        _mpath = _LINKED_TAG_PAGES.get(mod)
        if _mpath:
            parts.append(f'        <a class="cal-row__modality" '
                         f'href="{_esc(nav_prefix + _mpath)}">{_mlabel}</a>')
        else:
            parts.append(f'        <span class="cal-row__modality">{_mlabel}</span>')
    if is_fw:
        parts.append('        <span class="cal-row__tag">Firstwater</span>')
        parts.append('        <span class="cal-row__ours">Our room</span>')
    parts.append('      </div>')

    # Name links to the event's page: external -> its calendar permalink (our
    # rich, indexable surface + the internal link that puts it in the crawl
    # graph); Firstwater -> its session page on thefirstwater.co ([port]:
    # absolute URL, so no nav_prefix and it opens like any other operator link).
    slug = event_slug(row)
    if is_fw:
        name_href = row['ticket_url']
    else:
        name_href = f'{nav_prefix}{event_permalink_path(row)}' if slug else ''
    if name_href:
        _new_tab = ' target="_blank" rel="noopener"' if is_fw else ''
        parts.append(
            f'      <h3 class="cal-row__name">'
            f'<a href="{_esc(name_href)}"{_new_tab}>{_esc(row["name"])}</a></h3>'
        )
    else:
        parts.append(f'      <h3 class="cal-row__name">{_esc(row["name"])}</h3>')

    # Facts line: operator · venue · price. Geography rides the city chip above;
    # the factual sentence now lives only on the permalink page (B.3: these are
    # calendar rows, not article cards). An operator running its own room
    # (operator == venue) shows the name once, not doubled.
    meta = []
    if not is_fw and row['operator']:
        meta.append(row['operator'])
    if row['venue'] and normalize(row['venue']) != normalize(row['operator'] if not is_fw else ''):
        meta.append(row['venue'])
    if row['price']:
        meta.append(row['price'])
    if meta:
        parts.append(f'      <p class="cal-row__meta">{_esc(" · ".join(meta))}</p>')

    # Practitioner link (CAL-02) — external rows linked to a published profile.
    # Inlined path (no import of practitioners.py) to avoid a cycle.
    pr = row.get('practitioner') or {}
    if not is_fw and isinstance(pr, dict) and pr.get('slug'):
        parts.append(
            f'      <p class="cal-row__with">with <a href="'
            f'{nav_prefix}practitioner/{_esc(pr["slug"])}/">{_esc(pr.get("name") or "")}</a></p>')

    # Daniel's one-line editorial note — the moat — set as a margin voice.
    # External rows only, and only when he has written one; a bare row is the
    # honest default.
    note = editorial_note(row)
    if note:
        parts.append(f'      <p class="cal-row__note">{_esc(note)}</p>')

    # Tag chips (CAL-01) — external rows only; the canonical vocabulary, or
    # nothing when the row carries no known tag (a bare row is the honest default).
    if not is_fw:
        # Skip the modality already shown as the kicker (CAL-12) so the chip set
        # carries the qualifiers (intent/setting/access), not a repeat.
        chips = render_tag_chips(row, cls='cal-row__tags', nav_prefix=nav_prefix,
                                 skip={mod} if mod else None)
        if chips:
            parts.append('      ' + chips)

    # CTA row: ticket link (external -> their link, new tab; Firstwater -> its
    # session page) plus the operator/venue 'own page' link when known. External
    # ticket/site URLs are scheme-checked before becoming hrefs; unsafe -> no link.
    cta = []
    if is_fw:
        # [port] absolute cross-site link to the session page's own checkout
        cta.append(
            f'<a href="{_esc(row["ticket_url"])}" target="_blank" '
            f'rel="noopener">Get tickets</a>'
        )
    else:
        safe = _safe_ext_url(row['ticket_url'])
        if safe:
            cta.append(
                f'<a href="{_esc(safe)}" target="_blank" rel="noopener">Tickets</a>'
            )
        link_url, link_label = _facil_venue_link(row)
        if link_url:
            cta.append(
                f'<a class="cal-row__link" href="{_esc(link_url)}" '
                f'target="_blank" rel="noopener">{_esc(link_label)}</a>'
            )
    if cta:
        parts.append('      <p class="cal-row__cta">' + ' '.join(cta) + '</p>')

    parts.append('    </div>')  # .cal-row__text
    parts.append('  </div>')    # .cal-row__body
    parts.append('</article>')
    return '\n'.join(parts)


# ---------------------------------------------------------------------------
# Temporal bands — the root's axis (Track B B.1). Every future row lands in
# exactly one band; the bands render in this fixed order:
#   Today / Tonight  ·  This weekend  ·  This week  ·  The weeks ahead
# ---------------------------------------------------------------------------

def band_assignments(rows, now=None):
    """Partition future rows into the four temporal bands, each chronological:
    (today, this_weekend, this_week, weeks_ahead).

    Clean partition — today wins first; then the relevant Fri–Sun weekend
    (always within the next 7 days); then anything else inside 7 days; then
    everything beyond. Rows are assumed already future + de-duplicated + sorted
    (build_rows guarantees this)."""
    now = _now_utc(now)
    today = now.astimezone(DENVER).date()
    wknd_start, wknd_end = weekend_window(now)
    week_end = now + timedelta(days=7)

    today_b, weekend_b, week_b, ahead_b = [], [], [], []
    for r in rows:
        dt = parse_iso(r['starts_at'])
        local = dt.astimezone(DENVER)
        if local.date() == today:
            today_b.append(r)
        elif wknd_start <= local <= wknd_end:
            weekend_b.append(r)
        elif dt <= week_end:
            week_b.append(r)
        else:
            ahead_b.append(r)
    return today_b, weekend_b, week_b, ahead_b


# "Tonight" reads truer than "Today" once the day's only remaining rooms are
# evening ones; cutover 5pm Denver. PLACEHOLDER rule, flagged for Daniel.
_TONIGHT_HOUR = 17


def today_band_label(today_rows, now=None):
    """'Today', or 'Tonight' when every remaining room today is an evening one."""
    if today_rows and all(
        parse_iso(r['starts_at']).astimezone(DENVER).hour >= _TONIGHT_HOUR
        for r in today_rows
    ):
        return 'Tonight'
    return 'Today'


def _render_rows(rows, show_date, nav_prefix, geocode=None):
    inner = '\n'.join(
        _render_row(r, show_date=show_date, nav_prefix=nav_prefix, geocode=geocode)
        for r in rows)
    return f'<div class="cal-rows">\n{inner}\n</div>'


def _render_bands(rows, nav_prefix='', now=None, geocode=None):
    """The temporal jump-nav + the four bands in fixed order (each drawn only
    when it has rooms). Shared by the root and the city pages; the caller
    appends its own FAQ. An empty weekend band simply isn't drawn — 'This week'
    carries the near term — so a page never prints 'nothing this weekend'."""
    today_b, weekend_b, week_b, ahead_b = band_assignments(rows, now)
    bands = []
    if today_b:
        bands.append(('today', today_band_label(today_b, now), today_b, False))
    if weekend_b:
        bands.append(('this-weekend', 'This weekend', weekend_b, True))
    if week_b:
        bands.append(('this-week', 'This week', week_b, True))
    if ahead_b:
        bands.append(('weeks-ahead', 'The weeks ahead', ahead_b, True))

    out = []

    # Temporal jump-nav — only the bands that exist, plus the FAQ.
    out.append('<nav class="cal-jump" aria-label="Jump to a time">')
    for bid, label, _brows, _sd in bands:
        out.append(f'  <a href="#{bid}">{_esc(label)}</a>')
    out.append('  <a href="#faq">FAQ</a>')
    out.append('</nav>')

    if not bands:
        out.append(f'<p class="cal-empty cal-empty--all">{_esc(ALL_EMPTY)}</p>')

    for bid, label, brows, show_date in bands:
        out.append(f'<section class="cal-band" id="{bid}">')
        out.append(f'  <h2 class="cal-band__h2">{_esc(label)}</h2>')
        out.append('  ' + _render_rows(brows, show_date, nav_prefix, geocode))
        out.append('</section>')

    return '\n'.join(out)


# Register-passable PLACEHOLDER no-results line (B.5 filters). Flagged for Daniel.
NO_RESULTS = 'No sessions match those filters.'


def render_filters(rows=None, include_city=True):
    """The progressive-enhancement filter bar (B.5 + CAL-01): area (root only) +
    free/donation + tags. Hidden until filters.js reveals it, so no-JS visitors
    see every row and the page is fully usable. The tag facet only offers tags
    actually present in `rows` (never a filter that would match nothing), grouped
    by axis. PLACEHOLDER copy, flagged."""
    out = ['<div class="cal-filters" data-cal-filters hidden>']
    out.append('  <div class="cal-filters__primary">')
    if include_city:
        opts = ['<option value="">All areas</option>']
        opts += [f'<option value="{_esc(city_slug(c))}">{_esc(c)}</option>'
                 for c in CITIES]
        out.append('    <label class="cal-filters__field">')
        out.append('      <span class="visually-hidden">Filter by area</span>')
        out.append('      <select data-filter-city>' + ''.join(opts) + '</select>')
        out.append('    </label>')
    out.append('    <label class="cal-filters__check">'
               '<input type="checkbox" data-filter-free> '
               '<span>Free / donation only</span></label>')
    # CAL-05 near-me sort. Rendered hidden and only revealed by filters.js when
    # at least one row on the page carries coordinates (and geolocation exists),
    # so no-JS visitors never see a dead control.
    out.append('    <button type="button" class="cal-filters__nearme" '
               'data-nearme aria-pressed="false" hidden>Sort by distance</button>')
    out.append('  </div>')

    present = present_tag_slugs(rows or [])
    if present:
        present_set = set(present)
        out.append('  <div class="cal-filters__tags" role="group" '
                   'aria-label="Filter by tag">')
        for axis, axis_label in taxonomy.TAG_AXES:
            axis_slugs = [s for s, _l in taxonomy.tags_by_axis(axis)
                          if s in present_set]
            if not axis_slugs:
                continue
            out.append('    <div class="cal-filters__axis">')
            out.append(f'      <span class="cal-filters__axislabel">{_esc(axis_label)}</span>')
            for slug in axis_slugs:
                out.append(
                    '      <label class="cal-tag cal-tag--toggle">'
                    f'<input type="checkbox" data-filter-tag="{_esc(slug)}"> '
                    f'<span>{_esc(taxonomy.label_for(slug))}</span></label>')
            out.append('    </div>')
        out.append('  </div>')
    out.append('</div>')
    return '\n'.join(out)


def _render_noresults():
    """The 'nothing matches your filters' line — hidden until filters.js shows it."""
    return f'<p class="cal-empty" data-cal-noresults hidden>{_esc(NO_RESULTS)}</p>'


def render_calendar_body(rows, nav_prefix='', now=None, geocode=None):
    """The dynamic middle of the root: filter bar + nav + bands + no-results +
    FAQ. Static scaffold (H1, stamp, summary, digest, submission line) lives in
    the section file; this returns everything that depends on the feed."""
    # FAQ — a GEO/AIO citation surface (FAQPage JSON-LD emitted by build.py).
    return '\n'.join([
        render_filters(rows, include_city=True),
        _render_bands(rows, nav_prefix, now, geocode),
        _render_noresults(),
        render_faq_html(),
    ])


# ---------------------------------------------------------------------------
# Event JSON-LD (ItemList of Events — accurate or absent, never padded)
# ---------------------------------------------------------------------------

_PRICE_NUM_RE = re.compile(r'\d+(?:\.\d+)?')
# "free" as a standalone word — NOT the "free" buried in "freewill".
_FREE_RE = re.compile(r'\bfree\b', re.I)
# Pay-what-you-can / donation intent. When any of these appear, a bare "free"
# does NOT mean $0 ("Freewill donation", "free-will offering", "free, sliding
# scale"): the true price is unknown, so emit no price rather than a false 0
# (spec: "accurate or absent, never padded").
_DONATION_RE = re.compile(r'donat|offering|free[- ]will|sliding|suggested|pay[- ]?what', re.I)


def _parse_price(price):
    """('fixed', n) | ('free',) | ('range', lo, hi) | (None,)."""
    if not price:
        return (None,)
    nums = [float(x) for x in _PRICE_NUM_RE.findall(price)]
    if not nums:
        is_free = bool(_FREE_RE.search(price)) and not _DONATION_RE.search(price)
        return ('free',) if is_free else (None,)
    if len(nums) == 1:
        return ('fixed', nums[0])
    return ('range', min(nums), max(nums))


def _fmt_price_num(n):
    return str(int(n)) if n == int(n) else f'{n:.2f}'


def _external_offer(row):
    """Offer/AggregateOffer for an external row, or None. Ticket url only when
    known; price only when it can be read accurately from the price string.
    [port] isAccessibleForFree moved OFF the Offer (validator.schema.org
    warning: not a recognized Offer property) and onto the Event, where
    schema.org defines it; price:0 already says free here."""
    kind = _parse_price(row['price'])
    url = _safe_ext_url(row['ticket_url']) or None
    if kind[0] == 'fixed':
        offer = {'@type': 'Offer', 'price': _fmt_price_num(kind[1]), 'priceCurrency': 'USD'}
    elif kind[0] == 'free':
        offer = {'@type': 'Offer', 'price': '0', 'priceCurrency': 'USD'}
    elif kind[0] == 'range':
        offer = {'@type': 'AggregateOffer',
                 'lowPrice': _fmt_price_num(kind[1]),
                 'highPrice': _fmt_price_num(kind[2]),
                 'priceCurrency': 'USD'}
    elif url:
        offer = {'@type': 'Offer'}   # price unknown (e.g. "Donation") — never guessed
    else:
        return None
    if url:
        offer['url'] = url
    return offer


def _external_event(row, site_url):
    """schema.org Event (no @context) for one external row: only fields we know.

    url = the event's PERMALINK (its /calendar/event/<slug>/ page); offers.url
    stays the operator's ticket link. description = Daniel's note if present,
    else the factual description/template (accurate, never padded). performer =
    the named facilitator; organizer = the operator; image = the listing image.
    """
    place = {'@type': 'Place'}
    if row['venue']:
        place['name'] = row['venue']
    addr = {'@type': 'PostalAddress', 'addressLocality': row['city'],
            'addressRegion': 'CO', 'addressCountry': 'US'}
    if row['address']:
        addr['streetAddress'] = row['address']
    place['address'] = addr

    ev = {
        '@type': 'Event',
        'name': row['name'],
        'startDate': _denver(row['starts_at']).isoformat(),
        'eventStatus': 'https://schema.org/EventScheduled',
        'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
        'location': place,
    }
    desc = editorial_note(row) or factual_description(row)
    if desc:
        ev['description'] = desc
    if row.get('facilitator'):
        ev['performer'] = {'@type': 'Person', 'name': row['facilitator']}
    if row['operator']:
        ev['organizer'] = {'@type': 'Organization', 'name': row['operator']}
        if row.get('operator_url'):
            ev['organizer']['url'] = row['operator_url']
    if row.get('image_url'):
        ev['image'] = {'@type': 'ImageObject', 'url': row['image_url'],
                       'caption': alt_text(row)}
    offer = _external_offer(row)
    if offer:
        ev['offers'] = offer
    # Free events: the flag lives on the Event (its schema.org home).
    if _parse_price(row['price'])[0] == 'free':
        ev['isAccessibleForFree'] = True
    slug = event_slug(row)
    if slug:
        ev['url'] = event_permalink_url(row, site_url)
    return ev


def event_jsonld(row, site_url):
    """Standalone Event (with @context) for an external event's permalink page."""
    return {'@context': 'https://schema.org', **_external_event(row, site_url)}


def _firstwater_event(row, site_url):
    """Reuse sessions_feed's Event builder so Firstwater rows carry the same
    accurate Event markup as their session pages; url points at the session page
    (its canonical home ON THEFIRSTWATER.CO — [port]: never this domain), and
    @context is stripped for ItemList nesting."""
    slug = (row.get('_sess') or {}).get('event_slug', '')
    session_url = f'{FIRSTWATER_URL}/sessions/{slug}/' if slug else FIRSTWATER_URL
    ev = sessions_feed.event_schema(
        row['_sess'], row['_event_title'], session_url, FIRSTWATER_URL,
    )
    ev.pop('@context', None)
    return ev


def calendar_itemlist(rows, page_url, site_url):
    """One ItemList wrapping an Event per rendered row, or None when empty.

    Rows are already future + approved + de-duplicated + city/chronologically
    ordered by build_rows/group_by_city; the caller passes that same ordering.
    """
    # Chronological, to match the page's temporal axis (Track B).
    ordered = sorted(rows, key=lambda r: parse_iso(r['starts_at']))
    if not ordered:
        return None

    items = []
    for i, row in enumerate(ordered, start=1):
        ev = (_firstwater_event(row, site_url)
              if row['kind'] == 'firstwater' else _external_event(row, site_url))
        items.append({'@type': 'ListItem', 'position': i, 'item': ev})

    return {
        '@context': 'https://schema.org',
        # [port] "upcoming", not "this week" — the list holds three weeks
        # (pivot-memo P0 fix c).
        '@type': 'ItemList',
        'name': 'Upcoming sound baths on the Front Range',
        'itemListElement': items,
    }


def collectionpage_schema(page_url, site_url, description, date_modified):
    """CollectionPage schema for the calendar root with a speakable summary
    selector. dateModified matches the visible 'Last updated' stamp (emitted
    from build time — pivot-memo P0 fix e). [port] The publishing WebSite is
    Sound Bath Calendar, and the name says "upcoming" (fix c)."""
    return {
        '@context': 'https://schema.org',
        '@type': 'CollectionPage',
        'name': 'Upcoming sound baths in Denver & the Front Range',
        'url': page_url,
        'description': description,
        'dateModified': date_modified,
        'isPartOf': {'@type': 'WebSite', 'name': 'Sound Bath Calendar',
                     'url': site_url},
        'speakable': {'@type': 'SpeakableSpecification',
                      'cssSelector': ['#cal-summary']},
    }


def faqpage_schema():
    """FAQPage schema built from the same CALENDAR_FAQ the page renders."""
    return {
        '@context': 'https://schema.org',
        '@type': 'FAQPage',
        'mainEntity': [
            {'@type': 'Question', 'name': item['q'],
             'acceptedAnswer': {'@type': 'Answer', 'text': item['a']}}
            for item in CALENDAR_FAQ
        ],
    }


# ---------------------------------------------------------------------------
# City pages (Track B B.2) — the durable geographic surfaces that own the
# "{city} sound bath" query families. Same temporal bands as the root, filtered
# to one city, each with its own H1, summary, FAQ, OG, and schema. The root
# stays the freshness surface; these are the SEO surfaces. Assembly (base
# layout, <head>, schema) is build.py's job; render_city_page returns the
# <main> body, consonant with the permalink pipeline.
# ---------------------------------------------------------------------------

# PLACEHOLDER per-city display + search copy (flagged for Daniel).
CITY_H1 = {c: f'Sound baths in {c}' for c in CITIES}
CITY_META = {
    c: (f'A weekly-updated calendar of sound baths in {c}, Colorado: dates, '
        f'times, venues, prices, and ticket links for every listed session. '
        f'Part of the Front Range sound bath calendar.')
    for c in CITIES
}


def city_slug(city):
    """Canonical URL slug for a city ('Fort Collins' -> 'fort-collins')."""
    return CITY_ANCHOR[city]


def city_page_path(city):
    """Site-relative path for a city page (trailing slash)."""
    return f'{city_slug(city)}/'


def city_page_url(city, site_url):
    return f'{site_url}/{city_page_path(city)}'


def city_rows(rows, city):
    """The subset of rows in one city, chronological."""
    out = [r for r in rows if r['city'] == city]
    out.sort(key=lambda r: parse_iso(r['starts_at']))
    return out


def build_city_summary_sentence(rows, city, now=None):
    """Machine-extractable answer-first sentence for a city page: the next
    seven days' count in that city, with a price span. Rebuilt every build."""
    wk = [r for r in week_rows(rows, now) if r['city'] == city]
    n = len(wk)
    if n == 0:
        return (f'No sound baths are on the {city} calendar for the next seven '
                f'days yet; the weeks ahead are listed below.')
    noun = 'bath' if n == 1 else 'baths'
    sent = f'This week in {city}: {n} sound {noun}'
    lo_label, hi = _price_span(wk)
    if hi is not None:
        sent += f', priced {lo_label} to ${_fmt_price_num(hi)}'
    return sent + '.'


def city_faq(city):
    """PLACEHOLDER per-city FAQ (flagged for Daniel) — the calendar FAQ,
    localized so each city page is its own answer surface for search/AI."""
    return (
        {
            'q': f'Where can I find a sound bath in {city}?',
            'a': (f'This page lists every sound bath on our {city} calendar, '
                  'updated through the week. A sound bath is a session where you '
                  'lie down, usually on a mat, while a facilitator plays '
                  'instruments such as gongs, singing bowls, and chimes. Most run '
                  '45 to 75 minutes, and you stay clothed and still throughout.'),
        },
        {
            'q': f'How much do sound baths cost in {city}?',
            'a': ('Most sessions run between $20 and $55. Some are offered by '
                  'donation or free. Each listing shows its own price, and the '
                  'ticket link goes straight to the operator.'),
        },
        {
            'q': 'What should I bring to a sound bath?',
            'a': ('Wear clothes you can lie down in. Many rooms provide mats, '
                  'bolsters, and blankets, though your own blanket, a pillow, and '
                  'water are never wrong. When in doubt, the operator’s listing '
                  'says what the room supplies.'),
        },
    )


def render_city_switcher(current_city, nav_prefix):
    """Links to the OTHER city pages — the internal-link graph plus reader nav
    across areas. The root is reachable from the masthead wordmark."""
    out = ['<nav class="cal-cities" aria-label="Other areas">',
           '  <span class="cal-cities__label">Other areas</span>']
    for c in CITIES:
        if c == current_city:
            continue
        out.append(f'  <a href="{nav_prefix}{city_page_path(c)}">{_esc(c)}</a>')
    out.append('</nav>')
    return '\n'.join(out)


def render_digest_block(selected_city='all'):
    """The Thursday-digest capture form, with one area preselected. Posts to the
    events service /digest/subscribe (Track C) — a plain form + 303 redirect back
    to /thanks/; the service sets the list flag + area and source server-side.
    Mirrors the root form in sections/01-content.html."""
    opts = [('all', 'Everywhere on the Front Range')]
    opts += [(city_slug(c), c) for c in CITIES]
    option_html = '\n'.join(
        f'          <option value="{v}"{" selected" if v == selected_city else ""}>'
        f'{_esc(label)}</option>'
        for v, label in opts
    )
    return f'''<div class="digest-block" id="digest">
      <span class="eyebrow">The digest</span>
      <p class="form-note">The week's rooms, Thursday mornings.</p>
      <form class="contact-form" action="https://admin.soundbathcalendar.com/digest/subscribe" method="POST">
        <input type="hidden" name="next" value="https://soundbathcalendar.com/thanks/">
        <label class="form-field">
          <span>Email</span>
          <input type="email" name="email" autocomplete="email" required>
        </label>
        <label class="form-field">
          <span>Which areas?</span>
          <select name="cities">
{option_html}
          </select>
        </label>
        <button type="submit" class="btn btn-primary">Get the digest</button>
      </form>
    </div>'''


def render_city_page(rows, city, nav_prefix, now=None, geocode=None):
    """The <main> body for one city page: crumb · H1 · stamp · summary · the
    temporal bands (this city only) · other-areas nav · city FAQ · digest ·
    submission line."""
    now = _now_utc(now)
    crows = city_rows(rows, city)
    slug = city_slug(city)
    out = ['<section class="section section--light cal-main">', '  <div class="container">']

    out.append('    <nav class="cal-crumbs" aria-label="Breadcrumb">')
    out.append(f'      <a href="{nav_prefix}">Calendar</a> <span aria-hidden="true">/</span> '
               f'<span>{_esc(city)}</span>')
    out.append('    </nav>')

    out.append(f'    <h1 class="cal-h1">{_esc(CITY_H1[city])}</h1>')
    out.append(f'    <p class="cal-updated">Last updated {_esc(fmt_stamp_date(now))}.</p>')
    out.append(f'    <p class="cal-summary" id="cal-summary">'
               f'{_esc(build_city_summary_sentence(rows, city, now))}</p>')
    out.append('    ' + render_ics_subscribe(f'{slug}.ics'))

    # City is fixed here, so the bar carries the free/donation chip + the tags
    # present in this city.
    out.append('    ' + render_filters(crows, include_city=False))
    out.append('    ' + _render_bands(crows, nav_prefix, now, geocode))
    out.append('    ' + _render_noresults())
    out.append('    ' + render_city_switcher(city, nav_prefix))
    out.append('    ' + _render_faq(city_faq(city)))
    out.append('    ' + render_digest_block(selected_city=slug))

    out.append('    <p class="cal-submit">Running a room we should know about? '
               '<a href="mailto:hello@soundbathcalendar.com?subject=A%20room%20for%20the%20calendar">Send it our way.</a></p>')

    out.append('  </div>')
    out.append('</section>')
    return '\n'.join(out)


def city_collectionpage_schema(city, page_url, site_url, description, date_modified):
    """CollectionPage schema for a city page (speakable summary + build-time
    dateModified), published by the Sound Bath Calendar WebSite."""
    return {
        '@context': 'https://schema.org',
        '@type': 'CollectionPage',
        'name': f'Upcoming sound baths in {city}, Colorado',
        'url': page_url,
        'description': description,
        'dateModified': date_modified,
        'isPartOf': {'@type': 'WebSite', 'name': 'Sound Bath Calendar',
                     'url': site_url},
        'speakable': {'@type': 'SpeakableSpecification',
                      'cssSelector': ['#cal-summary']},
    }


def city_itemlist(rows, city, site_url):
    """ItemList of Events for one city (chronological), or None when empty."""
    crows = city_rows(rows, city)
    if not crows:
        return None
    items = []
    for i, row in enumerate(crows, start=1):
        ev = (_firstwater_event(row, site_url)
              if row['kind'] == 'firstwater' else _external_event(row, site_url))
        items.append({'@type': 'ListItem', 'position': i, 'item': ev})
    return {
        '@context': 'https://schema.org',
        '@type': 'ItemList',
        'name': f'Upcoming sound baths in {city}',
        'itemListElement': items,
    }


def city_faqpage_schema(city):
    """FAQPage schema built from the same city_faq the page renders."""
    return {
        '@context': 'https://schema.org',
        '@type': 'FAQPage',
        'mainEntity': [
            {'@type': 'Question', 'name': item['q'],
             'acceptedAnswer': {'@type': 'Answer', 'text': item['a']}}
            for item in city_faq(city)
        ],
    }


# ---------------------------------------------------------------------------
# ICS feeds (Track B B.4) — per-city webcal subscribe + whole-calendar +
# per-event .ics, all STATIC files the build emits from the same rows the pages
# render (the move nobody local has: a subscriber never needs the site again).
# Format/discipline mirror service/src/lib/ics.ts, via stdlib _src/lib/ics.py.
# Sound baths carry no explicit end time in the feed, so DTEND is a fixed
# default duration — a calendar-entry display convenience, not a claim about
# the event. PLACEHOLDER duration, flagged for Daniel.
# ---------------------------------------------------------------------------

ICS_DEFAULT_DURATION_MIN = 75


def _ics_location(row):
    """One LOCATION string: venue + street address, else venue + city."""
    bits = [x for x in (row.get('venue'), row.get('address')) if x]
    if not bits:
        bits = [x for x in (row.get('venue'), row.get('city')) if x]
    return ', '.join(bits)


def event_ics_input(row, site_url, now=None):
    """Normalize one row into the event dict _src/lib/ics.py expects. URL points
    at the event's own page (permalink for external, session page for
    Firstwater); the ticket link rides in DESCRIPTION."""
    start = parse_iso(row['starts_at'])
    end = start + timedelta(minutes=ICS_DEFAULT_DURATION_MIN)
    if row['kind'] == 'firstwater':
        slug = (row.get('_sess') or {}).get('event_slug', '')
        url = f'{FIRSTWATER_URL}/sessions/{slug}/' if slug else FIRSTWATER_URL
        ticket = row.get('ticket_url', '')
    else:
        url = event_permalink_url(row, site_url)
        ticket = _safe_ext_url(row.get('ticket_url', ''))
    desc = factual_description(row)
    if ticket:
        desc = f'{desc}\n\nTickets: {ticket}'
    return {
        'uid': f'{event_slug(row)}@{CALENDAR_ORIGIN}',
        'title': row['name'],
        'start': start,
        'end': end,
        'location': _ics_location(row),
        'description': desc,
        'url': url,
    }


def build_calendar_ics(rows, site_url, cal_name, now=None):
    """A VCALENDAR of the given rows (chronological)."""
    now = _now_utc(now)
    evs = [event_ics_input(r, site_url, now)
           for r in sorted(rows, key=lambda r: parse_iso(r['starts_at']))]
    return ics_lib.generate_calendar(evs, now, cal_name=cal_name)


def build_city_ics(rows, city, site_url, now=None):
    return build_calendar_ics(
        city_rows(rows, city), site_url, f'Sound baths in {city}', now)


def build_event_ics(row, site_url, now=None):
    now = _now_utc(now)
    return ics_lib.generate_calendar(
        [event_ics_input(row, site_url, now)], now, cal_name=row['name'])


def ics_webcal_url(ics_filename):
    """webcal:// subscribe URL for a build-emitted .ics file at the site root."""
    return f'webcal://{CALENDAR_ORIGIN}/{ics_filename}'


def ics_https_url(ics_filename):
    """https:// download URL for a build-emitted .ics file at the site root."""
    return f'https://{CALENDAR_ORIGIN}/{ics_filename}'


def render_ics_subscribe(ics_filename):
    """The subscribe + download line for a root or city page. PLACEHOLDER copy."""
    return (
        '<p class="cal-ics">'
        f'<a class="cal-ics__sub" href="{ics_webcal_url(ics_filename)}">'
        'Subscribe in your calendar</a> '
        f'<a class="cal-ics__dl" href="{ics_https_url(ics_filename)}">'
        'Download .ics</a></p>'
    )


# ---------------------------------------------------------------------------
# Per-event permalink page (/calendar/event/<slug>/) — the body HTML. Page
# assembly (base layout, <head>, schema) is build.py's job; this returns the
# <main> content only, consonant with the section-file pipeline.
# ---------------------------------------------------------------------------

# Inline style for event pages (they have no _src/pages dir, so no style.css is
# injected). Design tokens come from the sitewide styles.css every page loads.
EVENT_PAGE_STYLE = """<style>
    .cal-event { }
    .cal-event__crumbs { font-size: 0.82rem; color: rgba(10,11,13,0.55); margin: 0 0 2rem; }
    .cal-event__crumbs a { color: var(--accent-on-light); text-decoration: none; }
    .cal-event__crumbs a:hover { text-decoration: underline; }
    .cal-past-banner { background: rgba(10,11,13,0.05); border-left: 3px solid var(--gray); padding: 0.9rem 1.2rem; margin: 0 0 2rem; font-size: 0.95rem; }
    .cal-past-banner a { color: var(--accent-on-light); }
    .cal-event__h1 { font-size: clamp(2rem, 4vw, 3rem); margin: 0.4rem 0 1.4rem; }
    .cal-event__desc { font-size: 1.15rem; line-height: 1.6; max-width: 42rem; color: rgba(10,11,13,0.78); margin: 0 0 1rem; }
    .cal-event__note { font: 500 1.2rem var(--font-display); color: var(--ink); max-width: 40rem; line-height: 1.4; margin: 0 0 1.6rem; }
    .cal-event__figure { margin: 2rem 0; max-width: 640px; }
    .cal-event__figure img { width: 100%; aspect-ratio: 3 / 2; object-fit: cover; display: block; background: rgba(10,11,13,0.06); }
    .cal-event__figure figcaption { font-size: 0.82rem; color: rgba(10,11,13,0.55); margin-top: 0.6rem; }
    .cal-event__facts { display: grid; grid-template-columns: max-content 1fr; gap: 0.6rem 1.6rem; margin: 2rem 0; max-width: 40rem; }
    .cal-event__facts dt { font: 600 0.72rem var(--font-body); letter-spacing: 0.13em; text-transform: uppercase; color: var(--gray); align-self: baseline; }
    .cal-event__facts dd { margin: 0; color: var(--ink); }
    .cal-event__cta { display: flex; flex-wrap: wrap; gap: 1rem 1.6rem; align-items: center; margin: 2rem 0; }
    .cal-event__link { color: var(--accent-on-light); font: 600 0.9rem var(--font-body); text-decoration: none; }
    .cal-event__link:hover { text-decoration: underline; }
    .cal-event__back { margin: 2.4rem 0 0; padding-top: 2rem; border-top: 1px solid rgba(10,11,13,0.14); }
    .cal-event__back a { color: var(--accent-on-light); text-decoration: none; }
    .cal-event__back a:hover { text-decoration: underline; }
    @media (max-width: 640px) { .cal-event__facts { grid-template-columns: 1fr; gap: 0.2rem; } .cal-event__facts dd { margin-bottom: 0.8rem; } }
  </style>"""


def render_event_page(row, nav_prefix, site_url, now=None):
    """The <main> content for one external event's permalink page."""
    now = _now_utc(now)
    is_past = parse_iso(row['starts_at']) <= now
    esc = _esc
    out = ['<section class="section section--light cal-event">', '  <div class="container">']

    # Breadcrumb (visible) — mirrors the BreadcrumbList schema build.py emits.
    # [port] The calendar IS the home page here, so the trail is two levels.
    out.append('    <nav class="cal-event__crumbs" aria-label="Breadcrumb">')
    out.append(
        f'      <a href="{nav_prefix}">Calendar</a> <span aria-hidden="true">/</span> '
        f'<span>{esc(row["name"])}</span>')
    out.append('    </nav>')

    # Past session: page stays live (build.py sets robots=noindex + drops it from
    # the sitemap) but says so and points at the current list.
    if is_past:
        out.append(
            '    <p class="cal-past-banner">This session has passed. '
            f'<a href="{nav_prefix}">See what’s on now →</a></p>')

    # Two-column detail shell (CAL-10): identity + narrative in the reading
    # column, the decision card (facts · map · tickets · add-to-calendar) in the
    # sticky aside. Collapses to one column below 900px via styles.css.
    out.append('    <div class="detail-shell">')
    out.append('      <div class="detail-main">')
    out.append('    <span class="eyebrow">Front Range calendar</span>')
    out.append(f'    <h1 class="cal-event__h1">{esc(row["name"])}</h1>')

    out.append(f'    <p class="cal-event__desc">{esc(factual_description(row))}</p>')
    note = editorial_note(row)
    if note:
        out.append(f'    <p class="cal-event__note">{esc(note)}</p>')

    # Tag chips (CAL-01) — the canonical vocabulary for this session, or nothing.
    chips = render_tag_chips(row, cls='cal-event__tags', nav_prefix=nav_prefix)
    if chips:
        out.append('    ' + chips)

    img = row.get('image_url')
    if img:
        out.append('    <figure class="cal-event__figure">')
        out.append(
            f'      <img src="{esc(img)}" alt="{esc(alt_text(row))}" '
            f'loading="lazy" decoding="async">')
        out.append(f'      <figcaption>{esc(alt_text(row))}</figcaption>')
        out.append('    </figure>')

    # End the reading column; open the sticky decision aside + card.
    out.append('      </div>')  # .detail-main
    out.append('      <aside class="detail-aside">')
    out.append('        <div class="detail-card">')

    # Facts block
    out.append('    <dl class="cal-event__facts">')
    out.append(
        f'      <dt>When</dt><dd>{esc(sessions_feed.fmt_date_long(row["starts_at"]))} '
        f'· {esc(fmt_time(row["starts_at"]))} (Denver time)</dd>')
    # Where: link the venue to its curated /venue/<slug>/ page when linked to a
    # published one (CAL-03); otherwise the plain venue + address string.
    vr = row.get('venue_ref') or {}
    vr_slug = vr.get('slug') if isinstance(vr, dict) else None
    if vr_slug:
        vr_href = f'{nav_prefix}venue/{vr_slug}/'
        addr = row.get('address')
        where_dd = (f'<a class="cal-event__link" href="{esc(vr_href)}">'
                    f'{esc(vr.get("name") or row.get("venue") or "")}</a>')
        if addr:
            where_dd += f' · {esc(addr)}'
        out.append(f'      <dt>Where</dt><dd>{where_dd}</dd>')
    else:
        venue_bits = ' · '.join(x for x in (row.get('venue'), row.get('address')) if x)
        if venue_bits:
            out.append(f'      <dt>Where</dt><dd>{esc(venue_bits)}</dd>')
    place = row['neighborhood'] if row['city'] == 'Denver' and row.get('neighborhood') else None
    area = f'{place}, {row["city"]}' if place else row['city']
    out.append(f'      <dt>Area</dt><dd>{esc(area)}</dd>')
    if row.get('price'):
        out.append(f'      <dt>Price</dt><dd>{esc(row["price"])}</dd>')
    # Facilitator: link to the practitioner profile when this session is linked
    # to a published one (CAL-02); otherwise the plain listing string.
    pr = row.get('practitioner') or {}
    pr_slug = pr.get('slug') if isinstance(pr, dict) else None
    if pr_slug:
        pr_href = f'{nav_prefix}practitioner/{pr_slug}/'
        out.append(
            f'      <dt>Facilitator</dt><dd><a class="cal-event__link" '
            f'href="{esc(pr_href)}">{esc(pr.get("name") or row.get("facilitator") or "")}</a></dd>')
    elif row.get('facilitator'):
        out.append(f'      <dt>Facilitator</dt><dd>{esc(row["facilitator"])}</dd>')
    # Operator: link to the organizer profile when this session is linked to a
    # published one (CAL-08); otherwise the plain listing string.
    orf = row.get('operator_ref') or {}
    orf_slug = orf.get('slug') if isinstance(orf, dict) else None
    if orf_slug:
        orf_href = f'{nav_prefix}operator/{orf_slug}/'
        out.append(
            f'      <dt>Operator</dt><dd><a class="cal-event__link" '
            f'href="{esc(orf_href)}">{esc(orf.get("name") or row.get("operator") or "")}</a></dd>')
    elif row.get('operator'):
        out.append(f'      <dt>Operator</dt><dd>{esc(row["operator"])}</dd>')
    out.append('    </dl>')

    # Embedded venue mini-map (CAL-10) — the no-key Google embed the venue pages
    # use (CAL-03), keyed on this session's address. Upcoming events only; a
    # room with no address simply gets no map (the "Open in Maps" link remains).
    if row.get('address'):
        mq = quote_plus(f'{row["address"]}, {row["city"]}, CO')
        out.append(
            f'    <iframe class="detail-card__map" loading="lazy" title="Map"'
            f' src="https://maps.google.com/maps?q={mq}&amp;z=15&amp;output=embed"'
            f' referrerpolicy="no-referrer-when-downgrade"></iframe>')

    # Links: operator tickets + operator/venue own page + a maps link.
    links = []
    safe = _safe_ext_url(row['ticket_url'])
    if safe:
        links.append(
            f'<a class="btn btn-primary" href="{esc(safe)}" target="_blank" '
            f'rel="noopener">Tickets</a>')
    link_url, link_label = _facil_venue_link(row)
    if link_url:
        links.append(
            f'<a class="cal-event__link" href="{esc(link_url)}" target="_blank" '
            f'rel="noopener">{esc(link_label)}</a>')
    if row.get('address'):
        q = quote_plus(f'{row["address"]}, {row["city"]}, CO')
        maps = f'https://www.google.com/maps/search/?api=1&query={q}'
        links.append(
            f'<a class="cal-event__link" href="{esc(maps)}" target="_blank" '
            f'rel="noopener">Open in Maps</a>')
    if links:
        out.append('    <p class="cal-event__cta">' + ' '.join(links) + '</p>')

    # Add-to-calendar menu (CAL-01) — upcoming events only. A <details>
    # disclosure (no JS) offering Google/Outlook launch links + the local
    # event.ics for Apple/Outlook desktop and a raw download. The .ics is
    # written beside this page at event/<slug>/event.ics (Track B B.4).
    if not is_past:
        cal = add_to_calendar_urls(row, site_url, now)
        out.append('    <details class="cal-addcal">')
        out.append('      <summary class="cal-event__link cal-addcal__summary">'
                   'Add to calendar</summary>')
        out.append('      <div class="cal-addcal__menu">')
        out.append(
            f'        <a class="cal-addcal__opt" href="{esc(cal["google"])}" '
            f'target="_blank" rel="noopener">Google Calendar</a>')
        out.append(
            '        <a class="cal-addcal__opt" href="event.ics">'
            'Apple Calendar</a>')
        out.append(
            f'        <a class="cal-addcal__opt" href="{esc(cal["outlook"])}" '
            f'target="_blank" rel="noopener">Outlook</a>')
        out.append(
            '        <a class="cal-addcal__opt" href="event.ics" '
            'download>Download .ics</a>')
        out.append('      </div>')
        out.append('    </details>')

    out.append('        </div>')  # .detail-card
    out.append('      </aside>')  # .detail-aside
    out.append('    </div>')      # .detail-shell

    out.append(
        f'    <p class="cal-event__back"><a href="{nav_prefix}">'
        'Part of the Front Range calendar →</a></p>')

    out.append('  </div>')
    out.append('</section>')
    return '\n'.join(out)


def approved_event_rows(cal_feed, now=None):
    """External rows for EVERY approved event — past and future — deduped by
    permalink slug. Drives the permalink-page pipeline (future pages are
    indexed + in the sitemap; past pages stay live but noindex + out of it).
    Firstwater sessions are excluded: they already have their own rich session
    pages and must not get a second, duplicate permalink.
    """
    rows, seen = [], set()
    for e in (cal_feed or {}).get('events', []):
        if e.get('status') != RENDER_STATUS:
            continue
        try:
            parse_iso(e['starts_at'])
        except (KeyError, ValueError):
            continue
        row = _external_row(e)
        slug = event_slug(row)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        rows.append(row)
    rows.sort(key=lambda r: parse_iso(r['starts_at']))
    return rows
