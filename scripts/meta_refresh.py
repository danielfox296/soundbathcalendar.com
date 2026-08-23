"""Dead Meta token? Run this. One command, everything happens.

    python3 scripts/meta_refresh.py

Facebook invalidates the Page token whenever the account password changes
(or Facebook resets the session for "security reasons"), and when that
happens the daily carousel silently stops. meta_token.py fixes it but asks
you to ferry values between three places. This wraps the whole repair:

  1. opens the Graph API Explorer for you — your ONLY job is clicking
     "Generate Access Token", approving, and pasting the token here
  2. exchanges it for the never-expiring Page token (same chain, same
     verification as meta_token.py)
  3. writes it straight into the repo's META_PAGE_TOKEN Actions secret
  4. re-runs the deploy with post_social=true so today's post goes out
     now instead of tomorrow, and watches the run until it lands

The App Secret is needed for the exchange; you paste it ONCE and it is
kept in the macOS keychain, so every later run skips that step. Tokens
are never printed, never written to disk, and never passed on a command
line — the secret goes to GitHub over stdin.
"""
import getpass
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import meta_check  # noqa: E402
import meta_token  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

APP_ID = os.environ.get('META_APP_ID', '').strip() or meta_token.DEFAULT_APP_ID
PREFERRED_IG = 'soundbathcalendar'   # pick the Page linked to this IG account
PAGE_ID = os.environ.get('META_PAGE_ID', '').strip() or '1225168530684602'

# Keychain slot for the App Secret. One paste, then never again.
KC_SERVICE = 'soundbathcalendar-meta-app-secret'

EXPLORER_URL = f'https://developers.facebook.com/tools/explorer/?app_id={APP_ID}'
SECRET_URL = f'https://developers.facebook.com/apps/{APP_ID}/settings/basic/'

WORKFLOW = 'deploy.yml'


def run(cmd, **kw):
    return subprocess.run(cmd, cwd=ROOT, **kw)


