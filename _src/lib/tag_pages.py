"""Sound Bath Calendar — curated tag landing pages (CAL-09).

The payoff of the CAL-01 tag taxonomy: a durable, indexable landing page per
canonical tag (`/<tag-slug>/`, e.g. /gong-bath/, /grief-loss/) that answers a
real long-tail intent ("gong bath denver", "grief sound bath") and is a clean
citation surface for AI answer engines. No admin, no DB, no feed — the pages
derive entirely from the taxonomy + the rows the calendar already renders.

── DOORWAY-PAGE DISCIPLINE ──────────────────────────────────────────────────
A tag page is EARNED by real inventory, never spun up for content's sake:

  count >= INDEX_MIN  → build + index          (a real, useful list)
  BUILD_MIN <= count  → build + noindex         (live, but too thin to index)
  count <  BUILD_MIN  → skip entirely           (no page at all)

Today only ~2 tags clear the bar (gong-bath, breathwork-sound) — that's
EXPECTED. This module is the machinery; pages appear on their own as Daniel
curates per-event tags in the admin and inventory crosses the threshold.

Assembly (base layout, <head>, publisher schema) is build.py's job; this module
returns the <main> body + the page-specific CollectionPage/ItemList/FAQPage
schema, mirroring the city-page pipeline in external_events.
"""

from _src.lib import external_events as X
from _src.lib import taxonomy

_esc = X._esc

# Doorway thresholds (upcoming-event counts). INDEX_MIN gates indexing; BUILD_MIN
# gates whether a page exists at all. Flagged for Daniel — tune as inventory grows.
BUILD_MIN = 2
INDEX_MIN = 4

# The /tags/ directory stays out of the index until it has a few real pages.
TAGS_INDEX_MIN = 3


# ---------------------------------------------------------------------------
# Collision guard — never squat a reserved root path. A tag slug that would
# collide falls back to /tag/<slug>/. None of the v1 vocabulary collides today;
# this is safety for any slug the taxonomy gains later.
# ---------------------------------------------------------------------------
RESERVED_ROOT_SLUGS = frozenset({
    # City pages
    'denver', 'boulder', 'fort-collins', 'colorado-springs',
    # Curated-entity sections + their singulars
    'venues', 'venue', 'practitioners', 'practitioner',
    'operators', 'operator',
    # Other built surfaces
    'map', 'event', 'thanks', 'what-to-expect', 'state-of-sound-healing',
    'summer-2026', 'tags', 'tag',
    # Root files / asset dirs (defensive — a slug is a directory name)
    'feed', 'feed.xml', 'sitemap', 'sitemap.xml', 'robots', 'robots.txt',
    'llms', 'llms.txt', 'styles', 'filters', 'index',
    'img', 'vendor', 'scripts', 'data',
})


def tag_page_path(slug):
    """Site-relative path (trailing slash) for a tag page. Root-level unless the
    slug would collide with a reserved path, in which case /tag/<slug>/."""
    if slug in RESERVED_ROOT_SLUGS:
        return f'tag/{slug}/'
    return f'{slug}/'


def tag_page_output(slug):
    """Build output path for a tag page's index.html."""
    return f'{tag_page_path(slug)}index.html'


def tag_page_url(slug, site_url):
    return f'{site_url}/{tag_page_path(slug)}'


def tag_nav_prefix(slug):
    """'../' per directory level in the page path — so links resolve from the
    page's own depth (/gong-bath/ → ../ ; /tag/<slug>/ → ../../)."""
    return '../' * tag_page_path(slug).count('/')


# ---------------------------------------------------------------------------
# Row selection + qualification
# ---------------------------------------------------------------------------

def tag_rows(rows, slug):
    """The subset of rows carrying `slug`, in the incoming (chronological) order.
    `rows` is build_rows output — already future, de-duplicated, and sorted."""
    return [r for r in rows if slug in X.row_tag_slugs(r)]


def tag_counts(rows):
    """{slug: upcoming count} across the canonical vocabulary (present tags only)."""
    counts = {}
    for r in rows:
        for s in X.row_tag_slugs(r):
            counts[s] = counts.get(s, 0) + 1
    return counts


