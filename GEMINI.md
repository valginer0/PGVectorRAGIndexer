# Gemini Agent Instructions — PGVectorRAGIndexer

This project keeps shared, agent-agnostic procedures in `.claude/skills/`
(plain Markdown + shell — nothing Claude-specific inside). Follow them
exactly; do not improvise a parallel process.

- **Cutting a release** → follow `.claude/skills/cut-release/SKILL.md`
  end to end, including its two mandatory STOP points (waiting for the user
  to sign the MSI, and stopping after the final report). This supersedes the
  step list formerly in `.agents/workflows/release-process.md`.

Also read `AGENTS.md` at the repo root for common repo facts, and keep
following the artifact-mirroring rule in `.agents/AGENTS.md`.
