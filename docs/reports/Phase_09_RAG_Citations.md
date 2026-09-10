# ResearchNexus — Phase 9 Completion Report: RAG + Evidence/Citation System

**Scope.** Stage S13's RAG row (Architecture §3): verified multi-paper
question answering over a workspace, plus the deterministic citation build
and the summary / key-point synthesis that share its grounding machinery.
Implements only the RAG + citation surface; no comparison, gaps,
directions, research graph, UI, or orchestrator hardening.

**Companion docs.** `ResearchNexus_Implementation_Architecture.md` (§1.1
RAG/citation rows, §3 S13, §4 `EvidenceVerifier` / `Synthesis` /
`CitationBuilder` / `AnswerabilityGate`), `ResearchNexus_Data_Model.md`
(§6 `PaperChunk`, §10 `Citation` / `Claim`, §13), `ResearchNexus_API_
Specification.md` (§6), `ResearchNexus_Implementation_Roadmap.md` (Phase 9),
`ResearchNexus_Evaluation_Plan.md` (§5 RAG, §6 Citation integrity).

---

## Status

| Gate | Command | Result |
|---|---|---|
| Tests | `pytest -q` | **528 passed**, 2 warnings (pre-existing Starlette/anyio deprecations) |
| Lint | `ruff check .` | **All checks passed** |
| Types | `mypy app tests` | **Success: no issues in 212 source files** |
| Migrations | `test_migrations.py` + manual `0001->0008` up / `base` down / `0008<->0007` step | **round-trips clean**; ORM `create_all` and Alembic head schemas match for all four new tables |

56 new tests were added (all green); the rest of the suite is unchanged.
**No new dependencies** — see *Deliberate substitutions* below.

---

## Pipeline (Architecture §3 S13, fixed order)

```
retrieve (k=8)  ->  cross-encoder rerank (top 5)  ->  LLM contextual filter
   ->  answerability gate  ->  LLM generate (per-sentence chunk tags)
   ->  LLM IsSupported? verify  ->  faithfulness gate (regenerate x1, then warn)
   ->  deterministic claim -> chunk -> paper link
```

Every LLM stage degrades to a safe default; the pipeline never raises
because a provider misbehaved.

