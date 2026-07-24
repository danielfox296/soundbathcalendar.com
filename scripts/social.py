"""Render the daily social card + captions for Sound Bath Calendar (CAL-25).

One card per day: a 1080x1350 (4:5) gradient card listing the sound baths
happening that day on the Front Range, plus the captions that go with it.
Feeds scripts/post.py, which publishes to the Facebook Page and Instagram.

WHY A GRADIENT, NOT A PHOTO: the og cards (scripts/og.py) are stock
photography with per-image provenance in img/og/SOURCES.md. A card that
regenerates every single day cannot carry a hand-checked license per run, and
an event's own `image_url` is the operator's, not ours to repost. A gradient
built from the site's own tokens is license-clean by construction and stays
recognizably ours.

WHY THIS RUNS IN CI (unlike og.py, which is local-only): the card has to exist
at a public HTTPS URL before Meta will publish it — Instagram cURLs the image
at publish time and accepts JPEG only, no byte uploads. GitHub Pages is
already that public host, so the card is built into the deploy and the poster
runs after Pages goes live. The only new CI dependency is Pillow; the font is
already vendored at scripts/assets/fonts/.

4:5, not the og cards' 1200x630: 1.91:1 is legal on Instagram but renders as a
thin strip in feed. 4:5 is the tallest portrait the feed allows.

Run from the repo root:

    python3 scripts/social.py                 # today's card
    python3 scripts/social.py --date 2026-07-25
    python3 scripts/social.py --days 5        # today + next 4 (local preview)

Writes img/social/<YYYY-MM-DD>.jpg and a .json sidecar holding the captions
and the counts. The sidecar is what post.py reads, so caption wording is a
build-time decision reviewable in the run log, never a publish-time surprise.
"""
import argparse
import json
import math
import os
import sys
from datetime import date, datetime, timedelta

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _src.lib.sessions_feed import DENVER, fmt_time, parse_iso  # noqa: E402

W, H = 1080, 1350
MARGIN = 80
COL = W - MARGIN * 2

# Site tokens (styles.css). Dark-mode values: the card is always on ink.
INK = (10, 11, 13)          # --ink
TEXT = (245, 247, 250)      # dark-mode text (#F5F7FA)
MUTED = (167, 175, 185)     # dark-mode muted (#A7AFB9)
ICE = (98, 182, 232)        # --accent (#62B6E8)
GRAD_END = (22, 56, 76)     # ink pulled toward accent — the gradient's far corner

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_PATH = os.path.join(ROOT, 'scripts', 'assets', 'fonts', 'SpaceGrotesk-VF.ttf')
FEED_CACHE = os.path.join(ROOT, 'data', 'external-events.json')
OUT_DIR = os.path.join(ROOT, 'img', 'social')

SITE_URL = 'https://soundbathcalendar.com'

# City -> its page slug. Keep in sync with external_events.CITY_ANCHOR.
CITY_SLUGS = {
    'Denver': 'denver', 'Boulder': 'boulder',
    'Fort Collins': 'fort-collins', 'Colorado Springs': 'colorado-springs',
}

NUMBER_WORDS = ['no', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven',
                'Eight', 'Nine', 'Ten', 'Eleven', 'Twelve']

# Instagram feed posts have no clickable links, so the IG caption points at the
# bio instead. Tags stay narrow and literal — the practice and the places.
IG_TAGS = ('#soundbath #soundhealing #soundbathmeditation #gongbath '
           '#singingbowls #denver #colorado #frontrange')


def _font(size, weight=400):
    f = ImageFont.truetype(FONT_PATH, size)
    f.set_variation_by_axes([weight])
    return f


# ---------- ground ----------

def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _gradient():
    """Diagonal ink -> ice-tinted ink, weighted down the frame.

    Built small and upscaled (the ramp trick og.py uses for its scrims): a
    per-pixel loop at full size is ~1.5M putpixel calls for no visible gain.
    """
    sw, sh = 96, 120
    g = Image.new('RGB', (sw, sh))
    for y in range(sh):
        for x in range(sw):
            t = (x / (sw - 1)) * 0.38 + (y / (sh - 1)) * 0.62
            g.putpixel((x, y), _lerp(INK, GRAD_END, t ** 1.25))
    return g.resize((W, H), Image.BICUBIC)


def _glow(base):
    """A soft ice bloom in the upper right — keeps the flat gradient from
    reading as a default template."""
    sw, sh = 96, 120
    mask = Image.new('L', (sw, sh))
    cx, cy = 0.80 * sw, 0.20 * sh
    r = 0.62 * sw
    for y in range(sh):
        for x in range(sw):
            d = math.hypot(x - cx, y - cy) / r
            mask.putpixel((x, y), int(38 * max(0.0, 1 - d) ** 2.0))
    base.paste(Image.new('RGB', (W, H), ICE), (0, 0), mask.resize((W, H), Image.BICUBIC))
    return base


