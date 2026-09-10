# Release validation record

Automated CI proves the code. This file records the check that CI *cannot*
perform: that the artifact a customer downloads and installs actually works.

## Why this file exists

Two properties of the build make "the tests passed" insufficient:

1. **The MSI is built from its tag, not from `main`.** The installer workflow
   rewrites `DEFAULT_REPO_REF = "main"` to the tag before packaging, so a
   released installer checks out its own tag's tree. A fix on `main` does not
   reach MSI users until a new tag is cut.
2. **The MSI is built by the tag-triggered workflow**, which by definition runs
   after the release commit's CI has passed. The gate in `release.sh` blocks a
   tag until every workflow on the release commit is green, but no automated
   job exercises the installer that tag then produces.

v2.17.0 shipped past both: a default install returned `401` to its own machine,
and the desktop app's Local (Docker) mode — where the API-key field is disabled
— had no way to connect at all.

## The check

Run it against the **downloaded release MSI**, never a local build (a local
build carries the unpatched `main` ref and exercises a different path).

| # | Condition | How to evidence it |
|---|---|---|
| 1 | The install runs the release's own image, published on loopback | `docker ps` shows `<image>:<version>` and `127.0.0.1:8000->8000/tcp`, not `0.0.0.0:8000` |
| 2 | An authenticated endpoint answers **without** a key | `curl http://127.0.0.1:8000/documents` returns `200`, not `401` |
| 3 | The desktop app connects in Local (Docker) mode | `netstat -ano \| findstr 127.0.0.1:8000` shows an ESTABLISHED connection from a `python.exe` in the Console session |

Conditions 1 and 2 are a pair: the install needs no API key precisely because
nothing off the machine can reach it. Either one alone is a defect — condition 2
without condition 1 is an unauthenticated API on the network.

## Results

### v2.17.2 — PARTIAL, 2026-09-10

**Docker path: PASSED on real data. MSI path: NOT YET RUN.**

This release fixes a bug in which a **fresh** install destroyed its own schema
on first start, so validation has two halves and neither substitutes for the
other: does a new install now survive, and does an existing one still work.

**Half 1 — the fresh-install path, verified before release.** Run against the
*published* v2.17.1 image and repeated on the fix, on a throwaway stack with an
empty backups directory:

| | v2.17.1 (published) | v2.17.2 |
|---|---|---|
| Tables in `public` after first start | **0** | **17** |
| `DATA LOSS DETECTED` in the log | yes, falsely | no |

Now covered on every commit by the `first-run-schema-survives` CI job, which
starts the stack with no out-of-band `alembic upgrade head` — the step that made
every other job blind to this.

**Half 2 — an existing install with real data, on the author's own stack.**
The most important check for a fix that touches recovery: it must not act on a
database that is fine.

| # | Observed |
|---|---|
| 1 | `vector_rag_app \| ghcr.io/valginer0/pgvectorragindexer:2.17.2 \| 127.0.0.1:8000->8000/tcp` |
| — | **2,367 documents / 129,918 chunks — unchanged.** No recovery attempted, no backup restored |
| — | `/health` → `healthy`, database `healthy` |
| — | `/ready` → **503** while the embedding model loaded, **200** once ready |
| — | `docker ps` health → `healthy`, via the new probe `requests.get('/ready').raise_for_status()` |

**Not yet done: conditions 2 and 3 from the standard list**, which need the
signed MSI installed on Windows — a key-free `GET /documents`, and the desktop
app connecting in Local (Docker) mode. **This release is published but not
validated against the artifact a customer receives.**

Note for whoever runs it: a machine with an existing populated database
**cannot** reproduce the first-run condition. It validates that the MSI path
still works normally, which is a different claim from the one in half 1.

### v2.17.1 — PASSED, 2026-09-03

Installed from the signed MSI downloaded from the v2.17.1 release page.

| # | Observed |
|---|---|
| 1 | `vector_rag_app \| ghcr.io/valginer0/pgvectorragindexer:2.17.1 \| 127.0.0.1:8000->8000/tcp` |
| 2 | `GET /documents -> 200` with no `X-API-Key` header sent |
| 3 | `TCP 127.0.0.1:8000 127.0.0.1:53754 ESTABLISHED 38972` — PID 38972 is `python.exe` in the Console session, the desktop app |

Condition 3 is the one that matters most for this release: it is the exact path
that was dead in v2.17.0.

### v2.17.0 — FAILED (retrospective)

Not run at the time; the defect was found afterwards. Recorded here because the
absence of this check is why it shipped.

| # | Would have observed |
|---|---|
| 1 | `0.0.0.0:8000->8000/tcp` — published to every interface |
| 2 | `GET /documents -> 401 AUTH_2001` |
| 3 | No connection possible; the desktop app's Local mode disables the API-key field |

The release page for v2.17.0 carries a known-issue callout pointing at v2.17.1.
