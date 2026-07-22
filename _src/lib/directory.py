"""Sound Bath Calendar — shared entity-directory components.

The three directory indexes (/practitioners/, /venues/, /operators/) share one
card design: a media tile (the entity's own photo, else its next session's
listing image, else a designed monogram placeholder), then name + meta. The
styles live in styles.css (`.dir-*`) since three pages ride them; this module
holds the render helpers so the card markup can never drift apart between the
three renderers.
"""

from _src.lib import external_events as X

_esc = X._esc


def art_for(entity, session_rows):
    """The card image URL for one entity: its curated photo first, else the
    first upcoming session that carries a listing image (same scrubbed
    image_url the calendar rows and digest already show), else ''."""
    photo = X._safe_ext_url((entity or {}).get('photo_url') or '')
    if photo:
        return photo
    for r in session_rows or []:
        if r.get('image_url'):
            return r['image_url']
    return ''


def render_head(nav_prefix, crumb_label, h1, lede):
    """Crumb (left, chrome) + centered identity block (CAL-23 phase A pattern:
    the grid below keeps the full container width)."""
    return (
        f'    <nav class="dir-crumbs" aria-label="Breadcrumb">\n'
        f'      <a href="{nav_prefix}">Calendar</a> <span aria-hidden="true">/</span> '
        f'<span>{_esc(crumb_label)}</span>\n'
        f'    </nav>\n'
        f'    <div class="dir-head">\n'
        f'      <span class="eyebrow">Front Range calendar</span>\n'
        f'      <h1 class="dir-h1">{_esc(h1)}</h1>\n'
        f'      <p class="dir-lede">{_esc(lede)}</p>\n'
        f'    </div>')


def render_card(href, name, meta, img_url):
    """One directory card. A missing image draws the monogram placeholder —
    the media tile is RESERVED (CAL-12 doctrine: every text column shares one
    left edge, and the grid stays uniform). The tile ALWAYS carries
    data-monogram: when a present image later fails to load (expired CDN URL,
    hotlink block), the base-layout fallback marks the tile .img-broken and
    CSS draws the same monogram — designed absence either way. The tile is
    aria-hidden throughout; the name below carries the meaning."""
    initial = (name or '?').strip()[:1].upper()
    if img_url:
        media = (f'<span class="dir-card__media" data-monogram="{_esc(initial)}" '
                 f'aria-hidden="true"><img src="{_esc(img_url)}" alt="" '
                 f'loading="lazy" decoding="async" referrerpolicy="no-referrer"></span>')
    else:
        media = (f'<span class="dir-card__media dir-card__media--ph" '
                 f'data-monogram="{_esc(initial)}" aria-hidden="true"></span>')
    return (f'      <a class="dir-card" href="{_esc(href)}">{media}'
            f'<span class="dir-card__name">{_esc(name)}</span>'
            f'<span class="dir-card__meta">{_esc(meta)}</span></a>')
