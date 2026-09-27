# ResearchNexus remediation plan

Audit date: 2026-09-27, against `efab08e` and the live dev database.
Rule for every phase: find the real root cause, write tests, fix it in the backend and/or frontend, verify, report, then stop before the next phase.
Ports are fixed: frontend `localhost:3000`, backend `localhost:8000`. No fallback port, ever.

## Root causes found in the audit

These are measured from the code and from the real `jobs` and `stage_runs` rows. None of them is a guess.

| # | Problem | Root cause found |
|---|---|---|
| 9 | Gaps fail | Every gaps run ends at **exactly 60 s**, which is `orchestrator_stage_timeout_s = 60`. The runs start by profiling unprofiled members through the LLM one after another. `asyncio.TimeoutError` has an empty message, so `jobs.error` and `stage_runs.error` are stored as `""`, and the UI can't say why the run failed. |
| 10 | Chat / DeepSeek fails | `OpenAiCompatClient` uses a 30 s httpx timeout and a non-streaming call. `httpx` timeout and transport errors are **not** turned into `LlmProviderError`, so they escape the RAG stages' `except`. There's no JSON mode for structured stages, and a malformed body raises a raw `KeyError`. The model is hard-coded to `deepseek-chat`. |
| 12 | Budget stays $0 | Cost is only written by `orchestrator.run_stage`, and no stage returns its token usage: every `stage_runs` row has 0 tokens. Chat doesn't go through the orchestrator at all. The USD figure is a blended guess (`estimate_cost_usd`), not the provider's price. |
| 13 | Wrong timestamps | SQLite drops the timezone. `repository._utc` was added by hand to only some reads (users, keys, workspaces, gaps and so on), so jobs, papers, runs, stage runs and workspace members still serialise naive, and the browser parses those as local time. |
| 1 | Profile | `evaluation_metrics` stores only the metric *name* ("Recognition accuracy"). The value ("95.83%") is only in the quote, because the schema never asks for it. The abstract is copied verbatim, including a parser prefix (`":\xa0 Facial…"`), and is shown in full. |
| 5 | "Why this rank" duplicates | `prose` is `"; ".join(bullet_reasons)`, and the "Why this rank" section re-lists the same bullets. Neither shows weights or each signal's contribution. |
| 6 | Ranking control | `RankOptions.weights` already exists, but `discover-related` always uses `w0-initial`. Nothing reaches it from the API. |
| 8 | "No text to read" | Discovered papers are never given full text: **0 of 1,436** discovered papers have a PDF. 43 workspace members have **no chunks at all**, not even the abstract chunk. Comparison can't tell "abstract only" from "has text but isn't indexed". |
| 3 | Slow discovery | The `run_discovery` stage alone takes 60–100 s, while ranking and trail together take under 2 s. The 90 s deadline and Semantic Scholar's ~1 request/s spacing dominate. The job reports only three coarse stages. |

## Phases (execution order)

The order follows dependencies, not the issue numbers.

### Phase 1: Startup, ports and process lifecycle (infrastructure)
- Add a committed `start.py` at the repo root. It will:
  - check and install dependencies (the Python venv and backend packages, Node and `node_modules`, the DB migration level);
  - detect the GPU;
  - start the backend on 8000 and the frontend on 3000;
  - `stop`, `restart` and `status` both servers.
- Move the Windows process management into it (the kill-on-close Job Object, the ancestor watch, and freeing a port only from a stale ResearchNexus server). `.claude/launch.json` will call `start.py`.
- The GPU tier is handed to the frontend as a startup hint. It isn't used until Phase 14.
- **Depends on:** nothing. **Unblocks:** everything, since every later verification needs clean servers.

### Phase 2: LLM provider integration, DeepSeek first (#10, backend)
- Base URL, model and authentication.
- Timeouts sized to the call.
- Map `httpx` errors to `LlmProviderError`.
- Parse the `choices` and `usage` fields safely.
- JSON mode for structured stages.
- Real streaming support.
- Clear provider error codes: auth, rate limit, timeout, bad reply.
- Capture token usage on every call, reusing the same fields as Phase 5.
- Tests will use DeepSeek-shaped responses.
- **Depends on:** Phase 1.

### Phase 3: Long-running jobs and gaps (#9)
- Size stage timeouts to the work: time the profile step per paper, or run it outside the stage limit.
- Never store an empty error: record the exception type and the stage.
- Report per-step job progress (profiling k/n, then candidates, then articulation).
- The gaps page will show the real reason and offer a retry.
- The same failure contract is reused by discovery in Phase 8.
- **Depends on:** Phase 2, because gaps call the LLM.

### Phase 4: One UTC time contract (#13)
- Add a `UTCDateTime` SQLAlchemy type that attaches UTC on every read. It replaces the ad-hoc `_utc` calls.
- Every API timestamp gets an explicit offset.
- One frontend formatting helper handles local time and "relative" times; every page will use it.
- **Depends on:** Phase 1.

