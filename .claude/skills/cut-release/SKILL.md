---
name: cut-release
description: Cut a PGVectorRAGIndexer release end-to-end — release.sh, extra-docs sweep, CI MSI build, download for signing, wait for the user to sign, upload the signed MSI, and verify ragvault.net serves the new version. Use when the user asks to cut/prepare/ship a release. Args: [major|minor|patch|x.y.z] (default patch), optional -y to skip release.sh confirmation.
---

# Cut a Release

Follow these phases **in order**. Two hard STOP points are marked — end your
turn there and wait for the user. Never skip verification steps.

Parse `$ARGUMENTS`: bump type `major|minor|patch` or explicit `x.y.z`
(default `patch`); pass `-y` through to release.sh only if given.

## Phase 1 — Preflight (all must pass before anything else)

1. Run `<skill-base-dir>/scripts/preflight.sh` — checks both repos (main
   branch, clean, synced), gh auth, Docker, and prints VERSION + last tag.
   Any `[FAIL]` line blocks the release. For dirty-tree failures, surface the
   offending files to the user and let THEM decide (commit / stash /
   .gitignore) — never discard anything yourself. Note: release.sh hard-fails
   on **untracked** files too.
2. Full test suite is green (release.sh runs tests, but a pre-check fails
   faster):
   `source venv/bin/activate && python -m pytest tests/ --ignore=tests/test_upload_endpoint.py --ignore=tests/test_web_ui.py --ignore=tests/test_web_ui_integration.py -q`

## Phase 2 — Extra-docs sweep (things release.sh does NOT update)

`scripts/update_version_docs.py` (invoked by release.sh) already handles:
README.md, QUICK_START, DEPLOYMENT, USAGE_GUIDE, CHANGELOG.md (promotes
`[Unreleased]`), and in the website repo package.json + index.html (hero
version and the three `releases/download/v<ver>/...` URLs). Check what it
does NOT:

1. `OLD=$(cat VERSION)` then grep the repo for the old version string outside
   the auto-updated files:
   `grep -rn "v\?$OLD" docs/ *.md --exclude=CHANGELOG.md | grep -v -E "README|QUICK_START|DEPLOYMENT|USAGE_GUIDE"`
   and the website repo beyond index.html/package.json (e.g. `demo.html`).
   Report hits to the user; update only clear version references.
2. CHANGELOG.md must have a meaningful `[Unreleased]` section describing this
   release. If it is empty/missing, draft entries from
   `git log --oneline <last-tag>..HEAD` and show the user before committing.
3. If the release ships a user-visible feature the website feature list does
   not mention, DRAFT a feature card yourself in the site's existing style
   (benefit-first, plain language — read the neighboring `feature-card`
   blocks in index.html and match their tone/markup), add it in a sensible
   position, and show the user what you added in your next message. They can
   veto or reword; do not block the release waiting for approval.

Commit any resulting edits (both repos) BEFORE running release.sh — it
requires a clean tree.

## Phase 3 — Run the release script

