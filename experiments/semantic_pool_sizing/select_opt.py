"""
Experiment 2: does selecting ONLY document_id (dropping the embedding/text
payload) collapse the cost of a deep rescue scan?

Compares full-row materialization vs id-only at each cap on the 129k corpus.
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
TRIALS = 7
QUERIES = [
    "referencing and proving the origin of model output",
    "how do vector databases store embeddings",
    "fine tuning large language models on custom data",
]

db = lancedb.connect(LANCE_ROOT)
chunks = db.open_table("document_chunks")
model = get_embedding_service()
print(f"Corpus: {chunks.count_rows():,} chunks\n")


def scan_full(qv, cap):
    return (chunks.search(qv, vector_column_name="embedding")
                  .metric("cosine").limit(cap).to_arrow().to_pylist())


def scan_ids(qv, cap):
    return (chunks.search(qv, vector_column_name="embedding")
                  .metric("cosine").limit(cap)
                  .select(["document_id"])
                  .to_arrow().to_pylist())


def median_ms(fn, qv, cap):
    ts = []
    for _ in range(TRIALS):
        t0 = time.perf_counter()
        fn(qv, cap)
        ts.append((time.perf_counter() - t0) * 1000)
    return statistics.median(ts)


for q in QUERIES:
    qv = model.encode(q)
    scan_full(qv, max(CAPS)); scan_ids(qv, max(CAPS))   # warmup
    print(f"QUERY: {q!r}")
    print(f"  {'cap':>5} {'full-row ms':>12} {'id-only ms':>12} {'speedup':>9}")
    for cap in CAPS:
        full = median_ms(scan_full, qv, cap)
        ids = median_ms(scan_ids, qv, cap)
        print(f"  {cap:>5} {full:>12.2f} {ids:>12.2f} {full/ids:>8.2f}x")
    # sanity: id-only still returns document_id + _distance
    sample = scan_ids(qv, 5)
    print(f"  (id-only row keys: {sorted(sample[0].keys())})\n")
