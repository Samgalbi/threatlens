"""Structure-aware chunking: one knowledge object = one chunk, split only when too long.

Every slice repeats a contextual header (id, name, tactics...) so that a slice
retrieved alone still says which technique / weakness it belongs to.
"""

import re
import uuid
from collections.abc import Iterable, Iterator

from app.ingestion.cleaning import word_count
from app.ingestion.models import Chunk, SourceDocument

# Fixed namespace -> same input always gives the same point id (idempotent re-ingestion).
POINT_NAMESPACE = uuid.UUID("6f1c2b7e-3a51-4d0b-9a8e-2c9f0e4d7a11")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")

# bge-small-en-v1.5 truncates at 512 tokens; ~300 English words ~ 400 tokens + header.
DEFAULT_MAX_WORDS = 300


def build_header(doc: SourceDocument) -> str:
    parts = [f"[{doc.category}] {doc.external_id} {doc.name}"]
    if doc.tactics:
        parts.append("tactics: " + ", ".join(doc.tactics))
    if doc.platforms:
        parts.append("platforms: " + ", ".join(doc.platforms))
    if doc.related_ids and doc.category in {"capec", "procedure"}:
        parts.append("related: " + ", ".join(doc.related_ids[:12]))
    return " | ".join(parts)


def split_body(text: str, max_words: int) -> list[str]:
    """Split on sentence boundaries, never inside a sentence."""
    if word_count(text) <= max_words:
        return [text]
    slices: list[str] = []
    current: list[str] = []
    size = 0
    for sentence in _SENTENCE.split(text):
        n = word_count(sentence)
        if current and size + n > max_words:
            slices.append(" ".join(current))
            current, size = [], 0
        current.append(sentence)
        size += n
    if current:
        slices.append(" ".join(current))
    return slices


def chunk_document(doc: SourceDocument, max_words: int = DEFAULT_MAX_WORDS) -> list[Chunk]:
    header = build_header(doc)
    bodies = split_body(doc.text, max_words) if doc.text else [""]
    total = len(bodies)
    chunks: list[Chunk] = []
    for page, body in enumerate(bodies, start=1):
        content = f"{header}\n{body}".strip()
        chunk_id = f"{doc.doc_id}#{page}"
        payload: dict[str, object] = {
            "doc_id": doc.doc_id,
            "chunk_id": chunk_id,
            "external_id": doc.external_id,
            "name": doc.name,
            "category": doc.category,
            "source": doc.source,
            "url": doc.url,
            "page": page,
            "total_pages": total,
            "date": doc.date,
            "tactics": doc.tactics,
            "platforms": doc.platforms,
            "is_subtechnique": doc.is_subtechnique,
            "related_ids": doc.related_ids,
            "content": content,
            "char_count": len(content),
        }
        chunks.append(
            Chunk(
                point_id=str(uuid.uuid5(POINT_NAMESPACE, chunk_id)),
                doc_id=doc.doc_id,
                page=page,
                total_pages=total,
                content=content,
                payload=payload,
            )
        )
    return chunks


def chunk_documents(docs: Iterable[SourceDocument], max_words: int) -> Iterator[Chunk]:
    for doc in docs:
        yield from chunk_document(doc, max_words)
