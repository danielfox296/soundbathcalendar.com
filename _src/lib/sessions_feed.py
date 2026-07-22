"""Sessions feed loader + helpers for build.py.

SOUND BATH CALENDAR fork (2026-07-19 port): trimmed to what the calendar
needs — the feed loader (Firstwater rows on the calendar come from this
feed), the America/Denver date formatting shared with external_events, and
the Event JSON-LD builder. The session-page HTML rendering (checkout forms,
blog-chrome stripping) stays on the artist site and is not carried here.

The events service publishes a JSON feed of dated sessions. At build time we:
  1. fetch the feed (env SESSIONS_FEED_URL, default: live service),
  2. validate its shape and write it to data/sessions-cache.json
     (committed, deterministic formatting) so every future build has
     a known-good copy,
  3. on ANY fetch/parse/validation failure: warn and fall back to the
     committed cache. A broken build is never acceptable.

Test fixture path: set SESSIONS_FEED_FILE=/abs/path/to/fixture.json to
build against a local file. Fixture builds NEVER write the cache, so
fixture data cannot leak into the committed cache or subsequent builds.
(A file:// SESSIONS_FEED_URL also works and also never writes the cache:
only http(s) fetches update it.)

Stdlib only — no new dependencies.

FEED CONTRACT (GET {SESSIONS_FEED_URL}):
{ "generated_at": "...", "sessions": [ {
    "id","event_slug","starts_at","ends_at","doors_at",
    "status": "on_sale|sold_out|scheduled|completed",
    "remaining", "waitlist_open",
    "venue": {"name","address","lat","lng"},
    "tiers": [{"id","name","mode":"fixed|sliding","amount",
               "min_amount","suggested_amount"}],
    "checkout_url", "waitlist_url" } ] }
Timestamps ISO-8601 with offset; amounts in cents.
The checkout endpoint expects a POST; we render a form with a
`tier_id` field naming the chosen tier.
"""

import json
import os
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

DEFAULT_FEED_URL = 'https://ss-service-production.up.railway.app/feeds/sessions.json'
CACHE_REL_PATH = os.path.join('data', 'sessions-cache.json')
FETCH_TIMEOUT_S = 10
DENVER = ZoneInfo('America/Denver')

# Statuses that render as Firstwater rows on the calendar (same set the
# session pages display).
DISPLAY_STATUSES = ('on_sale', 'sold_out', 'scheduled')

_SCHEMA_AVAILABILITY = {
    'on_sale': 'https://schema.org/InStock',
    'sold_out': 'https://schema.org/SoldOut',
    'scheduled': 'https://schema.org/PreOrder',
}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def parse_iso(ts):
    """Parse an ISO-8601 timestamp (offset or trailing Z) to aware datetime."""
    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError(f'timestamp missing offset: {ts!r}')
    return dt


def empty_feed():
    return {'generated_at': None, 'sessions': []}


def validate_feed(feed):
    """Shape-check a parsed feed. Raises ValueError on any problem."""
    if not isinstance(feed, dict):
        raise ValueError('feed root is not an object')
    if not isinstance(feed.get('sessions'), list):
        raise ValueError('feed.sessions is not a list')
    for i, s in enumerate(feed['sessions']):
        where = f'sessions[{i}]'
        if not isinstance(s, dict):
            raise ValueError(f'{where} is not an object')
        for key in ('id', 'event_slug', 'starts_at', 'status'):
            if not isinstance(s.get(key), str) or not s[key]:
                raise ValueError(f'{where}.{key} missing or not a string')
        parse_iso(s['starts_at'])
        for key in ('ends_at', 'doors_at'):
            if s.get(key):
                parse_iso(s[key])
        if not isinstance(s.get('venue'), dict):
            raise ValueError(f'{where}.venue is not an object')
        if not isinstance(s.get('tiers'), list):
            raise ValueError(f'{where}.tiers is not a list')
        for j, t in enumerate(s['tiers']):
            if not isinstance(t, dict):
                raise ValueError(f'{where}.tiers[{j}] is not an object')
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
        log(f'  ⚠ sessions cache unusable ({exc.__class__.__name__}: {exc}) — building with no sessions')
        return empty_feed()


