# ResearchNexus — API Specification

**Purpose.** The HTTP contract between the frontend (Streamlit MVP / Next.js later) and the FastAPI backend. **Design only — no routes are implemented by this document.**

**Companions:** `ResearchNexus_Implementation_Architecture.md`, `ResearchNexus_Data_Model.md`, `ResearchNexus_Implementation_Roadmap.md`, `docs/evaluation/ResearchNexus_Evaluation_Plan.md`.

---

## 1. Conventions

- **Base path:** `/api/v1`. JSON in/out (`application/json`), UTF-8. File upload is `multipart/form-data`.
- **Auth:** `Authorization: Bearer <JWT>` on every route except `GET /health` and the auth-exchange route. JWT is issued by the configured auth provider (Cognito / local dev); the backend verifies signature + `exp` + audience. `owner_id` is derived from the token — never from the body or query.
- **Tenant isolation:** every workspace-scoped resource is filtered by `owner_id`; a mismatch returns `404` (not `403`, to avoid resource-existence disclosure).
- **IDs** are opaque strings (ULIDs) as defined in the Data Model.
- **Timestamps** are UTC ISO-8601.
- **Idempotency:** unsafe POSTs that create resources accept an optional `Idempotency-Key` header; a repeat within 24 h returns the original result.
- **Pagination:** list endpoints take `?limit` (default 20, max 100) and `?cursor` (opaque); responses include `next_cursor` (null when exhausted).
- **Rate limits:** per-user token-bucket. Buckets: `read` (60/min), `write` (20/min), `discovery` (5/min), `generation` (20/min), `apikey_test` (5/min). Exceed → `429` with `Retry-After`.
- **Long tasks are async.** `POST` returns `202 Accepted` with a `Job` (`job_id`, `status:"queued"`, `poll_url`); the client polls `GET /jobs/{job_id}` or subscribes to `GET /jobs/{job_id}/events` (SSE). Short tasks return `200`/`201` directly.
- **Streaming:** chat uses **SSE** (`text/event-stream`); events: `token`, `citation`, `usage`, `done`, `error`.
- **BYOK LLM:** generation routes require a saved, working provider key (`api_keys.status = "working"`); otherwise `409 llm_key_required`. The client never sends the raw key in a generation request — the server decrypts it in-memory per call.

### 1.1 Standard error envelope

```json
{ "error": { "code": "string_snake_case", "message": "human readable", "details": { }, "request_id": "req_..." } }
```

| HTTP | `code` examples | meaning |
|---|---|---|
| 400 | `invalid_request`, `unsupported_provider` | malformed body / params |
| 401 | `unauthenticated` | missing/invalid token |
| 403 | `forbidden` | authenticated but not allowed (rare; most cross-tenant → 404) |
| 404 | `not_found` | resource missing or not owned by caller |
| 409 | `llm_key_required`, `conflict`, `already_processing` | precondition unmet |
| 413 | `file_too_large` | upload exceeds `MAX_PDF_MB` |
| 415 | `unsupported_media_type` | not a PDF |
| 422 | `pdf_invalid`, `pdf_scanned`, `pdf_encrypted`, `validation_error` | file/schema rejected |
| 429 | `rate_limited` | bucket exceeded (`Retry-After`) |
| 502 | `provider_error` | user's LLM provider failed after retries |
| 503 | `upstream_unavailable` | arXiv/OpenAlex/etc. unavailable after retries (partial results may still be returned with `206`) |
| 500 | `internal_error` | unexpected |

### 1.2 Common objects (see Data Model for full schemas)

`Job`, `ResearchProfile`, `PaperCandidate`, `RankedPaper`, `TrailEdge`, `ResearchWorkspace`, `WorkspacePaper`, `ResearchGap`, `ResearchDirection`, `Citation`, `Claim`.

---

## 2. Health & auth

### `GET /health`
No auth. `200 {"status":"ok","version":"...","checks":{"db":"ok","faiss":"ok","embeddings":"loaded"}}`.

