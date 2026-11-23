from pathlib import Path

from qdrant_client import AsyncQdrantClient, models

from app.ingestion.chunking import chunk_documents
from app.ingestion.parsers import load_stix_objects, parse_attack
from app.ingestion.vector_store import DENSE, SPARSE, ensure_collection, index_chunks
from tests.conftest import FakeDense, FakeSparse


async def _index(client: AsyncQdrantClient, sample_dir: Path) -> int:
    docs = list(parse_attack(load_stix_objects(next(sample_dir.glob("enterprise-attack*.json")))))
    chunks = list(chunk_documents(docs, 300))
    await ensure_collection(client, "kb", FakeDense.dim, with_sparse=True)
    stats = await index_chunks(client, "kb", chunks, FakeDense(), FakeSparse(), batch_size=64)
    assert stats.batches == -(-len(chunks) // 64)
    return len(chunks)


async def test_index_and_filtered_search(
    memory_client: AsyncQdrantClient, sample_dir: Path
) -> None:
    n = await _index(memory_client, sample_dir)
    assert (await memory_client.count("kb", exact=True)).count == n

    flt = models.Filter(
        must=[
            models.FieldCondition(key="category", match=models.MatchValue(value="technique")),
            models.FieldCondition(key="tactics", match=models.MatchValue(value="execution")),
        ]
    )
    res = await memory_client.query_points(
        "kb", query=FakeDense().embed_query("powershell"), using=DENSE, query_filter=flt, limit=5
    )
    assert res.points
    assert all(p.payload and p.payload["category"] == "technique" for p in res.points)
    assert all(p.payload and "execution" in p.payload["tactics"] for p in res.points)


async def test_reingestion_is_idempotent(
    memory_client: AsyncQdrantClient, sample_dir: Path
) -> None:
    n = await _index(memory_client, sample_dir)
    await _index(memory_client, sample_dir)
    assert (await memory_client.count("kb", exact=True)).count == n


async def test_sparse_finds_exact_identifier(
    memory_client: AsyncQdrantClient, sample_dir: Path
) -> None:
    await _index(memory_client, sample_dir)
    query = FakeSparse().embed(["t1059.001"])[0]
    res = await memory_client.query_points("kb", query=query, using=SPARSE, limit=3)
    assert res.points and res.points[0].payload
    assert res.points[0].payload["external_id"] == "T1059.001"
