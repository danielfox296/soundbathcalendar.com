"""Render the daily / weekend social CAROUSEL for Sound Bath Calendar (CAL-25).

Builds a set of 4:5 slides plus the captions that go with them, and writes a
manifest scripts/post.py publishes to Instagram (as a carousel) and the
Facebook Page (as a multi-photo post).

POST KINDS (one a day, chosen by weekday — see the POSTING SCHEDULE block):
  daily        cover slide + one slide per session that day, each carrying the
               operator's own event image.
  weekend      Thu: cover + one slide per day for Fri/Sat/Sun, each a short
               list — the weekend card runs INSTEAD of the daily one.
  practitioner Tue: a three-slide spotlight (portrait, bio, where to find them).
  blog         Sun (alternating): a carousel per evergreen essay — cover +
               up to three VERBATIM passage slides + a read-the-piece closer.
  quote        Sun (alternating): a single 4:5 card, one striking verbatim line
               from an essay, attributed. One slide, not a carousel.

WHY A CAROUSEL. The single card had to hold a whole day, so it was a wall of
text. Giving each session its own slide drops it to three lines a slide and
lets the operator's image carry the weight. It also means every operator on a
busy night gets equal billing — a single hero post would have us picking a
favourite daily, which is a bad position for a calendar that runs on operator
goodwill.

ON THE EVENT IMAGES: these are the operators' own promotional flyers, which
the site already renders on-page with attribution and an outbound link. Every
slide names the operator and the caption's link points at their listing. An
event with no usable image (about 9% of the feed, plus anything whose CDN
fetch fails) falls back to a type-only slide on the same ground, which is
also what a network failure in CI degrades to — never a broken build.

Run from the repo root:

    python3 scripts/social.py                    # today's post, whichever kind
    python3 scripts/social.py --kind weekend
    python3 scripts/social.py --date 2026-08-02 --kind blog
    python3 scripts/social.py --date 2026-08-09 --kind quote
"""
import argparse
import html
import io
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _src.lib.sessions_feed import DENVER, fmt_time, parse_iso  # noqa: E402
from scripts.social_theme import (  # noqa: E402
    ACCENT, H, INK, MARGIN, MUTED, RULE, W,
    font, ground, palette_for,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEED_CACHE = os.path.join(ROOT, 'data', 'external-events.json')
SITE_URL = 'https://soundbathcalendar.com'
COL = W - MARGIN * 2

# Instagram caps a carousel at 10. Cover + 9 sessions, or cover + 8 + an
# overflow slide when the day runs longer than that.
MAX_SLIDES = 10
PHOTO_H = 820                      # the image band on an event slide

IMAGE_TIMEOUT_S = 12
IMAGE_MAX_BYTES = 12 * 1024 * 1024
# Some operator CDNs 403 a bare urllib UA.
IMAGE_UA = ('Mozilla/5.0 (compatible; soundbathcalendar/1.0; '
            '+https://soundbathcalendar.com)')

CITY_SLUGS = {
    'Denver': 'denver', 'Boulder': 'boulder',
    'Fort Collins': 'fort-collins', 'Colorado Springs': 'colorado-springs',
}

NUMBER_WORDS = ['no', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven',
                'Eight', 'Nine', 'Ten', 'Eleven', 'Twelve']

IG_TAGS = ('#soundbath #soundhealing #soundbathmeditation #gongbath '
           '#singingbowls #denver #boulder #colorado #frontrange')

# ============================ POSTING SCHEDULE ============================
# One post a day, chosen by weekday. THIS BLOCK IS THE WHOLE CADENCE — retune
# it here and both the renderer (this file) and the poster (post.py, which
# imports kind_for) follow. See kind_for() for the resolver.
#
#   Tue   practitioner spotlight        (warm, ~1/week)
#   Thu   weekend roundup (Fri/Sat/Sun)
#   Sun   warm essay content, ALTERNATING weekly: blog carousel / quote card
#   else  daily event carousel
#
# ~2 non-event posts a week (Tue + Sun), interleaved with the event cards.
MONDAY, TUESDAY, WEDNESDAY, THURSDAY = 0, 1, 2, 3
FRIDAY, SATURDAY, SUNDAY = 4, 5, 6

WEEKEND_WEEKDAY = THURSDAY          # matches the digest day

# Practitioner spotlights now run TUESDAYS ONLY — Sunday went to blog/quote.
PRACTITIONER_WEEKDAYS = {TUESDAY}
# Rotation epoch: one person is walked off the roster per practitioner slot
# from here, so the sequence is fixed and every re-run of a given date renders
# the same person. The first Tuesday on/after go-live.
PRACTITIONER_EPOCH = date(2026, 7, 28)

# The Sunday warm slot alternates blog carousel / quote card week over week.
# Odd Sundays since the epoch are blog, even are quote (see warm_sunday_kind);
# each kind then walks its own rotation (ESSAYS / QUOTES) one step per slot, so
# any given Sunday is fully reproducible. The first Sunday on/after go-live.
WARM_SUNDAY_EPOCH = date(2026, 8, 2)

PRACT_FEED_URL = 'https://admin.soundbathcalendar.com/feeds/practitioners.json'
PRACT_CACHE = os.path.join(ROOT, 'data', 'practitioners.json')
PRACT_PHOTO_DIR = os.path.join(ROOT, 'img', 'practitioners')


# ---------- text helpers ----------

def _wave(draw, x, y, width=60, amp=7, color=ACCENT):
    pts = [(x + i, y + amp * math.sin(i / width * 2 * math.pi))
           for i in range(0, width + 1, 2)]
    draw.line(pts, fill=color, width=3)


def _eyebrow(draw, x, y, text, f, tracking=3, color=ACCENT):
    for ch in text:
        draw.text((x, y), ch, font=f, fill=color)
        x += draw.textlength(ch, font=f) + tracking
    return x


def _wrap(draw, text, f, max_w, max_lines):
    """Greedy wrap to max_lines, ellipsizing the last line when it overruns."""
    words, lines, cur = (text or '').split(), [], ''
    for word in words:
        trial = f'{cur} {word}'.strip()
        if cur and draw.textlength(trial, font=f) > max_w:
            lines.append(cur)
            cur = word
            if len(lines) == max_lines:
                break
        else:
            cur = trial
    if len(lines) < max_lines:
        if cur:
            lines.append(cur)
        return lines
    tail = lines[-1]
    while tail and draw.textlength(tail + '…', font=f) > max_w:
        tail = tail[:-1].rstrip()
    lines[-1] = tail + '…'
    return lines


def _fit(draw, text, f, max_w):
    """Single line, ellipsized to fit."""
    lines = _wrap(draw, text, f, max_w, 1)
    return lines[0] if lines else ''


def _eyebrow_text(draw, text, f, max_w, tracking=3):
    """Clip an eyebrow string to what fits `max_w` at the tracked pitch —
    _eyebrow draws char by char and has no wrap, so a long essay title would
    otherwise run off the right margin."""
    out, x = '', 0.0
    for ch in text:
        adv = draw.textlength(ch, font=f) + tracking
        if x + adv > max_w:
            break
        out += ch
        x += adv
    return out


def _fit_block(draw, text, weight, max_w, max_h, sizes, max_lines):
    """Largest font from `sizes` (try in the given, descending, order) whose
    wrap fits inside max_lines AND max_h WITHOUT ellipsis. Returns (font, lines).

    The no-ellipsis rule matters: excerpt and quote text is verbatim from the
    essays, so dropping a trailing word to make it fit is not allowed — we
    shrink the type instead. Falls back to the smallest size if nothing fits."""
    for size in sizes:
        f = font(size, weight)
        lines = _wrap(draw, text, f, max_w, max_lines)
        line_h = round(f.size * 1.2)
        if (len(lines) <= max_lines and len(lines) * line_h <= max_h
                and not lines[-1].endswith('…')):
            return f, lines
    f = font(sizes[-1], weight)
    return f, _wrap(draw, text, f, max_w, max_lines)


def _where(draw, event, f, max_w):
    """'Venue · City', ellipsizing the VENUE so the city always survives —
    the city is the field a scroller actually filters on."""
    venue = (event.get('venue') or '').strip()
    city = (event.get('city') or '').strip()
    if not venue:
        return city
    if not city:
        return _fit(draw, venue, f, max_w)
    full = f'{venue} · {city}'
    if draw.textlength(full, font=f) <= max_w:
        return full
    tail = f' · {city}'
    room = max_w - draw.textlength(tail, font=f)
    while venue and draw.textlength(venue + '…', font=f) > room:
        venue = venue[:-1].rstrip()
    return f'{venue}…{tail}' if venue else city


# ---------- event images ----------

def fetch_image(url):
    """Download an operator's event image. Returns an RGB Image, or None.

    Never raises: a dead CDN, a 403, an HTML error page served as an image,
    or a truncated file all degrade to the type-only slide. A social card is
    not worth failing a site deploy over.
    """
    # http is allowed as a SOURCE even though the feed contract scrubs to
    # https — a handful of operator rows still carry http, and we re-encode
    # through PIL and re-host the result, so nothing insecure is ever embedded
    # in the published card. PIL decoding is also the validity check: an error
    # page served with an image content-type fails to open and falls back.
    if not (url or '').strip().lower().startswith(('https://', 'http://')):
        return None
    try:
        req = urllib.request.Request(url, headers={'user-agent': IMAGE_UA})
        with urllib.request.urlopen(req, timeout=IMAGE_TIMEOUT_S) as resp:
            if not resp.headers.get('content-type', '').startswith('image/'):
                return None
            raw = resp.read(IMAGE_MAX_BYTES + 1)
        if len(raw) > IMAGE_MAX_BYTES:
            return None
        img = Image.open(io.BytesIO(raw))
        img.load()
        return img.convert('RGB')
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _cover_crop(photo, size):
    """Scale-and-crop to fill `size`, centred (same construction as og.py's
    _cover, without the focal points — these are arbitrary operator flyers)."""
    tw, th = size
    sw, sh = photo.size
    scale = max(tw / sw, th / sh)
    nw, nh = max(tw, round(sw * scale)), max(th, round(sh * scale))
    photo = photo.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - tw) // 2, (nh - th) // 2
    return photo.crop((left, top, left + tw, top + th))