### `POST /api/v1/auth/session`
Exchange a provider token for a ResearchNexus session JWT (local dev: email+password). `200 {"token":"...","expires_at":"..."}`.

### `GET /api/v1/me`
`200` user profile `{id,email,created_at,has_working_llm_key:bool,default_provider:string|null}`.

### `DELETE /api/v1/me`
Delete account. Cascades: api_keys, workspaces (+ their chunks/edges/gaps/directions/citations/chat/artefacts/jobs), owned search_runs, and the FAISS index files + uploaded PDFs in object storage. `202` → `Job(kind=account_delete)`.

---

## 3. LLM provider keys (BYOK)

### `GET /api/v1/settings/llm-keys`
`200 {"keys":[{"provider":"groq","status":"working","key_last4":"a1b2","checked_at":"..."}]}` — **never** returns ciphertext or full key.

### `POST /api/v1/settings/llm-keys/test`
Body `{"provider":"groq","api_key":"..."}`. Runs a minimal chat + a capability probe (JSON-mode support, context length, streaming). `200 {"success":true,"latency_ms":480,"capabilities":{"json_mode":true,"context_tokens":131072,"streaming":true}}` or `{"success":false,"message":"..."}`. Rate bucket `apikey_test`. The key is **not** persisted by this call.

### `PUT /api/v1/settings/llm-keys`
Body `{"provider":"groq","api_key":"..."}`. Server **re-tests**, then stores ciphertext (`key_ciphertext`) + `key_last4`. `200` with the redacted record. `400 unsupported_provider` if not in the fixed enum.

### `DELETE /api/v1/settings/llm-keys/{provider}`
`204`. Removes the ciphertext row.

---

## 4. Papers — seed pipeline (stateless, pre-workspace)

### `POST /api/v1/papers/upload`
`multipart/form-data`: `file` (PDF). Runs **S1 validation synchronously**, then **S2/S3 as a job**.
- `413 file_too_large` if > `MAX_PDF_MB` (30). `415` non-PDF. `422 pdf_encrypted` / `pdf_scanned` (no text layer) / `pdf_invalid`.
- `202`:
```json
{ "paper_id": "pap_...", "file": {"sha256":"...","size_bytes":1234567,"page_count":14},
  "job": {"job_id":"job_...","kind":"ingest","status":"queued","poll_url":"/api/v1/jobs/job_..."} }
```
When the job completes, `papers.has_full_text=true`, chunks + seed FAISS index + SPECTER2 doc embedding exist.

### `GET /api/v1/papers/{paper_id}`
`200` bibliographic + parse status:
```json
{ "id":"pap_...","title":"...","authors":[...],"year":2025,"venue":"...","doi":null,"arxiv_id":null,
  "has_full_text":true,"parse_confidence":"medium","page_count":14,
  "sections":[{"title":"1 Introduction","order":1,"page_span":[1,2]}],
  "tables":[{"caption":"Table 2: ...","page":6}] }
```

### `POST /api/v1/papers/{paper_id}/analyze`
Runs **S4 research-profile extraction** (1 LLM call) — requires a working LLM key. Synchronous (usually < 15 s); if the provider is slow it may return `202` + job.
- `200`:
```json
{ "profile": { /* ResearchProfile */ },
  "extraction_confidence": "high",
  "warnings": [] }
```
- `409 llm_key_required` if no working key.
- On repair failure → `200` with a partial profile, `extraction_confidence:"low"`, and `warnings:["profile_extraction_failed"]`.

### `PATCH /api/v1/papers/{paper_id}/profile`
Body: a partial `ResearchProfile` (field → new value). Marks touched fields `status:"user_edited"`. `200` with the merged profile. Used by the "edit profile" UI (Step 2).

