---
name: cut-release
description: Cut a PGVectorRAGIndexer release end-to-end (release script, CI MSI build, signing stop, signed upload, ragvault.net verification). Use when the user asks to release/ship a new version.
---

# Cut a Release (pointer)

The canonical, battle-tested procedure lives in this repo at
**`.claude/skills/cut-release/SKILL.md`** (plain Markdown + shell, not
Claude-specific). Read that file and follow it end to end. Its two STOP
points are mandatory: wait for the user to sign the MSI with signtool, and
stop after the final report. Run its helper scripts rather than re-deriving
their checks:

- `.claude/skills/cut-release/scripts/preflight.sh`
- `.claude/skills/cut-release/scripts/verify_release.sh vX.Y.Z`

Do not copy the procedure into this file — one canonical copy prevents
drift, and it is version-controlled with the release tooling it drives.
