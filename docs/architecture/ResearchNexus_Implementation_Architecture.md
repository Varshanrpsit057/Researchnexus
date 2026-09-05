# ResearchNexus — Implementation Architecture

**Purpose.** Convert the completed 2022–2026 literature review into a concrete, build-ready architecture. This document is the engineering blueprint; it does **not** modify or add application source code.

**Companion documents**
- Literature review: `docs/literature-review/ResearchNexus_Literature_Review_2022_2026.md` (cited below as *[review §N]*; paper short-names as `[PaperQA2]` etc., keyed to review §29).
- Prior design: `docs/architecture/ResearchNexus_Seed_Paper_Research_Trail.md` (this document makes it concrete; where they overlap, this one is authoritative for module/stack decisions).
- Data model: `docs/architecture/ResearchNexus_Data_Model.md`
- API: `docs/architecture/ResearchNexus_API_Specification.md`
- Roadmap: `docs/architecture/ResearchNexus_Implementation_Roadmap.md`
- Evaluation: `docs/evaluation/ResearchNexus_Evaluation_Plan.md`

**Repository state (verified).** Greenfield. The repo contains only `Untitled document.pdf` (the abstract), the three review/design docs above, and `.semgrep/`. There is **no** application code, `package.json`, `pyproject.toml`, `requirements.txt`, `README.md`, project `CLAUDE.md`, tests, or CI. Everything below is to-be-built.

---

## 0. Framing (from the literature review — used consistently)

Individual components are **established** and are **not claimed as novel**: scientific RAG, semantic/dense scholarly retrieval, FAISS, local embeddings, PDF processing, LLM summarisation, single/multi-paper QA, comparison tables, citation grounding, agentic paper search, research-idea generation *[review §21, §22]*.

The defensible ResearchNexus contribution is the **integrated workflow**:

> Seed Paper → Research Profile → Multi-Strategy Discovery → Transparent Explained Ranking → Typed Research Trail → Persistent Multi-Paper Workspace → Verified RAG → Comparison → Evidence-Grounded Confidence-Labelled Gap Objects → Research Directions → Deterministic Citations → Presentation

with four particularly important contribution areas *[review §21]*:

1. **Auditable multi-signal related-paper ranking with per-paper reasons.**
2. **Typed, evidence-carrying research trail.**
3. **Structured, evidence-grounded, confidence-labelled research-gap objects.**
4. **End-to-end evaluation of the complete workflow** (not stage-by-stage).

Every architectural decision below carries a rationale traceable to the review, the abstract's requirements, or an explicit engineering reason.

---

## 1. Layered architecture (A–I)

```
┌────────────────────────────────────────────────────────────────────────────┐
│ A. PRESENTATION / UI                                                         │
│   MVP: Streamlit app (calls the API)   ·   Later: Next.js/React SPA          │
│   Screens: Upload · Paper Analysis · Discover (per-strategy progress) ·      │
│            Research Trail (grouped by type) · Selection · Workspace tabs     │
└───────────────┬────────────────────────────────────────────────────────────┘
                │ HTTPS / JSON · SSE for chat · job-poll for long tasks
┌───────────────▼────────────────────────────────────────────────────────────┐
│ B. APPLICATION / API LAYER  (FastAPI)                                        │
│   Auth · request/response schemas (Pydantic) · async job submission +       │
│   status · SSE streaming · rate limiting · tenant scoping · error mapping    │
└───────────────┬────────────────────────────────────────────────────────────┘
                │ in-process calls (MVP) / task queue (research/prod)
┌───────────────▼────────────────────────────────────────────────────────────┐
│ E. AGENT / ORCHESTRATION LAYER  (hand-written, bounded plan)                 │
│   ResearchOrchestrator: fixed workflow DAG + a few bounded decisions        │
│   (how many discovery strategies · one extra citation hop iff recall low ·  │
│    regenerate-once on failed faithfulness gate · answer vs "I don't know")   │
│   Typed tool registry · per-workspace token/USD budget guard · tool_log     │
└───┬───────────────┬────────────────────┬───────────────────┬───────────────┘
    │               │                    │                   │
┌───▼─────────┐ ┌───▼──────────────┐ ┌───▼───────────────┐ ┌─▼───────────────┐
│ C. DETERM-  │ │ D. RETRIEVAL     │ │ F. LLM LAYER      │ │ H. EXTERNAL      │
│ INISTIC     │ │  embeddings      │ │  provider-agnostic│ │ ACADEMIC SEARCH  │
│ PROCESSING  │ │  (MiniLM chunk,  │ │  client (BYOK)    │ │  arXiv API       │
│  pdf load / │ │   SPECTER2 doc)  │ │  OpenAI-compat +  │ │  OpenAlex        │
│  clean /    │ │  FAISS IndexFlat │ │  Gemini adapters  │ │  Semantic Scholar│
│  section    │ │  IP + metadata   │ │  JSON/function    │ │  Crossref        │
│  split /    │ │  sidecar + LRU   │ │  output → Pydantic│ │  (fixed allow-   │
│  table      │ │  BM25 (rank-bm25 │ │  validate + 1     │ │   list, retry,   │
│  extract /  │ │   / Tantivy)     │ │  repair retry     │ │   rate-limit,    │
│  dedupe /   │ │  cross-encoder   │ │  prompt registry  │ │   cache)         │
│  ranking    │ │  reranker        │ │  (versioned)      │ │                  │
│  arithmetic/│ │                  │ │                   │ │                  │
│  rules /    │ └──────────────────┘ └───────────────────┘ └──────────────────┘
│  citation   │
│  formatting/│ ┌────────────────────────────────────────────────────────────┐
│  FAISS I/O  │ │ G. STORAGE LAYER                                            │
└─────────────┘ │  SQLite (MVP) / PostgreSQL (research/prod) via SQLAlchemy   │
                │  2.0 + Alembic · FAISS index files on disk (per workspace)  │
                │  object storage for PDFs + index/DB backups                 │
                │  Redis (research/prod) for job queue + rate-limit counters  │
                └────────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────────────────────────┐
│ I. EVALUATION / OBSERVABILITY                                                │
│   stage_runs telemetry (latency/tokens/cost per stage) · structured logs ·  │
│   eval harness (discovery recall@k · trail F1 · RAGAs · ALCE citation P/R ·  │
│   gap expert-rating · composite W) · ablation switchboard                    │
└────────────────────────────────────────────────────────────────────────────┘
```