def _ground():
    """Gradient + glow + a whisper of noise.

    The noise is dither, not texture: a smooth dark gradient is exactly what
    JPEG bands worst, and 2% of a mid-grey noise field breaks the bands up for
    about a 2-level lift in the blacks.
    """
    base = _glow(_gradient())
    noise = Image.effect_noise((W, H), 7).convert('RGB')
    return Image.blend(base, noise, 0.02)


# ---------- type ----------

def _wave(draw, x, y, width=64, amp=7, color=ICE):
    """The site's small waveform mark (same construction as og.py)."""
    pts = [(x + i, y + amp * math.sin(i / width * 2 * math.pi))
           for i in range(0, width + 1, 2)]
    draw.line(pts, fill=color, width=3)


def _eyebrow(draw, x, y, text, font, tracking=3, color=ICE):
    """Letterspaced eyebrow — PIL has no tracking of its own."""
    for ch in text:
        draw.text((x, y), ch, font=font, fill=color)
        x += draw.textlength(ch, font=font) + tracking
    return x


def _wrap(draw, text, font, max_w, max_lines):
    """Greedy wrap to max_lines, ellipsizing the last line when it overruns.

    Returns the lines. A single word longer than the column is left long
    rather than hyphenated — it only happens on pathological event names, and
    an overflow warning is louder in the run log than a silent bad break.
    """
    words, lines, cur = text.split(), [], ''
    for word in words:
        trial = f'{cur} {word}'.strip()
        if cur and draw.textlength(trial, font=font) > max_w:
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
    # Overran: ellipsize the final line to fit.
    tail = lines[-1]
    while tail and draw.textlength(tail + '…', font=font) > max_w:
        tail = tail[:-1].rstrip()
    lines[-1] = tail + '…'
    return lines


# ---------- content ----------

def load_events():
    """Approved events from the committed feed cache.

    build.py refreshes this file from the service feed at the top of every
    build and falls back to the committed copy when the fetch fails, so
    reading it here means the card sees exactly what the site rendered — one
    source of truth, and no second HTTP dependency in the deploy.
    """
    with open(FEED_CACHE, encoding='utf-8') as fh:
        feed = json.load(fh)
    return [e for e in feed.get('events', []) if e.get('status') == 'approved']


def events_on(events, day):
    """That day's approved events in Denver local time, soonest first."""
    rows = [e for e in events
            if parse_iso(e['starts_at']).astimezone(DENVER).date() == day]
    return sorted(rows, key=lambda e: parse_iso(e['starts_at']))


def _day_word(rows):
    """'tonight' only when every session is genuinely an evening one.

    The register rule the whole site runs on: never say a thing that is not
    true because it sounds better. A 10am sound bath is not tonight.
    """
    hours = [parse_iso(e['starts_at']).astimezone(DENVER).hour for e in rows]
    return 'tonight' if hours and min(hours) >= 16 else 'today'


def _headline(rows):
    n = len(rows)
    word = _day_word(rows)
    if n == 1:
        return f'One sound bath {word}'
    count = NUMBER_WORDS[n] if n < len(NUMBER_WORDS) else str(n)
    return f'{count} sound baths {word}'


def _cities(rows):
    """Distinct cities in the order they appear (soonest session first)."""
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
    return ' · '.join(cities[:3]) + ('' if len(cities) <= 3 else ' & more')


def _date_stamp(day):
    return f'{day.strftime("%A")}, {day.strftime("%B")} {day.day}'


def _date_line(day, cities, draw=None, font=None, max_w=None):
    """'Sunday, August 2 · Denver & Boulder', degraded to fit the column.

    Four cities spelled out overruns the frame, so when the full line does not
    measure we fall back to a count, then to the bare date. The footer already
    says Front Range, so losing the city list costs nothing.
    """
    stamp = _date_stamp(day)
    if not cities:
        return stamp
    candidates = [f'{stamp} · {_city_line(cities)}']
    if len(cities) > 1:
        candidates.append(f'{stamp} · {len(cities)} cities')
    candidates.append(stamp)
    if draw is None:
        return candidates[0]
    for line in candidates:
        if draw.textlength(line, font=font) <= max_w:
            return line
    return stamp


