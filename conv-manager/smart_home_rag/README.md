# Smart-Home RAG Corpus Tooling

This folder contains Phase 7 corpus curation and chunking utilities for the smart-home pivot.

## What is included

- `corpus_manifest.json`: source definitions, include/exclude filters, and per-source limits.
- `chunker.py`: markdown-aware chunking that preserves fenced code blocks.
- `corpus_builder.py`: curated corpus builder that emits deterministic document and chunk IDs.
- `index_upsert.py`: local Qdrant upsert pipeline (delete by `doc_id`, then upsert).
- `retrieval.py`: hybrid retrieval engine (dense + lexical fusion) with parent context assembly.
- `retrieval_eval.py`: retrieval quality + latency evaluation over a query set.
- `retrieval_eval_queries.json`: representative smart-home retrieval queries.

## Expected source mirrors

Place local mirrors in the following paths:

- `repos/home-assistant.io`
- `repos/zigbee2mqtt.io`
- `repos/esphome-docs`

Example clone commands:

```powershell
git clone https://github.com/home-assistant/home-assistant.io.git conv-manager/smart_home_rag/repos/home-assistant.io
git clone https://github.com/Koenkk/zigbee2mqtt.io.git conv-manager/smart_home_rag/repos/zigbee2mqtt.io
git clone https://github.com/esphome/esphome-docs.git conv-manager/smart_home_rag/repos/esphome-docs
```

## Build artifacts

Dry run:

```powershell
python conv-manager/smart_home_rag/corpus_builder.py --dry-run
```

Write outputs:

```powershell
python conv-manager/smart_home_rag/corpus_builder.py
```

Upsert into local Qdrant (offline deterministic embedding mode):

```powershell
python conv-manager/smart_home_rag/index_upsert.py --embedding-mode hash
```

Upsert into local Qdrant using Ollama embeddings (deprecated - use llamacpp instead):

```powershell
python conv-manager/smart_home_rag/index_upsert.py --embedding-mode ollama --ollama-model qwen3-embedding:0.6b
```

Upsert into local Qdrant using llama.cpp embeddings (Phase 7 - replaces Ollama):

```powershell
python conv-manager/smart_home_rag/index_upsert.py --embedding-mode llamacpp
```

Generated files:

- `data/raw_documents.jsonl`
- `data/parents.jsonl`
- `data/chunks.jsonl`
- `data/curated_manifest.lock.json`

## Retrieval evaluation (Phase 7)

Run retrieval evaluation with local query set:

```powershell
python conv-manager/smart_home_rag/retrieval_eval.py --embedding-mode hash
```

Evaluation outputs:

- `data/retrieval_eval_results.json`

## Deterministic IDs

The builder uses SHA-256 IDs so re-indexing is stable:

- `doc_id = sha256(source_name:path)`
- `parent_id = sha256(doc_id:section_index)`
- `chunk_id = sha256(parent_id:chunk_index)`
