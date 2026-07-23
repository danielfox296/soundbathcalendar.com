# Sound Bath Calendar — DESIGN.md

*Ratified 2026-07-22. The calendar's own design constitution — post-split, this brand is not Firstwater. Every "per DESIGN.md" in `styles.css` now means this file; the Firstwater chassis doc (`site/DESIGN.md`) is a different brand and is never imported, cited, or matched for voice.*

**Ground truth.** The law lives here; the implementation lives in `styles.css`, the page-local style blocks in `_src/lib/*.py` (`EVENT_PAGE_STYLE`, `VENUE_PAGE_STYLE`, `PRACTITIONER_PAGE_STYLE`, `OPERATOR_PAGE_STYLE`, `BROWSE_STYLE`, `ROUNDUPS_HEAD`, `MAP_HEAD`, `INSIGHTS_HEAD`, `CITY_WARM_STYLE`), and `_src/partials/`. If doc and tree disagree, that is a defect: fix one to match the other and record the call here. `RULE:` lines are load-bearing.

---

## 0 · Doctrine (in force)

- Weight extremes over timid contrast. Asymmetry over three-identical-cards.
- Radius 0 — sharp editorial edges (§1.5 for the two sanctioned exceptions).
- Motion only where it earns its place. No glassmorphism. No purple-indigo gradient. No emoji bullets.
- The calendar is the site: one sheet (`styles.css`), one light ground, utility register.
- **NO JS in the baseline.** Every rule holds with scripts blocked. JS is progressive enhancement only: `filters.js` reveals the filter bar, the map initializes or stays an empty box, `<details>` disclosures are native. No-JS visitors see every row, always.
- Answer-first. The root opens with the machine-extractable summary (`.cal-summary`), not a hero. No tall marketing hero, no image, no animation on the listing root.
- Honest surfaces: every count is computed from the feed at build time, never typed in (§3.4).
- Utility voice, no belief required (public copy never says "non-woo" — commit `d57d296`). Copy law beyond vocabulary (§7) lives in the copy audits, not here.

---

## 1 · Tokens

### 1.1 Color

Defined at `:root` in `styles.css:5`. Dark mode flips the same names (§6).

| Token | Light | Dark | Role |
|---|---|---|---|
| `--ink` | `#0A0B0D` | `#F5F7FA` | solid text |
| `--paper` | `#F5F7FA` | `#101216` | the ground (the sheet) |
| `--ink-rgb` | `10, 11, 13` | `245, 247, 250` | powers every `rgba(var(--ink-rgb), a)` |
| `--accent` | `#62B6E8` | unchanged | ice — a MARK color (waveform, rules, small toggles) |
| `--accent-on-light` | `#1F6FA8` (5.02:1 on paper) | `#7CC3EC` (AA on `#101216`) | link/text blue |
| `--line` | `rgba(var(--ink-rgb), 0.14)` | follows the flip | hairlines |
| `--gray` | `#98A1AB` | unchanged | **borders/accents only — retired as a text color** (CAL-DES-1) |
| body bg | `--paper` | `#08090B` | dark adds the desk behind the sheet |

RULE: every secondary text color, border, and tint is written as `rgba(var(--ink-rgb), a)` — never a hardcoded gray, never `--gray`. This single convention is what makes dark mode a one-token flip (§6). A hex gray in a component is a defect.

RULE: `--accent` (ice) is never a text color and never a text-bearing button fill (ice under ink text is ~1.9:1 — the v1 washed-CTA defect, CAL-11). Text-blue is always `--accent-on-light`.

### 1.2 The muted-ink floor (CAL-DES-1, ratified 2026-07-22)

The opacity ramp on `rgba(var(--ink-rgb), a)` text (`styles.css:245`):

```
0.62   floor — muted text (crumbs, meta, times, stamps, empty lines)  ≈ 5.6:1
0.65   the uppercase label family (eyebrow, facts <dt>, axis/col labels)  ≈ 6.1:1
0.70–0.82   reading-prose intermediates (FAQ answers, ledes, entity prose)
1.0    solid ink
```

RULE: functional text never sits below `rgba(var(--ink-rgb), 0.62)`. Uppercase labels sit at `0.65`. Dark mode inherits the same floor by construction.

