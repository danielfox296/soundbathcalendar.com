"""Sound Bath Calendar — the map view (CAL-04, /map/).

An interactive map of every upcoming session, pinned by venue. Self-contained:
Leaflet is vendored under vendor/leaflet/ (no CDN), tiles come from OpenStreetMap,
and coordinates come from the committed data/geocode.json cache (filled locally
by scripts/geocode.py — the build never geocodes, so CI stays hermetic). A venue
with no cached coordinate simply has no pin; the page never breaks.

build.py owns page assembly; this returns the <main> body, the head block (the
Leaflet stylesheet + page styles), and the pin data prepared server-side (every
popup string is HTML-escaped here, so the client only ever sets trusted markup).
"""

import json
import os

from _src.lib import external_events as X

GEOCODE_REL_PATH = os.path.join('data', 'geocode.json')
_esc = X._esc


def load_geocode(repo_root, log=print):
    """venue string -> {lat, lng}, only for located rows. Never raises."""
    path = os.path.join(repo_root, GEOCODE_REL_PATH)
    try:
        with open(path, encoding='utf-8') as f:
            raw = json.load(f)
    except Exception as exc:
        log(f'  ⚠ geocode cache unusable ({exc.__class__.__name__}) — map will have no pins')
        return {}
    out = {}
    for venue, v in raw.items():
        if isinstance(v, dict) and isinstance(v.get('lat'), (int, float)) \
                and isinstance(v.get('lng'), (int, float)):
            out[venue] = {'lat': v['lat'], 'lng': v['lng']}
    return out


def _ldjson_safe(obj):
    """JSON for embedding in <script>, safe against '</script>' breakout."""
    # ensure_ascii=True (default) escapes every non-ASCII char — including
    # the U+2028/U+2029 separators illegal in JS string literals — so only
    # the HTML metacharacters need handling for the <script> context.
    return (json.dumps(obj)
            .replace('<', '\\u003c').replace('>', '\\u003e')
            .replace('&', '\\u0026'))


def build_pins(cal_rows, geocode, nav_prefix):
    """One pin per located venue: its coordinate + a pre-escaped popup listing
    that venue's upcoming sessions (each linking to its event page), with the
    venue name linking to /venue/<slug>/ when a published venue is linked."""
    groups = {}  # venue string -> {rows, venue_page}
    for r in cal_rows:
        venue = (r.get('venue') or '').strip()
        if not venue or venue not in geocode:
            continue
        g = groups.setdefault(venue, {'rows': [], 'venue_page': None})
        g['rows'].append(r)
        vr = r.get('venue_ref') or {}
        if isinstance(vr, dict) and vr.get('slug') and not g['venue_page']:
            g['venue_page'] = f'{nav_prefix}venue/{vr["slug"]}/'

    pins = []
    for venue, g in groups.items():
        rows = sorted(g['rows'], key=lambda r: X.parse_iso(r['starts_at']))
        coord = geocode[venue]
        title = (f'<a href="{_esc(g["venue_page"])}">{_esc(venue)}</a>'
                 if g['venue_page'] else _esc(venue))
        items = []
        for r in rows[:8]:  # a popup is a teaser, not the whole calendar
            slug = X.event_slug(r)
            url = f'{nav_prefix}{X.event_permalink_path(r)}' if slug else ''
            when = f'{X.fmt_row_date(r["starts_at"])} · {X.fmt_time(r["starts_at"])}'
            label = f'{_esc(when)} — {_esc(r["name"])}'
            items.append(f'<li><a href="{_esc(url)}">{label}</a></li>' if url
                         else f'<li>{label}</li>')
        more = len(rows) - 8
        if more > 0:
            items.append(f'<li class="sbc-pop__more">+{more} more</li>')
        html = (f'<div class="sbc-pop"><p class="sbc-pop__name">{title}</p>'
                f'<ul class="sbc-pop__list">{"".join(items)}</ul></div>')
        pins.append({'lat': coord['lat'], 'lng': coord['lng'], 'html': html,
                     'n': len(rows)})
    pins.sort(key=lambda p: -p['n'])  # dense venues drawn last (on top) below
    return pins


