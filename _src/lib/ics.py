"""ICS (RFC 5545) generation — stdlib only, no I/O.

Python mirror of service/src/lib/ics.ts (the Firstwater ticket-confirmation +
/events.ics emitter), same discipline: UTC timestamps, CRLF line endings, TEXT
escaping (backslash, semicolon, comma, newline), 75-octet line folding. The
calendar's static build writes per-city, whole-calendar, and per-event .ics
files from the same feed rows the pages render, so a webcal subscriber never
needs to open the site again.

Deliberately hand-rolled: the payload is a handful of properties per VEVENT,
not worth a dependency, and the build is stdlib-only by constraint.
"""

from datetime import timezone

PRODID = '-//Sound Bath Calendar//soundbathcalendar//EN'


def ics_utc(dt):
    """Aware datetime -> '20260801T190000Z' (UTC), matching toIcsUtc in ics.ts."""
    return dt.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def escape_text(value):
    """Escape a TEXT value per RFC 5545 §3.3.11 (backslash first)."""
    return (str(value)
            .replace('\\', '\\\\')
            .replace(';', '\\;')
            .replace(',', '\\,')
            .replace('\r\n', '\\n')
            .replace('\n', '\\n'))


def fold_line(line):
    """Fold a line longer than 75 octets with CRLF + space (RFC 5545 §3.1).
    Octet-aware (UTF-8), never splitting a multi-byte char — mirrors foldLine
    in ics.ts (first segment 75, continuations 74 to leave room for the space)."""
    if len(line.encode('utf-8')) <= 75:
        return line
    out, current = [], ''
    for ch in line:
        nxt = current + ch
        limit = 75 if not out else 74
        if len(nxt.encode('utf-8')) > limit:
            out.append(current)
            current = ch
        else:
            current = nxt
    if current:
        out.append(current)
    return '\r\n '.join(out)


def event_lines(ev, now):
    """VEVENT lines for one event dict (uid/title/start/end + optional
    location/description/url). start/end/now are aware datetimes."""
    lines = [
        'BEGIN:VEVENT',
        f'UID:{escape_text(ev["uid"])}',
        f'DTSTAMP:{ics_utc(now)}',
        f'DTSTART:{ics_utc(ev["start"])}',
        f'DTEND:{ics_utc(ev["end"])}',
        f'SUMMARY:{escape_text(ev["title"])}',
    ]
    if ev.get('location'):
        lines.append(f'LOCATION:{escape_text(ev["location"])}')
    if ev.get('description'):
        lines.append(f'DESCRIPTION:{escape_text(ev["description"])}')
    if ev.get('url'):
        lines.append(f'URL:{escape_text(ev["url"])}')
    lines.append('END:VEVENT')
    return lines


def generate_calendar(events, now, cal_name=None):
    """A VCALENDAR containing zero or more VEVENTs (an empty calendar is valid).
    X-WR-CALNAME sets the subscribed calendar's display name in Apple/Google."""
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', f'PRODID:{PRODID}',
             'CALSCALE:GREGORIAN', 'METHOD:PUBLISH']
    if cal_name:
        lines.append(f'X-WR-CALNAME:{escape_text(cal_name)}')
    for ev in events:
        lines.extend(event_lines(ev, now))
    lines.append('END:VCALENDAR')
    return '\r\n'.join(fold_line(ln) for ln in lines) + '\r\n'
