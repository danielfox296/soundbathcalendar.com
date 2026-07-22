#!/usr/bin/env python3
"""
Sound Bath Calendar — Site Builder
==================================
Assembles the static calendar site from modular source files. Forked from the
Firstwater SSG chassis (site/build.py) on 2026-07-19 for the brand split:
the calendar lives at the root of soundbathcalendar.com, permalinks at
/event/<slug>/, and Firstwater is one operator among many.

Usage:
    python3 build.py

Structure:
    _src/
      layouts/base.html       — HTML shell template
      partials/header.html    — masthead (edit once, updates everywhere)
      partials/footer.html    — shared footer
      lib/                    — feed loaders + calendar renderer
      pages/
        <page-name>/
          config.json         — title, description, output path, etc.
          style.css           — page-specific CSS (optional)
          sections/           — content modules in alphabetical order

Output:
    index.html (the calendar), thanks/, event/<slug>/ permalink pages,
    sitemap.xml. robots.txt and llms.txt are static files at the repo root.

Notes:
    - Stdlib only. The blog/session machinery of the parent chassis is not
      carried here; this site is the calendar and nothing else.
    - Reserved for Track B (do not squat these paths): /denver/ /boulder/
      /fort-collins/ /colorado-springs/.
"""

import os
import posixpath
import sys
import json
import glob
import re
import html as html_mod
import hashlib

REPO     = os.path.dirname(os.path.abspath(__file__))
SRC      = os.path.join(REPO, '_src')
LAYOUTS  = os.path.join(SRC, 'layouts')
PARTIALS = os.path.join(SRC, 'partials')
PAGES    = os.path.join(SRC, 'pages')

# Feed seams (same graceful-fallback discipline as the parent chassis): a
# broken feed never breaks the build — committed data/ caches are the net.
if REPO not in sys.path:
    sys.path.insert(0, REPO)
from _src.lib import sessions_feed
from _src.lib import external_events
from _src.lib import practitioners as practitioners_lib
from _src.lib import venues as venues_lib
from _src.lib import operators as operators_lib
from _src.lib import mapview as mapview_lib
from _src.lib import rss as rss_lib
from _src.lib import insights as insights_lib
from _src.lib import tag_pages as tag_pages_lib

SITE_URL = 'https://soundbathcalendar.com'
SITE_NAME = 'Sound Bath Calendar'
FIRSTWATER_URL = 'https://thefirstwater.co'

# Sitewide description used in Organization + WebSite JSON-LD. Reuses the
# approved calendar meta description verbatim — no new copy.
SITE_DESCRIPTION = (
    'A curated, weekly-updated calendar of sound baths across Denver and the '
    'Front Range: Boulder, Fort Collins, and Colorado Springs. Every room '
    'worth knowing.'
)

# The publisher entity for every page on this site: the calendar itself,
# bridged to the keeper via sameAs (Organization replaces the Firstwater
# LocalBusiness block from the parent chassis).
ORG_SCHEMA = {
    "@context": "https://schema.org",
    "@type": "Organization",
    "name": SITE_NAME,
    "url": SITE_URL,
    "sameAs": [FIRSTWATER_URL],
    "description": SITE_DESCRIPTION,
    "areaServed": {
        "@type": "AdministrativeArea",
        "name": "Denver metro and the Colorado Front Range"
    },
    "knowsAbout": [
        "sound baths",
        "gong baths",
        "sound healing",
        "breathwork with sound",
        "guided meditation with sound"
    ]
}


def page_url(output):
    """Public directory-style URL for a built output path.

    'index.html' -> SITE_URL/ ; 'thanks/index.html' -> SITE_URL/thanks/ ;
    anything else keeps its literal path.
    """
    if output == 'index.html':
        return f'{SITE_URL}/'
    if output.endswith('/index.html'):
        return f'{SITE_URL}/{output[:-len("index.html")]}'
    return f'{SITE_URL}/{output}'


def _ldjson(obj):
    """Serialize `obj` for embedding inside a <script type="application/ld+json">
    block, safe against markup breakout.

    json.dumps leaves '<', '>', '&' and the U+2028/U+2029 line separators raw, so
    a string field containing '</script>' would close the script element and let
    any following markup execute as HTML (stored XSS). Unicode-escape those
    characters: the JSON stays valid and semantically identical for consumers
    (a parser reads \\u003c as '<'), but no literal '</script>' can appear in the
    emitted page. HTML-entity escaping ('&lt;') is WRONG here — a <script>
    raw-text element does not decode entities, so consumers would read the
    literal entity.
    """
    return (json.dumps(obj, indent=2)
            .replace('<', '\\u003c')
            .replace('>', '\\u003e')
            .replace('&', '\\u0026')
            .replace('\u2028', '\\u2028')
            .replace('\u2029', '\\u2029'))