MAP_HEAD = """<link rel="stylesheet" href="{{css_path}}vendor/leaflet/leaflet.css">
  <style>
    .map-wrap { margin: 0; }
    .map-intro { margin: 0 0 1.4rem; }
    .map-intro .cal-updated { color: rgba(var(--ink-rgb),0.55); font-size: 0.85rem; margin: 0.2rem 0 0; }
    /* Fixed px height (not vh): guarantees the container is sized before Leaflet
       inits, so fitBounds sees real dimensions in every context. */
    #sbc-map { width: 100%; height: 560px; border: 1px solid var(--line); background: var(--paper); }
    @media (max-width: 640px) { #sbc-map { height: 460px; } }
    .sbc-pop__name { font: 600 0.98rem var(--font-body); margin: 0 0 0.3rem; }
    .sbc-pop__name a { color: var(--accent-on-light); text-decoration: none; }
    .sbc-pop__list { margin: 0; padding-left: 1.05rem; }
    .sbc-pop__list li { font-size: 0.86rem; line-height: 1.5; }
    .sbc-pop__list a { color: var(--ink); }
    .sbc-pop__more { list-style: none; margin-left: -1.05rem; color: rgba(var(--ink-rgb),0.55); }
    .leaflet-container { font: inherit; }
    .map-empty { color: rgba(var(--ink-rgb),0.55); }
  </style>"""


def render_map_page(pins, nav_prefix, updated_str):
    out = ['<section class="section section--light map-wrap">', '  <div class="container">']
    out.append('    <div class="map-intro">')
    out.append('      <span class="eyebrow">Front Range calendar</span>')
    out.append('      <h1 class="cal-h1">Sound baths on the map</h1>')
    out.append('      <p class="cal-summary">Every upcoming session, pinned by room. '
               'Tap a marker for what is on there and when.</p>')
    out.append(f'      <p class="cal-updated">Last updated {_esc(updated_str)}.</p>')
    out.append('    </div>')

    if not pins:
        out.append('    <p class="map-empty">The map is filling in. '
                   f'<a href="{nav_prefix}">See the full calendar →</a></p>')
        out.append('  </div>')
        out.append('</section>')
        return '\n'.join(out)

    out.append('    <div id="sbc-map" role="application" '
               'aria-label="Map of upcoming sound baths"></div>')
    out.append('  </div>')
    out.append('</section>')
    # Leaflet + init. Placed after the container so #sbc-map exists; the pin data
    # is server-escaped, script-safe JSON.
    out.append(f'<script src="{nav_prefix}vendor/leaflet/leaflet.js"></script>')
    out.append('<script>')
    out.append('(function(){')
    out.append('  if (typeof L === "undefined") return;')
    out.append(f'  var PINS = {_ldjson_safe(pins)};')
    out.append('  function init(){')
    out.append('    var map = L.map("sbc-map", {scrollWheelZoom:false})'
               '.setView([39.74,-104.99], 9);')
    out.append('    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", '
               '{maxZoom:19, attribution:"&copy; OpenStreetMap contributors"}).addTo(map);')
    out.append(f'    var icon = L.icon({{iconUrl:"{nav_prefix}vendor/leaflet/images/marker-icon.png",'
               f'iconRetinaUrl:"{nav_prefix}vendor/leaflet/images/marker-icon-2x.png",'
               f'shadowUrl:"{nav_prefix}vendor/leaflet/images/marker-shadow.png",'
               'iconSize:[25,41],iconAnchor:[12,41],popupAnchor:[1,-34],shadowSize:[41,41]});')
    out.append('    var ms = PINS.map(function(p){'
               'return L.marker([p.lat,p.lng],{icon:icon}).bindPopup(p.html);});')
    out.append('    ms.forEach(function(m){ m.addTo(map); });')
    # invalidateSize first so fitBounds sees the real container size (else it
    # under-zooms); cap the zoom so a lone pin isn't buried. animate:false is
    # load-bearing — an animated fitBounds leaves getZoom mid-flight and a second
    # fit() restarts the animation so the view never settles; applying it
    # immediately is deterministic. One deferred re-fit covers late layout.
    out.append('    var fit = function(){ map.invalidateSize();'
               ' if (ms.length){ map.fitBounds('
               'L.featureGroup(ms).getBounds().pad(0.12), {maxZoom:12, animate:false}); } };')
    out.append('    fit();')
    out.append('    setTimeout(fit, 250);')
    out.append('  }')
    out.append('  if (document.readyState === "complete") { init(); }')
    out.append('  else { window.addEventListener("load", init); }')
    out.append('})();')
    out.append('</script>')
    return '\n'.join(out)
