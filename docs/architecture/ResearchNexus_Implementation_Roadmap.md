# ResearchNexus — Implementation Roadmap

**Purpose.** The build sequence that turns the architecture into working software. **Design only — no application code is written by this document.** Each phase lists *objectives · files/modules · dependencies · APIs delivered · tests · acceptance criteria · risks · prerequisites*.

**Companions:** `ResearchNexus_Implementation_Architecture.md`, `ResearchNexus_Data_Model.md`, `ResearchNexus_API_Specification.md`, `docs/evaluation/ResearchNexus_Evaluation_Plan.md`, `ResearchNexus_Seed_Paper_Research_Trail.md`.

**Ground truth.** Greenfield repo (only `Untitled document.pdf` + the 5 design/review docs + `.semgrep/`). No code, deps, tests, or CI exist yet.

**Guiding rules (from the literature review):** keep the four layers separable (deterministic / retrieval / LLM / agent / external); do **not** agent-ify deterministic work; LLM never writes citations; every generated claim carries evidence; human-in-the-loop at selection, trail confirmation, gap acceptance; evaluate the whole workflow, not just stages *[review §15, §17, §18, §24]*.

**Sizing.** Phase estimates assume one engineer; "S" ≈ 2–4 days, "M" ≈ 1–2 weeks, "L" ≈ 2–4 weeks. They are planning aids, not commitments.

---

## Phase 1 — Repository & architecture foundation  (S–M)

**Objectives.** Buildable, testable skeleton. Config, auth, DB session, health, CI, the LLM client shell with BYOK key management.

**Files/modules.** `backend/pyproject.toml`, `app/main.py`, `app/config.py` (pydantic-settings), `app/deps.py`, `app/routers/health.py`, `app/routers/settings_keys.py`, `app/db/session.py`, `app/db/models.py` (users, api_keys), `app/security/key_vault.py` (envelope encryption), `app/llm/client.py` + `providers/openai_compat.py` + `providers/gemini.py` + `capability_probe.py`, `app/telemetry/logging.py` (structlog), `alembic.ini` + migration `0001_users_apikeys`, `.github/workflows/ci.yml`, `tests/`.

**Dependencies (new, flagged).** fastapi, uvicorn, pydantic, pydantic-settings, sqlalchemy, alembic, httpx, tenacity, structlog, python-jose (JWT verify), cryptography, pytest, ruff, mypy, pytest-recording.

**APIs delivered.** `GET /health`, `POST /auth/session` (local dev), `GET /me`, `GET|PUT|DELETE /settings/llm-keys`, `POST /settings/llm-keys/test`.

**Tests.** health returns component checks; JWT verify accepts/rejects; key ciphertext round-trips and plaintext never appears in logs (assert on captured log records); provider capability probe against a mocked OpenAI-compatible endpoint; `unsupported_provider` rejected.

**Acceptance criteria.** `pytest` + `ruff` + `mypy` green in CI; a dev can save a Groq key, see `status:"working"`, and it is stored only as ciphertext + last4.

**Risks.** JWT/auth-provider choice churn → keep `auth/session` swappable behind `deps.get_current_user`. Torch/faiss wheels on the target OS (Windows dev, Linux prod) → pin CPU wheels, document install.

**Prerequisites.** None.

---

## Phase 2 — PDF ingestion & structured extraction  (M)

**Objectives.** Upload → validate → parse → section map + table blocks + reference list → section-aware chunks → seed FAISS index + SPECTER2 doc embedding. All deterministic + retrieval; **no LLM**.

**Files/modules.** `security/pdf_sanitizer.py`, `services/ingest/{pdf_loader,cleaner,section_splitter,table_extractor,reference_parser}.py`, `retrieval/{embeddings,faiss_store}.py`, `external/nougat_client.py` (optional, feature-flagged), `routers/papers.py` (`upload`, `GET /papers/{id}`), `db/models.py` (papers, paper_chunks), migration `0002_papers_chunks`, `jobs` runner (BackgroundTasks), `domain/{chunk}.py`, `tests/fixtures/pdfs/` (10 real papers).

**Dependencies.** pypdf, pdfplumber, sentence-transformers, transformers, torch (CPU), faiss-cpu, python-multipart, (optional) a self-hosted Nougat service.

**APIs delivered.** `POST /papers/upload`, `GET /papers/{id}`, `GET /jobs/{id}` (+ `/events` SSE), `POST /jobs/{id}/cancel`.

**Tests.** oversized/encrypted/scanned/non-PDF/0-byte rejected with the right codes; random-bytes never crashes the worker; golden-file section/table/reference extraction within tolerance on the fixture set; chunk boundaries respect sections; provenance round-trips; searching the seed index for a chunk's own text returns it; index build time recorded.