def qualifying_tags(rows):
    """Tags that clear BUILD_MIN, in vocabulary order. Each entry is a dict:
    {slug, label, axis, count, indexable}. `indexable` is True at/above INDEX_MIN
    (doorway discipline: thinner pages are built but noindexed)."""
    counts = tag_counts(rows)
    out = []
    for slug, label, axis in taxonomy.TAGS:
        n = counts.get(slug, 0)
        if n < BUILD_MIN:
            continue
        out.append({
            'slug': slug, 'label': label, 'axis': axis,
            'count': n, 'indexable': n >= INDEX_MIN,
        })
    return out


def linked_tag_map(rows):
    """{slug: tag_page_path(slug)} for every tag that WILL have a built page —
    the map the chip renderer uses to decide which chips become links."""
    return {t['slug']: tag_page_path(t['slug']) for t in qualifying_tags(rows)}


# ---------------------------------------------------------------------------
# Copy. Every intro is an audience-first answer to the tag's intent — honest,
# non-woo, 2–3 sentences, in the calendar's factual voice. All flagged
# <!-- HUMAN REVIEW --> for Daniel. Curated intros below; the rest fall back to
# an axis-shaped generic so a newly-crossed tag always renders sane copy.
# ---------------------------------------------------------------------------
TAG_INTRO = {
    'gong-bath': (
        'A gong bath is a sound bath built around the gong — you lie down while '
        'a facilitator plays one or more gongs, letting the sustained, washing '
        'tone carry the session. It tends to run louder and more physical than a '
        'bowls-only sound bath, and you stay clothed and still throughout.'),
    'breathwork-sound': (
        'These sessions pair an active breathing practice with live sound: you '
        'move through a guided breath pattern while gongs, bowls, or drums play, '
        'then rest into the tones. Expect to be more physically engaged than in a '
        'lie-still sound bath — the breathwork does real work before the sound '
        'settles you.'),
    'crystal-bowls': (
        'Crystal (quartz) singing bowls make the clear, ringing tone most people '
        'picture when they think of a sound bath. Sessions center on those bowls '
        'while you lie down and rest; you stay clothed and still the whole time.'),
    'himalayan-bowls': (
        'Himalayan (Tibetan) metal singing bowls carry a warmer, more layered '
        'tone than crystal bowls. These sessions build the sound bath around them '
        'while you lie down and rest, clothed, for the length of the session.'),
    'deep-rest': (
        'These sessions are aimed squarely at rest and sleep — slower, quieter, '
        'and often held in the evening. You lie down, stay still, and let the '
        'sound do the settling; some people drift off, which is fine.'),
    'grief-loss': (
        'Sound baths held with grief and loss in mind give you a quiet, low-'
        'pressure place to be with heavy feelings — no talking required, no fixing '
        'expected. You lie down and rest while the sound plays; tears are welcome '
        'and common, and you can leave whenever you need to.'),
    'anxiety-relief': (
        'These sessions are framed around stress and anxiety: steady, grounding '
        'sound and permission to do nothing for an hour. Lying still and following '
        'the tones can calm the nervous system, though a sound bath is a rest '
        'practice, not medical treatment.'),
    'new-moon': (
        'New-moon sound baths are timed to the dark of the moon — often framed '
        'around setting intentions or starting fresh. The session itself is a '
        'normal sound bath: you lie down, stay still, and rest while the '
        'instruments play.'),
    'full-moon': (
        'Full-moon sound baths are timed to the full moon and often framed around '
        'release or completion. The format is a normal sound bath — you lie down '
        'and rest while gongs and bowls play — with the moon as the occasion.'),
    'candlelit': (
        'Candlelit sessions trade overhead light for low candlelight, which makes '
        'it easier to close your eyes and settle. Everything else is a normal '
        'sound bath: you lie down, stay still, and rest while the sound plays.'),
    'outdoor': (
        'These sound baths are held outside — a park, a garden, a reservoir — so '
        'the sound sits inside real ambient noise rather than a quiet room. Bring '
        'a mat or blanket and layers; weather can move or cancel a session.'),
    'yoga-nidra': (
        'Yoga nidra is a guided, lying-down "sleep-based" meditation; paired with '
        'sound, a facilitator talks you through a body scan while instruments play '
        'underneath. You stay still on your back the whole time — no poses, no '
        'flow.'),
    'womens': (
        "These are women's-circle sound baths — held for women, often with time "
        'to gather before or after the sound itself. The sound bath runs as usual: '
        'you lie down, stay still, and rest while the instruments play.'),
    'beginner-friendly': (
        'These sessions are a good first sound bath: nothing is expected of you '
        'beyond lying down and resting, and facilitators explain what will happen '
        'before they start. You stay clothed and still throughout — there is no '
        'way to do it wrong.'),
    'free-donation': (
        'These sessions are free or offered by donation, so cost is not a barrier '
        'to trying one. The experience is the same as a paid sound bath — you lie '
        'down and rest while the instruments play — so it is a low-stakes way to '
        'find out whether sound baths are for you.'),
}