- Backend/code changes → `./release.sh -y <bump>` (builds + pushes Docker).
- Docs-only or desktop-only → `./release-lite.sh -y <bump>` (no Docker).
Always pass `-y`: the script's interactive prompt cannot be answered from the
agent shell, and this skill's Phases 1–2 already perform the checks that
prompt exists for. Run it in the background (the Docker build can exceed the
foreground command timeout), capturing output with `> log 2>&1` — NEVER
`| tee` (the pipe reports tee's exit code and masks a script failure).
When in doubt, use full release.sh. It: bumps VERSION, updates docs, runs
tests, builds+pushes the image, commits, commits+pushes the website repo,
tags `vX.Y.Z`, pushes main + the tag.

**Do not trust the exit code alone.** After the script finishes, verify the
tag actually exists and is pushed: `git tag --points-at HEAD` must show the
new tag, and the release commit must be on origin/main. Record it as `$TAG`.

**If the script dies partway** (e.g. Docker credential failures — a known
one: Rancher Desktop re-adding `"credsStore": "wincred.exe"` to
~/.docker/config.json, which WSL cannot exec; fix by backing up the file and
removing that key, the inline ghcr auth suffices), the version bump is left
UNCOMMITTED across the main, website, and docs/internal repos. Stash all
three (`git stash push -m "aborted release.sh run"`) so VERSION returns to
the pre-bump value, fix the cause, verify with preflight.sh, and re-run —
otherwise the next run double-bumps.

**If ghcr.io auth itself is expired/insufficient**:
`gh auth refresh -h github.com -s write:packages` then
`gh auth token | docker login ghcr.io -u valginer0 --password-stdin`.

**After the script succeeds — docs/internal side-effect**:
update_version_docs.py also rewrites version references inside
`docs/internal/` (a SEPARATE private repo the script does not commit).
Commit and push it explicitly:
`cd docs/internal && git add -A && git commit -m "chore: version reference bump to $TAG (release tooling)" && git push`
(then `cd` back — the shell cwd persists and later `gh`/`git` commands
would silently target the wrong repo).

## Phase 4 — CI: the MSI build AND every other workflow

The tag push triggers the Windows installer workflow; the release commit on
main triggers the full workflow matrix (macOS compatibility, Windows tests,
split-backend E2E, fresh-image smoke, installer verify, ...).

1. Find the tag's installer run: `gh run list --limit 8` (match the tag).
2. Wait with `gh run watch <run-id> --exit-status` — NEVER a sleep loop.
3. **Check ALL runs on the release commit**, not just the installer:
   `gh run list --commit "$(git rev-parse HEAD)"` — every workflow must end
   `success`. A red non-installer workflow (e.g. the macOS no-database run)
   means the release commit shipped a regression CI would have caught; fix
   it on main immediately even though the tag is already cut, and say so in
   the final report. Known trap: new DB-dependent tests must carry
   `pytest.mark.database` (and ride the `setup_test_database` skip guard) or
   the macOS "No Database" job fails.
4. If the installer run fails, stop and report; do not proceed to download.

## Phase 5 — Download the unsigned MSI for signing

```bash
gh release download "$TAG" --pattern 'PGVectorRAGIndexer.msi' \
  --output '/mnt/c/Users/v_ale/Desktop/ToSign/PGVectorRAGIndexer-unsigned/PGVectorRAGIndexer.msi' \
  --clobber
```
Record its size and mtime (`stat`), then tell the user the file is ready to
sign with signtool (signing happens in place).

**STOP #1 — end your turn.** Wait until the user explicitly says the MSI is
signed. Do not poll, do not proceed on silence.

## Phase 6 — Upload the signed MSI

1. Sanity-check the same path: mtime must be newer and size different
   (a signature adds bytes) vs. the values recorded in Phase 5. If the file
   looks unchanged, ask the user whether the signed file is elsewhere —
   don't upload an unsigned binary over the release.
2. `gh release upload "$TAG" '/mnt/c/Users/v_ale/Desktop/ToSign/PGVectorRAGIndexer-unsigned/PGVectorRAGIndexer.msi' --clobber`
3. Verify: `gh release view "$TAG" --json assets` — one PGVectorRAGIndexer.msi,
   size matching the signed file.

## Phase 7 — Verify the website points at the signed MSI and is live

Run `<skill-base-dir>/scripts/verify_release.sh "$TAG"`. It checks:

1. **Website repo**: MSI button href is `releases/download/$TAG/...`, hero
   badge shows `$TAG`, package.json matches, and no stale version strings
   remain in index.html (known past bug: hero vs footer vs package.json
   drift).
2. **Live site**: https://www.ragvault.net shows `$TAG` and the
   "Windows Installer (.msi)" button href contains `$TAG`.
3. **Asset**: the button's GitHub URL serves Content-Length equal to the
   local signed MSI's size — proving the button serves the signed artifact,
   not a stale or unsigned one.

If only the **live** checks fail right after release, the Vercel/GitHub Pages
deploy is probably still running — rerun the script after a few minutes
rather than editing anything. Any repo or asset `[FAIL]` must be fixed.

## Phase 8 — Final report

Summarize: new version, release.sh output highlights, CI run result, signed
MSI uploaded (size), website live checks (all three: repo, live page, asset).
Remind about anything deferred from Phase 2.

**STOP #2** — the release is done; take no further action (no announcements,
no version bumps elsewhere) unless asked.