**Acceptance criteria.** For ≥ 8/10 fixture papers: section-detection F1 ≥ 0.8, ≥ 90 % of tables captured as blocks, reference list parsed; a 14-page paper ingests end-to-end in < 60 s on a dev laptop; `parse_confidence` set.

**Risks.** 2-column / equation-heavy / scanned PDFs break `pypdf` → Nougat/MinerU fallback + `parse_confidence=low` surfaced, never silent. Embedding model download in CI → cache in the CI image.

**Prerequisites.** P1.

---

## Phase 3 — Seed-paper ResearchProfile  (M)

**Objectives.** One validated, provenance-checked `ResearchProfile` per seed. First LLM use.

**Files/modules.** `services/profile/{extractor,validator,provenance_check}.py`, `llm/prompts/profile_v1.jinja`, `llm/schema_repair.py`, `domain/profile.py`, `db/models.py` (research_profiles) + migration `0003_research_profiles`, `routers/papers.py` (`analyze`, `PATCH /profile`).

**Dependencies.** rapidfuzz (span matching); no new heavy deps.

**APIs delivered.** `POST /papers/{id}/analyze`, `PATCH /papers/{id}/profile`.

**Tests.** recorded-LLM fixtures: valid JSON, malformed JSON → repair path, missing fields → partial profile `low`; provenance check flags a fabricated `source_span`; `extraction_confidence` computed per the rule; `PATCH` marks fields `user_edited`; `409 llm_key_required` without a key.

**Acceptance criteria.** On a 15-paper hand-labelled set: field-level precision ≥ 0.8 / recall ≥ 0.7 for problem/methods/datasets/limitations; ≥ 70 % of populated fields `verified`; median extraction latency < 15 s; malformed-JSON never surfaces as a 500.

**Risks.** Provider without JSON mode → function-calling or a strict-format prompt + `schema_repair`; capability probe (P1) drives this. Long papers exceed context → send only the key sections (already the design).

**Prerequisites.** P1, P2.

---

## Phase 4 — Academic search & candidate normalisation  (M)

**Objectives.** External scholarly clients behind one interface; `SearchPlan` generation; `PaperCandidate` normalisation; dedupe/merge; a buildable corpus discovery index.

**Files/modules.** `external/{http,allowlist,arxiv_client,openalex_client,semantic_scholar_client,crossref_client}.py`, `services/search_concepts/concept_generator.py` + `llm/prompts/search_concepts_v1.jinja`, `services/normalize/{dedupe,merge,filter}.py`, `domain/candidate.py`, `db/models.py` (search_runs, search_candidates) + migration `0004_search`, `scripts/build_corpus_index.py` (arXiv metadata dump → SPECTER2 + BM25 indices), `retrieval/bm25.py`.

**Dependencies.** rank-bm25 (MVP); arxiv (client) or raw httpx; feedparser (arXiv Atom).

**APIs delivered.** (internal) — surfaced via P5's `discover-related`. `GET /papers/{id}` already exists.

**Tests.** each client: happy path (recorded), 429 backoff, 5xx retry, timeout → typed `UpstreamUnavailable`; allowlist blocks a non-listed host; dedupe merges arXiv v1/v2 and preprint↔published; title-hash normalisation (case/punctuation/whitespace); `SearchPlan` fallback path is non-empty.

**Acceptance criteria.** From a seed profile, generate a `SearchPlan` and retrieve normalised `PaperCandidate`s from arXiv + OpenAlex; false-merge rate 0 on a 50-pair labelled dedupe set; corpus index build script runs on a 100k-abstract sample and answers a kNN query in < 200 ms.

**Risks.** OpenAlex/S2 rate limits / schema drift → cache aggressively, pin to documented fields, S2 is fallback-only. arXiv Atom quirks → golden-file parser tests.

**Prerequisites.** P1, P3.

---

## Phase 5 — Multi-strategy related-paper discovery  (M–L)

**Objectives.** The 7 strategies + a parallel runner with per-strategy isolation and progress; the bounded "one extra citation hop" decision.

**Files/modules.** `services/discovery/{base,runner,keyword,semantic,query_expansion,citation,method,topic,rq}.py`, `retrieval/embeddings.py` (method/topic/RQ views), `services/orchestrator/budget.py` (early), `routers/papers.py` (`POST /papers/{id}/discover-related`, `GET /papers/{id}/related` stub), migration `0005_candidates_extend`.

**Dependencies.** none new.

**APIs delivered.** `POST /papers/{id}/discover-related` (async job w/ per-strategy `progress`), partial `GET /papers/{id}/related`.

**Tests.** each strategy returns normalised candidates tagged with its `DiscoveryStrategy`; runner completes when one strategy raises; extra-citation-hop fires only when `count < MIN` or `diversity < MIN` and is capped; job `status:"partial"` when strategies fail; SSE `progress` events emitted.

**Acceptance criteria.** On a 20-seed internal benchmark (Evaluation Plan §Discovery): the union beats every single strategy on Recall@20; per-strategy metrics logged; a discovery run for one seed finishes in < 90 s with 6 strategies on a dev machine.