# Axis-shaped generic fallbacks — a real slug that crosses the threshold before
# it has a hand-written intro still gets honest, on-voice copy.
_GENERIC_INTRO = {
    'modality': (
        'These sound baths are built around {label_l} — that is the sound at the '
        'center of the session. You lie down, stay clothed and still, and rest '
        'while the instruments play, usually for 45 to 75 minutes.'),
    'intent': (
        'These sessions are held with {label_l} in mind — the reason people come '
        'rather than a different kind of sound. The format is a normal sound bath: '
        'you lie down, stay still, and rest while the instruments play.'),
    'setting': (
        'What sets these sessions apart is the setting — {label_l}. The sound bath '
        'itself runs as usual: you lie down, stay clothed and still, and rest for '
        'the length of the session.'),
    'access': (
        'These listings are flagged {label_l}, so you know before you book. The '
        'session is a normal sound bath — you lie down and rest while the '
        'instruments play — with that detail confirmed up front.'),
}


def tag_intro(slug):
    """Audience-first intro paragraph (HTML-safe already via caller esc), or a
    generic axis-shaped fallback. Marked HUMAN REVIEW by the caller."""
    if slug in TAG_INTRO:
        return TAG_INTRO[slug]
    axis = taxonomy.AXIS_BY_SLUG.get(slug, 'modality')
    label_l = taxonomy.label_for(slug).lower()
    return _GENERIC_INTRO[axis].format(label_l=label_l)


# ---------------------------------------------------------------------------
# Summary + FAQ
# ---------------------------------------------------------------------------

def tag_summary_sentence(rows, slug):
    """Answer-first, machine-extractable sentence: how many of these are on the
    calendar right now, with a price span. Rebuilt every build."""
    trows = tag_rows(rows, slug)
    label_l = taxonomy.label_for(slug).lower()
    n = len(trows)
    if n == 0:
        return (f'No {label_l} sound baths are on the Front Range calendar right '
                f'now; new dates are added every week.')
    verb = 'is' if n == 1 else 'are'
    noun = 'session' if n == 1 else 'sessions'
    sent = (f'{n} {label_l} {noun} {verb} on the Front Range calendar right now')
    lo_label, hi = X._price_span(trows)
    if hi is not None:
        sent += f', priced {lo_label} to ${X._fmt_price_num(hi)}'
    return sent + '.'


