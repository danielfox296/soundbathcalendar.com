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

    # ---- Stat tiles (the citable set). Pure numbers sit in [data-n] spans so
    # the count-up can animate them; everything renders complete without JS. ----
    tiles = [
        (f'~<span data-n="{round(vol["per_week"])}">{round(vol["per_week"])}</span><span class="u">/wk</span>',
         'sound bath sessions across the Front Range'),
        (f'<span class="u">$</span><span data-n="{pr["median"]:g}">{pr["median"]:g}</span>',
         f'median ticket price (${pr["low"]:g}–${pr["high"]:g} range)'),
        ('1<span class="u">in</span>3',
         'known-price sessions are free or by donation'),
        (f'<span data-n="{tim["evening_pct"]:.0f}">{tim["evening_pct"]:.0f}</span><span class="u">%</span>',
         'start after 5 p.m. — a weeknight ritual'),
        (f'<span data-n="{vol["venues"]}">{vol["venues"]}</span>',
         f'venues · {vol["operators"]} operators · {vol["cities"]} metros'),
        (f'~<span data-n="{geo["corridor_miles"]}">{geo["corridor_miles"]}</span><span class="u">mi</span>',
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

    # ---- Archive block ----
    if other_editions:
        links = '\n'.join(
            f'          <li><a href="{cp}state-of-sound-healing/{_esc(o["edition"]["slug"])}/">'
            f'{_esc(o["edition"]["label"])}</a> — {_esc(_fmt_window(o["edition"]))}</li>'
            for o in other_editions)
        archive = (f'      <section class="soh-archive">\n'
                   f'        <p class="soh-kicker">Past editions</p>\n'
                   f'        <ul>\n{links}\n        </ul>\n      </section>')
    else:
        archive = ('      <p class="soh-firstnote">This is the first edition. As new '
                   'quarters are published, past editions will be archived here — '
                   'and once two or more exist, so will genuine trend data.</p>')

    free_pct = pr['free_or_flex_pct']

    body = f"""<div class="soh" id="soh">

  <section class="soh-band soh-band--paper soh-band--mast">
    <div class="soh-wrap">
      <p class="soh-eyebrow">Front Range · Colorado · {_esc(ed['label'])}</p>
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
    <img src="{cp}img/insights/front-range-foothills.jpg" width="1400" height="1050" alt="The Flatirons rising over open grassland in Boulder County, Colorado — the Front Range foothills." fetchpriority="high">
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
          <img src="{cp}img/insights/singing-bowls.jpg" width="1000" height="667" alt="Overhead view of a set of Tibetan singing bowls and mallets on a plain surface." loading="lazy">
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
        <p>Nearly half of sessions ({mod['only_base_pct']:.0f}%) are currently tagged only with the general "sound bath" label. Any modality breakdown would reflect how thoroughly listings have been tagged, not what's happening in the rooms. As the calendar's tagging matures, this becomes a genuinely interesting figure — and a natural addition to the next edition.</p>
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
    return body + _SCRIPT


# Progressive enhancement only: bands fade/rise in, bars grow to --w, and stat
# figures count up, each the first time it scrolls into view. Without JS (or
# with reduced motion) the 'soh-js' class is never added and everything renders
# complete and static. Plain string (not an f-string) — braces are JS.
_SCRIPT = """
<script>
(function () {
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  if (!('IntersectionObserver' in window)) return;
  var root = document.getElementById('soh');
  if (!root) return;
  root.classList.add('soh-js');

  function countUp(el) {
    var target = parseFloat(el.getAttribute('data-n'));
    if (!isFinite(target)) return;
    var t0 = null, DUR = 900;
    function tick(t) {
      if (t0 === null) t0 = t;
      var p = Math.min((t - t0) / DUR, 1);
      var eased = 1 - Math.pow(1 - p, 3);
      el.textContent = String(Math.round(target * eased));
      if (p < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  }

  var seen = new WeakSet();
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (en) {
      if (!en.isIntersecting || seen.has(en.target)) return;
      seen.add(en.target);
      en.target.classList.add('in-view');
      en.target.querySelectorAll('[data-n]').forEach(countUp);
      io.unobserve(en.target);
    });
  }, { threshold: 0.18 });

  root.querySelectorAll('.soh-band, .soh-hero').forEach(function (b) { io.observe(b); });
})();
</script>"""


# ---------------------------------------------------------------------------
# Page <head> styles — namespaced under .soh so nothing leaks into styles.css.
# Reuses the site design tokens defined there (--ink, --paper, --accent,
# --accent-on-light, --line, --ink-rgb, --font-display, --font-body). Full-bleed
# alternating bands (paper / white / ink) differentiate sections; images keep
# their intrinsic ratio (height:auto / explicit object-fit) so nothing
# stretches; the stat grid uses explicit 3/2/1 columns so tiles always fill the
# row cleanly at every width.
# ---------------------------------------------------------------------------
INSIGHTS_HEAD = """<style>
  .soh { --soh-white: #fff; --soh-dim: #5d6570; --soh-wash: rgba(98,182,232,0.14);
         --soh-line: var(--line);
         --soh-ink-bg: #0A0B0D; --soh-ink-text: #F5F7FA;
         --soh-ink-dim: rgba(245,247,250,0.62); --soh-ink-line: rgba(245,247,250,0.14); }
  /* Dark scheme: the site swaps --ink/--paper/--accent-on-light (styles.css),
     so the prose adapts on its own — these keep the report's OWN surfaces in
     step: "white" bands become an elevated dark card, dims lighten, and the
     hairlines flip light (--line is a static dark rgba and would vanish). */
  @media (prefers-color-scheme: dark) {
    .soh { --soh-white: #16191E; --soh-dim: rgba(245,247,250,0.62);
           --soh-wash: rgba(98,182,232,0.17); --soh-line: rgba(245,247,250,0.14); }
    /* Photos are the one surface tokens can't fix: a daylight landscape and a
       white-tabletop still-life read as glowing blocks on the dark ground.
       Pull them down toward the page instead of letting them blast through. */
    .soh-hero img { filter: brightness(.8) saturate(.95); }
    .soh-split__fig img { filter: brightness(.68) saturate(.9); }
  }
  .soh :is(h1,h2,h3) { font-family: var(--font-display); }
  .soh p { line-height: 1.7; }
  .soh a { color: var(--accent-on-light); text-underline-offset: 3px; }

  /* ---- Bands: full-bleed rooms with a generous shared rhythm ---- */
  .soh-band { padding: clamp(3.5rem, 7vw, 6rem) 0; }
  .soh-band--paper { background: var(--paper); }
  .soh-band--white { background: var(--soh-white); border-top: 1px solid var(--soh-line); border-bottom: 1px solid var(--soh-line); }
  .soh-band--ink { background: var(--soh-ink-bg); color: var(--soh-ink-text); }
  .soh-band--ink a { color: var(--accent); }
  .soh-wrap { max-width: 71rem; margin: 0 auto; padding: 0 clamp(20px, 4vw, 40px); }

  /* ---- Masthead ---- */
  .soh-band--mast { padding-top: clamp(4rem, 9vw, 7rem); padding-bottom: clamp(3rem, 6vw, 4.5rem); }
  .soh-eyebrow { font: 500 13px/1 var(--font-display); letter-spacing: .22em;
    text-transform: uppercase; color: var(--accent-on-light); margin: 0 0 22px; }
  .soh-h1 { font-size: clamp(34px, 6vw, 66px); line-height: 1.02; font-weight: 700;
    letter-spacing: -0.022em; margin: 0 0 26px; max-width: 20ch; }
  .soh-h1__accent { color: var(--accent-on-light); }
  .soh-dek { font: 500 clamp(18px, 2.2vw, 22px)/1.5 var(--font-display); color: var(--ink);
    max-width: 46rem; margin: 0 0 34px; }
  .soh-dek em { font-style: normal; border-bottom: 3px solid var(--accent); }
  .soh-meta { display: flex; flex-wrap: wrap; gap: 10px 26px; font-size: 13.5px;
    color: var(--soh-dim); padding-top: 24px; border-top: 1px solid var(--soh-line); }
  .soh-meta b { color: var(--ink); font-weight: 600; }

  /* ---- Full-bleed hero photo ---- */
  .soh-hero { margin: 0; position: relative; }
  .soh-hero img { display: block; width: 100%; height: clamp(300px, 52vw, 540px);
    object-fit: cover; object-position: center 62%; }
  .soh-hero__credit { position: absolute; right: 14px; bottom: 12px;
    font-size: 11px; color: rgba(245,247,250,0.9); background: rgba(10,11,13,0.55);
    padding: 5px 12px; border-radius: 999px; backdrop-filter: blur(4px); }
  .soh-hero__credit a { color: rgba(245,247,250,0.9); }

  /* ---- Section furniture ---- */
  .soh-kicker { font: 500 12.5px/1 var(--font-display); letter-spacing: .18em;
    text-transform: uppercase; color: var(--accent-on-light); margin: 0 0 14px;
    display: flex; align-items: baseline; gap: 14px; }
  .soh-kicker::after { content:""; flex: 1; height: 1px; background: var(--soh-line); }
  .soh-band--ink .soh-kicker { color: var(--accent); }
  .soh-band--ink .soh-kicker::after { background: var(--soh-ink-line); }
  .soh-h2 { font-size: clamp(25px, 3.6vw, 36px); line-height: 1.1; font-weight: 700;
    letter-spacing: -0.018em; margin: 0 0 18px; max-width: 26ch; }
  .soh p { max-width: 44rem; }
  .soh-lead { font-size: 19px; }
  .soh-intro { color: var(--soh-ink-dim); }

  /* ---- Stat grid: explicit columns so tiles always fill the row ---- */
  .soh-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-top: 38px; }
  @media (max-width: 899px) { .soh-stats { grid-template-columns: repeat(2, 1fr); } }
  @media (max-width: 519px) { .soh-stats { grid-template-columns: 1fr; } }
  .soh-stat { background: rgba(255,255,255,0.045); border: 1px solid var(--soh-ink-line);
    border-radius: 14px; padding: 26px 24px 22px; }
  .soh-stat__fig { font: 500 clamp(38px, 5vw, 54px)/1 var(--font-display);
    letter-spacing: -0.02em; color: var(--soh-ink-text); font-variant-numeric: tabular-nums; }
  .soh-stat__fig .u { font-size: .48em; color: var(--accent); }
  .soh-stat__lab { margin-top: 12px; font-size: 14px; color: var(--soh-ink-dim); line-height: 1.45; }

  /* ---- Two-column prose + chart ---- */
  .soh-cols { display: grid; grid-template-columns: 1fr; gap: 34px 56px; align-items: center; margin-top: 8px; }
  @media (min-width: 860px) { .soh-cols { grid-template-columns: 1fr 1fr; } }

  /* ---- Bars ---- */
  .soh-chart { display: grid; gap: 11px; }
  .soh-row { display: grid; grid-template-columns: 118px 1fr 44px; align-items: center; gap: 14px; }
  .soh-row__name { font-size: 14px; color: var(--soh-dim); text-align: right; }
  .soh-row__track { background: var(--soh-wash); border-radius: 5px; height: 26px; overflow: hidden; }
  .soh-row__fill { display: block; height: 100%; background: var(--accent); border-radius: 5px; width: var(--w); }
  .soh-row__val { font: 500 15px var(--font-display); text-align: right; color: var(--ink);
    font-variant-numeric: tabular-nums; }
  @media (max-width: 560px) { .soh-row { grid-template-columns: 96px 1fr 38px; gap: 10px; }
    .soh-row__name { font-size: 13px; } }

  /* ---- Table ---- */
  .soh-tbl-scroll { overflow-x: auto; margin-top: 30px; background: var(--soh-white);
    border: 1px solid var(--soh-line); border-radius: 14px; }
  .soh-tbl { border-collapse: collapse; width: 100%; min-width: 360px; font-size: 15.5px; }
  .soh-tbl th, .soh-tbl td { text-align: left; padding: 14px 20px; border-bottom: 1px solid var(--soh-line); }
  .soh-tbl th { font: 500 11.5px var(--font-display); letter-spacing: .12em;
    text-transform: uppercase; color: var(--soh-dim); }
  .soh-num { text-align: right; font-family: var(--font-display); font-weight: 500;
    font-variant-numeric: tabular-nums; }
  .soh-tbl tbody tr:last-child td { border-bottom: none; }
  .soh-bc { position: relative; }
  .soh-mini { position: absolute; left: 20px; bottom: 7px; height: 3px;
    background: var(--accent); border-radius: 2px; opacity: .5; }

  /* ---- Split figure (price) — aspect preserved, never stretched ---- */
  .soh-split { display: grid; grid-template-columns: 1fr; gap: 30px; align-items: center; margin-top: 8px; }
  @media (min-width: 780px) { .soh-split { grid-template-columns: 1.05fr 1fr; } }
  .soh-split__fig { margin: 0; }
  .soh-split__fig img { display: block; width: 100%; height: auto; aspect-ratio: 3 / 2;
    object-fit: cover; border-radius: 14px; border: 1px solid var(--soh-line); }
  .soh-split__body > p:first-child { margin-top: 0; }
  .soh-credit { font-size: 11.5px; color: var(--soh-dim); margin-top: 8px; }

  /* ---- Note / callout ---- */
  .soh-note { background: var(--paper); border: 1px solid var(--soh-line);
    border-left: 3px solid var(--accent); border-radius: 12px; padding: 22px 26px;
    margin-top: 30px; max-width: 44rem; }
  .soh-band--paper .soh-note { background: var(--soh-white); }
  .soh-note h3 { font: 700 15px var(--font-body); margin: 0 0 8px; }
  .soh-note p { margin: 0; font-size: 15.5px; color: var(--soh-dim); }

  /* ---- Dark pull-quote band ---- */
  .soh-band--pull { padding: clamp(3.5rem, 7vw, 5.5rem) 0; }
  .soh-pull { font: 500 clamp(24px, 3.6vw, 38px)/1.32 var(--font-display);
    letter-spacing: -0.015em; margin: 0; max-width: 30ch; }
  .soh-pull b { color: var(--accent); font-weight: 500; }

  /* ---- Methodology ---- */
  .soh-band--method { border-bottom: 0; }
  .soh-list { max-width: 46rem; padding-left: 0; list-style: none; display: grid; gap: 16px; margin-top: 6px; }
  .soh-list li { position: relative; padding-left: 28px; font-size: 15px;
    color: var(--soh-dim); line-height: 1.6; }
  .soh-list li::before { content:""; position: absolute; left: 0; top: 8px;
    width: 9px; height: 9px; border: 1.5px solid var(--accent); border-radius: 50%; }
  .soh-list li b { color: var(--ink); }
  .soh-cite { font-size: 13.5px; line-height: 1.7; color: var(--soh-dim);
    background: var(--paper); border: 1px dashed var(--soh-line); border-radius: 12px;
    padding: 18px 22px; margin-top: 28px; max-width: 46rem; }
  .soh-cite b { color: var(--ink); }
  .soh-archive { padding-top: 42px; }
  .soh-archive ul { list-style: none; padding: 0; display: grid; gap: 8px; }
  .soh-firstnote, .soh-press { max-width: 46rem; font-size: 14.5px; color: var(--soh-dim);
    margin-top: 30px; }

  /* ---- Scroll-in animation (JS adds .soh-js; bands rise, bars grow,
         numbers count). Reduced-motion users never get .soh-js. ---- */
  .soh-js .soh-band .soh-wrap, .soh-js .soh-hero img { opacity: 0; transform: translateY(18px);
    transition: opacity .7s ease, transform .7s cubic-bezier(.22,.61,.36,1); }
  .soh-js .soh-band.in-view .soh-wrap, .soh-js .soh-hero.in-view img { opacity: 1; transform: none; }
  .soh-js .soh-row__fill { width: 0; transition: width .9s cubic-bezier(.22,.61,.36,1); }
  .soh-js .in-view .soh-row__fill { width: var(--w); }
  .soh-js .in-view .soh-row:nth-child(2) .soh-row__fill { transition-delay: .08s; }
  .soh-js .in-view .soh-row:nth-child(3) .soh-row__fill { transition-delay: .16s; }
  .soh-js .in-view .soh-row:nth-child(4) .soh-row__fill { transition-delay: .24s; }
  .soh-js .in-view .soh-row:nth-child(5) .soh-row__fill { transition-delay: .32s; }
  .soh-js .in-view .soh-row:nth-child(6) .soh-row__fill { transition-delay: .40s; }
  .soh-js .in-view .soh-row:nth-child(7) .soh-row__fill { transition-delay: .48s; }
</style>"""