### `POST /api/v1/papers/{paper_id}/discover-related`
Runs **S5 → S11** (search-concept generation, multi-strategy discovery, dedupe, filter, ranking, explanations, trail typing). **Always async.**
- Body (all optional):
```json
{ "strategies": ["keyword","semantic","semantic_doc","query_expansion","citation","method","topic","research_question"],
  "max_results": 60, "date_from": "2020-01-01", "date_to": null, "domains": [],
  "allow_extra_citation_hop": true, "weights_version": "w0-initial" }
```
- `202` → `Job(kind="discover")` with `progress` updating per strategy:
```json
{ "job_id":"job_...","kind":"discover","status":"running",
  "progress":{"keyword":"done","semantic":"done","semantic_doc":"running","citation":"queued", "...":"..."},
  "poll_url":"/api/v1/jobs/job_...","events_url":"/api/v1/jobs/job_.../events" }
```
- On completion, `result_ref` is a `run_id`. Partial success (some strategies failed) → job `status:"partial"` with `strategies_failed` listed.

### `GET /api/v1/papers/{paper_id}/related?run_id=run_...&type=SIMILAR&band=high&limit=20&cursor=...`
Returns the ranked, explained, typed results of the latest (or specified) discovery run.
- `200`:
```json
{ "run": { "run_id":"run_...","seed_paper_id":"pap_...",
            "strategies_succeeded":[...],"strategies_failed":[],
            "counts":{"raw":420,"after_dedupe":260,"after_filter":180},
            "extra_citation_hop_used":false, "weights_version":"w0-initial" },
  "results": [
    { "paper": { "id":"pap_...","title":"...","authors":[...],"year":2024,"venue":"EMNLP 2024","doi":"...","url":"..." },
      "discovery_methods": ["semantic_doc","citation"],
      "citation_relationship": "cited_by_seed",
      "signals": { "semantic_doc":0.81,"semantic_chunk":0.66,"problem_sim":0.79,
                   "method_sim":0.41,"dataset_overlap":0.5,"citation":1.0,"recency":0.55 },
      "weights_version": "w0-initial",
      "fused_score": 0.74, "rerank_score": 0.88, "final_rank": 3, "band": "high",
      "explanation": {
        "bullet_reasons": ["strong document similarity (0.81)","same research problem (0.79)",
                           "shares dataset BEIR","cited by the seed"],
        "prose": "Ranked highly because it targets the same retrieval-quality problem, evaluates on BEIR like the seed, and is directly cited by the seed.",
        "signals_used": ["semantic_doc","problem_sim","dataset_overlap","citation"],
        "template_only": false },
      "trail_edges": [
        { "edge_id":"edge_...","relationship_type":"FOUNDATIONAL","detection_method":"rule_llm_confirmed",
          "rule_fired":"cited_by_seed AND year<=seed_year-3","llm_confirmed":true,
          "confidence":"high","user_state":"pending",
          "evidence":[{"span":{"paper_id":"pap_seed","section":"2 Background","quote":"We build on ..."},"role":"seed_claim"}] }
      ] },
    "..."
  ],
  "next_cursor": null }
```
- Filters: `type` (RelationshipType), `band`, `method` (DiscoveryStrategy), `min_rank`/`max_rank`.
- `signals` always contains the **actual** values (or `null`); the client renders bands, never invents percentages.

---

## 5. Workspaces

### `POST /api/v1/workspaces`
Create a workspace from an analysed seed paper (+ optionally a discovery run to import from).
- Body: `{ "title":"...", "seed_paper_id":"pap_...", "import_run_id":"run_..."|null, "token_budget_usd":5.0 }`
- Preconditions: seed paper `has_full_text=true` and a profile exists → else `409 conflict` (`analyze` first).
- `201` → `ResearchWorkspace` (empty `papers` except the seed as `role:"seed"`).

### `GET /api/v1/workspaces` · `GET /api/v1/workspaces/{id}`
List (cursor) / fetch a workspace. `GET /{id}` returns the workspace plus counts (`papers`, `edges`, `gaps`, `directions`) and `cost_used`.