# Curated per-tag FAQ overrides (the live tags get a tag-specific first Q). Every
# answer is factual, no woo — a clean FAQPage citation surface. HUMAN REVIEW.
_TAG_FAQ = {
    'gong-bath': (
        {
            'q': 'What is a gong bath?',
            'a': ('A gong bath is a sound bath centered on the gong. You lie down, '
                  'usually on a mat, while a facilitator plays one or more gongs; '
                  'the sustained tone is louder and more physical than a bowls-only '
                  'session. You stay clothed and still, and most run 45 to 75 '
                  'minutes.'),
        },
        {
            'q': 'Is a gong bath too loud or intense for a first-timer?',
            'a': ('Gongs can get loud at peaks, but facilitators build up and back '
                  'down rather than starting there. If you are sound-sensitive, sit '
                  'toward the edge of the room and tell the facilitator beforehand; '
                  'you can cover your ears or step out at any point.'),
        },
    ),
    'breathwork-sound': (
        {
            'q': 'What happens at a breathwork and sound session?',
            'a': ('You are guided through an active breathing pattern while gongs, '
                  'bowls, or drums play, then rest into the sound afterward. It is '
                  'more physically engaging than a lie-still sound bath — the '
                  'breathwork does real work before the tones settle you.'),
        },
        {
            'q': 'Is breathwork safe for everyone?',
            'a': ('Strong breathwork can bring on lightheadedness, tingling, or '
                  'strong emotion, and some patterns are not advised during '
                  'pregnancy or with certain heart, blood-pressure, or seizure '
                  'conditions. Check with the operator — and your doctor if unsure '
                  '— before booking. This is not medical advice.'),
        },
    ),
}


def tag_faq(rows, slug):
    """The FAQ items for a tag page — curated where written, else an evergreen
    generic set (what it is / cost / experience) that applies to any tag."""
    if slug in _TAG_FAQ:
        items = list(_TAG_FAQ[slug])
    else:
        label_l = taxonomy.label_for(slug).lower()
        items = [
            {
                'q': f'What is a {label_l} sound bath?',
                'a': ('A sound bath is a session where you lie down, usually on a '
                      'mat, while a facilitator plays instruments such as gongs, '
                      'singing bowls, and chimes. Most run 45 to 75 minutes, and '
                      'you stay clothed and still the whole time.'),
            },
            {
                'q': 'Do I need any experience?',
                'a': ('No. There is nothing to learn or perform — you lie down and '
                      'rest. Facilitators explain what will happen before they '
                      'start, so a first sound bath is as easy as any other.'),
            },
        ]
    # Price is always useful and always current.
    lo_label, hi = X._price_span(tag_rows(rows, slug))
    if hi is not None:
        span = (f'{lo_label} to ${X._fmt_price_num(hi)}' if lo_label != f'${X._fmt_price_num(hi)}'
                else lo_label)
        items.append({
            'q': 'How much do these sessions cost?',
            'a': (f'The sessions listed here run {span}. Some are offered by '
                  'donation or free. Each listing shows its own price, and the '
                  'ticket link goes straight to the operator.'),
        })
    return tuple(items)


# ---------------------------------------------------------------------------
# Page body
# ---------------------------------------------------------------------------

def _render_related(slug, built_map, nav_prefix):
    """A small 'related' nav: sibling tag pages (same axis first, then others),
    plus the /tags/ index. Only ever links to pages that exist."""
    axis = taxonomy.AXIS_BY_SLUG.get(slug)
    others = [s for s in built_map if s != slug]
    # Same-axis siblings first, then the rest — both in vocabulary order.
    ordered = ([s for s in others if taxonomy.AXIS_BY_SLUG.get(s) == axis]
               + [s for s in others if taxonomy.AXIS_BY_SLUG.get(s) != axis])
    out = ['<nav class="cal-related" aria-label="Related">',
           '  <span class="cal-related__label">Explore more</span>']
    for s in ordered[:8]:
        out.append(f'  <a href="{nav_prefix}{tag_page_path(s)}">'
                   f'{_esc(taxonomy.label_for(s))}</a>')
    out.append(f'  <a href="{nav_prefix}tags/">All tags</a>')
    out.append(f'  <a href="{nav_prefix}map/">Map</a>')
    out.append('</nav>')
    return '\n'.join(out)


