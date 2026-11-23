"""Hermetic fixtures: no network, no model download, in-memory Qdrant."""

import hashlib
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import pytest
from qdrant_client import AsyncQdrantClient, models

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "sample"


class FakeDense:
    """Deterministic bag-of-words hashing embedder (8 dims)."""

    dim = 8

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self.dim
            for tok in text.lower().split():
                vec[int(hashlib.md5(tok.encode()).hexdigest(), 16) % self.dim] += 1.0
            out.append(vec)
        return out

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]


class FakeSparse:
    def embed(self, texts: Sequence[str]) -> list[models.SparseVector]:
        out = []
        for text in texts:
            counts: dict[int, float] = {}
            for tok in text.lower().split():
                idx = int(hashlib.md5(tok.encode()).hexdigest(), 16) % 10_000
                counts[idx] = counts.get(idx, 0.0) + 1.0
            out.append(models.SparseVector(indices=list(counts), values=list(counts.values())))
        return out


@pytest.fixture
def sample_dir() -> Path:
    return SAMPLE_DIR


@pytest.fixture
async def memory_client() -> AsyncIterator[AsyncQdrantClient]:
    client = AsyncQdrantClient(location=":memory:")
    yield client
    await client.close()