### 1.1 What each layer is / is not responsible for

| Layer | Owns | Must NOT |
|---|---|---|
| **A. Presentation/UI** | rendering, progress display, selection, hover-to-see-evidence, export triggers | contain business logic; call LLMs directly; hold BYOK keys longer than a request |
| **B. Application/API** | HTTP, auth, schema validation, job lifecycle, SSE, rate limits, tenant scoping, error → HTTP mapping | do retrieval/LLM work inline for long tasks (submit a job); make relevance judgements |
| **C. Deterministic processing** | PDF parse/clean, section split, table extraction, dedupe/merge, **all ranking arithmetic**, rule-based trail typing, citation string formatting, FAISS read/write, provenance bookkeeping | call an LLM; make relevance/relationship judgements that aren't rule-expressible |
| **D. Retrieval** | embed (MiniLM + SPECTER2), build/load/search FAISS, BM25, cross-encoder rerank, ANN metadata resolution | generate prose; decide *what to retrieve next* (that is the orchestrator) |
| **E. Agent/orchestration** | the bounded workflow plan, next-tool selection within that plan, expand-vs-stop on discovery, regenerate-once, answerability gating, budget guard | do arithmetic; format citations; write to the DB directly; spawn new agents at runtime |
| **F. LLM layer** | provider-agnostic chat + structured-output calls, prompt templates, JSON→Pydantic validation + one repair, capability probe on key connect | emit bibliographic reference strings; introduce uncited claims; alter control flow |
| **G. Storage** | relational persistence, FAISS files, object storage, (later) queue + counters | business logic |
| **H. External tools** | arXiv/OpenAlex/Semantic Scholar/Crossref HTTP clients behind a uniform interface with allowlist + retry + rate-limit + cache | be trusted blindly; be reachable at non-allowlisted hosts |
| **I. Evaluation/observability** | per-stage telemetry, structured logging (no secrets), the eval harness, ablation switches | affect production output paths (read-only observers) |

**Rule (from [review §15, §24]): do not turn every operation into an LLM agent.** LLM calls are confined to: profile extraction, search-concept generation, per-paper relevance-reason phrasing (from real signals), trail-edge confirmation, RAG answer generation, contextual chunk filtering, summarise/keypoints/compare/outline, gap articulation (constrained), direction generation + critique, `IsSupported?` verification. Everything else is deterministic code or retrieval.

---

## 2. Deterministic vs Retrieval vs LLM vs Agent vs External — the master separation table

