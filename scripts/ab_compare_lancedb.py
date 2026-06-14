#!/usr/bin/env python3
"""A/B compare LanceDB vs Postgres retrieval on the same queries.

Runs each query through ``retriever.search_hybrid()`` twice on one retriever
instance -- once with ``config.retrieval.lancedb_enabled=True`` (LanceDB
parent-child) and once with ``False`` (Postgres hybrid) -- and reports where the
two engines disagree on the top *documents*.

It is read-only: it only issues searches and writes to neither store. It flips
the in-process config flag and restores it on exit.

Prereqs: Postgres backend reachable AND the LanceDB index already synced
(``scripts/sync_lancedb.py``) so both engines have the same corpus. This is the
"populated behind the flag" window -- exactly where the quality A/B belongs.

Usage:
  venv/bin/python scripts/ab_compare_lancedb.py --top-k 10 \
      --queries-json docs/internal/AB_QUERIES.json \
      --output-json docs/internal/AB_LANCEDB_VS_PG_20260604.json

Query manifest (--queries-json): a JSON list of either plain strings, or objects
``{"query": "...", "expected_files": ["...optional..."]}``. If omitted, a small
built-in set is used. ``expected_files`` (basename or path substring) is
optional and lets the harness also report per-engine ground-truth hits, not just
A/B agreement.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_QUERIES: list[dict[str, Any]] = [
    {"query": q}
    for q in (
        "EV6 charging issues",
        "12V battery test",
        "diagnostic report",
        "service bulletin",
        "power supply compatibility",
        "warranty coverage",
        "thermal runaway",
        "nominal voltage reading",
    )
]


def load_queries(path: Optional[Path]) -> list[dict[str, Any]]:
    if path is None:
        return DEFAULT_QUERIES
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise SystemExit("--queries-json must be a non-empty JSON list")
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str):
            out.append({"query": item})
        elif isinstance(item, dict) and item.get("query"):
            out.append({"query": item["query"], "expected_files": item.get("expected_files", [])})
        else:
            raise SystemExit(f"Invalid query entry: {item!r}")
    return out


def doc_level_topk(results: list[Any], k: int) -> list[dict[str, Any]]:
    """Collapse chunk results to distinct documents in rank order, top k."""
    seen: set[str] = set()
    docs: list[dict[str, Any]] = []
    for r in results:
        doc_id = str(getattr(r, "document_id", ""))
        if doc_id in seen:
            continue
        seen.add(doc_id)
        docs.append({
            "document_id": doc_id,
            "source_uri": str(getattr(r, "source_uri", "")),
            "score": float(getattr(r, "relevance_score", 0.0) or 0.0),
        })
        if len(docs) >= k:
            break
    return docs


def run_engine(retriever, set_flag, query: str, top_k: int, lancedb: bool) -> list[dict[str, Any]]:
    set_flag(lancedb)
    # Over-fetch chunks so we can resolve up to top_k *distinct* documents.
    results = retriever.search_hybrid(query, top_k=max(top_k * 3, 30))
    return doc_level_topk(results, top_k)


def expected_hit(docs: list[dict[str, Any]], expected_files: list[str]) -> Optional[bool]:
    if not expected_files:
        return None
    
    # Normalize paths: slash directions, lowercasing, and suffix stripping
    def clean_path(p: str) -> str:
        return p.replace('\\', '/').lower().strip()
        
    uris = [clean_path(d["source_uri"]) for d in docs]
    norm_expected = [clean_path(ef) for ef in expected_files]
    
    for ef in norm_expected:
        for u in uris:
            # Direct match or endswith
            if ef in u or u.endswith(ef):
                return True
            # Strip .txt suffix from expected file (e.g. .pdf.txt -> .pdf)
            if ef.endswith('.txt'):
                ef_no_txt = ef[:-4]
                if ef_no_txt in u or u.endswith(ef_no_txt):
                    return True
            # Basename match as a fallback
            ef_base = ef.split('/')[-1]
            u_base = u.split('/')[-1]
            if ef_base == u_base:
                return True
            if ef_base.endswith('.txt'):
                ef_base_no_txt = ef_base[:-4]
                if ef_base_no_txt == u_base:
                    return True
    return False


def expected_rank(docs: list[dict[str, Any]], expected_files: list[str]) -> Optional[int]:
    """1-based rank of the first document matching any expected file (None if
    no expected_files, or not present in the returned docs).

    This is the precision-confirmation metric: recall@k asks 'is the expected
    doc in the top-k', but the spill-ratio question is 'is it still rank-1'.
    """
    if not expected_files:
        return None
    for rank in range(1, len(docs) + 1):
        if expected_hit([docs[rank - 1]], expected_files):
            return rank
    return None


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--queries-json", type=Path)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--spill-ratio", type=float, default=None,
                        help="Override config.retrieval.lancedb_child_parent_spill_ratio for this run")
    args = parser.parse_args(argv)
    if args.top_k < 1:
        parser.error("--top-k must be >= 1")

    from config import get_config
    from retriever_v2 import DocumentRetriever

    config = get_config()
    original_flag = getattr(config.retrieval, "lancedb_enabled", False)
    original_spill = getattr(config.retrieval, "lancedb_child_parent_spill_ratio", 1.0)

    def set_flag(value: bool) -> None:
        config.retrieval.lancedb_enabled = value

    if args.spill_ratio is not None:
        config.retrieval.lancedb_child_parent_spill_ratio = args.spill_ratio

    queries = load_queries(args.queries_json)
    retriever = DocumentRetriever()

    per_query: list[dict[str, Any]] = []
    try:
        for spec in queries:
            q = spec["query"]
            expected_files = spec.get("expected_files", [])
            lance_docs = run_engine(retriever, set_flag, q, args.top_k, lancedb=True)
            pg_docs = run_engine(retriever, set_flag, q, args.top_k, lancedb=False)

            lance_ids = [d["document_id"] for d in lance_docs]
            pg_ids = [d["document_id"] for d in pg_docs]
            lance_set, pg_set = set(lance_ids), set(pg_ids)
            overlap = lance_set & pg_set
            union = lance_set | pg_set

            top1_agree = bool(lance_ids and pg_ids and lance_ids[0] == pg_ids[0])
            jaccard = (len(overlap) / len(union)) if union else 1.0

            per_query.append({
                "query": q,
                "lancedb_top": lance_docs,
                "postgres_top": pg_docs,
                "top1_agree": top1_agree,
                "overlap_count": len(overlap),
                "jaccard": round(jaccard, 4),
                "lancedb_only": [d["source_uri"] for d in lance_docs if d["document_id"] not in pg_set],
                "postgres_only": [d["source_uri"] for d in pg_docs if d["document_id"] not in lance_set],
                "lancedb_expected_hit": expected_hit(lance_docs, expected_files),
                "postgres_expected_hit": expected_hit(pg_docs, expected_files),
                "lancedb_expected_rank": expected_rank(lance_docs, expected_files),
                "postgres_expected_rank": expected_rank(pg_docs, expected_files),
            })
    finally:
        set_flag(original_flag)
        if args.spill_ratio is not None:
            config.retrieval.lancedb_child_parent_spill_ratio = original_spill

    n = len(per_query)
    summary = {
        "queries": n,
        "top_k": args.top_k,
        "top1_agreement_rate": round(sum(p["top1_agree"] for p in per_query) / n, 4) if n else 0.0,
        "mean_jaccard": round(statistics.mean(p["jaccard"] for p in per_query), 4) if n else 0.0,
        "full_disagreement_queries": [p["query"] for p in per_query if p["overlap_count"] == 0],
    }
    # Ground-truth tallies only if any query supplied expected_files.
    gt = [p for p in per_query if p["lancedb_expected_hit"] is not None]
    if gt:
        summary["lancedb_expected_recall"] = round(sum(bool(p["lancedb_expected_hit"]) for p in gt) / len(gt), 4)
        summary["postgres_expected_recall"] = round(sum(bool(p["postgres_expected_hit"]) for p in gt) / len(gt), 4)
        # Rank-1 precision: fraction of ground-truth queries where the expected doc is the #1 result.
        summary["lancedb_expected_rank1_rate"] = round(sum(p["lancedb_expected_rank"] == 1 for p in gt) / len(gt), 4)
        summary["postgres_expected_rank1_rate"] = round(sum(p["postgres_expected_rank"] == 1 for p in gt) / len(gt), 4)

    output = {"summary": summary, "per_query": per_query}

    print("=== LanceDB vs Postgres A/B (top documents) ===")
    print(f"queries={n}  top_k={args.top_k}  "
          f"top1_agreement={summary['top1_agreement_rate']}  mean_jaccard={summary['mean_jaccard']}")
    for p in per_query:
        flag = "AGREE " if p["top1_agree"] else "DIFFER"
        print(f"[{flag}] '{p['query']}'  overlap={p['overlap_count']}/{args.top_k}  jaccard={p['jaccard']}")
        if not p["top1_agree"]:
            lance1 = p["lancedb_top"][0]["source_uri"] if p["lancedb_top"] else "(none)"
            pg1 = p["postgres_top"][0]["source_uri"] if p["postgres_top"] else "(none)"
            print(f"          top-1  LanceDB: {lance1}")
            print(f"          top-1  Postgres: {pg1}")
    if summary["full_disagreement_queries"]:
        print(f"\nFull-disagreement (0 overlap): {summary['full_disagreement_queries']}")
    if gt:
        print(f"\nGround-truth recall@{args.top_k}  LanceDB={summary['lancedb_expected_recall']}  "
              f"Postgres={summary['postgres_expected_recall']}")
        print(f"Expected-at-RANK-1     LanceDB={summary['lancedb_expected_rank1_rate']}  "
              f"Postgres={summary['postgres_expected_rank1_rate']}")
        print("\nPer-query expected rank (1=best; '-'=not in top-k):")
        for p in gt:
            lr = p["lancedb_expected_rank"] or "-"
            pr = p["postgres_expected_rank"] or "-"
            mark = "" if lr == pr else "  <-- differ"
            print(f"  LanceDB#{lr:<3} Postgres#{pr:<3}  '{p['query']}'{mark}")

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(output, indent=2), encoding="utf-8")
        print(f"\nWrote {args.output_json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
