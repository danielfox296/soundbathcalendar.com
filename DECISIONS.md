# Decisions — Sound Bath Calendar

*Moved here 2026-07-31 from Firstwater's `decisions.md`, where they were the
only two entries not about Firstwater. Append new ones; compact when
superseded entries outnumber live ones.*

---

**2026-07-19 · The aggregator is its own brand: Sound Bath Calendar,
soundbathcalendar.com** (purchased, GoDaddy). Firstwater is the artist and its
domain promotes the practice; the calendar is infrastructure and needs a
clear, directly named brand. Supersedes the same-day "curator is Firstwater"
framing in `marketing/calendar-play-2026-07.md` and the on-page-naming
recommendation in `site-pivot-strategy-2026-07-19.md`.

**2026-07-19 · Expansion doctrine: national name, regional war.** The name and
architecture scale nationally; operations stay Front Range until the 10-week
gate says otherwise. **The moat is the trust layer — accuracy, notes, operator
relationships — not the scrape.** If meditation events earn their own surface,
launch a sibling descriptor on the same rails rather than stretching the
flagship.

*The 10-week gate has no recorded start date and no criteria. An undated gate
with undefined criteria means Front Range by default rather than by decision.*

**2026-08-03 · Copy rulings executed (Daniel, via BASE-VOICE): the honest-tic
sweep and the body em-dash sweep.** Ruling 2: full sweep of the
"honest/actually/honestly/without hype" family from all public copy, titles and
metas included; closes CAL-COPY-7 (audit 2026-07-22). Public "non-woo" was
already "no belief required" (commit `d57d296`). Ruling 6: em dashes removed
from body prose under `_src/`; the SEO/title-string allowance stands
(`marketing/calendar-copy-review-2026-07.md` §2), and functional locator
strings (card captions, ALT text, ticket aria-labels, map-popup session lines,
the digest-preview summary that mirrors the shipped email) keep their spec'd
separators. The estate base voice lives at `~/Desktop/site-ops/BASE-VOICE.md`;
DESIGN.md §0 carries the pointer line.

---

## Standing constraint

This site's build consumes Firstwater's production feed at
`GET https://events.thefirstwater.co/feeds/sessions.json`, at build time.
If that feed's shape changes, or the `events.thefirstwater.co` custom domain
moves, this build breaks silently. One-way dependency, arms-length.

The same warning lives in Firstwater's `BRAIN.md`. It needs to exist on both
sides.

## Open

Whether Firstwater's own events appear here, and with what attribution. The
build consumes the feed, so something flows — but nothing records whether that
is a listing like any other operator's or something more favorable. Given the
stated moat is the trust layer, Front Range facilitators would notice the
difference before anyone else.