### `PATCH /api/v1/workspaces/{id}`
Body: `{ "title"?, "token_budget_usd"? }`. `200`.

### `DELETE /api/v1/workspaces/{id}`
`202` → `Job(kind=workspace_delete)` (cascades rows + FAISS files + graph JSON).

### `POST /api/v1/workspaces/{id}/papers`
Add papers (from the trail or manually).
- Body: `{ "paper_ids": ["pap_...","pap_..."], "from_run_id":"run_..."|null }` **or** `{ "manual": { "doi":"10..."|null, "arxiv_id":"..."|null, "url":"..."|null } }`.
- For each: create/link the `papers` row, resolve metadata (Crossref/OpenAlex/arXiv), fetch + chunk the abstract (or full text if a PDF is available), add to the combined index.
- `202` → `Job(kind="index_rebuild")` when the combined index/graph must rebuild; `201` with the updated `papers[]` for a cheap add.
- Trail edges' `user_state` for imported papers are set to `accepted`.

### `DELETE /api/v1/workspaces/{id}/papers/{paper_id}`
Remove a related paper (cannot remove the seed → `409`). `202` → `index_rebuild` job; dependent `artefacts` invalidated.

### `PATCH /api/v1/workspaces/{id}/papers/{paper_id}`
Body: `{ "pinned"?, "tags"?, "note"?, "order"? }`. `200` updated `WorkspacePaper`. (Covers pin / tag / annotate / reorder.)

### `GET /api/v1/workspaces/{id}/trail?type=&band=&state=`
The workspace trail (edges from the seed to workspace + still-candidate papers), grouped-friendly.
- `200`:
```json
{ "seed_paper_id":"pap_...",
  "groups": {
    "FOUNDATIONAL": [ { "target": {"id":"pap_...","title":"...","year":2021}, "edge": { /* TrailEdge */ } } ],
    "SIMILAR": [ ... ], "RECENT": [ ... ], "COMPETING": [ ... ],
    "METHOD_EXTENSION": [ ... ], "DATASET_RELATED": [ ... ], "POTENTIALLY_CONTRADICTORY": [ ... ] } }
```

### `POST /api/v1/workspaces/{id}/trail/{edge_id}`
Body: `{ "user_state": "accepted" | "rejected" }`. `200` updated edge. Rejections are remembered and suppress the same rule on re-run.

### `POST /api/v1/workspaces/{id}/trail/retype`
Re-run typing for a subset. Body: `{ "target_paper_ids": [...] }`. `202` → `Job(kind="trail")`.

---

## 6. Workspace synthesis operations

All require a working LLM key (`409 llm_key_required` otherwise) and respect the workspace token/USD budget (`429 budget_exhausted` with the current `cost_used` when the cap is hit; the orchestrator degrades before failing where possible).

### `POST /api/v1/workspaces/{id}/chat`  (SSE)
Multi-paper RAG Q&A. `Accept: text/event-stream`.
- Body: `{ "session_id":"cs_..."|null, "message":"...", "scope": {"paper_ids":[...] } | "all", "mode":"qa"|"themes" }`
  - `mode:"themes"` (or an auto-detected global question) routes to the per-workspace GraphRAG path.
- SSE events:
```
event: token      data: {"text":"Retrieval-augmented"}
event: citation   data: {"marker":"[1]","claim_id":"clm_...","paper_id":"pap_...","chunk_id":"chk_...","quote":"...","section":"4.2","page":7}
event: usage      data: {"prompt":1840,"completion":420,"cost_usd":0.004}
event: done       data: {"message_id":"cm_...","faithfulness":0.91,"answerable":true,"unsupported_dropped":1}
event: error      data: {"code":"provider_error","message":"..."}
```
- If `AnswerabilityGate` returns not-answerable: a single `done` event with `answerable:false` and `suggestion:"add papers on X"`, no tokens billed for generation.
- Non-streaming fallback: same body without the SSE `Accept` header → `200` with the full message + `claims[]`.