def read(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def collect_sections(sections_dir):
    """Collect section files from a directory in alphabetical order."""
    return sorted(glob.glob(os.path.join(sections_dir, '*.html')))


def _og_twitter_tags(title, description, canonical_url, og_image):
    """The OG + Twitter meta blocks (escaped)."""
    safe_title = html_mod.escape(title, quote=True)
    safe_desc = html_mod.escape(description, quote=True)
    safe_image = html_mod.escape(og_image, quote=True)
    og = '\n  '.join([
        f'<meta property="og:title" content="{safe_title}">',
        f'<meta property="og:description" content="{safe_desc}">',
        f'<meta property="og:url" content="{canonical_url}">',
        f'<meta property="og:type" content="website">',
        f'<meta property="og:image" content="{safe_image}">',
        f'<meta property="og:site_name" content="{SITE_NAME}">',
        f'<meta property="og:locale" content="en_US">',
    ])
    tw = '\n  '.join([
        f'<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{safe_title}">',
        f'<meta name="twitter:description" content="{safe_desc}">',
        f'<meta name="twitter:image" content="{safe_image}">',
    ])
    return og, tw


def _assemble(base, mapping):
    """Substitute {{placeholders}} into the base layout. Two passes on
    css_path: content/header/footer may themselves use {{css_path}}."""
    html = base
    for key, value in mapping.items():
        html = html.replace('{{' + key + '}}', value)
    html = html.replace('{{css_path}}', mapping.get('css_path', ''))
    # RSS discovery link — defaults to the root feed for any page that does not
    # set its own (city pages point at their own feed via mapping).
    html = html.replace('{{feed_link}}',
                        mapping.get('feed_link', f'{SITE_URL}/feed.xml'))
    return html


def _write_page(output, html, pages_built):
    out_path = os.path.join(REPO, output)
    if not os.path.abspath(out_path).startswith(os.path.abspath(REPO)):
        print(f'  ✗ SKIPPED {output} — path escapes repo root')
        return False
    os.makedirs(os.path.dirname(out_path) or REPO, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)
    pages_built.append(output)
    return True


def build():
    base   = read(os.path.join(LAYOUTS,  'base.html'))
    header = read(os.path.join(PARTIALS, 'header.html'))
    footer = read(os.path.join(PARTIALS, 'footer.html'))

    # Cache-bust styles.css with a content fingerprint so CDNs serve the new
    # file immediately after each deploy without a manual purge.
    with open(os.path.join(REPO, 'styles.css'), 'rb') as _f:
        _styles_ver = hashlib.md5(_f.read()).hexdigest()[:8]
    base = base.replace('styles.css"', f'styles.css?v={_styles_ver}"')

    # Same content-fingerprint cache-bust for filters.js so a behaviour change
    # (e.g. the CAL-05 near-me sort) reaches visitors immediately, not after a
    # stale cached copy expires.
    with open(os.path.join(REPO, 'filters.js'), 'rb') as _f:
        _filters_ver = hashlib.md5(_f.read()).hexdigest()[:8]
    base = base.replace('filters.js"', f'filters.js?v={_filters_ver}"')

    pages_built = []

    # Both feeds: external events are the calendar's body; the sessions feed
    # contributes Firstwater's own dated rows.
    print('Loading sessions feed...')
    feed = sessions_feed.load_feed(REPO)
    print()
    print('Loading calendar feed...')
    cal_feed = external_events.load_feed(REPO)
    # One build-time 'now' shared by the calendar page (weekend window,
    # past-event drop, Last-updated stamp, summary) and the per-event permalink
    # pages (past/future gate) so every surface agrees within a build.
    cal_now = external_events.current_now()
    # Future, de-duplicated, chronological rows — shared by the root injection,
    # the ItemList schema, and the city pages (Track B B.2).
    cal_rows = external_events.build_rows(cal_feed, feed, now=cal_now)
    # CAL-09: which tags have earned a landing page (>= BUILD_MIN upcoming). Set
    # BEFORE any chip renders (root injection below, then city/event pages) so
    # every tag chip links to /<slug>/ when that page exists.
    external_events.set_linked_tag_pages(tag_pages_lib.linked_tag_map(cal_rows))
    print()
    print('Loading practitioners feed...')
    pract_feed = practitioners_lib.load_feed(REPO)
    practs = practitioners_lib.published_practitioners(pract_feed)
    print()
    print('Loading venues feed...')
    venue_feed = venues_lib.load_feed(REPO)
    venue_list = venues_lib.published_venues(venue_feed)
    print()
    print('Loading operators feed...')
    operator_feed = operators_lib.load_feed(REPO)
    operator_list = operators_lib.published_operators(operator_feed)
    print()
    # Venue coordinates (CAL-04 cache) — shared by the map AND the CAL-05 near-me
    # distance sort, which attaches data-lat/lng to each row that has one.
    geocode = mapview_lib.load_geocode(REPO)

    page_dirs = []
    for root, dirs, files in os.walk(PAGES):
        if 'config.json' in files:
            page_dirs.append(root)

    for page_path in sorted(page_dirs):
        page_name = os.path.relpath(page_path, PAGES)
        config = json.loads(read(os.path.join(page_path, 'config.json')))

        if config.get('skip'):
            continue

        # ---------------------------------------------------------------
        # REDIRECT STUB (kept from the parent chassis: meta-refresh +
        # canonical + noindex; used if a path here is ever renamed).
        # ---------------------------------------------------------------
        if config.get('redirect_to'):
            redirect_target = config['redirect_to']
            redirect_output = config.get('output', f'{page_name}.html')
            safe_target = html_mod.escape(redirect_target, quote=True)
            redirect_title = html_mod.escape(
                config.get('title', f'Redirecting… | {SITE_NAME}'), quote=True
            )
            if redirect_target.startswith(('http://', 'https://')):
                canonical_href = redirect_target
            else:
                _resolved = posixpath.normpath(posixpath.join(
                    posixpath.dirname(redirect_output), redirect_target))
                canonical_href = f'{SITE_URL}/{"" if _resolved == "." else _resolved}'
                if redirect_target.endswith('/') and not canonical_href.endswith('/'):
                    canonical_href += '/'
            safe_canonical = html_mod.escape(canonical_href, quote=True)
            stub = (
                '<!DOCTYPE html>\n'
                '<html lang="en">\n'
                '<head>\n'
                '<meta charset="utf-8">\n'
                f'<title>{redirect_title}</title>\n'
                f'<link rel="canonical" href="{safe_canonical}">\n'
                f'<meta http-equiv="refresh" content="0; url={safe_target}">\n'
                '<meta name="robots" content="noindex">\n'
                '</head>\n'
                '<body>\n'
                f'<p>This page has moved. Redirecting to <a href="{safe_target}">{safe_target}</a>.</p>\n'
                f'<script>window.location.replace("{safe_target}");</script>\n'
                '</body>\n'
                '</html>\n'
            )
            if _write_page(redirect_output, stub, pages_built):
                print(f'  ↪ {redirect_output} → {redirect_target}')
            continue

        # seo_title (if set) drives the <title> tag; title drives display use.
        title       = config.get('seo_title') or config.get('title', SITE_NAME)
        description = config.get('description', '') or config.get('meta_description', '')
        output      = config.get('output', f'{page_name}.html')

        depth = output.count('/')
        nav_prefix = '../' * depth
        css_path = nav_prefix

        sections_dir = os.path.join(page_path, 'sections')
        if os.path.isdir(sections_dir):
            content = '\n\n'.join(read(f).strip() for f in collect_sections(sections_dir))
        else:
            content = ''

        # ---------------------------------------------------------------
        # CALENDAR INJECTION (the root page). The section file carries the
        # static scaffold (masthead H1, digest capture, jump nav, submission
        # line) plus three markers filled from the feeds.
        # ---------------------------------------------------------------
        if output == 'index.html':
            _cal_body = external_events.render_calendar_body(
                cal_rows, nav_prefix, now=cal_now, geocode=geocode)
            content = content.replace('<!-- CALENDAR_BODY -->', _cal_body)
            content = content.replace(
                '<!-- CALENDAR_SUMMARY -->',
                html_mod.escape(
                    external_events.build_summary_sentence(cal_rows, now=cal_now)))
            content = content.replace(
                '<!-- CALENDAR_LAST_UPDATED -->',
                html_mod.escape(external_events.fmt_stamp_date(cal_now)))

        robots_value = config.get('robots', 'index, follow')

        meta_desc = ''
        if description:
            safe_desc = html_mod.escape(description, quote=True)
            meta_desc = f'<meta name="description" content="{safe_desc}">'

        style_path = os.path.join(page_path, 'style.css')
        page_style = ''
        if os.path.exists(style_path):
            css_content = read(style_path).strip()
            if css_content:
                page_style = f'<style>\n{css_content}\n  </style>'

        page_header = header.strip().replace('{{nav_prefix}}', nav_prefix)
        page_footer = footer.strip().replace('{{nav_prefix}}', nav_prefix)
        if config.get('no_chrome'):
            page_header = ''
            page_footer = ''

        canonical_url = page_url(output)

        og_image = f'{SITE_URL}/img/og-default.png'
        if config.get('og_image'):
            og_image = (config['og_image'] if config['og_image'].startswith('http')
                        else f'{SITE_URL}/{config["og_image"].lstrip("/")}')

        og_tags, twitter_tags = _og_twitter_tags(
            title, description, canonical_url, og_image)

        # --- JSON-LD ---
        # Publisher entity on every page; the root also carries WebSite,
        # CollectionPage (speakable summary + build-time dateModified),
        # ItemList of Events, and FAQPage.
        schema_json = (f'<script type="application/ld+json">\n'
                       f'{json.dumps(ORG_SCHEMA, indent=2)}\n  </script>')

        if output == 'index.html':
            website_schema = {
                "@context": "https://schema.org",
                "@type": "WebSite",
                "name": SITE_NAME,
                "url": SITE_URL,
                "description": SITE_DESCRIPTION,
                "publisher": {
                    "@type": "Organization",
                    "name": SITE_NAME,
                    "url": SITE_URL,
                    "sameAs": [FIRSTWATER_URL]
                }
            }
            schema_json += (f'\n  <script type="application/ld+json">\n'
                            f'{json.dumps(website_schema, indent=2)}\n  </script>')

            if cal_rows:
                _il = external_events.calendar_itemlist(
                    cal_rows, canonical_url, SITE_URL)
                if _il:
                    # _ldjson (not raw json.dumps): the ItemList carries
                    # external-operator-controlled strings, so it must be
                    # escaped against '</script>' breakout.
                    schema_json += (f'\n  <script type="application/ld+json">\n'
                                    f'{_ldjson(_il)}\n  </script>')

            _cp = external_events.collectionpage_schema(
                canonical_url, SITE_URL, description,
                external_events.stamp_date_iso(cal_now))
            schema_json += (f'\n  <script type="application/ld+json">\n'
                            f'{_ldjson(_cp)}\n  </script>')
            _faq = external_events.faqpage_schema()
            schema_json += (f'\n  <script type="application/ld+json">\n'
                            f'{_ldjson(_faq)}\n  </script>')
        else:
            leaf_name = config.get('breadcrumb') or title.split(' | ')[0].strip()
            breadcrumb_schema = {
                "@context": "https://schema.org",
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Calendar",
                     "item": SITE_URL + "/"},
                    {"@type": "ListItem", "position": 2, "name": leaf_name},
                ],
            }
            schema_json += (f'\n  <script type="application/ld+json">\n'
                            f'{json.dumps(breadcrumb_schema, indent=2)}\n  </script>')

        html = _assemble(base, {
            'title':            title,
            'robots':           robots_value,
            'meta_description': meta_desc,
            'canonical_url':    canonical_url,
            'css_path':         css_path,
            'page_style':       page_style,
            'og_tags':          og_tags,
            'twitter_tags':     twitter_tags,
            'schema_json':      schema_json,
            'header':           page_header,
            'content':          content,
            'footer':           page_footer,
        })

        if _write_page(output, html, pages_built):
            print(f'  ✓ {output}')

    # --- City pages (/denver/ etc.) — Track B B.2 ---
    _city_outputs, _city_sitemap = build_city_pages(
        base, header, footer, cal_rows, cal_now, geocode)
    pages_built.extend(_city_outputs)

    # --- Per-event permalink pages (/event/<slug>/) ---
    _event_outputs, _event_sitemap = build_event_pages(
        base, header, footer, cal_feed, cal_now)
    pages_built.extend(_event_outputs)

    # --- Practitioner pages (/practitioner/<slug>/) + index — CAL-02 ---
    _pract_outputs, _pract_sitemap = build_practitioner_pages(
        base, header, footer, practs, cal_rows, cal_now)
    pages_built.extend(_pract_outputs)

    # --- Venue pages (/venue/<slug>/) + index — CAL-03 ---
    _venue_outputs, _venue_sitemap = build_venue_pages(
        base, header, footer, venue_list, cal_rows, cal_now)
    pages_built.extend(_venue_outputs)

    # --- Operator pages (/operator/<slug>/) + index — CAL-08 ---
    _operator_outputs, _operator_sitemap = build_operator_pages(
        base, header, footer, operator_list, cal_rows, cal_now)
    pages_built.extend(_operator_outputs)

    # --- Tag landing pages (/<tag-slug>/) + /tags/ index — CAL-09 ---
    _tag_outputs, _tag_sitemap = build_tag_pages(
        base, header, footer, cal_rows, cal_now, geocode)
    pages_built.extend(_tag_outputs)

    # --- Map view (/map/) — CAL-04 ---
    _map_outputs, _map_sitemap = build_map_page(
        base, header, footer, cal_rows, cal_now, geocode)
    pages_built.extend(_map_outputs)

    # --- State of Sound Healing report (/state-of-sound-healing/) — CAL-06 ---
    _insights_outputs, _insights_sitemap = build_insights_pages(
        base, header, footer, cal_now)
    pages_built.extend(_insights_outputs)

    # --- ICS feeds (/front-range.ics, /<city>.ics) — Track B B.4 ---
    build_ics_feeds(cal_rows, cal_now)

    # --- RSS feeds (/feed.xml, /<city>/feed.xml) — CAL-05 ---
    build_rss_feeds(cal_rows, cal_now)

    print(f'\nBuilt {len(pages_built)} pages.')

    generate_sitemap(page_dirs, cal_now,
                     extra_urls=(_city_sitemap + _event_sitemap
                                 + _pract_sitemap + _venue_sitemap
                                 + _operator_sitemap + _map_sitemap
                                 + _tag_sitemap + _insights_sitemap))


