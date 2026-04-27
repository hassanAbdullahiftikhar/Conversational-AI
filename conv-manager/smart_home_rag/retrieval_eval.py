from __future__ import annotations

import argparse
import json
import math
import os
import statistics
from pathlib import Path
from typing import Any

try:
    from .retrieval import DATA_DIR, RetrievalEngine
except ImportError:
    from retrieval import DATA_DIR, RetrievalEngine


ROOT = Path(__file__).resolve().parent
EVAL_QUERIES_PATH = ROOT / "retrieval_eval_queries.json"
RESULTS_PATH = DATA_DIR / "retrieval_eval_results.json"


def _load_queries(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        raise ValueError("retrieval eval query file must be a JSON list")
    return payload


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if p <= 0:
        return min(values)
    if p >= 100:
        return max(values)

    sorted_values = sorted(values)
    rank = (len(sorted_values) - 1) * (p / 100.0)
    low = int(math.floor(rank))
    high = int(math.ceil(rank))
    if low == high:
        return sorted_values[low]
    weight = rank - low
    return sorted_values[low] * (1 - weight) + sorted_values[high] * weight


def _parent_hit(parents: list[dict[str, Any]], expected_tokens: list[str]) -> bool:
    if not expected_tokens:
        return True

    lowered = [token.lower() for token in expected_tokens]
    for parent in parents:
        haystack = " ".join(
            [
                str(parent.get("source", "")),
                str(parent.get("path", "")),
                str(parent.get("title", "")),
            ]
        ).lower()
        if any(token in haystack for token in lowered):
            return True
    return False


def evaluate(
    queries_path: Path,
    embedding_mode: str,
    vector_size: int,
    ollama_base_url: str,
    ollama_model: str,
    top_k_parents: int,
) -> dict[str, Any]:
    engine = RetrievalEngine(
        embedding_mode=embedding_mode,
        vector_size=vector_size,
        ollama_base_url=ollama_base_url,
        ollama_model=ollama_model,
    )

    if not engine.has_corpus:
        return {
            "status": "no_corpus",
            "message": "No chunk corpus available. Build corpus and index first.",
        }

    queries = _load_queries(queries_path)

    rows: list[dict[str, Any]] = []
    hits = 0
    latency_values: list[float] = []

    for row in queries:
        query_id = str(row.get("id", "unknown"))
        query = str(row.get("query", "")).strip()
        expected_tokens = [str(item) for item in row.get("expected_contains", [])]
        if not query:
            continue

        result = engine.search(query=query, top_k_chunks=20, top_k_parents=top_k_parents)
        parents = result.get("parents", [])
        timings = result.get("timings_ms", {})
        total_ms = float(timings.get("total_ms", 0.0) or 0.0)

        hit = _parent_hit(parents=parents, expected_tokens=expected_tokens)
        if hit:
            hits += 1
        latency_values.append(total_ms)

        rows.append(
            {
                "id": query_id,
                "query": query,
                "hit": hit,
                "expected_contains": expected_tokens,
                "total_ms": total_ms,
                "top_parent_ids": [str(item.get("parent_id", "")) for item in parents[:5]],
                "top_parent_sources": [str(item.get("source", "")) for item in parents[:5]],
            }
        )

    total = len(rows)
    recall_at_k = round(hits / total, 4) if total else 0.0

    summary = {
        "status": "ok",
        "embedding_mode": embedding_mode,
        "total_queries": total,
        "hits": hits,
        "recall_at_k": recall_at_k,
        "retrieval_latency_ms": {
            "p50": round(_percentile(latency_values, 50), 2),
            "p95": round(_percentile(latency_values, 95), 2),
            "avg": round(statistics.mean(latency_values), 2) if latency_values else 0.0,
        },
        "rows": rows,
    }

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate retrieval quality and latency.")
    parser.add_argument("--queries", default=str(EVAL_QUERIES_PATH), help="Path to retrieval eval queries JSON.")
    parser.add_argument("--embedding-mode", choices=["hash", "ollama", "llamacpp"], default="hash")
    parser.add_argument("--vector-size", type=int, default=384)
    parser.add_argument("--ollama-base-url", default=os.getenv("EMBED_URL", "http://llm-engine:11434"))
    parser.add_argument("--ollama-model", default=os.getenv("EMBED_MODEL", "qwen3-embedding:0.6b"))
    parser.add_argument("--top-k-parents", type=int, default=5, help="Parent contexts to evaluate.")
    parser.add_argument("--out", default=str(RESULTS_PATH), help="Output results path.")
    args = parser.parse_args()

    summary = evaluate(
        queries_path=Path(args.queries).resolve(),
        embedding_mode=args.embedding_mode,
        vector_size=args.vector_size,
        ollama_base_url=args.ollama_base_url,
        ollama_model=args.ollama_model,
        top_k_parents=args.top_k_parents,
    )

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