def _where_line(draw, event, font, max_w):
    """'Venue · City', ellipsizing the VENUE so the city always survives.

    Truncating the whole string left rows reading 'Rocky Mountain Restore &
    Stretch LLC · Fort…' — the city is the one field a scroller actually
    filters on, so it is the last thing to go.
    """
    venue, city = (event.get('venue') or '').strip(), (event.get('city') or '').strip()
    if not venue:
        return city
    if not city:
        full = venue
    else:
        full = f'{venue} · {city}'
    if draw.textlength(full, font=font) <= max_w:
        return full
    if not city:
        while venue and draw.textlength(venue + '…', font=font) > max_w:
            venue = venue[:-1].rstrip()
        return venue + '…'
    tail = f' · {city}'
    room = max_w - draw.textlength(tail, font=font)
    while venue and draw.textlength(venue + '…', font=font) > room:
        venue = venue[:-1].rstrip()
    return (venue + '…' if venue else city) + (tail if venue else '')


def _landing_url(cities):
    """One link, not one per event: a single city page when the whole day is
    one city, the calendar root otherwise."""
    if len(cities) == 1 and cities[0] in CITY_SLUGS:
        return f'{SITE_URL}/{CITY_SLUGS[cities[0]]}/'
    return f'{SITE_URL}/'


# ---------- the card ----------

