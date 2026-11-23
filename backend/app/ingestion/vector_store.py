"""Qdrant collection setup and async batch indexing (dense + sparse BM25 named vectors)."""

import asyncio
import logging
import statistics
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from qdrant_client import AsyncQdrantClient, models

from app.ingestion.models import Chunk

logger = logging.getLogger(__name__)

DENSE = "dense"
SPARSE = "bm25"
INDEXED_FIELDS = ("category", "external_id", "tactics", "platforms", "source", "related_ids")


class DenseEmbedder(Protocol):
    dim: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class SparseEmbedder(Protocol):
    def embed(self, texts: Sequence[str]) -> list[models.SparseVector]: ...


class FastEmbedDense:
    """bge-small-en-v1.5 through ONNX Runtime (CPU, no PyTorch)."""

    def __init__(self, model_name: str, cache_dir: str | None = None) -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
        self.dim = len(next(iter(self._model.embed(["probe"]))))

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.embed(list(texts))]

    def embed_query(self, text: str) -> list[float]:
        return next(iter(self._model.query_embed(text))).tolist()


class FastEmbedSparse:
    """BM25 term weights computed client-side; IDF is applied by Qdrant (Modifier.IDF)."""

    def __init__(self, model_name: str, cache_dir: str | None = None) -> None:
        from fastembed import SparseTextEmbedding

        self._model = SparseTextEmbedding(model_name=model_name, cache_dir=cache_dir)

    def embed(self, texts: Sequence[str]) -> list[models.SparseVector]:
        return [
            models.SparseVector(indices=e.indices.tolist(), values=e.values.tolist())
            for e in self._model.embed(list(texts))
        ]

    def embed_query(self, text: str) -> models.SparseVector:
        e = next(iter(self._model.query_embed(text)))
        return models.SparseVector(indices=e.indices.tolist(), values=e.values.tolist())


async def ensure_collection(
    client: AsyncQdrantClient, name: str, dim: int, with_sparse: bool, recreate: bool = False
) -> None:
    exists = await client.collection_exists(name)
    if exists and recreate:
        await client.delete_collection(name)
        exists = False
    if exists:
        logger.info("Collection '%s' already exists (upsert is idempotent).", name)
        return
    await client.create_collection(
        collection_name=name,
        vectors_config={
            DENSE: models.VectorParams(
                size=dim,
                distance=models.Distance.COSINE,
                hnsw_config=models.HnswConfigDiff(m=16, ef_construct=100),
            )
        },
        sparse_vectors_config=(
            {SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)}
            if with_sparse
            else None
        ),
    )
    for field_name in INDEXED_FIELDS:
        await client.create_payload_index(
            collection_name=name,
            field_name=field_name,
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
    logger.info("Collection '%s' created (dim=%d, Cosine, HNSW m=16 ef=100).", name, dim)


@dataclass
class IndexStats:
    points: int = 0
    batches: int = 0
    embed_seconds: float = 0.0
    upsert_ms: list[float] = field(default_factory=list)

    def summary(self) -> dict[str, float | int]:
        ms = sorted(self.upsert_ms) or [0.0]
        return {
            "points": self.points,
            "batches": self.batches,
            "embed_seconds": round(self.embed_seconds, 1),
            "upsert_ms_p50": round(statistics.median(ms), 1),
            "upsert_ms_p95": round(ms[int(0.95 * (len(ms) - 1))], 1),
        }


async def index_chunks(
    client: AsyncQdrantClient,
    collection: str,
    chunks: Sequence[Chunk],
    dense: DenseEmbedder,
    sparse: SparseEmbedder | None,
    batch_size: int = 64,
) -> IndexStats:
    """Embed in a worker thread (CPU-bound, keeps the event loop free) then upsert by batch."""
    stats = IndexStats()
    total = len(chunks)
    for start in range(0, total, batch_size):
        batch = chunks[start : start + batch_size]
        texts = [c.content for c in batch]

        t0 = time.perf_counter()
        dense_vecs = await asyncio.to_thread(dense.embed, texts)
        sparse_vecs = await asyncio.to_thread(sparse.embed, texts) if sparse else None
        stats.embed_seconds += time.perf_counter() - t0

        points = []
        for i, chunk in enumerate(batch):
            vector: dict[str, Any] = {DENSE: dense_vecs[i]}
            if sparse_vecs is not None:
                vector[SPARSE] = sparse_vecs[i]
            points.append(
                models.PointStruct(id=chunk.point_id, vector=vector, payload=chunk.payload)
            )

        t1 = time.perf_counter()
        await client.upsert(collection_name=collection, points=points, wait=True)
        stats.upsert_ms.append((time.perf_counter() - t1) * 1000)
        stats.points += len(points)
        stats.batches += 1
        if stats.batches % 20 == 0 or stats.points == total:
            logger.info("Indexed %d / %d chunks", stats.points, total)
    return stats
