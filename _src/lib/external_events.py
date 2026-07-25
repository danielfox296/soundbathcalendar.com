"""External sound-events feed loader + calendar renderer for build.py.

SOUND BATH CALENDAR: the calendar lives at the ROOT of soundbathcalendar.com,
with permalinks at /event/<slug>/.

The Front Range calendar lists sound events run by operators across the region.
At build time we:
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
fetch overwrites it.
Set CALENDAR_FEED_FILE=/abs/path to build against a local fixture without
ever touching the committed file.

Stdlib only — no new dependencies. Date/time formatting comes from
datetime_fmt so every surface agrees on a session's local date.

FEED CONTRACT (GET {CALENDAR_FEED_URL}), shape:
{ "generated_at": "<ISO>", "events": [ {
    "name","operator","starts_at","venue","address",
    "city": "Denver|Boulder|Fort Collins|Colorado Springs",
    "neighborhood": <str|null>,
    "price","ticket_url","source_url","tags":[...],
    "confidence": <0..1>, "dedup_key","status","note","rejection_note",
    "first_seen_at",   # CAL-15: when the pull first surfaced the listing (row
                       # createdAt) — becomes offers.validFrom in Event schema.
    # v2 (all optional; "" when unknown):
    "image_url",       # listing image / flyer (on-page <img> + schema image;
                       # og:image stays a committed card). https only, scrubbed.
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
from urllib.parse import quote, quote_plus, urlencode

from _src.lib import ics as ics_lib
from _src.lib import taxonomy
from _src.lib import datetime_fmt
from _src.lib.datetime_fmt import DENVER, parse_iso

DEFAULT_FEED_URL = 'https://admin.soundbathcalendar.com/feeds/calendar.json'
CACHE_REL_PATH = os.path.join('data', 'external-events.json')
FETCH_TIMEOUT_S = 10


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
# used when a row's city is not already canonical, or to place an
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


# Legal-suffix tokens folded ONLY inside _same_entity below. A scrape can
# register one entity twice — "Rocky Mountain Restore & Stretch" as operator,
# "Rocky Mountain Restore & Stretch LLC" as venue — and a strict compare then
# renders the same name near-doubled on a row. NEVER fold these in normalize()
# or make_dedup_key(): the dedup key must stay byte-identical to the
# authoritative TS service impl (docstring above), and entity counts keep
# near-duplicate variants distinct on purpose (insights.py flags them rather
# than silently merging). Deliberately minimal set.
_LEGAL_SUFFIX_RE = re.compile(r' (?:llc|inc|ltd|co)$')


def _same_entity(a, b):
    """CAL-UX-12: do these two names refer to one entity? normalize-equal,
    ignoring a single trailing legal suffix on either side. Presentation-layer
    comparison only (the own-room test: meta line, CTA label, ALT text) —
    never a dedup input. Empty on either side is never a match."""
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return False
    return _LEGAL_SUFFIX_RE.sub('', na) == _LEGAL_SUFFIX_RE.sub('', nb)


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
# Loading (mirrors datetime_fmt.load_feed precedence + graceful fallback)
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
# Time helpers (America/Denver) — thin wrappers over datetime_fmt so every
# surface formats dates identically.
# ---------------------------------------------------------------------------

def _denver(ts):
    return datetime_fmt._denver(ts)


def _day(n):
    return datetime_fmt._day(n)


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
    return datetime_fmt.fmt_time(ts)


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
# Row model — one normalized dict per rendered event.
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
        # The image additionally upgrades http->https (it embeds; see
        # _safe_image_url).
        'image_url': _safe_image_url(e.get('image_url', '')),
        'facilitator': (e.get('facilitator', '') or '').strip(),
        'operator_url': _safe_ext_url(e.get('operator_url', '')),
        'venue_url': _safe_ext_url(e.get('venue_url', '')),
        'description': (e.get('description', '') or '').strip(),
        # CAL-15: when the pull first surfaced the listing (ISO, Denver offset).
        'first_seen_at': e.get('first_seen_at', '') or '',
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


def build_rows(cal_feed, now=None):
    """Normalized, future, de-duplicated rows for the calendar.

    status='approved' AND starts in the future. Rejected/candidate events and
    past events never appear.
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

    # Defensive de-dup (the server already dedups; this guards a hand-edited
    # feed): first occurrence by dedup_key, then by (ticket_url, local date),
    # wins. The URL guard is date-scoped because recurring series share one
    # landing page across dates — a bare-URL key would keep only the first
    # future occurrence and orphan every later permalink (CAL-33).
    seen_keys, seen_urls, deduped = set(), set(), []
    for r in rows:
        k = r.get('dedup_key') or ''
        u = r.get('ticket_url') or ''
        d = parse_iso(r['starts_at']).astimezone(DENVER).date().isoformat()
        if k and k in seen_keys:
            continue
        if u and (u, d) in seen_urls:
            continue
        if k:
            seen_keys.add(k)
        if u:
            seen_urls.add((u, d))
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
    only."""
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
    if venue and not _same_entity(venue, op):
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


def entity_next_up(session_rows, nav_prefix):
    """The entity aside's "Next up" value (CAL-13 two-column adoption): the
    soonest upcoming session, linked to its permalink page. Returns '' when the
    entity has nothing upcoming. Callers style the bare <a> via their page-local
    sheet."""
    if not session_rows:
        return ''
    r = session_rows[0]
    href = _esc(f'{nav_prefix}{event_permalink_path(r)}')
    date = datetime_fmt.fmt_date_short(r['starts_at'])
    return f'<a href="{href}">{_esc(date)} · {_esc(r["name"])}</a>'


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


_COUNT_RE = re.compile(r'(\d+ sound baths?)')


def summary_html(sentence):
    """Escape an answer-first summary sentence and bold its session count —
    the v5 register's "bold counts" (CAL-26/27). Presentation-only: schema and
    speakable extraction read textContent, which <strong> leaves untouched."""
    return _COUNT_RE.sub(r'<strong>\1</strong>', _esc(sentence))


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
              'straight to the organizer.'),
    },
    {
        'q': 'What should I bring to a sound bath?',
        'a': ('Wear clothes you can lie down in. Many rooms provide mats, '
              'bolsters, and blankets, though your own blanket, a pillow, and '
              'water are never wrong. When in doubt, ask the organizer what '
              'the room supplies.'),
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
    # CAL-SEO-4: some scraped values arrive with their HTML-attribute escaping
    # still on ('&amp;' between query params). A URL is not HTML — collapse
    # that residue (however many layers deep: '&amp;amp;' -> '&amp;' -> '&')
    # so the template's single escape is the only escape and the JSON-LD
    # carries the true URL. A query value that genuinely needs '&' as data is
    # percent-encoded (%26), so only escaping residue matches here. This is
    # de-escaping, not re-serialization: the query (and its signature) stays.
    while '&amp;' in s:
        s = s.replace('&amp;', '&')
    probe = _SAFE_URL_PROBE_RE.sub('', s).lower()
    return s if probe.startswith(('http://', 'https://')) else ''


def _safe_image_url(v):
    """_safe_ext_url for IMAGE URLs, additionally upgrading http:// to https://.

    Images embed as page resources (<img>, og:image, schema ImageObject),
    where a plain-http URL is mixed content — modern browsers block it
    outright on our https pages, so the image was never going to render
    (CAL-UX-6). Worst case an https-less host breaks an image that was
    already blocked. Plain LINKS (ticket/operator/venue hrefs) stay on
    _safe_ext_url untouched: navigation is not mixed content, and forcing
    https there could break a genuinely http-only site."""
    return re.sub(r'^http://', 'https://', _safe_ext_url(v), flags=re.IGNORECASE)


# Register-passable PLACEHOLDER empty-state lines. Flagged for Daniel.
# Per-city (reserved for the Track B city pages, B.2):
EMPTY_STATE = 'No sound baths on the calendar in {city} this week.'
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
    instances: one honest line of what the section will hold, two redirects
    (calendar + map), and a get-listed seed — never a bare '…on the way.' line
    floating above the footer. The ∿ glyph is retired (CAL-26); CAL-29 brings
    the type-tile empty-state language."""
    return (
        '    <div class="cal-emptystate">\n'
        f'      <p class="cal-emptystate__lead">{_esc(lead)}</p>\n'
        f'      <p class="cal-emptystate__links">'
        f'<a href="{nav_prefix}">Browse this week’s calendar</a> '
        f'<span aria-hidden="true">·</span> '
        f'<a href="{nav_prefix}map/">See the map</a></p>\n'
        '      <p class="cal-emptystate__seed">Run a venue or lead sessions? '
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
    # The event's own page rides in the launch-link details (the TEMPLATE URL
    # has no url param), matching the Thursday digest's googleCalUrl. The .ics
    # carries it as a proper URL property instead — event_ics_input is shared,
    # so the append happens here, never upstream.
    details = f'{ev["description"]}\n\n{ev["url"]}'
    google = 'https://calendar.google.com/calendar/render?' + urlencode({
        'action': 'TEMPLATE',
        'text': ev['title'],
        'dates': f'{start_utc}/{end_utc}',
        'details': details,
        'location': ev['location'],
    })
    outlook = 'https://outlook.live.com/calendar/0/deeplink/compose?' + urlencode({
        'path': '/calendar/action/compose',
        'rru': 'addevent',
        'subject': ev['title'],
        'startdt': iso_start,
        'enddt': iso_end,
        'location': ev['location'],
        'body': details,
    })
    return {'google': google, 'outlook': outlook, 'apple': 'event.ics'}


# ---------------------------------------------------------------------------
# Program Grid cards (CAL-28, ratified 2026-07-25 — replaces the list rows).
# Every session is one card: a committed duotone derivative (scripts/treat.py)
# when one exists, else a TYPE TILE — a designed poster variant, not a
# fallback state. Cards keep the .cal-row class + data-* hooks so filters.js
# binds byte-identical.
# ---------------------------------------------------------------------------

# Slugs with committed card derivatives (img/cards/<slug>-{i,c}.jpg). Set once
# per build (build.py scans img/cards/) — like _LINKED_TAG_PAGES. Empty by
# default, so a caller that doesn't set it renders every session as a tile.
_CARD_ART = set()


def set_card_art(slugs):
    """Register the set of event slugs with committed card art (CAL-28)."""
    global _CARD_ART
    _CARD_ART = set(slugs or ())


def _caption_meta(row, show_date, nav_prefix, city_context=None):
    """The card's one --muted caption line (CAL-28):
    [date ·] time · venue — locality · with practitioner · modality · price.

    - The listing surfaces pass show_date=False — their day band head says
      the date (addendum #5). Entity session lists (show_date=True) lead
      with the compact date, since they have no day bands.
    - city_context drops the city term on its own city page (the neighborhood
      leads there); the root names the city on every card.
    - The modality is the tag-linked caption term (link class survives the
      old kicker; inert span when no tag page exists).
    - Free/Donation rides <b> (--signal-text) — the one text-signal mark.
    """
    parts = []
    if show_date:
        parts.append(_esc(fmt_row_date(row['starts_at'])))
    parts.append(_esc(fmt_time(row['starts_at'])))

    place = row.get('venue') or row.get('operator') or ''
    loc_bits = []
    if row['city'] == 'Denver' and row.get('neighborhood'):
        loc_bits.append(row['neighborhood'])
    if row['city'] != city_context:
        loc_bits.append(row['city'])
    loc = ', '.join(loc_bits)
    if place and loc:
        parts.append(f'{_esc(place)} — {_esc(loc)}')
    elif place or loc:
        parts.append(_esc(place or loc))

    pr = row.get('practitioner') or {}
    if isinstance(pr, dict) and pr.get('slug'):
        parts.append(
            f'<span class="cal-row__with">with <a href="'
            f'{nav_prefix}practitioner/{_esc(pr["slug"])}/">'
            f'{_esc(pr.get("name") or "")}</a></span>')

    mod = row_primary_modality(row)
    if mod:
        _mlabel = _esc(taxonomy.label_for(mod))
        _mpath = _LINKED_TAG_PAGES.get(mod)
        if _mpath:
            parts.append(f'<a class="cal-row__modality" '
                         f'href="{_esc(nav_prefix + _mpath)}">{_mlabel}</a>')
        else:
            parts.append(f'<span class="cal-row__modality">{_mlabel}</span>')

    if row['price']:
        price = _esc(row['price'])
        parts.append(f'<b>{price}</b>' if _is_free_or_donation(row) else price)
    return ' · '.join(parts)


def _caption_icons(row, nav_prefix):
    """Ticket + website access as ICONOGRAPHY (addendum #4 — the worded
    'Tickets · Website' row is dead): line-drawn sprite glyphs in
    currentColor, aria-labeled, 40px hit targets via CSS padding. URLs are
    scheme-checked; unsafe -> no icon. Direct-to-tickets from the listing
    survives — it's the site's pitch."""
    icons = []
    sprite = f'{nav_prefix}img/social-sprite.svg'
    safe = _safe_ext_url(row['ticket_url'])
    if safe:
        icons.append(
            f'<a class="cal-card__ica" href="{_esc(safe)}" target="_blank" '
            f'rel="noopener" aria-label="Tickets — {_esc(row["name"])}">'
            f'<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
            f'<use href="{_esc(sprite)}#icon-ticket"/></svg></a>')
    link_url, link_label = _facil_venue_link(row)
    if link_url:
        icons.append(
            f'<a class="cal-card__ica" href="{_esc(link_url)}" target="_blank" '
            f'rel="noopener" aria-label="{_esc(link_label)} website">'
            f'<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
            f'<use href="{_esc(sprite)}#icon-globe"/></svg></a>')
    if not icons:
        return ''
    return f'<span class="cal-card__acts">{"".join(icons)}</span>'


def _render_row(row, show_date=True, nav_prefix='', geocode=None, now=None,
                city_context=None, eager=False):
    """One Program Grid card (CAL-28). The whole card is one link surface:
    the h3>a name link (crawlable, underlined at rest — addendum #2) stretches
    over the card via CSS ::after, so the image/tile face is clickable
    (addendum #3) with no duplicate anchor and no dead surface. Caption
    sub-links (practitioner, modality, ticket/globe icons) z-lift above it.
    """
    _slugs = row_tag_slugs(row)
    # Filter hooks: area + free/donation (B.5) + tags (CAL-01), read by
    # filters.js. data-tags is a space-joined slug list (empty when untagged).
    data = (f' data-city="{_esc(city_slug(row["city"]))}"'
            f' data-free="{"1" if _is_free_or_donation(row) else "0"}"'
            f' data-tags="{_esc(" ".join(_slugs))}"')
    # CAL-05 near-me sort: venue coordinates from the committed geocode cache
    # (same source as the map). A row whose venue isn't located carries no
    # coords — filters.js sorts it last and gives it no distance chip.
    coord = (geocode or {}).get((row.get('venue') or '').strip())
    if coord:
        data += f' data-lat="{coord["lat"]}" data-lng="{coord["lng"]}"'

    slug = event_slug(row)
    has_art = slug in _CARD_ART
    name_href = f'{nav_prefix}{event_permalink_path(row)}' if slug else ''

    # The crawlable name link — h3 > a[href] in served HTML, always.
    if name_href:
        name_html = (f'<h3 class="cal-row__name">'
                     f'<a href="{_esc(name_href)}">{_esc(row["name"])}</a></h3>')
    else:
        name_html = f'<h3 class="cal-row__name">{_esc(row["name"])}</h3>'

    meta_line = _caption_meta(row, show_date, nav_prefix, city_context)
    icons = _caption_icons(row, nav_prefix)
    # .cal-row__marks is the near-me distance chip's mount point (filters.js
    # setChip appends to it) — the chip lands at the end of the caption line.
    meta_html = (f'<p class="cal-card__meta cal-row__marks">{meta_line}'
                 f'{icons}</p>')

    # Daniel's one-line editorial note — the moat — kept as a caption voice.
    note = editorial_note(row)
    note_html = (f'\n    <p class="cal-row__note">{_esc(note)}</p>'
                 if note else '')

    parts = []
    if has_art:
        p = f'{nav_prefix}img/cards/{slug}'
        parts.append(f'<article class="cal-row cal-card"{data}>')
        # CAL-UX-11: empty alt — the caption carries name/venue, so a
        # descriptive alt would read every event twice. The coral hover layer
        # is a second stacked <img> (pure-CSS crossfade, no JS); both are
        # committed derivatives, so no external CDN can rot them.
        loading = 'eager' if eager else 'lazy'
        parts.append(
            f'  <span class="cal-card__im">'
            f'<img src="{_esc(p)}-i.jpg" '
            f'srcset="{_esc(p)}-i280.jpg 280w, {_esc(p)}-i.jpg 560w" '
            f'sizes="(max-width: 719px) 46vw, (max-width: 1079px) 30vw, 310px" '
            f'width="560" height="560" alt="" loading="{loading}" '
            f'decoding="async">'
            f'<img class="cal-card__im-c" src="{_esc(p)}-c.jpg" '
            f'width="560" height="560" alt="" loading="lazy" '
            f'decoding="async" aria-hidden="true"></span>')
        parts.append('  <span class="cal-card__cap">')
        parts.append(f'    {name_html}')
        parts.append(f'    {meta_html}{note_html}')
        parts.append('  </span>')
    else:
        # Type tile: solid --surface square, name + meta bottom-left — the
        # designed poster for a session with no honest image (imagery law:
        # flyers never stand in for people, stock never attaches to a
        # specific session).
        parts.append(f'<article class="cal-row cal-card cal-card--tile"{data}>')
        parts.append('  <span class="cal-card__tin">')
        parts.append(f'    {name_html}')
        parts.append(f'    {meta_html}{note_html}')
        parts.append('  </span>')
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


def _render_rows(rows, show_date, nav_prefix, geocode=None, now=None):
    """A bare card grid (entity session lists — CAL-28). Not day-banded, so
    the cards carry their dates in the caption (show_date=True there)."""
    inner = '\n'.join(
        _render_row(r, show_date=show_date, nav_prefix=nav_prefix, geocode=geocode, now=now)
        for r in rows)
    return f'<div class="cal-rows cal-rows--3">\n{inner}\n</div>'


def _band_list(rows, now=None):
    """The four temporal bands in fixed order (each present only when it has
    rooms): [(id, label, rows, show_date)]."""
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
    return bands


def day_head_label(d, now=None):
    """The date monument for a day head: 'Saturday, July 25' — plus the year
    only when it differs from the build year (honesty at the Dec/Jan seam)."""
    label = f'{d.strftime("%A")}, {d.strftime("%B")} {_day(d.strftime("%d"))}'
    if now is not None and d.year != _now_utc(now).astimezone(DENVER).year:
        label += f', {d.year}'
    return label


def _sessions_ct(n):
    """'6 sessions' / '1 session' — computed, never typed."""
    return f'{n} session' if n == 1 else f'{n} sessions'


def _day_sections(brows):
    """Group one band's (already chronological) rows by Denver-local date:
    [(date, rows)] — the Program Grid's day monuments."""
    out = []
    for r in brows:
        d = _denver(r['starts_at']).date()
        if out and out[-1][0] == d:
            out[-1][1].append(r)
        else:
            out.append((d, [r]))
    return out


def _grid_class(n, live=False):
    """Grid density, computed from the day's count (CAL-28): the live day is
    3-up; a 2-session day runs featured 2-up (44px names); a dense day (>=7)
    runs 4-up; everything else 3-up."""
    if live:
        return 'cal-rows cal-rows--3'
    if n == 2:
        return 'cal-rows cal-rows--2'
    if n >= 7:
        return 'cal-rows cal-rows--4'
    return 'cal-rows cal-rows--3'


def _render_day(d, drows, live, label, nav_prefix, geocode, now,
                city_context=None, eager_first=0):
    """One day section: the date-monument head (h2 + computed count) over its
    card grid. The LIVE day (Today/Tonight) gets the white-on-coral slab head
    — the signal budget's second sanctioned slab (ticker + live head ONLY) —
    and its count line carries the full date (addendum #5), since its cards
    omit per-card dates. Other days: 2px ink rule, date as the h2 itself."""
    if live:
        head_h2, ct = label, f'{day_head_label(d, now)} · {_sessions_ct(len(drows))}'
    else:
        head_h2, ct = day_head_label(d, now), _sessions_ct(len(drows))
    cards = '\n'.join(
        _render_row(r, show_date=False, nav_prefix=nav_prefix, geocode=geocode,
                    now=now, city_context=city_context, eager=(i < eager_first))
        for i, r in enumerate(drows))
    return '\n'.join([
        f'  <div class="cal-day{" cal-day--live" if live else ""}">',
        '    <div class="cal-day__head">',
        f'      <h2 class="cal-band__h2">{_esc(head_h2)}</h2>',
        f'      <span class="cal-day__ct">{_esc(ct)}</span>',
        '    </div>',
        f'    <div class="{_grid_class(len(drows), live)}">',
        cards,
        '    </div>',
        '  </div>',
    ])


def render_editorial_band(nav_prefix):
    """The full-width what-to-expect editorial band (CAL-28): treated stock
    (generic-editorial only — never attached to a specific session), duotone
    at rest crossfading coral on hover, linking the first-timer explainer.
    Derivatives are committed by scripts/treat.py."""
    p = f'{nav_prefix}img/cards/editorial-what-to-expect'
    return '\n'.join([
        f'<a class="cal-edband" href="{nav_prefix}what-to-expect/">',
        f'  <span class="cal-edband__im">'
        f'<img src="{p}-i.jpg" width="1300" height="406" alt="" '
        f'loading="lazy" decoding="async">'
        f'<img class="cal-card__im-c" src="{p}-c.jpg" width="1300" '
        f'height="406" alt="" loading="lazy" decoding="async" '
        f'aria-hidden="true"></span>',
        '  <span class="cal-edband__cap">'
        '<span class="cal-edband__t">First time? What to expect '
        'at a sound bath</span>'
        '<span class="cal-edband__arrow" aria-hidden="true">&rarr;</span>'
        '</span>',
        '</a>',
    ])


def _render_bands(rows, nav_prefix='', now=None, geocode=None,
                  include_jump=True, include_faq=True, editorial=False,
                  city_context=None):
    """The Program Grid (CAL-28): the four temporal bands survive as the IA —
    each `section.cal-band` wrapper keeps its id and renders only when it has
    sessions, so the CAL-16 jump/filter chips and filters.js keep working
    byte-identical (rows record the temporal band id) — but the VISIBLE
    structure inside is per-day date monuments, each over its own card grid.
    The wrappers themselves draw no head; the day heads are the page's H2s,
    in fixed chronological order, rendered only when non-empty.

    include_jump/include_faq as before (rail vs inline callers). editorial=True
    (root + city) inserts the what-to-expect band after the wrapper that
    completes the second day monument — 'after the second or third calendar
    band'. city_context drops the city term in captions on its own page."""
    bands = _band_list(rows, now)

    out = []

    if include_jump:
        out.append(render_jump(rows, now, include_faq=include_faq))

    if not bands:
        out.append(f'<p class="cal-empty cal-empty--all">{_esc(ALL_EMPTY)}</p>')

    editorial_pending = editorial
    days_done = 0
    for bid, label, brows, _show_date in bands:
        out.append(f'<section class="cal-band" id="{bid}">')
        live = (bid == 'today')
        for j, (d, drows) in enumerate(_day_sections(brows)):
            # The live band's first cards are the likely LCP — fetch eagerly.
            eager_first = 3 if (live and days_done == 0) else 0
            out.append(_render_day(
                d, drows, live, label, nav_prefix, geocode, now,
                city_context=city_context, eager_first=eager_first))
            days_done += 1
        out.append('</section>')
        if editorial_pending and days_done >= 2:
            out.append(render_editorial_band(nav_prefix))
            editorial_pending = False
    if editorial_pending and bands:
        out.append(render_editorial_band(nav_prefix))

    return '\n'.join(out)


def render_ticker(rows, now=None):
    """The coral broadcast ticker (CAL-28 — root + city pages): tonight's
    real sessions from the same cal_rows the bands render, as a pure-CSS
    ~70s loop (content duplicated 2x for seamlessness). aria-hidden — it
    duplicates the live band. Static under prefers-reduced-motion (CSS).
    An empty tonight shows the next day's computed date line instead —
    honest, never fabricated. Returns '' when the calendar is empty."""
    now = _now_utc(now)
    today_b, weekend_b, week_b, ahead_b = band_assignments(rows, now)
    if today_b:
        segs = [today_band_label(today_b, now)]
        for r in today_b:
            t = fmt_time(r['starts_at']).replace(' AM', '').replace(' PM', '')
            if r['city'] == 'Denver' and r.get('neighborhood'):
                loc = r['neighborhood']
            else:
                loc = r['city']
            seg = f'{r["name"]} {t} {loc}'
            price = (r.get('price') or '').strip()
            if price and len(price) <= 9:
                seg += f' {price}'
            segs.append(seg)
    else:
        nxt = weekend_b or week_b or ahead_b
        if not nxt:
            return ''
        d, drows = _day_sections(nxt)[0]
        segs = ['Next', f'{day_head_label(d, now)} · {_sessions_ct(len(drows))}']
    text = _esc('  /  '.join(segs) + '  /  ')
    return (f'<div class="cal-ticker" aria-hidden="true">'
            f'<div class="cal-ticker__in"><span>{text}</span>'
            f'<span>{text}</span></div></div>')


def render_jump(rows, now=None, include_faq=True):
    """The WHEN dial (CAL-38): the temporal jump-nav as a segmented strip —
    only the bands that exist, plus the FAQ. Each band cell carries its
    build-time census (len of the band's rows) as a muted tabular count —
    the same honest numbers the summary speaks. The counts are STATIC by
    design: filters.js is frozen, so an active area filter does not shrink
    them (decision of record, CAL-38 D3). With JS, filters.js upgrades each
    data-band anchor into a toggleable band FILTER chip (CAL-16; pressed =
    ink fill — cells are full blocks, so state changes shift nothing);
    without JS they stay plain jump anchors. The FAQ link carries no
    data-band and no count, so it always just jumps — which is why
    include_faq=False exists: on a page with no FAQ section that cell
    would be a dead anchor dressed like its working siblings. Standalone
    since CAL-23 phase B, so the rail can hold it beside the list."""
    out = ['<nav class="cal-jump" aria-label="Jump to a time">']
    for bid, label, brows, _sd in _band_list(rows, now):
        out.append(f'  <a href="#{bid}" data-band="{bid}">{_esc(label)}'
                   f' <span class="cal-jump__ct">{len(brows)}</span></a>')
    if include_faq:
        out.append('  <a href="#faq">FAQ</a>')
    out.append('</nav>')
    return '\n'.join(out)


def render_rail_links(nav_prefix, ics_filename, feed_path):
    """The standing links as TWO quiet lines of reference furniture (CAL-38,
    collapsing the old link wall; every CAL-23/UX-4/UX-9 href survives):
    a SUBSCRIBE line (webcal for Apple, add-by-URL for Google Calendar —
    which silently fails on webcal — the raw .ics, RSS) and a MORE line
    (map · digest · what-to-expect). Muted caps lead-ins, ink links bare
    at rest. Server-rendered, JS-free — never dead chrome without JS."""
    sep = '<span class="cal-rail__sep" aria-hidden="true">·</span>'
    return '\n'.join([
        '<div class="cal-rail__links">',
        '  <span class="cal-rail__line">'
        '<span class="cal-rail__subhead">Subscribe</span> '
        f'<a href="{ics_webcal_url(ics_filename)}">Apple / webcal</a> {sep} '
        f'<a href="{gcal_subscribe_url(ics_filename)}">Google Calendar</a> {sep} '
        f'<a href="{ics_https_url(ics_filename)}">Download .ics</a> {sep} '
        f'<a href="{nav_prefix}{feed_path}">RSS</a>'
        '</span>',
        '  <span class="cal-rail__line">'
        '<span class="cal-rail__subhead">More</span> '
        f'<a href="{nav_prefix}map/">See the map</a> {sep} '
        f'<a href="#digest">Get the Thursday digest</a> {sep} '
        f'<a href="{nav_prefix}what-to-expect/">'
        'New to sound baths? What to expect</a>'
        '</span>',
        '</div>',
    ])


# Register-passable PLACEHOLDER no-results line (B.5 filters). Flagged for Daniel.
NO_RESULTS = 'No sessions match those filters.'


def render_filters(rows=None, include_city=True):
    """The refine deck (B.5 + CAL-01, redesigned CAL-38): area (root/tag) +
    free/donation + near-me + tags + clear, inside a native <details> whose
    48px summary is the deck's engraved name, FILTER + SORT. Ships `open`
    (so the deck rides expanded wherever the summary is hidden or static);
    the base-layout script drops `open` under 640px at load — the mobile
    stack starts collapsed with zero changes to filters.js. Still `hidden`
    until filters.js reveals it, so no-JS visitors see every row and the
    page is fully usable — the details never matters without JS. The tag
    facet only offers tags actually present in `rows` (never a filter that
    would match nothing), grouped by axis. Checkboxes stay NATIVE inputs
    (visually hidden inside their chip labels; checked state paints via
    :has in styles.css) so every filters.js binding and the browser's own
    keyboard/AT semantics survive untouched. PLACEHOLDER copy, flagged."""
    out = ['<details class="cal-filters" data-cal-filters hidden open>']
    # The caret span is decorative; open/closed state is native semantics.
    out.append('  <summary><span class="cal-filters__summary">Filter + sort'
               '<span class="cal-filters__caret" aria-hidden="true"></span>'
               '</span></summary>')
    out.append('  <div class="cal-filters__primary">')
    if include_city:
        opts = ['<option value="">All areas</option>']
        opts += [f'<option value="{_esc(city_slug(c))}">{_esc(c)}</option>'
                 for c in CITIES]
        # The engraved AREA label is aria-hidden; the select carries the
        # full name for AT (CAL-38 a11y note — was a visually-hidden span).
        out.append('    <label class="cal-filters__field">')
        out.append('      <span class="cal-filters__flab" aria-hidden="true">'
                   'Area</span>')
        out.append('      <select data-filter-city aria-label="Filter by area">'
                   + ''.join(opts) + '</select>')
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
    # CAL-UX-10 clear-all at the deck's foot — after the facets it resets
    # (CAL-38 D1). Ships hidden; filters.js reveals it only while any filter
    # (or the near-me sort) is active.
    out.append('  <button type="button" class="cal-filters__clear" '
               'data-filter-clear hidden>Clear filters</button>')
    out.append('</details>')
    return '\n'.join(out)


def _render_noresults():
    """The 'nothing matches your filters' line — hidden until filters.js shows
    it. role=status + aria-live so the reveal is ANNOUNCED to screen readers,
    not just shown (CAL-UX-10); present from load so the region registers."""
    return ('<p class="cal-empty" data-cal-noresults role="status" '
            f'aria-live="polite" hidden>{_esc(NO_RESULTS)}</p>')


def render_calendar_body(rows, nav_prefix='', now=None, geocode=None):
    """The dynamic middle of the root: the CAL-23 rail/list split (sticky
    utility rail — filters + jump chips + standing links — beside the band
    list at >=1200px; a single stack below), then the full-width FAQ. Static
    scaffold (H1, stamp, summary, digest, submission line) lives in the
    section file; this returns everything that depends on the feed."""
    # FAQ — a GEO/AIO citation surface (FAQPage JSON-LD emitted by build.py).
    return '\n'.join([
        '<div class="cal-split">',
        '<aside class="cal-rail"><div class="cal-rail__inner">',
        # CAL-38 D1: the WHEN dial leads; the refine deck follows; furniture
        # last. filters.js is order-agnostic (selector-bound).
        render_jump(rows, now),
        render_filters(rows, include_city=True),
        render_rail_links(nav_prefix, 'front-range.ics', 'feed.xml'),
        '</div></aside>',
        '<div class="cal-list">',
        _render_bands(rows, nav_prefix, now, geocode, include_jump=False,
                      editorial=True),
        _render_noresults(),
        '</div>',
        '</div>',
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
        # CAL-15: "Free (donations appreciated)" IS free — admission stated
        # free, donation parenthetical. "Free-will donation" is NOT (that's
        # pay-what-you-want, price unknown), so the donation guard stands
        # unless the string literally opens "Free (".
        is_free = bool(_FREE_RE.search(price)) and (
            not _DONATION_RE.search(price)
            or bool(re.match(r'free\s*\(', price, re.I)))
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
    schema.org defines it; price:0 already says free here.
    availability (CAL-15): InStock only when we link live tickets — the link
    already asserts availability; rows without a ticket url stay silent rather
    than guess (same stance as price)."""
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
        offer['availability'] = 'https://schema.org/InStock'
    # CAL-15: validFrom = when the pull first surfaced the listing — the honest
    # "tickets observed on sale since" claim (never the true on-sale date,
    # which we don't know).
    if row.get('first_seen_at'):
        offer['validFrom'] = row['first_seen_at']
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
        ev = _external_event(row, site_url)
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

# CAL-22 warm bands: per-city strip under img/warm/<slug>-{800,1600}.jpg
# (generated LOCALLY by scripts/warm.py from the OG-card stock; committed).
# Alt text describes only what the photograph shows — it is stock, not a
# Front Range room, so it never claims a place.
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
                  'ticket link goes straight to the organizer.'),
        },
        {
            'q': 'What should I bring to a sound bath?',
            'a': ('Wear clothes you can lie down in. Many rooms provide mats, '
                  'bolsters, and blankets, though your own blanket, a pillow, and '
                  'water are never wrong. When in doubt, ask the organizer what '
                  'the room supplies.'),
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


# CAL-18: how many sessions the digest preview shows before the fade. Small on
# purpose — the preview is a glimpse of the email, not a second calendar.
_PREVIEW_MAX_ROWS = 3


def _digest_preview_meta(row):
    """operator · venue · price as escaped HTML, de-duplicated — mirrors
    renderDigestEventRow in digest.ts, sameEntity fold included: operator and
    venue are frequently the same entity in the feed — the same string, or one
    name under a legal suffix ("X" vs "X LLC", _same_entity) — and printing it
    twice is a display defect, not an extra fact. Free/Donation prices ride the
    coral text mark exactly as the email's do (CAL-37). §2.7 requires the
    preview to show the actual email, so both stay in lockstep with the email
    side's logic."""
    parts = []
    for part in (row.get('operator'), row.get('venue')):
        t = (part or '').strip()
        if t and not any(_same_entity(t, p) for p in parts):
            parts.append(t)
    parts = [_esc(p) for p in parts]
    price = (row.get('price') or '').strip()
    if price:
        marked = (f'<b class="digest-preview__free">{_esc(price)}</b>'
                  if _is_free_or_donation(row) else _esc(price))
        parts.append(marked)
    return ' · '.join(parts)


def render_digest_preview(rows, now=None):
    """A REAL mini-preview of this week's Thursday digest (CAL-18), rendered at
    build time from the same rows the calendar shows — the v5 Broadcast email
    (soundbathcalendar-admin digest.ts, CAL-37) recreated at reduced scale in
    site CSS: the email's own committed ground inside a 2px ink frame, caps day
    monuments with computed counts, the first few sessions, then a soft fade
    and an honest count of the rest. An empty week renders the email's actual
    empty state — never fabricated events. The frame is a picture of the email
    (aria-hidden; the figcaption carries the meaning), so nothing inside it
    links or duplicates the page's interactive list."""
    week = week_rows(rows, now)
    shown = week[:_PREVIEW_MAX_ROWS]
    remaining = len(week) - len(shown)
    # Reserve the thumbnail column for the whole preview when any shown session
    # has an image — the email's showThumb rule, so text columns share an edge.
    show_thumb = any(r.get('image_url') for r in shown)
    # Per-day session counts over the FULL week — the counts the email itself
    # prints on its day monuments (computed, never typed), regardless of where
    # the preview's fade cuts off.
    day_counts = {}
    for r in week:
        k = _denver(r['starts_at']).strftime('%Y-%m-%d')
        day_counts[k] = day_counts.get(k, 0) + 1

    out = ['<figure class="digest-preview">',
           '      <figcaption class="digest-preview__caption">This is what lands '
           'in your inbox Thursday.</figcaption>',
           '      <div class="digest-preview__frame" aria-hidden="true">',
           '        <div class="digest-preview__sheet">',
           '          <span class="digest-preview__brand">Sound Bath Calendar</span>']

    if not shown:
        out.append('          <p class="digest-preview__h1 digest-preview__h1--empty">'
                   'No sound baths are on the Front Range calendar for the next '
                   'seven days yet.</p>')
    else:
        out.append('          <p class="digest-preview__h1">This week&rsquo;s sound '
                   'baths on the Front Range</p>')
        # The email's answer-first summary line: computed count + the cities
        # actually on the list (digestSummaryHtml in digest.ts).
        cities = []
        for r in week:
            c = (r.get('city') or '').strip()
            if c and c not in cities:
                cities.append(c)
        n = len(week)
        count = f'<b>{n} session{"" if n == 1 else "s"}</b>'
        if cities:
            listed = (', '.join(cities) if len(cities) <= 3
                      else ', '.join(cities[:3]) + ' and more')
            out.append(f'          <p class="digest-preview__sum">{count} &mdash; '
                       f'{_esc(listed)}.</p>')
        else:
            out.append(f'          <p class="digest-preview__sum">{count}.</p>')
        current_day = None
        for r in shown:
            ts = r['starts_at']
            d = _denver(ts)
            day_key = d.strftime('%Y-%m-%d')
            if day_key != current_day:
                ct = day_counts[day_key]
                out.append('          <div class="digest-preview__day">')
                out.append(f'            <span class="digest-preview__daylabel">'
                           f'{_esc(d.strftime("%A"))}, {_esc(d.strftime("%B"))} '
                           f'{_day(d.strftime("%d"))}</span>')
                out.append(f'            <span class="digest-preview__dayct">'
                           f'{ct} session{"" if ct == 1 else "s"}</span>')
                out.append('          </div>')
                current_day = day_key
            thumb = ''
            if show_thumb:
                u = r.get('image_url') or ''
                thumb = (f'<span class="digest-preview__thumb">'
                         f'<img src="{_esc(u)}" alt="" loading="lazy" '
                         f'referrerpolicy="no-referrer"></span>'
                         if u else
                         '<span class="digest-preview__thumb digest-preview__thumb--empty"></span>')
            city = (r.get('city') or '').strip()
            chip = (f'<span class="digest-preview__city">{_esc(city)}</span>'
                    if city else '')
            out.append('          <div class="digest-preview__row">')
            out.append(f'            <span class="digest-preview__time">{_esc(fmt_time(ts))}</span>')
            if thumb:
                out.append(f'            {thumb}')
            out.append('            <span class="digest-preview__text">')
            if chip:
                out.append(f'              {chip}')
            out.append(f'              <span class="digest-preview__name">{_esc(r.get("name", ""))}</span>')
            meta = _digest_preview_meta(r)
            if meta:
                out.append(f'              <span class="digest-preview__meta">{meta}</span>')
            out.append('            </span>')
            out.append('          </div>')
        if remaining > 0:
            noun = 'sound bath' if remaining == 1 else 'sound baths'
            out.append(f'          <p class="digest-preview__more">&hellip;and '
                       f'{remaining} more {noun} in Thursday&rsquo;s email</p>')

    out.append('        </div>')
    out.append('      </div>')
    out.append('    </figure>')
    return '\n'.join(out)


def render_digest_block(selected_city='all', rows=None, now=None):
    """The Thursday-digest signup section (CAL-18): the pitch + capture form,
    paired with a live build-time preview of this week's actual email when
    `rows` is given. The form seam is unchanged from Track C — a plain POST to
    the events service /digest/subscribe + 303 redirect back to /thanks/; the
    service sets the list flag + area and source server-side. One area is
    preselected. Used by the root (via the <!-- DIGEST_BLOCK --> marker in
    sections/01-content.html), the city pages, and the tag pages."""
    opts = [('all', 'Everywhere on the Front Range')]
    opts += [(city_slug(c), c) for c in CITIES]
    option_html = '\n'.join(
        f'          <option value="{v}"{" selected" if v == selected_city else ""}>'
        f'{_esc(label)}</option>'
        for v, label in opts
    )
    preview = render_digest_preview(rows, now) if rows is not None else ''
    preview_html = f'\n    {preview}' if preview else ''
    return f'''<div class="digest-block" id="digest">
    <div class="digest-pitch">
      <span class="eyebrow">The digest</span>
      <h2 class="digest-h2">The week&rsquo;s sound baths, Thursday mornings.</h2>
      <!-- HUMAN REVIEW -->
      <p class="form-note">One email a week: every sound bath on the Front Range
      calendar for the seven days ahead, grouped by day. Unsubscribe any time.</p>
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
    </div>{preview_html}
    </div>'''


def render_city_page(rows, city, nav_prefix, now=None, geocode=None):
    """The <main> body for one city page (Program Grid, CAL-28): ticker ·
    crumb · H1 · summary · stamp · the day-banded card grid (this city only) ·
    other-areas nav · city FAQ · digest · submission line. The CAL-22 warm
    band is retired on listing surfaces — the editorial what-to-expect band
    (treated stock, mid-program) is the sanctioned image band now."""
    now = _now_utc(now)
    crows = city_rows(rows, city)
    slug = city_slug(city)
    out = []
    # The ticker is full-bleed chrome — it sits above the padded section.
    ticker = render_ticker(crows, now)
    if ticker:
        out.append(ticker)
    out += ['<section class="section section--light cal-main">', '  <div class="container">']

    out.append('    <nav class="cal-crumbs" aria-label="Breadcrumb">')
    out.append(f'      <a href="{nav_prefix}">Calendar</a> <span aria-hidden="true">/</span> '
               f'<span>{_esc(city)}</span>')
    out.append('    </nav>')

    # The identity block (v5: left-set monument; the CAL-23 centering is
    # retired by the comp). Order per the comp: H1 · summary · stamp.
    out.append('    <div class="cal-hero">')
    out.append(f'    <h1 class="cal-h1">{_esc(CITY_H1[city])}</h1>')
    out.append(f'    <p class="cal-summary" id="cal-summary">'
               f'{summary_html(build_city_summary_sentence(rows, city, now))}</p>')
    out.append(f'    <p class="cal-updated">Last updated {_esc(fmt_stamp_date(now))}.</p>')
    out.append('    </div>')

    # CAL-23 rail/list split. City is fixed here, so the bar carries the
    # free/donation chip + the tags present in this city; the subscribe links
    # (formerly in the hero) live in the rail with the map/digest links.
    # city_context drops the city term in captions (the neighborhood leads).
    out.append('    <div class="cal-split">')
    out.append('    <aside class="cal-rail"><div class="cal-rail__inner">')
    # CAL-38 D1 order: dial, then deck, then furniture.
    out.append('    ' + render_jump(crows, now))
    out.append('    ' + render_filters(crows, include_city=False))
    out.append('    ' + render_rail_links(nav_prefix, f'{slug}.ics',
                                          f'{slug}/feed.xml'))
    out.append('    </div></aside>')
    out.append('    <div class="cal-list">')
    out.append('    ' + _render_bands(crows, nav_prefix, now, geocode,
                                      include_jump=False, editorial=True,
                                      city_context=city))
    out.append('    ' + _render_noresults())
    out.append('    </div>')
    out.append('    </div>')
    out.append('    ' + render_city_switcher(city, nav_prefix))
    out.append('    ' + _render_faq(city_faq(city)))
    out.append('    ' + render_digest_block(selected_city=slug, rows=rows, now=now))

    out.append('    <p class="cal-submit">Running sessions, or have a space that '
               f'could host one? <a href="{nav_prefix}submit/">Add to the calendar.</a></p>')

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
        ev = _external_event(row, site_url)
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
    at the event's own permalink page; the ticket link rides in DESCRIPTION."""
    start = parse_iso(row['starts_at'])
    end = start + timedelta(minutes=ICS_DEFAULT_DURATION_MIN)
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


def gcal_subscribe_url(ics_filename):
    """Google Calendar add-by-URL subscribe link (CAL-UX-4). Google Calendar
    and Android silently fail on a bare webcal:// href — the pattern Google
    honors is its own /calendar/r page with the whole webcal URL, percent-
    encoded, as cid=."""
    return ('https://calendar.google.com/calendar/r?cid='
            + quote(ics_webcal_url(ics_filename), safe=''))


def render_ics_subscribe(ics_filename):
    """The subscribe + download line for a root or city page. PLACEHOLDER copy.
    (Unused since the CAL-23 rail took over; kept in step with it — three
    options, not webcal-only — so a revival doesn't strand Google users.)"""
    return (
        '<p class="cal-ics">'
        f'<a class="cal-ics__sub" href="{ics_webcal_url(ics_filename)}">'
        'Apple / webcal</a> '
        f'<a class="cal-ics__sub" href="{gcal_subscribe_url(ics_filename)}">'
        'Google Calendar</a> '
        f'<a class="cal-ics__dl" href="{ics_https_url(ics_filename)}">'
        'Download .ics</a></p>'
    )


# ---------------------------------------------------------------------------
# Per-event permalink page (/calendar/event/<slug>/) — the body HTML. Page
# assembly (base layout, <head>, schema) is build.py's job; this returns the
# <main> content only, consonant with the section-file pipeline.
# ---------------------------------------------------------------------------

# <title> budget for event permalinks (CAL-SEO-5). SERPs display ~60 chars and
# operator listing names regularly blow past it, so the NAME — never the H1 or
# the Event schema name — is cut at a word boundary to keep the whole tag
# inside the budget. Geography rides the meta description, not the title.
EVENT_TITLE_MAX = 65


def event_title_tag(name, site_name):
    """'{name} | {site_name}' for an event permalink <title>: the full name
    when the composition fits EVENT_TITLE_MAX, else the name cut at a word
    boundary + '…'. Measures the raw string — the caller HTML-escapes."""
    full = f'{name} | {site_name}'
    if len(full) <= EVENT_TITLE_MAX:
        return full
    budget = EVENT_TITLE_MAX - len(f'… | {site_name}')
    prefix = name[:budget + 1]
    cut = prefix[:prefix.rfind(' ')] if ' ' in prefix else name[:budget]
    # A cut can land after joiner punctuation ('Sound Bath &') — drop it.
    cut = cut.rstrip(' ·-–—,.:;&+|/') or name[:budget].rstrip()
    return f'{cut}… | {site_name}'


# Inline style for event pages (they have no _src/pages dir, so no style.css is
# injected). Design tokens come from the sitewide styles.css every page loads.
EVENT_PAGE_STYLE = """<style>
    .cal-past-banner { background: rgba(var(--ink-rgb),0.05); border-left: 3px solid rgba(var(--ink-rgb),0.4); padding: 0.9rem 1.2rem; margin: 0 0 2rem; font-size: 0.95rem; }
    .cal-past-banner a { color: var(--ink); text-decoration: underline; text-underline-offset: 3px; }
    /* Event-page overrides of the shared .detail__* vocabulary (styles.css,
       CAL-31): roomier H1 + a facts grid that breathes wider than the entity
       aside default. The base gap override would also win over the shared
       stylesheet's mobile stack (same specificity, later in cascade), so the
       media requery restates the tight mobile gap. */
    .detail__h1 { margin: 0.4rem 0 1.4rem; }
    .detail__facts { gap: 0.6rem 1.6rem; margin: 2rem 0; max-width: 40rem; }
    @media (max-width: 640px) { .detail__facts { gap: 0.2rem; } }
    .cal-event__desc { font-size: 1.15rem; line-height: 1.6; max-width: 42rem; color: var(--ink); margin: 0 0 1rem; }
    .cal-event__note { font: 500 1.2rem var(--font-display); color: var(--ink); max-width: 40rem; line-height: 1.4; margin: 0 0 1.6rem; }
    .cal-event__figure { margin: 2rem 0; max-width: 640px; }
    .cal-event__figure img { width: 100%; aspect-ratio: 3 / 2; object-fit: cover; display: block; background: rgba(var(--ink-rgb),0.06); }
    .cal-event__figure figcaption { font-size: 0.82rem; color: var(--muted); margin-top: 0.6rem; }
    .cal-event__cta { display: flex; flex-wrap: wrap; gap: 1rem 1.6rem; align-items: center; margin: 2rem 0; }
    .cal-event__link { color: var(--ink); font: 600 0.9rem var(--font-body); text-decoration: none; }
    .cal-event__link:hover { text-decoration: underline; }
    .cal-event__firsttime { margin: 1.4rem 0 0; font-size: 0.88rem; color: var(--muted); }
  </style>"""


def render_event_page(row, nav_prefix, site_url, now=None):
    """The <main> content for one external event's permalink page."""
    now = _now_utc(now)
    is_past = parse_iso(row['starts_at']) <= now
    esc = _esc
    out = ['<section class="section section--light cal-event">', '  <div class="container">']

    # Breadcrumb (visible) — mirrors the BreadcrumbList schema build.py emits.
    # [port] The calendar IS the home page here, so the trail is Calendar >
    # {City} > Event, the city level linking its city page — present only when
    # the row's city is canonical, so schema and crumbs agree (CAL-SEO-9).
    out.append('    <nav class="detail__crumbs" aria-label="Breadcrumb">')
    crumb = (f'      <a href="{nav_prefix}">Calendar</a> '
             '<span aria-hidden="true">/</span> ')
    if row['city'] in CITIES:
        crumb += (f'<a href="{nav_prefix}{city_page_path(row["city"])}">'
                  f'{esc(row["city"])}</a> <span aria-hidden="true">/</span> ')
    crumb += f'<span>{esc(row["name"])}</span>'
    out.append(crumb)
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
    out.append(f'    <h1 class="detail__h1">{esc(row["name"])}</h1>')

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
            f'loading="lazy" decoding="async" referrerpolicy="no-referrer">')
        out.append(f'      <figcaption>{esc(alt_text(row))}</figcaption>')
        out.append('    </figure>')

    # End the reading column; open the sticky decision aside + card.
    out.append('      </div>')  # .detail-main
    out.append('      <aside class="detail-aside">')
    out.append('        <div class="detail-card">')

    # Facts block
    out.append('    <dl class="detail__facts">')
    out.append(
        f'      <dt>When</dt><dd>{esc(datetime_fmt.fmt_date_long(row["starts_at"]))} '
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
            f'      <dt>Organizer</dt><dd><a class="cal-event__link" '
            f'href="{esc(orf_href)}">{esc(orf.get("name") or row.get("operator") or "")}</a></dd>')
    elif row.get('operator'):
        out.append(f'      <dt>Organizer</dt><dd>{esc(row["operator"])}</dd>')
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

    # First-timer doorway (CAL-UX-9): a quiet line beside the ticket links
    # into the learn layer — the decision card answers "what am I walking
    # into?" as well as "how do I go?".
    out.append(
        f'    <p class="cal-event__firsttime">First time? '
        f'<a class="cal-event__link" href="{nav_prefix}what-to-expect/">'
        'Read what to expect</a></p>')

    out.append('        </div>')  # .detail-card
    out.append('      </aside>')  # .detail-aside
    out.append('    </div>')      # .detail-shell

    out.append(
        f'    <p class="detail__back"><a href="{nav_prefix}">'
        'Part of the Front Range calendar →</a></p>')

    out.append('  </div>')
    out.append('</section>')
    return '\n'.join(out)


def approved_event_rows(cal_feed, now=None):
    """Rows for EVERY approved event — past and future — deduped by permalink
    slug. Drives the permalink-page pipeline (future pages are indexed + in the
    sitemap; past pages stay live but noindex + out of it).
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