| Module | Responsibility |
|---|---|
| `retrieval/workspace_index.py` (`FaissWorkspaceIndex`, `WorkspaceIndexCache`) | Vector `WorkspaceChunkIndex` behind the Phase 8 Protocol. `IndexFlatIP` over L2-normalised MiniLM chunk embeddings (the deterministic `FakeEmbeddingProvider` is the test/default backend; `minilm` + a `faiss` vector backend are opt-in via `settings`). `build` / `load` (no re-embedding) / `add_paper` / `remove_paper`; `<ws>.npz` + `<ws>.meta.json` on disk. `WorkspaceIndexCache` is the bounded LRU. |
| `services/rag/retriever.py` | k≈8 over the workspace index, optional `scope_paper_ids`; enriches hits with `section` / `page` from `paper_chunks`. |
| `services/rag/rerank.py` | cross-encoder rerank -> top ~5; `FakeCrossEncoder` default, `cross-encoder` opt-in. |
| `services/rag/context_filter.py` | LLM keeps only verbatim-relevant sentences; a returned span that is not a literal substring of its chunk falls back to the whole chunk; no session / failure -> keep every chunk. |
| `services/rag/answerability.py` | deterministic: `< rag_min_answerable_chunks` kept -> "Not enough in this workspace" + keyword suggestion; the pipeline returns before generation, **billing no generation tokens**. |
| `services/rag/generate.py` | LLM returns sentences tagged with `chunk_id`s; a tag not in the retrieved set is dropped; `[1]` / `(Author, 2024)` strings are stripped from the prose. |
| `services/rag/verify.py` | LLM `IsSupported?` per sentence over its cited chunks; no cited chunk -> unsupported without a call; LLM failure -> unsupported (Architecture §4 safe default). |
| `services/rag/faithfulness.py` | context token-recall heuristic (the roadmap's "cheap heuristic first"); `< rag_faithfulness_min` -> one regeneration, then a `faithfulness_below_threshold` warning. |
| `services/rag/pipeline.py` | `answer_question(...) -> RagAnswer`; `build_answer_claims(...)` does the deterministic chunk->paper link. |
| `services/citations/formatter.py` | hand-rolled CSL -> APA / IEEE / BibTeX; missing title -> `"Not available"`. Golden tests. |
| `services/citations/metadata_resolver.py` | `PaperORM` stored metadata -> CSL-JSON + `resolved_from` (`crossref` / `arxiv` / `openalex` / `unresolved`); `to_citation(...)` returns a `Citation` whose `formatted` is `"Not available"` when unresolved. |
| `services/citations/validate.py` | `link_claims(...)` keeps only claims whose chunk ids were actually retrieved and derives `supporting_paper_ids` from the chunk->paper map (never the LLM). |
| `services/synthesis/summary.py` | reuses generate + verify + faithfulness; drops unsupported sentences; `to_claims(kind="summary")`. |
| `services/synthesis/keypoints.py` | LLM proposes FacetSum-typed points; a point survives only if its `text` is a **verbatim span** of a real `paper_chunks` row for that paper. |

### Persistence (migration `0008_chat_citations`)

`chat_sessions`, `chat_messages` (`ix_msg_session`, `citations` = list of
`Claim.claim_id`, `faithfulness` nullable), `citations`
(`UNIQUE(workspace_id, paper_id)`), `claims` (`ix_claims_workspace`,
`ix_claims_artefact`). All cascade-delete with their workspace / session.
Repository: chat session/message CRUD (tenant-scoped), `save_claims`
(upsert), `get_claims_for_artefact`, `upsert_citation`, `get_citations`,
`get_chunks_by_ids`.

### API (`app/routers/chat.py`, `app/routers/synthesis.py`)

| Endpoint | Notes |
|---|---|
| `POST /workspaces/{id}/chat` | SSE (`Accept: text/event-stream` -> `token` / `citation` / `usage` / `done`) and non-stream (same body -> `200` + `claims[]`) share one path. `409 llm_key_required` without a key; `404` cross-tenant. `mode:"themes"` falls back to QA with a `graphrag_not_available` warning (graph is Phase 13). Not-answerable -> single `done` with `answerable:false`, no generation billed. |
| `GET /workspaces/{id}/chat/sessions` · `/{sid}` | list / full history with `claims` resolved per assistant turn. |
| `POST /workspaces/{id}/summary` | `{scope, length}` -> `{summary_id, text, claims[], faithfulness}`. `409` without a key. |
| `POST /workspaces/{id}/keypoints` | `{paper_ids}` -> per-paper points each with a `span`. `409` without a key. |
| `POST /workspaces/{id}/citations` | `{paper_ids, formats}` -> `{citations[], unresolved[]}`. **Deterministic, needs no key.** Unresolved papers listed with `"Not available"`, never guessed. |

---

## Guarantees (verified by tests)

- **The LLM never emits a reference string** — `Citation.formatted` is built
  only by `formatter.py`; `strip_fabricated_references` removes `[n]` /
  `(Author, year)` from every generated sentence; golden APA/IEEE/BibTeX
  tests pin the deterministic output.
- **Every citation resolves to a real `PaperChunk`** — `generate` drops
  invented chunk ids; `link_claims` drops any claim whose chunks were not
  retrieved; `Claim` rejects an empty `supporting_chunk_ids` at
  construction (Data Model §10 invariant); key-point spans must be verbatim.
- **Unsupported claims are dropped or flagged** — `IsSupported?` gates every
  sentence; `rag_drop_unsupported` (default true) drops them and counts
  `unsupported_dropped`; an LLM verify failure defaults to unsupported.
- **Faithfulness gate** — one regeneration on a below-threshold score, then
  a warning (never a silent low-faithfulness answer).
- **Answerability** — thin evidence returns "not enough in this workspace" +
  a suggestion, and no generation tokens are billed.
- **Tenant isolation preserved** — every chat / synthesis route resolves the
  workspace through the Phase 8 owner gate (`404`, never `403`); chat
  sessions are `(workspace_id, owner_id)`-scoped.
- **Deterministic & testable** — `FakeEmbeddingProvider` + numpy
  `IndexFlatIP` + `FakeCrossEncoder` give byte-identical retrieval; the
  pipeline test asserts an identical `RagAnswer` across repeated runs.

---

## Tests (56 new)

| File | N | Covers |
|---|---|---|
| `test_citation_formatter.py` | 7 | APA (2/3 authors, DOI vs URL, n.d.), IEEE (initials-first, optional number), BibTeX (deterministic key, `@inproceedings` / `@article`), unresolved -> `"Not available"`, determinism. |
| `test_citation_resolver.py` | 5 | `resolved_from` precedence; CSL mapping + author-name split (space and comma forms); `to_citation` formatted vs unresolved. |
| `test_workspace_faiss_index.py` | 6 | build / search / membership; **`add` / `remove` update search**; persist + **load without re-embedding**; deterministic embed+search; **LRU eviction (least-recently-used)**; factory backend switch. |
| `test_rag_stages.py` | 13 | rerank order + truncation; contextual filter verbatim-only / paraphrase fallback / degrade (no session, provider error); generate drops invented ids + strips markers / not-ok on failure; verify supported vs flagged / no-chunk / LLM-failure-as-unsupported; faithfulness token-recall; answerability + suggestion; `strip_fabricated_references`; `link_claims` drops unretrieved + fills papers. |
| `test_rag_pipeline.py` | 8 | happy path grounded + faithful + claims; **unsupported sentence dropped + counted**; **answerability skips generation (no billing)**; **faithfulness failure -> exactly one regeneration**; generation failure -> warning; no session degrades without raising; scope restricts retrieval; deterministic repeat. |
| `test_synthesis.py` | 5 | summary keeps only supported sentences + faithfulness + `summary` claims; unavailable without a key; generation-failure warning; keypoints drop paraphrased / unknown-chunk points + emit spans; unavailable without a key. |
| `test_db_repository_rag.py` | 5 | chat session/message round-trip + **tenant scoping**; session delete cascades messages; `save_claims` upsert; workspace delete cascades claims + citations; citation upsert unique per `(workspace, paper)`. |
| `test_chat_synthesis_api.py` | 7 | chat `409` no key / `404` cross-tenant; non-stream grounded answer + persisted history + claims; **SSE emits `token` / `citation` / `usage` / `done`** with a real span; not-answerable turn; summary supported claims; keypoints spans; **citations deterministic + no key required**. |

Maps to the Roadmap Phase 9 test list: unsupported sentences never rendered
with empty `supporting_chunk_ids`; the faithfulness gate triggers exactly
one regeneration then warns; the answerability gate returns "not enough" +
suggestion with no generation billing; a fabricated reference string is
stripped; citation formatter golden tests; SSE emits
`token` / `citation` / `usage` / `done`.

---

## Acceptance criteria

| Criterion (Roadmap Phase 9) | State |
|---|---|
| retrieve -> rerank -> contextual filter -> generate (per-sentence tags) -> `IsSupported?` -> faithfulness gate -> render with hover-excerpts | **Met** — implemented end to end; SSE `citation` events carry `quote` / `section` / `page`. |
| Deterministic citation build + "Not available" for unresolved; LLM never emits references | **Met** — hand-rolled formatter + golden tests + `strip_fabricated_references`. |
| Answerability gating; "I don't know" with no generation billing | **Met** — deterministic gate; token totals prove generation did not run. |
| **Fabricated-reference rate = 0** | **Met by construction** — generation output is stripped of reference-shaped strings; the only reference source is the formatter. |
| RAGAS faithfulness >= 0.85 median; unsupported-sentence rate <= 5 %; citation P/R; p95 first-token latency < 3 s | **Deferred to Phase 16** — these are benchmark numbers over QASPER + an M3SciQA-style set with the `ragas` library and an ALCE-style NLI harness (Evaluation Plan §5-6). The runtime gate here is the roadmap's sanctioned "cheap heuristic first"; `run_eval.py` + `ragas` are Phase 16. |
| ALCE-style citation precision/recall | **Deferred to Phase 16** — `Claim.citation_precision` / `citation_recall` columns exist and stay `None` at request time (set by eval runs). |

---

## Deliberate substitutions (no new dependencies)

- **`ragas` (roadmap dep) — deferred to Phase 16.** The roadmap's own risk
  note says "gate on a cheap heuristic first, full RAGAS in eval runs";
  `ragas` pulls a large langchain/datasets tree and is an eval-harness
  concern (Evaluation Plan §5). The runtime faithfulness gate is a
  context token-recall heuristic behind a stable `score_faithfulness`
  signature an LLM-judge or `ragas` backend can later slot into.
- **`citeproc-py` / `bibtexparser` (roadmap deps) — replaced by a
  hand-rolled CSL formatter**, which the roadmap explicitly offers as the
  alternative ("citeproc-py **or a hand-rolled CSL formatter**"). Golden
  tests pin APA / IEEE / BibTeX output.
- **MiniLM embeddings + faiss `IndexFlatIP`** stay lazy-optional (the
  `embeddings` / `faiss` extras), same pattern as Phases 5-6. The
  deterministic `FakeEmbeddingProvider` + numpy `IndexFlatIP` are the
  default so the suite is hermetic; `settings.rag_embedder="minilm"` /
  `rag_vector_backend="faiss"` switch to the real stack.

---

## Deferred / explicitly out of scope

- **GraphRAG routing for themes/gaps questions** — needs the per-workspace
  research graph (Phase 13); `mode:"themes"` falls back to QA with a
  warning.
- **`artefacts` cache table** (summary/keypoints memoisation + invalidation)
  — a Phase 8 roadmap file-list item not built there or here; summaries are
  recomputed per request for now.
- **Async `202 -> Job` variants**, map-reduce over very large workspaces,
  per-provider latency reporting — Phase 14 / eval.
- **`compare` / `gaps` / `directions` / `graph` / `presentation` routes** —
  Phases 10-14.

---

## Traceability

Preserves the *IEEE BigData 2024 limitation -> ResearchNexus solution ->
evidence* chain: the source paper generates meta-analysis narrative text
rated only for overall relevance. Phase 9 makes every answer, summary and
key point a set of sentence-level `Claim`s, each carrying the exact
`chunk_id` -> `paper_id` -> source span it rests on, each `IsSupported?`-
checked, with references built deterministically and unsupported sentences
dropped — the per-claim auditable evidence trail the source approach does
not provide.

---

## Files changed

**New**

- `app/domain/{rag,citation,chat}.py`
- `app/retrieval/workspace_index.py` — `FaissWorkspaceIndex`, `WorkspaceIndexCache` (extends the Phase 8 file)
- `app/services/rag/{_llm,retriever,rerank,context_filter,answerability,generate,verify,faithfulness,pipeline}.py`
- `app/services/citations/{formatter,metadata_resolver,validate}.py`
- `app/services/synthesis/{summary,keypoints}.py`
- `app/routers/{chat,synthesis}.py`
- `migrations/versions/0008_chat_citations.py`
- `tests/unit/test_{citation_formatter,citation_resolver,workspace_faiss_index,rag_stages,rag_pipeline,synthesis,db_repository_rag}.py`
- `tests/integration/test_chat_synthesis_api.py`

**Modified**

- `app/db/models.py` — `ChatSessionORM`, `ChatMessageORM`, `CitationORM`, `ClaimORM`.
- `app/db/repository.py` — the Phase 9 persistence section + `get_chunks_by_ids`.
- `app/main.py` — register `chat.router`, `synthesis.router`.
- `app/config.py` — `rag_*` settings (retrieval/rerank widths, faithfulness floor, backend switches).
- `tests/unit/test_migrations.py` — assert the four new tables on upgrade / gone on downgrade.
- `pyproject.toml` — description bumped to "Phases 1-9".