# ---------- content helpers ----------

def load_events():
    """Approved events from the committed feed cache — the same file build.py
    refreshes at the top of every build, so the card sees what the site did."""
    with open(FEED_CACHE, encoding='utf-8') as fh:
        return [e for e in json.load(fh).get('events', [])
                if e.get('status') == 'approved']


def events_on(events, day):
    rows = [e for e in events
            if parse_iso(e['starts_at']).astimezone(DENVER).date() == day]
    return sorted(rows, key=lambda e: parse_iso(e['starts_at']))


def _day_word(rows):
    """'tonight' only when every session is genuinely an evening one — the
    register rule the site runs on: never say a thing that is not true
    because it sounds better."""
    hours = [parse_iso(e['starts_at']).astimezone(DENVER).hour for e in rows]
    return 'tonight' if hours and min(hours) >= 16 else 'today'


def _count_word(n):
    return NUMBER_WORDS[n] if n < len(NUMBER_WORDS) else str(n)


def _headline(rows):
    n = len(rows)
    word = _day_word(rows)
    if n == 1:
        return f'One sound bath {word}'
    return f'{_count_word(n)} sound baths {word}'


def _cities(rows):
    seen = []
    for e in rows:
        if e.get('city') and e['city'] not in seen:
            seen.append(e['city'])
    return seen


def _city_line(cities):
    if len(cities) == 1:
        return cities[0]
    if len(cities) == 2:
        return f'{cities[0]} & {cities[1]}'
    return f'{len(cities)} cities'


def _stamp(day):
    return f'{day.strftime("%A")}, {day.strftime("%B")} {day.day}'


def _short_stamp(day):
    return f'{day.strftime("%a")} {day.strftime("%b")} {day.day}'


def _landing_url(cities):
    if len(cities) == 1 and cities[0] in CITY_SLUGS:
        return f'{SITE_URL}/{CITY_SLUGS[cities[0]]}/'
    return f'{SITE_URL}/'


def _operator(event):
    ref = event.get('operator_ref') or {}
    return (ref.get('name') or event.get('operator') or '').strip()


def _norm(s):
    return ''.join(c for c in (s or '').lower() if c.isalnum())


def _credit(event):
    """The attribution line under the venue.

    Prefers the facilitator — the person actually leading it — and falls back
    to the operator. Returns '' when the operator IS the venue, because the
    line above already names them and 'Rocky Mountain Restore & Stretch ·
    Fort Collins / Presented by Rocky Mountain Restore & Stretch' just reads
    as a bug. Attribution still stands in that case: their name is on the slide.
    """
    operator = _operator(event)
    facilitator = (event.get('facilitator') or '').strip()
    if facilitator and _norm(facilitator) != _norm(operator):
        return f'Led by {facilitator}'
    if operator and _norm(operator) != _norm(event.get('venue')):
        return f'Presented by {operator}'
    return ''


# ---------- slide chrome ----------

def _footer(d, left=None, right=None, right_color=ACCENT):
    f_foot = font(28, 500)
    y = H - MARGIN - 30
    d.line([(MARGIN, y - 30), (W - MARGIN, y - 30)], fill=RULE, width=2)
    d.text((MARGIN, y), left or 'soundbathcalendar.com', font=f_foot, fill=ACCENT)
    if right:
        d.text((W - MARGIN - d.textlength(right, font=f_foot), y),
               right, font=f_foot, fill=right_color)


