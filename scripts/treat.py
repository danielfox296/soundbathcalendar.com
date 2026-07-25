"""Generate the committed duotone card derivatives for the Program Grid
(CAL-28, ratified 2026-07-25).

The ratified house treatment, shared in spirit with scripts/og.py's ramp but
specified exactly by the CAL-28 ticket:

    grayscale -> autocontrast(cutoff 2) -> contrast 1.2
    -> grain (Image.effect_noise sigma 52, blended at alpha 0.19 PRE-colorize,
       so the grain prints in ink, not as a gray wash)
    -> ImageOps.colorize:
         -i  index/rest layer: black #352F5C (indigo), white #FFFFFF
         -c  coral hover layer: black #B93A2B, white #FFFFFF

Source hierarchy per event (imagery law — flyers never stand in for people,
stock never attaches to a specific session, entity photos are real-only):

    1. the event's own image_url from the live feed (~92% coverage) —
       snapshotted here once; the committed derivative is the rot-proof copy
    2. the linked practitioner's committed photo (img/practitioners/<slug>.jpg)
       — THEIR sessions only
    3. nothing -> the site renders a type tile (a designed poster variant,
       not a fallback state)

Outputs, committed under img/cards/ (CI never runs this — like og.py):

    <event-slug>-i.jpg      560x560 center-square, the rest layer
    <event-slug>-i280.jpg   280x280, the srcset small variant
    <event-slug>-c.jpg      560x560, the hover layer
    editorial-what-to-expect-{i,c}.jpg   1300x406 editorial band (stock,
        generic-editorial only — provenance img/og/SOURCES.md)

Derivatives of events no longer in the future row set are pruned each run.
Existing derivatives are kept (the snapshot survives CDN rot); --force
regenerates everything.

LOCAL-only: needs Pillow. Run from the repo root:

    python3 scripts/treat.py [--force]
"""
import io
import os
import sys
import urllib.request

from PIL import Image, ImageEnhance, ImageOps

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
from _src.lib import external_events  # noqa: E402

CARDS_DIR = os.path.join(REPO, 'img', 'cards')
ENT_DIR = os.path.join(REPO, 'img', 'entities')   # CAL-29 entity portraits
PRACT_DIR = os.path.join(REPO, 'img', 'practitioners')

STOCK_DIR = os.path.join(REPO, 'scripts', 'assets', 'stock')

INK = (0x35, 0x2F, 0x5C)      # --ink light: indigo — the -i shadow end
SIGNAL = (0xB9, 0x3A, 0x2B)   # --signal: coral — the -c shadow end
WHITE = (255, 255, 255)

SIZE = 560                    # committed card square
SIZE_SMALL = 280              # srcset small variant
QUALITY = 75                  # ticket: q74-76

# Some operator CDNs (img.evbuc.com) 403 bare urllib requests.
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
      'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36')


def _treat_gray(img):
    """The shared pre-colorize ramp: grayscale -> autocontrast(2) ->
    contrast 1.2 -> ink-printing grain (sigma 52 @ alpha 0.19)."""
    g = ImageOps.autocontrast(img.convert('L'), cutoff=2)
    g = ImageEnhance.Contrast(g).enhance(1.2)
    noise = Image.effect_noise(g.size, 52)
    return Image.blend(g, noise, 0.19)


def _cover(img, w, h):
    """Center-crop cover to w x h."""
    return ImageOps.fit(img, (w, h), Image.LANCZOS, centering=(0.5, 0.5))


def _save(img, path):
    img.save(path, 'JPEG', quality=QUALITY, optimize=True, progressive=True)
    return os.path.getsize(path) // 1024