| Operation | Class | Component | Notes / rationale |
|---|---|---|---|
| Validate upload (MIME, size, page count, encrypted, has-text-layer) | Deterministic | `security/pdf_sanitizer.py` | untrusted input *[review §26; §22 here]* |
| Extract text + section map + table blocks | Deterministic | `services/ingest/*` (`pypdf`/`pdfplumber`; optional Nougat/MinerU service) | section-aware, not flat *[PDFTriage]* |
| Clean (headers/footers, de-hyphenation) | Deterministic | `services/ingest/cleaner.py` | — |
| Section-aware chunking | Deterministic | `services/ingest/section_splitter.py` | fixed-size char chunks fragment scientific context *[review §13]* |
| Chunk embedding | Retrieval | `retrieval/embeddings.py` (MiniLM) | acceptable for QA passages *[review §11]* |
| Document embedding for similarity | Retrieval | `retrieval/embeddings.py` (SPECTER2) | scholarly document similarity backbone *[SciRepEval/SPECTER2]* |
| Build/load/search FAISS | Retrieval + Deterministic I/O | `retrieval/faiss_store.py` | `IndexFlatIP`, exact, fine at RN scale |
| BM25 keyword search | Retrieval | `retrieval/bm25.py` | exact-term robustness dense misses *[LitSearch hybrid]* |
| **Research-profile extraction** | LLM (structured) | `services/profile/extractor.py` + `validator.py` | one call, strict schema; validated + provenance-checked *[FacetSum, ChatCite]* |
| Profile provenance check (span exists in text) | Deterministic | `services/profile/provenance_check.py` | catches hallucinated fields |
| Search-concept / query generation | LLM (structured) | `services/search_concepts/` | keyword sets + expansions + perspective questions *[LitLLM, STORM]* |
| Discovery: keyword / arXiv / OpenAlex / Semantic Scholar calls | External | `external/*_client.py` via `discovery/*` | allowlist + retry + cache |
| Discovery: semantic (chunk + SPECTER2 doc) | Retrieval | `discovery/semantic.py` | — |
| Discovery: citation 1–2 hop | External + Deterministic | `discovery/citation.py` + OpenAlex | popularity/recency bias noted → capped weight *[CitationNet-LLM]* |
| Discovery: method / topic / research-question | Retrieval (embedding views) | `discovery/method.py` `topic.py` `rq.py` | distinct embedding views of profile fields *[review §11]* |
| Dedupe / merge (DOI → arXiv id → title-hash) | Deterministic | `services/normalize/dedupe.py` | v1/v2, preprint↔published |
| Relevance filtering (language, venue-type, date, off-topic threshold) | Deterministic (+ optional cheap LLM classifier) | `services/normalize/filter.py` | — |
| **Multi-signal ranking (score fusion)** | Deterministic | `services/ranking/signals.py` + `fuse.py` | all arithmetic; initial weights labelled experimental *[review §11, §25]* |
| Cross-encoder rerank of top slice | Retrieval | `services/ranking/rerank.py` | "always rerank" *[LitLLM/"there yet?" doubles recall; LitSearch +4.4%]* |
| **Per-paper relevance explanation** | Deterministic template + LLM rephrase (constrained) | `services/ranking/explain.py` | reasons come from real signal values, LLM only rephrases *[task §7]* |
| Trail typing — rules | Deterministic | `services/trail/rules.py` | citation dir+year, shared dataset + diff method, recency, method_sim |
| Trail typing — LLM confirmation with spans | LLM (structured) | `services/trail/confirm_llm.py` | must quote spans from both papers |
| Trail typing — contradiction pass | Retrieval + LLM (NLI-style) | `services/trail/contradiction.py` | claim-level; never asserted without evidence *[SciFact, PaperQA2/ContraCrow]* |
| Trail confidence band | Deterministic | `services/trail/confidence.py` | function of signal agreement + evidence completeness |
| Workspace CRUD, combined index rebuild | Deterministic | `services/*` + `retrieval/faiss_store.py` | incremental |
| Multi-paper RAG retrieve → rerank | Retrieval | `services/rag/retriever.py` `reranker.py` | k≈8 → rerank top ~5 *[review §13]* |
| RAG contextual chunk filter | LLM | `services/rag/context_filter.py` | keep only relevant sentences *[PaperQA2]* |
| RAG answer generation | LLM (structured, per-sentence chunk tags) | `services/rag/generate.py` | — |
| RAG `IsSupported?` verification | LLM | `services/rag/verify.py` | Self-RAG-style; drop/flag unsupported *[Self-RAG]* |
| RAG faithfulness gate | LLM-as-judge (RAGAS lib) | `services/rag/faithfulness.py` | below threshold → regenerate once *[RAGAs]* |
| GraphRAG routing for "themes/gaps" questions | Deterministic router + Retrieval over graph | `services/graph/query.py` | flat top-k fails on global questions *[GraphRAG]* |
| Summarise / key points / compare / outline | LLM (structured) | `services/synthesis/*` | map-reduce for long docs; FacetSum-typed key points; schema→value tables *[AutoSurvey, FacetSum, ArxivDIGESTables]* |
| Comparison cell grounding check | Deterministic (span exists) + eval DecontextEval | `services/synthesis/compare.py` + `eval/` | every cell cites a span |
| **Gap: cross-paper matrix** | Deterministic (+ reuse profile fields) | `services/gaps/matrix.py` | rows = papers, cols = problem/method/model/dataset/metrics/limitation/future-work |
| **Gap: rule-derived candidates** | Deterministic | `services/gaps/candidates.py` | coverage / evaluation / method / contradiction rules |
| **Gap: evidence assembly** | Deterministic | `services/gaps/evidence.py` | ≥2 supporting papers or drop |
| **Gap: constrained articulation** | LLM (structured) | `services/gaps/articulate_llm.py` | may only phrase statement + why-unaddressed + direction; no new claims *[RA-FSM]* |
| **Gap: self-support check** | LLM | `services/gaps/confidence.py` (uses `rag/verify.py`) | `IsSupported?` over (statement, evidence) *[Self-RAG]* |
| **Gap: confidence band** | Deterministic | `services/gaps/confidence.py` | bands only, never invented % *[review §11, §18]* |
| Research directions | LLM (structured) + LLM critique pass | `services/directions/generate.py` `critique.py` | from accepted gaps only; feasibility labelled uncertain *[ResearchAgent; Si et al.]* |
| Citation metadata resolution | External | `services/citations/metadata_resolver.py` (Crossref/OpenAlex/arXiv) | — |
| **Citation string formatting (APA/IEEE/BibTeX)** | Deterministic | `services/citations/formatter.py` | **LLM never emits references** — GPT-4o hallucinates 78–90% *[OpenScholar]* |
| Citation grounding check (claim → chunk → paper → id) | Deterministic link + LLM `IsSupported?` + ALCE metrics | `services/citations/validate.py` + `eval/` | *[ALCE, Self-RAG]* |
| Research graph build/query (per workspace) | Deterministic (networkx) | `services/graph/builder.py` `query.py` | small; JSON-persisted; no graph DB |
| Orchestrator plan + next-tool + budget + answerability | Agent | `services/orchestrator/*` | bounded plan, no runtime agent creation *[review §15]* |
| Per-stage telemetry, eval harness | Observability | `eval/*`, `stage_runs` table | read-only |

---

## 3. The seed-paper pipeline — stage by stage

Each stage: **In → Out**, **modules**, **data structures** (Pydantic; full definitions in `ResearchNexus_Data_Model.md`), **LLM calls**, **external APIs**, **failure handling**, **tests**, **evaluation metrics**.

### S1. Upload paper
- **In:** file bytes + filename + `owner_id`. **Out:** `PaperFile` row (`pdf_path`, `sha256`, `size`, `page_count`), or a rejection.
- **Modules:** `routers/papers.py`, `security/pdf_sanitizer.py`, storage adapter.
- **Data:** `PaperFileMeta{path, sha256, size_bytes, page_count, has_text_layer, encrypted}`.
- **LLM:** none. **External:** none.
- **Failure:** reject > `MAX_PDF_MB` (default 30) / > `MAX_PAGES` (default 60) / encrypted / non-PDF MIME → `422` with reason. Zip-bomb / decompression-ratio guard. Parse in a resource-limited worker.
- **Tests:** unit — oversized, encrypted, non-PDF, 0-byte, valid; property — random bytes never crash.
- **Metrics:** rejection rate by reason; p50/p95 validation latency.

