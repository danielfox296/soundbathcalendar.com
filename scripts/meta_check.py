"""Verify a Meta token before it ever becomes a GitHub secret (CAL-25).

Run this with just a token in your hand. It discovers the two ids you need,
confirms the token is the never-expiring PAGE kind rather than a user token,
checks every permission the poster actually calls, and prints the three secret
values to paste into GitHub.

    python3 scripts/meta_check.py

It prompts for the token (hidden input, so it stays out of shell history);
META_PAGE_TOKEN is honoured if already set to a real one.

Read-only: it lists and inspects, and never publishes anything.

The one distinction this exists to catch: a long-lived USER token expires in
60 days, a PAGE token derived from one does not. They look identical when you
copy them out of the Graph API Explorer, and picking the wrong one means the
whole automation silently dies two months from now — on a Tuesday, with no
error until the workflow goes red. debug_token is what tells them apart.
"""
import getpass
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API_VERSION = os.environ.get('META_API_VERSION', 'v25.0')
GRAPH = f'https://graph.facebook.com/{API_VERSION}'
TIMEOUT_S = 30

# Everything scripts/post.py actually calls, and why.
NEEDED_SCOPES = {
    'pages_manage_posts': 'create the Facebook Page post',
    'pages_read_engagement': 'read the Page the post attaches to',
    'instagram_basic': 'resolve the linked Instagram account',
    'instagram_content_publish': 'publish the Instagram carousel',
}

OK, WARN, BAD = '  ok  ', ' warn ', ' FAIL '


def graph(path, params):
    url = f'{GRAPH}/{path.lstrip("/")}?{urllib.parse.urlencode(params)}'
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_S) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors='replace')
        try:
            err = json.loads(body).get('error', {})
            return None, err.get('message', body)
        except ValueError:
            return None, body
    except urllib.error.URLError as exc:
        return None, str(exc.reason)


def main():
    # Prompt rather than require an env var: an `export VAR='placeholder'`
    # line pasted verbatim is indistinguishable here from a real token, and
    # produces a confusing "cannot parse access token" from Meta instead of an
    # obvious local mistake. getpass keeps it out of shell history too.
    token = os.environ.get('META_PAGE_TOKEN', '').strip()
    if not token.startswith('EAA'):
        if token:
            print(f'META_PAGE_TOKEN is set but does not look like a token '
                  f'(expected it to start with "EAA") — ignoring it.\n')
        try:
            token = getpass.getpass('Page access token: ').strip()
        except (EOFError, KeyboardInterrupt):
            print('\nCancelled.')
            return 2
    if not token.startswith('EAA'):
        print('That does not look like a Graph access token.')
        return 2

    problems = []
    print(f'Checking token against Graph {API_VERSION}\n')

    # --- what kind of token is this, and when does it die? ---
    info, err = graph('debug_token', {'input_token': token, 'access_token': token})
    scopes = []
    if err:
        print(f'{WARN} debug_token unavailable ({err})')
        print('       — token type and expiry unverified; the checks below still apply')
    else:
        data = info.get('data', {})
        ttype = data.get('type', 'UNKNOWN')
        expires = data.get('expires_at', 0)
        scopes = data.get('scopes', []) or []

        if ttype == 'PAGE':
            print(f'{OK} token type is PAGE')
        else:
            print(f'{BAD} token type is {ttype}, not PAGE')
            print('       — a USER token expires in 60 days. Call /me/accounts with')
            print('         it and use the Page\'s own `access_token` instead.')
            problems.append('token is not a Page token')

        if expires in (0, None):
            print(f'{OK} never expires')
        else:
            when = datetime.fromtimestamp(expires, tz=timezone.utc)
            print(f'{BAD} expires {when:%Y-%m-%d %H:%M UTC}')
            print('       — this will stop posting on that date with no warning.')
            problems.append('token has an expiry')

        if not data.get('is_valid'):
            print(f'{BAD} token reports is_valid=false')
            problems.append('token invalid')

    # --- permissions ---
    if scopes:
        for scope, why in NEEDED_SCOPES.items():
            if scope in scopes:
                print(f'{OK} {scope}')
            else:
                print(f'{BAD} {scope} MISSING — needed to {why}')
                problems.append(f'missing {scope}')

    # --- who does this token speak for? ---
    print()
    me, err = graph('me', {'fields': 'id,name', 'access_token': token})
    if err:
        print(f'{BAD} /me failed — {err}')
        return 1
    page_id, page_name = me.get('id', ''), me.get('name', '')
    print(f'{OK} acting as: {page_name} ({page_id})')

    # A user token answers /me with a person and has no linked IG account; the
    # accounts list is the useful next step in that case.
    linked, err = graph(page_id, {
        'fields': 'instagram_business_account{id,username}', 'access_token': token,
    })
    ig_id = ig_name = ''
    if err or not (linked or {}).get('instagram_business_account'):
        print(f'{BAD} no Instagram professional account linked to this Page')
        if err:
            print(f'       — {err}')
        accounts, acc_err = graph('me/accounts', {
            'fields': 'id,name,instagram_business_account{id,username}',
            'access_token': token,
        })
        if not acc_err and (accounts or {}).get('data'):
            print('\n       Pages this token can see — use one of these ids and its')
            print('       own access_token as META_PAGE_TOKEN:')
            for row in accounts['data']:
                ig = (row.get('instagram_business_account') or {}).get('username', '—')
                print(f'         {row["id"]}  {row.get("name", "?")}  (IG: {ig})')
        problems.append('no linked Instagram account')
    else:
        ig = linked['instagram_business_account']
        ig_id, ig_name = ig.get('id', ''), ig.get('username', '')
        print(f'{OK} Instagram linked: @{ig_name} ({ig_id})')

        probe, err = graph(ig_id, {'fields': 'username,media_count',
                                   'access_token': token})
        if err:
            print(f'{BAD} cannot read the Instagram account — {err}')
            problems.append('Instagram account unreadable')
        else:
            print(f'{OK} Instagram readable ({probe.get("media_count", "?")} posts)')

    # --- verdict ---
    print()
    if problems:
        print(f'{len(problems)} problem(s) to fix before this will post:')
        for p in problems:
            print(f'  - {p}')
        return 1

    print('All checks passed. Set these three as GitHub repository secrets')
    print('(Settings -> Secrets and variables -> Actions -> New repository secret):\n')
    print(f'  META_PAGE_ID       {page_id}')
    print(f'  META_IG_USER_ID    {ig_id}')
    print('  META_PAGE_TOKEN    (the token you just checked)\n')
    print('Then: Actions -> Deploy Sound Bath Calendar -> Run workflow,')
    print('tick "Also publish the day carousel to Facebook + Instagram".')
    return 0


if __name__ == '__main__':
    sys.exit(main())