Exempt (not functional text): disabled controls (`.cal-filters__nearme:disabled`, 0.45); the digest-preview miniature (`.digest-preview__brand`/`__dow` at 0.5 — a scaled depiction of the email, not page UI); decorative glyphs and monograms (`.cal-row__media--empty::after` 0.16, `.cal-emptystate__glyph` 0.18, `.dir-card__media--ph::before` 0.32).

Drift converged 2026-07-22: `.cal-row__ours` (was 0.5, under AA at its size) and `.browse__axis-h2` (was 0.60) joined the uppercase-label family at 0.65; the rest of the 0.60 family (`.cal-row__time`, `.cal-row__with`, `.cal-emptystate__seed`, `.footer-tag`, `.browse__count`) sits at the 0.62 floor. No functional text below the floor remains.

### 1.3 Type

- `--font-display: 'Space Grotesk'` · `--font-body: 'Inter'`.
- Body: Inter 400, `1.02rem / 1.65`. Headings base (`h1,h2,h3`): display 700, `line-height 1.08`, `letter-spacing -0.015em`.
- Scale anchors (checkable):

| Surface | Spec |
|---|---|
| Listing H1 `.cal-h1` | `clamp(1.7rem, 3.6vw, 2.7rem)` · 500 |
| Detail H1 (`.cal-event__h1`, `.venue__h1`, `.pract__h1`, `.operator__h1`) | `clamp(2rem, 4vw, 3rem)` · 700 (base) |
| Directory H1 `.dir-h1` | same clamp · 500 |
| Band H2 `.cal-band__h2` | `clamp(1.4rem, 2.6vw, 1.95rem)` · 700 |
| Summary `.cal-summary` | display 500 · 1.12rem / 1.45 |
| Row name `.cal-row__name` | 500 · 1.12rem / 1.25 |
| Row meta `.cal-row__meta` | 400 · 0.92rem · ink 0.62 |
| Eyebrow `.eyebrow` | Inter 600 · 0.75rem · 0.16em tracking · uppercase · ink 0.65 |
| Wordmark `.wordmark` | display 700 · 0.95rem · 0.14em · uppercase |

The pattern: identity/answer surfaces run display **500** (utility register); entity and event names carry the base **700**. Rows are a scan surface — their leading (1.25–1.45) is deliberately tighter than page prose (1.65); don't "fix" it up.

Reading measure (D-13, ratified 2026-07-22): one physical family, two roles. `--measure: 44rem` (`styles.css:143`; was `68ch` — the same width at shipped font sizes) caps long-form prose in shells (`.detail-main > p`, entity bio/desc paragraphs, `/privacy/`); fixed rem caps (38–48rem, centered on 42–44rem) govern listing and answer surfaces whose font sizes intentionally differ (`.cal-summary` 44, `.cal-row__meta` 42, `.cal-intro` 42, `.cal-faq__item` 44, `.cal-emptystate` 40, `.rup-narrow` 48…). RULE: new prose columns pick from this family — `var(--measure)` for long-form, an existing rem cap otherwise; no new bespoke widths.

### 1.4 Spacing & chrome offsets

No abstract spacing scale — rem values tuned per surface. The load-bearing ones:

- Container padding `clamp(24px, 4vw, 64px)`; masthead keeps tight `24px` (`.masthead-inner`).
- Section `2.2rem 0 4rem`. Band stride `3.4rem`. Row padding `0.85rem 0` (CAL-12 — was 1.15rem; density is a feature).
- Sticky offsets: masthead is the sticky chrome; rail sticks at `top: 80px`, detail aside at `90px`; every jump target carries `scroll-margin-top: 90px` (`.cal-band`, `.cal-faq`, `.digest-block`). New sticky/jump surfaces must respect these clearances.

### 1.5 Radius (the identity)

RULE: `border-radius: 0` on all chrome — buttons, chips, cards, inputs, the mobile row-card (CAL-12 killed the 6px). Two sanctioned exceptions:

1. **2px on photographic tiles only** — `.cal-row__media`, `.dir-card__media`, `.digest-preview__thumb`. A hairline round reads better on photos; it never applies to non-photo boxes.
2. **Map pins are circles** (`.sbc-pin`, 50%) — a designed marker shape, not a rounded rectangle.

The state-of-sound report's 14px/999px family is the sanctioned editorial register — **ratified, D-14, §9.**

---

## 2 · Layout

### 2.1 Containers & the listing rail (CAL-23 A / A2 / B)

