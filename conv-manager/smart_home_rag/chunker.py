from __future__ import annotations

import re
from dataclasses import dataclass

_FRONTMATTER_BOUNDARY = "---"
_FENCE_RE = re.compile(r"^\s*```")
_HEADING_RE = re.compile(r"^(#{2,3})\s+(.+)$")


@dataclass
class Section:
    heading: str
    body: str


def strip_frontmatter(markdown: str) -> str:
    """Strip YAML frontmatter if present at the top of a markdown file."""
    text = markdown.lstrip("\ufeff")
    lines = text.splitlines()
    if len(lines) < 3:
        return text

    if lines[0].strip() != _FRONTMATTER_BOUNDARY:
        return text

    for idx in range(1, len(lines)):
        if lines[idx].strip() == _FRONTMATTER_BOUNDARY:
            return "\n".join(lines[idx + 1 :]).lstrip("\n")

    return text


def split_sections(markdown: str) -> list[Section]:
    """Split markdown into H2/H3 sections without splitting inside fenced code blocks."""
    lines = markdown.splitlines()
    sections: list[Section] = []
    in_fence = False

    current_heading = "Document Introduction"
    current_lines: list[str] = []

    for line in lines:
        if _FENCE_RE.match(line):
            in_fence = not in_fence

        heading_match = _HEADING_RE.match(line)
        if not in_fence and heading_match:
            body = "\n".join(current_lines).strip()
            if body:
                sections.append(Section(heading=current_heading, body=body))
            current_heading = heading_match.group(2).strip()
            current_lines = []
            continue

        current_lines.append(line)

    tail = "\n".join(current_lines).strip()
    if tail:
        sections.append(Section(heading=current_heading, body=tail))

    return sections


def _split_long_text(text: str, max_chars: int) -> list[str]:
    """Split oversized prose blocks on line boundaries."""
    if len(text) <= max_chars:
        return [text]

    parts: list[str] = []
    lines = text.splitlines(keepends=True)
    bucket: list[str] = []
    size = 0

    for line in lines:
        if size + len(line) > max_chars and bucket:
            parts.append("".join(bucket).strip())
            bucket = []
            size = 0
        bucket.append(line)
        size += len(line)

    if bucket:
        parts.append("".join(bucket).strip())

    return [part for part in parts if part]


def _to_blocks_preserve_fences(text: str) -> list[str]:
    """Convert section text into blocks; fenced code remains a single unsplittable block."""
    blocks: list[str] = []
    lines = text.splitlines()

    in_fence = False
    block: list[str] = []

    def flush() -> None:
        nonlocal block
        joined = "\n".join(block).strip()
        if joined:
            blocks.append(joined)
        block = []

    for line in lines:
        if _FENCE_RE.match(line):
            if not in_fence and block:
                flush()
            in_fence = not in_fence
            block.append(line)
            if not in_fence:
                flush()
            continue

        if in_fence:
            block.append(line)
            continue

        if line.strip() == "":
            flush()
            continue

        block.append(line)

    flush()

    expanded: list[str] = []
    for item in blocks:
        if item.startswith("```") and item.endswith("```"):
            expanded.append(item)
        else:
            expanded.extend(_split_long_text(item, max_chars=1800))

    return [item for item in expanded if item]


def chunk_section(section_text: str, max_chars: int = 2200, overlap_chars: int = 300) -> list[str]:
    """Pack section blocks into overlapping chunks while preserving fenced code blocks."""
    blocks = _to_blocks_preserve_fences(section_text)
    if not blocks:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_size = 0

    for block in blocks:
        block_len = len(block)
        if current and current_size + block_len + 2 > max_chars:
            chunk_text = "\n\n".join(current).strip()
            chunks.append(chunk_text)

            overlap: list[str] = []
            overlap_size = 0
            for existing in reversed(current):
                candidate = len(existing) + (2 if overlap else 0)
                if overlap and overlap_size + candidate > overlap_chars:
                    break
                overlap.insert(0, existing)
                overlap_size += candidate

            current = overlap
            current_size = sum(len(x) for x in current) + max(0, 2 * (len(current) - 1))

        current.append(block)
        current_size += block_len + (2 if len(current) > 1 else 0)

    if current:
        chunks.append("\n\n".join(current).strip())

    return chunks


def chunk_document(markdown: str, max_chars: int = 2200, overlap_chars: int = 300) -> list[dict]:
    """Return section-aware chunk records for a full markdown document."""
    cleaned = strip_frontmatter(markdown)
    sections = split_sections(cleaned)

    chunk_records: list[dict] = []
    for section_index, section in enumerate(sections):
        section_text = f"## {section.heading}\n\n{section.body.strip()}"
        section_chunks = chunk_section(section_text, max_chars=max_chars, overlap_chars=overlap_chars)
        for chunk_index, chunk_text in enumerate(section_chunks):
            chunk_records.append(
                {
                    "section_index": section_index,
                    "chunk_index": chunk_index,
                    "heading": section.heading,
                    "parent_text": section_text,
                    "text": chunk_text,
                }
            )

    return chunk_records