def treat_pair(src_img, stem, w=SIZE, h=SIZE, small=True, outdir=None):
    """Write the -i / -c (and -i<small>) derivatives for one source image."""
    outdir = outdir or CARDS_DIR
    base = _cover(src_img.convert('RGB'), w, h)
    g = _treat_gray(base)
    sizes = {}
    sizes['i'] = _save(ImageOps.colorize(g, black=INK, white=WHITE),
                       os.path.join(outdir, f'{stem}-i.jpg'))
    sizes['c'] = _save(ImageOps.colorize(g, black=SIGNAL, white=WHITE),
                       os.path.join(outdir, f'{stem}-c.jpg'))
    if small:
        small_g = _treat_gray(_cover(src_img.convert('RGB'),
                                     SIZE_SMALL, SIZE_SMALL))
        sizes['i280'] = _save(
            ImageOps.colorize(small_g, black=INK, white=WHITE),
            os.path.join(outdir, f'{stem}-i280.jpg'))
    return sizes


def treat_entities(force=False):
    """CAL-29: the entity portraits — practitioner headshots as the SAME
    duotone pair the Program Grid cards ride, so a directory index and a
    profile head read as one index aesthetic.

    Sources are the repo's own committed, reviewed images (img/practitioners/,
    provenance in its SOURCES.md — the practitioners' own promotional
    material); nothing is fetched. A practitioner with no committed photo gets
    no derivative and the site draws its type-plate: flyers never stand in for
    faces (imagery law), so there is deliberately no session-image fallback.

    VENUES ARE DELIBERATELY EXCLUDED. img/venues/*.jpg are Google Places
    photos (scripts/harvest_venue_photos.py); Google's terms allow resizing
    and cropping but not recoloring, so venue heads and cards draw the
    type-plate and the venue page keeps its photograph UNMODIFIED with its
    attribution. Do not "fix" this by adding VENUE_DIR here.

    Outputs, committed under img/entities/:
        pract-<slug>-{i,i280,c}.jpg      560/280 squares
    """
    os.makedirs(ENT_DIR, exist_ok=True)
    keep, made, skipped = set(), 0, 0
    for prefix, src_dir in (('pract', PRACT_DIR),):
        if not os.path.isdir(src_dir):
            continue
        for name in sorted(os.listdir(src_dir)):
            if not name.lower().endswith(('.jpg', '.jpeg', '.png')):
                continue
            stem = f'{prefix}-{os.path.splitext(name)[0]}'
            keep.add(stem)
            if os.path.exists(os.path.join(ENT_DIR, f'{stem}-i.jpg')) and not force:
                skipped += 1
                continue
            try:
                with Image.open(os.path.join(src_dir, name)) as src:
                    sizes = treat_pair(src, stem, outdir=ENT_DIR)
                print(f'  ok {stem} ({sizes["i"]}+{sizes["c"]}KB)')
                made += 1
            except Exception as e:
                print(f'  !! {stem}: {type(e).__name__}: {e} — type-plate')

    pruned = 0
    for name in os.listdir(ENT_DIR):
        if not name.endswith('.jpg'):
            continue
        if name.rsplit('-', 1)[0] not in keep:
            os.remove(os.path.join(ENT_DIR, name))
            pruned += 1
    print(f'  entities: {made} generated, {skipped} kept, {pruned} pruned')


def fetch(url, referer=None):
    headers = {'User-Agent': UA}
    if referer:
        headers['Referer'] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        return Image.open(io.BytesIO(r.read()))


def sources_for(row):
    """[(kind, opener), ...] in hierarchy order — a hotlink-blocked flyer
    falls through to the practitioner photo (their session), else the site
    renders a type tile."""
    out = []
    img_url = external_events._safe_image_url(row.get('image_url') or '')
    if img_url:
        out.append(('flyer', lambda: fetch(img_url)))
        # Some CDNs 403 referrerless requests but allow the listing site's.
        ref = external_events._safe_ext_url(row.get('source_url') or '')
        out.append(('flyer+ref',
                    lambda: fetch(img_url, referer=ref or 'https://www.google.com/')))
    pr = row.get('practitioner') or {}
    slug = pr.get('slug') if isinstance(pr, dict) else None
    if slug:
        photo = os.path.join(PRACT_DIR, f'{slug}.jpg')
        if os.path.exists(photo):
            out.append(('practitioner', lambda: Image.open(photo)))
    return out


