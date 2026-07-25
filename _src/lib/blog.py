"""Sound Bath Calendar — the blog (CAL-19; was /roundups/ until CAL-22).

  /blog/           — index of posts (noindexed until >= INDEX_MIN posts,
                     doorway-page discipline like /tags/ and the entity indexes)
  /blog/<slug>/    — one page per committed post source (always indexed)

One home for everything dated: essays with a personal byline and the
calendar cuts that used to live at /roundups/. The old URLs are redirect
stubs under _src/pages/roundups/ and _src/pages/roundup-post/.

Posts are COMMITTED SOURCE, not generated from the feed: each file under
_src/blog/<slug>.md is front matter + a markdown-lite body written and
edited by a human. The editorial voice is Daniel's — the `note` field on
events (his verbatim one-liners) is the intended spine of the calendar
posts; the build never synthesizes opinion. Factual connective tissue comes
from event/venue data at WRITING time, but the build renders exactly what
the file says — a published post never drifts because the feed changed (the
same freeze discipline as the insights editions).

Front matter ('---'-delimited `key: value` lines at the top of the file):
    title        required — the H1 and Article headline
    dek          one-line subtitle under the H1
    date         required — YYYY-MM-DD publication date (sort + schema)
    kind         eyebrow label + index tag ('Essay', 'Roundup'). Defaults to
                 'Post' on the page and shows no tag on the index.
    byline       author credit; defaults to the site name. Today that is
                 "Sound Bath Calendar" (Organization author in schema); a
                 personal byline renders as a Person author — Daniel's call.
    description  meta description
    draft        'true' -> the file is skipped entirely (not built)

Markdown-lite (deliberately tiny, stdlib only):
    '## ' / '### '   headings
    '> '             blockquote — reserved for Daniel's verbatim notes
    '- '             unordered list items
    blank line       paragraph break
    **bold**  *em*   inline emphasis
    [text](href)     links; root-relative hrefs ('/venue/x/') are rewritten
                     against nav_prefix so cross-links work at any depth
    <!-- ... -->     comment LINES pass through raw (HUMAN REVIEW markers
                     survive into the built page, like the _src/pages/ files)
Everything else is escaped — raw HTML is not a feature of this format.
"""

import html as html_mod
import os
import re

BLOG_REL_DIR = os.path.join('_src', 'blog')

# Doorway discipline: posts are always real content (indexed); the INDEX only
# earns `index, follow` once it lists this many posts. Set at 2 (CAL-22): the
# concern behind the gate is thin auto-generated hubs (/tags/, the entity
# indexes, which can materialize with a single row). Every post here is a
# committed, hand-written file, so a two-post index is a real listing, and
# holding the section's only hub back from search costs more than it saves.
INDEX_MIN = 2


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def load_posts(repo_root, log=print):
    """All committed, non-draft posts, newest first. Never raises — a bad file
    is logged and skipped (same graceful discipline as the feed loaders)."""
    d = os.path.join(repo_root, BLOG_REL_DIR)
    posts = []
    try:
        names = sorted(os.listdir(d))
    except FileNotFoundError:
        return []
    for name in names:
        if not name.endswith('.md'):
            continue
        path = os.path.join(d, name)
        try:
            with open(path, encoding='utf-8') as f:
                meta, body = _parse(f.read())
            if str(meta.get('draft', '')).strip().lower() == 'true':
                continue
            if not meta.get('title') or not _DATE_RE.match(meta.get('date', '')):
                raise ValueError('front matter needs title + date (YYYY-MM-DD)')
            meta['slug'] = name[:-3]
            meta['body'] = body
            posts.append(meta)
        except Exception as exc:
            log(f'  ⚠ blog post {name} unusable ({exc.__class__.__name__}: {exc}) — skipped')
    posts.sort(key=lambda p: p['date'], reverse=True)
    return posts


def _parse(text):
    """Split '---' front matter from the body. Returns (meta_dict, body_str)."""
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.DOTALL)
    if not m:
        raise ValueError("missing '---' front matter block")
    meta = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, _, value = line.partition(':')
        meta[key.strip()] = value.strip()
    return meta, text[m.end():].strip()