### `GET /api/v1/workspaces/{id}/chat/sessions` · `GET /.../chat/sessions/{sid}`
List sessions / fetch full message history with `claims`.

### `POST /api/v1/workspaces/{id}/summary`
Body: `{ "scope":"all"|{"paper_ids":[...]}, "length":"short"|"medium"|"long" }`. `200 { "summary_id":"...","text":"...","claims":[Claim], "faithfulness":0.9 }`. Map-reduce for long inputs.

### `POST /api/v1/workspaces/{id}/keypoints`
Body: `{ "paper_ids":[...] }`. `200` FacetSum-typed points per paper: `{ "papers":[{"paper_id":"...","points":[{"facet":"method","text":"...","span":{...}}]}] }`.

### `POST /api/v1/workspaces/{id}/compare`
Body: `{ "paper_ids":[...], "schema": ["method","dataset","metric","result"] | null }`. `null` → deterministic schema = union of method/model/dataset/metric profile fields.
- `202` for larger sets → `Job`; `200` for ≤ ~4 papers:
```json
{ "comparison_id":"...", "schema":["method","dataset","reported_metric","main_result"],
  "rows":[ {"paper_id":"pap_...","cells":{"method":{"text":"cross-encoder rerank","span":{...},"claim_id":"clm_..."}, "...":"..."}} ],
  "coverage": 0.92,           /* fraction of cells with a valid supporting span */
  "decontext_eval": null }    /* set by an eval run, not at request time */
```

### `POST /api/v1/workspaces/{id}/gaps`
Runs the structured gap pipeline (matrix → rule candidates → evidence assembly → constrained articulation → self-support check → confidence band). **Async.**
- Body: `{ "gap_types": ["METHOD_GAP","EVALUATION_GAP","CONTRADICTION", "..."] | null, "min_supporting_papers": 2 }`
- `202` → `Job(kind="gaps")`; `result_ref` → list of `ResearchGap` with `user_state:"candidate"`.

### `GET /api/v1/workspaces/{id}/gaps?state=candidate|accepted|rejected`
`200 { "gaps": [ ResearchGap ] }` — each carries `statement`, `supporting_papers`, `supporting_evidence` (spans + quotes), `conflicting_evidence`, `why_unaddressed`, `evidence_coverage`, `confidence`, `confidence_basis`, `proposed_direction`, `self_support_passed`.

### `POST /api/v1/workspaces/{id}/gaps/{gap_id}`
Body: `{ "user_state": "accepted" | "rejected" }`. `200`. Accepting a gap enables direction generation for it.

### `POST /api/v1/workspaces/{id}/directions`
Body: `{ "gap_ids": ["gap_..."] }` (must be `accepted`). Generates + critiques directions. `200 { "directions": [ ResearchDirection ] }` — each labelled `kind:"evidence_backed_inference" | "llm_hypothesis"` and carrying `critique` scores and an explicitly-uncertain feasibility.

### `POST /api/v1/workspaces/{id}/citations`
Body: `{ "paper_ids": [...] | "all", "formats": ["apa","ieee","bibtex"] }`. Deterministic build from resolved metadata.
- `200 { "citations": [ { "paper_id":"pap_...","resolved_from":"crossref","formatted":{"apa":"...","ieee":"...","bibtex":"@inproceedings{...}"} } ], "unresolved": ["pap_..."] }`
- Unresolved papers appear in `unresolved` with `formatted` fields = `"Not available"` — **never guessed**.

### `POST /api/v1/workspaces/{id}/presentation`
Body: `{ "audience":"group_meeting"|"conference", "max_slides": 12, "include": ["overview","trail","comparison","gaps","directions"] }`.
- `200 { "outline_id":"...", "slides":[ {"title":"...","bullets":[{"text":"...","cite":{"paper_id":"pap_...","claim_id":"clm_..."}}]} ] }` — every bullet cites a workspace paper.