def build_ics_feeds(cal_rows, now):
    """Write the static ICS feeds (Track B B.4): the whole-calendar feed plus
    one per city, at the site root, from the same rows the pages render. The
    per-event .ics files are written beside their permalink pages in
    build_event_pages. All are webcal-subscribable and .ics-downloadable."""
    print('\nGenerating ICS feeds...')
    written = []

    def _write(name, text):
        # newline='' so the explicit CRLF line endings survive untranslated.
        with open(os.path.join(REPO, name), 'w', encoding='utf-8', newline='') as f:
            f.write(text)
        written.append(name)

    _write('front-range.ics', external_events.build_calendar_ics(
        cal_rows, SITE_URL, 'Sound baths on the Front Range', now))
    for city in external_events.CITIES:
        slug = external_events.city_slug(city)
        _write(f'{slug}.ics', external_events.build_city_ics(
            cal_rows, city, SITE_URL, now))

    print(f'  ✓ {len(written)} ICS feed(s): ' + ', '.join(written))


def build_rss_feeds(cal_rows, now):
    """Write the static RSS 2.0 feeds (CAL-05): the whole-calendar feed at the
    site root plus one per city, at <city>/feed.xml, from the same rows the pages
    render. Mirrors build_ics_feeds — feeds are generated output (CI regenerates
    them), never a source file."""
    print('\nGenerating RSS feeds...')
    written = []

    def _write(name, text):
        out_path = os.path.join(REPO, name)
        os.makedirs(os.path.dirname(out_path) or REPO, exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(text)
        written.append(name)

    _write('feed.xml', rss_lib.build_rss(
        cal_rows, SITE_URL, f'{SITE_URL}/feed.xml', SITE_NAME,
        f'{SITE_URL}/', SITE_DESCRIPTION, now))
    for city in external_events.CITIES:
        slug = external_events.city_slug(city)
        _write(f'{slug}/feed.xml', rss_lib.build_rss(
            external_events.city_rows(cal_rows, city), SITE_URL,
            f'{SITE_URL}/{slug}/feed.xml', f'Sound baths in {city} · {SITE_NAME}',
            external_events.city_page_url(city, SITE_URL),
            external_events.CITY_META[city], now))

    print(f'  ✓ {len(written)} RSS feed(s): ' + ', '.join(written))


def build_city_pages(base, header, footer, cal_rows, now, geocode=None):
    """Emit the four city pages (/denver/ etc.) — Track B B.2. Each is the same
    temporal bands as the root, filtered to one city, with its own H1, summary,
    FAQ, OG image, and CollectionPage/ItemList/FAQPage/Breadcrumb schema. All
    four have real inventory today, so none is a doorway page. Returns
    (built_outputs, sitemap_entries) with one (loc, lastmod) per city.
    """
    print('\nGenerating city pages...')
    built, sitemap_entries = [], []
    lastmod = external_events.stamp_date_iso(now)
    nav_prefix = '../'

    for city in external_events.CITIES:
        slug = external_events.city_slug(city)
        output = f'{slug}/index.html'
        canonical_url = external_events.city_page_url(city, SITE_URL)

        # Title uses pipes (not em dashes); description is the stable per-city
        # meta line (NOT the volatile count sentence, which is on-page only).
        title = f'Sound Baths in {city} | {SITE_NAME}'
        description = external_events.CITY_META[city]
        meta_desc = (f'<meta name="description" '
                     f'content="{html_mod.escape(description, quote=True)}">')

        og_rel = f'img/og/{slug}.png'
        og_image = (f'{SITE_URL}/{og_rel}'
                    if os.path.exists(os.path.join(REPO, og_rel))
                    else f'{SITE_URL}/img/og-default.png')
        og_tags, twitter_tags = _og_twitter_tags(
            external_events.CITY_H1[city], description, canonical_url, og_image)

        # Organization (publisher) + CollectionPage + ItemList + FAQPage +
        # BreadcrumbList. The ItemList carries external-operator strings, so it
        # routes through _ldjson (breakout-safe); the rest are our own.
        schema_json = (f'<script type="application/ld+json">\n'
                       f'{json.dumps(ORG_SCHEMA, indent=2)}\n  </script>')
        _cp = external_events.city_collectionpage_schema(
            city, canonical_url, SITE_URL, description, lastmod)
        schema_json += (f'\n  <script type="application/ld+json">\n'
                        f'{_ldjson(_cp)}\n  </script>')
        _il = external_events.city_itemlist(cal_rows, city, SITE_URL)
        if _il:
            schema_json += (f'\n  <script type="application/ld+json">\n'
                            f'{_ldjson(_il)}\n  </script>')
        _faq = external_events.city_faqpage_schema(city)
        schema_json += (f'\n  <script type="application/ld+json">\n'
                        f'{_ldjson(_faq)}\n  </script>')
        breadcrumb_schema = {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Calendar",
                 "item": SITE_URL + "/"},
                {"@type": "ListItem", "position": 2, "name": city,
                 "item": canonical_url},
            ],
        }
        schema_json += (f'\n  <script type="application/ld+json">\n'
                        f'{json.dumps(breadcrumb_schema, indent=2)}\n  </script>')

        content = external_events.render_city_page(
            cal_rows, city, nav_prefix, now=now, geocode=geocode)
        page_header = header.strip().replace('{{nav_prefix}}', nav_prefix)
        page_footer = footer.strip().replace('{{nav_prefix}}', nav_prefix)

        html = _assemble(base, {
            'title':            title,
            'robots':           'index, follow',
            'meta_description': meta_desc,
            'canonical_url':    canonical_url,
            'css_path':         nav_prefix,
            'page_style':       '',
            'og_tags':          og_tags,
            'twitter_tags':     twitter_tags,
            'schema_json':      schema_json,
            'header':           page_header,
            'content':          content,
            'footer':           page_footer,
            # City pages advertise their own region feed for discovery (CAL-05).
            'feed_link':        f'{SITE_URL}/{slug}/feed.xml',
        })

        if not _write_page(output, html, built):
            continue
        n = len(external_events.city_rows(cal_rows, city))
        print(f'  ✓ {output} ({n} upcoming)')
        sitemap_entries.append((canonical_url, lastmod))

    return built, sitemap_entries


