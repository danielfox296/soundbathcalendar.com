"""WCAG contrast audit for the v5 "Broadcast" tokens (CAL-26 DoD).

Stdlib-only. Recomputes the ratio for every token pair the palette ships and
fails loudly if any drops below its floor — rerun after ANY token change:

    python3 scripts/contrast_check.py
"""

# v5 tokens (CAL-26, ratified 2026-07-25). Keep in sync with styles.css :root.
PAPER_L, INK_L = '#F5F2ED', '#352F5C'
PAPER_D, INK_D = '#0E0C12', '#F5F2ED'
MUTED_L, MUTED_D = '#676561', '#ABA8A3'
SURFACE_L, SURFACE_D = '#352F5C', '#1C1826'
SIGNAL = '#B93A2B'
SIGNAL_TEXT_L, SIGNAL_TEXT_D = '#B93A2B', '#E2724E'
SURFACE_TEXT = '#F5F2ED'   # --surface-text (CAL-28 tiles) — one value, both schemes
WHITE = '#FFFFFF'
# --field-line rides rgba(ink-rgb, alpha) over paper; audit the BLENDED edge
# (CAL-38 D7: 0.46 was tuned for v4's near-black ink and fell to 2.51:1 on
# the v5 day ground — 0.56 clears the 1.4.11 boundary floor on both).
FIELD_ALPHA = 0.56


def _blend(fg_hex, alpha, bg_hex):
    f, b = fg_hex.lstrip('#'), bg_hex.lstrip('#')
    out = ''.join(
        f'{round(int(f[i:i + 2], 16) * alpha + int(b[i:i + 2], 16) * (1 - alpha)):02X}'
        for i in (0, 2, 4))
    return '#' + out


FIELD_LINE_L = _blend(INK_L, FIELD_ALPHA, PAPER_L)
FIELD_LINE_D = _blend(INK_D, FIELD_ALPHA, PAPER_D)


def _lin(c):
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lum(hexcol):
    h = hexcol.lstrip('#')
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def ratio(fg, bg):
    a, b = sorted((_lum(fg), _lum(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def blend(fg, bg, alpha):
    """The solid color an alpha-composited fg reads as over bg."""
    f = [int(fg.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4)]
    b = [int(bg.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4)]
    return '#' + ''.join(f'{round(alpha * x + (1 - alpha) * y):02X}'
                         for x, y in zip(f, b))


# (label, fg, bg, floor). 4.5 = AA text; 3.0 = large text / UI boundaries.
PAIRS = [
    ('ink on paper (light)', INK_L, PAPER_L, 4.5),
    ('ink on paper (dark)', INK_D, PAPER_D, 4.5),
    ('muted on paper (light)', MUTED_L, PAPER_L, 4.5),
    ('muted on paper (dark)', MUTED_D, PAPER_D, 4.5),
    ('paper text on surface (light tile)', PAPER_L, SURFACE_L, 4.5),
    ('ink text on surface (dark tile)', INK_D, SURFACE_D, 4.5),
    ('muted on surface (dark tile)', MUTED_D, SURFACE_D, 4.5),
    ('white on signal slab', WHITE, SIGNAL, 4.5),
    ('surface-text on surface (light tile)', SURFACE_TEXT, SURFACE_L, 4.5),
    ('surface-text on surface (dark tile)', SURFACE_TEXT, SURFACE_D, 4.5),
    # The tile caption runs surface-text at 0.78 alpha — check the blended
    # value on each surface (CAL-28).
    ('tile caption 0.78 alpha (light)', blend(SURFACE_TEXT, SURFACE_L, 0.78), SURFACE_L, 4.5),
    ('tile caption 0.78 alpha (dark)', blend(SURFACE_TEXT, SURFACE_D, 0.78), SURFACE_D, 4.5),
    ('signal-text on paper (light)', SIGNAL_TEXT_L, PAPER_L, 4.5),
    ('signal-text on paper (dark)', SIGNAL_TEXT_D, PAPER_D, 4.5),
    ('signal slab against paper (light, non-text)', SIGNAL, PAPER_L, 3.0),
    ('signal slab against paper (dark, non-text)', SIGNAL, PAPER_D, 3.0),
    ('field-line edge on paper (light, control boundary)', FIELD_LINE_L, PAPER_L, 3.0),
    ('field-line edge on paper (dark, control boundary)', FIELD_LINE_D, PAPER_D, 3.0),
]

if __name__ == '__main__':
    failed = False
    for label, fg, bg, floor in PAIRS:
        r = ratio(fg, bg)
        ok = r >= floor
        failed |= not ok
        print(f'{"ok " if ok else "FAIL"} {r:5.2f}:1  (floor {floor})  {label}')
    raise SystemExit(1 if failed else 0)