**Risks.** Latency/cost blow-up with all strategies × citation hops → `budget.py` caps, config to disable strategies, per-strategy timeouts. Citation-graph popularity bias → capped weight downstream (P6) + diversity term.

**Prerequisites.** P4.

---

## Phase 6 — Ranking & explanations  (M)  ← first contribution area

**Objectives.** Transparent multi-signal fusion (initial experimental weights), cross-encoder rerank, per-paper relevance explanation generated from **real** signals.

**Files/modules.** `services/ranking/{signals,fuse,rerank,explain}.py`, `retrieval/reranker.py` (cross-encoder), `llm/prompts/relevance_explain_v1.jinja`, `domain/ranking.py`, `db/models.py` (ranked_papers) + migration `0006_ranked_papers`, complete `GET /papers/{id}/related`.

**Dependencies.** the cross-encoder model (sentence-transformers CrossEncoder).

**APIs delivered.** `GET /papers/{id}/related` (full: `signals`, `fused_score`, `rerank_score`, `band`, `explanation`).

**Tests.** monotonicity (raising one signal never lowers the fused score at fixed weights); missing-signal renormalisation; deterministic given fixed inputs; every explanation bullet maps to a signal above threshold; **no bullet without a signal**; template-only fallback on LLM failure; `weights_version` recorded.

**Acceptance criteria.** "Reason accuracy" ≥ 0.95 on a human check (each stated reason true given the signals); nDCG@10 improves over `preliminary_rank` on the 20-seed benchmark; response contains actual signal values (never a fabricated %).

**Risks.** Weight tuning is deferred and could look arbitrary → label `w0-initial` everywhere, expose per-signal values, tune in P16. Cross-encoder latency on long lists → rerank only the top `RERANK_TOP_N` (50).

**Prerequisites.** P5.

---

## Phase 7 — Typed research trail  (M–L)  ← second contribution area

**Objectives.** 7 relationship types via deterministic rules → LLM confirmation with spans → contradiction pass → confidence band; user accept/reject.

**Files/modules.** `services/trail/{rules,confirm_llm,contradiction,confidence}.py`, `llm/prompts/{trail_confirm_v1,contradiction_nli_v1}.jinja`, `domain/trail.py`, `db/models.py` (paper_relationships) + migration `0007_paper_relationships`, `routers/workspaces.py` (trail read/confirm — pre-workspace variant on `run_id`).

**Dependencies.** none new (reuse retrieval + LLM).

**APIs delivered.** trail data inside `GET /papers/{id}/related` (`trail_edges`), `POST .../trail/{edge_id}` (accept/reject), `POST .../trail/retype`.

**Tests.** each rule fires on a crafted fixture and not on a near-miss; `POTENTIALLY_CONTRADICTORY` requires a quotable span from **both** papers; multi-type assignment allowed; rejected edge suppresses the same rule on re-run; confidence band matches `confidence_basis`.

**Acceptance criteria.** On a human-labelled trail set (≥ 150 edges): per-type F1 — `FOUNDATIONAL`/`RECENT`/`DATASET_RELATED` ≥ 0.75, `SIMILAR`/`METHOD_EXTENSION`/`COMPETING` ≥ 0.6, `POTENTIALLY_CONTRADICTORY` precision ≥ 0.8 (recall may be lower); confidence calibration monotone vs human agreement.

**Risks.** Contradiction false positives are costly → high-precision threshold, always show evidence, mark `pending` on disagreement. Rule thresholds are guesses → tune in P16 (ablation A9).

**Prerequisites.** P6.

---

## Phase 8 — Multi-paper workspace  (M)

**Objectives.** The persistent `ResearchWorkspace`; add/remove/reorder/pin/tag/annotate; combined chunk index; artefact cache; jobs + telemetry tables.

**Files/modules.** `services/orchestrator/orchestrator.py` (skeleton plan), `routers/workspaces.py` (full CRUD + papers), `db/models.py` (workspaces, workspace_papers, artefacts, jobs, stage_runs) + migration `0008_workspaces` (+ first Postgres CI leg), `retrieval/faiss_store.py` (incremental combined index + LRU cache + metadata sidecar), `telemetry/{stage_timer,cost}.py`.

**Dependencies.** none new for MVP (arq/redis deferred to P18/research).

**APIs delivered.** `POST /workspaces`, `GET /workspaces[/{id}]`, `PATCH /workspaces/{id}`, `DELETE /workspaces/{id}`, `POST /workspaces/{id}/papers`, `DELETE /workspaces/{id}/papers/{pid}`, `PATCH /workspaces/{id}/papers/{pid}`, `GET /workspaces/{id}/trail`, `POST /workspaces/{id}/trail/*`.

