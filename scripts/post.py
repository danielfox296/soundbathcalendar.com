"""Publish the day's social card to the Facebook Page and Instagram (CAL-25).

Reads the manifest scripts/social.py wrote (img/social/<date>.json) and posts
the card with its caption. DRY RUN BY DEFAULT — it prints exactly what would
go out and touches nothing. Publishing requires --live.

    python3 scripts/post.py                      # dry run, today
    python3 scripts/post.py --date 2026-08-02    # dry run, a specific day
    python3 scripts/post.py --live               # actually publish

CREDENTIALS (env; all three needed for --live):
    META_PAGE_ID      the Facebook Page's numeric id
    META_PAGE_TOKEN   a PAGE access token (see below)
    META_IG_USER_ID   the Instagram professional account's IG user id

ON THE TOKEN — this is the decision that keeps the whole thing from rotting.
Instagram's own login path issues a token that expires every 60 days, which
would mean a refresh job that rewrites its own GitHub secret and a PAT scoped
to do it. Taking the Facebook-Login path instead, a Page access token derived
from a long-lived user token DOES NOT EXPIRE, and the same token authorizes
both surfaces: Page posts and Instagram publishing (via the IG account linked
to the Page). One secret, set once, no refresh machinery. Getting it:

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

WHY INSTAGRAM NEEDS A PUBLIC URL: Meta cURLs the image at publish time rather
than accepting bytes, and takes JPEG only. That is the entire reason the card
is built into the Pages deploy and this script runs after it — see
--require-live-image, which refuses to publish an image the CDN cannot serve.
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Overridable because Meta retires versions on a ~2-year clock; when this one
# goes, set META_API_VERSION rather than editing the script.
API_VERSION = os.environ.get('META_API_VERSION', 'v21.0')
GRAPH = f'https://graph.facebook.com/{API_VERSION}'

HTTP_TIMEOUT_S = 30
IMAGE_POLL_TRIES = 20
IMAGE_POLL_SLEEP_S = 15
CONTAINER_POLL_TRIES = 12
CONTAINER_POLL_SLEEP_S = 5


class PostError(RuntimeError):
    pass


# ---------- graph plumbing ----------

def _graph(path, params, method='GET'):
    """One Graph call. Raises PostError with Meta's own message on failure —
    its error bodies name the actual problem (expired token, unpermitted
    scope, unreachable media) far better than a status code does."""
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
    """Block until the card is actually served as a JPEG.

    deploy-pages returning success means the deployment is live, but the CDN
    edge can lag it by a few seconds. Instagram does not retry a media fetch —
    it just fails the container — so it is much cheaper to poll here than to
    debug a 'media could not be downloaded' after the fact.
    """
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, method='HEAD')
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
                ctype = resp.headers.get('content-type', '')
                if resp.status == 200 and 'image/jpeg' in ctype:
                    print(f'  image live ({ctype}) after {attempt} check(s)')
                    return
                last = f'status {resp.status}, content-type {ctype!r}'
        except urllib.error.HTTPError as exc:
            last = f'status {exc.code}'
        except urllib.error.URLError as exc:
            last = str(exc.reason)
        if attempt < tries:
            time.sleep(sleep_s)
    raise PostError(f'card never became publicly readable at {url} — {last}')


# ---------- the two surfaces ----------

def post_facebook(manifest, page_id, token):
    """Photo + caption in one call. `url` is the same public card Instagram
    will fetch, so the two posts can never drift apart."""
    res = _graph(f'{page_id}/photos', {
        'url': manifest['image_url'],
        'caption': manifest['caption_facebook'],
        'access_token': token,
    }, method='POST')
    post_id = res.get('post_id') or res.get('id')
    return f'https://www.facebook.com/{post_id}', post_id


def post_instagram(manifest, ig_user_id, token):
    """Two-step publish: build a media container, wait for it to finish, then
    publish it. The wait matters — publishing an IN_PROGRESS container is the
    single most common cause of a silent no-post."""
    container = _graph(f'{ig_user_id}/media', {
        'image_url': manifest['image_url'],
        'caption': manifest['caption_instagram'],
        'access_token': token,
    }, method='POST')
    creation_id = container.get('id')
    if not creation_id:
        raise PostError(f'no container id in response: {container}')

    for attempt in range(1, CONTAINER_POLL_TRIES + 1):
        status = _graph(creation_id, {
            'fields': 'status_code,status', 'access_token': token,
        })
        code = status.get('status_code')
        if code == 'FINISHED':
            break
        if code == 'ERROR':
            raise PostError(f'container failed: {status.get("status", code)}')
        if attempt == CONTAINER_POLL_TRIES:
            raise PostError(f'container stuck at {code} after '
                            f'{CONTAINER_POLL_TRIES} checks')
        time.sleep(CONTAINER_POLL_SLEEP_S)

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

def load_manifest(day):
    path = os.path.join(ROOT, 'img', 'social', f'{day}.json')
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def _preview(manifest):
    print(f'  date         {manifest["date"]}')
    print(f'  image        {manifest["image_url"]}')
    print(f'  sessions     {manifest["event_count"]} '
          f'({manifest["shown_on_card"]} on the card)')
    print(f'  cities       {", ".join(manifest["cities"]) or "—"}')
    for label, key in (('facebook', 'caption_facebook'),
                       ('instagram', 'caption_instagram')):
        print(f'\n  --- {label} caption ---')
        for line in manifest[key].splitlines():
            print(f'  | {line}')
    print()


def main():
    ap = argparse.ArgumentParser(description="Publish the day's social card.")
    ap.add_argument('--date', help='YYYY-MM-DD (default: today, Denver)')
    ap.add_argument('--live', action='store_true',
                    help='actually publish (default: dry run)')
    ap.add_argument('--require-live-image', action='store_true',
                    help='poll the public image URL before publishing')
    ap.add_argument('--allow-stale-date', action='store_true',
                    help="publish a day that isn't today (default: refuse)")
    ap.add_argument('--skip-facebook', action='store_true')
    ap.add_argument('--skip-instagram', action='store_true')
    args = ap.parse_args()

    today = datetime.now(DENVER).date().isoformat()
    day = args.date or today

    manifest = load_manifest(day)
    if manifest is None:
        # Not an error. social.py writes nothing for a day with no approved
        # sessions, and silence beats posting "nothing on tonight".
        print(f'no card for {day} — nothing to post')
        return 0

    print(f'{"PUBLISH" if args.live else "DRY RUN"} — {day}')
    _preview(manifest)

    if not args.live:
        print('dry run — nothing published. Pass --live to post.')
        return 0

    if day != today and not args.allow_stale_date:
        # Guards the obvious footgun: re-running an old workflow and blasting
        # a day that has already happened.
        raise SystemExit(f'refusing to publish {day} on {today} — '
                         f'pass --allow-stale-date if you mean it')

    page_id = os.environ.get('META_PAGE_ID', '').strip()
    token = os.environ.get('META_PAGE_TOKEN', '').strip()
    ig_user_id = os.environ.get('META_IG_USER_ID', '').strip()
    if not token or not (page_id or ig_user_id):
        raise SystemExit('META_PAGE_TOKEN and at least one of META_PAGE_ID / '
                         'META_IG_USER_ID must be set to publish')

    if args.require_live_image:
        wait_for_image(manifest['image_url'])

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