def main(force=False):
    os.makedirs(CARDS_DIR, exist_ok=True)
    feed = external_events.load_feed(REPO)
    now = external_events.current_now()
    rows = external_events.build_rows(feed, now=now)

    keep = set()
    made = skipped = tiles = failed = 0
    for row in rows:
        slug = external_events.event_slug(row)
        if not slug:
            continue
        sources = sources_for(row)
        if not sources:
            tiles += 1
            continue
        out_i = os.path.join(CARDS_DIR, f'{slug}-i.jpg')
        if os.path.exists(out_i) and not force:
            keep.add(slug)
            skipped += 1
            continue
        err = None
        for kind, opener in sources:
            try:
                with opener() as src:
                    sizes = treat_pair(src, slug)
                print(f'  ok {slug} ({kind}, {sizes["i"]}+{sizes["c"]}KB)')
                keep.add(slug)
                made += 1
                err = None
                break
            except Exception as e:  # a dead CDN URL must not sink the run
                err = e
        if err is not None:
            print(f'  !! {slug}: {type(err).__name__}: {err} — type tile')
            failed += 1

    # Editorial band (stock, generic-editorial only): the what-to-expect
    # photograph, treated wide. Regenerated every run (cheap, one file).
    with Image.open(os.path.join(STOCK_DIR, 'pexels-6914822.jpg')) as ed:
        sizes = treat_pair(ed, 'editorial-what-to-expect',
                           w=1300, h=406, small=False)
    print(f'  ok editorial-what-to-expect ({sizes["i"]}+{sizes["c"]}KB)')

    # The State of Sound report's two photographs (CAL-36): the CC0 hero and
    # the still-life beside the price section, in the house treatment — which
    # is also what retires the dark-mode brightness hacks that used to keep a
    # daylight landscape from blasting through the night ground. Credits are
    # unaffected (they ride the caption, not the pixels).
    INSIGHTS_SRC = os.path.join(REPO, 'img', 'insights')
    for stem, fname, w, h in (
            ('hero-state-of-sound', 'front-range-foothills.jpg', 1600, 900),
            ('fig-singing-bowls', 'singing-bowls.jpg', 1200, 800)):
        src = os.path.join(INSIGHTS_SRC, fname)
        if not os.path.exists(src):
            continue
        with Image.open(src) as im:
            sizes = treat_pair(im, stem, w=w, h=h, small=False)
        print(f'  ok {stem} ({sizes["i"]}+{sizes["c"]}KB)')

    # /what-to-expect/ hero (CAL-34): the same photograph at the page's own
    # 21:10 crop, in the same treatment — the reading page opens in the house
    # register instead of a stray natural photo. -c is written and unused
    # (the hero doesn't hover); it costs one file and keeps the pair rule.
    with Image.open(os.path.join(STOCK_DIR, 'pexels-6914822.jpg')) as hero:
        sizes = treat_pair(hero, 'hero-what-to-expect',
                           w=1600, h=762, small=False)
    print(f'  ok hero-what-to-expect ({sizes["i"]}+{sizes["c"]}KB)')

    # Prune derivatives of events that left the future set (past/renamed/
    # dropped) — the directory reflects only the current program + editorial.
    pruned = 0
    for name in os.listdir(CARDS_DIR):
        if (not name.endswith('.jpg') or name.startswith('editorial-')
                or name.startswith('hero-') or name.startswith('fig-')):
            continue
        stem = name.rsplit('-', 1)[0]
        if stem not in keep:
            os.remove(os.path.join(CARDS_DIR, name))
            pruned += 1

    # CAL-29: entity portraits, from the repo's own committed photos.
    treat_entities(force=force)

    total_kb = sum(
        os.path.getsize(os.path.join(CARDS_DIR, n))
        for n in os.listdir(CARDS_DIR) if n.endswith('.jpg')) // 1024
    print(f'\ntreat done: {made} generated, {skipped} kept, {tiles} type tiles, '
          f'{failed} failed, {pruned} pruned — img/cards/ {total_kb}KB')


if __name__ == '__main__':
    main(force='--force' in sys.argv[1:])
