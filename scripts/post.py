"""Publish the day's social carousel to the Facebook Page and Instagram (CAL-25).

Reads the manifest scripts/social.py wrote and posts its slides as one
carousel. DRY RUN BY DEFAULT — it prints exactly what would go out and
touches nothing. Publishing requires --live.

    python3 scripts/post.py                      # dry run, today
    python3 scripts/post.py --kind weekend       # dry run, the weekend post
    python3 scripts/post.py --live               # actually publish

CREDENTIALS (env; needed for --live):
    META_PAGE_TOKEN   a PAGE access token — the ONLY required secret.

The Page and Instagram ids are derived from the token at run time (a Page
token knows its own Page, and the Page knows its linked Instagram account), so
there is nothing else to look up or paste. META_PAGE_ID / META_IG_USER_ID
still override, for a token that can see more than one Page.

ON THE TOKEN — this is the decision that keeps the whole thing from rotting.
Instagram's own login path issues a token that expires every 60 days, which
would mean a refresh job that rewrites its own GitHub secret and a PAT scoped
to do it. Taking the Facebook-Login path instead, a Page access token derived
from a long-lived user token DOES NOT EXPIRE, and the same token authorizes
both surfaces: Page posts and Instagram publishing (via the IG account linked
to the Page). One secret, set once, no refresh machinery.

    scripts/meta_token.py does the whole chain and refuses to hand back a
    token that turns out to be expiring. Prefer it to doing this by hand.

The chain it runs:

  1. Graph API Explorer -> your app -> User Token with pages_show_list,
     pages_manage_posts, pages_read_engagement, instagram_basic,
     instagram_content_publish.
  2. Exchange for a long-lived user token:
     GET /oauth/access_token?grant_type=fb_exchange_token
         &client_id=<app id>&client_secret=<app secret>&fb_exchange_token=<short>
  3. GET /me/accounts with THAT token -> the Page's `access_token` is the
     never-expiring one. Store it as the META_PAGE_TOKEN secret.
  4. GET /<page id>?fields=instagram_business_account -> META_IG_USER_ID.

The app stays in Development mode and never needs App Review: it only ever
touches accounts Daniel has a role on. Going Live is what triggers review.

HOW EACH SURFACE TAKES A MULTI-IMAGE POST — they are not symmetrical:

  Instagram  a container per slide with is_carousel_item=true, then a parent
             container with media_type=CAROUSEL and the children ids, then
             publish the parent. 2-10 slides. The caption goes on the PARENT;
             a caption on a child is silently dropped.
  Facebook   each photo uploaded to /photos with published=false to get a
             media id, then one /feed post with attached_media. Posting them
             published=true instead would spray N separate photo posts.

WHY INSTAGRAM NEEDS PUBLIC URLS: Meta cURLs each image at publish time rather
than accepting bytes, and takes JPEG only. That is the entire reason the
slides are built into the Pages deploy and this script runs after it — see
--require-live-image.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _src.lib.sessions_feed import DENVER  # noqa: E402
from scripts.social import kind_for  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Overridable because Meta retires versions on a ~2-year clock; when this one
# goes, set META_API_VERSION rather than editing the script.
API_VERSION = os.environ.get('META_API_VERSION', 'v25.0')
GRAPH = f'https://graph.facebook.com/{API_VERSION}'

HTTP_TIMEOUT_S = 45
IMAGE_POLL_TRIES = 20
IMAGE_POLL_SLEEP_S = 15
CONTAINER_POLL_TRIES = 12
CONTAINER_POLL_SLEEP_S = 5


class PostError(RuntimeError):
    pass


# ---------- graph plumbing ----------

def _graph(path, params, method='GET'):
    """One Graph call. Raises PostError carrying Meta's own message — its
    error bodies name the actual problem (expired token, unpermitted scope,
    unreachable media) far better than a status code does."""
    url = f'{GRAPH}/{path.lstrip("/")}'
    data = urllib.parse.urlencode(params).encode()
    if method == 'GET':
        url = f'{url}?{data.decode()}'
        data = None
    req = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors='replace')
        try:
            err = json.loads(body).get('error', {})
            detail = f'{err.get("type", "?")}: {err.get("message", body)}'
            if err.get('error_user_msg'):
                detail += f' — {err["error_user_msg"]}'
        except ValueError:
            detail = body
        raise PostError(f'{method} {path} failed ({exc.code}) — {detail}') from None
    except urllib.error.URLError as exc:
        raise PostError(f'{method} {path} unreachable — {exc.reason}') from None


def wait_for_image(url, tries=IMAGE_POLL_TRIES, sleep_s=IMAGE_POLL_SLEEP_S):
    """Block until a slide is actually served as a JPEG.

    deploy-pages returning success means the deployment is live, but the CDN
    edge can lag it by a few seconds. Meta does not retry a media fetch — it
    just fails the container — so polling here is far cheaper than debugging
    a 'media could not be downloaded' after the fact.
    """
    last = 'no attempt made'
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, method='HEAD')
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
                ctype = resp.headers.get('content-type', '')
                if resp.status == 200 and 'image/jpeg' in ctype:
                    return attempt
                last = f'status {resp.status}, content-type {ctype!r}'
        except urllib.error.HTTPError as exc:
            last = f'status {exc.code}'
        except urllib.error.URLError as exc:
            last = str(exc.reason)
        if attempt < tries:
            time.sleep(sleep_s)
    raise PostError(f'slide never became publicly readable at {url} — {last}')


def _await_container(creation_id, token, label):
    """Poll a media container to FINISHED. Publishing an IN_PROGRESS container
    is the single most common cause of a silent no-post."""
    for attempt in range(1, CONTAINER_POLL_TRIES + 1):
        status = _graph(creation_id, {
            'fields': 'status_code,status', 'access_token': token,
        })
        code = status.get('status_code')
        if code == 'FINISHED':
            return
        if code == 'ERROR':
            raise PostError(f'{label} container failed: {status.get("status", code)}')
        if attempt == CONTAINER_POLL_TRIES:
            raise PostError(f'{label} container stuck at {code} after '
                            f'{CONTAINER_POLL_TRIES} checks')
        time.sleep(CONTAINER_POLL_SLEEP_S)


def resolve_targets(token):
    """Work out which Page and Instagram account this token speaks for.

    A Page token already knows its own Page (/me) and the Page knows its
    linked Instagram account, so making a human look those ids up and paste
    them into two more secrets was busywork with two extra chances to paste
    the wrong thing. One secret in, both ids derived here.

    META_PAGE_ID / META_IG_USER_ID still override, for the case of a token
    that can see several Pages.
    """
    page_id = os.environ.get('META_PAGE_ID', '').strip()
    ig_user_id = os.environ.get('META_IG_USER_ID', '').strip()
    if page_id and ig_user_id:
        return page_id, ig_user_id

    if not page_id:
        try:
            page_id = _graph('me', {'fields': 'id,name',
                                    'access_token': token}).get('id', '')
        except PostError as exc:
            print(f'  could not resolve the Page from the token — {exc}',
                  file=sys.stderr)
            return '', ig_user_id

    if not ig_user_id and page_id:
        # Absent is normal and not an error: no linked Instagram account just
        # means this run posts to Facebook only.
        try:
            linked = _graph(page_id, {
                'fields': 'instagram_business_account{id,username}',
                'access_token': token,
            }).get('instagram_business_account') or {}
            ig_user_id = linked.get('id', '')
        except PostError as exc:
            print(f'  no Instagram account resolved ({exc}) — Facebook only')
    return page_id, ig_user_id


# ---------- the two surfaces ----------

def post_facebook(manifest, page_id, token):
    """Upload each slide unpublished, then one feed post with attached_media."""
    media_ids = []
    for i, slide in enumerate(manifest['slides'], start=1):
        res = _graph(f'{page_id}/photos', {
            'url': slide['url'], 'published': 'false', 'access_token': token,
        }, method='POST')
        ident = res.get('id')
        if not ident:
            raise PostError(f'slide {i}: no photo id in response: {res}')
        media_ids.append(ident)

    params = {'message': manifest['caption_facebook'], 'access_token': token}
    for i, ident in enumerate(media_ids):
        params[f'attached_media[{i}]'] = json.dumps({'media_fbid': ident})
    res = _graph(f'{page_id}/feed', params, method='POST')
    post_id = res.get('id')
    if not post_id:
        raise PostError(f'no post id in feed response: {res}')
    return f'https://www.facebook.com/{post_id}', post_id


def post_instagram(manifest, ig_user_id, token):
    """Child container per slide -> parent CAROUSEL container -> publish."""
    slides = manifest['slides']
    if not 2 <= len(slides) <= 10:
        raise PostError(f'Instagram carousels take 2-10 slides, got {len(slides)}')

    children = []
    for i, slide in enumerate(slides, start=1):
        res = _graph(f'{ig_user_id}/media', {
            'image_url': slide['url'],
            'is_carousel_item': 'true',
            'access_token': token,
        }, method='POST')
        ident = res.get('id')
        if not ident:
            raise PostError(f'slide {i}: no container id in response: {res}')
        _await_container(ident, token, f'slide {i}')
        children.append(ident)

    parent = _graph(f'{ig_user_id}/media', {
        'media_type': 'CAROUSEL',
        'children': ','.join(children),
        # The caption belongs on the PARENT — one set on a child is dropped.
        'caption': manifest['caption_instagram'],
        'access_token': token,
    }, method='POST')
    creation_id = parent.get('id')
    if not creation_id:
        raise PostError(f'no carousel container id in response: {parent}')
    _await_container(creation_id, token, 'carousel')

    res = _graph(f'{ig_user_id}/media_publish', {
        'creation_id': creation_id, 'access_token': token,
    }, method='POST')
    media_id = res.get('id')
    if not media_id:
        raise PostError(f'no media id in publish response: {res}')
    permalink = _graph(media_id, {
        'fields': 'permalink', 'access_token': token,
    }).get('permalink', '')
    return permalink, media_id


# ---------- driver ----------

def load_manifest(day, kind):
    # daily lives at <date>.json; the others get a suffix.
    name = f'{day}.json' if kind == 'daily' else f'{day}-{kind}.json'
    path = os.path.join(ROOT, 'img', 'social', name)
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def _preview(manifest):
    print(f'  date         {manifest["date"]} ({manifest["kind"]})')
    print(f'  palette      {manifest["palette"]}')
    # Event manifests carry a session count; the practitioner one names a person.
    if 'event_count' in manifest:
        print(f'  sessions     {manifest["event_count"]}')
    if 'practitioner' in manifest:
        print(f'  practitioner {manifest["practitioner"]}')
    if 'photos_used' in manifest:
        print(f'  photos       {manifest["photos_used"]}/'
              f'{manifest["sessions_on_slides"]} slides with event images')
    print(f'  slides       {len(manifest["slides"])}')
    for i, slide in enumerate(manifest['slides'], start=1):
        print(f'    {i:>2}  {slide["url"]}')
    for label, key in (('facebook', 'caption_facebook'),
                       ('instagram', 'caption_instagram')):
        print(f'\n  --- {label} caption ---')
        for line in manifest[key].splitlines():
            print(f'  | {line}')
    print()


def main():
    ap = argparse.ArgumentParser(description="Publish the day's social carousel.")
    ap.add_argument('--date', help='YYYY-MM-DD (default: today, Denver)')
    ap.add_argument('--kind', choices=('daily', 'weekend', 'practitioner', 'auto'),
                    default='auto')
    ap.add_argument('--live', action='store_true',
                    help='actually publish (default: dry run)')
    ap.add_argument('--require-live-image', action='store_true',
                    help='poll every slide URL before publishing')
    ap.add_argument('--allow-stale-date', action='store_true',
                    help="publish a day that isn't today (default: refuse)")
    ap.add_argument('--skip-facebook', action='store_true')
    ap.add_argument('--skip-instagram', action='store_true')
    args = ap.parse_args()

    today = datetime.now(DENVER).date()
    day = args.date or today.isoformat()
    kind = args.kind
    if kind == 'auto':
        kind = kind_for(datetime.strptime(day, '%Y-%m-%d').date())

    manifest = load_manifest(day, kind)
    if manifest is None:
        # Not an error. social.py writes nothing for a day with no approved
        # sessions, and silence beats posting "nothing on tonight".
        print(f'no {kind} card for {day} — nothing to post')
        return 0

    print(f'{"PUBLISH" if args.live else "DRY RUN"} — {day} ({kind})')
    _preview(manifest)

    if not args.live:
        print('dry run — nothing published. Pass --live to post.')
        return 0

    if day != today.isoformat() and not args.allow_stale_date:
        # Guards the obvious footgun: re-running an old workflow and blasting
        # a day that has already happened.
        raise SystemExit(f'refusing to publish {day} on {today} — '
                         f'pass --allow-stale-date if you mean it')

    token = os.environ.get('META_PAGE_TOKEN', '').strip()
    if not token:
        raise SystemExit('META_PAGE_TOKEN must be set to publish')
    page_id, ig_user_id = resolve_targets(token)
    if not (page_id or ig_user_id):
        raise SystemExit('token resolves to no Page and no Instagram account')

    if args.require_live_image:
        for i, slide in enumerate(manifest['slides'], start=1):
            tries = wait_for_image(slide['url'])
            print(f'  slide {i:>2} live after {tries} check(s)')

    # Each surface is attempted independently and failures are collected, so
    # an Instagram problem never costs the Facebook post (or the other way).
    failures = []
    if page_id and not args.skip_facebook:
        try:
            url, ident = post_facebook(manifest, page_id, token)
            print(f'  facebook  posted {ident} — {url}')
        except PostError as exc:
            failures.append(f'facebook: {exc}')
    if ig_user_id and not args.skip_instagram:
        try:
            url, ident = post_instagram(manifest, ig_user_id, token)
            print(f'  instagram posted {ident} — {url}')
        except PostError as exc:
            failures.append(f'instagram: {exc}')

    for line in failures:
        print(f'  FAILED {line}', file=sys.stderr)
    # Non-zero on any failure so the workflow goes red and GitHub mails it —
    # that notification is the whole monitoring story for this job.
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
