# Working in this repo

Static site for soundbathcalendar.com. `python3 build.py` (stdlib-only) regenerates every page from `_src/` + `data/`. Generated output (`event/`, `operator/`, `venue/`, `practitioner/`, the city dirs, `*.ics`, `feed.xml`, `sitemap.xml`, most top-level page dirs) is committed, but CI rebuilds it all from source on every deploy (`.github/workflows/deploy.yml` → GitHub Pages) — so local generated churn is harmless and never worth "cleaning up". Source is `_src/`, `scripts/`, `build.py`, root `styles.css`, and the static root files; `data/*.json` are committed fetch caches that builds refresh (live feeds are truth, not these).

## Parallel sessions: one checkout, many Claudes

Daniel often fires several Claude sessions at once, and they all resolve to this one directory — meaning the main checkout and its ONE git index are shared. On 2026-07-24 two sessions interleaved live edits, staged files, and builds here, each seeing the other's half-done work as its own. The rules below exist so that never happens again.

### Rule 1 — ticket work happens in a worktree, not here

If your session will edit files in this repo, your first repo action is to enter a worktree (the EnterWorktree tool, or `git worktree add`). Worktrees live under `.claude/worktrees/<name>/` with their own index and HEAD, so sessions cannot interfere. Do all edits, staging, commits, and `build.py` runs inside the worktree.

Landing from a worktree:

1. `git fetch origin`, rebase your branch onto `origin/main`.
2. Resolve conflicts in source files only. For conflicts in generated files, never hand-merge — take either side, rerun `python3 build.py`, and commit the regenerated output.
3. Merge to main and push promptly. Origin is the only durable truth.

### Rule 2 — if you must touch the main checkout, assume you are not alone

- Unexpected `git status` entries are probably another session's live work, not corruption. Coordinate (cross-session message) before touching shared files.
- Banned in the main checkout: `git checkout -- .`, `git restore .`, `git reset --hard`, `git clean`, `git stash` — any blanket revert or stash can destroy another session's uncommitted work. Equally: don't run `build.py` here unless you know no other session is mid-work, because it rewrites every generated file under them.
- Stage exact paths only, and commit with `git commit -m "…" -- <paths>` — it commits only those paths no matter what else is staged, and leaves other sessions' staged entries untouched. If you use plain `git commit`, re-verify `git diff --cached --name-only` immediately first; the shared index can change between your add and your commit.
- Weird build output (wrong counts, impossible timestamps) → another session probably built here; rebuild yourself before debugging your code.

### Rule 3 — iCloud syncs this folder, including .git

This repo currently sits inside iCloud's Desktop & Documents sync scope. Expect its artifacts: empty directories named like `<slug> 2` and files like `.git/index 2` — iCloud conflict copies, never git's doing. Treat any `<name> 2` path as garbage: never read one as data, never commit one. If tracked files look silently reverted to older content, suspect an iCloud restore and check origin before debugging.
