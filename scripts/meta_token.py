"""Turn a short-lived Graph Explorer token into the never-expiring Page token.

Run this once, in YOUR OWN terminal, right after generating a user token in
the Graph API Explorer. It does both exchanges, then verifies the result
really is the non-expiring kind before handing it to you.

    python3 scripts/meta_token.py

It prompts for the App Secret and the short-lived token rather than reading
them from argv or the environment, so neither value lands in your shell
history, in a file, or in any log. Paste each when asked. (Env vars are still
honoured if set, for non-interactive use.)

WHY THIS EXISTS RATHER THAN TWO CURL COMMANDS. The Explorer offers a "Get Page
Access Token" shortcut, and it is a trap: the Page token it hands back inherits
the life of the SHORT-lived user token it came from. You get something that
looks right, works all afternoon, and then stops. The never-expiring Page token
only exists at the end of a specific chain —

    short user token -> LONG-LIVED user token -> Page token

— and every hop has to happen in that order. Chaining it by hand means pasting
one opaque EAA... string into the next command twice, where a truncated paste
produces a token that fails much later and for reasons that look unrelated.
So the chain runs here, and the last step is debug_token asserting `type` is
PAGE and `expires_at` is 0. If that assertion fails, this prints nothing you
could mistakenly save.

OUTPUT IS SENSITIVE. It prints a live Page access token. Do not paste this
output into a chat, an issue, or a commit. (scripts/meta_check.py is the one
that is safe to share — it reports on a token without ever printing it.)
"""
import getpass
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_APP_ID = '1973127126520036'   # Sound Bath Calendar Poster

API_VERSION = os.environ.get('META_API_VERSION', 'v25.0')
GRAPH = f'https://graph.facebook.com/{API_VERSION}'
TIMEOUT_S = 30


def graph(path, params):
    url = f'{GRAPH}/{path.lstrip("/")}?{urllib.parse.urlencode(params)}'
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_S) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors='replace')
        try:
            return None, json.loads(body).get('error', {}).get('message', body)
        except ValueError:
            return None, body
    except urllib.error.URLError as exc:
        return None, str(exc.reason)


