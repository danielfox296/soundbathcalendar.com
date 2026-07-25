"""v5 "Broadcast" tokens, type and imagery treatment for the social cards
(CAL-37; supersedes the frozen v4 pastel-mesh theme).

Split out from social.py because the palette family is a brand asset with its
own rules, not layout plumbing. The law is DESIGN.md; the constants here are
the same values styles.css and og.py carry.

ONE COMMITTED GROUND. The v4 six-palette date rotation is retired with the
pastels: v5 commits to the Night ground — near-black, violet-cast — as the
identity scheme (DESIGN.md §0), written in white-hot ink with ONE coral
signal on a hard budget. Every card of every kind shares it, so the feed
reads as one system with the site and the OG cards. A solid ground also
needs no dither: the mesh's noise pass existed because smooth gradients band
in JPEG, and a flat fill doesn't.

THE SIGNAL BUDGET (§1.1, translated to a card): coral appears as at most one
slab-class element per card — white text on a `SIGNAL` fill — plus
Free/Donation marks riding `SIGNAL_TEXT`. Nothing else is ever coral.

TYPE IS ARCHIVO, ZERO TRACKING. One variable file, two voices: the condensed
caps display voice (wdth 72–78, heavy) and the normal-width text voice
(wdth 100). The v4 tracked-eyebrow vocabulary is dead — the tracking law
(§1.3) allows no positive letter-spacing anywhere on a card.

IMAGERY IS THE HOUSE DUOTONE (CAL-28, scripts/treat.py — the exact ramp):
grayscale -> autocontrast(2) -> contrast 1.2 -> grain pre-colorize ->
indigo-shadow-to-white colorize, so a shared card and the site's Program
Grid read as the same treatment.

DETERMINISM HOLDS: a re-run must never produce a different card from one
Meta already ingested. Solid grounds are trivially stable; the grain rides
PIL's effect_noise exactly the way treat.py and the v4 mesh dither already
did, so same inputs -> same pixels.
"""
import os

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_PATH = os.path.join(ROOT, 'scripts', 'assets', 'fonts', 'Archivo-VF.ttf')

W, H = 1080, 1350          # 4:5 — the tallest portrait the Instagram feed allows
MARGIN = 76

# v5 "Broadcast" Night tokens (DESIGN.md §1.1 — same values as styles.css/og.py).
NIGHT = (14, 12, 18)         # --paper dark  #0E0C12, the committed ground
INK = (245, 242, 237)        # --ink dark    #F5F2ED white-hot — ALL text
MUTED = (171, 168, 163)      # --muted dark  #ABA8A3 — meta, fine print
SIGNAL = (185, 58, 43)       # --signal      #B93A2B — slab fills only
SIGNAL_TEXT = (226, 114, 78)  # --signal-text dark #E2724E — Free/Donation marks
SURFACE = (28, 24, 38)       # --surface dark #1C1826 — imageless type tiles
WHITE = (255, 255, 255)      # slab text: white-on-coral, 5.67:1
DUO_INK = (53, 47, 92)       # --ink light #352F5C — the duotone shadow end

# Structural hairlines: ink at 0.14 over each ground, precomputed solid
# because JPEG has no alpha and PIL lines don't blend.
LINE = (46, 44, 49)          # on NIGHT
LINE_SURFACE = (58, 55, 66)  # on SURFACE

# What the manifest reports where v4 reported its rotating palette. post.py
# prints the key, so it survives; the value is now the committed scheme.
SCHEME = 'night'


def font(size, weight=400, width=100):
    """Archivo variable — axis order in the file is (wght, wdth), same file
    and call shape as og.py. width 72 is the monument voice, 78 the card-name
    voice, 100 the text voice."""
    f = ImageFont.truetype(FONT_PATH, size)
    f.set_variation_by_axes([weight, width])
    return f


def ground(fill=NIGHT, size=(W, H)):
    """One committed solid ground — Night unless a type tile asks for
    SURFACE. No mesh, no rotation, no dither."""
    return Image.new('RGB', size, fill)


def duotone(img):
    """The CAL-28 house treatment, byte-for-byte the treat.py ramp:
    grayscale -> autocontrast(cutoff 2) -> contrast 1.2 -> grain
    (effect_noise sigma 52 blended at 0.19 PRE-colorize, so it prints in
    ink) -> colorize indigo #352F5C shadows to white highlights."""
    g = ImageOps.autocontrast(img.convert('L'), cutoff=2)
    g = ImageEnhance.Contrast(g).enhance(1.2)
    noise = Image.effect_noise(g.size, 52)
    g = Image.blend(g, noise, 0.19)
    return ImageOps.colorize(g, black=DUO_INK, white=WHITE)


def slab(draw, x, y, text, f, pad_x=18, pad_y=12):
    """The card's one coral slab: white caps on a SIGNAL fill, zero tracking,
    radius 0. Returns (right, bottom) of the box. Budget law: at most one
    slab-class element per card."""
    l, t, r, b = draw.textbbox((0, 0), text, font=f)
    box_r = x + (r - l) + 2 * pad_x
    box_b = y + (b - t) + 2 * pad_y
    draw.rectangle((x, y, box_r, box_b), fill=SIGNAL)
    draw.text((x + pad_x - l, y + pad_y - t), text, font=f, fill=WHITE)
    return box_r, box_b


def slab_h(draw, f, pad_y=12):
    """Height a slab() of this font will take — for measuring blocks before
    drawing them. Uses a full-height caps probe so every slab of a given
    font size lands the same height regardless of its own glyphs."""
    l, t, r, b = draw.textbbox((0, 0), 'AJQ', font=f)
    return (b - t) + 2 * pad_y


if __name__ == '__main__':
    # Tiny self-check: tokens render, the font loads with both axes, a slab
    # draws. Run: python3 scripts/social_theme.py
    img = ground()
    d = ImageDraw.Draw(img)
    slab(d, MARGIN, MARGIN, 'SOUND BATH CALENDAR', font(31, 700))
    d.text((MARGIN, 220), 'NIGHT GROUND', font=font(120, 800, 72), fill=INK)
    d.text((MARGIN, 360), 'muted meta line', font=font(34), fill=MUTED)
    print('social_theme v5 ok —', img.size)
