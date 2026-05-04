from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import httpx
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
CHUNKS_JSONL = DATA_DIR / "chunks.jsonl"
PARENTS_JSONL = DATA_DIR / "parents.jsonl"
DB_PATH = DATA_DIR / "qdrant_db"
COLLECTION = "smart_home_docs"

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_\-.]*")


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


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


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


class LexicalIndex:
    def __init__(self, chunks: dict[str, dict[str, Any]]) -> None:
        self._chunks_ref = chunks
        self.doc_len: dict[str, int] = {}
        self.postings: dict[str, list[tuple[str, int]]] = defaultdict(list)
        self.doc_count = len(chunks)

        total_len = 0
        for chunk_id, payload in chunks.items():
            text = str(payload.get("text", ""))
            counts = Counter(_tokenize(text))
            length = sum(counts.values())
            self.doc_len[chunk_id] = length
            total_len += length

            for token, freq in counts.items():
                self.postings[token].append((chunk_id, freq))

        self.avg_len = (total_len / self.doc_count) if self.doc_count else 0.0

    def search(self, query: str, limit: int = 50, source_filter: str | None = None) -> list[tuple[str, float]]:
        if self.doc_count == 0:
            return []

        k1 = 1.5
        b = 0.75
        q_tokens = _tokenize(query)
        if not q_tokens:
            return []

        scores: dict[str, float] = defaultdict(float)
        for token in q_tokens:
            postings = self.postings.get(token)
            if not postings:
                continue

            df = len(postings)
            idf = math.log(1.0 + ((self.doc_count - df + 0.5) / (df + 0.5)))

            for chunk_id, freq in postings:
                doc_length = self.doc_len.get(chunk_id, 0)
                denominator = freq + k1 * (1 - b + b * (doc_length / (self.avg_len or 1.0)))
                scores[chunk_id] += idf * ((freq * (k1 + 1)) / (denominator or 1.0))

        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)

        if source_filter:
            ranked = [
                (chunk_id, score)
                for chunk_id, score in ranked
                if str(self._chunks_ref.get(chunk_id, {}).get("source", "")) == source_filter
            ]

        return ranked[:limit]

    def bind_chunks(self, chunks: dict[str, dict[str, Any]]) -> None:
        self._chunks_ref = chunks