def load_feed(repo_root, log=print):
    """Return the sessions feed dict, never raising.

    Order of precedence:
      SESSIONS_FEED_FILE (local fixture, cache untouched)
      > SESSIONS_FEED_URL fetch (http(s) success refreshes the cache)
      > committed data/sessions-cache.json
      > empty feed.
    """
    cache_path = os.path.join(repo_root, CACHE_REL_PATH)

    fixture = os.environ.get('SESSIONS_FEED_FILE')
    if fixture:
        try:
            with open(fixture, 'r', encoding='utf-8') as f:
                feed = validate_feed(json.load(f))
            log(f'  ✓ sessions feed from fixture {fixture} ({len(feed["sessions"])} session(s); cache untouched)')
            return feed
        except Exception as exc:
            log(f'  ⚠ SESSIONS_FEED_FILE unusable ({exc.__class__.__name__}: {exc}) — using committed cache')
            return _load_cache(cache_path, log)

    url = os.environ.get('SESSIONS_FEED_URL', DEFAULT_FEED_URL)
    try:
        with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT_S) as resp:
            feed = validate_feed(json.loads(resp.read().decode('utf-8')))
    except Exception as exc:
        log(f'  ⚠ sessions feed unavailable at {url} ({exc.__class__.__name__}) — using committed cache')
        return _load_cache(cache_path, log)

    if url.startswith(('http://', 'https://')):
        _write_cache(cache_path, feed)
        log(f'  ✓ sessions feed fetched ({len(feed["sessions"])} session(s)) — cache refreshed')
    else:
        log(f'  ✓ sessions feed from {url} ({len(feed["sessions"])} session(s); cache untouched)')
    return feed


# ---------------------------------------------------------------------------
# Formatting (America/Denver, functional copy only)
# ---------------------------------------------------------------------------

def _denver(ts):
    return parse_iso(ts).astimezone(DENVER)


def _day(n):
    return str(int(n))  # strip leading zero portably (no %-d on Windows)


def fmt_date_long(ts):
    d = _denver(ts)
    return f'{d.strftime("%A")}, {d.strftime("%B")} {_day(d.strftime("%d"))}, {d.year}'


def fmt_date_short(ts):
    d = _denver(ts)
    return f'{d.strftime("%B")} {_day(d.strftime("%d"))}'


def fmt_time(ts):
    d = _denver(ts)
    hour = _day(d.strftime("%I"))
    return f'{hour}:{d.strftime("%M")} {d.strftime("%p")}'


def fmt_money(cents):
    if cents is None:
        return None
    dollars = cents / 100
    if dollars == int(dollars):
        return f'${int(dollars)}'
    return f'${dollars:.2f}'


# ---------------------------------------------------------------------------
# Event JSON-LD (only ever called with real dated sessions, so DESIGN.md's
# "Event schema once a real date exists, not before" holds automatically)
# ---------------------------------------------------------------------------

def _offer(tier, s):
    if tier.get('mode') == 'sliding':
        cents = tier.get('min_amount') or tier.get('suggested_amount') or tier.get('amount') or 0
    else:
        cents = tier.get('amount') or 0
    offer = {
        '@type': 'Offer',
        'name': tier.get('name') or 'Ticket',
        'price': f'{cents / 100:.2f}',
        'priceCurrency': 'USD',
        'availability': _SCHEMA_AVAILABILITY.get(s.get('status'), 'https://schema.org/InStock'),
    }
    if s.get('checkout_url'):
        offer['url'] = s['checkout_url']
    return offer


def event_schema(s, event_title, page_url, site_url, description='', image=''):
    """schema.org Event dict for one dated session."""
    starts = _denver(s['starts_at'])
    venue = s.get('venue') or {}
    place = {'@type': 'Place', 'name': venue.get('name') or 'Venue to be announced'}
    if venue.get('address'):
        place['address'] = venue['address']
    if venue.get('lat') and venue.get('lng'):
        place['geo'] = {'@type': 'GeoCoordinates',
                        'latitude': venue['lat'], 'longitude': venue['lng']}
    ev = {
        '@context': 'https://schema.org',
        '@type': 'Event',
        'name': f'{event_title} · {fmt_date_short(s["starts_at"])}, {starts.year}',
        'startDate': starts.isoformat(),
        'endDate': _denver(s['ends_at']).isoformat() if s.get('ends_at') else starts.isoformat(),
        'eventStatus': 'https://schema.org/EventScheduled',
        'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
        'location': place,
        'organizer': {'@type': 'LocalBusiness', 'name': 'Firstwater', 'url': site_url},
        # CAL-15: the practice is the named performer of its own sessions.
        'performer': {'@type': 'Person', 'name': 'Firstwater', 'url': site_url},
        'url': page_url,
    }
    if description:
        ev['description'] = description
    if image:
        ev['image'] = image
    offers = [_offer(t, s) for t in (s.get('tiers') or [])]
    if offers:
        ev['offers'] = offers
    return ev