### `GET /api/v1/workspaces/{id}/graph`
`200` the `ResearchGraph` JSON (nodes/edges) for the per-workspace research graph view.

---

## 7. Jobs

### `GET /api/v1/jobs/{job_id}`
`200` `Job` (`status`, `progress`, `result_ref`, `error`, `tokens`, `cost`). `result_ref` resolves via the relevant GET (e.g. a `discover` job → `GET /papers/{seed}/related?run_id=...`).

### `GET /api/v1/jobs/{job_id}/events`  (SSE)
`event: progress` (per-strategy / per-stage updates), `event: done` (`{status,result_ref}`), `event: error`.

### `POST /api/v1/jobs/{job_id}/cancel`
Best-effort cancel of a `queued`/`running` job. `202`.

---

## 8. Request/response schema summary (validation)

- All request bodies are Pydantic models; unknown fields → `422 validation_error` with a field list.
- All response bodies are Pydantic models serialised with `model_dump(mode="json")`.
- Enum values are exactly as in the Data Model (`DiscoveryStrategy`, `RelationshipType`, `GapType`, `JobKind`, `JobStatus`).
- Numeric scores in responses are the **actual computed values** or `null`; the API never emits a fabricated relevance percentage. `band` (`high/medium/low`) is threshold-derived.

---

## 9. Async vs sync vs streaming — quick reference

| Endpoint | Mode | Why |
|---|---|---|
| `POST /papers/upload` | sync validate + **async** ingest | parsing/chunking/embedding can take 10–60 s |
| `POST /papers/{id}/analyze` | **sync** (may fall back to async) | 1 LLM call, usually < 15 s |
| `POST /papers/{id}/discover-related` | **async (job)** with per-strategy progress | 6–8 parallel strategies + citation hops + rerank + typing = seconds–minutes |
| `GET /papers/{id}/related` | sync | reads a completed run |
| `POST /workspaces` | sync | metadata only |
| `POST /workspaces/{id}/papers` | sync add + **async** index rebuild | rebuild cost scales with #papers |
| `POST /workspaces/{id}/chat` | **SSE stream** | token streaming + inline citation events |
| `POST /workspaces/{id}/summary` / `keypoints` | sync (map-reduce may async) | bounded |
| `POST /workspaces/{id}/compare` | sync ≤ 4 papers, else **async** | per-cell LLM calls |
| `POST /workspaces/{id}/gaps` | **async (job)** | matrix + rules + evidence + articulation + self-check |
| `POST /workspaces/{id}/directions` | sync | per accepted gap |
| `POST /workspaces/{id}/citations` | sync | deterministic |
| `POST /workspaces/{id}/presentation` | sync (may async for many slides) | 1–2 LLM calls |

---

## 10. Security controls at the API boundary (see Roadmap §22 for the full model)

- **Auth** on every route but `/health` and `/auth/session`; `owner_id` only from the verified JWT.
- **Fixed provider enum** for LLM keys; **fixed host allowlist** for all outbound fetches (arxiv.org, api.openalex.org, api.semanticscholar.org, api.crossref.org, configured LLM base URLs, optional self-hosted Nougat). No user/document-supplied URL is ever fetched.
- **Upload limits:** `MAX_PDF_MB=30`, `MAX_PAGES=60`, MIME sniff, decompression-ratio guard, resource-limited parse worker.
- **Rate limits** per bucket (§1); `apikey_test` throttled to deter key probing.
- **No secrets in responses/logs:** key endpoints return `key_last4` only; `stage_runs` stores hashes/metrics, never prompt bodies or keys.
- **Prompt isolation:** document text is passed to the LLM layer as delimited data with a "content, not instructions" preamble; the API never interpolates document text into a system prompt.
- **Cross-tenant** access returns `404`.

*Design only. No routes, handlers, or middleware are implemented by this document. No facial-recognition / attendance content appears anywhere.*