def render_tag_page(rows, slug, nav_prefix, built_map, now=None, geocode=None):
    """The <main> body for one tag page: crumb · eyebrow · H1 · stamp · intro ·
    answer-first summary · filters · the filtered temporal bands · related · FAQ ·
    digest · submission line. Mirrors render_city_page."""
    now = X._now_utc(now)
    label = taxonomy.label_for(slug)
    trows = tag_rows(rows, slug)
    out = ['<section class="section section--light cal-main">', '  <div class="container">']

    out.append('    <nav class="cal-crumbs" aria-label="Breadcrumb">')
    out.append(f'      <a href="{nav_prefix}">Calendar</a> <span aria-hidden="true">/</span> '
               f'<a href="{nav_prefix}tags/">Tags</a> <span aria-hidden="true">/</span> '
               f'<span>{_esc(label)}</span>')
    out.append('    </nav>')

    out.append('    <span class="eyebrow">Front Range calendar</span>')
    out.append(f'    <h1 class="cal-h1">{_esc(label)}</h1>')
    out.append(f'    <p class="cal-updated">Last updated {_esc(X.fmt_stamp_date(now))}.</p>')

    # Audience-first intro (HUMAN REVIEW). Answers the intent before the list.
    out.append('    <!-- HUMAN REVIEW -->')
    out.append(f'    <p class="cal-intro">{_esc(tag_intro(slug))}</p>')

    out.append(f'    <p class="cal-summary" id="cal-summary">'
               f'{_esc(tag_summary_sentence(rows, slug))}</p>')

    # The tag is fixed; the bar still offers area + free/donation + any OTHER tags
    # these rows carry, so a visitor can narrow further.
    out.append('    ' + X.render_filters(trows, include_city=True))
    out.append('    ' + X._render_bands(trows, nav_prefix, now, geocode))
    out.append('    ' + X._render_noresults())
    out.append('    ' + _render_related(slug, built_map, nav_prefix))
    out.append('    ' + X._render_faq(tag_faq(rows, slug)))
    out.append('    ' + X.render_digest_block(selected_city='all', rows=rows, now=now))

    out.append('    <p class="cal-submit">Running a room we should know about? '
               '<a href="mailto:hello@soundbathcalendar.com?subject=A%20room%20for%20the%20calendar">Send it our way.</a></p>')

    out.append('  </div>')
    out.append('</section>')
    return '\n'.join(out)


# ---------------------------------------------------------------------------
# Schema (mirror the city-page builders)
# ---------------------------------------------------------------------------

def tag_collectionpage_schema(slug, page_url, site_url, description, date_modified):
    label = taxonomy.label_for(slug)
    return {
        '@context': 'https://schema.org',
        '@type': 'CollectionPage',
        'name': f'{label} sound baths on the Colorado Front Range',
        'url': page_url,
        'description': description,
        'dateModified': date_modified,
        'isPartOf': {'@type': 'WebSite', 'name': 'Sound Bath Calendar',
                     'url': site_url},
        'speakable': {'@type': 'SpeakableSpecification',
                      'cssSelector': ['#cal-summary']},
    }


def tag_itemlist(rows, slug, site_url):
    """ItemList of Events carrying this tag (chronological), or None when empty."""
    trows = tag_rows(rows, slug)
    if not trows:
        return None
    items = []
    for i, row in enumerate(trows, start=1):
        ev = (X._firstwater_event(row, site_url)
              if row['kind'] == 'firstwater' else X._external_event(row, site_url))
        items.append({'@type': 'ListItem', 'position': i, 'item': ev})
    return {
        '@context': 'https://schema.org',
        '@type': 'ItemList',
        'name': f'{taxonomy.label_for(slug)} sound baths on the Front Range',
        'itemListElement': items,
    }


def tag_faqpage_schema(rows, slug):
    """FAQPage schema from the same items the page renders."""
    return {
        '@context': 'https://schema.org',
        '@type': 'FAQPage',
        'mainEntity': [
            {'@type': 'Question', 'name': item['q'],
             'acceptedAnswer': {'@type': 'Answer', 'text': item['a']}}
            for item in tag_faq(rows, slug)
        ],
    }


# ---------------------------------------------------------------------------
# /tags/ index — the live tag pages grouped by axis. Noindex until it has a few
# (doorway discipline); the individual tag pages still rank on their own.
# ---------------------------------------------------------------------------

