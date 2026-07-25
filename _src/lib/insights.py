"""Sound Bath Calendar — "State of Sound Healing on the Front Range" (CAL-06).

The flagship original-data report: /state-of-sound-healing/. A DISCOVERY-LAYER
asset — built to be cited by search, AI answer engines, and press, and kept out
of the primary participant nav (footer + llms.txt + sitemap only).

Design choice that matters: each edition is FROZEN. The build never recomputes
figures from the live feed — it renders a committed edition JSON emitted by
marketing/scripts/state_of_sound_healing.py (the single source of truth). That
keeps a cited stat stable forever and keeps CI hermetic (no recompute, like the
geocode cache the map uses). New quarter -> emit a new edition JSON, commit it.

Layout: full-bleed alternating bands (paper / white / ink) so sections read as
distinct rooms — a full-width hero photo, a dark "by the numbers" band, and a
dark pull-quote as its mirror. Charts and stat figures animate in on scroll via
a small inline script (progressive enhancement: no JS or reduced-motion means
everything simply renders complete). Images carry width/height attributes AND
height:auto/aspect-ratio in CSS, so nothing ever stretches.

build.py owns page assembly + JSON-LD; this module loads editions and returns
the <main> body + the page's <head> style block. Every dynamic string is escaped
here.
"""

import json
import os

from _src.lib import external_events as X

EDITIONS_REL_DIR = os.path.join('data', 'insights')
_esc = X._esc


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def load_editions(repo_root, log=print):
    """All committed edition JSONs, newest window first. Never raises — a bad or
    missing file just means that edition is skipped (the page is gated on there
    being at least one valid edition, checked by the caller)."""
    d = os.path.join(repo_root, EDITIONS_REL_DIR)
    editions = []
    try:
        names = sorted(os.listdir(d))
    except FileNotFoundError:
        return []
    for name in names:
        if not name.endswith('.json'):
            continue
        try:
            with open(os.path.join(d, name), encoding='utf-8') as f:
                agg = json.load(f)
            # minimal shape check
            agg['edition']['slug']
            agg['volume']['sessions']
            editions.append(agg)
        except Exception as exc:
            log(f'  ⚠ insights edition {name} unusable ({exc.__class__.__name__}) — skipped')
    editions.sort(key=lambda a: a['edition'].get('window_end', ''), reverse=True)
    return editions


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------
def _bar_rows(items):
    """items: list of (label, value, display). Bars scale to the max value and
    carry their target width in --w so the scroll-in animation can grow them."""
    mx = max((v for _, v, _ in items), default=1) or 1
    out = []
    for label, value, disp in items:
        pct = max(3, round(value / mx * 100))
        out.append(
            f'        <div class="soh-row"><span class="soh-row__name">{_esc(label)}</span>'
            f'<span class="soh-row__track"><span class="soh-row__fill" style="--w:{pct}%"></span></span>'
            f'<span class="soh-row__val">{_esc(disp)}</span></div>')
    return '\n'.join(out)


def _fmt_window(ed):
    """'Jul 19 – Aug 11, 2026' from ISO window bounds."""
    from datetime import date
    try:
        a = date.fromisoformat(ed['window_start'])
        b = date.fromisoformat(ed['window_end'])
    except Exception:
        return ''
    mon = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep',
           'Oct', 'Nov', 'Dec']
    return f'{mon[a.month]} {a.day} – {mon[b.month]} {b.day}, {b.year}'


