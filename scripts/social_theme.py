"""Pastel mesh grounds + type tokens for the social cards (CAL-25).

Split out from social.py because the palette family is a brand asset with its
own rules, not layout plumbing.

SIX PALETTES, ROTATED BY DATE. Each post picks one from the day's ordinal, so
the family cycles through the feed while any given day always re-renders
identically — a re-run must never produce a different card from the one Meta
already ingested.

MESH, NOT A RAMP: every pixel is an inverse-distance-weighted blend of four
colour centres, so four tones bleed into one another with no hard axis. The
centre POSITIONS rotate per slide while the colours stay fixed, which is what
lets a ten-slide carousel vary without ever leaving its palette.

DARK TYPE ON LIGHT. The pastel ground inverts the type stack: --ink on the
paper side, and --accent-on-light (#1F6FA8) for the eyebrow, times and
prices, which is the token the site already proved at AA on a light ground.
The ice --accent is a mark colour and would fail as text here.
"""
import os

from PIL import Image, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_PATH = os.path.join(ROOT, 'scripts', 'assets', 'fonts', 'SpaceGrotesk-VF.ttf')

W, H = 1080, 1350          # 4:5 — the tallest portrait the Instagram feed allows
MARGIN = 76

INK = (10, 11, 13)              # --ink
ACCENT = (31, 111, 168)         # --accent-on-light, 5.02:1 on paper
MUTED = (78, 88, 102)           # darkened from the site's --gray: #98A1AB is a
#                                 border tone and drops under AA as body text
#                                 on the lighter corners of these meshes.
RULE = (176, 184, 196)

# name -> the four corner colours, and the falloff power for the blend.
PALETTES = {
    'dawn': ([(247, 218, 210), (250, 231, 205), (226, 214, 242), (214, 229, 242)], 2.4),
    'seafoam': ([(214, 238, 230), (206, 227, 242), (236, 231, 246), (246, 238, 226)], 2.4),
    'iris': ([(222, 216, 244), (243, 219, 238), (211, 229, 246), (240, 234, 220)], 2.4),
    'sand': ([(242, 231, 213), (223, 233, 219), (240, 222, 212), (226, 234, 240)], 2.4),
    'sky': ([(219, 234, 246), (236, 243, 249), (223, 231, 247), (245, 236, 230)], 2.4),
    'saturated': ([(255, 205, 190), (198, 226, 250), (226, 196, 245), (253, 232, 186)], 2.0),
}

# Fixed order so the date rotation is stable across Python versions.
PALETTE_ORDER = ['dawn', 'iris', 'saturated', 'seafoam', 'sand', 'sky']

CORNERS = [(0.12, 0.10), (0.92, 0.18), (0.08, 0.86), (0.88, 0.92)]

_MESH_RES = (72, 90)


def palette_for(day):
    """Deterministic palette for a date. Consecutive days differ; the same
    date always resolves to the same one."""
    return PALETTE_ORDER[day.toordinal() % len(PALETTE_ORDER)]


def font(size, weight=400):
    f = ImageFont.truetype(FONT_PATH, size)
    f.set_variation_by_axes([weight])
    return f


def _mesh(colours, power, rotate, size):
    w, h = size
    sw, sh = _MESH_RES
    # Rotating which corner holds which colour is what varies slide to slide.
    pts = [((CORNERS[(i + rotate) % 4][0] * (sw - 1),
             CORNERS[(i + rotate) % 4][1] * (sh - 1)), c)
           for i, c in enumerate(colours)]
    g = Image.new('RGB', (sw, sh))
    half = power / 2
    for y in range(sh):
        for x in range(sw):
            wsum, acc = 0.0, [0.0, 0.0, 0.0]
            for (px, py), col in pts:
                d2 = (x - px) ** 2 + (y - py) ** 2
                weight = 1.0 / (d2 ** half + 1e-6)
                wsum += weight
                for i in range(3):
                    acc[i] += col[i] * weight
            g.putpixel((x, y), tuple(min(255, round(acc[i] / wsum)) for i in range(3)))
    return g.resize((w, h), Image.BICUBIC)


def ground(palette, rotate=0, size=(W, H)):
    """One pastel mesh field, dithered.

    The noise is dither, not texture: a smooth gradient is what JPEG bands
    worst, and 1.8% of a mid-grey field breaks the banding up.
    """
    colours, power = PALETTES[palette]
    base = _mesh(colours, power, rotate, size)
    noise = Image.effect_noise(size, 6).convert('RGB')
    return Image.blend(base, noise, 0.018)
