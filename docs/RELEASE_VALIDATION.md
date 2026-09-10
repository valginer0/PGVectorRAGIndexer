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

### v2.17.2 — PASSED, 2026-09-10

**Tested on an UPGRADED install, not a fresh one.** Read that caveat with the
result: it is stronger evidence in one direction and no evidence in another.
This release fixes a bug that only fires on a *new* database, so a machine that
already has data cannot reproduce the condition being fixed. What this row
proves is that the migration path preserved a real 2,367-document database and
that the normal install still works. The fresh-install half is evidenced
separately, below.

#### The three standard conditions — observed, not inferred

Installed from the **signed MSI downloaded from the v2.17.2 release page**.

| # | Observed |
|---|---|
| 1 | Both services bound loopback-only; app on `ghcr.io/valginer0/pgvectorragindexer:2.17.2` |
| 2 | `GET /documents` → **200** with no `X-API-Key` header, returning **2,376 documents** |
| 3 | Desktop app connected in Local (Docker) mode; a reindex ran to completion against the upgraded stack |

#### The upgrade preserved real data

Measured on the author's own stack before and after the upgrade to 2.17.2:

| | Before | After upgrade | After reindex |
|---|---|---|---|
| Documents | 2,367 | **2,367** | 2,376 |
| Chunks | 129,918 | **129,918** | 130,182 |

No recovery was attempted and no backup was restored — the correct behaviour for
a database that is fine, and the single most important check for a release that
changes the recovery path.

`/ready`, new in this release, returned **503** while the embedding model loaded
and **200** once ready; `docker ps` reported `healthy` via the new probe
`requests.get('/ready').raise_for_status()`.

#### Indexing run, 2026-09-10 21:11:04–21:13:51 UTC

| | |
|---|---|
| Wall clock | **167 s** |
| Files scanned | **287** |
| Indexed | 9 added, 5 updated (**264 chunks**) |
| Not indexed | 273 |
| Per indexed document | **7.0 s average** (range 1.4–41.0 s, n=14) |

The 273 are content-extraction outcomes, not code failures, and all three
classes are expected for this corpus:

| Class | Files |
|---|---|
| `encrypted_pdf` (password-protected) | 261 |
| `no_content_loaded` (empty file) | 8 |
| `no_text_in_word_doc` (scanned/imageonly) | 4 |

**This is not a throughput benchmark.** 95% of the scanned files failed fast on
extraction, so the file-per-second figure for this run (1.7/s) measures how
quickly encrypted PDFs are rejected, not how quickly documents are indexed. The
usable number is the **7.0 s per document actually indexed**, and even that is
n=14. A full folder pass over indexable content is still the missing
measurement — see the peak-RAM gap, which is also unmeasured.

#### The fresh-install half, evidenced separately

Run before release against a throwaway stack with an empty backups directory:

| | v2.17.1 (published image) | v2.17.2 |
|---|---|---|
| Tables in `public` after first start | **0** | **17** |
| `DATA LOSS DETECTED` in the log | yes, falsely | no |

Now covered on every commit by the `first-run-schema-survives` CI job, which
starts the stack with no out-of-band `alembic upgrade head` — the step that made
every other job blind to this.

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