def render(day, rows, path):
    """Draw one day's card. Returns how many sessions actually fit on it."""
    img = _ground()
    d = ImageDraw.Draw(img)

    f_eyebrow = _font(26, 600)
    f_date = _font(38, 500)
    f_foot = _font(30, 500)

    # Masthead.
    _wave(d, MARGIN, 100)
    _eyebrow(d, MARGIN + 84, 86, 'SOUND BATH CALENDAR', f_eyebrow)

    cities = _cities(rows)
    d.text((MARGIN, 176), _date_line(day, cities, d, f_date, COL),
           font=f_date, fill=MUTED)

    # Headline: try the big size, step down once rather than run to 3 lines.
    headline = _headline(rows)
    f_head = _font(94, 500)
    lines = _wrap(d, headline, f_head, COL, 3)
    if len(lines) > 2:
        f_head = _font(78, 500)
        lines = _wrap(d, headline, f_head, COL, 2)
    y = 248
    for line in lines:
        d.text((MARGIN, y), line, font=f_head, fill=TEXT)
        y += round(f_head.size * 1.14)

    y += 34
    d.line([(MARGIN, y), (W - MARGIN, y)], fill=(58, 74, 88), width=2)
    y += 52

    # Session list. Measure-then-fit: drop the last session (into a "+N more"
    # line) until the block clears the footer, so a heavy night degrades to a
    # shorter card instead of overprinting it.
    #
    # The type scale moves with the count, which is the whole trick. A busy
    # day wants a tight, scannable list of four; a one-session day wants that
    # session set large, with its price, like a poster. Centring a single
    # small row in 600px of empty gradient read as a rendering fault rather
    # than as calm.
    list_top = y
    foot_y = H - 118
    avail = (foot_y - 34) - 28 - list_top
    name_w = COL - 190

    # count -> (time size, name size, venue size, name lines, gap)
    SCALE = {
        1: (54, 64, 36, 2, 0),
        2: (48, 56, 33, 2, 54),
        3: (40, 46, 30, 1, 40),
        4: (40, 46, 30, 1, 30),
    }

    def block(count):
        """Lay out `count` sessions; return (height, lines, fonts, metrics)."""
        t_sz, n_sz, v_sz, max_lines, gap = SCALE[count]
        fonts = (_font(t_sz, 600), _font(n_sz, 500), _font(v_sz, 400))
        line_h = round(n_sz * 1.22)
        # Measured, not guessed: the time column has to hold '10:00 am' at
        # whatever size this count selected, or the hero scale runs the time
        # straight into the session name.
        time_col = round(max(d.textlength(fmt_time(e['starts_at']).lower(), font=fonts[0])
                             for e in rows[:count]) + 30)
        width = COL - time_col
        h, laid = 0, []
        for i, e in enumerate(rows[:count]):
            name_lines = _wrap(d, e['name'], fonts[1], width, max_lines)
            price = (e.get('price') or '').strip() if count <= 2 else ''
            laid.append((name_lines, price))
            h += len(name_lines) * line_h + v_sz + 16
            if price:
                h += v_sz + 12
            if i < count - 1:
                h += gap
        return h, laid, fonts, (line_h, time_col, width)

    shown = min(4, len(rows))
    while True:
        height, laid, fonts, metrics = block(shown)
        extra = 46 if shown < len(rows) else 0
        if shown <= 1 or height + extra <= avail:
            break
        shown -= 1
    f_time, f_name, f_venue = fonts
    line_h, time_col, name_w = metrics
    extra = 46 if shown < len(rows) else 0

    y = list_top + max(0, (avail - height - extra) // 2)

    for e, (name_lines, price) in zip(rows[:shown], laid):
        d.text((MARGIN, y + 4), fmt_time(e['starts_at']).lower(),
               font=f_time, fill=ICE)
        ny = y
        for line in name_lines:
            d.text((MARGIN + time_col, ny), line, font=f_name, fill=TEXT)
            ny += line_h
        d.text((MARGIN + time_col, ny + 6), _where_line(d, e, f_venue, name_w),
               font=f_venue, fill=MUTED)
        ny += f_venue.size + 16
        if price:
            d.text((MARGIN + time_col, ny), price, font=f_venue, fill=ICE)
            ny += f_venue.size + 12
        y = ny + SCALE[shown][4]

    if shown < len(rows):
        rest = len(rows) - shown
        d.text((MARGIN + time_col, y - SCALE[shown][4] + 14),
               f'+{rest} more on the site', font=f_venue, fill=ICE)

    # Footer.
    d.line([(MARGIN, foot_y - 34), (W - MARGIN, foot_y - 34)],
           fill=(58, 74, 88), width=2)
    d.text((MARGIN, foot_y), 'soundbathcalendar.com', font=f_foot, fill=ICE)
    right = 'Front Range, Colorado'
    d.text((W - MARGIN - d.textlength(right, font=f_foot), foot_y),
           right, font=f_foot, fill=MUTED)

    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    # JPEG because Instagram publishes JPEG only — not a size decision.
    img.save(path, 'JPEG', quality=90, optimize=True, progressive=True)
    return shown


# ---------- captions ----------

def _session_lines(rows, limit=6):
    out = []
    for e in rows[:limit]:
        where = ' · '.join(x for x in (e.get('venue'), e.get('city')) if x)
        out.append(f'{fmt_time(e["starts_at"]).lower()} — {e["name"]} · {where}')
    if len(rows) > limit:
        out.append(f'+{len(rows) - limit} more')
    return out


def captions(day, rows):
    """Facebook and Instagram captions for the day.

    They differ on exactly one axis, and it is a platform limit rather than a
    voice choice: Instagram feed captions render URLs as plain text, so the
    link lives on the Facebook post and Instagram points at the bio.
    """
    head = _headline(rows)
    stamp = f'{day.strftime("%A")}, {day.strftime("%B")} {day.day}'
    body = '\n'.join(_session_lines(rows))
    url = _landing_url(_cities(rows))

    fb = (f'{head} — {stamp}\n\n{body}\n\n'
          f'Times, tickets and directions: {url}')
    ig = (f'{head} — {stamp}\n\n{body}\n\n'
          f'Full calendar — link in bio.\n\n{IG_TAGS}')
    return fb, ig


# ---------- driver ----------

def build_day(events, day, quiet=False):
    """Render one day and write its sidecar. Returns the manifest, or None
    when the day is empty.

    An empty day writes nothing at all. Posting a card that says "no sound
    baths today" would be worse than silence — it trains the feed to ignore
    us, and the honest answer is that some Tuesdays are quiet.
    """
    rows = events_on(events, day)
    stamp = day.isoformat()
    if not rows:
        if not quiet:
            print(f'  -- {stamp}: no approved sessions, skipping')
        return None

    rel = f'img/social/{stamp}.jpg'
    shown = render(day, rows, os.path.join(ROOT, rel))
    fb, ig = captions(day, rows)
    manifest = {
        'date': stamp,
        'image_url': f'{SITE_URL}/{rel}',
        'image_path': rel,
        'event_count': len(rows),
        'shown_on_card': shown,
        'cities': _cities(rows),
        'landing_url': _landing_url(_cities(rows)),
        'caption_facebook': fb,
        'caption_instagram': ig,
    }
    with open(os.path.join(ROOT, f'img/social/{stamp}.json'), 'w',
              encoding='utf-8') as fh:
        json.dump(manifest, fh, indent=1, ensure_ascii=False, sort_keys=True)
        fh.write('\n')
    if not quiet:
        print(f'  ok {rel} — {len(rows)} session(s), {shown} on card')
    return manifest


def main():
    ap = argparse.ArgumentParser(description='Render daily social cards.')
    ap.add_argument('--date', help='YYYY-MM-DD (default: today, Denver)')
    ap.add_argument('--days', type=int, default=1,
                    help='render this many consecutive days (default 1)')
    args = ap.parse_args()

    start = (date.fromisoformat(args.date) if args.date
             else datetime.now(DENVER).date())
    events = load_events()
    made = 0
    for i in range(max(1, args.days)):
        if build_day(events, start + timedelta(days=i)):
            made += 1
    print(f'social done — {made} card(s)')


if __name__ == '__main__':
    main()
