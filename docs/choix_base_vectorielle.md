# Choix de la base vectorielle — ThreatLens

**Décision : Qdrant v1.18.3** (image `qdrant/qdrant:v1.18.3`, client `qdrant-client==1.18.0`).

| Critère (fiche S1 §5) | Qdrant | Milvus | pgvector |
| --- | --- | --- | --- |
| Dense + sparse BM25 dans la même collection | Oui (vecteurs nommés `dense` + `bm25`, IDF côté serveur) | Oui | Non natif (BM25 via `tsvector`, fusion à coder) |
| Fusion RRF côté serveur | Oui (Query API, `prefetch`, depuis v1.10) | Oui | Non |
| Filtrage par métadonnées | Intégré au parcours HNSW (pas de perte de recall en post-filtrage) | Oui | Pré/post-filtrage SQL |
| Orchestration locale | 1 conteneur léger | Plusieurs services (etcd, MinIO) | Déjà présent avec PostgreSQL |
| Échelle visée (~10⁶ chunks) | Largement suffisant | Surdimensionné | Suffisant, mais hybride à la main |

**Pourquoi pas la v1.9.0 du template :** la Query API (`prefetch` + fusion RRF) n'existe qu'à partir de la v1.10. Avec la v1.9, la fusion devrait être codée côté client, en dupliquant l'index BM25 en mémoire comme dans `rag_hybrid_poc.py`.

**Paramètres :** distance Cosine (embeddings normalisés), HNSW `m=16`, `ef_construct=100`. Index de payload `keyword` sur `category`, `tactics`, `platforms`, `external_id`, `source`, `related_ids`.

**Mémoire estimée :** 21 047 vecteurs × 384 dimensions × 4 octets ≈ 32,3 Mo de vecteurs denses, plus le graphe HNSW (environ m × 2 liens × 4 octets par point, soit environ 2,7 Mo) et les payloads. Tout tient très largement dans 16 Go.
