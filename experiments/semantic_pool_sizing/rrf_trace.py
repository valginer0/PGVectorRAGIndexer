import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
# Uses the LanceDB root from the active app config (config.py), not a hardcoded path.
from services import get_lancedb_adapter
from embeddings import get_embedding_service
from config import get_config

adapter = get_lancedb_adapter()
model = get_embedding_service()
config = get_config()

query_text = "referencing and proving the origin of model output"
query_vector = model.encode(query_text)
parent_limit = 100
child_limit = 100
child_parent_spill_ratio = config.retrieval.lancedb_child_parent_spill_ratio
semantic_candidate_pool = config.retrieval.lancedb_semantic_candidate_pool

print(f"Config spill ratio: {child_parent_spill_ratio}")
print(f"Config candidate pool: {semantic_candidate_pool}")

parents = adapter.db.open_table("parent_documents")
chunks = adapter.db.open_table("document_chunks")

# FTS Search on parents
parent_search = parents.search(query_text, query_type="fts")
parent_rows = parent_search.limit(parent_limit).to_arrow().to_pylist()
fts_parent_ranks = {}
for rank, row in enumerate(parent_rows, 1):
    fts_parent_ranks[row["document_id"]] = rank

print(f"\nFTS Parents matched: {len(parent_rows)}")
if "01_what_is_rag.txt" in fts_parent_ranks:
    print(f"  Target 01_what_is_rag.txt found in FTS at rank {fts_parent_ranks['01_what_is_rag.txt']}")
else:
    print("  Target 01_what_is_rag.txt NOT found in FTS matches")

# Global vector search
global_chunk_search = chunks.search(query_vector, vector_column_name="embedding").metric("cosine")
global_chunk_rows = global_chunk_search.limit(semantic_candidate_pool).to_arrow().to_pylist()

vector_parent_ranks = {}
vector_rank_counter = 1
for idx, row in enumerate(global_chunk_rows, 1):
    doc_id = row["document_id"]
    if doc_id not in vector_parent_ranks:
        vector_parent_ranks[doc_id] = vector_rank_counter
        vector_rank_counter += 1
    if doc_id == "01_what_is_rag.txt":
        print(f"  Target chunk found in global search at rank {idx} (document vector rank: {vector_parent_ranks[doc_id]})")

# RRF scores computation
all_parent_ids = set(fts_parent_ranks.keys()) | set(vector_parent_ranks.keys())
parent_scores = []
for doc_id in all_parent_ids:
    fts_rank = fts_parent_ranks.get(doc_id)
    vector_rank = vector_parent_ranks.get(doc_id)
    
    fts_score = 1.0 / (60.0 + fts_rank) if fts_rank is not None else 0.0
    vector_score = 1.0 / (60.0 + vector_rank) if vector_rank is not None else 0.0
    rrf_score = fts_score + vector_score
    parent_scores.append((doc_id, rrf_score, fts_rank, vector_rank))

parent_scores.sort(key=lambda x: -x[1])

print("\nTop 15 merged parents by RRF:")
for i in range(min(15, len(parent_scores))):
    p = parent_scores[i]
    target_marker = " <--- TARGET" if p[0] == "01_what_is_rag.txt" else ""
    print(f"  {i+1}. ID={p[0]}, RRF={p[1]:.5f}, FTS_rank={p[2]}, Vector_rank={p[3]}{target_marker}")

selected_parents = parent_scores[:parent_limit]
top_rrf = selected_parents[0][1]
allowed_parents = [
    p for p in selected_parents
    if p[1] >= top_rrf * child_parent_spill_ratio
]

print(f"\nTop RRF score: {top_rrf:.5f}")
print(f"Threshold (Top * spill_ratio): {top_rrf * child_parent_spill_ratio:.5f}")
print(f"Allowed parents count: {len(allowed_parents)}")

target_allowed = False
for idx, p in enumerate(allowed_parents, 1):
    if p[0] == "01_what_is_rag.txt":
        print(f"  Target allowed! Rank: {idx}")
        target_allowed = True
if not target_allowed:
    print("  Target NOT allowed!")