class RetrievalEngine:
    def __init__(
        self,
        chunks_path: Path = CHUNKS_JSONL,
        parents_path: Path = PARENTS_JSONL,
        qdrant_path: Path = DB_PATH,
        collection: str = COLLECTION,
        embedding_mode: str = "hash",
        vector_size: int = 384,
        ollama_base_url: str | None = None,
        ollama_model: str | None = None,
    ) -> None:
        self.collection = collection
        self.embedding_mode = embedding_mode
        self.vector_size = vector_size

        if ollama_base_url is None:
            ollama_base_url = os.getenv("EMBED_URL", "http://localhost:11434")
        if ollama_model is None:
            ollama_model = os.getenv("EMBED_MODEL", "qwen3-embedding:0.6b")

        chunk_rows = _read_jsonl(chunks_path)
        parent_rows = _read_jsonl(parents_path)

        self.chunks: dict[str, dict[str, Any]] = {
            str(row.get("chunk_id")): row for row in chunk_rows if row.get("chunk_id")
        }
        self.parents: dict[str, dict[str, Any]] = {
            str(row.get("parent_id")): row for row in parent_rows if row.get("parent_id")
        }

        # Fallback when parents artifact is missing.
        if not self.parents:
            for chunk in self.chunks.values():
                parent_id = str(chunk.get("parent_id", ""))
                if not parent_id:
                    continue
                current = self.parents.get(parent_id)
                candidate = {
                    "parent_id": parent_id,
                    "doc_id": str(chunk.get("doc_id", "")),
                    "source": str(chunk.get("source", "")),
                    "path": str(chunk.get("path", "")),
                    "section_index": int(chunk.get("section_index", 0)),
                    "heading": str(chunk.get("heading", "")),
                    "text": str(chunk.get("text", "")),
                    "char_count": int(chunk.get("char_count", 0)),
                }
                if current is None or candidate["char_count"] > int(current.get("char_count", 0)):
                    self.parents[parent_id] = candidate

        self.lexical = LexicalIndex(self.chunks)
        self.lexical.bind_chunks(self.chunks)

        self.embedder: OllamaEmbedder | LlamaCppEmbedder | None = None
        if embedding_mode in ("ollama", "llamacpp"):
            base = ollama_base_url or os.getenv("EMBED_URL", "http://localhost:11434")
            if embedding_mode == "llamacpp":
                self.embedder = LlamaCppEmbedder(base_url=base)
            else:
                self.embedder = OllamaEmbedder(base_url=base, model=ollama_model)

        self.qdrant: QdrantClient | None = None
        self.dense_available = False
        try:
            if qdrant_path.exists():
                self.qdrant = QdrantClient(path=str(qdrant_path))
                self.dense_available = bool(self.qdrant.collection_exists(collection))
        except Exception:
            self.qdrant = None
            self.dense_available = False

    @property
    def has_corpus(self) -> bool:
        return bool(self.chunks)

    def _embed_query(self, query: str) -> list[float]:
        if self.embedder is not None:
            return self.embedder.embed(query)
        return _hash_embedding(query, size=self.vector_size)

    def _query_dense(self, query_vector: list[float], limit: int, source_filter: str | None) -> list[tuple[str, float]]:
        if not self.dense_available or self.qdrant is None:
            return []

        query_filter = None
        if source_filter:
            query_filter = Filter(must=[FieldCondition(key="source", match=MatchValue(value=source_filter))])

        points: list[Any] = []

        if hasattr(self.qdrant, "query_points"):
            response = self.qdrant.query_points(
                collection_name=self.collection,
                query=query_vector,
                limit=limit,
                query_filter=query_filter,
                with_payload=True,
                with_vectors=False,
            )
            points = list(getattr(response, "points", []) or [])
        else:
            response = self.qdrant.search(
                collection_name=self.collection,
                query_vector=query_vector,
                limit=limit,
                query_filter=query_filter,
                with_payload=True,
                with_vectors=False,
            )
            points = list(response or [])

        output: list[tuple[str, float]] = []
        for point in points:
            chunk_id = str(getattr(point, "id", ""))
            payload = getattr(point, "payload", None)
            if isinstance(payload, dict):
                payload_chunk_id = str(payload.get("chunk_id", "")).strip()
                if payload_chunk_id:
                    chunk_id = payload_chunk_id
            score = float(getattr(point, "score", 0.0) or 0.0)
            if chunk_id:
                output.append((chunk_id, score))
        return output

    @staticmethod
    def _rrf_fusion(
        dense: list[tuple[str, float]],
        lexical: list[tuple[str, float]],
        k: int = 60,
    ) -> tuple[list[tuple[str, float]], dict[str, float], dict[str, float]]:
        fused: dict[str, float] = defaultdict(float)
        dense_scores = {chunk_id: score for chunk_id, score in dense}
        lexical_scores = {chunk_id: score for chunk_id, score in lexical}

        for rank, (chunk_id, _) in enumerate(dense, start=1):
            fused[chunk_id] += 1.0 / (k + rank)

        for rank, (chunk_id, _) in enumerate(lexical, start=1):
            fused[chunk_id] += 1.0 / (k + rank)

        ranked = sorted(fused.items(), key=lambda item: item[1], reverse=True)
        return ranked, dense_scores, lexical_scores

    @staticmethod
    def _truncate_text(text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "\n...[truncated]"

    def _assemble_parents(
        self,
        ranked_chunk_ids: list[str],
        top_k_parents: int,
        max_parent_chars: int,
        max_total_chars: int,
    ) -> list[dict[str, Any]]:
        used: set[str] = set()
        parents: list[dict[str, Any]] = []
        total_chars = 0

        for chunk_id in ranked_chunk_ids:
            chunk = self.chunks.get(chunk_id)
            if not chunk:
                continue
            parent_id = str(chunk.get("parent_id", ""))
            if not parent_id or parent_id in used:
                continue

            parent = dict(self.parents.get(parent_id, {}))
            if not parent:
                continue

            text = str(parent.get("text", ""))
            clipped = self._truncate_text(text, max_chars=max_parent_chars)
            char_count = len(clipped)
            if total_chars + char_count > max_total_chars and parents:
                break

            parents.append(
                {
                    "parent_id": parent_id,
                    "doc_id": str(parent.get("doc_id", "")),
                    "source": str(parent.get("source", "")),
                    "path": str(parent.get("path", "")),
                    "title": str(parent.get("heading", "")),
                    "text": clipped,
                    "char_count": char_count,
                }
            )
            used.add(parent_id)
            total_chars += char_count

            if len(parents) >= top_k_parents:
                break

        return parents

    def search(
        self,
        query: str,
        top_k_chunks: int = 20,
        top_k_parents: int = 5,
        max_parent_chars: int = 2400,
        max_total_parent_chars: int = 8000,
        source_filter: str | None = None,
    ) -> dict[str, Any]:
        if not self.has_corpus:
            return {
                "status": "no_corpus",
                "query": query,
                "candidates": [],
                "parents": [],
                "timings_ms": {
                    "total_ms": 0,
                },
            }

        t0 = time.perf_counter()

        embed_start = time.perf_counter()
        query_vector = self._embed_query(query)
        embed_ms = int((time.perf_counter() - embed_start) * 1000)

        dense_start = time.perf_counter()
        dense_hits = self._query_dense(query_vector=query_vector, limit=top_k_chunks, source_filter=source_filter)
        dense_ms = int((time.perf_counter() - dense_start) * 1000)

        lexical_start = time.perf_counter()
        lexical_hits = self.lexical.search(query=query, limit=top_k_chunks, source_filter=source_filter)
        lexical_ms = int((time.perf_counter() - lexical_start) * 1000)

        fusion_start = time.perf_counter()
        fused_ranked, dense_scores, lexical_scores = self._rrf_fusion(dense_hits, lexical_hits)
        fused_ranked = fused_ranked[:top_k_chunks]
        fusion_ms = int((time.perf_counter() - fusion_start) * 1000)

        candidate_rows: list[dict[str, Any]] = []
        ranked_chunk_ids: list[str] = []
        for chunk_id, fused_score in fused_ranked:
            payload = self.chunks.get(chunk_id)
            if not payload:
                continue

            ranked_chunk_ids.append(chunk_id)
            candidate_rows.append(
                {
                    "chunk_id": chunk_id,
                    "parent_id": str(payload.get("parent_id", "")),
                    "doc_id": str(payload.get("doc_id", "")),
                    "source": str(payload.get("source", "")),
                    "path": str(payload.get("path", "")),
                    "title": str(payload.get("heading", "")),
                    "section_index": int(payload.get("section_index", 0)),
                    "chunk_index": int(payload.get("chunk_index", 0)),
                    "dense_score": float(dense_scores.get(chunk_id, 0.0)),
                    "lexical_score": float(lexical_scores.get(chunk_id, 0.0)),
                    "fusion_score": float(fused_score),
                    "text_preview": str(payload.get("text", ""))[:240],
                }
            )

        parent_start = time.perf_counter()
        parents = self._assemble_parents(
            ranked_chunk_ids=ranked_chunk_ids,
            top_k_parents=top_k_parents,
            max_parent_chars=max_parent_chars,
            max_total_chars=max_total_parent_chars,
        )
        parent_ms = int((time.perf_counter() - parent_start) * 1000)

        total_ms = int((time.perf_counter() - t0) * 1000)

        return {
            "status": "ok",
            "query": query,
            "source_filter": source_filter,
            "candidates": candidate_rows,
            "parents": parents,
            "timings_ms": {
                "embedding_ms": embed_ms,
                "dense_ms": dense_ms,
                "lexical_ms": lexical_ms,
                "fusion_ms": fusion_ms,
                "parent_assembly_ms": parent_ms,
                "total_ms": total_ms,
            },
        }
