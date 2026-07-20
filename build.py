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
    print()

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
                cal_rows, nav_prefix, now=cal_now)
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
        base, header, footer, cal_rows, cal_now)
    pages_built.extend(_city_outputs)

    # --- Per-event permalink pages (/event/<slug>/) ---
    _event_outputs, _event_sitemap = build_event_pages(
        base, header, footer, cal_feed, cal_now)
    pages_built.extend(_event_outputs)

    print(f'\nBuilt {len(pages_built)} pages.')

    generate_sitemap(page_dirs, cal_now, extra_urls=_city_sitemap + _event_sitemap)


def build_city_pages(base, header, footer, cal_rows, now):
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

        content = external_events.render_city_page(cal_rows, city, nav_prefix, now=now)
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