### S2. PDF validation & structure extraction
- **In:** `PaperFileMeta`. **Out:** `ParsedDocument{full_text, sections:[Section{title, order, char_range, page_span}], tables:[TableBlock{caption, raw_text, page}], references:[RawReference], parse_confidence}`.
- **Modules:** `services/ingest/pdf_loader.py`, `cleaner.py`, `section_splitter.py`, `table_extractor.py`, `reference_parser.py`; optional `external/nougat_client.py` (self-hosted).
- **Data:** `ParsedDocument`, `Section`, `TableBlock`, `RawReference`.
- **LLM:** none (deterministic). **External:** optional Nougat/MinerU service (self-hosted, allowlisted).
- **Failure:** no text layer → offer OCR/Nougat path or reject "Scanned PDF". Garbled ratio > threshold → `parse_confidence=low`, surface to UI, still proceed. Section detection fails → single "body" section, flag.
- **Tests:** golden-file tests on a fixture set of 10 real papers (2-column, equations, tables); assert section titles, table count, reference count within tolerance.
- **Metrics:** section-detection F1 vs manual labels; table-recall; % low-confidence parses.

### S3. Paper understanding (seed indexing)
- **In:** `ParsedDocument`. **Out:** `SeedIndex{faiss_path, chunk_count}`, chunks persisted with provenance; `doc_embedding` (SPECTER2).
- **Modules:** `services/ingest/section_splitter.py`, `retrieval/embeddings.py`, `retrieval/faiss_store.py`.
- **Data:** `PaperChunk{chunk_id, paper_id, section, page, char_range, text, embedding_ref}`.
- **LLM:** none. **External:** none.
- **Failure:** embedding model download/load failure → clear startup error (model is a hard dependency, pinned). Empty text → abort with reason.
- **Tests:** chunk boundary respects sections; provenance round-trips; index search returns the seeded chunk for its own text.
- **Metrics:** chunks/paper distribution; index build time vs page count.

