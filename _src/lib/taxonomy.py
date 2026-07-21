"""Sound Bath Calendar — controlled tag vocabulary (CAL-01).

The v1 taxonomy: a tight, audience-first set of tags whose only job is to help a
real person DECIDE or FILTER (modality, intent, setting, access). The admin
normalizes ingested tags to these slugs; this module gives the SSG the labels,
the axis grouping, and the same normalizer so the site renders chips + a filter
facet from whatever the feed carries.

── SYNC CONTRACT ────────────────────────────────────────────────────────────
This file mirrors soundbathcalendar-admin/src/lib/taxonomy.ts. The two MUST
carry the same slugs. Edit BOTH when the vocabulary changes. Slugs are PERMANENT
once live (a rename = new slug + a redirect later): they become filter values,
feed data, and — in a later ticket — landing-page URLs.
"""

import re

# Axis display order (groups the filter UI and the curation checkboxes).
TAG_AXES = (
    ('modality', 'Sound'),
    ('intent', 'Intention'),
    ('setting', 'Setting'),
    ('access', 'Access'),
)

# The v1 vocabulary: (slug, label, axis). Keep it tight — every entry must help
# someone choose.
TAGS = (
    # Modality — what makes the sound
    ('gong-bath', 'Gong bath', 'modality'),
    ('crystal-bowls', 'Crystal bowls', 'modality'),
    ('himalayan-bowls', 'Himalayan bowls', 'modality'),
    ('voice-toning', 'Voice & toning', 'modality'),
    ('breathwork-sound', 'Breathwork + sound', 'modality'),
    ('drum-journey', 'Drum journey', 'modality'),
    ('tuning-forks', 'Tuning forks', 'modality'),
    ('live-instruments', 'Live instruments', 'modality'),
    ('432hz', '432 Hz', 'modality'),
    # Intent — why someone comes
    ('deep-rest', 'Deep rest & sleep', 'intent'),
    ('grief-loss', 'Grief & loss', 'intent'),
    ('anxiety-relief', 'Stress & anxiety', 'intent'),
    ('new-moon', 'New moon', 'intent'),
    ('full-moon', 'Full moon', 'intent'),
    ('couples', 'Couples', 'intent'),
    ('prenatal', 'Prenatal', 'intent'),
    ('yoga-nidra', 'Yoga nidra', 'intent'),
    ('chakra', 'Chakra', 'intent'),
    ('cacao', 'Cacao ceremony', 'intent'),
    # Setting — the container
    ('candlelit', 'Candlelit', 'setting'),
    ('outdoor', 'Outdoor', 'setting'),
    ('restorative-yoga', 'With restorative yoga', 'setting'),
    ('series', 'Series or course', 'setting'),
    ('private-group', 'Private / group', 'setting'),
    # Access — who it's for / barriers
    ('free-donation', 'Free or donation', 'access'),
    ('beginner-friendly', 'Beginner-friendly', 'access'),
    ('sober', 'Sober space', 'access'),
    ('wheelchair-accessible', 'Wheelchair accessible', 'access'),
    ('womens', "Women's circle", 'access'),
    ('lgbtq-friendly', 'LGBTQ+ friendly', 'access'),
    ('kids-family', 'Kids & family', 'access'),
)

VALID_SLUGS = frozenset(slug for slug, _label, _axis in TAGS)
LABEL_BY_SLUG = {slug: label for slug, label, _axis in TAGS}
AXIS_BY_SLUG = {slug: axis for slug, _label, axis in TAGS}


def tags_by_axis(axis):
    """Ordered TagDefs in one axis."""
    return [(s, l) for s, l, a in TAGS if a == axis]


