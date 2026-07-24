"""Sound Bath Calendar — RSS 2.0 feeds (CAL-05).

feed.xml at the site root (every upcoming event) plus one per region
(denver/feed.xml, boulder/feed.xml, …), built from the SAME cal_rows the pages
render so the feed never drifts from the calendar. Mirrors the .ics feeds
(build_ics_feeds): all rows are included.

Stdlib only — hand-rolled XML with xml.sax.saxutils.escape for every value, and
email.utils for the RFC-822 dates RSS requires. build.py owns file writing; this
returns the feed text.
"""

import email.utils
from xml.sax.saxutils import escape

from _src.lib import external_events as X


def _item_link(row, site_url):
    """The item's canonical URL: the event's permalink page."""
    return X.event_permalink_url(row, site_url)


def _item_guid(row, link):
    """A globally-unique guid that still resolves (isPermaLink stays true).

    A permalink already encodes name+date+venue, so it is unique per
    occurrence."""
    return link


def _item_description(row, link):
    """A factual, plain-text description: the same factual line the permalink
    shows, then venue/area, price, and a link back. Escaped by the caller."""
    parts = [X.factual_description(row)]
    where = ', '.join(x for x in (row.get('venue'), row.get('city')) if x)
    if where:
        parts.append(f'Where: {where}.')
    if row.get('price'):
        parts.append(f'Price: {row["price"]}.')
    parts.append(f'Details: {link}')
    return ' '.join(parts)


def _rss_item(row, site_url):
    link = _item_link(row, site_url)
    guid = _item_guid(row, link)
    pub = email.utils.format_datetime(X.parse_iso(row['starts_at']))
    return (
        '    <item>\n'
        f'      <title>{escape(row["name"] or "Sound bath")}</title>\n'
        f'      <link>{escape(link)}</link>\n'
        f'      <guid isPermaLink="true">{escape(guid)}</guid>\n'
        f'      <pubDate>{pub}</pubDate>\n'
        f'      <description>{escape(_item_description(row, link))}</description>\n'
        '    </item>'
    )


def build_rss(rows, site_url, feed_url, channel_title, channel_link,
              channel_desc, now=None):
    """An RSS 2.0 document for the given rows (chronological). `feed_url` is the
    feed's own address (the atom:link self-reference); `channel_link` is the
    human page the feed describes (the root or a city page)."""
    now = now or X.current_now()
    ordered = sorted(rows, key=lambda r: X.parse_iso(r['starts_at']))
    items = '\n'.join(_rss_item(r, site_url) for r in ordered)
    body = f'{items}\n' if items else ''
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        '  <channel>\n'
        f'    <title>{escape(channel_title)}</title>\n'
        f'    <link>{escape(channel_link)}</link>\n'
        f'    <description>{escape(channel_desc)}</description>\n'
        '    <language>en-us</language>\n'
        f'    <lastBuildDate>{email.utils.format_datetime(now)}</lastBuildDate>\n'
        f'    <atom:link href="{escape(feed_url)}" rel="self" '
        'type="application/rss+xml"/>\n'
        f'{body}'
        '  </channel>\n'
        '</rss>\n'
    )
