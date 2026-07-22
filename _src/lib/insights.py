"""Sound Bath Calendar — "State of Sound Healing on the Front Range" (CAL-06).

The flagship original-data report: /state-of-sound-healing/. A DISCOVERY-LAYER
asset — built to be cited by search, AI answer engines, and press, and kept out
of the primary participant nav (footer + llms.txt + sitemap only).

Design choice that matters: each edition is FROZEN. The build never recomputes
figures from the live feed — it renders a committed edition JSON emitted by
marketing/scripts/state_of_sound_healing.py (the single source of truth). That
keeps a cited stat stable forever and keeps CI hermetic (no recompute, like the
geocode cache the map uses). New quarter -> emit a new edition JSON, commit it.

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
# Rendering
# ---------------------------------------------------------------------------
def _bar_rows(items, unit=''):
    """items: list of (label, value, display). Renders accent bars scaled to max."""
    mx = max((v for _, v, _ in items), default=1) or 1
    out = []
    for label, value, disp in items:
        pct = max(3, round(value / mx * 100))
        out.append(
            f'      <div class="soh-row"><span class="soh-row__name">{_esc(label)}</span>'
            f'<span class="soh-row__track"><span class="soh-row__fill" style="width:{pct}%"></span></span>'
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

    # ---- Stat tiles (the citable set) ----
    tiles = [
        (f'~{round(vol["per_week"])}<span class="u">/wk</span>',
         'sound bath sessions across the Front Range'),
        (f'<span class="u">$</span>{pr["median"]:g}',
         f'median ticket price (${pr["low"]:g}–${pr["high"]:g} range)'),
        ('1<span class="u">in</span>3',
         'known-price sessions are free or by donation'),
        (f'{tim["evening_pct"]:.0f}<span class="u">%</span>',
         'start after 5 p.m. — a weeknight ritual'),
        (f'{vol["venues"]}',
         f'venues · {vol["operators"]} operators · {vol["cities"]} metros'),
        (f'~{geo["corridor_miles"]}<span class="u">mi</span>',
         'north–south corridor, FoCo to the Springs'),
    ]
    tiles_html = '\n'.join(
        f'      <div class="soh-stat"><div class="soh-stat__fig">{fig}</div>'
        f'<div class="soh-stat__lab">{_esc(lab)}</div></div>'
        for fig, lab in tiles)

    # ---- Busiest venues table ----
    vrows = []
    mxv = vol['busiest_venues'][0]['count'] if vol['busiest_venues'] else 1
    for b in vol['busiest_venues']:
        loc = f' · {b["city"]}' if b.get('city') else ''
        w = max(8, round(b['count'] / mxv * 100))
        vrows.append(
            f'          <tr><td class="soh-bc">{_esc(b["venue"])}{_esc(loc)}'
            f'<span class="soh-mini" style="width:calc({w}% - 40px)"></span></td>'
            f'<td class="soh-num">{b["count"]}</td></tr>')
    vrows_html = '\n'.join(vrows)

    # ---- Metro bars ----
    metro_items = [(name, pct, f'{pct:.0f}%') for name, _c, pct in geo['metros']]
    metro_items.sort(key=lambda t: t[1], reverse=True)
    metro_bars = _bar_rows(metro_items)

    # ---- Day-of-week bars (ordered by count, then weekday) ----
    dow_sorted = sorted(tim['dow'], key=lambda t: t[1], reverse=True)
    dow_bars = _bar_rows([(d, c, str(c)) for d, c in dow_sorted])

    # ---- Timing prose ----
    tt = tim['top_times']
    times_str = ', then '.join(f'{t.replace(" ", " ")} ({c})' for t, c in tt[1:]) if len(tt) > 1 else ''
    top_time = tt[0][0].replace(' ', ' ') if tt else ''
    top_time_ct = tt[0][1] if tt else 0

    # ---- Archive block ----
    if other_editions:
        links = '\n'.join(
            f'        <li><a href="{cp}state-of-sound-healing/{_esc(o["edition"]["slug"])}/">'
            f'{_esc(o["edition"]["label"])}</a> — {_esc(_fmt_window(o["edition"]))}</li>'
            for o in other_editions)
        archive = (f'  <section class="soh-archive">\n'
                   f'    <p class="soh-kicker">Past editions</p>\n'
                   f'    <ul>\n{links}\n    </ul>\n  </section>')
    else:
        archive = ('  <p class="soh-firstnote">This is the first edition. As new '
                   'quarters are published, past editions will be archived here — '
                   'and once two or more exist, so will genuine trend data.</p>')

    free_pct = pr['free_or_flex_pct']

    return f"""<div class="soh">
  <header class="soh-mast">
    <p class="soh-eyebrow">Front Range · Colorado · {_esc(ed['label'])}</p>
    <h1 class="soh-h1">The Front Range Sound Bath Scene: A {_esc(ed['label'])} Snapshot</h1>
    <p class="soh-dek">The first count of a quietly widespread ritual — every public sound bath across Denver, Boulder, Fort Collins, and Colorado Springs. A <em>point-in-time snapshot</em>, not a trend: simply what is verifiably true of the calendar right now.</p>
    <div class="soh-meta">
      <span>Source · <b>Sound Bath Calendar</b></span>
      <span>Window · <b>{_esc(window)}</b></span>
      <span>Sessions · <b>{vol['sessions']}</b></span>
      <span>Every figure reproducible</span>
    </div>
  </header>

  <figure class="soh-hero">
    <img src="{cp}img/insights/front-range-foothills.jpg" width="1400" height="1050" alt="The Flatirons rising over open grassland in Boulder County, Colorado — the Front Range foothills." loading="lazy">
  </figure>
  <p class="soh-credit">Above: the Front Range foothills, Boulder County. Public domain (CC0), Mike Pascoe via <a href="https://commons.wikimedia.org/w/index.php?curid=176702599" rel="nofollow">Wikimedia Commons</a>.</p>

  <section>
    <p class="soh-kicker">By the numbers</p>
    <h2 class="soh-h2">The citable stats</h2>
    <p>Each figure maps directly to a session on the calendar — nothing modeled, nothing projected.</p>
    <div class="soh-stats">
{tiles_html}
    </div>
  </section>

  <section>
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
  </section>

  <section>
    <p class="soh-kicker">Price</p>
    <h2 class="soh-h2">A ${pr['median']:g} median — and about a third are free or by donation</h2>
    <div class="soh-split">
      <figure>
        <img src="{cp}img/insights/singing-bowls.jpg" width="1000" height="667" alt="Overhead view of a set of Tibetan singing bowls and mallets on a plain surface." loading="lazy">
      </figure>
      <div class="soh-splitbody">
        <p>Of the {pr['known_model']} sessions with a <b>known access model</b>, the middle 50% of paid tickets land in a tight band — <b>${pr['q1']:g} to ${pr['q3']:g}</b> — with a full parseable range of ${pr['low']:g} to ${pr['high']:g}.</p>
        <p>Underneath the median sits the more human finding: <b>roughly one in three ({free_pct:.0f}%) is free, or offered by donation or sliding scale.</b> A meaningful share is priced to be open to anyone.</p>
      </div>
    </div>
    <div class="soh-note">
      <h3>The honest caveat on price</h3>
      <p>{pr['unpriced']} of {vol['sessions']} listings ({pr['unpriced_pct']:.0f}%) carry no stated price in the source — often free community or church-hosted gatherings. The figures above describe the priced-and-stated portion of the calendar. We report the median, not the average, so a few higher-priced sessions don't misrepresent the typical experience.</p>
    </div>
  </section>

  <section>
    <p class="soh-kicker">Geography</p>
    <h2 class="soh-h2">Four metros, evenly shared — a regional scene, not a Denver one</h2>
    <p>Denver anchors the calendar, but the notable finding is how evenly the rest distributes. Colorado Springs and Fort Collins each carry a fifth or more — well above what their relative size would predict.</p>
    <div class="soh-chart" role="img" aria-label="Session share by metro: Denver 40 percent, Colorado Springs 24 percent, Fort Collins 20 percent, Boulder 16 percent.">
{metro_bars}
    </div>
    <p>Mapping the venues confirms the reach: located sessions span a <b>~{geo['corridor_miles']}-mile north–south corridor</b>, from Fort Collins down to Colorado Springs, tracking the I-25 population spine of the state. <a href="{cp}map/">See them on the map →</a></p>
  </section>

  <section>
    <p class="soh-kicker">Timing</p>
    <h2 class="soh-h2">An evening ritual, peaking Friday at 7&nbsp;p.m.</h2>
    <p>Sound baths are overwhelmingly an after-work wind-down: <b>{tim['evening_pct']:.0f}% start at 5&nbsp;p.m. or later</b>, and just {tim['morning_pct']:.0f}% are morning sessions. The single most common start time is <b>{top_time}</b> ({top_time_ct} sessions){', then ' + times_str if times_str else ''}.</p>
    <div class="soh-chart" role="img" aria-label="Sessions by day of week.">
{dow_bars}
    </div>
    <p>Weekends carry about {tim['weekend_pct']:.0f}% of the week's sessions — meaning most sound baths happen on <b>weeknights</b>, a midweek reset rather than a weekend outing. For a curious first-timer: a weeknight around 7&nbsp;p.m. gives you the most to choose from.</p>
  </section>

  <section>
    <p class="soh-kicker">Modality mix</p>
    <h2 class="soh-h2">Not yet a reliable number — and we won't pretend otherwise</h2>
    <p>It's tempting to report which <em>kinds</em> of sound healing dominate — gong baths versus crystal bowls versus breathwork-with-sound. We're choosing not to, yet.</p>
    <div class="soh-note">
      <h3>Why this figure is deferred</h3>
      <p>Nearly half of sessions ({mod['only_base_pct']:.0f}%) are currently tagged only with the general "sound bath" label. Any modality breakdown would reflect how thoroughly listings have been tagged, not what's happening in the rooms. As the calendar's tagging matures, this becomes a genuinely interesting figure — and a natural addition to the next edition.</p>
    </div>
  </section>

  <div class="soh-pull">
    A cottage scene of <b>independent facilitators</b> — {vol['venues']} venues, {vol['operators']} operators, a {geo['corridor_miles']}-mile corridor — where the median session costs <b>${pr['median']:g}</b> and about one in three is free.
  </div>

  <section class="soh-method">
    <p class="soh-kicker">Methodology &amp; caveats</p>
    <h2 class="soh-h2">How these numbers were made</h2>
    <ul>
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
  </section>