def render_report(agg, nav_prefix, other_editions):
    """Return the <main> body for one edition. `other_editions` is the list of
    OTHER editions (for the archive block); empty on the first edition."""
    ed, vol, pr = agg['edition'], agg['volume'], agg['price']
    geo, tim, mod = agg['geography'], agg['timing'], agg['modality']
    window = _fmt_window(ed)
    cp = nav_prefix  # css/asset prefix

    # ---- Stat tiles (the citable set) — CAL-36 data monuments. Plain text:
    # the [data-n] count-up spans went with the scroll-reveal script. ----
    tiles = [
        (f'~{round(vol["per_week"])}<span class="u">/wk</span>',
         'sound bath sessions across the Front Range'),
        (f'<span class="u">$</span>{pr["median"]:g}',
         f'median ticket price (${pr["low"]:g}–${pr["high"]:g} range)'),
        ('1<span class="u">in</span>3',
         'known-price sessions are free or by donation'),
        (f'{tim["evening_pct"]:.0f}<span class="u">%</span>',
         'start after 5 p.m. — a weeknight ritual'),
        (f'{vol["venues"]}',
         f'venues · {vol["operators"]} operators · {vol["cities"]} metros'),
        (f'~{geo["corridor_miles"]}<span class="u">mi</span>',
         'north–south corridor, FoCo to the Springs'),
    ]
    tiles_html = '\n'.join(
        f'        <div class="soh-stat"><div class="soh-stat__fig">{fig}</div>'
        f'<div class="soh-stat__lab">{_esc(lab)}</div></div>'
        for fig, lab in tiles)

    # ---- Busiest venues table ----
    vrows = []
    mxv = vol['busiest_venues'][0]['count'] if vol['busiest_venues'] else 1
    for b in vol['busiest_venues']:
        loc = f' · {b["city"]}' if b.get('city') else ''
        w = max(8, round(b['count'] / mxv * 100))
        vrows.append(
            f'            <tr><td class="soh-bc">{_esc(b["venue"])}{_esc(loc)}'
            f'<span class="soh-mini" style="width:calc({w}% - 40px)"></span></td>'
            f'<td class="soh-num">{b["count"]}</td></tr>')
    vrows_html = '\n'.join(vrows)

    # ---- Metro + day-of-week bars ----
    metro_items = [(name, pct, f'{pct:.0f}%') for name, _c, pct in geo['metros']]
    metro_items.sort(key=lambda t: t[1], reverse=True)
    metro_bars = _bar_rows(metro_items)
    dow_sorted = sorted(tim['dow'], key=lambda t: t[1], reverse=True)
    dow_bars = _bar_rows([(d, c, str(c)) for d, c in dow_sorted])

    # ---- Timing prose ----
    tt = tim['top_times']
    times_str = ', then '.join(f'{t} ({c})' for t, c in tt[1:]) if len(tt) > 1 else ''
    top_time = tt[0][0] if tt else ''
    top_time_ct = tt[0][1] if tt else 0

    # ---- Editions block. The hub passes every edition (the one on display
    # included) so each dated permalink always has an internal link — never an
    # orphan (CAL-32 D1); edition permalinks still pass just the others. ----
    if other_editions:
        links = '\n'.join(
            f'          <li><a href="{cp}state-of-sound-healing/{_esc(o["edition"]["slug"])}/">'
            f'{_esc(o["edition"]["label"])}</a> — {_esc(_fmt_window(o["edition"]))}</li>'
            for o in other_editions)
        archive = (f'      <section class="soh-archive">\n'
                   f'        <p class="soh-kicker">Editions</p>\n'
                   f'        <ul>\n{links}\n        </ul>\n      </section>')
    else:
        archive = ('      <p class="soh-firstnote">This is the first edition. As new '
                   'quarters are published, past editions will be archived here — '
                   'and once two or more exist, so will genuine trend data.</p>')

    free_pct = pr['free_or_flex_pct']

    body = f"""<div class="soh" id="soh">

  <section class="soh-band soh-band--paper soh-band--mast">
    <div class="soh-wrap">
      <h1 class="soh-h1">The Front Range Sound Bath Scene: <span class="soh-h1__accent">A {_esc(ed['label'])} Snapshot</span></h1>
      <p class="soh-dek">The first count of a quietly widespread ritual — every public sound bath across Denver, Boulder, Fort Collins, and Colorado Springs. A <em>point-in-time snapshot</em>, not a trend: simply what is verifiably true of the calendar right now.</p>
      <div class="soh-meta">
        <span>Source · <b>Sound Bath Calendar</b></span>
        <span>Window · <b>{_esc(window)}</b></span>
        <span>Sessions · <b>{vol['sessions']}</b></span>
        <span>Every figure reproducible</span>
      </div>
    </div>
  </section>

  <figure class="soh-hero">
    <img src="{cp}img/cards/hero-state-of-sound-i.jpg" width="1600" height="900" alt="The Flatirons rising over open grassland in Boulder County, Colorado — the Front Range foothills." fetchpriority="high">
    <figcaption class="soh-hero__credit">The Front Range foothills, Boulder County · CC0, Mike Pascoe / <a href="https://commons.wikimedia.org/w/index.php?curid=176702599" rel="nofollow">Wikimedia Commons</a></figcaption>
  </figure>

  <section class="soh-band soh-band--ink" id="numbers">
    <div class="soh-wrap">
      <p class="soh-kicker">By the numbers</p>
      <h2 class="soh-h2">The citable stats</h2>
      <p class="soh-intro">Each figure maps directly to a session on the calendar — nothing modeled, nothing projected.</p>
      <div class="soh-stats">
{tiles_html}
      </div>
    </div>
  </section>

  <section class="soh-band soh-band--paper">
    <div class="soh-wrap">
      <p class="soh-kicker">Volume</p>
      <h2 class="soh-h2">About {round(vol['per_week'])} sessions a week — more than most residents would guess</h2>
      <p class="soh-lead">In the window measured, the calendar carried <b>{vol['sessions']} approved sessions over {ed['span_days']} days</b> — an average of {vol['per_week']:g} per week. Sound baths aren't a rare, seek-it-out event here; on a typical week you have your pick of roughly three a day, in four cities.</p>
      <p>The volume is spread across many small hosts: <b>{vol['venues']} venues and {vol['operators']} operators</b>. The scene isn't dominated by one or two big studios — the most active single host accounts for {vol['busiest_venues'][0]['count'] if vol['busiest_venues'] else 0} sessions in the window, and the rest is a long tail of one- and two-session operators. A cottage ecosystem of independent facilitators, not a chain.</p>
      <div class="soh-tbl-scroll">
        <table class="soh-tbl">
          <thead><tr><th>Busiest venues in the window</th><th class="soh-num">Sessions</th></tr></thead>
          <tbody>
{vrows_html}
          </tbody>
        </table>
      </div>
    </div>
  </section>

  <section class="soh-band soh-band--white">
    <div class="soh-wrap">
      <p class="soh-kicker">Price</p>
      <h2 class="soh-h2">A ${pr['median']:g} median — and about a third are free or by donation</h2>
      <div class="soh-split">
        <figure class="soh-split__fig">
          <img src="{cp}img/cards/fig-singing-bowls-i.jpg" width="1200" height="800" alt="Overhead view of a set of Tibetan singing bowls and mallets on a plain surface." loading="lazy">
          <figcaption class="soh-credit">CC0 via rawpixel</figcaption>
        </figure>
        <div class="soh-split__body">
          <p>Of the {pr['known_model']} sessions with a <b>known access model</b>, the middle 50% of paid tickets land in a tight band — <b>${pr['q1']:g} to ${pr['q3']:g}</b> — with a full parseable range of ${pr['low']:g} to ${pr['high']:g}.</p>
          <p>Underneath the median sits the more human finding: <b>roughly one in three ({free_pct:.0f}%) is free, or offered by donation or sliding scale.</b> A meaningful share is priced to be open to anyone.</p>
        </div>
      </div>
      <div class="soh-note">
        <h3>The honest caveat on price</h3>
        <p>{pr['unpriced']} of {vol['sessions']} listings ({pr['unpriced_pct']:.0f}%) carry no stated price in the source — often free community or church-hosted gatherings. The figures above describe the priced-and-stated portion of the calendar. We report the median, not the average, so a few higher-priced sessions don't misrepresent the typical experience.</p>
      </div>
    </div>
  </section>

  <section class="soh-band soh-band--paper">
    <div class="soh-wrap">
      <p class="soh-kicker">Geography</p>
      <h2 class="soh-h2">Four metros, evenly shared — a regional scene, not a Denver one</h2>
      <div class="soh-cols">
        <div>
          <p>Denver anchors the calendar, but the notable finding is how evenly the rest distributes. Colorado Springs and Fort Collins each carry a fifth or more — well above what their relative size would predict.</p>
          <p>Mapping the venues confirms the reach: located sessions span a <b>~{geo['corridor_miles']}-mile north–south corridor</b>, from Fort Collins down to Colorado Springs, tracking the I-25 population spine of the state. <a href="{cp}map/">See them on the map →</a></p>
        </div>
        <div class="soh-chart" role="img" aria-label="Session share by metro: Denver 40 percent, Colorado Springs 24 percent, Fort Collins 20 percent, Boulder 16 percent.">
{metro_bars}
        </div>
      </div>
    </div>
  </section>

  <section class="soh-band soh-band--white">
    <div class="soh-wrap">
      <p class="soh-kicker">Timing</p>
      <h2 class="soh-h2">An evening ritual, peaking Friday at 7&nbsp;p.m.</h2>
      <div class="soh-cols">
        <div>
          <p>Sound baths are overwhelmingly an after-work wind-down: <b>{tim['evening_pct']:.0f}% start at 5&nbsp;p.m. or later</b>, and just {tim['morning_pct']:.0f}% are morning sessions. The single most common start time is <b>{_esc(top_time)}</b> ({top_time_ct} sessions){', then ' + _esc(times_str) if times_str else ''}.</p>
          <p>Weekends carry about {tim['weekend_pct']:.0f}% of the week's sessions — most sound baths happen on <b>weeknights</b>, a midweek reset rather than a weekend outing. For a curious first-timer: a weeknight around 7&nbsp;p.m. gives you the most to choose from.</p>
        </div>
        <div class="soh-chart" role="img" aria-label="Sessions by day of week: Friday 15, Sunday 14, Wednesday 13, Saturday 9, Monday 8, Tuesday 8, Thursday 8.">
{dow_bars}
        </div>
      </div>
    </div>
  </section>

  <section class="soh-band soh-band--paper">
    <div class="soh-wrap">
      <p class="soh-kicker">Modality mix</p>
      <h2 class="soh-h2">Not yet a reliable number — and we won't pretend otherwise</h2>
      <p>It's tempting to report which <em>kinds</em> of sound healing dominate — gong baths versus crystal bowls versus breathwork-with-sound. We're choosing not to, yet.</p>
      <div class="soh-note">
        <h3>Why this figure is deferred</h3>
        <p>Nearly half of sessions ({mod['only_base_pct']:.0f}%) are currently tagged only with the general "sound bath" label. Any modality breakdown would reflect how thoroughly listings have been tagged, not what's happening in the sessions themselves. As the calendar's tagging matures, this becomes a genuinely interesting figure — and a natural addition to the next edition.</p>
      </div>
    </div>
  </section>

  <section class="soh-band soh-band--ink soh-band--pull">
    <div class="soh-wrap">
      <p class="soh-pull">A cottage scene of <b>independent facilitators</b> — {vol['venues']} venues, {vol['operators']} operators, a {geo['corridor_miles']}-mile corridor — where the median session costs <b>${pr['median']:g}</b> and about one in three is free.</p>
    </div>
  </section>

  <section class="soh-band soh-band--white soh-band--method">
    <div class="soh-wrap">
      <p class="soh-kicker">Methodology &amp; caveats</p>
      <h2 class="soh-h2">How these numbers were made</h2>
      <ul class="soh-list">
        <li><b>Source.</b> Every figure derives from the public sessions on Sound Bath Calendar, from a data snapshot taken {_esc(ed['generated_at'][:10])}. The stdlib-Python analysis script is public — anyone can reproduce every number.</li>
        <li><b>Data window.</b> Sessions starting between {_esc(window)} — a forward-looking window of {ed['span_days']} days. This is every session approved and listed as of the snapshot date, not a full census of every sound bath that occurred.</li>
        <li><b>A snapshot, not a trend.</b> The calendar is young. There is no year-over-year or growth data here, and none is implied. This edition is the baseline; its value compounds as future editions become comparable.</li>
        <li><b>Price parsing.</b> Prices are free-text from operator listings ("$39", "Donation", "$15–40", "From $44.52"). Ranges use the midpoint. {pr['unpriced_pct']:.0f}% of listings carry no stated price, so price statistics describe only the priced-and-stated subset. Medians resist high outliers.</li>
        <li><b>Venue &amp; operator counts</b> are distinct name strings; a few are near-duplicate variants, so the true count of physical spaces is slightly lower. We flag it rather than silently merge.</li>
        <li><b>Excluded.</b> Private or invite-only sessions, sessions outside the four covered metros, and any listing not approved for the public calendar.</li>
      </ul>
      <div class="soh-cite">
        <b>How to cite:</b> Sound Bath Calendar, <i>The Front Range Sound Bath Scene: A {_esc(ed['label'])} Snapshot</i> ({_esc(ed['label'])}), soundbathcalendar.com/state-of-sound-healing/.<br>Figures reflect sessions listed as of {_esc(ed['generated_at'][:10])}. Photography public domain (CC0) via Wikimedia Commons and rawpixel.
      </div>
{archive}
      <p class="soh-press">Writing about wellness on the Front Range? These figures are free to cite. Questions or a correction — <a href="{cp}">see the calendar</a>.</p>
    </div>
  </section>
</div>
"""
    return body