- `.container`: max 1140px — the default shell (detail pages, learn pages).
- Listing pages (`.cal-main`, i.e. root + city + tag): container caps at **1024px** — "stingy margins, aggressively left justified" — so row text (~42rem) nearly fills its track (phase A2).
- At **≥1080px** (`styles.css:61`) listing pages widen to **1320px** and split: `.cal-split` = sticky rail `clamp(232px, 19vw, 272px)` + `minmax(0, 1fr)` list, gap `clamp(2.4rem, 3vw, 3.4rem)`. `.cal-rail__inner` sticks at `top: 80px`.
- The rail is a build-time **relocation** of the same markup `filters.js` binds (filters · jump chips · standing links) — selector-based and position-agnostic. Below 1080px the wrappers are inert and the page is the phase-A stack.
- Phase A: the identity block on listing pages is centered (`.cal-hero`); the list below keeps the full track.

### 2.2 The detail shell (CAL-10)

One primitive for every detail page (event, venue, practitioner, organizer):

- `.detail-shell`: one column; at **≥900px** → `minmax(0, 1fr) var(--aside)` (`--aside: 340px`), gap 3rem, `.detail-aside` sticky at `top: 90px`.
- Reading column: prose capped at `--measure`. Aside: `.detail-card` decision cards (1px `--line` border, radius 0) — facts `<dl>`, mini-map (`.detail-card__map`, 4:3), tickets, add-to-calendar.
- RULE: reading text never widens to fill the shell; structure may span it.
- Entity pages cross-link the trio (venue ↔ practitioner ↔ organizer) and end with "Upcoming sessions" rendered by the **same row component** as the calendar (§2.3) — every entity page is a live mini-calendar.

### 2.3 Bands & rows (the core surface)

**Bands** — the site's signature IA. `Today`/`Tonight` (Tonight when every remaining session starts in the evening — `today_band_label`, `external_events.py`) · `This weekend` · `This week` · `The weeks ahead`. A band renders only when it has sessions. Jump chips double as filters (CAL-16): pressed state is ink-fill-on-paper with negative margins canceling the padding so toggling never shifts layout (`styles.css:215`); with JS off they are plain anchors and every row is visible.

**Row anatomy** (`.cal-row`: grid `78px 1fr`, gap 1.5rem):

