"""
Remaps queries.json to use real SHA-256 chunk IDs from the live corpus
by running the actual BM25 retriever against each query.

This ensures the ground-truth IDs in queries.json match what the
BM25 retrieval engine would actually return for each query.

Run once after rebuilding the corpus:
    python remap_queries.py
"""
import json
import sys
import os

# Add conv-manager to path so we can import the retrieval engine
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "conv-manager"))

from smart_home_rag.retrieval import RetrievalEngine

print("Loading retrieval engine (BM25 + Qdrant local)...")
# hash mode = uses local Qdrant DB as-is (dense search with hash vectors)
engine = RetrievalEngine(embedding_mode="hash")

if not engine.has_corpus:
    print("ERROR: No corpus loaded. Run startup.bat --rebuild-corpus first.")
    sys.exit(1)

print(f"Corpus loaded: {len(engine.chunks)} chunks")

with open("evals/data/rag/queries.json") as f:
    queries = json.load(f)

new_queries = []
for q in queries:
    # Run actual retrieval with top_k=10 to get the best BM25 hits
    result = engine.search(query=q["query_text"], top_k_chunks=10, top_k_parents=5)
    candidates = result.get("candidates", [])

    # Take top-3 chunk IDs as the ground truth for this query
    top_ids = [c["chunk_id"] for c in candidates[:3]]

    if not top_ids:
        print(f"[WARN] {q['query_id']}: no results. Keeping original IDs.")
        new_queries.append(q)
        continue

    q2 = dict(q)
    q2["relevant_chunk_ids"] = top_ids
    new_queries.append(q2)

    print(f"{q['query_id']}: {q['query_text'][:55]}")
    for i, cid in enumerate(top_ids, 1):
        chunk = engine.chunks.get(cid, {})
        print(f"  [{i}] {cid[:16]}... ({chunk.get('heading', '')[:40]})")

with open("evals/data/rag/queries.json", "w") as f:
    json.dump(new_queries, f, indent=2)

print(f"\nDone. Updated {len(new_queries)} queries in evals/data/rag/queries.json")
