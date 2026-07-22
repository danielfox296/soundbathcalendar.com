# OG card photo sources (CAL-17)

Every stock photo used in the `img/og/` share cards, with source + license.
Raw originals live in `scripts/assets/stock/` (local-only; `scripts/` is
excluded from the deploy). Cards are generated locally by `scripts/og.py`
and committed here — CI never regenerates them (geocode-cache pattern).

## License

All photos are from **Pexels** and are used under the
[Pexels license](https://www.pexels.com/license/): free to use and modify
for commercial purposes without attribution. Attribution is recorded below
anyway, for provenance. No AI-generated stock was used (results credited to
AI-studio accounts were deliberately skipped).

## Photos

| File (scripts/assets/stock/) | Source URL | Photographer | Used on |
|---|---|---|---|
| pexels-6013471.jpg | https://www.pexels.com/photo/a-person-using-a-singing-bowl-6013471/ | Anastasia Shuraeva | og-default, tags |
| pexels-6013488.jpg | https://www.pexels.com/photo/a-man-playing-musical-instrument-6013488/ | Anastasia Shuraeva | denver |
| pexels-6013490.jpg | https://www.pexels.com/photo/a-man-holding-a-cymbal-6013490/ | Anastasia Shuraeva | gong-bath |
| pexels-6013474.jpg | https://www.pexels.com/photo/a-man-sitting-beside-the-singing-bowls-6013474/ | Anastasia Shuraeva | colorado-springs |
| pexels-6997998.jpg | https://www.pexels.com/photo/women-holding-singing-bowls-and-mallets-6997998/ | Arina Krasnikova | boulder, operators |
| pexels-6914822.jpg | https://www.pexels.com/photo/singing-bowl-on-a-man-lying-on-yoga-mat-6914822/ | Arina Krasnikova | what-to-expect |
| pexels-5602498.jpg | https://www.pexels.com/photo/a-room-with-gongs-and-tibetan-bowls-for-meditation-5602498/ | cottonbro studio | venues |
| pexels-5602465.jpg | https://www.pexels.com/photo/tibetan-singing-bowls-in-close-up-photography-5602465/ | cottonbro studio | fort-collins |
| pexels-3544322.jpg | https://www.pexels.com/photo/healing-music-3544322/ | Magicbowls | practitioners |
| pexels-8617327.jpg | https://www.pexels.com/photo/yellow-candles-on-black-surface-8617327/ | Pedro Nollet Sumida | map, breathwork-sound |

Downloaded 2026-07-22 at w=1600 (`images.pexels.com/photos/<id>/pexels-photo-<id>.jpeg?auto=compress&cs=tinysrgb&w=1600`).

## Fonts

`scripts/assets/fonts/SpaceGrotesk-VF.ttf` — Space Grotesk variable font
(SIL Open Font License 1.1), from
https://github.com/google/fonts/tree/main/ofl/spacegrotesk. Local-only,
used by `scripts/og.py` for the card type; never deployed.