**Tests.** add/remove rebuilds the combined index + invalidates dependent artefacts; tenant scoping on every read (cross-tenant → 404); FAISS LRU cache eviction under a memory cap; incremental rebuild correctness (a removed paper's chunks are gone from search).

**Acceptance criteria.** A workspace with 20 papers: combined-index rebuild < 20 s on a dev machine; `stage_runs` rows written for every stage with latency/tokens/cost; workspace load < 1 s.

**Risks.** Memory on a `t3.small`-class box (~2 GB) with torch + 2 embedding models + FAISS → LRU-bounded resident indices, lazy model load, document a 4 GB recommendation for research/prod.

**Prerequisites.** P2, P3, P7.

---

## Phase 9 — RAG + evidence/citation system  (L)  ← core of RAG safety + contribution area 3 groundwork

**Objectives.** Multi-paper RAG: retrieve → rerank → contextual filter → structured generation with per-sentence chunk tags → `IsSupported?` → RAGAS faithfulness gate → render with hover-excerpts. Deterministic citation build + ALCE-style checks. Answerability gating; "I don't know".

**Files/modules.** `services/rag/{retriever,reranker,context_filter,generate,verify,faithfulness}.py`, `services/orchestrator/answerability.py`, `services/citations/{metadata_resolver,formatter,validate}.py`, `llm/prompts/{rag_generate_v1,context_filter_v1,is_supported_v1}.jinja`, `domain/{citation}.py`, `db/models.py` (chat_sessions, chat_messages, claims) + migration `0009_chat_claims`, `routers/chat.py` (SSE), `routers/synthesis.py` (`summary`, `keypoints`).

**Dependencies.** ragas; citeproc-py or a hand-rolled CSL formatter for APA/IEEE; bibtexparser (BibTeX emit).

**APIs delivered.** `POST /workspaces/{id}/chat` (SSE + non-stream), `GET /workspaces/{id}/chat/sessions[/{sid}]`, `POST /workspaces/{id}/summary`, `POST /workspaces/{id}/keypoints`, `POST /workspaces/{id}/citations`.

**Tests.** unsupported sentences are dropped/flagged (never rendered with empty `supporting_chunk_ids`); faithfulness gate triggers exactly one regeneration then warns; answerability gate returns "not enough in this workspace" + suggestion with **no** generation billing; **LLM output containing a fabricated reference string is caught and stripped** (formatter is the only source of references); citation formatter golden tests for APA/IEEE/BibTeX; SSE emits `token`/`citation`/`usage`/`done`.

**Acceptance criteria.** On QASPER (single-paper) + an M3SciQA-style anchor+trail set (multi-paper): RAGAS faithfulness ≥ 0.85 median; unsupported-sentence rate ≤ 5 %; **fabricated-reference rate = 0**; citation precision/recall reported; p95 first-token latency < 3 s (provider-dependent, logged).

**Risks.** LLM-judge cost for faithfulness on every message → sample in dev, gate on a cheap heuristic first, full RAGAS in eval runs. Provider variance → report per provider, never hard-code a model.

**Prerequisites.** P8.

---

## Phase 10 — Comparison  (M)

**Objectives.** Profile-grounded comparison tables: deterministic schema (union of method/model/dataset/metric fields) → per-cell LLM value generation → every cell cites a span → DecontextEval in CI.

**Files/modules.** `services/synthesis/compare.py`, `llm/prompts/compare_cell_v1.jinja`, `eval/decontext_eval.py`, `routers/synthesis.py` (`compare`).

**Dependencies.** none new.

**APIs delivered.** `POST /workspaces/{id}/compare`.

**Tests.** schema = union of profile fields when `schema:null`; every populated cell has a `span` and a `claim_id`; cells with no support are `null`, not hallucinated; DecontextEval aligns generated vs reference columns on a small fixture.

**Acceptance criteria.** On a 10-workspace fixture with reference tables (arxivDIGESTables-style): column/value recall ≥ 0.6; per-cell evidence coverage ≥ 0.9; DecontextEval runs in CI.

**Risks.** Hallucinated cell values → span requirement + coverage metric + `null` allowed. Abstract-only related papers give thin cells → mark cell `grounding:"abstract"`.

**Prerequisites.** P9.

---

## Phase 11 — Research-gap objects  (L)  ← third contribution area

**Objectives.** The structured, evidence-grounded, confidence-labelled `ResearchGap`. Pipeline: matrix → rule candidates → evidence assembly (≥2 papers) → constrained articulation → self-support check → confidence band → human accept/reject.

**Files/modules.** `services/gaps/{matrix,candidates,evidence,articulate_llm,confidence}.py`, `llm/prompts/{gap_articulate_v1}.jinja` (constrained), reuse `rag/verify.py` for self-support, `domain/gap.py`, `db/models.py` (research_gaps) + migration `0011_research_gaps`, `routers/synthesis.py` (`gaps`).

**Dependencies.** none new.

**APIs delivered.** `POST /workspaces/{id}/gaps` (async), `GET /workspaces/{id}/gaps`, `POST /workspaces/{id}/gaps/{gap_id}` (accept/reject).

**Tests.** a candidate with < 2 supporting papers is dropped; the articulation prompt cannot introduce a claim without a cited span (adversarial fixture: LLM tries to add an unsupported claim → caught); `CONTRADICTION` gaps require conflicting spans from ≥2 papers; confidence band derives only from `confidence_basis`; `self_support_passed=false` → dropped; **no percentage appears in `confidence`** (enum only).

**Acceptance criteria.** On a 10-workspace expert-rated set (Evaluation Plan §Gap): ≥ 60 % of surfaced gaps rated "relevant/plausible" by ≥ 2 experts; evidence-support rate = 100 % (every surfaced gap has ≥ 2 valid spans); hallucination rate (claims not in a cited span) ≤ 2 %; beats the "ask GPT-4 for gaps" baseline on expert relevance.

**Risks.** LLM over-generalises from a thin matrix → strict rules gate candidates before the LLM; abstract-only evidence weakens confidence → `evidence_coverage` down-weights it. Expert-rating throughput → small set, clear rubric.

**Prerequisites.** P10, P13 (matrix is a graph projection — can be built from profiles directly for MVP, upgraded when P13 lands).

---

## Phase 12 — Research directions  (M)

**Objectives.** Directions from **accepted gaps only**; LLM generate → LLM critique; `kind` label (`evidence_backed_inference` vs `llm_hypothesis`); feasibility explicitly uncertain.

**Files/modules.** `services/directions/{generate,critique}.py`, `llm/prompts/{direction_generate_v1,direction_critique_v1}.jinja`, `domain/direction.py`, `db/models.py` (research_directions) + migration `0012_research_directions`, `routers/synthesis.py` (`directions`).

**Dependencies.** none new.

**APIs delivered.** `POST /workspaces/{id}/directions`.

**Tests.** a direction cannot be generated for a non-accepted gap; every direction carries `kind`, `critique` scores, and `confidence`; `motivation` cites the gap's evidence; low critique score → flagged, not dropped.

**Acceptance criteria.** Expert rubric (novelty/specificity/feasibility/groundedness, 1–5): median groundedness ≥ 3.5; directions are never phrased as established facts (checked by a lint prompt + human spot-check).

**Risks.** LLM ideas over-novel / infeasible *[Si et al.]* → critique pass + uncertain feasibility label + tie to a specific gap.

**Prerequisites.** P11.

---

## Phase 13 — Research graph (per workspace)  (M)

**Objectives.** `networkx` graph of Paper/Method/Dataset/Topic/RQ/Claim/Gap/Direction nodes with the 10 edge types; JSON-persisted on the workspace; powers global "themes/gaps" questions and the gap matrix.

**Files/modules.** `services/graph/{builder,query}.py`, `domain/graph.py`, migration `0013_workspace_graph_json` (adds `workspaces.graph_json`), `routers/workspaces.py` (`GET /workspaces/{id}/graph`), `services/rag/retriever.py` (GraphRAG routing hook).

**Dependencies.** networkx.

**APIs delivered.** `GET /workspaces/{id}/graph`; `mode:"themes"` routing in `POST /workspaces/{id}/chat`.

**Tests.** graph rebuilds incrementally on paper add/remove; global question ("what dataset do these share?") answered from graph traversal, not top-k; node/edge counts bounded; user correction of a node persists.

**Acceptance criteria.** On a themes-question fixture set, GraphRAG routing beats flat top-k on an LLM head-to-head (comprehensiveness); graph builds in < 5 s for 30 papers.

**Risks.** Entity-extraction noise → keep the graph small, inspectable, correctable; do not build a global KG (rationale: Architecture §5).

**Prerequisites.** P8, P9.

---

## Phase 14 — Agentic orchestration  (M)

**Objectives.** Harden the `ResearchOrchestrator`: bounded plan DAG, typed tool registry, the 5 bounded decisions, budget guard, answerability gating, "show your work" via `tool_log`/`stage_runs`.

**Files/modules.** `services/orchestrator/{orchestrator,tools,budget,answerability}.py` (finalised), `telemetry/stage_timer.py` wired into every tool, a `GET /workspaces/{id}/activity` read of `stage_runs`.

**Dependencies.** none new.

**APIs delivered.** `GET /workspaces/{id}/activity` (tool-call log); orchestrated variants of discover/gaps/directions already exposed.

**Tests.** the plan is a fixed DAG (no runtime node creation); the extra-citation-hop / regenerate-once / answer-vs-IDK decisions each have a unit test at the boundary; budget guard degrades (fewer strategies, smaller k) before failing; every tool call writes a `stage_runs` row; no unbounded loops (max-iterations asserted).

**Acceptance criteria.** Agentic vs non-agentic ablation (A10/A-agentic) runs and shows the orchestrated path's effect on faithfulness / discovery recall / citation integrity / latency / cost, all logged.

**Risks.** Scope creep toward a multi-agent swarm → the design forbids it; review at PR time against Architecture §4. Cost of the extra LLM verification calls → budget guard + config to disable in a "fast" mode.

**Prerequisites.** P5–P12.

---

## Phase 15 — Frontend integration  (L)

**Objectives.** The coherent Streamlit workflow: Upload → Paper Analysis → Discover (per-strategy progress) → Research Trail (grouped by type) → Selection (select/deselect/pin/remove/inspect reason) → Workspace tabs (Overview · Papers · Research Trail · Chat · Compare · Research Gaps · Research Directions · Citations · Presentation).

**Files/modules.** `frontend/streamlit_app/` — `Home.py`, `pages/{1_Upload,2_Analysis,3_Discover,4_Trail,5_Workspace}.py`, `lib/api.py` (typed client), `lib/sse.py`, components for the signal-score breakdown, trail-type groups, hover-evidence, gap cards.

**Dependencies.** streamlit, httpx-sse (or raw SSE parse).

**APIs delivered.** none (consumes existing).

**Tests.** a Playwright/Streamlit e2e smoke: upload a fixture PDF → analyse → discover → see trail groups → select 3 → open workspace → ask a chat question → see a cited answer → generate a gap → accept it → generate a direction → export citations. Screenshot diffs for the trail + gap card.

**Acceptance criteria.** A first-time user completes seed→workspace→one gap in < 10 min without instructions; every ranked paper shows its per-signal reasons; every chat answer shows hover-evidence; no dead tabs.

**Risks.** Streamlit's re-run model vs long jobs → poll `GET /jobs/{id}` with a progress bar; SSE for chat only. If Streamlit friction is high, this phase de-risks the eventual Next.js port (API unchanged).

**Prerequisites.** P9–P13.

---

## Phase 16 — Evaluation & ablations  (L)

**Objectives.** The full harness from `docs/evaluation/ResearchNexus_Evaluation_Plan.md`: per-stage metrics, ablations A1–A13, baselines B1–B9, the composite `W`. Tune `RankingWeights` and trail thresholds on the validation split.

**Files/modules.** `eval/{harness,discovery_eval,ranking_eval,trail_eval,rag_eval,citation_eval,gap_eval,e2e_eval,ablations}.py`, `eval/datasets/` (RN discovery benchmark builder; trail-label set; gap-rating set), `scripts/run_eval.py`, a results table generator.

**Dependencies.** ragas (already), scikit-learn (metrics), pandas.

**APIs delivered.** none (offline).

**Tests.** each metric function has a unit test with a known-answer fixture; ablation switchboard toggles exactly one component; `W` recomputes from component files.

**Acceptance criteria.** A reproducible `run_eval.py` produces: discovery Recall@20 per strategy + fused; nDCG@10 for ranking; per-type trail F1; RAGAS + ALCE for RAG; gap expert-rating summary; `W` for RN and B1–B9; tuned `w1-*` weights checked in with the eval run that produced them.

**Risks.** Human-eval bottleneck (trail labels, gap ratings) → keep sets small (150 edges, 10 workspaces), write clear rubrics, recruit 2 raters. Benchmark contamination → prefer seeds published after common model cut-offs.

**Prerequisites.** P6, P7, P9, P11 (and ideally P15 for e2e).

---

## Phase 17 — Security hardening  (M)

**Objectives.** Implement and test the full §22 model.

**Files/modules.** `security/{pdf_sanitizer,prompt_guard,rate_limit,key_vault,allowlist}.py` (finalised), a security test suite `tests/security/`, a pre-release checklist.

**Dependencies.** slowapi or a hand-rolled token bucket; python-magic (MIME sniff).

**Coverage.** PDF prompt-injection (delimited data + "content not instructions" preamble; injection-pattern strip); malicious PDFs (size/page/ratio caps, resource-limited worker, JS disabled); SSRF (fixed host allowlist; no user/document URLs ever fetched); API-key protection (ciphertext only, never logged/returned/URL'd; `stage_runs` stores hashes only); tenant isolation (cross-tenant → 404; Postgres RLS policies); rate limiting per bucket; file validation; resource limits; LLM prompt isolation; citation integrity (LLM cannot emit references; monitored fabrication rate); logging without secrets.

**Tests.** an injected-instruction PDF does not change tool selection or the fetch allowlist; a document-supplied URL is never fetched; a captured log stream contains no key material and no prompt bodies; a cross-tenant request returns 404; rate-limit buckets enforce and emit `Retry-After`.

**Acceptance criteria.** The security checklist passes; a lightweight threat-model review (or `security-reviewer` agent) finds no High/Critical issue in the diff.

**Risks.** Injection patterns evolve → treat as data always (structural mitigation), not just pattern-matching. Semgrep Guardian hook currently unauthenticated in this environment → CI runs its own SAST leg; local hook is advisory.

**Prerequisites.** P1–P9 (touches upload, external, llm, api-keys, chat).

---

## Phase 18 — Deployment  (M)

**Objectives.** Reproducible deploy of the backend + Streamlit UI; migrations; backups; observability; job queue for research/prod.

**Files/modules.** `Dockerfile` (backend), `docker-compose.yml` (backend + Postgres + Redis + Streamlit), `scripts/deploy/*`, `alembic upgrade head` in the release step, `backend/app/telemetry/otel.py` (optional), a `.env.example` (no secrets), `README.md` (run + deploy).

**Dependencies.** arq + redis (research/prod job queue), gunicorn/uvicorn workers, an object-storage client (S3-compatible) for PDFs + FAISS/DB backups.

**APIs delivered.** none.

**Tests.** a compose-up smoke test in CI: migrate → health green → upload fixture → analyse → discover (mocked externals) → workspace → chat (mocked LLM) → gap.

**Acceptance criteria.** One command brings up the stack; migrations run idempotently; nightly backup of Postgres + `data/faiss/` + PDFs to object storage; structured logs shipped; SSE works through the proxy (`proxy_buffering off`).

**Risks.** Single-box memory (embeddings + reranker + FAISS) → document 4 GB minimum, lazy-load models, LRU-bound indices. SSE + reverse proxy buffering → explicit config + a smoke test.

**Prerequisites.** P1–P15.

---

## MVP vs Research/Publication-grade split

**MVP (Phases 1–10 + a thin 15 + minimal 17) — a usable, honest product:**

| In MVP | Notes |
|---|---|
| arXiv upload + PDF ingestion + section-aware structure | P2 |
| ResearchProfile (Pydantic, validated, provenance-checked) | P3 |
| Discovery: **keyword + semantic (chunk) + semantic_doc (SPECTER2) + citation (1-hop) + query-expansion** | subset of P5 (method/topic/RQ views can be `semantic_doc` re-uses initially) |
| Dedupe + filter | P4 |
| Transparent multi-signal ranking + per-paper explanation (initial weights, clearly labelled) | P6 |
| Typed trail: `FOUNDATIONAL / SIMILAR / RECENT / DATASET_RELATED` by rules + LLM confirm; `COMPETING`/`METHOD_EXTENSION` best-effort; `POTENTIALLY_CONTRADICTORY` **flagged only with dual-span evidence** | P7, high-precision subset |
| Persistent workspace (add/remove/pin/tag) | P8 |
| Multi-paper RAG with rerank + contextual filter + `IsSupported?` + faithfulness gate + hover-evidence | P9 |
| Summary + key points | P9 |
| Comparison table (deterministic schema, cited cells) | P10 |
| **Basic gap objects** — coverage/evaluation/contradiction rules, ≥2-paper evidence, confidence band, human accept/reject | P11 subset (rules + articulation + self-check; no learned confidence calibration) |
| Deterministic citations (APA/IEEE/BibTeX) + ALCE spot-check | P9 |
| Streamlit UI covering the whole flow | thin P15 |
| Security essentials: upload caps, host allowlist, prompt isolation, BYOK ciphertext, tenant scoping, rate limits | subset of P17 |
| Telemetry: `stage_runs` (latency/tokens/cost) | P8 |

**Deliberately NOT in the MVP (avoid over-engineering):** learned/tuned ranking weights; full 7-strategy discovery with 2-hop citations and agentic crawler expansion; per-workspace research graph + GraphRAG routing; research directions; confidence **calibration**; multi-agent critique; Nougat/MinerU integration; Next.js UI; Redis/arq job queue; ablation suite; composite `W`.

**Research / publication-grade version (Phases 11–14, 16, + full 5, 13, 15, 17, 18):**

| Added | Why it matters for a paper |
|---|---|
| Full 7-strategy discovery (method / topic / research-question views, 2-hop citations, bounded agentic expansion) | the "multi-strategy" claim; ablations A1–A6 |
| Learned / tuned ranking weights + reason-accuracy study | contribution area 1, with evidence |
| All 7 trail types + confidence calibration + human-agreement study | contribution area 2, with evidence (ablation A9) |
| Per-workspace research graph + GraphRAG routing for themes/gaps | contribution area 3 substrate (ablation A13) |
| Full `ResearchGap` with `evidence_coverage`, calibrated confidence, novelty assessment; baseline comparison | contribution area 3, with evidence |
| Research directions + critique + `kind` labelling | rounds out the workflow |
| Agentic orchestrator with the ablation (agentic vs fixed pipeline) | the brief's requested comparison |
| **End-to-end evaluation harness + composite `W` + baselines B1–B9 + ablations A1–A13** | contribution area 4 — the methodological contribution |
| Contamination-controlled RN discovery benchmark + expert-rated trail/gap sets | reproducibility |
| Next.js UI, Redis/arq queue, OTel, backups | deployment maturity (not a research claim) |

---

## Critical risks (cross-cutting)

1. **Citation hallucination.** Even good LLMs fabricate references 78–90 % on scientific synthesis *[OpenScholar]*. → Structural fix: the LLM **never** emits references; `services/citations/formatter.py` is the only source; fabrication rate is a monitored, target-0 metric; enforced by a test in P9.
2. **Research-gap hallucination.** LLMs invent plausible gaps and self-evaluate poorly *[Si et al.]*. → Rules gate candidates *before* the LLM; ≥2-paper evidence with spans; self-support check; confidence bands not percentages; human accept/reject. This is the riskiest contribution area — treat P11's acceptance criteria as gating.
3. **Discovery recall.** No single strategy is enough *[LitSearch]*; multi-strategy adds cost and latency. → Bounded runner, per-strategy timeouts, budget guard, ablations to prove each strategy earns its keep.
4. **PDF structure extraction.** Scanned / 2-column / equation-heavy PDFs break parsers *[PDFTriage assumes structure; Nougat/MinerU are partial]*. → `parse_confidence` surfaced, Nougat fallback, never silent; disable figure-only answers.
5. **Cost & latency under BYOK.** The full workflow is many LLM calls across the user's paid key. → Per-workspace token/USD budget with graceful degradation; report cost per stage (a differentiator — few papers do); a "fast mode" that skips optional verification.
6. **Memory footprint.** Two embedding models + a cross-encoder + FAISS on a small box. → Lazy load, LRU-bounded resident indices, document a 4 GB minimum for research/prod.
7. **Novelty framing.** Must not claim FAISS/RAG/embeddings/summarisation as novel. → Every doc repeats the "integration + 4 contribution areas" framing; the evaluation is built to substantiate exactly those four, not the components.
8. **Human-evaluation throughput.** Trail labels, gap ratings, reason-accuracy all need people. → Small, well-specified sets (150 edges, 10 workspaces), 2 raters, clear rubrics; scheduled early in P16.
9. **Provider variability.** Quality/latency vary by BYOK provider. → Provider-agnostic prompts, capability probe on connect, results reported per provider, never a hard-coded model.
10. **External API fragility / TOS.** OpenAlex/S2/arXiv rate limits and schema drift. → Cache hard, pin to documented fields, S2 fallback-only, graceful "N of M sources reached".

---

## Recommended implementation order (condensed)

`P1 → P2 → P3 → P4 → P5(MVP subset) → P6 → P7(high-precision subset) → P8 → P9 → P10 → thin P15 → MVP-essentials of P17`  → **MVP demo**.
Then `P11 → P13 → P12 → P14 → full P5 → full P7 → P16 (tune weights + ablations) → full P15 → full P17 → P18` → **research-grade**.

---

## First implementation task (when approved)

**Task 1 — Phase 1 skeleton (no domain logic).**

Scope:
1. `backend/pyproject.toml` with the P1 dependency set + ruff/mypy/pytest config; `README.md` run instructions.
2. `app/main.py` (FastAPI app, router registration), `app/config.py` (pydantic-settings, env-only), `app/deps.py` (`get_db`, `get_current_user` stub verifying a dev JWT, `get_llm_client`).
3. `app/db/session.py`, `app/db/models.py` with **only** `users` + `api_keys`; Alembic init + migration `0001_users_apikeys`.
4. `app/security/key_vault.py` — envelope encryption (a local KEK from env for dev; interface ready for KMS).
5. `app/llm/client.py` + `providers/openai_compat.py` + `providers/gemini.py` + `capability_probe.py` — `chat()` and `structured()` with a `schema_repair` retry; **no business prompts yet**.
6. `app/routers/health.py`, `app/routers/settings_keys.py` (`GET|PUT|DELETE /settings/llm-keys`, `POST /settings/llm-keys/test`).
7. `app/telemetry/logging.py` (structlog JSON; a redaction processor for anything key-shaped).
8. `.github/workflows/ci.yml` — ruff + mypy + pytest (SQLite).
9. Tests: health checks; JWT accept/reject; key ciphertext round-trip + **log-redaction assertion**; capability probe against a mocked OpenAI-compatible server; `unsupported_provider` → 400.

Acceptance: CI green; a dev can `PUT` a Groq key, `POST .../test` returns `success:true` + capabilities, and the DB row holds ciphertext + `key_last4` only, with nothing key-shaped in the logs.

Out of scope for Task 1: PDF handling, profiles, discovery, workspaces, any domain prompt.

---

*Design only. No application source code is created by this document. Every phase decision is traceable to the literature review, the abstract's requirements, or a stated engineering rationale. No facial-recognition / attendance content appears anywhere.*