# CAL-36: the IntersectionObserver scroll-reveal is retired. The report is a
# citable artifact — crawlers, print, and readers who scroll fast all get the
# same complete page, with nothing depending on a viewport event to become
# visible. Bars are drawn at their real width; figures render as text.


# ---------------------------------------------------------------------------
# Page <head> styles — namespaced under .soh so nothing leaks into styles.css.
# Reuses the site design tokens defined there (--ink, --paper, --accent,
# --line, --ink-rgb, --font-display, --font-body; its ice accents are its own
# --soh-* values, frozen until CAL-36). Full-bleed
# alternating bands (paper / white / ink) differentiate sections; images keep
# their intrinsic ratio (height:auto / explicit object-fit) so nothing
# stretches; the stat grid uses explicit 3/2/1 columns so tiles always fill the
# row cleanly at every width.
# ---------------------------------------------------------------------------
INSIGHTS_HEAD = """<style>
  /* The report in the v5 Broadcast register (CAL-36). The --soh-* ice palette
     is retired: this page now rides the site tokens like everything else, so
     the dark scheme flips it for free — and the legacy #0A0B0D ink band, which
     was hardcoded in BOTH schemes and read as a dead near-black slab on the
     night ground, is gone with it. Two grounds only: --paper and --surface.
     Radius 0 throughout (the doctrine); no blur, no pills, no gradients.
     Namespaced under .soh so nothing leaks into styles.css. */
  .soh :is(h1,h2,h3) { font-family: var(--font-display); font-weight: 800; font-stretch: 72%; letter-spacing: -0.005em; text-transform: uppercase; }
  .soh p { line-height: 1.65; }
  .soh a { color: var(--signal-text); text-decoration: underline; text-underline-offset: 3px; }

  /* ---- Bands: full-bleed rooms, alternating the two committed grounds ---- */
  .soh-band { padding: clamp(3.2rem, 6vw, 5.5rem) 0; }
  .soh-band--paper { background: var(--paper); }
  /* The former "white" band: same ground, held apart by rules instead of a
     third surface value (there is no third ground in v5). */
  .soh-band--white { background: var(--paper); border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
  /* The former "ink" band. --surface flips with the scheme, so the stats band
     reads as a raised block on both grounds instead of a permanent near-black. */
  .soh-band--ink { background: var(--surface); color: var(--surface-text); }
  .soh-band--ink a { color: var(--surface-text); }
  .soh-band--ink b { color: var(--surface-text); }
  .soh-wrap { max-width: 71rem; margin: 0 auto; padding: 0 clamp(20px, 4vw, 40px); }

  /* ---- Masthead ---- */
  .soh-band--mast { padding-top: clamp(2.4rem, 5vw, 4rem); padding-bottom: clamp(2.6rem, 5vw, 4rem); }
  .soh-h1 { font-size: clamp(38px, 6.4vw, 84px); line-height: 0.95; margin: 0 0 22px; max-width: 20ch; }
  /* The accent half of the title is the same ink — the title is one monument,
     not two colours (the coral budget is slabs + marks, never headline text). */
  .soh-h1__accent { color: inherit; }
  .soh-dek { font-size: clamp(18px, 2.2vw, 24px); line-height: 1.4; color: var(--ink); max-width: 42rem; margin: 0 0 30px; }
  .soh-dek em { font-style: normal; border-bottom: 3px solid var(--signal); }
  .soh-meta { display: flex; flex-wrap: wrap; gap: 10px 26px; font-size: 14px;
    color: var(--muted); padding-top: 18px; border-top: 2px solid var(--ink); font-variant-numeric: tabular-nums; }
  .soh-meta b { color: var(--ink); font-weight: 700; }

  /* ---- Full-bleed hero (the committed duotone — CAL-36) ---- */
  .soh-hero { margin: 0; position: relative; }
  .soh-hero img { display: block; width: 100%; height: clamp(300px, 52vw, 540px);
    object-fit: cover; object-position: center 62%; }
  .soh-hero__credit { position: absolute; right: 0; bottom: 0;
    font-size: 12px; color: var(--surface-text); background: var(--surface);
    padding: 6px 12px; }
  .soh-hero__credit a { color: var(--surface-text); }

  /* ---- Section furniture: caps 13, ZERO tracking (the tracking law) ---- */
  .soh-kicker { font: 700 13px/1.2 var(--font-body); letter-spacing: 0;
    text-transform: uppercase; color: var(--muted); margin: 0 0 14px;
    display: flex; align-items: center; gap: 14px; }
  .soh-kicker::after { content:""; flex: 1; height: 1px; background: var(--line); }
  .soh-band--ink .soh-kicker { color: rgba(var(--surface-text-rgb), 0.78); }
  .soh-band--ink .soh-kicker::after { background: rgba(var(--surface-text-rgb), 0.24); }
  .soh-h2 { font-size: clamp(26px, 3.6vw, 44px); line-height: 1.0; margin: 0 0 18px; max-width: 26ch; }
  .soh p { max-width: 640px; }
  .soh-lead { font-size: 19px; }
  .soh-intro { color: rgba(var(--surface-text-rgb), 0.78); }

  /* ---- The stat grid: DATA MONUMENTS. The numerals are the largest type on
         the page after the H1 — the report reads like a broadcast rundown. ---- */
  .soh-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0; margin-top: 34px; border-top: 1px solid rgba(var(--surface-text-rgb), 0.24); }
  @media (max-width: 899px) { .soh-stats { grid-template-columns: repeat(2, 1fr); } }
  @media (max-width: 519px) { .soh-stats { grid-template-columns: 1fr; } }
  .soh-stat { padding: 22px 22px 26px 0; border-bottom: 1px solid rgba(var(--surface-text-rgb), 0.24); }
  .soh-stat__fig { font-family: var(--font-display); font-weight: 800; font-stretch: 62%;
    font-size: clamp(56px, 7vw, 96px); line-height: 0.9; letter-spacing: -0.01em;
    color: var(--surface-text); font-variant-numeric: tabular-nums; }
  .soh-stat__fig .u { font-size: .34em; font-stretch: 72%; }
  .soh-stat__lab { margin-top: 12px; font-size: 15px; color: rgba(var(--surface-text-rgb), 0.78); line-height: 1.45; max-width: 22ch; }

  /* ---- Two-column prose + chart ---- */
  .soh-cols { display: grid; grid-template-columns: 1fr; gap: 34px 56px; align-items: center; margin-top: 8px; }
  @media (min-width: 860px) { .soh-cols { grid-template-columns: 1fr 1fr; } }

  /* ---- Bars: ink fills on an ink-tint track, drawn at their real width ---- */
  .soh-chart { display: grid; gap: 10px; }
  .soh-row { display: grid; grid-template-columns: 118px 1fr 44px; align-items: center; gap: 14px; }
  .soh-row__name { font: 700 13px/1.2 var(--font-body); letter-spacing: 0; text-transform: uppercase; color: var(--muted); text-align: right; }
  .soh-row__track { background: rgba(var(--ink-rgb), 0.10); height: 24px; overflow: hidden; }
  .soh-row__fill { display: block; height: 100%; background: var(--ink); width: var(--w); }
  .soh-row__val { font: 700 15px var(--font-body); text-align: right; color: var(--ink);
    font-variant-numeric: tabular-nums; }
  @media (max-width: 560px) { .soh-row { grid-template-columns: 96px 1fr 38px; gap: 10px; }
    .soh-row__name { font-size: 12px; } }

  /* ---- Table ---- */
  .soh-tbl-scroll { overflow-x: auto; margin-top: 28px; border-top: 2px solid var(--ink); }
  .soh-tbl { border-collapse: collapse; width: 100%; min-width: 360px; font-size: 16px; }
  .soh-tbl th, .soh-tbl td { text-align: left; padding: 13px 20px 13px 0; border-bottom: 1px solid var(--line); }
  .soh-tbl th { font: 700 13px/1.2 var(--font-body); letter-spacing: 0;
    text-transform: uppercase; color: var(--muted); }
  .soh-num { text-align: right; font-weight: 700; font-variant-numeric: tabular-nums; }
  .soh-bc { position: relative; }
  .soh-mini { position: absolute; left: 0; bottom: 5px; height: 3px;
    background: var(--signal); opacity: .85; }

  /* ---- Split figure (price) — aspect preserved, never stretched ---- */
  .soh-split { display: grid; grid-template-columns: 1fr; gap: 30px; align-items: center; margin-top: 8px; }
  @media (min-width: 780px) { .soh-split { grid-template-columns: 1.05fr 1fr; } }
  .soh-split__fig { margin: 0; }
  .soh-split__fig img { display: block; width: 100%; height: auto; aspect-ratio: 3 / 2;
    object-fit: cover; }
  .soh-split__body > p:first-child { margin-top: 0; }
  .soh-credit { font-size: 12px; color: var(--muted); margin-top: 8px; }

  /* ---- Note / callout: the honest caveats, on the ink rule ---- */
  .soh-note { border-left: 3px solid var(--ink); padding: 0.2rem 0 0.2rem 1.1rem;
    margin-top: 28px; max-width: 640px; }
  .soh-note h3 { font-size: 18px; margin: 0 0 8px; }
  .soh-note p { margin: 0; font-size: 16px; color: var(--ink); }

  /* ---- Pull band ---- */
  .soh-band--pull { padding: clamp(3.2rem, 6vw, 5rem) 0; }
  .soh-pull { font-family: var(--font-display); font-weight: 800; font-stretch: 72%;
    font-size: clamp(26px, 3.8vw, 46px); line-height: 1.05; text-transform: uppercase;
    margin: 0; max-width: 24ch; color: var(--surface-text); }
  .soh-pull b { color: var(--surface-text); font-weight: 800; }
  .soh-band--pull p { max-width: none; }

  /* ---- Methodology ---- */
  .soh-band--method { border-bottom: 0; }
  .soh-list { max-width: 640px; padding-left: 0; list-style: none; display: grid; gap: 14px; margin-top: 6px; }
  .soh-list li { position: relative; padding-left: 22px; font-size: 16px;
    color: var(--ink); line-height: 1.6; }
  .soh-list li::before { content:""; position: absolute; left: 0; top: 9px;
    width: 8px; height: 8px; background: var(--signal); }
  .soh-list li b { color: var(--ink); }
  .soh-cite { font-size: 14px; line-height: 1.7; color: var(--muted);
    border: 1px solid var(--line); padding: 18px 22px; margin-top: 28px; max-width: 640px; }
  .soh-cite b { color: var(--ink); }
  .soh-archive { padding-top: 38px; }
  .soh-archive ul { list-style: none; padding: 0; display: grid; gap: 8px; }
  .soh-firstnote, .soh-press { max-width: 640px; font-size: 15px; color: var(--muted);
    margin-top: 28px; }
</style>"""