def build_event_pages(base, header, footer, cal_feed, now):
    """Emit one permalink page per approved external event at
    /event/<slug>/index.html, from the feed data (not a _src/pages dir).

    Upcoming pages are indexed; PAST pages stay live (no 404) but carry
    robots=noindex, a 'this session has passed' banner, and are omitted from
    the sitemap. Returns (built_outputs, sitemap_entries) where each sitemap
    entry is (loc, lastmod) for an UPCOMING page only.
    """
    print('\nGenerating event pages...')
    # Clear stale event pages from a previous build first: an event that drops
    # out of the feed (past its date, renamed, un-approved) must not leave an
    # orphaned page behind. The directory reflects ONLY the current feed.
    import shutil
    shutil.rmtree(os.path.join(REPO, 'event'), ignore_errors=True)
    rows = external_events.approved_event_rows(cal_feed, now=now)
    if not rows:
        print('  (none)')
        return [], []

    import datetime as _dt
    # lastmod = the feed's own generated_at date (when the listing data was
    # last refreshed), falling back to today.
    gen = (cal_feed or {}).get('generated_at')
    try:
        lastmod = sessions_feed.parse_iso(gen).astimezone(
            sessions_feed.DENVER).date().isoformat()
    except Exception:
        lastmod = _dt.date.today().isoformat()

    built, sitemap_entries = [], []
    for row in rows:
        slug = external_events.event_slug(row)
        if not slug:
            continue
        output = f'event/{slug}/index.html'
        nav_prefix = '../../'
        css_path = nav_prefix
        is_past = sessions_feed.parse_iso(row['starts_at']) <= now
        robots_value = 'noindex, follow' if is_past else 'index, follow'
        canonical_url = external_events.event_permalink_url(row, SITE_URL)

        name = row['name']
        # Permalink title pattern: {Event} · {City} | Sound Bath Calendar
        # (pipes, not em dashes, in title tags).
        title = f'{html_mod.escape(name)} · {row["city"]} | {SITE_NAME}'
        description = external_events.factual_description(row)
        meta_desc = (f'<meta name="description" '
                     f'content="{html_mod.escape(description, quote=True)}">')

        og_image = row.get('image_url') or f'{SITE_URL}/img/og-default.png'
        og_tags, twitter_tags = _og_twitter_tags(
            name, description, canonical_url, og_image)

        # Organization (publisher entity, sitewide) + Event + BreadcrumbList.
        # The Event carries external-operator strings, so it and the crumbs
        # route through _ldjson (breakout-safe); the Organization is our own.
        schema_json = (f'<script type="application/ld+json">\n'
                       f'{json.dumps(ORG_SCHEMA, indent=2)}\n  </script>')
        _ev = external_events.event_jsonld(row, SITE_URL)
        schema_json += (f'\n  <script type="application/ld+json">\n'
                        f'{_ldjson(_ev)}\n  </script>')
        breadcrumb_schema = {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Calendar",
                 "item": SITE_URL + "/"},
                {"@type": "ListItem", "position": 2, "name": name},
            ],
        }
        schema_json += (f'\n  <script type="application/ld+json">\n'
                        f'{_ldjson(breadcrumb_schema)}\n  </script>')

        content = external_events.render_event_page(row, nav_prefix, SITE_URL, now=now)
        page_header = header.strip().replace('{{nav_prefix}}', nav_prefix)
        page_footer = footer.strip().replace('{{nav_prefix}}', nav_prefix)

        html = _assemble(base, {
            'title':            title,
            'robots':           robots_value,
            'meta_description': meta_desc,
            'canonical_url':    canonical_url,
            'css_path':         css_path,
            'page_style':       external_events.EVENT_PAGE_STYLE,
            'og_tags':          og_tags,
            'twitter_tags':     twitter_tags,
            'schema_json':      schema_json,
            'header':           page_header,
            'content':          content,
            'footer':           page_footer,
        })

        if not _write_page(output, html, built):
            continue
        print(f'  ✓ {output} ({"past/noindex" if is_past else "upcoming"})')
        if not is_past:
            sitemap_entries.append((canonical_url, lastmod))
            # Per-event .ics beside the page (Track B B.4). newline='' keeps the
            # explicit CRLF endings untranslated. Upcoming events only.
            ics_path = os.path.join(REPO, 'event', slug, 'event.ics')
            with open(ics_path, 'w', encoding='utf-8', newline='') as f:
                f.write(external_events.build_event_ics(row, SITE_URL, now))

    return built, sitemap_entries


def build_practitioner_pages(base, header, footer, practs, cal_rows, now):
    """Emit /practitioner/<slug>/ pages for every PUBLISHED practitioner + the
    /practitioners/ index (CAL-02). Individual profiles are curated (a bio is
    required to publish), so they're indexed; the index page is noindexed until
    it has enough profiles to be a real page (doorway-page discipline). Returns
    (built_outputs, sitemap_entries) — (loc, lastmod) per indexed page.
    """
    import shutil
    # Clear stale profile pages first: an unpublished practitioner must not leave
    # an orphaned page behind. The directory reflects ONLY the published set.
    shutil.rmtree(os.path.join(REPO, 'practitioner'), ignore_errors=True)

    print('\nGenerating practitioner pages...')
    built, sitemap_entries = [], []
    lastmod = external_events.stamp_date_iso(now)

    # Upcoming-session counts per practitioner (for the index cards).
    count_by_slug = {}
    for p in practs:
        count_by_slug[p['slug']] = len(
            practitioners_lib.sessions_for(p['slug'], cal_rows))

    # --- individual profile pages ---
    for p in practs:
        slug = p['slug']
        output = f'practitioner/{slug}/index.html'
        nav_prefix = '../../'
        canonical_url = practitioners_lib.practitioner_url(slug, SITE_URL)
        name = p['name']
        sessions = practitioners_lib.sessions_for(slug, cal_rows)

        title = f'{html_mod.escape(name)} · Sound bath practitioner | {SITE_NAME}'
        bio = ' '.join((p.get('bio') or '').split())
        description = (bio[:157].rstrip() + '…') if len(bio) > 158 else (
            bio or f'{name} leads sound baths on the Colorado Front Range. '
                   f'Bio and upcoming sessions.')
        meta_desc = (f'<meta name="description" '
                     f'content="{html_mod.escape(description, quote=True)}">')

        og_image = (external_events._safe_ext_url(p.get('photo_url') or '')
                    or f'{SITE_URL}/img/og-default.png')
        og_tags, twitter_tags = _og_twitter_tags(
            name, description, canonical_url, og_image)

        # Organization (publisher) + ProfilePage/Person + BreadcrumbList. The
        # Person carries operator-adjacent strings, so route it through _ldjson.
        schema_json = (f'<script type="application/ld+json">\n'
                       f'{json.dumps(ORG_SCHEMA, indent=2)}\n  </script>')
        _person = practitioners_lib.person_schema(p, canonical_url, sessions)
        schema_json += (f'\n  <script type="application/ld+json">\n'
                        f'{_ldjson(_person)}\n  </script>')
        breadcrumb_schema = {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Calendar",
                 "item": SITE_URL + "/"},
                {"@type": "ListItem", "position": 2, "name": "Practitioners",
                 "item": SITE_URL + "/practitioners/"},
                {"@type": "ListItem", "position": 3, "name": name},
            ],
        }
        schema_json += (f'\n  <script type="application/ld+json">\n'
                        f'{_ldjson(breadcrumb_schema)}\n  </script>')

        content = practitioners_lib.render_practitioner_page(
            p, sessions, nav_prefix, SITE_URL, now=now)
        page_header = header.strip().replace('{{nav_prefix}}', nav_prefix)
        page_footer = footer.strip().replace('{{nav_prefix}}', nav_prefix)

        html = _assemble(base, {
            'title': title,
            'robots': 'index, follow',
            'meta_description': meta_desc,
            'canonical_url': canonical_url,
            'css_path': nav_prefix,
            'page_style': practitioners_lib.PRACTITIONER_PAGE_STYLE,
            'og_tags': og_tags,
            'twitter_tags': twitter_tags,
            'schema_json': schema_json,
            'header': page_header,
            'content': content,
            'footer': page_footer,
        })
        if _write_page(output, html, built):
            print(f'  ✓ {output} ({count_by_slug.get(slug, 0)} upcoming)')
            sitemap_entries.append((canonical_url, lastmod))

    # --- index page (/practitioners/) ---
    # Doorway-page discipline: keep the directory out of the index until it has
    # a few real profiles; the individual pages still rank on their own.
    INDEX_MIN_INDEXED = 3
    index_output = 'practitioners/index.html'
    index_nav = '../'
    index_canonical = f'{SITE_URL}/practitioners/'
    indexable = len(practs) >= INDEX_MIN_INDEXED
    robots_value = 'index, follow' if indexable else 'noindex, follow'
    index_title = f'Practitioners | {SITE_NAME}'
    index_desc = ('The facilitators leading sound baths across Denver and the '
                  'Colorado Front Range: who they are and where to find them next.')
    index_meta = (f'<meta name="description" '
                  f'content="{html_mod.escape(index_desc, quote=True)}">')
    og_tags, twitter_tags = _og_twitter_tags(
        'Practitioners', index_desc, index_canonical,
        f'{SITE_URL}/img/og-default.png')

    schema_json = (f'<script type="application/ld+json">\n'
                   f'{json.dumps(ORG_SCHEMA, indent=2)}\n  </script>')
    _il = practitioners_lib.index_itemlist(practs, SITE_URL)
    if _il:
        schema_json += (f'\n  <script type="application/ld+json">\n'
                        f'{_ldjson(_il)}\n  </script>')
    index_breadcrumb = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Calendar",
             "item": SITE_URL + "/"},
            {"@type": "ListItem", "position": 2, "name": "Practitioners",
             "item": index_canonical},
        ],
    }
    schema_json += (f'\n  <script type="application/ld+json">\n'
                    f'{json.dumps(index_breadcrumb, indent=2)}\n  </script>')

    index_content = practitioners_lib.render_index(practs, count_by_slug, index_nav)
    page_header = header.strip().replace('{{nav_prefix}}', index_nav)
    page_footer = footer.strip().replace('{{nav_prefix}}', index_nav)
    html = _assemble(base, {
        'title': index_title,
        'robots': robots_value,
        'meta_description': index_meta,
        'canonical_url': index_canonical,
        'css_path': index_nav,
        'page_style': practitioners_lib.INDEX_STYLE,
        'og_tags': og_tags,
        'twitter_tags': twitter_tags,
        'schema_json': schema_json,
        'header': page_header,
        'content': index_content,
        'footer': page_footer,
    })
    if _write_page(index_output, html, built):
        print(f'  ✓ {index_output} ({len(practs)} listed, '
              f'{"indexed" if indexable else "noindex until 3"})')
        if indexable:
            sitemap_entries.append((index_canonical, lastmod))

    if not practs:
        print('  (no published practitioners yet)')

    return built, sitemap_entries