def main():
    app_id = os.environ.get('META_APP_ID', '').strip() or DEFAULT_APP_ID
    # getpass, not input(): these are live credentials, and echoing them to a
    # terminal is how they end up in a screenshot or a scrollback buffer.
    secret = os.environ.get('META_APP_SECRET', '').strip()
    short = os.environ.get('META_SHORT_TOKEN', '').strip()
    try:
        if not secret:
            secret = getpass.getpass(
                'App Secret (App settings -> Basic -> App Secret -> Show): ').strip()
        if not short:
            short = getpass.getpass(
                'Short-lived token (from the Graph API Explorer): ').strip()
    except (EOFError, KeyboardInterrupt):
        print('\nCancelled — nothing was sent anywhere.')
        return 2
    if not secret or not short:
        print('Both the App Secret and the short-lived token are required.')
        return 2

    # Shape check before spending a round trip. A Meta App Secret is exactly
    # 32 lowercase hex characters. The overwhelmingly common mistake is
    # grabbing the "Instagram app secret" off the Instagram use-case page, or
    # copying the masked bullets without clicking Show first — both fail this.
    if not re.fullmatch(r'[0-9a-f]{32}', secret):
        print(f'That does not look like an App Secret '
              f'({len(secret)} chars; expected 32 lowercase hex).\n')
        print('  - It must come from App settings -> Basic -> App secret -> Show')
        print('    (Meta re-prompts for your Facebook password to reveal it).')
        print('  - It is NOT the "Instagram app secret" shown on the Instagram')
        print('    use-case page. That is a different value and will be rejected.')
        print('  - Clicking Show is required; copying the masked bullets fails.')
        return 2
    if not short.startswith('EAA'):
        print(f'That does not look like a Graph access token '
              f'(expected it to start with "EAA").')
        return 2

    print(f'\nApp {app_id}, Graph {API_VERSION}\n')

    # 1. short-lived user token -> long-lived user token (~60 days)
    long_lived, err = graph('oauth/access_token', {
        'grant_type': 'fb_exchange_token',
        'client_id': app_id,
        'client_secret': secret,
        'fb_exchange_token': short,
    })
    if err:
        print(f'FAIL  exchange for a long-lived user token — {err}')
        if 'client secret' in err.lower():
            # Meta validates the secret before it even looks at the token, so
            # this error never means the token is the problem.
            print('\n      This is the App Secret specifically — the token is fine.')
            print('      Take it from App settings -> Basic -> App secret -> Show,')
            print('      NOT the "Instagram app secret" on the Instagram use-case')
            print(f'      page. Check it belongs to app {app_id}.')
        else:
            print('      The short token may be expired — Explorer tokens are')
            print('      short-lived. Generate a fresh one and re-run.')
        return 1
    user_token = long_lived.get('access_token', '')
    if not user_token:
        print(f'FAIL  no access_token in exchange response: {long_lived}')
        return 1
    print('  ok  exchanged for a long-lived user token')

    # 2. long-lived user token -> per-Page tokens (these do not expire)
    accounts, err = graph('me/accounts', {
        'fields': 'id,name,access_token,instagram_business_account{id,username}',
        'access_token': user_token,
    })
    if err:
        print(f'FAIL  listing Pages — {err}')
        return 1
    pages = (accounts or {}).get('data', [])
    if not pages:
        print('FAIL  this token can see no Pages at all.')
        print('      Re-run the consent dialog and make sure a Page is selected.')
        return 1
    print(f'  ok  {len(pages)} Page(s) visible\n')

    results = []
    for page in pages:
        page_token = page.get('access_token', '')
        ig = page.get('instagram_business_account') or {}
        # The whole point: prove it is a PAGE token with no expiry.
        info, err = graph('debug_token', {
            'input_token': page_token, 'access_token': user_token,
        })
        data = (info or {}).get('data', {})
        ttype = data.get('type', 'UNKNOWN')
        expires = data.get('expires_at', None)
        never = expires in (0, None)
        results.append({
            'name': page.get('name', '?'), 'id': page.get('id', ''),
            'token': page_token, 'ig_id': ig.get('id', ''),
            'ig_name': ig.get('username', ''),
            'ok': (not err) and ttype == 'PAGE' and never,
            'why': err or (f'type={ttype}' if ttype != 'PAGE'
                           else ('' if never else f'expires_at={expires}')),
        })

    for r in results:
        mark = '  ok  ' if r['ok'] else ' FAIL '
        ig = f'@{r["ig_name"]}' if r['ig_name'] else 'NO INSTAGRAM LINKED'
        print(f'{mark}{r["name"]}  (page {r["id"]})  IG: {ig}')
        if not r['ok']:
            print(f'       token unusable — {r["why"]}')

    usable = [r for r in results if r['ok']]
    if not usable:
        print('\nNo usable Page token produced. Nothing to save.')
        return 1

    print('\n' + '=' * 68)
    print('SENSITIVE OUTPUT — do not paste below this line into a chat.')
    print('=' * 68)
    for r in usable:
        print(f'\n--- {r["name"]} ---')
        print(f'META_PAGE_ID       {r["id"]}')
        if r['ig_id']:
            print(f'META_IG_USER_ID    {r["ig_id"]}   (@{r["ig_name"]})')
        else:
            print('META_IG_USER_ID    (none — Instagram not linked to this Page)')
        print(f'META_PAGE_TOKEN    {r["token"]}')
    print('\nSet these three as GitHub repository secrets:')
    print('  Settings -> Secrets and variables -> Actions -> New repository secret')
    print('\nThen confirm with the shareable checker:')
    print("  export META_PAGE_TOKEN='<the token above>'")
    print('  python3 scripts/meta_check.py')
    return 0


if __name__ == '__main__':
    sys.exit(main())
