from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from .chunker import chunk_document
except ImportError:
    from chunker import chunk_document


ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "corpus_manifest.json"
DATA_DIR = ROOT / "data"
LOCK_PATH = DATA_DIR / "curated_manifest.lock.json"
DOCS_JSONL = DATA_DIR / "raw_documents.jsonl"
CHUNKS_JSONL = DATA_DIR / "chunks.jsonl"
PARENTS_JSONL = DATA_DIR / "parents.jsonl"


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _load_manifest(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _is_markdown(path: Path) -> bool:
    return path.suffix.lower() in {".md", ".markdown", ".mdx"}


def _matches_any(path_posix: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if fnmatch.fnmatch(path_posix, pattern):
            return True
    return False


def _discover_source_files(source_root: Path, include: list[str], exclude: list[str]) -> list[Path]:
    candidates: set[Path] = set()
    for pattern in include:
        candidates.update(source_root.glob(pattern))

    selected: list[Path] = []
    for candidate in sorted(candidates):
        if not candidate.is_file() or not _is_markdown(candidate):
            continue

        rel_posix = candidate.relative_to(source_root).as_posix()
        if _matches_any(rel_posix, exclude):
            continue

        selected.append(candidate)

    return selected


def _priority_score(path: Path, keywords: list[str]) -> int:
    target = path.as_posix().lower()
    return sum(1 for keyword in keywords if keyword.lower() in target)


def _select_curated(files: list[Path], max_docs: int, keywords: list[str]) -> list[Path]:
    ranked = sorted(
        files,
        key=lambda item: (
            -_priority_score(item, keywords),
            len(item.parts),
            item.as_posix(),
        ),
    )
    return ranked[:max_docs]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def build(manifest_path: Path = MANIFEST_PATH, dry_run: bool = False) -> dict[str, Any]:
    manifest = _load_manifest(manifest_path)

    max_total_docs = int(manifest.get("max_total_docs", 100))
    docs_written: list[dict[str, Any]] = []
    parents_written: dict[str, dict[str, Any]] = {}
    chunks_written: list[dict[str, Any]] = []
    lock_sources: list[dict[str, Any]] = []

    total_docs = 0

    for source in manifest.get("sources", []):
        source_name = str(source["name"])
        source_root = ROOT / str(source["repo_root"])
        source_license = str(source.get("license", "unknown"))
        include = list(source.get("include", []))
        exclude = list(source.get("exclude", []))
        keywords = list(source.get("priority_contains", []))
        max_docs = int(source.get("max_docs", 0))

        if not source_root.exists():
            lock_sources.append(
                {
                    "name": source_name,
                    "status": "missing_repo_root",
                    "repo_root": source_root.as_posix(),
                    "selected_files": [],
                }
            )
            continue

        discovered = _discover_source_files(source_root, include=include, exclude=exclude)
        selected = _select_curated(discovered, max_docs=max_docs, keywords=keywords)

        if total_docs >= max_total_docs:
            selected = []
        elif total_docs + len(selected) > max_total_docs:
            selected = selected[: max_total_docs - total_docs]

        lock_files: list[str] = []

        for file_path in selected:
            relative_path = file_path.relative_to(source_root).as_posix()
            lock_files.append(relative_path)

            content = file_path.read_text(encoding="utf-8", errors="ignore")
            if not content.strip():
                continue

            doc_id = _sha256_hex(f"{source_name}:{relative_path}")
            chunk_rows = chunk_document(content, max_chars=2200, overlap_chars=300)

            docs_written.append(
                {
                    "doc_id": doc_id,
                    "source": source_name,
                    "source_license": source_license,
                    "path": relative_path,
                    "chunk_count": len(chunk_rows),
                }
            )

            for row in chunk_rows:
                section_index = int(row["section_index"])
                chunk_index = int(row["chunk_index"])
                heading = str(row["heading"])
                parent_text = str(row.get("parent_text", "")).strip()
                chunk_text = str(row["text"])

                parent_id = _sha256_hex(f"{doc_id}:{section_index}")
                chunk_id = _sha256_hex(f"{parent_id}:{chunk_index}")

                if parent_id not in parents_written and parent_text:
                    parents_written[parent_id] = {
                        "parent_id": parent_id,
                        "doc_id": doc_id,
                        "source": source_name,
                        "source_license": source_license,
                        "path": relative_path,
                        "section_index": section_index,
                        "heading": heading,
                        "text": parent_text,
                        "char_count": len(parent_text),
                    }

                chunks_written.append(
                    {
                        "chunk_id": chunk_id,
                        "parent_id": parent_id,
                        "doc_id": doc_id,
                        "source": source_name,
                        "path": relative_path,
                        "section_index": section_index,
                        "chunk_index": chunk_index,
                        "heading": heading,
                        "text": chunk_text,
                        "char_count": len(chunk_text),
                    }
                )

            total_docs += 1

        lock_sources.append(
            {
                "name": source_name,
                "status": "ok",
                "repo_root": source_root.as_posix(),
                "selected_files": lock_files,
                "selected_count": len(lock_files),
            }
        )

    summary = {
        "manifest": manifest_path.as_posix(),
        "max_total_docs": max_total_docs,
        "selected_docs": len(docs_written),
        "selected_parents": len(parents_written),
        "selected_chunks": len(chunks_written),
        "sources": lock_sources,
    }

    if not dry_run:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _write_jsonl(DOCS_JSONL, docs_written)
        _write_jsonl(PARENTS_JSONL, list(parents_written.values()))
        _write_jsonl(CHUNKS_JSONL, chunks_written)
        LOCK_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build curated smart-home corpus artifacts.")
    parser.add_argument("--manifest", default=str(MANIFEST_PATH), help="Path to corpus manifest JSON.")
    parser.add_argument("--dry-run", action="store_true", help="Print summary without writing outputs.")
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    summary = build(manifest_path=manifest_path, dry_run=args.dry_run)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