def build_venue_pages(base, header, footer, venue_list, cal_rows, now):
    """Emit /venue/<slug>/ pages for every PUBLISHED venue + the /venues/ index
    (CAL-03). Individual pages are curated (Daniel publishes the rooms worth a
    page), so they're indexed; the index is noindexed until it has a few
    (doorway-page discipline). Returns (built_outputs, sitemap_entries)."""
    import shutil
    shutil.rmtree(os.path.join(REPO, 'venue'), ignore_errors=True)

    print('\nGenerating venue pages...')
    built, sitemap_entries = [], []
    lastmod = external_events.stamp_date_iso(now)

    count_by_slug = {}
    for v in venue_list:
        count_by_slug[v['slug']] = len(venues_lib.sessions_for(v['slug'], cal_rows))

    for v in venue_list:
        slug = v['slug']
        output = f'venue/{slug}/index.html'
        nav_prefix = '../../'
        canonical_url = venues_lib.venue_url(slug, SITE_URL)
        name = v['name']
        sessions = venues_lib.sessions_for(slug, cal_rows)

        title = f'{html_mod.escape(name)} · Sound bath venue | {SITE_NAME}'
        where = ', '.join(x for x in (v.get('address'), v.get('city')) if x)
        desc_body = ' '.join((v.get('description') or '').split())
        description = (desc_body[:157].rstrip() + '…') if len(desc_body) > 158 else (
            desc_body or
            f'{name}{" in " + where if where else ""}: directions, what to expect, '
            f'and upcoming sound baths at this room.')
        meta_desc = (f'<meta name="description" '
                     f'content="{html_mod.escape(description, quote=True)}">')

        og_image = (external_events._safe_ext_url(v.get('photo_url') or '')
                    or f'{SITE_URL}/img/og-default.png')
        og_tags, twitter_tags = _og_twitter_tags(
            name, description, canonical_url, og_image)

        schema_json = (f'<script type="application/ld+json">\n'
                       f'{json.dumps(ORG_SCHEMA, indent=2)}\n  </script>')
        _place = venues_lib.place_schema(v, canonical_url, sessions)
        schema_json += (f'\n  <script type="application/ld+json">\n'
                        f'{_ldjson(_place)}\n  </script>')
        breadcrumb_schema = {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Calendar",
                 "item": SITE_URL + "/"},
                {"@type": "ListItem", "position": 2, "name": "Venues",
                 "item": SITE_URL + "/venues/"},
                {"@type": "ListItem", "position": 3, "name": name},
            ],
        }
        schema_json += (f'\n  <script type="application/ld+json">\n'
                        f'{_ldjson(breadcrumb_schema)}\n  </script>')

        content = venues_lib.render_venue_page(v, sessions, nav_prefix, SITE_URL, now=now)
        page_header = header.strip().replace('{{nav_prefix}}', nav_prefix)
        page_footer = footer.strip().replace('{{nav_prefix}}', nav_prefix)

        html = _assemble(base, {
            'title': title,
            'robots': 'index, follow',
            'meta_description': meta_desc,
            'canonical_url': canonical_url,
            'css_path': nav_prefix,
            'page_style': venues_lib.VENUE_PAGE_STYLE,
            'og_tags': og_tags,
            'twitter_tags': twitter_tags,
            'schema_json': schema_json,
            'header': page_header,
            'content': content,
            'footer': page_footer,
        })
        if _write_page(output, html, built):
            print(f'  ✓ {output} ({count_by_slug.get(slug, 0)} upcoming)')
            sitemap_entries.append((canonical_url, lastmod))

    # --- index (/venues/) ---
    INDEX_MIN_INDEXED = 3
    index_output = 'venues/index.html'
    index_nav = '../'
    index_canonical = f'{SITE_URL}/venues/'
    indexable = len(venue_list) >= INDEX_MIN_INDEXED
    robots_value = 'index, follow' if indexable else 'noindex, follow'
    index_desc = ('The rooms hosting sound baths across Denver and the Colorado '
                  'Front Range: where they are, what to expect, and what is on next.')
    index_meta = (f'<meta name="description" '
                  f'content="{html_mod.escape(index_desc, quote=True)}">')
    og_tags, twitter_tags = _og_twitter_tags(
        'Venues', index_desc, index_canonical, f'{SITE_URL}/img/og-default.png')

    schema_json = (f'<script type="application/ld+json">\n'
                   f'{json.dumps(ORG_SCHEMA, indent=2)}\n  </script>')
    _il = venues_lib.index_itemlist(venue_list, SITE_URL)
    if _il:
        schema_json += (f'\n  <script type="application/ld+json">\n'
                        f'{_ldjson(_il)}\n  </script>')
    index_breadcrumb = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Calendar",
             "item": SITE_URL + "/"},
            {"@type": "ListItem", "position": 2, "name": "Venues",
             "item": index_canonical},
        ],
    }
    schema_json += (f'\n  <script type="application/ld+json">\n'
                    f'{json.dumps(index_breadcrumb, indent=2)}\n  </script>')

    index_content = venues_lib.render_index(venue_list, count_by_slug, index_nav)
    page_header = header.strip().replace('{{nav_prefix}}', index_nav)
    page_footer = footer.strip().replace('{{nav_prefix}}', index_nav)
    html = _assemble(base, {
        'title': f'Venues | {SITE_NAME}',
        'robots': robots_value,
        'meta_description': index_meta,
        'canonical_url': index_canonical,
        'css_path': index_nav,
        'page_style': venues_lib.INDEX_STYLE,
        'og_tags': og_tags,
        'twitter_tags': twitter_tags,
        'schema_json': schema_json,
        'header': page_header,
        'content': index_content,
        'footer': page_footer,
    })
    if _write_page(index_output, html, built):
        print(f'  ✓ {index_output} ({len(venue_list)} listed, '
              f'{"indexed" if indexable else "noindex until 3"})')
        if indexable:
            sitemap_entries.append((index_canonical, lastmod))

    if not venue_list:
        print('  (no published venues yet)')

    return built, sitemap_entries


