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
  <link rel="stylesheet" href="{{css_path}}vendor/markercluster/MarkerCluster.css">
  <style>
    .map-wrap { margin: 0; }
    .map-intro { margin: 0 0 1.4rem; }
    .map-intro .cal-updated { color: var(--muted); font-size: 0.85rem; margin: 0.2rem 0 0; }
    /* List + map split (CAL-10 phase C): the list flows with the page scroll, the
       map sits sticky beside it. Below 900px they stack, map band on top. With JS
       blocked the list is fully usable and the map box simply never initializes. */
    .map-split { display: grid; grid-template-columns: minmax(0, 1fr); gap: 2rem; }
    /* Anchors the touch-gesture hint overlay. The ≥900px sticky rule below
       overrides this — sticky positions absolute children just the same. */
    .map-split__map { position: relative; }
    @media (min-width: 900px) {
      .map-split { grid-template-columns: minmax(340px, 5fr) 7fr; gap: 2.4rem; align-items: start; }
      .map-split__map { position: sticky; top: var(--mast-offset); }
    }
    /* The beside-list is the COMPACT CARD-LIST variant (CAL-35, the CAL-29
       strip anatomy at one column): the map is this page's visual, so the
       cards drop their faces and read as a scan column — strip-scale names,
       14px meta, hairline between entries. Type tiles flatten to captions
       (their tile colours revert to the page tokens) so the column has one
       texture, not two. */
    .map-split__list .cal-card__im { display: none; }
    .map-split__list .cal-rows { grid-template-columns: minmax(0, 1fr); gap: 0; }
    .map-split__list .cal-row { padding: 13px 0; border-top: 1px solid var(--line); }
    .map-split__list .cal-rows > .cal-row:first-child { border-top: 0; }
    .map-split__list .cal-card--tile { background: transparent; aspect-ratio: auto; }
    .map-split__list .cal-card__tin { padding: 0; }
    .map-split__list .cal-row__name { font-size: clamp(16px, 0.9vw + 11px, 21px); }
    .map-split__list .cal-card__meta { font-size: 14px; }
    .map-split__list .cal-card--tile .cal-row__name a { color: var(--ink); }
    .map-split__list .cal-card--tile .cal-card__meta { color: var(--muted); }
    .map-split__list .cal-card--tile .cal-card__meta b { color: var(--signal-text); }
    .map-split__list .cal-card--tile:hover { background: transparent; }
    .map-split__list .cal-card--tile:hover .cal-card__meta { color: var(--muted); }
    /* The hovered row's own mark, paired with the pin's white ring. */
    .map-split__list .cal-row:hover { background: rgba(var(--ink-rgb), 0.05); }
    @media (max-width: 899px) { .map-split__map { order: -1; } }
    /* Fixed px height (not vh): guarantees the container is sized before Leaflet
       inits, so fitBounds sees real dimensions in every context. */
    #sbc-map { width: 100%; height: 680px; border: 1px solid var(--line); background: var(--paper); }
    @media (max-width: 899px) { #sbc-map { height: 440px; } }
    /* Two-finger hint (CAL-UX-8): on touch devices one-finger dragging is off,
       so Leaflet's own .leaflet-touch-zoom rule leaves touch-action: pan-x pan-y
       and a thumb-scroll moves the PAGE, not the map. This overlay teaches the
       two-finger gesture when a one-finger drag is attempted. JS-created (no-JS
       pages never carry it), pointer-events:none so it can never trap a scroll
       itself. Token colors — they flip in dark. */
    .map-hint { position: absolute; inset: 0; z-index: 1200; display: flex; align-items: center; justify-content: center; text-align: center; padding: 0 1.4rem; background: rgba(var(--ink-rgb),0.45); opacity: 0; transition: opacity .25s; pointer-events: none; }
    .map-hint--on { opacity: 1; }
    .map-hint span { background: var(--paper); color: var(--ink); border: 1px solid var(--line); padding: 0.6rem 1rem; font: 600 0.9rem var(--font-body); }
    /* Count-carrying pins (CAL-10 → CAL-35): CORAL DISCS carrying the venue's
       session count in condensed numerals; a cluster sums the sessions inside
       it. The map is the one surface where coral runs as a field of marks —
       they are the data, not decoration (the ≤2-slabs budget governs page
       chrome, and this page has no ticker and no live-day slab). White on
       --signal is 5.67:1. Hovered or selected, the disc takes a white ring. */
    .sbc-pin { width: 100%; height: 100%; background: var(--signal); color: #fff;
      border: 2px solid var(--paper); border-radius: 50%; display: flex;
      align-items: center; justify-content: center;
      font-family: var(--font-display); font-weight: 800; font-stretch: 62%;
      font-size: 14px; line-height: 1; font-variant-numeric: tabular-nums;
      box-shadow: 0 1px 4px rgba(var(--shadow-rgb),0.35); }
    .sbc-pin--cluster { font-size: 16px; }
    .sbc-pin--hot { border-color: #fff; box-shadow: 0 0 0 2px #fff, 0 1px 4px rgba(var(--shadow-rgb),0.35); }
    /* Popup surfaces ride the tokens so they follow dark mode — the leaflet.css
       default is hardcoded white, which went illegible once --ink flipped. */
    .leaflet-popup-content-wrapper, .leaflet-popup-tip { background: var(--paper); color: var(--ink); }
    /* Popups speak the register (CAL-35): the venue name as a condensed-caps
       20 monument, the sessions beneath it at 15 with coral links. */
    .leaflet-popup-content-wrapper { border-radius: 0; }
    .sbc-pop__name { font-family: var(--font-display); font-weight: 800; font-stretch: 72%;
      font-size: 20px; line-height: 1.05; text-transform: uppercase; margin: 0 0 0.45rem; }
    .sbc-pop__name a { color: var(--ink); text-decoration: underline; text-underline-offset: 3px; text-decoration-thickness: 1.5px; }
    .sbc-pop__name a:hover { color: var(--signal-text); }
    .sbc-pop__list { margin: 0; padding-left: 1.05rem; }
    .sbc-pop__list li { font-size: 15px; line-height: 1.5; }
    .sbc-pop__list a { color: var(--signal-text); text-underline-offset: 3px; }
    .sbc-pop__more { list-style: none; margin-left: -1.05rem; color: var(--muted); font-size: 14px; }
    .leaflet-container { font: inherit; }
    .map-empty { color: var(--muted); }
    /* Dark mode (CAL-14 → retuned for the v5 night ground, CAL-35): the light
       OSM raster tiles are inverted + hue-rotated into a dark basemap. The
       previous values were tuned against v4's near-black; against #0E0C12 the
       plain inversion sits too bright and too blue, so it is pulled down and
       desaturated until the basemap reads as a ground the coral pins sit ON
       rather than a lit panel beside the page. Only .leaflet-tile is filtered —
       markers, popups, and controls live in other panes and stay untouched. */
    @media (prefers-color-scheme: dark) {
      .leaflet-tile { filter: invert(1) hue-rotate(185deg) brightness(0.78) contrast(0.88) saturate(0.62); }
      /* The frame + the tile gutter match the page's own night ground. */
      #sbc-map { border-color: rgba(var(--ink-rgb), 0.24); }
    }
  </style>"""


def render_map_page(pins, nav_prefix, updated_str, cal_rows=None, now=None, geocode=None):
    """The /map/ body (CAL-10 phase C): the same temporal bands the root renders
    (rows carry data-lat/lng, enabling the row→pin hover sync) beside a sticky,
    clustered map whose pins carry each venue's session count. With JS blocked
    the list is fully usable and the map box simply stays empty."""
    out = ['<section class="section section--light map-wrap">', '  <div class="container">']
    out.append('    <div class="map-intro">')
    out.append('      <h1 class="cal-h1">Sound baths on the map</h1>')
    out.append('      <p class="cal-summary">Every upcoming session, pinned by venue, '
               'beside the list. Tap a marker for what is on there and when.</p>')
    out.append(f'      <p class="cal-updated">Last updated {_esc(updated_str)}.</p>')
    out.append('    </div>')

    if not pins:
        out.append('    <p class="map-empty">The map is filling in. '
                   f'<a href="{nav_prefix}">See the full calendar →</a></p>')
        if cal_rows:
            # include_faq=False: this page renders no FAQ section, so the
            # jump nav must not offer a pill whose anchor doesn't exist.
            out.append(X._render_bands(cal_rows, nav_prefix=nav_prefix, now=now,
                                       geocode=geocode, include_faq=False))
        out.append('  </div>')
        out.append('</section>')
        return '\n'.join(out)

    out.append('    <div class="map-split">')
    out.append('      <div class="map-split__list">')
    if cal_rows:
        # include_faq=False: this page renders no FAQ section, so the
        # jump nav must not offer a pill whose anchor doesn't exist.
        out.append(X._render_bands(cal_rows, nav_prefix=nav_prefix, now=now,
                                   geocode=geocode, include_faq=False))
    out.append('      </div>')
    out.append('      <div class="map-split__map">')
    out.append('        <div id="sbc-map" role="application" '
               'aria-label="Map of upcoming sound baths"></div>')
    out.append('      </div>')
    out.append('    </div>')
    out.append('  </div>')
    out.append('</section>')
    # Leaflet + clustering + init. Placed after the container so #sbc-map exists;
    # the pin data is server-escaped, script-safe JSON. Clustering degrades: if
    # markercluster fails to load, plain markers still draw.
    out.append(f'<script src="{nav_prefix}vendor/leaflet/leaflet.js"></script>')
    out.append(f'<script src="{nav_prefix}vendor/markercluster/leaflet.markercluster.js"></script>')
    out.append('<script>')
    out.append('(function(){')
    out.append('  if (typeof L === "undefined") return;')
    out.append(f'  var PINS = {_ldjson_safe(pins)};')
    out.append('  var byKey = {};')
    out.append('  function key(la, ln){ return la.toFixed(5) + "," + ln.toFixed(5); }')
    # Count-carrying divIcon: the venue's session count (clusters sum sessions).
    out.append('  function pinIcon(n, cluster){')
    out.append('    var size = cluster ? 34 : 28;')
    out.append('    var cls = cluster ? "sbc-pin sbc-pin--cluster" : "sbc-pin";')
    out.append('    return L.divIcon({className: "", '
               'html: "<div class=\\"" + cls + "\\">" + n + "</div>", '
               'iconSize: [size, size], iconAnchor: [size/2, size/2], '
               'popupAnchor: [0, -size/2 - 2]});')
    out.append('  }')
    out.append('  function init(){')
    # Cooperative gestures (CAL-UX-8): on phones the map opens above the list,
    # and a one-finger drag that pans the MAP traps the thumb-scroll — the list
    # below becomes unreachable. So on touch devices one-finger dragging is off:
    # Leaflet's own .leaflet-touch-zoom CSS then sets touch-action: pan-x pan-y,
    # the page scrolls natively, and two fingers pan/zoom the map (the pinch
    # handler follows the midpoint, so it pans too). Desktop drag is unchanged,
    # and the keyboard handler (focus + arrow keys) is independent of dragging.
    out.append('    var coop = L.Browser.mobile;')
    out.append('    var map = L.map("sbc-map", '
               '{scrollWheelZoom:false, dragging:!coop})'
               '.setView([39.74,-104.99], 9);')
    out.append('    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", '
               '{maxZoom:19, attribution:"&copy; OpenStreetMap contributors"}).addTo(map);')
    out.append('    var group = (typeof L.markerClusterGroup === "function") ? '
               'L.markerClusterGroup({maxClusterRadius: 46, showCoverageOnHover: false,')
    out.append('      iconCreateFunction: function(c){ var n = 0;')
    out.append('        c.getAllChildMarkers().forEach(function(m){ '
               'n += (m.options.sessions || 0); });')
    out.append('        return pinIcon(n, true); }}) : null;')
    out.append('    var ms = PINS.map(function(p){')
    out.append('      var m = L.marker([p.lat,p.lng], '
               '{sessions: p.n, icon: pinIcon(p.n, false)}).bindPopup(p.html);')
    out.append('      byKey[key(p.lat, p.lng)] = m;')
    out.append('      return m;')
    out.append('    });')
    out.append('    if (group){ ms.forEach(function(m){ group.addLayer(m); }); '
               'map.addLayer(group); }')
    out.append('    else { ms.forEach(function(m){ m.addTo(map); }); }')
    # invalidateSize first so fitBounds sees the real container size (else it
    # under-zooms); cap the zoom so a lone pin isn't buried. animate:false is
    # load-bearing — an animated fitBounds leaves getZoom mid-flight and a second
    # fit() restarts the animation so the view never settles; applying it
    # immediately is deterministic. One deferred re-fit covers late layout.
    # Bounds come straight from the pin coordinates (no temporary featureGroup —
    # the markers already belong to the cluster group).
    out.append('    var bounds = L.latLngBounds(PINS.map(function(p){ '
               'return [p.lat, p.lng]; }));')
    out.append('    var fit = function(){ map.invalidateSize();'
               ' if (PINS.length){ map.fitBounds(bounds.pad(0.12), '
               '{maxZoom:12, animate:false}); } };')
    out.append('    fit();')
    out.append('    setTimeout(fit, 250);')
    # The two-finger hint: shown when a one-finger drag is attempted over the
    # map (>10px of travel — a plain tap never flashes it), gone ~1.1s after
    # the last such move or the moment a second finger lands. Passive listeners
    # and pointer-events:none throughout: the hint only ever narrates, it never
    # intercepts the scroll it exists to protect.
    out.append('    if (coop) {')
    out.append('      var mapEl = document.getElementById("sbc-map");')
    out.append('      var hint = document.createElement("div");')
    out.append('      hint.className = "map-hint";')
    out.append('      hint.setAttribute("aria-hidden", "true");')
    out.append('      hint.innerHTML = '
               '"<span>Use two fingers to move the map</span>";')
    out.append('      mapEl.parentNode.appendChild(hint);')
    out.append('      var hintT = null, sx = 0, sy = 0;')
    out.append('      var show = function(){ hint.classList.add("map-hint--on");')
    out.append('        clearTimeout(hintT);')
    out.append('        hintT = setTimeout(function(){ '
               'hint.classList.remove("map-hint--on"); }, 1100); };')
    out.append('      var hide = function(){ clearTimeout(hintT); '
               'hint.classList.remove("map-hint--on"); };')
    out.append('      mapEl.addEventListener("touchstart", function(e){')
    out.append('        if (e.touches.length === 1) { '
               'sx = e.touches[0].clientX; sy = e.touches[0].clientY; }')
    out.append('        else { hide(); }')
    out.append('      }, {passive:true});')
    out.append('      mapEl.addEventListener("touchmove", function(e){')
    out.append('        if (e.touches.length !== 1) return;')
    out.append('        var dx = e.touches[0].clientX - sx, '
               'dy = e.touches[0].clientY - sy;')
    out.append('        if (dx*dx + dy*dy > 100) show();')
    out.append('      }, {passive:true});')
    out.append('    }')
    # Row → pin hover sync: rows carry data-lat/lng (CAL-05), pins are keyed by
    # coordinate. A marker folded into a cluster has no element — no-op then.
    out.append('    var rows = [].slice.call('
               'document.querySelectorAll(".map-split__list .cal-row"));')
    out.append('    rows.forEach(function(r){')
    out.append('      var la = parseFloat(r.getAttribute("data-lat")), '
               'ln = parseFloat(r.getAttribute("data-lng"));')
    out.append('      if (isNaN(la) || isNaN(ln)) return;')
    out.append('      var k = key(la, ln);')
    # Highlight the marker's VISIBLE representation: the marker itself when
    # unclustered, else the cluster currently holding it (getVisibleParent) —
    # otherwise hover would no-op at the default zoom, where most pins are folded.
    out.append('      function pinEl(){ var m = byKey[k]; if (!m) return null;')
    out.append('        var t = (group && group.getVisibleParent) ? '
               '(group.getVisibleParent(m) || m) : m;')
    out.append('        return t._icon ? t._icon.querySelector(".sbc-pin") : null; }')
    out.append('      r.addEventListener("mouseenter", function(){ '
               'var el = pinEl(); if (el) el.classList.add("sbc-pin--hot"); });')
    out.append('      r.addEventListener("mouseleave", function(){ '
               'var el = pinEl(); if (el) el.classList.remove("sbc-pin--hot"); });')
    out.append('    });')
    out.append('  }')
    out.append('  if (document.readyState === "complete") { init(); }')
    out.append('  else { window.addEventListener("load", init); }')
    out.append('})();')
    out.append('</script>')
    return '\n'.join(out)