def open_in_browser(url):
    try:
        subprocess.run(['open', url], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass  # the URL is printed anyway; opening it is a convenience


# ---------- keychain ----------

def keychain_get():
    try:
        out = subprocess.run(
            ['security', 'find-generic-password', '-s', KC_SERVICE, '-w'],
            capture_output=True, text=True)
    except OSError:
        return ''
    return out.stdout.strip() if out.returncode == 0 else ''


def keychain_put(secret, announce=True):
    try:
        out = subprocess.run(
            ['security', 'add-generic-password', '-U',
             '-s', KC_SERVICE, '-a', APP_ID, '-w', secret],
            capture_output=True, text=True)
        if out.returncode == 0 and announce:
            print('  ok  App Secret saved to the keychain — future runs skip that paste')
    except OSError:
        pass  # not fatal; worst case the next run prompts again


def keychain_drop():
    subprocess.run(['security', 'delete-generic-password', '-s', KC_SERVICE],
                   capture_output=True, text=True)


# ---------- the two values ----------

def get_app_secret():
    """Keychain first; prompt (and remember) only when it is missing."""
    cached = keychain_get()
    if cached:
        print('  ok  App Secret from the keychain')
        return cached, True
    print(f'\nApp Secret needed (first run only). Opening:\n  {SECRET_URL}')
    print('App settings -> Basic -> App secret -> Show (Facebook re-asks your password).')
    open_in_browser(SECRET_URL)
    secret = getpass.getpass('Paste the App Secret (input hidden): ').strip()
    if not re.fullmatch(r'[0-9a-f]{32}', secret):
        print(f'That does not look like an App Secret '
              f'({len(secret)} chars; expected 32 lowercase hex). '
              f'Click Show first — copying the masked bullets fails.')
        sys.exit(2)
    return secret, False


def get_short_token():
    print(f'\nOpening the Graph API Explorer:\n  {EXPLORER_URL}')
    print('In that tab: check the app dropdown (top right) says "Sound Bath')
    print('Calendar Poster", click "Generate Access Token", approve, then copy')
    print('the token from the Access Token field. Permissions are already')
    print('granted — you should not need to touch them.')
    open_in_browser(EXPLORER_URL)
    short = getpass.getpass('\nPaste the token (input hidden): ').strip()
    if not short.startswith('EAA'):
        print('That does not look like a Graph access token (expected "EAA...").')
        sys.exit(2)
    return short


# ---------- token exchange (meta_token.py's chain, quiet) ----------

def mint_page_token(secret, short, secret_was_cached):
    long_lived, err = meta_token.graph('oauth/access_token', {
        'grant_type': 'fb_exchange_token',
        'client_id': APP_ID,
        'client_secret': secret,
        'fb_exchange_token': short,
    })
    if err and 'client secret' in err.lower() and secret_was_cached:
        # The cached secret went stale (the app secret itself was rotated).
        # Drop it and ask once.
        print('  ..  cached App Secret rejected — it must have been rotated')
        keychain_drop()
        secret, _ = get_app_secret()
        long_lived, err = meta_token.graph('oauth/access_token', {
            'grant_type': 'fb_exchange_token',
            'client_id': APP_ID,
            'client_secret': secret,
            'fb_exchange_token': short,
        })
    if err:
        print(f'FAIL  exchanging for a long-lived token — {err}')
        print('      Explorer tokens die fast; generate a fresh one and re-run.')
        sys.exit(1)
    user_token = long_lived.get('access_token', '')
    if not user_token:
        print('FAIL  no access_token in the exchange response')
        sys.exit(1)
    print('  ok  long-lived user token')

    accounts, err = meta_token.graph('me/accounts', {
        'fields': 'id,name,access_token,instagram_business_account{id,username}',
        'access_token': user_token,
    })
    if err:
        print(f'FAIL  listing Pages — {err}')
        sys.exit(1)
    pages = (accounts or {}).get('data', [])
    if not pages:
        # A Facebook security reset can drop the classic page-role listing
        # (/me/accounts comes back empty) while the app's granular grant on
        # the Page still stands — hit 2026-08-23. The page node still hands
        # over its token in that state, so ask it directly.
        print('  ..  /me/accounts empty — asking the page node directly')
        node, err = meta_token.graph(PAGE_ID, {
            'fields': 'id,name,access_token,'
                      'instagram_business_account{id,username}',
            'access_token': user_token,
        })
        if err or not (node or {}).get('access_token'):
            print(f'FAIL  the token can see no Pages and the page node gave '
                  f'no token — {err or "empty response"}')
            print('      Re-approve in the Explorer with the Page selected.')
            sys.exit(1)
        pages = [node]

    usable = []
    for page in pages:
        info, err = meta_token.graph('debug_token', {
            'input_token': page.get('access_token', ''),
            'access_token': user_token,
        })
        data = (info or {}).get('data', {})
        if not err and data.get('type') == 'PAGE' and data.get('expires_at') in (0, None):
            usable.append(page)
    if not usable:
        print('FAIL  no never-expiring PAGE token came back. Run meta_token.py to see why.')
        sys.exit(1)

    ig_name = lambda p: ((p.get('instagram_business_account') or {})
                         .get('username', ''))
    chosen = next((p for p in usable if ig_name(p) == PREFERRED_IG), None)
    if chosen is None and len(usable) == 1:
        chosen = usable[0]
    if chosen is None:
        print('FAIL  several Pages and none is linked to @' + PREFERRED_IG + ':')
        for p in usable:
            print(f'        {p.get("name", "?")}  IG: {ig_name(p) or "none"}')
        print('      Run meta_token.py and set the secret by hand for the right one.')
        sys.exit(1)

    ig = ig_name(chosen)
    print(f'  ok  Page token for "{chosen.get("name", "?")}"'
          f'  IG: {"@" + ig if ig else "NOT LINKED"}')
    return chosen['access_token'], secret


# ---------- GitHub: secret + repost ----------

def set_repo_secret(token):
    out = run(['gh', 'secret', 'set', 'META_PAGE_TOKEN'],
              input=token, text=True, capture_output=True)
    if out.returncode != 0:
        print(f'FAIL  gh secret set — {out.stderr.strip()}')
        print('      Is gh logged in? Try: gh auth status')
        sys.exit(1)
    print('  ok  META_PAGE_TOKEN updated on GitHub')


def repost_today():
    dispatched_at = datetime.now(timezone.utc)
    out = run(['gh', 'workflow', 'run', WORKFLOW, '-f', 'post_social=true'],
              capture_output=True, text=True)
    if out.returncode != 0:
        print(f'FAIL  dispatching the deploy — {out.stderr.strip()}')
        sys.exit(1)
    print('  ok  deploy dispatched with post_social=true — waiting for the run...')

    run_id = None
    for _ in range(12):
        time.sleep(5)
        out = run(['gh', 'run', 'list', '--workflow', WORKFLOW,
                   '--event', 'workflow_dispatch', '--limit', '1',
                   '--json', 'databaseId,createdAt'],
                  capture_output=True, text=True)
        rows = json.loads(out.stdout or '[]') if out.returncode == 0 else []
        if rows:
            created = datetime.fromisoformat(
                rows[0]['createdAt'].replace('Z', '+00:00'))
            if (created - dispatched_at).total_seconds() > -60:
                run_id = str(int(rows[0]['databaseId']))
                break
    if not run_id:
        print('  ..  could not spot the new run; check: gh run list')
        return

    print(f'  ..  watching run {run_id} (a few minutes)\n')
    watched = run(['gh', 'run', 'watch', run_id, '--exit-status'])
    if watched.returncode == 0:
        print('\nPOSTED. The card should be on instagram.com/' + PREFERRED_IG
              + ' and the Facebook Page within a minute or two.')
    else:
        print('\nThe run FAILED — the log above has the step. The usual suspect')
        print('is Meta rejecting the post; the token itself verified fine here.')
        sys.exit(1)


def main():
    print('Meta token refresh — the only manual step is one copy/paste.\n')

    # gh must be authed before we ask for anything.
    out = run(['gh', 'auth', 'status'], capture_output=True, text=True)
    if out.returncode != 0:
        print('FAIL  the gh CLI is not logged in. Run: gh auth login')
        return 1

    secret, cached = get_app_secret()
    short = get_short_token()

    print()
    token, secret = mint_page_token(secret, short, cached)

    # Belt and braces: meta_check prints its safe report (scopes, IG link,
    # expiry) without ever printing the token.
    print()
    problems, _, _ = meta_check.verify(token)
    if problems:
        print(f'\nFAIL  {len(problems)} problem(s) above — secret NOT updated.')
        print('      Missing permissions? In the Explorer add: '
              + ', '.join(meta_check.NEEDED_SCOPES) + ' and regenerate.')
        return 1

    # -U makes this an idempotent update, so it also re-caches the new value
    # after the rotated-secret retry inside mint_page_token.
    keychain_put(secret, announce=not cached)
    set_repo_secret(token)
    repost_today()
    return 0


if __name__ == '__main__':
    sys.exit(main())