def build_operator_pages(base, header, footer, operator_list, cal_rows, now):
    """Emit /operator/<slug>/ pages for every PUBLISHED operator + the
    /operators/ index (CAL-08). Individual pages are curated (Daniel publishes
    only the multi-venue organizers worth a distinct page — the owner-operated
    single-room duplicates stay drafts), so they're indexed; the index is
    noindexed until it has a few (doorway-page discipline). Returns
    (built_outputs, sitemap_entries)."""
    import shutil
    shutil.rmtree(os.path.join(REPO, 'operator'), ignore_errors=True)

    print('\nGenerating operator pages...')
    built, sitemap_entries = [], []
    lastmod = external_events.stamp_date_iso(now)

    count_by_slug = {}
    for o in operator_list:
        count_by_slug[o['slug']] = len(operators_lib.sessions_for(o['slug'], cal_rows))

    for o in operator_list:
        slug = o['slug']
        output = f'operator/{slug}/index.html'
        nav_prefix = '../../'
        canonical_url = operators_lib.operator_url(slug, SITE_URL)
        name = o['name']
        sessions = operators_lib.sessions_for(slug, cal_rows)

        title = f'{html_mod.escape(name)} · Sound bath organizer | {SITE_NAME}'
        desc_body = ' '.join((o.get('description') or '').split())
        description = (desc_body[:157].rstrip() + '…') if len(desc_body) > 158 else (
            desc_body or
            f'{name}: the sound baths they run across Denver and the Front Range, '
            f'and where to catch them next.')
        meta_desc = (f'<meta name="description" '
                     f'content="{html_mod.escape(description, quote=True)}">')

        og_image = f'{SITE_URL}/img/og-default.png'
        og_tags, twitter_tags = _og_twitter_tags(
            name, description, canonical_url, og_image)

        schema_json = (f'<script type="application/ld+json">\n'
                       f'{json.dumps(ORG_SCHEMA, indent=2)}\n  </script>')
        _org = operators_lib.organization_schema(o, canonical_url)
        schema_json += (f'\n  <script type="application/ld+json">\n'
                        f'{_ldjson(_org)}\n  </script>')
        breadcrumb_schema = {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Calendar",
                 "item": SITE_URL + "/"},
                {"@type": "ListItem", "position": 2, "name": "Organizers",
                 "item": SITE_URL + "/operators/"},
                {"@type": "ListItem", "position": 3, "name": name},
            ],
        }
        schema_json += (f'\n  <script type="application/ld+json">\n'
                        f'{_ldjson(breadcrumb_schema)}\n  </script>')

        content = operators_lib.render_operator_page(o, sessions, nav_prefix, SITE_URL, now=now)
        page_header = header.strip().replace('{{nav_prefix}}', nav_prefix)
        page_footer = footer.strip().replace('{{nav_prefix}}', nav_prefix)

        html = _assemble(base, {
            'title': title,
            'robots': 'index, follow',
            'meta_description': meta_desc,
            'canonical_url': canonical_url,
            'css_path': nav_prefix,
            'page_style': operators_lib.OPERATOR_PAGE_STYLE,
            'og_tags': og_tags,
            'twitter_tags': twitter_tags,
            'schema_json': schema_json,
            'header': page_header,
            'content': content,
            'footer': page_footer,
        })
        if _write_page(output, html, built):
            print(f'  ✓ {output} ({count_by_slug.get(slug, 0)} upcoming)')
            sitemap_entries.append((canonical_url, lastmod))

    # --- index (/operators/) ---
    INDEX_MIN_INDEXED = 3
    index_output = 'operators/index.html'
    index_nav = '../'
    index_canonical = f'{SITE_URL}/operators/'
    indexable = len(operator_list) >= INDEX_MIN_INDEXED
    robots_value = 'index, follow' if indexable else 'noindex, follow'
    index_desc = ('The collectives and studios running sound baths across Denver and '
                  'the Colorado Front Range: who they are, and where to catch them next.')
    index_meta = (f'<meta name="description" '
                  f'content="{html_mod.escape(index_desc, quote=True)}">')
    og_tags, twitter_tags = _og_twitter_tags(
        'Organizers', index_desc, index_canonical, f'{SITE_URL}/img/og-default.png')

    schema_json = (f'<script type="application/ld+json">\n'
                   f'{json.dumps(ORG_SCHEMA, indent=2)}\n  </script>')
    _il = operators_lib.index_itemlist(operator_list, SITE_URL)
    if _il:
        schema_json += (f'\n  <script type="application/ld+json">\n'
                        f'{_ldjson(_il)}\n  </script>')
    index_breadcrumb = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Calendar",
             "item": SITE_URL + "/"},
            {"@type": "ListItem", "position": 2, "name": "Organizers",
             "item": index_canonical},
        ],
    }
    schema_json += (f'\n  <script type="application/ld+json">\n'
                    f'{json.dumps(index_breadcrumb, indent=2)}\n  </script>')

    index_content = operators_lib.render_index(operator_list, count_by_slug, index_nav)
    page_header = header.strip().replace('{{nav_prefix}}', index_nav)
    page_footer = footer.strip().replace('{{nav_prefix}}', index_nav)
    html = _assemble(base, {
        'title': f'Organizers | {SITE_NAME}',
        'robots': robots_value,
        'meta_description': index_meta,
        'canonical_url': index_canonical,
        'css_path': index_nav,
        'page_style': operators_lib.INDEX_STYLE,
        'og_tags': og_tags,
        'twitter_tags': twitter_tags,
        'schema_json': schema_json,
        'header': page_header,
        'content': index_content,
        'footer': page_footer,
    })
    if _write_page(index_output, html, built):
        print(f'  ✓ {index_output} ({len(operator_list)} listed, '
              f'{"indexed" if indexable else "noindex until 3"})')
        if indexable:
            sitemap_entries.append((index_canonical, lastmod))

    if not operator_list:
        print('  (no published operators yet)')

    return built, sitemap_entries


