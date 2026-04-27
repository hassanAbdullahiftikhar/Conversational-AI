from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchAny,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
CHUNKS_JSONL = DATA_DIR / "chunks.jsonl"
DEFAULT_DB_PATH = DATA_DIR / "qdrant_db"
DEFAULT_COLLECTION = "smart_home_docs"
DEFAULT_VECTOR_SIZE = 384


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _normalize(vector: list[float]) -> list[float]:
    length = math.sqrt(sum(value * value for value in vector))
    if length == 0:
        return vector
    return [value / length for value in vector]


def _hash_embedding(text: str, size: int) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values: list[float] = []
    while len(values) < size:
        for byte in digest:
            values.append((byte / 127.5) - 1.0)
            if len(values) == size:
                break
        digest = hashlib.sha256(digest).digest()
    return _normalize(values)


class OllamaEmbedder:
    def __init__(self, base_url: str, model: str, timeout_seconds: int = 30) -> None:
        self.url = base_url.rstrip("/") + "/api/embed"
        self.model = model
        self.timeout = httpx.Timeout(timeout_seconds)

    def embed(self, text: str) -> list[float]:
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(self.url, json={"model": self.model, "input": text})
            response.raise_for_status()
            payload = response.json()
            vectors = payload.get("embeddings") or []
            if not vectors:
                raise RuntimeError("Ollama embed response did not include embeddings")
            vector = vectors[0]
            if not isinstance(vector, list):
                raise RuntimeError("Invalid embedding format from Ollama")
            return [float(value) for value in vector]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(self.url, json={"model": self.model, "input": texts})
            response.raise_for_status()
            payload = response.json()
            vectors = payload.get("embeddings") or []
            return [[float(v) for v in vec] for vec in vectors]


class LlamaCppEmbedder:
    def __init__(self, base_url: str, timeout_seconds: int = 30) -> None:
        self.url = base_url.rstrip("/") + "/v1/embeddings"
        self.timeout = httpx.Timeout(timeout_seconds)

    def embed(self, text: str) -> list[float]:
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(self.url, json={"input": text})
            payload = response.json()
            data = payload.get("data") or []
            if not data:
                raise RuntimeError("LlamaCpp embed response missing 'data' field")
            embedding = data[0].get("embedding")
            if not isinstance(embedding, list):
                raise RuntimeError("Invalid embedding format from LlamaCpp")
            return [float(v) for v in embedding]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(self.url, json={"input": texts})
            payload = response.json()
            data = payload.get("data") or []
            results: list[list[float]] = []
            for item in data:
                vec = item.get("embedding", [])
                results.append([float(v) for v in vec])
            return results


def _build_points(
    rows: list[dict[str, Any]],
    embedding_mode: str,
    vector_size: int,
    ollama_base_url: str,
    ollama_model: str,
) -> tuple[list[PointStruct], int]:
    entries: list[dict[str, Any]] = []
    for row in rows:
        chunk_id = str(row["chunk_id"])
        text = str(row.get("text", "")).strip()
        if not text:
            continue
        entries.append({
            "chunk_id": chunk_id,
            "doc_id": str(row.get("doc_id", "")),
            "parent_id": str(row.get("parent_id", "")),
            "source": str(row.get("source", "")),
            "path": str(row.get("path", "")),
            "section_index": int(row.get("section_index", 0)),
            "chunk_index": int(row.get("chunk_index", 0)),
            "heading": str(row.get("heading", "")),
            "text": text,
            "char_count": int(row.get("char_count", len(text))),
        })

    if not entries:
        return [], 0

    embedder: OllamaEmbedder | LlamaCppEmbedder | None = None
    if embedding_mode == "ollama":
        embedder = OllamaEmbedder(base_url=ollama_base_url, model=ollama_model)
    elif embedding_mode == "llamacpp":
        embedder = LlamaCppEmbedder(base_url=ollama_base_url)

    BATCH_SIZE = 50
    texts = [e["text"] for e in entries]
    all_embeddings: list[list[float]] = []

    if embedder is not None:
        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i:i + BATCH_SIZE]
            emb = embedder.embed_batch(batch)
            all_embeddings.extend(emb)
    else:
        for text in texts:
            vector = _hash_embedding(text, size=vector_size)
            all_embeddings.append(vector)

    inferred_dim = len(all_embeddings[0]) if all_embeddings else 0

    points: list[PointStruct] = []
    for entry, vector in zip(entries, all_embeddings):
        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, entry["chunk_id"]))
        points.append(PointStruct(id=point_id, vector=vector, payload=entry))

    return points, inferred_dim


