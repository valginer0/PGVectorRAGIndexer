# Agent Instructions — PGVectorRAGIndexer

Shared, agent-agnostic procedures live in `.claude/skills/` as plain
Markdown + shell. Follow them exactly; do not improvise a parallel process.

## Cutting a release

When asked to release a new version, follow
**`.claude/skills/cut-release/SKILL.md`** end to end. It covers preflight
(`scripts/preflight.sh`), the extra-docs sweep, `./release.sh -y <bump>`,
watching CI, downloading the MSI to the signing folder, the hard stop while
the user signs, uploading the signed MSI, committing the `docs/internal`
side-effect, and the final website/asset verification
(`scripts/verify_release.sh`). The two STOP points in that file are
mandatory.

## Module-specific instructions

Read the local file before editing that directory — each covers gotchas
that don't fit here:

- `windows_installer/AGENTS.md` — installer API/build gotchas
- `desktop_app/AGENTS.md` — the repo-root import ban

## Durable architecture decisions

Before proposing changes to retrieval/search architecture, check
`docs/internal/` (private repo, see below) for settled decisions with
named rejected alternatives — don't re-propose something already tried:

- `SEARCH_RETRIEVAL_DECISION_SUMMARY_V0.md` — parent-child staging,
  keyword staged-not-fused (RRF fusion and native `ts_rank` both
  rejected).
- `SEMANTIC_POOL_AUTOSIZING_DECISION_V0.md` — rescue pool sizing
  (score-cutoff/adaptive-k and an uncapped pool both rejected).

## Repo facts agents commonly need

- `docs/internal/` is a separate private git repo — commit/push it
  independently; never assume the main repo's push covered it.
- The desktop app (`desktop_app/`) must not import repo-root modules
  (it is bundled separately).
- Test suite: exclude `tests/test_upload_endpoint.py`, `tests/test_web_ui.py`,
  `tests/test_web_ui_integration.py` (they hang). DB-dependent tests need
  `pytest.mark.database` or the `db_manager`/`setup_test_database` fixtures.