def build_insights_pages(base, header, footer, now):
    """Emit the "State of Sound Healing on the Front Range" data report (CAL-06).

      /state-of-sound-healing/            — hub: the latest edition + archive
      /state-of-sound-healing/<slug>/     — each frozen edition permalink

    A DISCOVERY-LAYER asset (search/AI/press citation) — linked from the footer,
    llms.txt, and the sitemap, but NOT the primary participant nav. Editions are
    FROZEN JSONs under data/insights/ emitted by the marketing analysis script;
    the build only renders them (no recompute), so a cited stat never drifts and
    CI stays hermetic. Gated on there being at least one valid edition. Returns
    (built_outputs, sitemap_entries)."""
    print('\nGenerating State of Sound Healing report...')
    editions = insights_lib.load_editions(REPO)
    built, sitemap_entries = [], []
    if not editions:
        print('  ⚠ no valid insights editions — skipping (page not built)')
        return built, sitemap_entries

    latest = editions[0]

    def _emit(output, nav_prefix, agg, others, is_hub):
        ed = agg['edition']
        window = insights_lib._fmt_window(ed)
        canonical = (f'{SITE_URL}/state-of-sound-healing/' if is_hub
                     else f'{SITE_URL}/state-of-sound-healing/{ed["slug"]}/')
        title = (f'State of Sound Healing on the Front Range — {ed["label"]} '
                 f'| {SITE_NAME}')
        description = (f'An original-data snapshot of the Front Range sound bath '
                       f'scene, {ed["label"]}: {agg["volume"]["sessions"]} sessions, '
                       f'a ${agg["price"]["median"]:g} median price, '
                       f'{agg["timing"]["evening_pct"]:.0f}% in the evening, across '
                       f'{agg["volume"]["cities"]} metros. Free to cite.')
        og_image = f'{SITE_URL}/img/insights/og-{ed["slug"]}.jpg'
        meta_desc = (f'<meta name="description" '
                     f'content="{html_mod.escape(description, quote=True)}">')
        og_tags, twitter_tags = _og_twitter_tags(
            f'State of Sound Healing — {ed["label"]}', description, canonical, og_image)

        # Dataset (the GEO payload) + Article + BreadcrumbList.
        dataset = {
            "@context": "https://schema.org", "@type": "Dataset",
            "name": f"State of Sound Healing on the Front Range — {ed['label']}",
            "description": description,
            "url": canonical,
            "temporalCoverage": f"{ed['window_start']}/{ed['window_end']}",
            "spatialCoverage": {
                "@type": "Place",
                "name": "Front Range, Colorado (Denver, Boulder, Fort Collins, Colorado Springs)",
            },
            "isAccessibleForFree": True,
            "license": "https://creativecommons.org/licenses/by/4.0/",
            "creator": {"@type": "Organization", "name": SITE_NAME, "url": SITE_URL},
            "dateModified": ed["generated_at"][:10],
        }
        article = {
            "@context": "https://schema.org", "@type": "Report",
            "headline": f"The Front Range Sound Bath Scene: A {ed['label']} Snapshot",
            "about": "Sound baths and sound healing sessions on Colorado's Front Range",
            "isPartOf": {"@type": "WebSite", "name": SITE_NAME, "url": SITE_URL},
            "publisher": {"@type": "Organization", "name": SITE_NAME, "url": SITE_URL},
            "url": canonical,
        }
        crumbs = [{"@type": "ListItem", "position": 1, "name": "Calendar",
                   "item": SITE_URL + "/"},
                  {"@type": "ListItem", "position": 2, "name": "State of Sound Healing",
                   "item": SITE_URL + "/state-of-sound-healing/"}]
        if not is_hub:
            crumbs.append({"@type": "ListItem", "position": 3, "name": ed["label"],
                           "item": canonical})
        breadcrumb = {"@context": "https://schema.org", "@type": "BreadcrumbList",
                      "itemListElement": crumbs}
        schema_json = '\n  '.join(
            f'<script type="application/ld+json">\n{_ldjson(obj)}\n  </script>'
            for obj in (ORG_SCHEMA, dataset, article, breadcrumb))

        content = insights_lib.render_report(agg, nav_prefix, others)
        page_header = header.strip().replace('{{nav_prefix}}', nav_prefix)
        page_footer = footer.strip().replace('{{nav_prefix}}', nav_prefix)
        html = _assemble(base, {
            'title': title, 'robots': 'index, follow', 'meta_description': meta_desc,
            'canonical_url': canonical, 'css_path': nav_prefix,
            'page_style': insights_lib.INSIGHTS_HEAD,
            'og_tags': og_tags, 'twitter_tags': twitter_tags,
            'schema_json': schema_json, 'header': page_header,
            'content': content, 'footer': page_footer,
        })
        if _write_page(output, html, built):
            print(f'  ✓ {output}')
            sitemap_entries.append((canonical, external_events.stamp_date_iso(now)))

    # Hub = latest edition inline, with the rest listed as archive.
    _emit('state-of-sound-healing/index.html', '../', latest, editions[1:], True)
    # Each edition also gets a stable dated permalink.
    for i, ed in enumerate(editions):
        _emit(f'state-of-sound-healing/{ed["edition"]["slug"]}/index.html', '../../',
              ed, editions[:i] + editions[i + 1:], False)
    return built, sitemap_entries


def build_tag_pages(base, header, footer, cal_rows, now, geocode=None):
    """Emit a curated landing page per canonical tag that clears BUILD_MIN
    upcoming events (/<tag-slug>/, e.g. /gong-bath/) plus the /tags/ index —
    CAL-09. SITE-ONLY: pages derive from the CAL-01 taxonomy + the rows the
    calendar already renders (no admin, no feed, no DB).

    Doorway discipline: a tag page is indexed only at/above INDEX_MIN; thinner
    ones (BUILD_MIN..INDEX_MIN-1) are built but noindexed; below BUILD_MIN there
    is no page at all. Root-level unless a slug would collide with a reserved
    path, in which case /tag/<slug>/. Today only ~2 tags qualify (gong-bath,
    breathwork-sound) — EXPECTED; the machinery lets pages appear as Daniel
    curates per-event tags. Returns (built_outputs, sitemap_entries).
    """
    import shutil
    # The /tag/<slug>/ collision-fallback dir is ours alone — clear stale ones.
    # Root-level tag dirs aren't blanket-removed (can't safely); CI builds clean.
    shutil.rmtree(os.path.join(REPO, 'tag'), ignore_errors=True)

    print('\nGenerating tag pages...')
    built, sitemap_entries = [], []
    lastmod = external_events.stamp_date_iso(now)

    tags = tag_pages_lib.qualifying_tags(cal_rows)
    built_map = tag_pages_lib.linked_tag_map(cal_rows)  # {slug: page path}

    for t in tags:
        slug = t['slug']
        label = t['label']
        output = tag_pages_lib.tag_page_output(slug)
        nav_prefix = tag_pages_lib.tag_nav_prefix(slug)
        canonical_url = tag_pages_lib.tag_page_url(slug, SITE_URL)

        title = f'{label} sound baths on the Front Range | {SITE_NAME}'
        description = (f'Upcoming {label.lower()} sound baths across Denver, '
                       f'Boulder, Fort Collins, and Colorado Springs: dates, '
                       f'times, venues, prices, and ticket links.')
        meta_desc = (f'<meta name="description" '
                     f'content="{html_mod.escape(description, quote=True)}">')

        # Doorway discipline: index only the pages with real depth.
        robots_value = 'index, follow' if t['indexable'] else 'noindex, follow'

        og_image = f'{SITE_URL}/img/og-default.png'
        og_tags, twitter_tags = _og_twitter_tags(
            label, description, canonical_url, og_image)

        # Organization (publisher) + CollectionPage + ItemList + FAQPage +
        # BreadcrumbList. The ItemList carries external-operator strings, so it
        # routes through _ldjson (breakout-safe); the rest are our own.
        schema_json = (f'<script type="application/ld+json">\n'
                       f'{json.dumps(ORG_SCHEMA, indent=2)}\n  </script>')
        _cp = tag_pages_lib.tag_collectionpage_schema(
            slug, canonical_url, SITE_URL, description, lastmod)
        schema_json += (f'\n  <script type="application/ld+json">\n'
                        f'{_ldjson(_cp)}\n  </script>')
        _il = tag_pages_lib.tag_itemlist(cal_rows, slug, SITE_URL)
        if _il:
            schema_json += (f'\n  <script type="application/ld+json">\n'
                            f'{_ldjson(_il)}\n  </script>')
        _faq = tag_pages_lib.tag_faqpage_schema(cal_rows, slug)
        schema_json += (f'\n  <script type="application/ld+json">\n'
                        f'{_ldjson(_faq)}\n  </script>')
        breadcrumb_schema = {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Calendar",
                 "item": SITE_URL + "/"},
                {"@type": "ListItem", "position": 2, "name": "Tags",
                 "item": SITE_URL + "/tags/"},
                {"@type": "ListItem", "position": 3, "name": label,
                 "item": canonical_url},
            ],
        }
        schema_json += (f'\n  <script type="application/ld+json">\n'
                        f'{json.dumps(breadcrumb_schema, indent=2)}\n  </script>')

        content = tag_pages_lib.render_tag_page(
            cal_rows, slug, nav_prefix, built_map, now=now, geocode=geocode)
        page_header = header.strip().replace('{{nav_prefix}}', nav_prefix)
        page_footer = footer.strip().replace('{{nav_prefix}}', nav_prefix)

        html = _assemble(base, {
            'title':            title,
            'robots':           robots_value,
            'meta_description': meta_desc,
            'canonical_url':    canonical_url,
            'css_path':         nav_prefix,
            'page_style':       '',
            'og_tags':          og_tags,
            'twitter_tags':     twitter_tags,
            'schema_json':      schema_json,
            'header':           page_header,
            'content':          content,
            'footer':           page_footer,
        })

        if not _write_page(output, html, built):
            continue
        print(f'  ✓ {output} ({t["count"]} upcoming, '
              f'{"indexed" if t["indexable"] else "noindex until %d" % tag_pages_lib.INDEX_MIN})')
        if t['indexable']:
            sitemap_entries.append((canonical_url, lastmod))

    # --- index page (/tags/) ---
    # Doorway discipline: keep the directory out of the index until it has a few
    # real tag pages; the individual pages still rank on their own.
    index_output = 'tags/index.html'
    index_nav = '../'
    index_canonical = f'{SITE_URL}/tags/'
    indexable = len(tags) >= tag_pages_lib.TAGS_INDEX_MIN
    robots_value = 'index, follow' if indexable else 'noindex, follow'
    index_title = f'Browse sound baths by tag | {SITE_NAME}'
    index_desc = ('Sound baths on the Colorado Front Range grouped by tag — what '
                  'makes the sound, why people come, the setting, and who they '
                  'are for.')
    index_meta = (f'<meta name="description" '
                  f'content="{html_mod.escape(index_desc, quote=True)}">')
    og_tags, twitter_tags = _og_twitter_tags(
        'Browse by tag', index_desc, index_canonical,
        f'{SITE_URL}/img/og-default.png')

    schema_json = (f'<script type="application/ld+json">\n'
                   f'{json.dumps(ORG_SCHEMA, indent=2)}\n  </script>')
    _il = tag_pages_lib.index_itemlist(tags, SITE_URL)
    if _il:
        schema_json += (f'\n  <script type="application/ld+json">\n'
                        f'{_ldjson(_il)}\n  </script>')
    index_breadcrumb = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Calendar",
             "item": SITE_URL + "/"},
            {"@type": "ListItem", "position": 2, "name": "Tags",
             "item": index_canonical},
        ],
    }
    schema_json += (f'\n  <script type="application/ld+json">\n'
                    f'{json.dumps(index_breadcrumb, indent=2)}\n  </script>')

    index_content = tag_pages_lib.render_index(tags, index_nav)
    page_header = header.strip().replace('{{nav_prefix}}', index_nav)
    page_footer = footer.strip().replace('{{nav_prefix}}', index_nav)
    html = _assemble(base, {
        'title':            index_title,
        'robots':           robots_value,
        'meta_description': index_meta,
        'canonical_url':    index_canonical,
        'css_path':         index_nav,
        'page_style':       tag_pages_lib.INDEX_STYLE,
        'og_tags':          og_tags,
        'twitter_tags':     twitter_tags,
        'schema_json':      schema_json,
        'header':           page_header,
        'content':          index_content,
        'footer':           page_footer,
    })
    if _write_page(index_output, html, built):
        print(f'  ✓ {index_output} ({len(tags)} tag page(s), '
              f'{"indexed" if indexable else "noindex until %d" % tag_pages_lib.TAGS_INDEX_MIN})')
        if indexable:
            sitemap_entries.append((index_canonical, lastmod))

    if not tags:
        print('  (no tags clear the inventory threshold yet)')

    return built, sitemap_entries


