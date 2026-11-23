# Fiche de Cadrage d'Ingénierie — Projet Fédérateur AI-BD_BI
## ThreatLens — Copilote RAG pour analystes SOC

> Gabarit : `Seance_01_Ideation_Cadrage_RAG/templates/fiche_cadrage_projet.md`. Tous les chiffres marqués *(mesuré)* sortent des scripts du dépôt (`scripts/ingest.py`, `data/processed/ingest_report_*.json`).

---

### 1. Fiche d'identité du projet

- **Nom du projet :** `ThreatLens`
- **Membres de l'équipe :**
  1. *[Nom Prénom]* — Lead Data / Retrieval (ingestion, Qdrant, évaluation)
  2. *[Nom Prénom]* — Lead Backend / MLOps (FastAPI, SSE, CI/CD, Docker)
  3. *[Nom Prénom]* — Lead Frontend / Infra (Next.js, Source Drawer, K8s) *(si trinôme)*
- **Dépôt GitHub :** `https://github.com/<organisation>/threatlens`
- **Branche principale :** `main` (protégée, merge via PR + CI verte)

---

### 2. Cadrage du problème métier (« Problem-First »)

#### 2.1 Persona cible et contexte opérationnel

- **Utilisateur visé :** analyste SOC niveau 1/2 (centre de sécurité d'une banque, d'un opérateur télécom ou d'une administration).
- **Point de douleur :** pour chaque rapport de menace ou avis CVE reçu, l'analyste doit retrouver à la main dans ATT&CK (706 techniques et sous-techniques *(mesuré)*) les techniques en jeu, la faiblesse CWE en cause et les mesures de protection. Il doit ensuite justifier chaque correspondance dans son ticket. C'est long, variable d'un analyste à l'autre, et les rapports arrivent souvent en français alors que les référentiels sont en anglais.
- **Pourquoi la recherche classique échoue :**
  - *Le mot-clé seul (Ctrl+F, Elasticsearch)* rate le sens. Un rapport écrit « script PowerShell encodé lancé depuis une macro » : le texte de T1059.001 ne contient ni « macro » ni « encodé », et il est en anglais.
  - *Le sémantique seul (embeddings)* rate les identifiants exacts : `T1059.001`, `CWE-79`, `CVE-2024-23848` sont mal représentés par un modèle dense.
  - **Il faut donc une recherche hybride** (dense + BM25), un reranker, et une réponse générée qui cite ses sources pour être vérifiable.

#### 2.2 Proposition de valeur

À partir d'un rapport collé (FR ou EN), ThreatLens renvoie en streaming les techniques ATT&CK (badges `T####`), la faiblesse CWE et les mitigations. **Chaque assertion porte une citation cliquable** (Source Drawer : fiche d'origine, `stix_id`, score). Une carte ATT&CK colorée résume le rapport. En sortie, ThreatLens propose un **plan de protection priorisé** en trois volets (*bloquer*, *détecter*, *corriger*). Il est construit à partir des relations expertes de MITRE (1 477 relations `mitigates`, 706 detection strategies *(mesuré)*), classé par couverture des techniques détectées, et chaque recommandation est citée. L'analyste reste décisionnaire. Le gain se mesure sur le Golden Dataset CTIBench, face à une baseline « LLM sans RAG ».

---

### 3. Données et volumétrie

- **Format des sources :** `[x] JSON (STIX 2.1)` `[x] XML (CWE)` `[x] TSV (CTIBench)` `[ ] PDF` `[ ] SQL`

| Source | Version figée | Format | Rôle |
| --- | --- | --- | --- |
| MITRE ATT&CK Enterprise | v20.1 (bundle du 05/11/2026) | JSON STIX 2.1, 55 Mo | Corpus |
| CAPEC | v3.9 | JSON STIX 2.1, 4,5 Mo | Corpus (pont CWE ↔ ATT&CK) |
| CWE | version notée dans `data/MANIFEST.json` au téléchargement | XML | Corpus |
| CTIBench (AI4Sec, CC BY-NC-SA 4.0) | sha256 dans `data/MANIFEST.json` | TSV | **Golden Dataset, jamais indexé** |

- **Volumétrie initiale (PoC S1-S3) :** 20 021 documents → **20 079 chunks** *(mesuré, hors CWE)* : 17 636 procedure examples, 842 logiciels, 750 chunks de techniques, 558 CAPEC, 178 groupes, 58 mitigations, 57 campagnes. Le catalogue CWE ajoutera environ un millier d'entrées (nombre exact produit par `ingest.py`).
- **Volumétrie cible en production :** environ 10⁶ chunks, avec la base NVD (plusieurs centaines de milliers de CVE) et les rapports CTI internes. Garde-fou : les CVE de CTIBench sont exclues du corpus, sinon fuite de la vérité terrain.
- **Fréquence de mise à jour :** `[x] Batch` : ATT&CK semestriel plus releases « agiles », CWE et CAPEC trimestriel, NVD quotidien en cible. L'ingestion est idempotente (IDs UUID5 déterministes), donc une mise à jour = un upsert.

---

### 4. Architecture technique et composants RAG

