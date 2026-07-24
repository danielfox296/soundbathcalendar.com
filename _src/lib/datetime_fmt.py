"""America/Denver date and time formatting for build.py.

Every rendered date on the calendar goes through here, so a row, a permalink
page, an .ics entry and an RSS item can never disagree about what day a session
falls on. Denver is hard-coded on purpose: the calendar covers one metro area
and a session's local date IS its date.

Stdlib only. `_day` exists because %-d is not portable to Windows.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

DENVER = ZoneInfo('America/Denver')


def parse_iso(ts):
    """Parse an ISO-8601 timestamp (offset or trailing Z) to aware datetime."""
    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError(f'timestamp missing offset: {ts!r}')
    return dt


def _denver(ts):
    return parse_iso(ts).astimezone(DENVER)


def _day(n):
    return str(int(n))  # strip leading zero portably (no %-d on Windows)


def fmt_date_long(ts):
    d = _denver(ts)
    return f'{d.strftime("%A")}, {d.strftime("%B")} {_day(d.strftime("%d"))}, {d.year}'


def fmt_date_short(ts):
    d = _denver(ts)
    return f'{d.strftime("%B")} {_day(d.strftime("%d"))}'


def fmt_time(ts):
    d = _denver(ts)
    hour = _day(d.strftime("%I"))
    return f'{hour}:{d.strftime("%M")} {d.strftime("%p")}'
