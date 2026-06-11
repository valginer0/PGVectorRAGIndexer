#!/usr/bin/env python3
"""Draft recall ground-truth candidates from the live corpus.

Generates query candidates FROM documents (doc -> query), never from search
results, so the ground truth is not biased toward what the engine already
retrieves. Each candidate carries an evidence snippet and a corpus-rarity
count so a human can judge it in seconds.

Output:
  - a JSON candidates file (machine side)
  - prints progress to stderr

Usage:
  venv/bin/python scripts/draft_recall_groundtruth.py \
      --out docs/internal/.validation_work/recall_gt_candidates.json
"""

import argparse
import json
import os
import random
import re
import sys
from collections import defaultdict

import psycopg2

STOPWORDS = set("""a an and are as at be but by for from has have if in into is it its no not of on or
such that the their then there these they this to was were will with you your we our i he she him her
about after all also am any been before being can could did do does down each few had how just like
more most my new now off once only other out over own same so some than too under until up very what
when where which while who why would""".split())

DOC_QUOTAS = {"txt": 16, "pdf": 16, "docx": 12, "md": 8, "doc": 5, "html": 4}
MIN_DOC_TEXT = 600
SNIPPET_LEN = 160


def connect():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ.get("POSTGRES_DB", "rag_vector_db"),
        user=os.environ.get("POSTGRES_USER", "rag_user"),
        password=os.environ.get("POSTGRES_PASSWORD", "rag_password"),
    )


def alpha_ratio(text: str) -> float:
    if not text:
        return 0.0
    alpha = sum(c.isalpha() or c.isspace() for c in text)
    return alpha / len(text)


def sample_documents(cur):
    docs = []
    for ext, quota in DOC_QUOTAS.items():
        cur.execute(
            """
            SELECT document_id, source_uri, SUM(LENGTH(text_content)) AS total_len
            FROM document_chunks
            WHERE lower(source_uri) LIKE %s
            GROUP BY document_id, source_uri
            HAVING SUM(LENGTH(text_content)) > %s
            """,
            (f"%.{ext}", MIN_DOC_TEXT),
        )
        rows = cur.fetchall()
        random.shuffle(rows)
        kept = 0
        for doc_id, uri, _len in rows:
            cur.execute(
                """
                SELECT text_content FROM document_chunks
                WHERE document_id = %s ORDER BY chunk_index LIMIT 3
                """,
                (doc_id,),
            )
            text = "\n".join(r[0] for r in cur.fetchall())
            if alpha_ratio(text[:1500]) < 0.6:
                continue
            docs.append({"document_id": doc_id, "source_uri": uri, "ext": ext, "text": text})
            kept += 1
            if kept >= quota:
                break
        print(f"  {ext}: sampled {kept}", file=sys.stderr)
    return docs


def rarity_count(cur, phrase: str) -> int:
    """How many distinct documents match these terms via FTS (engine-consistent)."""
    cur.execute(
        """
        SELECT COUNT(DISTINCT document_id) FROM document_chunks
        WHERE to_tsvector('english', text_content) @@ plainto_tsquery('english', %s)
        """,
        (phrase,),
    )
    return cur.fetchone()[0]


IDENT_RE = re.compile(r"\b(?=\w*\d)[A-Za-z][A-Za-z0-9_-]{2,19}\b|\b[A-Z]{2,5}-\d+\b")


def identifier_candidates(doc):
    """Tokens that look like identifiers (contain digits / code-like)."""
    seen = set()
    out = []
    for m in IDENT_RE.finditer(doc["text"][:4000]):
        tok = m.group(0)
        low = tok.lower()
        if low in seen or low in STOPWORDS:
            continue
        # Skip pure numbers, years, phone-ish, very common file junk
        if re.fullmatch(r"(19|20)\d\d", tok) or re.fullmatch(r"\d+", tok):
            continue
        seen.add(low)
        idx = m.start()
        snippet = doc["text"][max(0, idx - 70): idx + 90].replace("\n", " ").strip()
        out.append((tok, snippet))
        if len(out) >= 3:
            break
    return out


def content_words(sentence):
    return [w for w in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", sentence)
            if w.lower() not in STOPWORDS]


def contextual_candidates(doc):
    """A distinctive content-word query from a mid-document sentence."""
    mid = doc["text"][len(doc["text"]) // 4:]
    sentences = re.split(r"(?<=[.!?])\s+|\n{2,}", mid)
    for s in sentences:
        s = s.strip().replace("\n", " ")
        if not (60 <= len(s) <= 220):
            continue
        words = content_words(s)
        if len(words) < 5:
            continue
        # prefer longer/rarer-looking words
        words.sort(key=lambda w: -len(w))
        query = " ".join(dict.fromkeys(w.lower() for w in words[:5]))
        return [(query, s[:SNIPPET_LEN])]
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=20260611)
    args = ap.parse_args()
    random.seed(args.seed)

    conn = connect()
    cur = conn.cursor()
    print("Sampling documents...", file=sys.stderr)
    docs = sample_documents(cur)
    print(f"Sampled {len(docs)} documents", file=sys.stderr)

    candidates = []
    n = 0
    for doc in docs:
        base = os.path.basename(doc["source_uri"].replace("\\", "/"))
        for tok, snippet in identifier_candidates(doc):
            words = [w for w in content_words(snippet) if w.lower() != tok.lower()][:2]
            query = " ".join([tok] + [w.lower() for w in words])
            cnt = rarity_count(cur, query)
            if 0 < cnt <= 5:
                n += 1
                candidates.append({
                    "id": f"GT-{n:03d}", "type": "identifier", "query": query,
                    "expected_source_uri": doc["source_uri"], "expected_file": base,
                    "evidence": snippet[:SNIPPET_LEN], "fts_doc_matches": cnt,
                })
                break  # one identifier query per doc
        for query, snippet in contextual_candidates(doc):
            cnt = rarity_count(cur, query)
            if 0 < cnt <= 8:
                n += 1
                candidates.append({
                    "id": f"GT-{n:03d}", "type": "contextual", "query": query,
                    "expected_source_uri": doc["source_uri"], "expected_file": base,
                    "evidence": snippet, "fts_doc_matches": cnt,
                })

    # Also dump snippets for hand-written semantic queries (no auto queries)
    semantic_pool = [
        {"source_uri": d["source_uri"],
         "file": os.path.basename(d["source_uri"].replace("\\", "/")),
         "snippet": d["text"][:600]}
        for d in random.sample(docs, min(18, len(docs)))
    ]

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump({"candidates": candidates, "semantic_pool": semantic_pool}, f, indent=1)
    by_type = defaultdict(int)
    for c in candidates:
        by_type[c["type"]] += 1
    print(f"Wrote {len(candidates)} candidates {dict(by_type)} + {len(semantic_pool)} semantic snippets -> {args.out}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
