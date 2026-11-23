"""Index ATT&CK (+ procedure examples), CAPEC and CWE into Qdrant.

Usage:
  python scripts/ingest.py                       # full corpus, dense + BM25 sparse
  python scripts/ingest.py --recreate            # drop and rebuild the collection
  python scripts/ingest.py --max-words 120 --collection threatlens_kb_w120   # chunking benchmark
  python scripts/ingest.py --raw-dir data/raw/sample                         # quick sample run
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from collections import Counter
from pathlib import Path

from qdrant_client import AsyncQdrantClient

from app.core.config import get_settings
from app.ingestion.chunking import DEFAULT_MAX_WORDS, chunk_documents
from app.ingestion.models import SourceDocument
from app.ingestion.parsers import load_stix_objects, parse_attack, parse_capec, parse_cwe
from app.ingestion.vector_store import (
    FastEmbedDense,
    FastEmbedSparse,
    ensure_collection,
    index_chunks,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ingest")


def collect_documents(raw_dir: Path) -> tuple[list[SourceDocument], dict[str, str]]:
    """Parse every available source; a missing or broken file is logged, not fatal."""
    docs: list[SourceDocument] = []
    sources: dict[str, str] = {}

    for path in sorted(raw_dir.glob("enterprise-attack*.json")):
        try:
            parsed = list(parse_attack(load_stix_objects(path)))
            docs += parsed
            sources[path.name] = parsed[0].source if parsed else "empty"
        except (OSError, ValueError) as exc:
            logger.error("ATT&CK parse failed for %s: %s", path, exc)

    for path in sorted(raw_dir.glob("*capec*.json")):
        try:
            parsed = list(parse_capec(load_stix_objects(path)))
            docs += parsed
            sources[path.name] = parsed[0].source if parsed else "empty"
        except (OSError, ValueError) as exc:
            logger.error("CAPEC parse failed for %s: %s", path, exc)

    # Non-recursive on purpose: a recursive glob would also pick up data/raw/sample/.
    cwe_paths = {*raw_dir.glob("cwe/cwec*.xml"), *raw_dir.glob("cwec*.xml")}
    for path in sorted(cwe_paths):
        try:
            parsed = list(parse_cwe(path))
            docs += parsed
            sources[path.name] = parsed[0].source if parsed else "empty"
        except Exception as exc:  # malformed XML
            logger.error("CWE parse failed for %s: %s", path, exc)

    return docs, sources


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    collection = args.collection or settings.qdrant_collection_name
    docs, sources = collect_documents(Path(args.raw_dir))
    if not docs:
        logger.error("No document found in %s. Run scripts/download_data.py first.", args.raw_dir)
        return 1

    chunks = list(chunk_documents(docs, args.max_words))
    by_category = Counter(c.payload["category"] for c in chunks)
    split_docs = sum(1 for c in chunks if c.page == 2)
    logger.info("%d documents -> %d chunks %s", len(docs), len(chunks), dict(by_category))

    logger.info(
        "Loading embedding models (first run downloads them to %s)", settings.fastembed_cache_path
    )
    dense = FastEmbedDense(settings.embedding_model_name, settings.fastembed_cache_path)
    sparse = (
        None
        if args.no_sparse
        else FastEmbedSparse(settings.sparse_model_name, settings.fastembed_cache_path)
    )

    client = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)
    try:
        await ensure_collection(client, collection, dense.dim, sparse is not None, args.recreate)
        t0 = time.perf_counter()
        stats = await index_chunks(client, collection, chunks, dense, sparse, args.batch_size)
        elapsed = time.perf_counter() - t0
        count = (await client.count(collection_name=collection, exact=True)).count
    finally:
        await client.close()

    report = {
        "collection": collection,
        "sources": sources,
        "embedding_model": settings.embedding_model_name,
        "sparse_model": None if sparse is None else settings.sparse_model_name,
        "max_words": args.max_words,
        "documents": len(docs),
        "chunks": len(chunks),
        "documents_split": split_docs,
        "chunks_by_category": dict(by_category),
        "points_in_collection": count,
        "total_seconds": round(elapsed, 1),
        **stats.summary(),
    }
    out = Path(settings.processed_data_dir) / f"ingest_report_{collection}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("Done: %s", json.dumps(report))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--collection", default=None)
    parser.add_argument("--max-words", type=int, default=DEFAULT_MAX_WORDS)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--no-sparse", action="store_true", help="dense vectors only")
    parser.add_argument("--recreate", action="store_true")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
