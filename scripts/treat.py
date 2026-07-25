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


def treat_pair(src_img, stem, w=SIZE, h=SIZE, small=True):
    """Write the -i / -c (and -i<small>) derivatives for one source image."""
    base = _cover(src_img.convert('RGB'), w, h)
    g = _treat_gray(base)
    sizes = {}
    sizes['i'] = _save(ImageOps.colorize(g, black=INK, white=WHITE),
                       os.path.join(CARDS_DIR, f'{stem}-i.jpg'))
    sizes['c'] = _save(ImageOps.colorize(g, black=SIGNAL, white=WHITE),
                       os.path.join(CARDS_DIR, f'{stem}-c.jpg'))
    if small:
        small_g = _treat_gray(_cover(src_img.convert('RGB'),
                                     SIZE_SMALL, SIZE_SMALL))
        sizes['i280'] = _save(
            ImageOps.colorize(small_g, black=INK, white=WHITE),
            os.path.join(CARDS_DIR, f'{stem}-i280.jpg'))
    return sizes


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

    # Prune derivatives of events that left the future set (past/renamed/
    # dropped) — the directory reflects only the current program + editorial.
    pruned = 0
    for name in os.listdir(CARDS_DIR):
        if not name.endswith('.jpg') or name.startswith('editorial-'):
            continue
        stem = name.rsplit('-', 1)[0]
        if stem not in keep:
            os.remove(os.path.join(CARDS_DIR, name))
            pruned += 1

    total_kb = sum(
        os.path.getsize(os.path.join(CARDS_DIR, n))
        for n in os.listdir(CARDS_DIR) if n.endswith('.jpg')) // 1024
    print(f'\ntreat done: {made} generated, {skipped} kept, {tiles} type tiles, '
          f'{failed} failed, {pruned} pruned — img/cards/ {total_kb}KB')


if __name__ == '__main__':
    main(force='--force' in sys.argv[1:])