- **Stratégie de chunking :** `[x] Structure-aware` (1 objet de connaissance = 1 chunk)
  - Chaque chunk commence par un **en-tête contextuel** : `[technique] T1059.001 PowerShell | tactics: execution | platforms: Windows, Linux, macOS`.
  - Découpage aux frontières de phrase **seulement au-delà de 300 mots** (limite de 512 tokens du modèle) : 58 documents sur 20 021 sont concernés *(mesuré)*.
  - Les procedure examples sont des chunks à part : ce sont les phrases les plus proches d'un rapport réel.
  - Nettoyage : suppression des `(Citation: …)`, des liens markdown et des balises HTML.
  - *Benchmark S2 → S3 :* 300 mots (20 079 chunks) contre 120 mots (20 867 chunks, 630 documents découpés) *(mesuré)*, Recall@5 sur 10 questions.
- **Modèle d'embeddings :** `BAAI/bge-small-en-v1.5` (dimension 384), via **fastembed / ONNX Runtime sur CPU, sans PyTorch**. Raison : machine sans GPU et image Docker < 350 Mo exigée en S7.
  - Rapports en français : une étape de **réécriture de requête FR → EN** par le LLM, qui conserve les identifiants extraits par regex. Elle sera comparée à un modèle multilingue sur un sous-ensemble traduit de cti-rcm.
- **Recherche lexicale :** BM25 sparse calculé par fastembed (`Qdrant/bm25`), IDF appliquée côté Qdrant, fusion **RRF** côté serveur (Query API, `prefetch`).
- **Base vectorielle retenue :** `[x] Qdrant v1.18.3`, voir `docs/choix_base_vectorielle.md`.
  - *Justification :* dense et sparse dans la même collection, fusion RRF native, filtrage par payload (`category`, `tactics`, `platforms`) intégré au parcours HNSW, un seul conteneur léger.
- **Reranker (Cross-Encoder) :** `BAAI/bge-reranker-base` (imposé), Top-20 → Top-5.
- **Expansion GraphRAG :** relations STIX `uses`, `mitigates`, `subtechnique-of` stockées dans PostgreSQL, 1 saut après le reranking.
- **Plan de protection (US-20) :** classement déterministe et explicable des mitigations : score(m) = Σ confiance(t) sur les techniques détectées t que m atténue. Les detection strategies servent pour « détecter », les mitigations CWE pour « corriger ». Le LLM rédige le plan à partir de ce classement, avec citations. Pas de modèle de recommandation entraîné : aucune donnée étiquetée publique fiable n'existe pour en entraîner un.
- **LLM de génération :** **Groq** (API compatible OpenAI, TTFT faible, bon niveau en français), avec **Ollama** en secours local hors-ligne. Le modèle exact sera figé en S4.

---

### 5. Métriques quantitatives et SLAs

Évaluation sur CTIBench, hors Pytest (`scripts/evaluate.py`, S3). Résultats versionnés en JSON/CSV. Progression mesurée : sans RAG → dense → hybride → + reranker → + graphe.

| Métrique | Définition / outil | Cible (KPI) |
| --- | --- | :---: |
| **Recall@5 / Recall@10** | Fiche CWE de vérité dans le top-k (cti-rcm, 1 000 CVE 2024) | ≥ 80 % / ≥ 85 % |
| **MRR** | Rang moyen inverse de la bonne fiche | ≥ 0,60 |
| **Accuracy CVE → CWE** | Réponse finale = CWE de vérité ; à comparer à la **baseline majoritaire (toujours CWE-79) = 22,9 %** *(mesuré)* et au LLM sans RAG | > LLM sans RAG, sur 2021 et 2024 |
| **Micro-F1 rapport → techniques** | cti-ate, 47 lignes Enterprise, au niveau technique parent, **entité source exclue du corpus** (anti-fuite) | > LLM sans RAG |
| **Précision@5 du plan de protection** | Mitigations proposées ∈ mitigations ATT&CK des techniques de vérité (cti-ate) | ≥ 70 % |
| **Faithfulness (Ragas)** | Assertions soutenues par le contexte | ≥ 0,85 |
| **Answer Relevance (Ragas)** | Adéquation à la question | ≥ 0,80 |
| **Context Recall (Ragas)** | Le contexte couvre la vérité | ≥ 0,80 |
| **Latence retrieval** | Embedding + hybride + RRF | < 200 ms |
| **Latence reranker** | Cross-Encoder sur 20 paires, CPU | < 150 ms (cible à vérifier sur CPU, mesurée et publiée) |
| **TTFT** | Premier token en streaming SSE | < 800 ms |
| **Latence E2E P95** | Requête complète | < 3,5 s |

---

### 6. Gestion des risques et garde-fous

- **Hallucinations :**
  - Directive système : *« Si l'information n'est pas présente dans les extraits ci-dessus, réponds explicitement que le corpus ne permet pas de conclure. »*
  - Citation obligatoire pour chaque technique ou CWE.
  - **Vérification après génération :** tout identifiant `T####` / `CWE-###` cité qui n'est pas dans le contexte récupéré est retiré et signalé.
- **Données sensibles (PII / IOC) :** un rapport collé contient des IP, des noms d'hôtes et des e-mails internes. Ils sont **masqués par regex avant tout appel au LLM cloud**. Le mode Ollama permet de traiter un rapport sans aucune sortie réseau.
- **Injection de prompt :** le rapport collé est un contenu non fiable. Il est délimité et traité comme des données, jamais comme des instructions.
- **Secrets :** uniquement dans `.env` (ignoré par Git), `.env.example` sans valeur ; Secrets K8s et secrets GitHub Actions ; gitleaks en CI (S6).
- **Isolation réseau :** Qdrant et PostgreSQL sur un réseau Docker interne, ports liés à `127.0.0.1` uniquement.
- **Fuite d'évaluation :** CTIBench n'est jamais indexé, et les entités sources de cti-ate sont exclues pendant l'évaluation.