# Free-form → canonical slug (identical to taxonomy.ts SYNONYMS). "sound bath" /
# "sound healing" are the category itself, not a filter facet → they map to None.
_SYNONYMS = {
    # modality
    'gong': 'gong-bath', 'gongs': 'gong-bath', 'gong meditation': 'gong-bath',
    'crystal': 'crystal-bowls', 'crystal singing bowls': 'crystal-bowls',
    'quartz bowls': 'crystal-bowls',
    'himalayan': 'himalayan-bowls', 'tibetan': 'himalayan-bowls',
    'tibetan bowls': 'himalayan-bowls', 'metal bowls': 'himalayan-bowls',
    'singing bowls': 'himalayan-bowls',
    'voice': 'voice-toning', 'toning': 'voice-toning', 'vocal': 'voice-toning',
    'chant': 'voice-toning', 'chanting': 'voice-toning', 'mantra': 'voice-toning',
    'breathwork': 'breathwork-sound', 'breath': 'breathwork-sound',
    'drum': 'drum-journey', 'drums': 'drum-journey', 'drumming': 'drum-journey',
    'shamanic drum': 'drum-journey',
    'tuning fork': 'tuning-forks', 'forks': 'tuning-forks',
    'live music': 'live-instruments', 'band': 'live-instruments',
    '432': '432hz', '432 hz': '432hz',
    # intent
    'sleep': 'deep-rest', 'deep rest': 'deep-rest', 'rest': 'deep-rest',
    'relaxation': 'deep-rest',
    'grief': 'grief-loss', 'loss': 'grief-loss', 'heartbreak': 'grief-loss',
    'breakup': 'grief-loss', 'breakups': 'grief-loss',
    'anxiety': 'anxiety-relief', 'stress': 'anxiety-relief',
    'stress relief': 'anxiety-relief', 'calm': 'anxiety-relief',
    'couple': 'couples', 'partner': 'couples',
    'prenatal': 'prenatal', 'pregnancy': 'prenatal', 'pregnant': 'prenatal',
    'nidra': 'yoga-nidra', 'chakras': 'chakra', 'cacao ceremony': 'cacao',
    # setting
    'candlelight': 'candlelit', 'candle': 'candlelit',
    'outdoors': 'outdoor', 'outside': 'outdoor',
    'restorative': 'restorative-yoga', 'yin': 'restorative-yoga',
    'course': 'series', 'weekly': 'series',
    'private': 'private-group', 'group booking': 'private-group',
    # access
    'free': 'free-donation', 'donation': 'free-donation',
    'by donation': 'free-donation', 'pay what you can': 'free-donation',
    'pwyc': 'free-donation', 'sliding scale': 'free-donation',
    'beginner': 'beginner-friendly', 'beginners': 'beginner-friendly',
    'intro': 'beginner-friendly',
    'sober': 'sober', 'alcohol free': 'sober',
    'wheelchair': 'wheelchair-accessible', 'accessible': 'wheelchair-accessible',
    'ada': 'wheelchair-accessible',
    'women': 'womens', "women's": 'womens', 'women only': 'womens',
    'lgbtq': 'lgbtq-friendly', 'lgbtq+': 'lgbtq-friendly', 'queer': 'lgbtq-friendly',
    'kids': 'kids-family', 'children': 'kids-family', 'family': 'kids-family',
    'family friendly': 'kids-family',
}

_KEY_RE = re.compile(r'[^a-z0-9]+')


def _normalize_key(raw):
    return _KEY_RE.sub(' ', str(raw).lower()).strip()


def normalize_tag(raw):
    """Free-form → canonical slug, or None when unrecognized."""
    key = _normalize_key(raw)
    if not key:
        return None
    as_slug = key.replace(' ', '-')
    if as_slug in VALID_SLUGS:
        return as_slug
    return _SYNONYMS.get(key)


def normalize_tags(raw_list):
    """Map a list to canonical slugs, dropping unknowns + dupes, order-preserving."""
    out = []
    for r in (raw_list or []):
        slug = normalize_tag(r)
        if slug is not None and slug not in out:
            out.append(slug)
    return out


def label_for(slug):
    """Display label for a slug; humanized fallback for an unknown slug so a
    stale feed value renders as a readable chip instead of crashing the build."""
    if slug in LABEL_BY_SLUG:
        return LABEL_BY_SLUG[slug]
    return slug.replace('-', ' ').replace('_', ' ').strip().capitalize()
