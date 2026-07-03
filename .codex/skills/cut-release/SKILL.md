---
name: cut-release
description: Cut a PGVectorRAGIndexer release end-to-end. This is a pointer stub — the canonical procedure lives in .claude/skills/cut-release/SKILL.md.
---

# Cut a Release (pointer)

Follow **`.claude/skills/cut-release/SKILL.md`** in this repo, end to end —
it is plain Markdown + shell, nothing Claude-specific. Its two STOP points
(waiting for the user to sign the MSI; stopping after the final report) are
mandatory. Run its helper scripts rather than re-deriving their checks:

- `.claude/skills/cut-release/scripts/preflight.sh`
- `.claude/skills/cut-release/scripts/verify_release.sh vX.Y.Z`

Do not copy the procedure here — this stub exists only so Codex can find it
via `.codex/skills/`; keeping one canonical file prevents drift.
