"""
Experiment: cost of the global semantic-rescue scan in parent-child search.

Question 1 (timing): how much slower is the global vector scan at deeper caps
                     (100 / 200 / 500 / 1000) on a real 129k-chunk corpus?
Question 2 (effective size): if instead of a fixed cap we keep only chunks whose
                     cosine score is within tau of the best hit, how big is the
                     *effective* pool -- and is it stable as we raise the cap?

Run:  python experiments/semantic_pool_sizing/pool_timing.py
      LANCE_ROOT=/path/to/lancedb python experiments/semantic_pool_sizing/pool_timing.py
"""
import os, sys, time, statistics

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

import lancedb
from embeddings import get_embedding_service

# Point at a populated LanceDB root; override with the LANCE_ROOT env var.
LANCE_ROOT = os.environ.get(
    "LANCE_ROOT", os.path.join(REPO_ROOT, ".codex/lancedb-smoke-data-2/lancedb")
)
CAPS = [100, 200, 500, 1000]
TAUS = [0.95, 0.92, 0.90]          # keep chunks with score >= best * tau
TRIALS = 7

QUERIES = [
    "referencing and proving the origin of model output",   # the known hard case
    "how do vector databases store embeddings",
    "fine tuning large language models on custom data",
]

db = lancedb.connect(LANCE_ROOT)
chunks = db.open_table("document_chunks")
print(f"Corpus: {chunks.count_rows():,} chunks\n")

model = get_embedding_service()


def scan(query_vector, cap):
    return (chunks.search(query_vector, vector_column_name="embedding")
                  .metric("cosine")
                  .limit(cap)
                  .to_arrow().to_pylist())


def cosine_score(row):
    # LanceDB returns cosine *distance* in `_distance`; similarity = 1 - distance
    return 1.0 - row["_distance"]


for q in QUERIES:
    qv = model.encode(q)
    print("=" * 78)
    print(f"QUERY: {q!r}")

    # ---- warmup (load index pages, JIT, etc.) ----
    scan(qv, max(CAPS))

    # ---- timing sweep ----
    print(f"\n  Latency (median of {TRIALS} trials):")
    for cap in CAPS:
        times = []
        for _ in range(TRIALS):
            t0 = time.perf_counter()
            scan(qv, cap)
            times.append((time.perf_counter() - t0) * 1000)
        print(f"    cap={cap:<5d} {statistics.median(times):7.2f} ms   "
              f"(min {min(times):6.2f}, max {max(times):6.2f})")

    # ---- effective pool size under a score cutoff ----
    deep = scan(qv, max(CAPS))
    best = cosine_score(deep[0])
    print(f"\n  Best cosine sim: {best:.4f}")
    print(f"  Effective pool size (chunks kept) under score cutoff, from a {max(CAPS)} scan:")
    for tau in TAUS:
        floor = best * tau
        kept = [r for r in deep if cosine_score(r) >= floor]
        distinct_parents = len({r["document_id"] for r in kept})
        print(f"    tau={tau:.2f} (score>={floor:.4f}):  {len(kept):4d} chunks  "
              f"-> {distinct_parents:3d} distinct parent docs")
    print()