1. **Tear-off date rail** (`.cal-row__when`): weekday (`__dow`, uppercase, 0.62) over numeral (`__dnum`, display 500, 1.5rem) over time (`__time`). The Today band omits the date — a time-only rail is correct there.
2. **Month marker** (`.cal-row__mo`, CAL-UX-2): any row whose Denver-time month differs from the build month stamps the muted month abbreviation (`Aug`) in the rail. Per-row on purpose — client-side filters can hide the rollover, so the marker must survive filtering. Entity-page session lists get it too.
3. **Media tile** (`.cal-row__media`): fixed 104px, 3:2, radius 2px, `object-fit: cover` — flyers of any source aspect are framed, never raw. Image-less rows render the reserved placeholder (`--empty`: the ∿ sine glyph at 0.16) so every text column shares one left edge (CAL-12, mirroring the digest's `showThumb`). On mobile: 84px.
4. **Text column**: marks line (`__marks`: city chip + modality kicker, §3.2) → name → meta (one line where it fits, capped 42rem) → optional practitioner cross-link (`__with`) → optional editorial note (`__note`: Daniel's one line, display 500, 2px accent left rule, capped 38rem) → ghost-link CTA row (`__cta`).
5. **Firstwater rows** (`.cal-row--firstwater`): 3px accent left border + `rgba(98,182,232,0.06)` tint — one operator among many, still visibly its own.

Mobile ≤640px: rows become bordered cards (radius 0), the date rail runs inline, `.cal-rows` drops its top rule. First-viewport budget: stamp + summary + first rows above the fold.

### 2.4 List + map (`/map/`, CAL-10 phase C)

`.map-split`: ≥900px → list `minmax(340px, 5fr)` beside sticky map `7fr`; the list column hides media tiles (the map is the visual). Below 900px the map band stacks on top. Map height is fixed px (680 / 440 mobile) so Leaflet initializes against real dimensions. Pins carry the decision datum — a venue's session count — as ink circles with paper borders (`.sbc-pin`; `--hot` variant in accent); clusters sum their contents; popups ride the tokens so they flip in dark. With JS blocked the list is fully usable and the map box simply never initializes.

### 2.5 Entity directories (`/venues/`, `/practitioners/`, `/operators/`)

One shared card design (`_src/lib/directory.py`): `.dir-grid` auto-fill `minmax(13.5rem, 1fr)`; `.dir-card` is borderless — the 3:2 media tile carries the mass (entity photo, else next session's listing image, else the monogram placeholder). Placeholder = the entity's initial via `data-monogram` over the tint with a 2px accent baseline — designed absence, not a broken image; `.img-broken` collapses to the same state.

### 2.6 Masthead & footer

Masthead (`_src/partials/header.html`): sticky, compact — wordmark · scrolling city anchors · slim digest capture (inline form ≥900px, anchor link below). Footer: brand column + three link columns over a fine-print bar (`Sound Bath Calendar` · `Denver, Colorado · Privacy` — the `/privacy/` link rides every page); footer links ride the muted-ink ramp, **not** accent — reference furniture, not a call to action.

### 2.7 Digest block (CAL-18)

Signup pitch + form beside a build-time mini-render of this week's **actual** Thursday email, in the email's own `--dp-*` palette (from `digest.ts`, both schemes). The preview column is deliberately narrow (19rem) — a glimpse, not a second calendar. The tear-off fade and "+N more" line render **only when the week actually holds more sessions than shown** — a fully shown week gets no false "more."

---

## 3 · Components

### 3.1 Buttons (CAL-11)

- `.btn-primary`: `--ink` fill, `--paper` text (~17:1). Hover: `inset 0 -2px 0 var(--accent)` — an ice underline, never a fill swap. Auto-inverts to a light button in dark mode.
- `.btn-secondary`: transparent, ink text, `--line` border; hover border `--accent-on-light`.
- `.btn-slim`: the compact variant (masthead). Ghost tier = plain `--accent-on-light` link CTAs (`.cal-row__cta`, `.cal-event__link`).
- RULE: **exactly one `.btn-primary` per view intent.** Everything else is secondary or ghost. Known open violation: the masthead digest button on event pages — §9.
- RULE: every button's text ≥ 4.5:1 on its own fill. An ice fill is allowed only on small non-critical toggles where softness reads as *selected*, not *disabled* — e.g. `.cal-filters__nearme[aria-pressed="true"]`.
- Specificity note: anchor buttons inside `.section--light` need the label pin (`.section--light a.btn-primary { color: var(--paper) }`, `styles.css:112`) — keep it when adding button contexts.

### 3.2 Chips & marks

- `.cal-tag` (CAL-01): 600 · 0.68rem · `--accent-on-light` text · `rgba(ink, 0.18)` border · radius 0. Variants: `--toggle` (checkbox, `accent-color: var(--accent-on-light)`); `--link` (CAL-09 — links to its tag page, hover border + `rgba(31,111,168,0.06)` tint). Link-or-span rule: a chip links only when its landing page exists.
- Marks line: `.cal-row__city` (every row) + `.cal-row__modality` (the "what kind" kicker, middot-separated, links per CAL-09) — both uppercase 0.68rem `--accent-on-light`.
- `.cal-row__dist` (CAL-05): ink text, bordered — appears only when near-me sort is active.

### 3.3 Cards

`.detail-card` (aside decision card) and `.dir-card` (§2.5) are the only card primitives. Both radius 0; borders are 1px `--line` or nothing (media carries the mass). No shadows on chrome — the only shadows shipped are the digest-preview sheet (depicting an email on a desk) and map pins.

### 3.4 Empty states & honest lines (CAL-13)

`.cal-emptystate`: quiet glyph → one honest line of what the section will hold → two redirects ("Browse this week's calendar" · "See the map") → the get-listed seed line.

- RULE: never a bare "…on the way." floating above the footer.
- RULE: **never fabricate.** Every count, price span, and "next up" is computed from the feed at build time. Entity fallback paragraphs state only what the data holds (`venues.py` / `operators.py` fallbacks). No fake scarcity, no invented urgency badges, no "+N more" unless N is real (§2.7). If we don't know it, the surface doesn't say it.

---

## 4 · Imagery

**The warmth register:** warm, human, held — hands on bowls, candlelit rooms, soft fabric, wood, plants, human presence. Never institutional, empty, or eerie. No AI-generated stock (`img/og/SOURCES.md` — AI-studio results were deliberately skipped).

**Placement:** warmth lives on city pages (`.cal-warmband`, 16:5 band under the H1), the what-to-expect hero, and share cards. The listing root stays utilitarian — answer-first, no hero (§0).

**Pipeline (CAL-22):** `scripts/warm.py` emits committed `img/warm/<surface>-1600/800.jpg` (q80, progressive) from the same stock as the surface's OG card, so a shared link and the page it opens feel like one thing. Photos ship natural — no scrim, no type baked in; dark mode dims via CSS (`filter: brightness(0.82)`), never in the file. Local-only; CI never runs it.

RULE — **the honesty line:** stock is atmosphere, never evidence. Alt text and captions state what the photo literally shows ("Two practitioners playing singing bowls in a sunlit studio") and never present stock as a specific Front Range venue, session, or person.

RULE — **entity photos are real-only.** A venue photo, practitioner portrait, or organizer image is a real photo of that entity (`photo_url`) or the designed monogram placeholder — stock never stands in for a real place or person.

**Flyers:** always framed — letterboxed into the fixed 3:2 tile in lists (§2.3), max-640px 3:2 figure on event pages. Source art never renders raw in-list.

**Systemic fallback:** the base-layout script removes any `<img>` that fails to load and marks its parent `.img-broken`. Tile contexts restate their designed empty state; standalone figures disappear entirely — a caption with no picture, or an empty frame, must never remain (`styles.css:387`).

---

## 5 · OG cards (CAL-17)

**Spec:** 1200×630 **JPEG**, quality 82, progressive — photographic cards land ~200KB. Hard cap **< 600KB**: WhatsApp drops link previews above that, which is why these are JPEG, not PNG (`scripts/og.py:113`).

**Anatomy:** a warm stock photo pulled toward ink (30% ink blend + bottom scrim from 30% height + left scrim to 78% width), the ice waveform + letterspaced eyebrow, title in Space Grotesk — all set in the dark tokens (`#F5F7FA` text, `#A7AFB9` muted, ice accent, which hold AA on the ink ground). Card copy reuses the page's own H1/meta language — no new claims.

**Provenance law:** every photo is logged in `img/og/SOURCES.md` — source URL, photographer, license, where used. A card whose photo isn't in SOURCES.md doesn't ship.

**No-rot law (CAL-DES-2):** `og:image` is always a **committed** card — event permalinks use their city card, else `og-default.jpg` — never the organizer's signed CDN image, which expires and leaves share previews dead. Rot-prone listing images may still render on-page and in JSON-LD, where failure degrades gracefully (§4 fallback).

**Pipeline:** local-only, like `geocode.py` — needs Pillow + the vendored assets in `scripts/assets/` (stock JPGs + `SpaceGrotesk-VF.ttf`). Outputs are committed under `img/og/`; **CI never regenerates them.**

**Procedure — new page needs a card:**
1. New tag page → add a `CARDS` entry in `scripts/og.py` (new photo? add it to `scripts/assets/stock/` + a SOURCES.md row).
2. Run `python3 scripts/og.py` from the repo root (watch for the title-overflow warning).
3. Commit the JPEG + any SOURCES.md change.
4. New city → keep `CITY_SLUGS` in sync with `external_events.CITY_ANCHOR`.

---

## 6 · Dark mode (CAL-14)

One `prefers-color-scheme: dark` token flip over the **same layout** — no bespoke dark components (`styles.css:467`). Palette proven in the digest email (`digest.ts`).

Mechanism: flipping `--ink-rgb` inverts every `rgba(var(--ink-rgb), a)` secondary/border/tint at once; `--line` follows; `--paper` becomes the `#101216` sheet on the `#08090B` desk; links move to `#7CC3EC` (AA on ink; `#1F6FA8` does not clear it — never use the light link blue on the dark ground); `--accent` stays a mark on both grounds; `.btn-primary` auto-inverts.

RULE: new components get dark mode for free **only** if they follow §1.1's `--ink-rgb` rule. A component needing its own dark block is a smell; justify it.

Sanctioned exceptions: the digest preview flips to the email's own `--dp-*` dark layer; OSM tiles are CSS-inverted into a dark basemap (`.leaflet-tile` only — markers/popups untouched); warm photos and report photos dim via `filter`, not new assets; the state-of-sound report keeps its own `--soh-*` surface tokens with its own dark block (§9 D-14).

---

## 7 · Vocabulary (law — Daniel, 2026-07-22)

Commits `0330c4c` (D-17) and `d57d296` (D-20). Applies to all public copy: pages, metas, JSON-LD, OG cards, `llms.txt`, the digest.

- Events are **"sound baths"** or **"sessions"** — never "rooms."
- Places are **"venues"** — "rooms" is never the unit noun for places. Literal physical-space English stays ("the room gets cool," "a full room").
- The public entity label is **"Organizer" / "Organizers"** — in labels, crumbs, facts, eyebrows, OG copy. "Operator" is internal/admin vocabulary and code identifiers only. URL slugs stay `/operator/` and `/operators/` (kept to avoid day-0 URL churn) — label ≠ slug is deliberate, not drift.

---

## 8 · Accessibility floor

- AA everywhere, both schemes: link blue 5.02:1 on paper, `#7CC3EC` on ink; the muted-ink floor (§1.2); button text ≥ 4.5:1 on its own fill (§3.1).
- Focus is always visible: `a, button, input` get a 2px `--accent-on-light` outline, offset 2px (`styles.css:74`); form fields swap their border for an accent outline.
- `prefers-reduced-motion` kills smooth scroll (`styles.css:22`); any future motion must check it.
- The no-JS baseline (§0) is itself an accessibility guarantee: content never gated on scripts; enhancement-only controls ship `hidden` until `filters.js` reveals them.
- Semantics: `.visually-hidden` for off-screen labels, `aria-pressed` on toggle chips/buttons, `aria-label`ed navs, alt text on every image (§4's honesty line governs its content).
- Sticky-chrome clearance: jump targets carry `scroll-margin-top: 90px` so anchors never land under the masthead (§1.4).

---

## 9 · Rulings — Daniel's call

### Ratified

**D-13 · Reading measure (2026-07-22): the shipped roomier 42–44rem family is the law.**
`--measure` is restated as `44rem` (was `68ch` — the same physical width at shipped font sizes, so no reader-visible change) and the fixed rem caps on listing/answer surfaces stand as shipped. Two roles, one family; the full spec lives in §1.3. No unification sweep — it buys no reader-visible change.

**D-14 · The editorial register (2026-07-22): the State of Sound report look is blessed.**
The `/state-of-sound-healing/` "report look" (`.soh-*`, `_src/lib/insights.py`) — rounded (14px radii on stat tiles/tables/figures, the 999px credit pill), the softer `--soh-*` surface palette (white and ink full-bleed bands), a px type scale up to 66px, count-up motion — is the official editorial/data sub-style. **When it applies:** report-class pages only — published, citable data artifacts (State of Sound Healing editions, and future reports of that class) where reading as a *document* beats reading as calendar chrome. **Never** on listing, entity, or chrome surfaces: the calendar proper keeps radius 0 and the utility register (§1.5). Constraints carried into the ruling: stays fully namespaced (its own `--soh-*`-style token prefix and dark block), sources root tokens where it can, and nothing leaks into `styles.css`.

### Open

**The masthead primary.**
The masthead ships `.btn-primary.btn-slim` "Get the digest" on every page (`_src/partials/header.html:18`). On event pages the aside's Tickets is also `.btn-primary` (`external_events.py:2165`) — two ink fills in view, against §3.1's one-primary rule. Candidate fixes: demote the masthead button to `.btn-secondary` sitewide, or scope the demotion to detail pages. Unresolved; the rule stands and the violation is known.

---

## Crosswalk

| Landed | Sections here |
|---|---|
| CAL-10 detail shell + map split | §2.2, §2.4 |
| CAL-11 buttons | §3.1 |
| CAL-12 row rebuild + density + radius | §2.3, §1.5 |
| CAL-13 entity template + empty states | §2.2, §2.5, §3.4 |
| CAL-14 dark mode | §6 |
| CAL-16 bands as filters | §2.3 |
| CAL-17 OG cards | §5 |
| CAL-18 digest preview | §2.7 |
| CAL-21 entity two-column | §2.2 |
| CAL-22 warm imagery | §4 |
| CAL-23 listing phases A/A2/B | §2.1 |
| CAL-DES-1 muted-ink floor | §1.2 |
| CAL-DES-2 og:image never rots | §5 |
| CAL-UX-2 month marker | §2.3 |
| D-17/D-20 vocabulary | §7 |
| D-13 reading measure ratified | §1.3, §9 |
| D-14 editorial register ratified | §1.5, §9 |
