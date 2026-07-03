---
description: How to release a new version of PGVectorRAGIndexer
---
# Release Process for PGVectorRAGIndexer

When the user asks to release a new version, follow the canonical,
battle-tested procedure in **`.claude/skills/cut-release/SKILL.md`**
(plain Markdown + shell, not Claude-specific) end to end. The agent
performs the entire process — do not just print instructions: preflight,
extra-docs sweep, `./release.sh -y <bump>`, watching ALL CI workflows on
the release commit, downloading the unsigned MSI to
`C:\Users\v_ale\Desktop\ToSign\PGVectorRAGIndexer-unsigned\`, a hard STOP
while the user signs with signtool, uploading the signed MSI back to the
GitHub release, committing the `docs/internal` version side-effect, and
verifying that ragvault.net's "Windows Installer (.msi)" button serves the
just-signed artifact (byte-size match).

Helper scripts (run these, don't re-derive their checks):

- `.claude/skills/cut-release/scripts/preflight.sh` — release gate
- `.claude/skills/cut-release/scripts/verify_release.sh vX.Y.Z` — final
  website/asset verification

The step list that used to live in this file is superseded by the skill;
its recovery notes (ghcr auth refresh, docs/internal commit) were merged
into the skill's Phase 3.