def fmt_date(iso):
    """'2026-07-22' -> 'July 22, 2026' (no strftime: %-d is platform-bound)."""
    months = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
              'August', 'September', 'October', 'November', 'December']
    y, mth, day = iso.split('-')
    return f'{months[int(mth) - 1]} {int(day)}, {y}'


# ---------------------------------------------------------------------------
# Markdown-lite rendering (escape-first: only our own markup survives)
# ---------------------------------------------------------------------------
_LINK_RE = re.compile(r'\[([^\]]+)\]\(([^)\s]+)\)')
_BOLD_RE = re.compile(r'\*\*(.+?)\*\*')
_EM_RE = re.compile(r'(?<!\*)\*([^*]+)\*(?!\*)')
_COMMENT_RE = re.compile(r'^<!--.*-->$')


def _inline(text, nav_prefix):
    """Escaped text with links/bold/em applied. Hrefs are restricted to http(s),
    root-relative (rewritten to nav_prefix), or plain relative paths."""
    out = html_mod.escape(text, quote=False)

    def _link(m):
        label, href = m.group(1), m.group(2)
        if href.startswith('/'):
            href = nav_prefix + href[1:]
        elif not re.match(r'^(https?:)?//|^[\w.-]', href):
            return label  # unsupported scheme (javascript: etc.) — drop the link
        safe = html_mod.escape(href, quote=True)
        return f'<a href="{safe}">{label}</a>'

    out = _LINK_RE.sub(_link, out)
    out = _BOLD_RE.sub(r'<strong>\1</strong>', out)
    out = _EM_RE.sub(r'<em>\1</em>', out)
    return out


def render_body(body, nav_prefix):
    """The post body as HTML. Line-oriented: headings, blockquotes, lists,
    comment passthrough, paragraphs."""
    blocks, para, quote, items = [], [], [], []

    def _flush_para():
        if para:
            blocks.append(f'<p>{_inline(" ".join(para), nav_prefix)}</p>')
            para.clear()

    def _flush_quote():
        if quote:
            inner = '\n'.join(f'  <p>{_inline(q, nav_prefix)}</p>' for q in quote)
            blocks.append(f'<blockquote>\n{inner}\n</blockquote>')
            quote.clear()

    def _flush_items():
        if items:
            inner = '\n'.join(f'  <li>{_inline(i, nav_prefix)}</li>' for i in items)
            blocks.append(f'<ul>\n{inner}\n</ul>')
            items.clear()

    def _flush():
        _flush_para(); _flush_quote(); _flush_items()

    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            _flush()
        elif _COMMENT_RE.match(line):
            _flush()
            blocks.append(line)
        elif line.startswith('### '):
            _flush()
            blocks.append(f'<h3>{_inline(line[4:], nav_prefix)}</h3>')
        elif line.startswith('## '):
            _flush()
            blocks.append(f'<h2>{_inline(line[3:], nav_prefix)}</h2>')
        elif line.startswith('> '):
            _flush_para(); _flush_items()
            quote.append(line[2:])
        elif line.startswith('- '):
            _flush_para(); _flush_quote()
            items.append(line[2:])
        else:
            _flush_quote(); _flush_items()
            para.append(line)
    _flush()
    return '\n'.join(blocks)


# ---------------------------------------------------------------------------
# Page bodies (build.py owns the shell + JSON-LD, same split as insights)
# ---------------------------------------------------------------------------
def render_post(post, nav_prefix):
    esc = lambda s: html_mod.escape(s, quote=False)
    dek = (f'\n    <p class="cal-summary">{esc(post["dek"])}</p>'
           if post.get('dek') else '')
    byline = post.get('byline') or 'Sound Bath Calendar'
    return f'''<section class="section section--light post">
  <div class="container post-narrow">
    <p class="cal-crumbs"><a href="{nav_prefix}">Calendar</a> &rsaquo; <a href="{nav_prefix}blog/">Blog</a> &rsaquo; {esc(post["title"])}</p>
    <span class="eyebrow">{esc(post.get('kind') or 'Post')}</span>
    <h1 class="cal-h1">{esc(post["title"])}</h1>{dek}
    <p class="post-meta">By {esc(byline)} · {esc(fmt_date(post["date"]))}</p>
    <div class="post-body">
{render_body(post["body"], nav_prefix)}
    </div>
    <p class="post-cta"><a class="btn btn-primary" href="{nav_prefix}">See this week's sessions</a></p>
  </div>
</section>'''