### S4. Research profile extraction
- **In:** `ParsedDocument` (abstract + intro + method + experiments + conclusion + any *Limitations*/*Future Work*). **Out:** validated `ResearchProfile` (schema §5, full def in Data Model).
- **Modules:** `services/profile/extractor.py` (LLM), `validator.py` (Pydantic), `provenance_check.py`.
- **Data:** `ResearchProfile`, `ProfileField{value, source_span, verified, user_edited}`.
- **LLM:** **1 structured call** (JSON mode / function-calling), temperature ≈ 0.2, provider = user's BYOK. On invalid JSON → `schema_repair` one retry with stricter instruction.
- **External:** none.
- **Failure:** repair retry fails → return a partial profile with `extraction_confidence=low` and empty fields the user fills in. Field whose `source_span` text isn't found in the doc → `verified=false`, shown differently.
- **Tests:** unit with recorded LLM fixtures (VCR-style) — valid JSON, malformed JSON (repair path), missing fields; provenance check rejects a fabricated span.
- **Metrics:** field-level precision/recall vs a small hand-labelled set; % fields `verified`; extraction latency + token cost.

### S5. Search-concept generation
- **In:** `ResearchProfile`. **Out:** `SearchPlan{keyword_sets:[[str]], expanded_queries:[str], perspective_questions:[str], citation_anchors:[paper_ref]}`.
- **Modules:** `services/search_concepts/concept_generator.py` (LLM), `services/ingest/reference_parser.py` output for anchors.
- **Data:** `SearchPlan`.
- **LLM:** 1 structured call.
- **External:** none.
- **Failure:** LLM failure → deterministic fallback: keywords = profile `keywords` + noun-phrases from `research_problem`; no expansions/perspectives (flag reduced coverage).
- **Tests:** fallback path produces a non-empty plan; expansions include acronym forms for a known fixture.
- **Metrics:** downstream — does adding expanded/perspective queries raise discovery recall (ablation A-concepts).

### S6. Multi-strategy discovery
- **In:** `SearchPlan`, `ResearchProfile`, filters (max results, date window, domain). **Out:** `list[PaperCandidate]` per strategy, unioned.
- **Modules:** `services/discovery/runner.py` (parallel) → `keyword.py`, `semantic.py`, `query_expansion.py`, `citation.py`, `method.py`, `topic.py`, `rq.py`; `external/arxiv_client.py`, `openalex_client.py`, `semantic_scholar_client.py`.
- **Data:** `PaperCandidate` (schema §6).
- **LLM:** none in the strategies themselves (queries were generated in S5).
- **External:** arXiv API, OpenAlex, Semantic Scholar (fallback), corpus FAISS/BM25 indices (internal).
- **Failure:** a strategy/API error is isolated — the runner continues with the rest and records which ran; if total candidates or diversity is low, the orchestrator may authorise **one** extra citation hop (bounded).
- **Tests:** each strategy returns normalised `PaperCandidate`s with its `discovery_methods` tag; runner tolerates one failing strategy; rate-limit backoff is exercised with a mock.
- **Metrics:** per-strategy Recall@{10,20,50}, Precision@{5,10,20}, contribution overlap (Jaccard between strategies), API error rate.

### S7. Deduplication
- **In:** unioned candidates. **Out:** merged `list[PaperCandidate]` with `discovery_methods` accumulated.
- **Modules:** `services/normalize/dedupe.py`, `merge.py`.
- **Data:** `PaperCandidate` (merged).
- **LLM:** none. **External:** none.
- **Failure:** ambiguous identity (no DOI/arXiv id, near-identical title) → keep both, flag `possible_duplicate` for the UI.
- **Tests:** v1/v2 arXiv merge; preprint + published merge keeps richer metadata; title-hash normalisation (case, punctuation, whitespace).
- **Metrics:** duplicate rate before/after; false-merge rate on a labelled sample (target 0).

### S8. Relevance filtering
- **In:** merged candidates + `ResearchProfile`. **Out:** filtered candidates + drop log.
- **Modules:** `services/normalize/filter.py`.
- **Data:** `FilterDecision{candidate_id, kept:bool, reasons:[str]}`.
- **LLM:** optional 1 cheap batched classifier call for borderline off-topic cases (config flag; off by default in MVP).
- **External:** none.
- **Failure:** over-aggressive filtering (kept count collapses) → relax the off-topic threshold once and log.
- **Tests:** date/language/venue-type filters; off-topic obvious negatives dropped; the seed itself is always dropped.
- **Metrics:** precision/recall of the filter vs a labelled borderline set; kept-count stability.

### S9. Multi-signal ranking
- **In:** filtered candidates, `ResearchProfile`, seed embeddings, citation edges, `RankingWeights` (initial experimental values). **Out:** `list[RankedPaper]` with full `SignalScores` retained.
- **Modules:** `services/ranking/signals.py` (one function per sub-score), `fuse.py` (weighted sum + normalisation), `rerank.py` (cross-encoder on top ~50).
- **Data:** `SignalScores{semantic_doc, semantic_chunk, problem_sim, method_sim, dataset_overlap, citation, recency}`, `RankedPaper{candidate, signals, fused_score, rerank_score, final_rank, band}`.
- **LLM:** none (arithmetic). Cross-encoder is a retrieval model, not an LLM.
- **External:** none.
- **Failure:** a sub-score unavailable (e.g. no citation data) → renormalise weights over available signals; record which were missing.
- **Tests:** monotonicity (raising one signal cannot lower the fused score with fixed weights); missing-signal renormalisation; deterministic given fixed inputs.
- **Metrics:** nDCG@10, MRR, pairwise-preference agreement with expert ranking; per-signal ablation deltas (A1–A6).

### S10. Relevance explanation
- **In:** `RankedPaper` (with `SignalScores`), seed + candidate spans. **Out:** `RankingExplanation{bullet_reasons:[str], prose:str}`.
- **Modules:** `services/ranking/explain.py`.
- **Data:** `RankingExplanation`.
- **LLM:** 1 short **constrained** call per paper (batched): given the signal values + one span from each paper, phrase the reasons. It may **not** introduce a reason not backed by a signal.
- **External:** none.
- **Failure:** LLM failure → deterministic template only ("high problem similarity (0.81); shares dataset BEIR; 1-hop citation").
- **Tests:** every bullet maps to a signal above threshold; no bullet without a signal; template fallback always non-empty.
- **Metrics:** "reason accuracy" — human check that each stated reason is true given the signals (target ≥ 0.95).

### S11. Typed research trail
- **In:** `RankedPaper`s, citation edges, seed key-claims, `ResearchProfile`s. **Out:** `list[TrailEdge]` (a paper may have several).
- **Modules:** `services/trail/rules.py` → `confirm_llm.py` → `contradiction.py` → `confidence.py`.
- **Data:** `TrailEdge{source=seed, target, relationship_type, evidence:[Evidence], confidence, detection_method, supporting_references, user_state}`.
- **LLM:** 1 structured confirmation call per candidate edge (batched by type); contradiction pass is retrieval + 1 NLI-style call per seed key-claim × top candidates.
- **External:** none (citation edges already fetched).
- **Failure:** rules and LLM disagree → keep edge `pending` at `Low` confidence, ask the user. Contradiction with no quotable span from both → do not create the edge.
- **Tests:** each rule fires on a crafted fixture; contradiction requires spans from both; multi-type assignment allowed; user reject is remembered.
- **Metrics:** per-type precision/recall/F1 vs human labels; contradiction-pass precision (target high — false contradictions are costly); confidence calibration vs human agreement.

### S12. User review / selection
- **In:** trail. **Out:** `list[selected paper_id]` + per-edge `accept/reject`.
- **Modules:** `routers/workspaces.py`, UI.
- **Data:** `WorkspacePaper{workspace_id, paper_id, added_by='trail'|'manual', pinned, tags, note}`, `trail_edges.user_state`.
- **LLM/External:** none.
- **Failure:** none material; selection is explicit (no auto-add).
- **Tests:** API adds/removes/pins/tags; rejected edges hidden by default.
- **Metrics:** selection precision (of shown trail, fraction the user keeps) as a downstream signal for ranking weight tuning.

### S13. Multi-paper workspace
- **In:** seed + selected papers + profiles + trail. **Out:** `ResearchWorkspace` (persistent) + combined chunk index + per-workspace research graph.
- **Modules:** `services/orchestrator/*`, `retrieval/faiss_store.py`, `services/graph/builder.py`.
- **Data:** `ResearchWorkspace` (schema §9 / Data Model).
- **LLM:** none at assembly (per-paper abstract profiles for related papers are extracted lazily on first use, flagged `grounding='abstract'`).
- **External:** none.
- **Failure:** adding a paper whose PDF isn't available → index its abstract only, flag; combined index rebuild failure → keep the last good index, surface an error.
- **Tests:** add/remove rebuilds the combined index and graph incrementally; artefact cache invalidates on paper-set change; tenant scoping enforced on every read.
- **Metrics:** index rebuild time vs #papers ∈ {5,20,50,100}; workspace load latency.

**Downstream workspace operations** (RAG, comparison, gaps, directions, citations, presentation) are specified in `ResearchNexus_Seed_Paper_Research_Trail.md` §12–§16 and made concrete in the Data Model / API / Evaluation docs. Key engineering points repeated here for the separation contract:

- **RAG:** retrieve (k≈8) → cross-encoder rerank (top ~5) → LLM contextual filter → LLM structured generation with per-sentence `chunk_id` tags → LLM `IsSupported?` → RAGAS faithfulness gate (regenerate once, then warn) → render with hover-excerpts. Route "themes/gaps/what's-missing" questions to the per-workspace GraphRAG path.
- **Comparison:** deterministic schema (union of method/dataset/metric fields) → LLM value generation per cell → every cell must cite a span → DecontextEval in CI.
- **Gap:** deterministic matrix → deterministic candidate rules → deterministic evidence assembly (≥2 papers) → constrained LLM articulation → LLM self-support check → deterministic confidence band → human accept/reject.
- **Directions:** LLM from accepted gaps only → LLM critique pass → feasibility labelled uncertain.
- **Citations:** deterministic metadata resolve → deterministic formatter (LLM never writes references) → deterministic claim→chunk→paper→id link + ALCE/Self-RAG checks.
- **Presentation:** LLM outline from workspace artefacts; every bullet cites a paper.

---

## 4. Agentic orchestrator — component table

`ResearchOrchestrator` runs a **fixed workflow DAG**. Its only discretion: (a) which discovery strategies to run (config + budget), (b) authorise **one** extra citation hop iff `candidate_count < MIN` or `diversity < MIN`, (c) regenerate a RAG answer **once** on a failed faithfulness gate, (d) answer vs "I don't know" via answerability gating, (e) degrade under budget. **No runtime agent creation. No recursion.** *[review §15; Agentic-RAG-Survey B4]*

| Component | Class | Input | Output | Retry / failure behaviour |
|---|---|---|---|---|
| `PaperAnalyzer` | Deterministic (S2/S3) + **LLM** (S4 profile) | `ParsedDocument` | `ResearchProfile`, `SeedIndex` | LLM: schema-repair ×1 → partial profile `low` confidence |
| `SearchPlanner` | **LLM** (S5) | `ResearchProfile` | `SearchPlan` | LLM fail → deterministic keyword fallback |
| `DiscoveryTools` (7 strategies) | Retrieval + **External** (S6) | `SearchPlan` | `list[PaperCandidate]` | per-strategy isolation; runner continues; record failures |
| `CandidateFilter` | Deterministic (+ optional cheap LLM) (S7/S8) | candidates | filtered candidates + drop log | over-filter → relax threshold ×1 |
| `EvidenceVerifier` | **LLM** (`IsSupported?`) + Retrieval | (claim, chunks) | `supported: bool + score` | timeout → treat as unsupported (safe default) |
| `Ranking` | Deterministic + Retrieval rerank (S9) | filtered candidates + signals | `list[RankedPaper]` + `SignalScores` | missing signal → renormalise weights |
| `RelevanceExplainer` | Deterministic template + **LLM** rephrase (S10) | `RankedPaper` + spans | `RankingExplanation` | LLM fail → template only |
| `TrailTyper` | Deterministic rules → **LLM** confirm → contradiction (S11) | ranked papers + edges + claims | `list[TrailEdge]` | rules/LLM disagree → `pending`/`Low` + ask user |
| `Synthesis` | **LLM** structured (summary/keypoints/compare/outline) | workspace papers/profiles | artefacts w/ per-claim citations | faithfulness gate → regenerate ×1 → warn |
| `GapAnalyzer` | Deterministic matrix + rules + evidence → **LLM** articulate → **LLM** self-check → Deterministic confidence | workspace matrix | `list[ResearchGap]` (candidates for the user) | < 2 supporting papers or self-check fail → drop candidate |
| `DirectionGenerator` | **LLM** generate → **LLM** critique | accepted gaps | `list[ResearchDirection]` | low critique score → flag, keep for user |
| `CitationBuilder` | **External** resolve → Deterministic format → Deterministic+LLM validate | workspace papers + generated claims | `Citation` objects, formatted strings | missing metadata → field `Not available` |
| `GraphBuilder` | Deterministic (networkx) | profiles + trail + gaps | `ResearchGraph` (JSON) | entity extraction weak → keep inspectable/correctable |
| `BudgetGuard` | Deterministic | token/USD counters | degrade signals (fewer strategies, smaller k) | hard stop at cap → notify user, offer raise |
| `AnswerabilityGate` | **LLM** (RA-FSM Relevance→Confidence→Knowledge) | question + workspace | `answerable: bool` | not answerable → "not enough in this workspace" + suggest papers |
| `ToolLog` | Observability | every tool call | `stage_runs` rows (latency/tokens/cost/in-hash/out-hash) | never blocks the path |

---

## 5. Research graph — why workspace-level is the right MVP

- **Scale.** A workspace holds ~5–50 papers → tens of method/dataset/metric/claim nodes. An in-memory `networkx` graph, persisted as JSON on the `workspaces` row, is enough. No Neo4j / graph DB, no operational cost, trivially inspectable and user-correctable.
- **Correctness surface.** Entity extraction is the weak link *[review §16]*. A small per-workspace graph can be shown to the user and corrected; a global graph cannot be curated at scale and its errors compound.
- **What it buys, now.** Answers "which datasets do these papers share?", "what method does nobody here use?"; is the substrate for the **gap matrix** (a projection of the graph), for **trail typing** (shared-node structure → competing / dataset-related / method-extension), and for **GraphRAG-style routing** of global questions *[GraphRAG]*.
- **Deferred.** A cross-workspace / global knowledge graph (recurring gaps across a user's projects, a personal research map) is a **research-version** extension once per-workspace extraction quality is measured.

---

## 6. Module / package layout (to be created)

```
researchnexus/
  backend/
    pyproject.toml               # deps + tool config (ruff, mypy, pytest)
    alembic.ini
    app/
      main.py                    # FastAPI app + router registration
      config.py                  # pydantic-settings (env only; no secrets in code)
      deps.py                    # get_db, get_current_user, get_llm_client
      routers/                   # B. API layer
        health.py papers.py workspaces.py discovery.py chat.py synthesis.py citations.py
      domain/                    # pure Pydantic models (no IO) — see Data Model doc
        profile.py candidate.py ranking.py trail.py workspace.py chunk.py
        gap.py direction.py citation.py graph.py jobs.py
      services/                  # C + E business logic
        ingest/ profile/ search_concepts/ discovery/ normalize/ ranking/ trail/
        rag/ synthesis/ gaps/ directions/ citations/ graph/ orchestrator/
      llm/                       # F. LLM layer
        client.py providers/ prompts/ schema_repair.py capability_probe.py
      retrieval/                 # D. retrieval layer
        embeddings.py faiss_store.py bm25.py reranker.py
      external/                  # H. external tools
        http.py allowlist.py arxiv_client.py openalex_client.py
        semantic_scholar_client.py crossref_client.py nougat_client.py
      db/                        # G. storage
        models.py session.py
        migrations/versions/
      security/                  # cross-cutting — see §22 of Roadmap / Data Model
        pdf_sanitizer.py prompt_guard.py rate_limit.py key_vault.py
      eval/                      # I. evaluation/observability
        harness.py datasets/ discovery_eval.py ranking_eval.py trail_eval.py
        rag_eval.py citation_eval.py gap_eval.py e2e_eval.py ablations.py
      telemetry/
        logging.py stage_timer.py cost.py
    tests/
      unit/ integration/ eval/ fixtures/
  frontend/
    streamlit_app/               # MVP UI
    web/                         # (research/prod) Next.js — later
  scripts/
    build_corpus_index.py        # arXiv metadata → SPECTER2/BM25 discovery indices
    run_eval.py
  docs/                          # (this set)
```

---

## 7. Technology choices — decision + rationale (traceable)

| Concern | Choice | Rationale (traceable) |
|---|---|---|
| Language | **Python 3.11+** | project requirement; abstract stack; ML ecosystem |
| Backend framework | **FastAPI** (async) | needs parallel discovery, SSE chat streaming, background jobs, multi-tenant auth — Streamlit alone cannot do these cleanly; keeps logic in a testable, reusable service *[review §24: separable layers]* |
| Frontend (MVP) | **Streamlit** calling the API | matches the abstract; fastest to a demo; **all logic lives in the API**, so the UI is swappable |
| Frontend (research/prod) | **Next.js/React** | multi-tab workspace, hover-evidence, progress UIs; deferred |
| Orchestration primitives | **LangChain** (splitters, prompt templates, provider adapters) — **not** LangChain agents | project stack; but the orchestrator is hand-written and bounded *[review §15; B4]* |
| Domain models / validation | **Pydantic v2** | task requirement ("prefer Pydantic", "LLM output must be parsed and validated") |
| Structured LLM output | JSON mode / function-calling → Pydantic validate → **one** `schema_repair` retry | task §5; robustness |
| Chunk embeddings | **`sentence-transformers/all-MiniLM-L6-v2`** (local) | free, local, CPU-ok; acceptable for QA passages *[review §11]* |
| Document-similarity embeddings | **`allenai/specter2`** (local) | scholarly document similarity backbone; conflating topic vs method is a known failure of a single space *[SciRepEval/SPECTER2; review §9, §11]* |
| Vector store | **FAISS `IndexFlatIP`** (normalised vectors) on disk, LRU-cached | project requirement; exact search fine at RN scale (tens–hundreds of papers/workspace) |
| Keyword search | **`rank_bm25`** (MVP) → **Tantivy/OpenSearch** (scale) | hybrid dense+sparse robustness *[LitSearch]* |
| Reranker | **cross-encoder** (`BAAI/bge-reranker-base` or `cross-encoder/ms-marco-MiniLM-L-6-v2`) | "always rerank" — doubles recall in *[LitLLM "there yet?"]*, +4.4% in *[LitSearch]* |
| RAG faithfulness eval | **RAGAS** library | *[RAGAs]*; reference-free faithfulness/answer/context relevance |
| Citation eval | custom **ALCE-style** NLI precision/recall | *[ALCE]* |
| Relational DB | **SQLite** (MVP) → **PostgreSQL** (research/prod) via **SQLAlchemy 2.0** + **Alembic** | zero-setup MVP; Postgres for concurrency, JSONB, RLS-style tenant isolation |
| Background jobs | **FastAPI `BackgroundTasks`** (MVP) → **ARQ + Redis** (research/prod) | discovery/gap runs take seconds–minutes |
| LLM providers | provider-agnostic client; **OpenAI-compatible** adapter (OpenAI, Groq, DeepSeek, OpenRouter, Together) + **Gemini** adapter; **BYOK** | abstract's "user-selected LLM"; fixed provider enum (SSRF); capability probe on connect |
| External scholarly APIs | **arXiv API**, **OpenAlex** (citations+metadata, no key), **Semantic Scholar** (fallback), **Crossref** (DOI metadata) | free, keyless, permissive; fixed allowlist *[review §22 / §21 here]* |
| Hard-PDF parsing (optional) | self-hosted **Nougat** / **MinerU** service | scanned/equation-heavy PDFs *[Nougat, MinerU]* |
| Logging | **structlog** JSON; per-stage timing/token/cost to `stage_runs` | task §20 end-to-end evaluation; no secrets in logs |
| Lint / type / test | **ruff**, **mypy**, **pytest** (+ `pytest-recording` for LLM fixtures) | standard; deterministic tests for the deterministic layer |
| New dependencies flagged | fastapi, uvicorn, pydantic, sqlalchemy, alembic, langchain-core, langchain-text-splitters, sentence-transformers, transformers, torch (CPU), faiss-cpu, rank-bm25, pypdf, pdfplumber, ragas, httpx, tenacity, structlog, python-multipart, arq (later), redis (later) | each justified above; no dependency added without a line here |

---

## 9. Research contribution traceability — IEEE BigData 2024 limitation → ResearchNexus

ResearchNexus's research-gap workflow (contribution area 3, review §21) is tracked against a specific limitation in a specific published paper, not asserted in the abstract. Verified against the paper's official record and arXiv preprint (title, authors, venue and DOI confirmed on IEEE Xplore and arXiv; the limitation characterisation below is drawn from the abstract and arXiv metadata only — the full IEEE-Xplore-paywalled text was not reviewed, and this is stated explicitly rather than guessed).

**Source paper.** Ahad, J. I., Sultan, R. M., Kaikobad, A., Rahman, F., Amin, M. R., Mohammed, N., Rahman, S. *"Empowering Meta-Analysis: Leveraging Large Language Models for Scientific Synthesis."* 2024 IEEE International Conference on Big Data (IEEE BigData). DOI: 10.1109/BigData62323.2024.10825310. Preprint: arXiv:2411.10878. — verified YES (IEEE Xplore document 10825310; arXiv record matches title/authors/venue).

**What it does (per the abstract).** Fine-tunes an LLM on scientific-document data, combined with Retrieval-Augmented Generation and a novel "Inverse Cosine Distance" (ICD) fine-tuning loss, to automatically generate meta-analysis synthesis text from multiple studies. Reports human evaluation of 87.6% "relevant" meta-analysis abstracts, with irrelevancy reduced from 4.56% to 1.9% versus baselines.

**Target limitation this project tracks.** The paper's abstract and available metadata describe a pipeline that *generates synthesised meta-analysis narrative text* and evaluates it for overall *relevance*; they do not describe (a) a structured, per-claim evidence object, (b) an audit trail linking a synthesised statement back to an exact span in a specific source paper, or (c) an explicit research-gap-identification step distinguishing "what these papers agree on" from "what none of them address." In other words: **no explicit, auditable, evidence-backed research-gap identification workflow across multiple papers** is described. This framing is this project's characterisation of an adjacent, unaddressed problem — not a quoted claim from the paper — and is flagged as such.

**ResearchNexus solution.** The structured `ResearchGap` object (`ResearchNexus_Data_Model.md` §8; Roadmap Phase 11): cross-paper matrix → rule-derived candidates (`METHOD_GAP` / `DATASET_GAP` / `EVALUATION_GAP` / `CONTRADICTION` / …) → evidence assembly requiring ≥2 supporting papers → constrained LLM articulation (may not introduce an unsupported claim) → Self-RAG-style self-support check → deterministic confidence band → human accept/reject. Every `GapEvidence` entry carries a `SourceSpan` (`paper_id`, `section`, `page`, exact `char_start`/`char_end`, `quote`) — the audit trail the source paper's approach does not provide.

**Required data (why this constrains Phase 2, implemented now).** The gap workflow is only buildable later if ingestion preserves, today:

| Data preserved by Phase 2 | Domain type / table | Why the gap workflow needs it |
|---|---|---|
| Exact character-offset provenance per chunk | `PaperChunk.char_start/char_end` → `paper_chunks` | every `GapEvidence.span` must resolve to real, verifiable text |
| Section identity per chunk | `PaperChunk.section`/`section_order` | builds the matrix's rows/columns (method, dataset, limitation, per section) |
| Table blocks with captions, anchored | `TableBlock` → part of `papers.tables` | dataset/metric evidence for `DATASET_GAP`/`EVALUATION_GAP` candidates |
| Segmented reference list | `RawReference` → `papers.references` | future citation-based cross-paper linking and contradiction evidence |
| Deterministic, rule-based parse confidence | `ParsedDocument.parse_confidence` → `papers.parse_confidence` | weights how much a paper's evidence should be trusted in the matrix |

Phase 2 (`backend/app/services/ingest/*`, `backend/app/domain/{paper,chunk}.py`) implements exactly this and nothing more — it does **not** implement matrix-building, candidate rules, or gap articulation.

**Future implementation phase.** Roadmap Phase 11 ("Research-gap objects"), building on Phase 13 (per-workspace research graph, which the matrix is a projection of). Not implemented in Phase 2.

**Evaluation metric.** `docs/evaluation/ResearchNexus_Evaluation_Plan.md` §7 (Gap detection): evidence-support rate (target 1.0), hallucination rate (≤0.02/gap), expert relevance rate (≥0.6), confidence calibration — plus a new Phase-2-precursor metric, **provenance completeness**, defined and tested now (§10 below).

---

## 10. Cross-references

- **Data structures & DB:** `docs/architecture/ResearchNexus_Data_Model.md`
- **Endpoints:** `docs/architecture/ResearchNexus_API_Specification.md`
- **Build order, acceptance criteria, MVP vs research split:** `docs/architecture/ResearchNexus_Implementation_Roadmap.md`
- **Metrics, ablations A1–A13, baselines B1–B9, composite W:** `docs/evaluation/ResearchNexus_Evaluation_Plan.md`
- **UX detail & security narrative:** `docs/architecture/ResearchNexus_Seed_Paper_Research_Trail.md` §2, §21
- **IEEE-limitation traceability:** §9 above

**Phase 2 implementation status (2026-09-05).** PDF ingestion is implemented and tested at `backend/` — see `backend/app/services/ingest/*`, `backend/app/domain/{paper,chunk,jobs}.py`, `backend/app/db/*`, `backend/app/routers/{papers,jobs,health}.py`. 106 tests pass (`pytest`), `ruff check .` and `mypy app tests` are clean. Embeddings/FAISS interfaces (`backend/app/retrieval/*`) are prepared per §7 but not yet wired into the pipeline, per plan.

*No application source code is created by **this document** (the code itself lives under `backend/`, produced alongside it per the user's explicit Phase 2 instruction). Every non-obvious decision above is traceable to the literature review, the abstract's stated requirements, a specific paper's limitation, or a stated engineering rationale. No facial-recognition / attendance content appears anywhere.*