def _ensure_collection(client: QdrantClient, collection: str, vector_size: int) -> None:
    if not client.collection_exists(collection):
        client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )
        client.create_payload_index(collection_name=collection, field_name="source", field_schema=PayloadSchemaType.KEYWORD)
        client.create_payload_index(collection_name=collection, field_name="doc_id", field_schema=PayloadSchemaType.KEYWORD)
        client.create_payload_index(collection_name=collection, field_name="parent_id", field_schema=PayloadSchemaType.KEYWORD)


def _delete_existing_doc_points(client: QdrantClient, collection: str, doc_ids: list[str]) -> int:
    filtered_ids = [d for d in doc_ids if d]
    if not filtered_ids:
        return 0
    _filter = Filter(must=[FieldCondition(key="doc_id", match=MatchAny(any=filtered_ids))])
    client.delete(collection_name=collection, points_selector=_filter)
    return len(filtered_ids)


def upsert_chunks(
    chunks_path: Path,
    db_path: Path,
    collection: str,
    embedding_mode: str,
    vector_size: int,
    ollama_base_url: str,
    ollama_model: str,
) -> dict[str, Any]:
    rows = _read_jsonl(chunks_path)
    if not rows:
        return {
            "status": "no_chunks",
            "chunks_path": chunks_path.as_posix(),
        }

    points, inferred_dim = _build_points(
        rows=rows,
        embedding_mode=embedding_mode,
        vector_size=vector_size,
        ollama_base_url=ollama_base_url,
        ollama_model=ollama_model,
    )
    if not points:
        return {
            "status": "no_points",
            "chunks_path": chunks_path.as_posix(),
        }

    active_vector_size = inferred_dim if inferred_dim > 0 else vector_size

    db_path.mkdir(parents=True, exist_ok=True)
    client = QdrantClient(path=str(db_path))
    _ensure_collection(client, collection=collection, vector_size=active_vector_size)

    doc_to_points: dict[str, list[PointStruct]] = defaultdict(list)
    for point in points:
        doc_to_points[str(point.payload.get("doc_id", ""))].append(point)

    deleted_docs = _delete_existing_doc_points(client, collection=collection, doc_ids=list(doc_to_points.keys()))

    for batch in doc_to_points.values():
        client.upsert(collection_name=collection, points=batch, wait=True)

    return {
        "status": "ok",
        "collection": collection,
        "db_path": db_path.as_posix(),
        "embedding_mode": embedding_mode,
        "vector_size": active_vector_size,
        "docs_upserted": len(doc_to_points),
        "chunks_upserted": len(points),
        "docs_deleted_before_upsert": deleted_docs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Upsert curated chunk JSONL into local Qdrant.")
    parser.add_argument("--chunks", default=str(CHUNKS_JSONL), help="Path to chunks JSONL.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="Path for local Qdrant storage.")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION, help="Collection name.")
    parser.add_argument(
        "--embedding-mode",
        choices=["hash", "ollama", "llamacpp"],
        default="hash",
        help="Embedding mode. Use hash for offline deterministic test mode.",
    )
    parser.add_argument("--vector-size", type=int, default=DEFAULT_VECTOR_SIZE, help="Vector size for hash mode.")
    parser.add_argument("--ollama-base-url", default=os.getenv("EMBED_URL", "http://llm-engine:11434"), help="Ollama base URL.")
    parser.add_argument("--ollama-model", default=os.getenv("EMBED_MODEL", "qwen3-embedding:0.6b"), help="Ollama embedding model tag.")
    args = parser.parse_args()

    summary = upsert_chunks(
        chunks_path=Path(args.chunks).resolve(),
        db_path=Path(args.db_path).resolve(),
        collection=args.collection,
        embedding_mode=args.embedding_mode,
        vector_size=args.vector_size,
        ollama_base_url=args.ollama_base_url,
        ollama_model=args.ollama_model,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