### Phase 5: Usage accounting and budget (#12)
- Token counts come from the provider's `usage` reply, which is reliable. USD is not reliable with bring-your-own keys, where prices, cache-hit discounts and off-peak pricing vary.
- Record real tokens per stage and per chat turn.
- **Decision rule from the brief:** if the price can't be measured reliably, remove the USD budget and cap UI instead of showing misleading numbers.
- **Depends on:** Phase 2.

### Phase 6: Research profile quality and analysis layout (#1, #2)
- **Backend:**
  - metrics become name, value and quote, with the value checked against the quote;
  - clean the abstract of parser prefixes and broken line and hyphen joins;
  - add a short grounded summary.
- **Frontend (the analysis sections):**
  - show the summary with the abstract behind a "full abstract" toggle, and no "Abstract" label;
  - metrics show their values;
  - tighter section rhythm and sentence-case headings.
- **Depends on:** Phase 2, because extraction uses the LLM.

### Phase 7: Full-text acquisition and analysis coverage (#8)
- Trace the pipeline: acquisition, then PDF, parse, chunks and index, then profile, then comparison and RAG.
- Fetch open-access PDFs for discovered and added papers (arXiv, OpenAlex and Semantic Scholar OA links), then parse, chunk, index and re-profile on full text.
- Backfill the abstract chunk for members with no chunks.
- Every paper gets an explicit coverage state (full text / abstract only / not indexed) that the API returns and the UI shows.
- Comparison says "abstract only" instead of "No text to read" when that is the truth.
- **Depends on:** Phases 3 and 6. Needed before Phases 11 and 12.

### Phase 8: Discovery performance and progress (#3)
- Instrument each source and stage.
- Stream live progress: sources done, candidates found, time remaining.
- Cut the time spent waiting on rate limits.
- Make the deadline and failure handling explicit, with partial results clearly labelled.
- Backend failures are shown as failures, not hidden.
- **Depends on:** Phase 3's failure contract.

### Phase 9: Ranking control and explainability (#5, #6)
- **Backend:**
  - a weights parameter for discovery and re-ranking goes into `RankOptions.weights`, stamped with its own version;
  - the explanation gives each signal's value times its weight and its share of the final score.
- **Frontend:**
  - before discovery, six criteria sliders: topic similarity (document plus passage), research problem, methods, datasets, citation links, recency;
  - "Why this rank" shows the real decision.
- **Depends on:** Phase 8.

### Phase 10: Discovery results UX (#4)
- Replace the long card list with a scan-friendly research results view: full titles, rank and score bars, band, contribution strip, filters, a detail pane and keyboard navigation.
- **Depends on:** Phase 9.

### Phase 11: Full-screen focused workspace and Chat (#11)
- Build a shared focused-surface layout: a viewport-height stage, with secondary controls revealed by hover, proximity or focus (keyboard-accessible, reduced-motion safe).
- Chat comes first: the answer is readable in the main viewport, with evidence to the side.
- **Depends on:** Phases 2 and 5.

### Phase 12: Comparison workspace (#7)
- Paper picker with full titles, search, filters and a clear identity for each paper (authors, year, coverage).
- A matrix workspace instead of long scrolling, built on the Phase 11 layout, with coverage states from Phase 7.
- **Depends on:** Phases 7 and 11.

### Phase 13: Citations simplification (#16)
- One readable flow per paper: paper, then why it's cited, then the supporting passage, then where it's used, then actions. Plain language, with no internal terms.
- **Depends on:** Phase 11.

### Phase 14: Background modes and GPU fallback (#15)
- A setting with three choices: Animated (neural), Lightweight (React Bits `GhostFibers`, using the existing `ogl` dependency) and Static.
- Auto mode uses in-browser GPU detection (WebGL renderer and major-performance-caveat), falling back to the Phase 1 startup hint.
- Honour reduced motion.
- There is one background host, so it can never show two effects at once.
- **Depends on:** Phase 1.

### Phase 15: Research Graph redesign (#14)
- Composition, hierarchy, node and edge styling, labels, controls, the detail panel, and interaction and motion.
- A premium background-to-graph transition in both background modes.
- All current graph functionality is kept.
- **Depends on:** Phases 11 and 14.

### Phase 16: Polish and full regression
- Cross-page consistency, Impeccable audit, the full Playwright suite (desktop and mobile), the production build and a final real-flow run.

## Overlaps handled once
- **Job failure contract** (Phase 3) is reused by discovery (8) and any later job.
- **LLM usage capture** (Phase 2) feeds budget (5) and chat (11).
- **Coverage state** (Phase 7) feeds comparison (12), gaps evidence and chat citations.
- **Focused-surface layout** (Phase 11) is reused by compare (12), citations (13) and the graph (15).
- **GPU tier** (Phase 1) feeds background modes (14).

## Status
| Phase | State |
|---|---|
| 1 | done: `start.py` (deps, migrations, secrets, GPU, fixed ports, stop/restart/status); `launch.json` runs it |
| 2 | done: typed provider errors + retries, DeepSeek URL/model/thinking-off, JSON mode, streaming adapter, strict chat failures (nothing saved), `llm_calls` usage ledger (migration 0017) |
| 3–16 | not started |
