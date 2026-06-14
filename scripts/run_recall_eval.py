#!/usr/bin/env python3
"""Run the recall ground-truth eval against the live backend.

Reads the human-reviewed markdown (surviving IDs only) + the draft manifest,
queries POST /search (file-level via group_by_document), and reports
hit@1/@5/@10 and ranks per query type.

Usage:
  venv/bin/python scripts/run_recall_eval.py \
      --review docs/internal/RECALL_GT_REVIEW_20260611.md \
      --manifest docs/internal/.validation_work/recall_gt_manifest_draft.json \
      --out docs/internal/.validation_work/recall_eval_results.json
"""

import argparse
import json
import re
import sys
from collections import defaultdict

import requests

BASE = "http://localhost:8000"
TOP_K = 10


def surviving_ids(review_path):
    ids = set()
    for line in open(review_path, encoding="utf-8"):
        m = re.match(r"\|\s*((?:GT|ST|MD)-\d+)\s*\|", line)
        if m:
            ids.add(m.group(1))
    return ids


def norm(uri):
    return uri.replace("\\", "/").lower()


def run_query(query):
    r = requests.post(f"{BASE}/search", json={
        "query": query, "top_k": TOP_K, "min_score": 0.0,
        "group_by_document": True,
    }, timeout=120)
    r.raise_for_status()
    return [res["source_uri"] for res in r.json()["results"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--review", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ids", help="comma-separated subset (smoke test)")
    args = ap.parse_args()

    keep = surviving_ids(args.review)
    manifest = [m for m in json.load(open(args.manifest)) if m["id"] in keep]
    if args.ids:
        subset = set(args.ids.split(","))
        manifest = [m for m in manifest if m["id"] in subset]
    print(f"Evaluating {len(manifest)} approved queries against {BASE}", file=sys.stderr)

    results = []
    for m in manifest:
        returned = run_query(m["query"])
        expected = {norm(u) for u in m["expected_source_uris"]}
        sub = m.get("match_substring", "").lower()

        def is_hit(u):
            return norm(u) in expected or (sub and sub in norm(u))

        rank = next((i for i, u in enumerate(returned, 1) if is_hit(u)), None)
        results.append({**m, "rank": rank, "returned_top3": returned[:3]})
        mark = f"rank {rank}" if rank else "MISS"
        print(f"  {m['id']:7} [{m['type']:10}] {mark:8} {m['query'][:60]}", file=sys.stderr)

    by_type = defaultdict(list)
    for r in results:
        by_type[r["type"]].append(r)

    def stats(rs):
        n = len(rs)
        return {
            "n": n,
            "hit@1": sum(1 for r in rs if r["rank"] == 1) / n if n else 0,
            "hit@5": sum(1 for r in rs if r["rank"] and r["rank"] <= 5) / n if n else 0,
            "hit@10": sum(1 for r in rs if r["rank"]) / n if n else 0,
        }

    summary = {t: stats(rs) for t, rs in sorted(by_type.items())}
    summary["OVERALL"] = stats(results)
    json.dump({"summary": summary, "results": results}, open(args.out, "w"), indent=1)

    print("\n=== RECALL SUMMARY (file-level, top_k=10) ===")
    for t, s in summary.items():
        print(f"{t:11} n={s['n']:3}  hit@1={s['hit@1']:.2f}  hit@5={s['hit@5']:.2f}  hit@10={s['hit@10']:.2f}")
    misses = [r["id"] for r in results if not r["rank"]]
    if misses:
        print(f"misses: {', '.join(misses)}")


if __name__ == "__main__":
    main()