def build_map_page(base, header, footer, cal_rows, now, geocode=None):
    """Emit /map/ — an interactive Leaflet map of every upcoming session, pinned
    by venue (CAL-04). Coordinates come from the committed data/geocode.json
    (loaded once in build() and shared with the near-me sort); venues without
    one simply have no pin. Returns (built_outputs, sitemap)."""
    print('\nGenerating map page...')
    if geocode is None:
        geocode = mapview_lib.load_geocode(REPO)
    nav_prefix = '../'
    pins = mapview_lib.build_pins(cal_rows, geocode, nav_prefix)

    output = 'map/index.html'
    canonical_url = f'{SITE_URL}/map/'
    title = f'Map of sound baths on the Front Range | {SITE_NAME}'
    description = ('An interactive map of every upcoming sound bath across Denver '
                  'and the Colorado Front Range — pinned by room, with dates and '
                  'ticket links.')
    meta_desc = (f'<meta name="description" '
                 f'content="{html_mod.escape(description, quote=True)}">')
    og_tags, twitter_tags = _og_twitter_tags(
        'Sound baths on the map', description, canonical_url,
        f'{SITE_URL}/img/og-default.png')

    schema_json = (f'<script type="application/ld+json">\n'
                   f'{json.dumps(ORG_SCHEMA, indent=2)}\n  </script>')
    collectionpage = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": "Sound baths on the Front Range map",
        "url": canonical_url,
        "description": description,
        "isPartOf": {"@type": "WebSite", "name": SITE_NAME, "url": SITE_URL},
    }
    schema_json += (f'\n  <script type="application/ld+json">\n'
                    f'{json.dumps(collectionpage, indent=2)}\n  </script>')
    breadcrumb = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Calendar",
             "item": SITE_URL + "/"},
            {"@type": "ListItem", "position": 2, "name": "Map", "item": canonical_url},
        ],
    }
    schema_json += (f'\n  <script type="application/ld+json">\n'
                    f'{json.dumps(breadcrumb, indent=2)}\n  </script>')

    content = mapview_lib.render_map_page(
        pins, nav_prefix, external_events.fmt_stamp_date(now),
        cal_rows=cal_rows, now=now, geocode=geocode)
    page_header = header.strip().replace('{{nav_prefix}}', nav_prefix)
    page_footer = footer.strip().replace('{{nav_prefix}}', nav_prefix)

    html = _assemble(base, {
        'title': title,
        'robots': 'index, follow',
        'meta_description': meta_desc,
        'canonical_url': canonical_url,
        'css_path': nav_prefix,
        'page_style': mapview_lib.MAP_HEAD,
        'og_tags': og_tags,
        'twitter_tags': twitter_tags,
        'schema_json': schema_json,
        'header': page_header,
        'content': content,
        'footer': page_footer,
    })
    built, sitemap_entries = [], []
    if _write_page(output, html, built):
        print(f'  ✓ {output} ({len(pins)} pins from {len(cal_rows)} rows)')
        sitemap_entries.append((canonical_url, external_events.stamp_date_iso(now)))
    return built, sitemap_entries


def _sitemap_url_entry(loc, lastmod):
    """Render one <url> block: loc + lastmod. changefreq/priority are dropped
    (Google ignores both); lastmod is the field crawlers actually use."""
    lines = ['  <url>', f'    <loc>{loc}</loc>']
    if lastmod:
        lines.append(f'    <lastmod>{lastmod}</lastmod>')
    lines.append('  </url>')
    return '\n'.join(lines) + '\n'


def generate_sitemap(page_dirs, cal_now, extra_urls=None):
    """Generate sitemap.xml: the root (lastmod = build date — the calendar
    changes every build), any other indexable page, then the upcoming event
    permalink pages by loc. noindex pages and redirect stubs are excluded.
    """
    print('\nGenerating sitemap...')

    homepage_entry = None
    root_entries = []

    for page_path in sorted(page_dirs):
        page_name = os.path.relpath(page_path, PAGES)
        config = json.loads(read(os.path.join(page_path, 'config.json')))
        if config.get('skip') or config.get('redirect_to'):
            continue
        output = config.get('output', f'{page_name}.html')
        if output == '404.html':
            continue
        robots_value = config.get('robots', 'index, follow')
        if 'noindex' in robots_value:
            continue
        lastmod = config.get('lastmod') or external_events.stamp_date_iso(cal_now)
        xml = _sitemap_url_entry(page_url(output), lastmod)
        if output == 'index.html':
            homepage_entry = xml
        else:
            root_entries.append((output, xml))

    root_entries.sort(key=lambda x: x[0])
    event_entries = sorted(
        ((loc, _sitemap_url_entry(loc, lastmod)) for loc, lastmod in (extra_urls or [])),
        key=lambda x: x[0],
    )

    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    if homepage_entry:
        parts.append(homepage_entry.rstrip('\n'))
    parts.extend(xml.rstrip('\n') for _, xml in root_entries)
    parts.extend(xml.rstrip('\n') for _, xml in event_entries)
    parts.append('</urlset>')
    sitemap_xml = '\n'.join(parts) + '\n'

    with open(os.path.join(REPO, 'sitemap.xml'), 'w', encoding='utf-8') as f:
        f.write(sitemap_xml)
    print(f'  ✓ sitemap.xml ({1 if homepage_entry else 0}+{len(root_entries)} page, '
          f'{len(event_entries)} event)')


if __name__ == '__main__':
    print('Building Sound Bath Calendar...\n')
    build()
    print('\nDone.')