INDEX_STYLE = """<style>
    .tags__crumbs { font-size: 0.82rem; color: rgba(var(--ink-rgb),0.55); margin: 0 0 2rem; }
    .tags__crumbs a { color: var(--accent-on-light); text-decoration: none; }
    .tags__h1 { font-size: clamp(2rem, 4vw, 3rem); margin: 0.2rem 0 0.8rem; }
    .tags__lede { font-size: 1.1rem; color: rgba(var(--ink-rgb),0.75); max-width: 42rem; margin: 0 0 2.4rem; }
    .tags__axis { margin: 0 0 2rem; }
    .tags__axis-h2 { font: 600 0.78rem var(--font-body); letter-spacing: 0.14em; text-transform: uppercase; color: rgba(var(--ink-rgb),0.6); margin: 0 0 0.9rem; }
    .tags__grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr)); gap: 0.9rem; }
    .tags__card { display: flex; align-items: baseline; justify-content: space-between; gap: 0.6rem; text-decoration: none; color: inherit; border: 1px solid rgba(var(--ink-rgb),0.14); padding: 0.8rem 0.95rem; }
    .tags__card:hover { border-color: var(--accent-on-light); }
    .tags__name { font: 500 1.02rem var(--font-display); color: var(--ink); }
    .tags__count { font-size: 0.82rem; color: rgba(var(--ink-rgb),0.6); white-space: nowrap; }
    .tags__empty { color: rgba(var(--ink-rgb),0.7); }
  </style>"""


def render_index(built_tags, nav_prefix):
    """The <main> for /tags/ — the live tag pages grouped by axis, in vocabulary
    order. `built_tags` is qualifying_tags(rows) output."""
    by_slug = {t['slug']: t for t in built_tags}
    out = ['<section class="section section--light tags">', '  <div class="container">']
    out.append('    <nav class="tags__crumbs" aria-label="Breadcrumb">')
    out.append(f'      <a href="{nav_prefix}">Calendar</a> <span aria-hidden="true">/</span> '
               '<span>Tags</span>')
    out.append('    </nav>')
    out.append('    <span class="eyebrow">Front Range calendar</span>')
    out.append('    <h1 class="tags__h1">Browse by tag</h1>')
    out.append('    <p class="tags__lede">Sound baths grouped by what makes the '
               'sound, why people come, the setting, and who they are for — every '
               'tag here has upcoming sessions on the calendar.</p>')

    if not built_tags:
        out.append('    <p class="tags__empty">Tag pages open up as the calendar '
                   'fills in. Check back soon.</p>')
    else:
        for axis_key, axis_label in taxonomy.TAG_AXES:
            axis_tags = [by_slug[s] for s, _l, a in taxonomy.TAGS
                         if a == axis_key and s in by_slug]
            if not axis_tags:
                continue
            out.append('    <div class="tags__axis">')
            out.append(f'      <h2 class="tags__axis-h2">{_esc(axis_label)}</h2>')
            out.append('      <div class="tags__grid">')
            for t in axis_tags:
                href = f'{nav_prefix}{tag_page_path(t["slug"])}'
                n = t['count']
                cnt = f'{n} upcoming'
                out.append(
                    f'        <a class="tags__card" href="{_esc(href)}">'
                    f'<span class="tags__name">{_esc(t["label"])}</span>'
                    f'<span class="tags__count">{_esc(cnt)}</span></a>')
            out.append('      </div>')
            out.append('    </div>')

    out.append('  </div>')
    out.append('</section>')
    return '\n'.join(out)


def index_itemlist(built_tags, site_url):
    """ItemList of the live tag pages for the /tags/ index (or None when empty)."""
    if not built_tags:
        return None
    items = []
    for i, t in enumerate(built_tags, start=1):
        items.append({'@type': 'ListItem', 'position': i,
                      'name': t['label'],
                      'url': tag_page_url(t['slug'], site_url)})
    return {
        '@context': 'https://schema.org',
        '@type': 'ItemList',
        'name': 'Sound baths by tag on the Front Range',
        'itemListElement': items,
    }