def render_index(posts, nav_prefix):
    esc = lambda s: html_mod.escape(s, quote=False)
    rows = []
    for p in posts:
        dek = (f'\n        <p class="post-item__dek">{esc(p["dek"])}</p>'
               if p.get('dek') else '')
        kind = (f'<span class="post-item__kind">{esc(p["kind"])}</span> · '
                if p.get('kind') else '')
        rows.append(f'''      <li class="post-item">
        <a class="post-item__title" href="{nav_prefix}blog/{p["slug"]}/">{esc(p["title"])}</a>{dek}
        <p class="post-item__meta">{kind}{esc(fmt_date(p["date"]))}</p>
      </li>''')
    listing = ('\n'.join(rows) if rows else
               '      <li class="post-item"><p class="post-item__dek">'
               'The first post is on its way.</p></li>')
    return f'''<section class="section section--light post">
  <div class="container post-narrow">
    <p class="cal-crumbs"><a href="{nav_prefix}">Calendar</a> &rsaquo; Blog</p>
    <span class="eyebrow">Blog</span>
    <h1 class="cal-h1">Blog</h1>
    <p class="cal-summary">Writing from the calendar: essays on what an hour of sound actually does, and occasional cuts of the listings showing which venues are busy, what costs nothing, and what only happens once.</p>
    <ul class="post-list">
{listing}
    </ul>
  </div>
</section>'''


# Page-scoped styles, injected via {{page_style}} (same delivery as the
# _src/pages/ style.css files). Ink goes through --ink-rgb so dark mode
# (CAL-14 token flip) holds.
BLOG_HEAD = '''<style>
.post-narrow { max-width: 48rem; }
.post-meta { font-size: 0.85rem; color: var(--muted); margin: 0 0 2.2rem; }
.post-body h2 {
  font-size: clamp(1.25rem, 2.4vw, 1.6rem);
  font-weight: 500;
  letter-spacing: -0.01em;
  margin: 2.4rem 0 0.6rem;
}
.post-body h3 { font-size: 1.1rem; font-weight: 600; margin: 1.8rem 0 0.5rem; }
.post-body p { color: var(--ink); line-height: 1.68; margin: 0 0 0.9rem; }
.post-body ul { margin: 0 0 0.9rem; padding-left: 1.2rem; }
.post-body li { color: var(--ink); line-height: 1.6; margin: 0 0 0.35rem; }
/* Blockquote = Daniel's verbatim note. Quiet accent rule, same family as the
   what-to-expect health note — set apart, never loud. */
.post-body blockquote {
  border-left: 3px solid var(--ink);
  padding: 0.15rem 0 0.15rem 1rem;
  margin: 1.2rem 0;
}
.post-body blockquote p { color: var(--ink); font: 500 1.05rem var(--font-display); }
.post-cta { margin: 2.2rem 0 0; }
.post-list { list-style: none; margin: 0.4rem 0 0; padding: 0; }
.post-item { border-top: 1px solid var(--line); padding: 1.1rem 0 1.2rem; }
.post-item__title { font: 500 1.2rem var(--font-display); letter-spacing: -0.01em; }
.post-item__dek { color: var(--ink); line-height: 1.6; margin: 0.35rem 0 0; }
.post-item__meta { font-size: 0.82rem; color: var(--muted); margin: 0.35rem 0 0; }
/* The kind tag ("Essay" / "Roundup") — caps micro-furniture on --muted
   (v5: zero tracking, no accent tokens; CAL-36 owns this surface's full
   v5 pass). The branch's v4 values (tracked caps, --accent-on-light) were
   corrected to law at landing. */
.post-item__kind {
  font-weight: 600;
  letter-spacing: 0;
  text-transform: uppercase;
  font-size: 0.72rem;
  color: var(--muted);
}
</style>'''