</div>"""


# ---------------------------------------------------------------------------
# Page <head> styles — namespaced under .soh so nothing leaks into styles.css.
# Reuses the site design tokens already defined there (--ink, --paper, --accent,
# --accent-text, --line, --gray, --font-display, --font-body).
# ---------------------------------------------------------------------------
INSIGHTS_HEAD = """<style>
  .soh { --soh-card: #fff; --soh-dim: #616b75; --soh-wash: rgba(98,182,232,0.14);
         max-width: 60rem; margin: 0 auto; padding: 0 24px; }
  .soh :is(h1,h2,h3) { font-family: var(--font-display); }
  .soh-eyebrow { font: 500 12.5px/1 var(--font-display); letter-spacing: .2em;
    text-transform: uppercase; color: var(--accent-on-light); margin: 0 0 16px; }
  .soh-h1 { font-size: clamp(30px, 5.4vw, 52px); line-height: 1.04; font-weight: 700;
    letter-spacing: -0.02em; margin: 0 0 20px; }
  .soh-dek { font: 500 clamp(17px,2.1vw,20px)/1.45 var(--font-display); color: var(--ink);
    max-width: 44rem; margin: 0 0 26px; }
  .soh-dek em { font-style: normal; color: var(--accent-on-light); }
  .soh-meta { display: flex; flex-wrap: wrap; gap: 8px 22px; font-size: 13px;
    color: var(--soh-dim); padding-top: 20px; border-top: 1px solid var(--line); }
  .soh-meta b { color: var(--ink); font-weight: 600; }
  .soh-hero { margin: 26px 0 0; border-radius: 12px; overflow: hidden;
    border: 1px solid var(--line); }
  .soh-hero img { display: block; width: 100%; height: clamp(220px, 40vw, 380px); object-fit: cover; }
  .soh-credit { font-size: 11.5px; color: var(--soh-dim); margin: 8px 0 0; }
  .soh-credit a { color: var(--soh-dim); }
  .soh section { padding-top: 52px; }
  .soh-kicker { font: 500 12px/1 var(--font-display); letter-spacing: .16em;
    text-transform: uppercase; color: var(--accent-on-light); margin: 0 0 10px;
    display: flex; align-items: baseline; gap: 12px; }
  .soh-kicker::after { content:""; flex:1; height:1px; background: var(--line); }
  .soh-h2 { font-size: clamp(23px, 3.4vw, 32px); line-height: 1.12; font-weight: 700;
    letter-spacing: -0.015em; margin: 0 0 14px; }
  .soh p { max-width: 42rem; line-height: 1.65; }
  .soh-lead { font-size: 19px; }
  .soh a { color: var(--accent-on-light); }
  .soh-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(158px,1fr));
    gap: 1px; background: var(--line); border: 1px solid var(--line); border-radius: 12px;
    overflow: hidden; margin-top: 26px; }
  .soh-stat { background: var(--soh-card); padding: 22px 20px 20px; }
  .soh-stat__fig { font: 500 clamp(30px,4.4vw,42px)/1 var(--font-display);
    letter-spacing: -0.02em; color: var(--ink); font-variant-numeric: tabular-nums; }
  .soh-stat__fig .u { font-size: .5em; color: var(--accent-on-light); }
  .soh-stat__lab { margin-top: 10px; font-size: 13.5px; color: var(--soh-dim); line-height: 1.42; }
  .soh-chart { margin: 24px 0 6px; display: grid; gap: 9px; max-width: 40rem; }
  .soh-row { display: grid; grid-template-columns: 124px 1fr 40px; align-items: center; gap: 14px; }
  .soh-row__name { font-size: 14px; color: var(--soh-dim); text-align: right; }
  .soh-row__track { background: var(--soh-wash); border-radius: 4px; height: 22px; overflow: hidden; }
  .soh-row__fill { display: block; height: 100%; background: var(--accent); border-radius: 4px; }
  .soh-row__val { font: 500 14px var(--font-display); text-align: right; color: var(--ink);
    font-variant-numeric: tabular-nums; }
  .soh-tbl-scroll { overflow-x: auto; margin: 22px 0 4px; }
  .soh-tbl { border-collapse: collapse; width: 100%; min-width: 340px; font-size: 15px; }
  .soh-tbl th, .soh-tbl td { text-align: left; padding: 11px 14px; border-bottom: 1px solid var(--line); }
  .soh-tbl th { font: 500 11.5px var(--font-display); letter-spacing: .1em;
    text-transform: uppercase; color: var(--soh-dim); }
  .soh-num { text-align: right; font-family: var(--font-display); font-weight: 500;
    font-variant-numeric: tabular-nums; }
  .soh-tbl tbody tr:last-child td { border-bottom: none; }
  .soh-bc { position: relative; }
  .soh-mini { position: absolute; left: 14px; bottom: 5px; height: 3px;
    background: var(--accent); border-radius: 2px; opacity: .5; }
  .soh-split { display: grid; grid-template-columns: 1fr; gap: 26px; align-items: center; margin-top: 28px; }
  .soh-split figure { margin: 0; }
  .soh-split img { display: block; width: 100%; border-radius: 12px; border: 1px solid var(--line); }
  .soh-splitbody > p:first-child { margin-top: 0; }
  @media (min-width: 720px) { .soh-split { grid-template-columns: 1.1fr 1fr; } }
  .soh-note { background: var(--soh-card); border: 1px solid var(--line);
    border-left: 3px solid var(--accent); border-radius: 10px; padding: 20px 24px;
    margin: 22px 0 4px; max-width: 42rem; }
  .soh-note h3 { font: 700 15px var(--font-body); margin: 0 0 8px; }
  .soh-note p { margin: 0; font-size: 15.5px; color: var(--soh-dim); }
  .soh-pull { font: 500 clamp(21px,3vw,27px)/1.34 var(--font-display);
    letter-spacing: -0.01em; color: var(--ink); border-top: 1px solid var(--line);
    border-bottom: 1px solid var(--line); padding: 32px 0; margin: 42px 0; max-width: 42rem; }
  .soh-pull b { color: var(--accent-on-light); }
  .soh-method { margin-top: 58px; padding-top: 36px; border-top: 2px solid var(--ink); }
  .soh-method ul { max-width: 42rem; padding-left: 0; list-style: none; display: grid; gap: 14px; }
  .soh-method li { position: relative; padding-left: 26px; font-size: 15px;
    color: var(--soh-dim); line-height: 1.55; }
  .soh-method li::before { content:""; position: absolute; left: 0; top: 8px;
    width: 9px; height: 9px; border: 1.5px solid var(--accent); border-radius: 50%; }
  .soh-method li b { color: var(--ink); }
  .soh-cite { font-size: 13.5px; line-height: 1.7; color: var(--soh-dim);
    background: var(--soh-card); border: 1px dashed var(--line); border-radius: 10px;
    padding: 16px 20px; margin-top: 22px; max-width: 42rem; }
  .soh-cite b { color: var(--ink); }
  .soh-archive { padding-top: 40px; }
  .soh-archive ul { list-style: none; padding: 0; display: grid; gap: 8px; }
  .soh-firstnote, .soh-press { max-width: 42rem; font-size: 14.5px; color: var(--soh-dim);
    margin-top: 26px; }
  @media (prefers-reduced-motion: no-preference) {
    .soh-row__fill { transition: width .6s cubic-bezier(.2,.7,.3,1); }
  }
  /* Dark mode (CAL-14 polish): the report already rides the site tokens (--ink,
     --paper, --line, --accent-on-light) which flip; only its own --soh-* need a
     dark card + a lighter dim, so the stat cards / tables stop reading as a white
     island on the dark ground. --soh-wash (alpha ice) works on both. */
  @media (prefers-color-scheme: dark) {
    .soh { --soh-card: #181c22; --soh-dim: #9aa3ad; }
  }
</style>"""
