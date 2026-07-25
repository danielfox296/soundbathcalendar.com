# Sound Bath Calendar — DESIGN.md

*Ratified 2026-07-22; tokens and register re-ratified 2026-07-25 as v5 "Broadcast" (CAL-26/27). The calendar's own design constitution. Every "per DESIGN.md" in `styles.css` means this file.*

**Ground truth.** The law lives here; the implementation lives in `styles.css`, the page-local style blocks in `_src/lib/*.py` (`EVENT_PAGE_STYLE`, `VENUE_PAGE_STYLE`, `PRACTITIONER_PAGE_STYLE`, `OPERATOR_PAGE_STYLE`, `BROWSE_STYLE`, `ROUNDUPS_HEAD`, `MAP_HEAD`, `INSIGHTS_HEAD`, `CITY_WARM_STYLE`), and `_src/partials/`. If doc and tree disagree, that is a defect: fix one to match the other and record the call here. `RULE:` lines are load-bearing.

---

## 0 · Doctrine (in force)

- Weight extremes over timid contrast. Asymmetry over three-identical-cards.
- **v5 "Broadcast" (ratified 2026-07-25):** committed grounds — warm white day, near-black violet-cast night — written entirely in ink, with ONE coral signal on a hard budget (§1.1). Night is the identity scheme. The ∿ wave mark is retired from all chrome (masthead, footer, empty states, favicon, OG, separators).
- Radius 0 — sharp editorial edges (§1.5 for the two sanctioned exceptions).
- Motion only where it earns its place. No glassmorphism. No gradients on chrome. No emoji bullets.
- The calendar is the site: one sheet (`styles.css`), utility register.
- **NO JS in the baseline.** Every rule holds with scripts blocked. JS is progressive enhancement only: `filters.js` reveals the filter bar, the map initializes or stays an empty box, `<details>` disclosures are native. No-JS visitors see every row, always.
- Answer-first. The root opens with the machine-extractable summary (`.cal-summary`), not a hero. No tall marketing hero, no image, no animation on the listing root.
- Honest surfaces: every count is computed from the feed at build time, never typed in (§3.4).
- Utility voice, no belief required (public copy never says "non-woo" — commit `d57d296`). Copy law beyond vocabulary (§7) lives in the copy audits, not here.

---

## 1 · Tokens

### 1.1 Color (v5 "Broadcast" — CAL-26, ratified 2026-07-25)

Defined at `:root` in `styles.css:4`. Dark mode flips the same names (§6). All ratios re-verified by `scripts/contrast_check.py` — rerun it after ANY token change.

| Token | Light "Day" | Dark "Night" | Role |
|---|---|---|---|
| `--paper` | `#F5F2ED` warm white | `#0E0C12` near-black, violet-cast | committed grounds; never tinted pastels |
| `--ink` | `#352F5C` indigo (10.98:1) | `#F5F2ED` white-hot (17.41:1) | ALL text — the site is WRITTEN in these; violet never tints dark-scheme type |
| `--ink-rgb` | `53, 47, 92` | `245, 242, 237` | structural alphas (hairlines, tints) ONLY — never text |
| `--muted` | `#676561` (5.21:1) | `#ABA8A3` (8.21:1) | meta/counts/fine print — the discrete grey that replaced the muted-ink alpha ramp for text |
| `--surface` | `#352F5C` (paper text) | `#1C1826` | imageless type tiles (CAL-28) |
| `--signal` | `#B93A2B` coral | unchanged | slabs/fills: ticker band, TONIGHT slab, tile hover — white text on it (5.67:1) |
| `--signal-text` | `#B93A2B` (5.08:1) | `#E2724E` (6.25:1) | coral AS TEXT: Free/Donation marks, hover-name color |
| `--signal-rgb` | `185, 58, 43` | unchanged | hover tint washes only |
| `--shadow-rgb` | `53, 47, 92` (ink-cast) | `0, 0, 0` | shadows — never a light glow |
| `--line` | `rgba(var(--ink-rgb), 0.14)` | follows the flip | hairlines **between blocks** — never a control edge |
| `--field-line` | `rgba(var(--ink-rgb), 0.46)` | follows the flip | the edge of anything a person types or clicks into |

There is no third hue. The ice accent, the link blue, and `--gray` are deleted — the only sanctioned survivors are the frozen `--soh-*` (until CAL-36) and `--dp-*` (until CAL-37) namespaces, which depict artifacts that still ship v4.

RULE — **the signal budget:** coral appears as at most **2 slabs** per screen (ticker + TONIGHT) + Free/Donation marks + hover states. Nothing else. A third slab, a coral label, a coral border at rest — defects.