# ---------- slides ----------

def slide_cover(palette, day, rows, kind):
    """Near-textless opener: the count, the date, and a swipe cue."""
    img = ground(palette, rotate=0)
    d = ImageDraw.Draw(img)

    _wave(d, MARGIN, 116)
    _eyebrow(d, MARGIN + 80, 100, 'SOUND BATH CALENDAR', font(26, 600))

    if kind == 'weekend':
        headline = f'{_count_word(len(rows))} sound baths this weekend'
        sub = f'{_short_stamp(day)} – {_short_stamp(day + timedelta(days=2))}'
    else:
        headline = _headline(rows)
        sub = _stamp(day)
    cities = _cities(rows)
    if cities:
        sub = f'{sub} · {_city_line(cities)}'

    f_head = font(104, 500)
    lines = _wrap(d, headline, f_head, COL, 4)
    if len(lines) > 3:
        f_head = font(86, 500)
        lines = _wrap(d, headline, f_head, COL, 3)
    line_h = round(f_head.size * 1.12)

    block_h = len(lines) * line_h + 70
    y = max(300, (H - block_h) // 2 - 40)
    for line in lines:
        d.text((MARGIN, y), line, font=f_head, fill=INK)
        y += line_h
    d.text((MARGIN, y + 24), sub, font=font(38, 500), fill=MUTED)

    _footer(d, right='swipe →')
    return img


def slide_event(palette, event, rotate, photo):
    """One session. Photo band on top, pastel panel below.

    A panel rather than a scrim over a full-bleed photo: a dark scrim is what
    the ink cards did, and it would fight the pastel identity on every slide.
    The panel also keeps type legibility independent of whatever the operator
    happened to upload.
    """
    img = ground(palette, rotate=rotate)
    d = ImageDraw.Draw(img)

    if photo is not None:
        img.paste(_cover_crop(photo, (W, PHOTO_H)), (0, 0))
        d.line([(0, PHOTO_H), (W, PHOTO_H)], fill=RULE, width=2)
        f_time, f_name, f_meta, name_lines_max = (
            font(44, 600), font(56, 500), font(34, 400), 2)
    else:
        # Type-only fallback: no photo band, so the name is set large and the
        # block is centred in the card. Anchoring it at the top instead left
        # two thirds of the slide visibly empty.
        _wave(d, MARGIN, 116)
        _eyebrow(d, MARGIN + 80, 100, 'SOUND BATH CALENDAR', font(26, 600))
        f_time, f_name, f_meta, name_lines_max = (
            font(48, 600), font(80, 500), font(36, 400), 3)

    name_lines = _wrap(d, event['name'], f_name, COL, name_lines_max)
    name_h = round(f_name.size * 1.16)
    credit = _credit(event)

    block_h = (round(f_time.size * 1.36) + len(name_lines) * name_h + 10
               + round(f_meta.size * 1.36) + (round(f_meta.size * 1.2) if credit else 0))
    if photo is not None:
        y = PHOTO_H + max(40, (H - PHOTO_H - 96 - block_h) // 2)
    else:
        y = max(300, (H - block_h) // 2 - 40)

    d.text((MARGIN, y), fmt_time(event['starts_at']).lower(), font=f_time, fill=ACCENT)
    y += round(f_time.size * 1.36)

    for line in name_lines:
        d.text((MARGIN, y), line, font=f_name, fill=INK)
        y += name_h

    y += 10
    d.text((MARGIN, y), _where(d, event, f_meta, COL), font=f_meta, fill=MUTED)
    y += round(f_meta.size * 1.36)

    if credit:
        d.text((MARGIN, y), _fit(d, credit, f_meta, COL), font=f_meta, fill=MUTED)

    _footer(d, right=(event.get('price') or '').strip() or None)
    return img


def slide_day_list(palette, day, rows, rotate, limit=6):
    """A weekend slide: one day, listed short."""
    img = ground(palette, rotate=rotate)
    d = ImageDraw.Draw(img)

    _wave(d, MARGIN, 116)
    _eyebrow(d, MARGIN + 80, 100, day.strftime('%A').upper(), font(26, 600))

    d.text((MARGIN, 186), _stamp(day), font=font(64, 500), fill=INK)
    d.line([(MARGIN, 292), (W - MARGIN, 292)], fill=RULE, width=2)

    f_time, f_name, f_venue = font(38, 600), font(44, 500), font(30, 400)
    time_col = round(max(d.textlength(fmt_time(e['starts_at']).lower(), font=f_time)
                         for e in rows[:limit]) + 28)
    name_w = COL - time_col

    # Centre the list between the rule and the footer, so a three-session day
    # doesn't leave the bottom half of the slide empty.
    shown = rows[:limit]
    block_h = len(shown) * 122 + (44 if len(rows) > limit else 0)
    y = 356 + max(0, ((H - 150) - 356 - block_h) // 2)
    for e in shown:
        d.text((MARGIN, y + 4), fmt_time(e['starts_at']).lower(), font=f_time, fill=ACCENT)
        d.text((MARGIN + time_col, y), _fit(d, e['name'], f_name, name_w),
               font=f_name, fill=INK)
        d.text((MARGIN + time_col, y + 54), _where(d, e, f_venue, name_w),
               font=f_venue, fill=MUTED)
        y += 122

    if len(rows) > limit:
        d.text((MARGIN + time_col, y), f'+{len(rows) - limit} more on the site',
               font=f_venue, fill=ACCENT)

    _footer(d, right=_city_line(_cities(rows)) or None, right_color=MUTED)
    return img


def slide_overflow(palette, count, rotate):
    """Closer for a day too long for one carousel."""
    img = ground(palette, rotate=rotate)
    d = ImageDraw.Draw(img)
    _wave(d, MARGIN, 116)
    _eyebrow(d, MARGIN + 80, 100, 'SOUND BATH CALENDAR', font(26, 600))

    f_head = font(96, 500)
    lines = _wrap(d, f'+{count} more sound baths today', f_head, COL, 3)
    y = (H - len(lines) * round(f_head.size * 1.12)) // 2 - 60
    for line in lines:
        d.text((MARGIN, y), line, font=f_head, fill=INK)
        y += round(f_head.size * 1.12)
    d.text((MARGIN, y + 24), 'Times, tickets and directions on the site',
           font=font(36, 400), fill=MUTED)
    _footer(d)
    return img


# ---------- captions ----------

def _session_lines(rows, limit=8):
    out = []
    for e in rows[:limit]:
        out.append(f'{fmt_time(e["starts_at"]).lower()} — {e["name"]} · '
                   f'{" · ".join(x for x in (e.get("venue"), e.get("city")) if x)}')
    if len(rows) > limit:
        out.append(f'+{len(rows) - limit} more')
    return out


def captions(day, rows, kind, weekend_days=None):
    """Facebook and Instagram captions.

    They differ on one axis only, and it is a platform limit rather than a
    voice choice: Instagram feed captions render URLs as plain text, so the
    link lives on the Facebook post and Instagram points at the bio.
    """
    if kind == 'weekend':
        head = (f'{_count_word(len(rows))} sound baths this weekend — '
                f'{_short_stamp(day)}–{_short_stamp(day + timedelta(days=2))}')
        parts = []
        for d_, day_rows in (weekend_days or []):
            parts.append(f'{d_.strftime("%A")}\n' + '\n'.join(_session_lines(day_rows, 4)))
        body = '\n\n'.join(parts)
    else:
        head = f'{_headline(rows)} — {_stamp(day)}'
        body = '\n'.join(_session_lines(rows))

    url = _landing_url(_cities(rows))
    fb = f'{head}\n\n{body}\n\nTimes, tickets and directions: {url}'
    ig = f'{head}\n\n{body}\n\nFull calendar — link in bio.\n\n{IG_TAGS}'
    return fb, ig


# ---------- post builders ----------

def _write(img, rel):
    path = os.path.join(ROOT, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # JPEG because Instagram publishes JPEG only — not a size decision.
    img.save(path, 'JPEG', quality=88, optimize=True, progressive=True)
    return {'path': rel, 'url': f'{SITE_URL}/{rel}'}


def build_daily(events, day, quiet=False):
    rows = events_on(events, day)
    if not rows:
        # Silence beats "no sound baths today" — that trains a feed to skip us.
        if not quiet:
            print(f'  -- {day}: no approved sessions, skipping')
        return None

    palette = palette_for(day)
    stamp = day.isoformat()
    folder = f'img/social/{stamp}'

    room = MAX_SLIDES - 1
    shown = rows if len(rows) <= room else rows[:room - 1]
    overflow = len(rows) - len(shown)

    slides = [_write(slide_cover(palette, day, rows, 'daily'), f'{folder}/01-cover.jpg')]
    photos_used = 0
    for i, event in enumerate(shown, start=2):
        photo = fetch_image(event.get('image_url', ''))
        photos_used += photo is not None
        slides.append(_write(slide_event(palette, event, i % 4, photo),
                             f'{folder}/{i:02d}-event.jpg'))
    if overflow:
        slides.append(_write(slide_overflow(palette, overflow, 0),
                             f'{folder}/{len(slides) + 1:02d}-more.jpg'))

    fb, ig = captions(day, rows, 'daily')
    manifest = {
        'date': stamp, 'kind': 'daily', 'palette': palette,
        'slides': slides, 'event_count': len(rows),
        'sessions_on_slides': len(shown), 'photos_used': photos_used,
        'cities': _cities(rows), 'landing_url': _landing_url(_cities(rows)),
        'caption_facebook': fb, 'caption_instagram': ig,
    }
    _write_manifest(f'img/social/{stamp}.json', manifest)
    if not quiet:
        print(f'  ok {folder} — {len(slides)} slides, {len(rows)} session(s), '
              f'{photos_used}/{len(shown)} with photos, palette {palette}')
    return manifest


def build_weekend(events, thursday, quiet=False):
    """Fri/Sat/Sun from a Thursday. One slide per day, listed short."""
    days = [thursday + timedelta(days=n) for n in (1, 2, 3)]
    per_day = [(d, events_on(events, d)) for d in days]
    per_day = [(d, r) for d, r in per_day if r]
    rows = [e for _, r in per_day for e in r]
    if not rows:
        if not quiet:
            print(f'  -- weekend of {days[0]}: no approved sessions, skipping')
        return None

    palette = palette_for(thursday)
    stamp = thursday.isoformat()
    folder = f'img/social/{stamp}-weekend'

    slides = [_write(slide_cover(palette, days[0], rows, 'weekend'),
                     f'{folder}/01-cover.jpg')]
    for i, (d_, day_rows) in enumerate(per_day, start=2):
        slides.append(_write(slide_day_list(palette, d_, day_rows, i % 4),
                             f'{folder}/{i:02d}-{d_.strftime("%a").lower()}.jpg'))

    fb, ig = captions(days[0], rows, 'weekend', per_day)
    manifest = {
        'date': stamp, 'kind': 'weekend', 'palette': palette,
        'slides': slides, 'event_count': len(rows),
        'days': [d_.isoformat() for d_, _ in per_day],
        'cities': _cities(rows), 'landing_url': _landing_url(_cities(rows)),
        'caption_facebook': fb, 'caption_instagram': ig,
    }
    _write_manifest(f'img/social/{stamp}-weekend.json', manifest)
    if not quiet:
        print(f'  ok {folder} — {len(slides)} slides, {len(rows)} session(s) '
              f'across {len(per_day)} day(s), palette {palette}')
    return manifest


# ---------- practitioner spotlights ----------

def load_practitioners():
    """Published practitioners that have a REVIEWED photo committed under
    img/practitioners/. The photo file is the gate — a practitioner without a
    face never enters the rotation, so no spotlight ever ships a logo or a
    blank. Bios come from the live service feed (falling back to the committed
    cache), because the local cache goes stale — see the feed contract."""
    feed = None
    try:
        req = urllib.request.Request(PRACT_FEED_URL, headers={'user-agent': IMAGE_UA})
        with urllib.request.urlopen(req, timeout=IMAGE_TIMEOUT_S) as resp:
            feed = json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, ValueError):
        try:
            with open(PRACT_CACHE, encoding='utf-8') as fh:
                feed = json.load(fh)
        except (OSError, ValueError):
            return []
    rows = feed.get('practitioners', []) if isinstance(feed, dict) else (feed or [])
    out = []
    for p in rows:
        slug = (p.get('slug') or '').strip()
        photo = os.path.join(PRACT_PHOTO_DIR, f'{slug}.jpg')
        if slug and os.path.exists(photo):
            out.append({**p, '_photo': photo})
    # Stable order so the rotation is deterministic regardless of feed order.
    return sorted(out, key=lambda p: p['slug'])


def _count_weekday(start, end, weekday):
    """Occurrences of `weekday` in [start, end] inclusive, by ordinal math —
    no day-by-day loop that would grow with the calendar."""
    if end < start:
        return 0
    a, b = start.toordinal(), end.toordinal()
    first = a + (weekday - (a - 1) % 7) % 7   # first such weekday >= start
    return 0 if first > b else (b - first) // 7 + 1


def practitioner_slot(day):
    """How many warm slots have elapsed through `day` since the epoch — the
    rotation index before it is taken modulo the roster size."""
    return sum(_count_weekday(PRACTITIONER_EPOCH, day, wd)
               for wd in PRACTITIONER_WEEKDAYS)


def practitioner_for(day, roster):
    """The practitioner whose turn it is on `day`. One person advances per
    warm slot, so the roster cycles evenly and a given date is reproducible."""
    if not roster:
        return None
    return roster[(practitioner_slot(day) - 1) % len(roster)]


def _first_sentence(text, limit=120):
    """The bio's opening sentence, for the cover's one-line essence."""
    text = ' '.join((text or '').split())
    m = re.search(r'(.+?[.!?])(\s|$)', text)
    s = m.group(1) if m else text
    return s if len(s) <= limit else s[:limit].rsplit(' ', 1)[0] + '…'


def _pull_quote(bio):
    """A quoted line from the bio if the practitioner has one — their own
    words are the warmest thing on the card."""
    m = re.search(r'[“"]([^”"]{20,140})[”"]', bio or '')
    return m.group(1) if m else ''


def practitioner_next_session(events, name, on_day):
    """Soonest session this person facilitates that is still UPCOMING on
    `on_day` — never a past date, which on a public card reads as stale."""
    key = _norm(name)
    if not key:
        return None
    mine = [e for e in events
            if _norm(e.get('facilitator')) == key
            and parse_iso(e['starts_at']).astimezone(DENVER).date() >= on_day]
    return sorted(mine, key=lambda e: parse_iso(e['starts_at']))[0] if mine else None


def _first_name(name):
    return (name or '').split()[0] if name else 'them'


def slide_practitioner_cover(palette, p):
    """Portrait band + name. The face is the hook, so it gets the top half."""
    img = ground(palette, rotate=0)
    d = ImageDraw.Draw(img)
    try:
        photo = Image.open(p['_photo']).convert('RGB')
        img.paste(_cover_crop(photo, (W, PHOTO_H)), (0, 0))
        d.line([(0, PHOTO_H), (W, PHOTO_H)], fill=RULE, width=2)
    except (OSError, ValueError):
        pass

    y = PHOTO_H + 54
    _wave(d, MARGIN, y + 6)
    _eyebrow(d, MARGIN + 80, y - 8, 'PRACTITIONER', font(26, 600))
    y += 58

    f_name = font(72, 500)
    for line in _wrap(d, p.get('name', ''), f_name, COL, 2):
        d.text((MARGIN, y), line, font=f_name, fill=INK)
        y += round(f_name.size * 1.12)

    essence = _first_sentence(p.get('bio', ''))
    if essence:
        for line in _wrap(d, essence, font(34, 400), COL, 2):
            d.text((MARGIN, y + 6), line, font=font(34, 400), fill=MUTED)
            y += 44
    _footer(d, right='swipe →')
    return img


def slide_practitioner_bio(palette, p, rotate):
    """Their story, in their own words. A pulled quote gets set large; the
    rest of the bio runs beneath it."""
    img = ground(palette, rotate=rotate)
    d = ImageDraw.Draw(img)
    _wave(d, MARGIN, 116)
    _eyebrow(d, MARGIN + 80, 100, _first_name(p.get('name')).upper(), font(26, 600))

    bio = ' '.join((p.get('bio') or '').split())
    quote = _pull_quote(bio)
    y = 210
    if quote:
        # Drop the quote from the running body so it is not said twice.
        bio = bio.replace(f'“{quote}”', '').replace(f'"{quote}"', '').strip(' ,.')
        f_q = font(52, 500)
        for line in _wrap(d, f'“{quote}”', f_q, COL, 4):
            d.text((MARGIN, y), line, font=f_q, fill=INK)
            y += round(f_q.size * 1.2)
        y += 30

    f_b = font(34, 400)
    for line in _wrap(d, bio, f_b, COL, 12):
        d.text((MARGIN, y), line, font=f_b, fill=INK if not quote else MUTED)
        y += round(f_b.size * 1.34)
    _footer(d, right='swipe →')
    return img


def slide_practitioner_find(palette, p, rotate, session):
    """Where to find them: next session if there is one, plus their own links.

    The block is measured and vertically centred, because whether a person has
    an upcoming session swings the content between full and sparse — a fixed
    top anchor left the no-session version stranded above a half-empty card.
    """
    img = ground(palette, rotate=rotate)
    d = ImageDraw.Draw(img)
    _wave(d, MARGIN, 116)
    _eyebrow(d, MARGIN + 80, 100, 'WHERE TO FIND THEM', font(26, 600))

    f_title = font(72, 500)
    f_lead = font(28, 600)
    f_big = font(38, 500)
    f_body = font(34, 400)
    f_small = font(30, 400)

    # Build the block as (font, colour, text) rows, then measure and centre.
    rows = [(f_title, INK, f'Find {_first_name(p.get("name"))}'), (None, None, 24)]
    when = parse_iso(session['starts_at']).astimezone(DENVER) if session else None
    if session:
        rows += [
            (f_lead, ACCENT, 'NEXT SESSION'),
            (f_big, INK, f'{when.strftime("%a %b %-d")} · {fmt_time(session["starts_at"]).lower()}'),
            (f_body, MUTED, _fit(d, session.get('name', ''), f_body, COL)),
            (f_small, MUTED, _fit(d, _where(d, session, f_small, COL), f_small, COL)),
            (None, None, 40),
        ]
    else:
        rows += [(f_body, MUTED, 'Practicing on the Front Range'), (None, None, 40)]
    for label, key in (('Website', 'website_url'), ('Instagram', 'instagram_url')):
        val = (p.get(key) or '').strip()
        if val:
            handle = re.sub(r'^https?://(www\.)?', '', val).rstrip('/')
            rows.append((f_small, INK, f'{label} · {_fit(d, handle, f_small, COL - 220)}'))

    def row_h(r):
        return r[2] if r[0] is None else round(r[0].size * 1.34)
    total = sum(row_h(r) for r in rows)
    top, bottom = 210, H - 190
    y = top + max(0, (bottom - top - total) // 2)
    for fnt, col, val in rows:
        if fnt is None:
            y += val
            continue
        d.text((MARGIN, y), val, font=fnt, fill=col)
        y += round(fnt.size * 1.34)

    _footer(d, left='soundbathcalendar.com', right='full profile — link in bio')
    return img


def practitioner_captions(p, session):
    """Meet-the-practitioner captions. The body is the bio verbatim — their
    voice, not ours — and the link is their profile page."""
    name = p.get('name', '')
    slug = p.get('slug', '')
    url = f'{SITE_URL}/practitioner/{slug}/'
    bio = ' '.join((p.get('bio') or '').split())

    lines = [f'Meet {name} — a sound practitioner on the Front Range.', '', bio]
    if session:
        when = parse_iso(session['starts_at']).astimezone(DENVER)
        lines += ['', f'Next up: {session.get("name", "")} · '
                  f'{when.strftime("%a %b %-d")}, {fmt_time(session["starts_at"]).lower()}.']
    body = '\n'.join(lines)
    tags = ('#soundbath #soundhealing #frontrange #denver #boulder #colorado '
            '#practitioner #soundhealer')
    fb = f'{body}\n\nFull profile: {url}'
    ig = f'{body}\n\nFull profile — link in bio.\n\n{tags}'
    return fb, ig


def build_practitioner(events, day, quiet=False):
    """One practitioner spotlight for `day`. Returns the manifest, or None
    when there is no one in the rotation (roster empty)."""
    roster = load_practitioners()
    p = practitioner_for(day, roster)
    if p is None:
        if not quiet:
            print(f'  -- {day}: no practitioner with a photo, skipping')
        return None

    palette = palette_for(day)
    stamp = day.isoformat()
    slug = p['slug']
    folder = f'img/social/{stamp}-practitioner'
    session = practitioner_next_session(events, p.get('name', ''), day)

    slides = [
        _write(slide_practitioner_cover(palette, p), f'{folder}/01-cover.jpg'),
        _write(slide_practitioner_bio(palette, p, 2), f'{folder}/02-story.jpg'),
        _write(slide_practitioner_find(palette, p, 3, session), f'{folder}/03-find.jpg'),
    ]
    fb, ig = practitioner_captions(p, session)
    manifest = {
        'date': stamp, 'kind': 'practitioner', 'palette': palette,
        'slides': slides, 'practitioner': p.get('name', ''), 'slug': slug,
        'landing_url': f'{SITE_URL}/practitioner/{slug}/',
        'caption_facebook': fb, 'caption_instagram': ig,
    }
    _write_manifest(f'img/social/{stamp}-practitioner.json', manifest)
    if not quiet:
        print(f'  ok {folder} — {p.get("name")}, palette {palette}'
              f'{" (+next session)" if session else ""}')
    return manifest


# ---------- blog excerpts & quote cards ----------
#
# Both draw on the twelve evergreen essays that live at the repo ROOT as
# <slug>/index.html. Nothing here writes new prose: excerpts are pulled
# VERBATIM from the essays (the register rule — honest facts, subculture voice
# honored, never a claim the essay didn't make), and quote cards use a curated
# shortlist of lines lifted from those same essays.

# Rotation order for the blog carousel. A blog Sunday resolves to one essay via
# WARM_SUNDAY_EPOCH + a slot counter (mirrors the practitioner rotation), so
# the sequence is fixed and every re-run of a given date renders the same essay.
# Ordered to interleave the topics rather than march through look-alikes.
ESSAYS = [
    'what-to-expect',
    'sound-bath-science',
    'where-sound-baths-come-from',
    'singing-bowls-vs-gongs',
    'is-a-sound-bath-religious',
    '432hz-explained',
    'what-is-a-gong-bath',
    'sound-bath-vs-meditation',
    'what-is-a-crystal-bowl-sound-bath',
    'gong-bath',
    'breathwork-sound',
    'state-of-sound-healing',
]

# One striking line per quote card, VERBATIM from the essay it is credited to
# (excerpts only — no new claims). Rotated one per quote slot. Each line is a
# self-contained sentence that survives being lifted out of its paragraph.
QUOTES = [
    ('There is nothing to perform and no way to do it wrong.', 'what-to-expect'),
    ('Most sound baths use both, and neither requires anything from you but '
     'lying down and listening.', 'singing-bowls-vs-gongs'),
    ('A sound bath is receptive — you lie down and the sound comes to you, no '
     'technique required.', 'sound-bath-vs-meditation'),
    ('There is nothing to do and no technique to get right.', 'what-is-a-gong-bath'),
    ('No beliefs and no experience are required.', 'what-is-a-gong-bath'),
    ('There is no liturgy, no text, no membership, and no one asks what you '
     'believe.', 'is-a-sound-bath-religious'),
    ('Thin evidence is not the same as evidence against.', 'sound-bath-science'),
    ('Young traditions are still traditions; this one is being written by the '
     'people playing tonight.', 'where-sound-baths-come-from'),
    ('You are welcome to enjoy the session with or without the framework.',
     '432hz-explained'),
    ('Your mind can wander all it likes; the sound keeps drawing it back '
     'without you doing anything.', 'sound-bath-vs-meditation'),
    ('That physical, whole-room quality is what people mean when they call a '
     'gong bath immersive.', 'what-is-a-gong-bath'),
    ('Choose a session by facilitator, instruments, size, and setting — the '
     'things that actually shape the hour.', '432hz-explained'),
]

# Paragraph classes that are chrome, not prose (crumbs, ctas, meta rows…).
_PROSE_SKIP = ('crumb', 'cta', 'meta', 'footer', 'tag', 'label', 'eyebrow',
               'kicker', 'fine', 'note')
# Sentences opening with one of these dangle without their antecedent once
# lifted out of the paragraph, so they never make good pull-quotes.
_SENT_BAD_START = {'But', 'So', 'That', 'This', 'It', 'They', 'And', 'Yet',
                   'Still', 'Then', 'There', 'These', 'Those'}
QUOTE_TAGS = ('#soundbath #soundhealing #frontrange #denver #boulder #colorado '
              '#soundbathmeditation #mindfulness')
BLOG_TAGS = ('#soundbath #soundhealing #frontrange #denver #boulder #colorado '
             '#soundbathmeditation #gongbath #singingbowls')


# ---------- essay parsing ----------

def _clean(fragment):
    """Inline tags out, entities decoded, whitespace collapsed."""
    text = re.sub(r'<[^>]+>', ' ', fragment or '')
    return re.sub(r'\s+', ' ', html.unescape(text)).strip()


def _sentences(text):
    """Split into sentences on end punctuation FOLLOWED by whitespace and a
    capital (or a quote), so decimals like '21.9' and mid-sentence
    abbreviations don't fracture a sentence in half."""
    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z"“])', (text or '').strip())
    return [p.strip() for p in parts if p.strip()]


def _prose_sentences(raw_paragraph):
    """Sentences of a paragraph, with any cross-reference / calendar link
    DROPPED whole — a sentence that was really a 'see also' (its text was a
    link to another page) is not pulled as an excerpt. Same-page anchors (#…)
    are kept."""
    marked = re.sub(r'<a\b[^>]*\shref="(?!#)[^"]*"[^>]*>.*?</a>', ' \x00 ',
                    raw_paragraph, flags=re.S)
    return [s for s in _sentences(_clean(marked)) if '\x00' not in s]


def _essay_html(slug):
    with open(os.path.join(ROOT, slug, 'index.html'), encoding='utf-8') as fh:
        return fh.read()


def _essay_title(html_text):
    m = re.search(r'<h1[^>]*>(.*?)</h1>', html_text, re.S)
    return _clean(m.group(1)) if m else ''


def _essay_paragraphs(html_text):
    """Raw inner-HTML of each prose paragraph in <main>, in document order.

    Content-filtered, not class-filtered: the twelve essays use a dozen
    different paragraph classes for the same honest prose, so a paragraph
    qualifies by being a real sentence of some length rather than by its class.
    """
    m = re.search(r'<main\b[^>]*>(.*?)</main>', html_text, re.S)
    body = m.group(1) if m else html_text
    out = []
    for pm in re.finditer(r'<p(?:\s+class="([^"]*)")?[^>]*>(.*?)</p>', body, re.S):
        cls = pm.group(1) or ''
        if any(s in cls for s in _PROSE_SKIP):
            continue
        raw = pm.group(2)
        if len(_clean(raw).split()) >= 18 and re.search(r'[.!?]', raw):
            out.append(raw)
    return out


def _essay_hook(html_text, paragraphs):
    """The cover's one-line essence: the page's own summary, minus any leading
    live-count sentence (a few essays open their summary with a session count,
    which would date an evergreen card), falling back to the first prose
    paragraph."""
    m = re.search(r'<p class="(?:cal-summary|soh-dek)"[^>]*>(.*?)</p>',
                  html_text, re.S)
    sents = _sentences(_clean(m.group(1))) if m else []
    while sents and re.match(r'\d', sents[0]):   # drop a leading count sentence
        sents.pop(0)
    hook = ' '.join(sents).strip()
    if not hook and paragraphs:
        hook = _clean(paragraphs[0])
    return hook


def _essay_passages(paragraphs, hook, n=3):
    """Up to n verbatim excerpts, spread across the essay. Each is a single
    sentence chosen to stand on its own: long enough to say something, short
    enough to set large, and not opening on a dangling connective."""
    hook_sents = set(_sentences(hook))
    pool, seen = [], set()
    for raw in paragraphs:
        for s in _prose_sentences(raw):
            if s in hook_sents or s in seen:
                continue
            if not 60 <= len(s) <= 200:
                continue
            first = s.split()[0].strip('“"—')
            # A dangling connective or a bare number opening reads badly once
            # the sentence is lifted onto a card of its own.
            if first in _SENT_BAD_START or first[:1].isdigit():
                continue
            seen.add(s)
            pool.append(s)
    if len(pool) <= n:
        return pool
    # Spread the picks roughly evenly through the essay so the three slides
    # aren't three consecutive sentences from the opening.
    step = len(pool) / n
    return [pool[min(len(pool) - 1, int(i * step))] for i in range(n)]


# ---------- rotation ----------

def _sunday_index(day):
    """1-based count of Sundays from WARM_SUNDAY_EPOCH through `day` inclusive.
    Odd -> blog week, even -> quote week. Robust off-Sunday too (a manual
    --kind blog on any date still resolves deterministically)."""
    return _count_weekday(WARM_SUNDAY_EPOCH, day, SUNDAY)


def warm_sunday_kind(day):
    return 'blog' if _sunday_index(day) % 2 == 1 else 'quote'


def blog_essay_slug(day):
    """The essay whose turn it is — one step per blog Sunday."""
    slot = (_sunday_index(day) + 1) // 2
    return ESSAYS[(slot - 1) % len(ESSAYS)]


def quote_for(day):
    """The (line, source-slug) whose turn it is — one step per quote Sunday."""
    slot = _sunday_index(day) // 2
    return QUOTES[(slot - 1) % len(QUOTES)]


# ---------- blog slides ----------

def slide_blog_cover(palette, title, hook):
    """Essay title + hook. No photo — the type is the hero, on the pastel."""
    img = ground(palette, rotate=0)
    d = ImageDraw.Draw(img)
    _wave(d, MARGIN, 116)
    _eyebrow(d, MARGIN + 80, 100, 'FROM THE JOURNAL', font(26, 600))

    f_title, lines = _fit_block(d, title, 500, COL, 560,
                                [104, 92, 80, 70, 60], 4)
    line_h = round(f_title.size * 1.1)
    hook_lines = _wrap(d, hook, font(36, 400), COL, 4) if hook else []
    hook_h = len(hook_lines) * round(36 * 1.34) + (34 if hook_lines else 0)
    block_h = len(lines) * line_h + hook_h
    y = max(300, (H - block_h) // 2 - 30)
    for line in lines:
        d.text((MARGIN, y), line, font=f_title, fill=INK)
        y += line_h
    if hook_lines:
        y += 34
        for line in hook_lines:
            d.text((MARGIN, y), line, font=font(36, 400), fill=MUTED)
            y += round(36 * 1.34)

    _footer(d, right='swipe →')
    return img


def slide_blog_passage(palette, passage, eyebrow, rotate):
    """One verbatim excerpt, set as large as it fits and vertically centred."""
    img = ground(palette, rotate=rotate)
    d = ImageDraw.Draw(img)
    _wave(d, MARGIN, 116)
    _eyebrow(d, MARGIN + 80, 100, eyebrow, font(26, 600))

    top, bottom = 250, H - 170
    f, lines = _fit_block(d, passage, 500, COL, bottom - top,
                          [64, 58, 52, 46, 40, 36, 32], 9)
    line_h = round(f.size * 1.28)
    y = top + max(0, (bottom - top - len(lines) * line_h) // 2)
    for line in lines:
        d.text((MARGIN, y), line, font=f, fill=INK)
        y += line_h

    _footer(d, right='swipe →')
    return img


def slide_blog_close(palette, title, slug, rotate):
    """Closer: the title again and the call to read it. Link in bio."""
    img = ground(palette, rotate=rotate)
    d = ImageDraw.Draw(img)
    _wave(d, MARGIN, 116)
    _eyebrow(d, MARGIN + 80, 100, 'READ THE FULL PIECE', font(26, 600))

    f_head, lines = _fit_block(d, title, 500, COL, 520, [88, 76, 66, 58], 4)
    line_h = round(f_head.size * 1.12)
    block_h = len(lines) * line_h + 90
    y = max(300, (H - block_h) // 2 - 20)
    for line in lines:
        d.text((MARGIN, y), line, font=f_head, fill=INK)
        y += line_h
    d.text((MARGIN, y + 30), 'Link in bio', font=font(42, 500), fill=ACCENT)

    _footer(d, left='soundbathcalendar.com', right=f'/{slug}')
    return img


# ---------- quote card ----------

def slide_quote(palette, line, essay_title):
    """A single 4:5 card: one line centred large, attributed. No swipe cue —
    this is a one-slide post, not a carousel."""
    img = ground(palette, rotate=0)
    d = ImageDraw.Draw(img)
    _wave(d, (W - 60) // 2, 190)

    top, bottom = 300, H - 300
    f, lines = _fit_block(d, f'“{line}”', 500, COL, bottom - top,
                          [96, 84, 74, 64, 56, 48, 42], 8)
    line_h = round(f.size * 1.2)
    y = top + max(0, (bottom - top - len(lines) * line_h) // 2)
    for ln in lines:
        w = d.textlength(ln, font=f)
        d.text(((W - w) // 2, y), ln, font=f, fill=INK)
        y += line_h

    fa = font(30, 500)
    attrib = 'soundbathcalendar.com'
    wa = d.textlength(attrib, font=fa)
    d.text(((W - wa) // 2, y + 46), attrib, font=fa, fill=ACCENT)
    if essay_title:
        fe = font(28, 400)
        et = _fit(d, f'from “{essay_title}”', fe, COL)
        we = d.textlength(et, font=fe)
        d.text(((W - we) // 2, y + 96), et, font=fe, fill=MUTED)
    return img


# ---------- captions ----------

def blog_captions(title, hook, slug):
    """Excerpt-carousel captions. The body is the essay's own hook — its
    words, not ours — and the link is the essay page."""
    url = f'{SITE_URL}/{slug}/'
    lines = [f'From the journal — {title}.']
    if hook:
        lines += ['', hook]
    body = '\n'.join(lines)
    fb = f'{body}\n\nRead the full piece: {url}'
    ig = f'{body}\n\nRead the full piece — link in bio.\n\n{BLOG_TAGS}'
    return fb, ig


def quote_captions(line, essay_title, slug):
    url = f'{SITE_URL}/{slug}/'
    body = f'“{line}”\n\n— soundbathcalendar.com'
    tail = f'in “{essay_title}”' if essay_title else 'on the calendar'
    fb = f'{body}\n\nMore {tail}: {url}'
    ig = f'{body}\n\nFrom “{essay_title}” — link in bio.\n\n{QUOTE_TAGS}'
    return fb, ig


# ---------- post builders ----------

def build_blog(events, day, quiet=False):
    """One blog-excerpt carousel for `day`: cover + up to three verbatim
    passage slides + a read-the-piece closer. Returns the manifest, or None
    when the essay can't be read or yields nothing usable."""
    slug = blog_essay_slug(day)
    try:
        html_text = _essay_html(slug)
    except OSError:
        if not quiet:
            print(f'  -- {day}: essay {slug} not found, skipping')
        return None
    title = _essay_title(html_text)
    paragraphs = _essay_paragraphs(html_text)
    hook = _essay_hook(html_text, paragraphs)
    passages = _essay_passages(paragraphs, hook, 3)
    if not title or not passages:
        if not quiet:
            print(f'  -- {day}: essay {slug} yielded no passages, skipping')
        return None

    palette = palette_for(day)
    stamp = day.isoformat()
    folder = f'img/social/{stamp}-blog'
    # A blank scratch canvas for text measurement — cheaper than rendering a
    # mesh ground just to size the eyebrow.
    eyebrow = _eyebrow_text(ImageDraw.Draw(Image.new('RGB', (W, H))),
                            title.upper(), font(26, 600), COL - 90)

    slides = [_write(slide_blog_cover(palette, title, hook), f'{folder}/01-cover.jpg')]
    for i, passage in enumerate(passages, start=2):
        slides.append(_write(slide_blog_passage(palette, passage, eyebrow, i % 4),
                             f'{folder}/{i:02d}-passage.jpg'))
    n = len(slides) + 1
    slides.append(_write(slide_blog_close(palette, title, slug, n % 4),
                         f'{folder}/{n:02d}-read.jpg'))

    fb, ig = blog_captions(title, hook, slug)
    manifest = {
        'date': stamp, 'kind': 'blog', 'palette': palette,
        'slides': slides, 'essay': slug, 'title': title,
        'landing_url': f'{SITE_URL}/{slug}/',
        'caption_facebook': fb, 'caption_instagram': ig,
    }
    _write_manifest(f'img/social/{stamp}-blog.json', manifest)
    if not quiet:
        print(f'  ok {folder} — “{title}”, {len(slides)} slides, palette {palette}')
    return manifest


def build_quote(events, day, quiet=False):
    """One single-image quote card for `day`. Always renders — the quote list
    is committed, so there is nothing to fetch and nothing to skip on."""
    line, slug = quote_for(day)
    try:
        title = _essay_title(_essay_html(slug))
    except OSError:
        title = ''

    palette = palette_for(day)
    stamp = day.isoformat()
    folder = f'img/social/{stamp}-quote'
    slides = [_write(slide_quote(palette, line, title), f'{folder}/01-quote.jpg')]

    fb, ig = quote_captions(line, title, slug)
    manifest = {
        'date': stamp, 'kind': 'quote', 'palette': palette,
        'slides': slides, 'essay': slug, 'quote': line, 'title': title,
        'landing_url': f'{SITE_URL}/{slug}/',
        'caption_facebook': fb, 'caption_instagram': ig,
    }
    _write_manifest(f'img/social/{stamp}-quote.json', manifest)
    if not quiet:
        print(f'  ok {folder} — quote from {slug}, palette {palette}')
    return manifest


def _write_manifest(rel, manifest):
    path = os.path.join(ROOT, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(manifest, fh, indent=1, ensure_ascii=False, sort_keys=True)
        fh.write('\n')


def kind_for(day):
    """One post a day, picked by weekday. The whole schedule lives in the
    POSTING SCHEDULE block near the top of this file:

        Tue   practitioner spotlight
        Thu   weekend roundup
        Sun   blog carousel / quote card, alternating weekly
        else  daily event carousel
    """
    wd = day.weekday()
    if wd == WEEKEND_WEEKDAY:
        return 'weekend'
    if wd in PRACTITIONER_WEEKDAYS:
        return 'practitioner'
    if wd == SUNDAY:
        return warm_sunday_kind(day)
    return 'daily'


def main():
    ap = argparse.ArgumentParser(description='Render the social carousel.')
    ap.add_argument('--date', help='YYYY-MM-DD (default: today, Denver)')
    ap.add_argument('--kind', choices=('daily', 'weekend', 'practitioner',
                                       'blog', 'quote', 'auto'),
                    default='auto')
    ap.add_argument('--days', type=int, default=1,
                    help='render this many consecutive days (local preview)')
    args = ap.parse_args()

    start = (date.fromisoformat(args.date) if args.date
             else datetime.now(DENVER).date())
    events = load_events()
    builders = {
        'weekend': build_weekend,
        'practitioner': build_practitioner,
        'blog': build_blog,
        'quote': build_quote,
        'daily': build_daily,
    }
    made = 0
    for i in range(max(1, args.days)):
        day = start + timedelta(days=i)
        kind = kind_for(day) if args.kind == 'auto' else args.kind
        # Best-effort: this runs mid-deploy, so a render fault must degrade to
        # "no card for that day" (the post step then no-ops), never fail the
        # site build. A missing social post is recoverable; a failed deploy is
        # the whole site down.
        try:
            built = builders[kind](events, day)
            made += built is not None
        except Exception as exc:  # noqa: BLE001 — deliberately broad
            print(f'  !! {day} ({kind}) render failed: {exc}', file=sys.stderr)
    print(f'social done — {made} post(s)')


if __name__ == '__main__':
    main()
