"""Top-k retrieval check for the S2 demo (with payload filters).

Examples:
  python scripts/search_test.py --query "steal web browser cookies to hijack sessions"
  python scripts/search_test.py --query "encoded powershell download cradle" --category technique --tactic execution
  python scripts/search_test.py --query "T1059.001" --mode sparse
  python scripts/search_test.py --query "SQL injection in login form" --category cwe --mode hybrid
"""

import argparse
import sys
import time

from qdrant_client import QdrantClient, models

from app.core.config import get_settings
from app.ingestion.vector_store import DENSE, SPARSE, FastEmbedDense, FastEmbedSparse

CATEGORIES = [
    "technique",
    "mitigation",
    "group",
    "software",
    "campaign",
    "procedure",
    "capec",
    "cwe",
]


def build_filter(args: argparse.Namespace) -> models.Filter | None:
    must: list[models.Condition] = []
    if args.category:
        must.append(models.FieldCondition(key="category", match=models.MatchAny(any=args.category)))
    if args.tactic:
        must.append(
            models.FieldCondition(key="tactics", match=models.MatchValue(value=args.tactic))
        )
    if args.platform:
        must.append(
            models.FieldCondition(key="platforms", match=models.MatchValue(value=args.platform))
        )
    return models.Filter(must=must) if must else None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--query", required=True)
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--category", nargs="*", choices=CATEGORIES)
    p.add_argument("--tactic", help="e.g. execution, credential-access, stealth")
    p.add_argument("--platform", help="e.g. Windows, Linux, macOS")
    p.add_argument("--mode", choices=["dense", "sparse", "hybrid"], default="dense")
    p.add_argument("--collection", default=None)
    args = p.parse_args()

    s = get_settings()
    collection = args.collection or s.qdrant_collection_name
    client = QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key or None)
    flt = build_filter(args)

    t0 = time.perf_counter()
    dense_q = (
        FastEmbedDense(s.embedding_model_name, s.fastembed_cache_path).embed_query(args.query)
        if args.mode in {"dense", "hybrid"}
        else None
    )
    sparse_q = (
        FastEmbedSparse(s.sparse_model_name, s.fastembed_cache_path).embed_query(args.query)
        if args.mode in {"sparse", "hybrid"}
        else None
    )
    t_embed = (time.perf_counter() - t0) * 1000

    t1 = time.perf_counter()
    if args.mode == "dense":
        res = client.query_points(
            collection,
            query=dense_q,
            using=DENSE,
            query_filter=flt,
            limit=args.top_k,
            with_payload=True,
        )
    elif args.mode == "sparse":
        res = client.query_points(
            collection,
            query=sparse_q,
            using=SPARSE,
            query_filter=flt,
            limit=args.top_k,
            with_payload=True,
        )
    else:  # server-side Reciprocal Rank Fusion (Qdrant Query API, >= 1.10)
        res = client.query_points(
            collection,
            prefetch=[
                models.Prefetch(query=dense_q, using=DENSE, filter=flt, limit=20),
                models.Prefetch(query=sparse_q, using=SPARSE, filter=flt, limit=20),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=args.top_k,
            with_payload=True,
        )
    t_search = (time.perf_counter() - t1) * 1000

    score_name = {"dense": "cosine", "sparse": "bm25", "hybrid": "rrf"}[args.mode]
    print("\n" + "=" * 100)
    print(
        f"Query: {args.query!r} | mode={args.mode} | filter={flt.model_dump(exclude_none=True) if flt else None}"
    )
    print(f"Collection: {collection} | points: {client.count(collection, exact=True).count}")
    print(
        f"Latency: query embedding {t_embed:.0f} ms (incl. model load) | Qdrant search {t_search:.1f} ms"
    )
    print("=" * 100)
    for rank, pt in enumerate(res.points, start=1):
        pl = pt.payload or {}
        tactics = ",".join(pl.get("tactics") or []) or "-"
        print(f"\n[{rank}] {score_name}={pt.score:.4f} | {pl.get('external_id')} {pl.get('name')}")
        print(
            f"    category={pl.get('category')} | tactics={tactics} | page={pl.get('page')}/{pl.get('total_pages')}"
            f" | source={pl.get('source')}"
        )
        print(f"    url={pl.get('url')}")
        body = str(pl.get("content", "")).split("\n", 1)[-1]
        print(f"    {body[:240]}{'...' if len(body) > 240 else ''}")
    print("\n" + "=" * 100)
    return 0


if __name__ == "__main__":
    sys.exit(main())