RULE: every structural alpha (hairline, border, tint wash) is written as `rgba(var(--ink-rgb), a)` — never a hardcoded gray. This single convention is what makes dark mode a one-token flip (§6). A hex gray in a component is a defect.

RULE: links are `--ink`. Prose links keep the UA underline; chrome links (nav rows, CTA rows, crumbs) may drop it where position and weight carry the affordance, and hover restores it. Hover MAY move name-class text to `--signal-text` (the comp's card-hover language). Focus rings are `--ink` (10.98:1 / 17.41:1 — 2.4.11 clears on both grounds).

RULE: form-control borders use `--field-line`, not `--line`. WCAG 1.4.11 asks 3:1 for the *visual boundary of a control*; the 0.14 hairline is a decorative divider between blocks (exempt) and lands at 1.2:1. The two are not interchangeable, and a control edge on `--line` — or on the old 0.25 literal (1.77:1) — is a defect. Decorative borders around already-legible text (e.g. `.cal-row__dist`) are not controls and keep their lighter edge.

### 1.2 Two text colors, no ramp (CAL-26 — supersedes the CAL-DES-1 opacity floor)

Text is binary in v5: **`--ink`** (headings, names, prose, links, controls) or **`--muted`** (crumbs, meta, times, stamps, counts, labels, fine print, empty lines). Daniel's ruling of record: *small type is never purple* — an alpha over indigo ink tints grey text violet, so the muted-ink TEXT ramp is retired sitewide.

RULE: `rgba(var(--ink-rgb), a)` never colors text. It survives for **lines and tints only** — hairlines, control edges, wash backgrounds, decorative glyph marks.

Exempt (depictions, not page UI): the digest-preview miniature keeps its scaled email values; monogram/placeholder marks stay decorative alphas (`.dir-card__media--ph::before` 0.32).

### 1.3 Type (v5 — CAL-27, ratified 2026-07-25)

**Archivo variable is the site's only typeface.** Self-hosted latin subset (~88KB woff2, axes `wdth 62..125` + `wght 100..900`) at `vendor/fonts/`, `@font-face` + `font-display: swap` + a `<link rel="preload">` in the base layout; zero requests to Google Fonts. Space Grotesk and Inter are retired. Fallback stack: `system-ui, 'Helvetica Neue', Arial, sans-serif` — **no serif anywhere, ever** (standing ruling), in the stack or otherwise. `--font-display`/`--font-body` survive as aliases of the same stack so page-local sheets keep resolving.

One file, two voices: the condensed display voice (`font-stretch: 72–78%`, heavy, UPPERCASE via CSS `text-transform` — crawlable text stays sentence-case in HTML) and the normal-width text voice (`font-stretch: 100%`). Headings base (`h1,h2,h3`): 800 · stretch 72% · `line-height 1.02` · `letter-spacing -0.005em`.

| Surface | Spec |
|---|---|
| H1 monument `.cal-h1` | `clamp(56px, 8vw, 112px)` · wdth 72 · wght 800 · UPPERCASE · lh .92 · ls −.005em |
| Band heads `.cal-band__h2` | `clamp(36px, 4.5vw, 64px)` · wdth 72 · wght 800 · UPPERCASE · lh .95 |
| Card names `.cal-row__name` (h3>a) | 30px (22 mobile) · wdth 78 · wght 750 · UPPERCASE · lh 1.02; featured 2-up cards 44px (CAL-28) |
| Detail/directory H1s (`.detail__h1`, `.dir-h1`) | `clamp(2.4rem, 5vw, 4rem)` · UPPERCASE · lh .95 (CAL-29 refines) |
| Answer-first summary `.cal-summary` | 24px · wdth 100 · wght 400 · lh 1.35 · **bold counts** (`summary_html`) |
| Meta / UI / forms | 16px · wdth 100 · `--muted` · lh 1.45 |
| Fine print (`.cal-updated`, `.footer-fine`) | 13px · `--muted` |
| Masthead | 15px · UPPERCASE · wordmark 700, nav 400 · no added tracking |
| Ticker (CAL-28) | 16px · 700 · UPPERCASE · **ls .055em** — the single sanctioned positive tracking on the site (Daniel-ruled) · `/` separators |

RULE — **the tracking law: zero positive letter-spacing everywhere except the ticker.** The small-caps tracked-label vocabulary no longer exists — dates-as-monuments replaced it (CAL-28). Negative tracking on monuments is fine. (The digest-preview miniature keeps its tracked depiction of the shipping email until CAL-37.)

RULE: `font-variant-numeric: tabular-nums` on times, prices, and counts (`.cal-row__when`, `.cal-row__meta`, `.cal-updated`, summary counts).

**Wordmark:** `SOUND BATH CALENDAR` — caps, wght 700, wdth 100, **no mark of any kind** (∿ retired). Footer matches.

Rows are a scan surface — their leading (1.02–1.35) is deliberately tighter than page prose (1.65); don't "fix" it up. The reading register (learn/explainers) keeps sentence-case heads until its own pass (CAL-34).

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
3. **Media tile** (`.cal-row__media`): fixed 104px, 3:2, radius 2px, `object-fit: cover` — flyers of any source aspect are framed, never raw. Image-less rows render the reserved placeholder (`--empty`: a bare tint tile — the ∿ glyph is retired, CAL-26; CAL-29 brings the type-tile language) so every text column shares one left edge (CAL-12). On mobile: 84px.
4. **Text column**: marks line (`__marks`: city chip + modality kicker, §3.2) → name → meta (one line where it fits, capped 42rem) → optional practitioner cross-link (`__with`) → optional editorial note (`__note`: Daniel's one line, display 500, 2px accent left rule, capped 38rem) → ghost-link CTA row (`__cta`).

Mobile ≤640px: rows become bordered cards (radius 0), the date rail runs inline, `.cal-rows` drops its top rule. First-viewport budget: stamp + summary + first rows above the fold.

### 2.4 List + map (`/map/`, CAL-10 phase C)

`.map-split`: ≥900px → list `minmax(340px, 5fr)` beside sticky map `7fr`; the list column hides media tiles (the map is the visual). Below 900px the map band stacks on top. Map height is fixed px (680 / 440 mobile) so Leaflet initializes against real dimensions. Pins carry the decision datum — a venue's session count — as ink circles with paper borders (`.sbc-pin`; the `--hot` variant is a coral `--signal` fill with white text, CAL-26); clusters sum their contents; popups ride the tokens so they flip in dark. With JS blocked the list is fully usable and the map box simply never initializes.

### 2.5 Entity directories (`/venues/`, `/practitioners/`, `/operators/`)

One shared card design (`_src/lib/directory.py`): `.dir-grid` auto-fill `minmax(13.5rem, 1fr)`; `.dir-card` is borderless — the 3:2 media tile carries the mass (entity photo, else next session's listing image, else the monogram placeholder). Placeholder = the entity's initial via `data-monogram` over the tint with a 2px ink-alpha baseline — designed absence, not a broken image; `.img-broken` collapses to the same state. (CAL-29 replaces these with letterform type-plates.)

### 2.6 Masthead & footer

Masthead (`_src/partials/header.html`): sticky, compact — wordmark · scrolling city anchors · slim digest capture (inline form ≥900px, anchor link below). Footer: brand column + three link columns over a fine-print bar (`Sound Bath Calendar` · `Denver, Colorado · Privacy` — the `/privacy/` link rides every page); footer links ride the muted-ink ramp, **not** accent — reference furniture, not a call to action.

### 2.7 Digest block (CAL-18)

Signup pitch + form beside a build-time mini-render of this week's **actual** Thursday email, in the email's own `--dp-*` palette (from `digest.ts`, both schemes). The preview column is deliberately narrow (19rem) — a glimpse, not a second calendar. The tear-off fade and "+N more" line render **only when the week actually holds more sessions than shown** — a fully shown week gets no false "more."

---

## 3 · Components

### 3.1 Buttons (CAL-11)

- `.btn-primary`: `--ink` fill, `--paper` text (10.98:1 light / 15.6:1 dark). Hover: `inset 0 -3px 0 var(--signal)` — a coral underline (a sanctioned hover state), never a fill swap. Auto-inverts to a light button in dark mode.
- `.btn-secondary`: transparent, ink text, `--line` border; hover border `--ink`.
- `.btn-slim`: the compact variant (masthead). Ghost tier = plain ink 600 link CTAs (`.cal-row__cta`, `.cal-event__link`).
- RULE: **exactly one `.btn-primary` per view intent.** Everything else is secondary or ghost. Known open violation: the masthead digest button on event pages — §9.
- RULE: every button's text ≥ 4.5:1 on its own fill. Pressed states are ink-fill-on-paper (`.cal-filters__nearme[aria-pressed="true"]`, the jump chips) — coral is never a pressed/selected fill (budget law, §1.1).
- Specificity note: anchor buttons inside `.section--light` need the label pin (`.section--light a.btn-primary { color: var(--paper) }`, `styles.css:112`) — keep it when adding button contexts.

### 3.2 Chips & marks

- `.cal-tag` (CAL-01): 600 · 0.68rem · ink text · `rgba(ink, 0.18)` border · radius 0. Variants: `--toggle` (checkbox, `accent-color: var(--ink)`); `--link` (CAL-09 — links to its tag page; hover = `--signal-text` border + `rgba(var(--signal-rgb), 0.07)` tint, a sanctioned hover state). Link-or-span rule: a chip links only when its landing page exists.
- Marks line: `.cal-row__city` (every row) + `.cal-row__modality` (the "what kind" kicker, middot-separated, links per CAL-09) — both uppercase 0.68rem `--muted` (caps micro-furniture).
- Free/Donation in row meta is `<b>` riding `--signal-text` — the one text-signal mark (§1.1).
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

**Anatomy (v5, CAL-26):** a split card on the Night ground — a duotone-and-grain photo panel (indigo shadows → warm-white highlights; the ramp CAL-28's `treat.py` shares) beside a near-black text panel carrying the coral slab kicker, the title in condensed-caps Archivo (wght 800 · wdth 72 · UPPERCASE, shrink-to-fit), and a `--muted` sub. No wave mark. Card copy reuses the page's own H1/meta language — no new claims.

**Provenance law:** every photo is logged in `img/og/SOURCES.md` — source URL, photographer, license, where used. A card whose photo isn't in SOURCES.md doesn't ship.

**No-rot law (CAL-DES-2):** `og:image` is always a **committed** card — event permalinks use their city card, else `og-default.jpg` — never the organizer's signed CDN image, which expires and leaves share previews dead. Rot-prone listing images may still render on-page and in JSON-LD, where failure degrades gracefully (§4 fallback).

**Pipeline:** local-only, like `geocode.py` — needs Pillow + the vendored assets in `scripts/assets/` (stock JPGs + `Archivo-VF.ttf`). Outputs are committed under `img/og/`; **CI never regenerates them.**

**Procedure — new page needs a card:**
1. New tag page → add a `CARDS` entry in `scripts/og.py` (new photo? add it to `scripts/assets/stock/` + a SOURCES.md row).
2. Run `python3 scripts/og.py` from the repo root (watch for the title-overflow warning).
3. Commit the JPEG + any SOURCES.md change.
4. New city → keep `CITY_SLUGS` in sync with `external_events.CITY_ANCHOR`.

---

## 6 · Dark mode (CAL-14)

One `prefers-color-scheme: dark` token flip over the **same layout** — no bespoke dark components (`styles.css:467`). Palette proven in the digest email (`digest.ts`).

Mechanism (v5): flipping `--ink-rgb` inverts every `rgba(var(--ink-rgb), a)` hairline/tint at once; `--line` follows; `--paper` becomes the one `#0E0C12` near-black ground (the desk/sheet split is retired — Night is a single committed ground); `--muted` lifts to its light grey; `--signal-text` lifts to `#E2724E` (coral never passes AA as text on near-black at the light value); `--shadow-rgb` drops to true black; `.btn-primary` auto-inverts.

RULE: new components get dark mode for free **only** if they follow §1.1's `--ink-rgb` rule. A component needing its own dark block is a smell; justify it.

Sanctioned exceptions: the digest preview flips to the email's own `--dp-*` dark layer (its v4 accents pinned in that namespace until CAL-37); OSM tiles are CSS-inverted into a dark basemap (`.leaflet-tile` only — markers/popups untouched); warm photos and report photos dim via `filter`, not new assets; the state-of-sound report keeps its own `--soh-*` surface AND accent tokens with its own dark block until CAL-36 (§9 D-14).

---

## 7 · Vocabulary (law — Daniel, 2026-07-22)

Commits `0330c4c` (D-17) and `d57d296` (D-20). Applies to all public copy: pages, metas, JSON-LD, OG cards, `llms.txt`, the digest.

- Events are **"sound baths"** or **"sessions"** — never "rooms."
- Places are **"venues"** — "rooms" is never the unit noun for places. Literal physical-space English stays ("the room gets cool," "a full room").
- The public entity label is **"Organizer" / "Organizers"** — in labels, crumbs, facts, eyebrows, OG copy. "Operator" is internal/admin vocabulary and code identifiers only. URL slugs stay `/operator/` and `/operators/` (kept to avoid day-0 URL churn) — label ≠ slug is deliberate, not drift.

---

## 8 · Accessibility floor

- AA everywhere, both schemes: ink 10.98:1 / 17.41:1; `--muted` 5.21:1 / 8.21:1; `--signal-text` 5.08:1 / 6.25:1; button text ≥ 4.5:1 on its own fill (§3.1). `scripts/contrast_check.py` re-verifies every shipped pair.
- Focus is always visible: `a, button, input` get a 2px `--ink` outline, offset 2px; form fields swap their border for an ink outline.
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
| CAL-26 v5 Broadcast tokens | §0, §1.1, §1.2, §5, §6, §8 |
| CAL-27 Archivo type system | §1.3 |
