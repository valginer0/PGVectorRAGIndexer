# Security Audit Log

A durable record of security findings against this repository and how each
one actually resolved — kept in git so a **closed** finding is not re-opened
from scratch months later by someone (or some agent) reading only a commit
message.

Add an entry when a security question is investigated, whether or not it
turns out to be real. Always record how to re-verify the conclusion.

---

## 2026-08-26 — `.env.neon-demo` committed to a public repo — NOT AN INCIDENT

**Status: closed, verified twice. No credential rotation is or was required.**

### What happened

`.env.neon-demo` was swept into commit `873112e` (2026-02-21, "chore: release
v2.6.2") by a broad `git add`, and stayed in a public repository until it was
removed in `95fc792` (2026-08-26). The `.gitignore` rule at the time was a
bare `.env`, which does not match `.env.*` — that is how it slipped through.

### What was actually in it

Both secret-bearing fields were the literal placeholder string `REDACTED`:

| Field | Value |
|---|---|
| `POSTGRES_PASSWORD` | literal `REDACTED` |
| `STRIPE_WEBHOOK_SECRET` | literal `REDACTED` |
| `DB_HOST`, `DB_PORT`, `POSTGRES_USER`, `POSTGRES_DB`, `DB_SSLMODE` | real, but non-secret connection metadata |

A hostname, port, username, database name and SSL mode are not exploitable
without a password. **No working credential was ever present in git history**,
so there was nothing to rotate — for the database or for Stripe.

### ⚠️ The trap: `95fc792`'s commit message is wrong

That commit message reads *"(Neon Postgres credentials + Stripe webhook
secret) … Rotate both credentials."* It was written **before** anyone opened
the file, during the initial alarmed assessment, and was never corrected —
a pushed commit message cannot be edited without rewriting public history.

This has already caused one false alarm on 2026-08-27, when the message was
taken at face value and the "leak" was reported to the user a second time.
**Do not re-raise this finding from that commit message.** Re-verify instead.

### How to re-verify (30 seconds)

```bash
# 1. What was actually in the file — expect two literal "REDACTED" values
git show 873112e:.env.neon-demo

# 2. Every commit that ever touched it — expect exactly two (add, remove)
git log --all --oneline -- .env.neon-demo

# 3. Any real Stripe webhook secret anywhere in history — expect no output
git log --all --oneline -S'whsec_'
```

The same check in the website repo returns only `whsec_fake…` (a test
fixture) and an `.env.example` placeholder.

### Fixed alongside

`.gitignore` was broadened from `.env` to `.env*` (keeping `.env.example`
tracked), so no `.env.<variant>` can be committed by accident again.

### Residual, accepted

The demo Neon endpoint's hostname, username and database name are public in
history forever. Not exploitable without a password. The demo project itself
was retired on 2026-08-27 (see `c955f7a`), so the endpoint is moot.
