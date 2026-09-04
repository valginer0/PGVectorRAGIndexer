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
version, footer version line, and the three `releases/download/v<ver>/...`
URLs). Check what it does NOT:

1. `OLD=$(cat VERSION)` then grep the repo for the old version string outside
   the auto-updated files:
   `grep -rn "v\?$OLD" docs/ *.md --exclude=CHANGELOG.md | grep -v -E "README|QUICK_START|DEPLOYMENT|USAGE_GUIDE"`
   and the website repo beyond index.html/package.json (e.g. `demo.html`).
   Report hits to the user; update only clear version references.
   Then sweep the website repo for ANY semver-like string, not just the old
   version — a string missed in one release never matches "the old version"
   again and stays stale forever (the footer sat at 2.13.0 this way):
   `grep -rnE '[Vv]ersion [0-9]+\.[0-9]+\.[0-9]+|v[0-9]+\.[0-9]+\.[0-9]+' index.html demo.html`
   Flag any match that is not the NEW version.
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

**The script now gates the tag on CI.** It pushes the release commit, waits
for every workflow on that commit to finish, and pushes the tag ONLY if they
all pass (40-minute ceiling). So expect release.sh to sit for ~10 minutes
after the Docker push - that is the gate, not a hang. If CI is red it exits
without pushing the tag and prints the two recovery options; the local tag
still exists, so fix the failure and either `git tag -d v<ver>` and re-run, or
push the tag deliberately. `--skip-ci-gate` bypasses it for an emergency
release when CI itself is broken.

This exists because v2.17.0 shipped a default install that 401'd against its
own machine: the tag went out seconds after the commit, so the suite that
would have caught it finished after the release was already public.

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
3. **Check ALL runs on the release commit**, not just the installer. The gate
   in release.sh already required these to be green before it pushed the tag,
   so this is a confirmation rather than a discovery - but the tag-triggered
   installer build runs AFTER the gate and is not covered by it:
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

## Phase 6b — Fresh-install validation (REQUIRED; the CI gate cannot cover it)

The gate in release.sh waits for workflows on the release *commit*. The MSI is
built by the tag-triggered workflow, from a tree whose `DEFAULT_REPO_REF` that
workflow rewrites to the tag — so the artifact customers install is produced
*after* the gate has already passed and is never exercised by it. Nothing
automated tests what a customer receives. This step is that test.

Do it with the **downloaded release MSI**, never a local build: a locally
built installer carries the unpatched `DEFAULT_REPO_REF = "main"` and
exercises a different code path.

1. Install the signed MSI from the release page on a Windows machine.
2. Let it complete its Docker setup, then confirm the backend came up on
   loopback and answers WITHOUT a key (single-machine default):
   - `docker ps` shows `127.0.0.1:8000->8000/tcp`, not `0.0.0.0:8000`
   - `curl http://127.0.0.1:8000/documents` returns 200, not 401
3. Open the desktop app in **Local (Docker)** mode and confirm it loads
   documents. The API-key field is disabled in that mode, so a backend that
   demands a key leaves the app with no way to connect — this is exactly how
   v2.17.0 shipped.
4. Only after this passes: announce the release.

**What counts as having run it.** The user installing the downloaded MSI and
reporting the app works IS this phase - don't ask for a ceremonial re-run. The
three checks can be evidenced from machine state after the fact:

- `docker ps` shows the app on `127.0.0.1:8000->8000/tcp` and the release's
  image tag,
- `curl http://127.0.0.1:8000/documents` returns 200,
- `netstat.exe -ano | grep 127.0.0.1:8000` shows an ESTABLISHED connection
  from a `python.exe` in the Console session - that is the desktop app.

Record the evidence in the final report rather than re-running the install,
AND append a dated result row to `docs/RELEASE_VALIDATION.md` - that file is
the durable record, and it is the form diligence asks for: not "we test our
releases" but "here is the check, and here is the result for this one".

If it fails, the tag is already public. Annotate the release page with a
known-issue callout pointing at the fix (see what v2.17.0 carries), and cut
the patch release rather than leaving the latest release broken.

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
no version bumps elsewhere) unless asked. If Phase 6b has not been run, say so
explicitly in the report: the release is published but unvalidated against the
artifact customers actually receive.
