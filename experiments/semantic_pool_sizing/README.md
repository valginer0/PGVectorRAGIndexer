# Semantic rescue-pool sizing — analysis

Scratch experiments behind the decision to **auto-size** the LanceDB semantic
candidate pool (`lancedb_semantic_candidate_pool`) instead of using a fixed
constant. Shipped in commit *"auto-size LanceDB semantic rescue pool as
sqrt(corpus)"*.

These scripts are kept for reproducibility/record. They are **not** part of the
app and are not run by CI. They need a populated LanceDB root; set `LANCE_ROOT`
or rely on the default `.codex/lancedb-smoke-data-2/lancedb` (gitignored, local).

## Background

In `lancedb_adapter.search_parent_child`, the "semantic rescue" path does a
global vector scan over all chunks and keeps the top *N* so their parent
documents become candidates in RRF fusion (rescuing docs that keyword/FTS
missed). *N* was a hardcoded `100`.

**Concern:** `100` was tuned to a tiny test corpus. *N* is "how far down the
similarity-sorted line we look." A fixed *N* covers a *shrinking fraction* of
the corpus as it grows, so semantic recall on lexically-weak docs silently
degrades at scale.

## Scripts

| script | question it answers |
|---|---|
| `pool_timing.py` | How much does a deeper scan cost? And how big is the "effective" pool under a relative score cutoff? |
| `select_opt.py` | Does selecting only `document_id` (dropping the embedding payload) make deep scans cheaper? |
| `rrf_trace.py` | Per-query trace of FTS vs vector parent ranks through RRF + spill-ratio (uses the active app config). |

## Findings (corpus: 129,189 chunks / 2,309 parent docs)

### 1. Deeper scans are NOT free — full-row latency roughly doubles 100→1000
| cap | median latency (full row) |
|----|----|
| 100 | ~300 ms |
| 200 | ~360 ms |
| 500 | ~490 ms |
| 1000 | ~610 ms |

The cost is **payload materialization** (each row drags its embedding vector),
not the ANN search itself.

### 2. Selecting only `document_id` halves the marginal cost of going deep
The rescue stage only uses `document_id` (+ implicit `_distance`). Dropping the
embedding/text payload:

| cap | full-row | id-only |
|----|----|----|
| 100 | ~300 ms | ~273 ms |
| 1000 | ~610 ms | ~365 ms |
| 100→1000 growth | **+95%** | **+34%** |

→ a deep (cap=500) id-only pool runs at ~today's cap=100 latency.

### 3. A relative score-cutoff (adaptive-k) was REJECTED
Best cosine sims on this corpus are low (~0.49–0.66), so a `score >= best*tau`
cutoff keeps only 1–3 chunks — and would **drop** exactly the low-similarity,
lexically-weak docs the rescue pool exists to save. Elegant in theory, wrong
for this mechanism when measured.

### 4. Distinct parent docs reachable vs scan depth
| scan depth | distinct parents |
|----|----|
| 100 | 46 |
| 200 | 76 |
| 500 | 169 |
| 1000 | 422 |

Downstream, only `parent_limit = max(5, top_k)` parents survive. 1000-deep →
422 candidate parents to pick ~5 from is a huge safety net, so the `cap=1000`
ceiling sacrifices almost no recall while bounding latency.

## Decision

- Scan selects **`document_id`** only (cheap depth).
- Pool = **`clamp(round(sqrt(chunk_count)), floor=100, cap=1000)`**, computed at
  search time from the live corpus (always current, no stored state).
- `√N` = sub-linear compromise: grows with the corpus, stays bounded.
- `floor`/`cap` are config knobs; an explicit integer pins a fixed pool.

## Open gap

This is a *principled* default, not a *recall-proven* one. Proving "depth X
catches the hard docs" needs a labelled query→doc ground-truth set (the MSI
validation gate) — separate, optional follow-up before any recall SLA claim.
