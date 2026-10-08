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
| 3 | done: concurrent first-use profiling + candidate checks with per-item limits and live job progress; typed run failures (provider kind / timeout / internal) with retry; grounding check no longer flags plain English (template fallback, never a dropped gap); rule facts given to the self-support check; temperature 0 for judgements; decisions kept by `match_key` (migration 0018) |
| 4 | done: `UTCDateTime` column type (aware UTC on read, naive refused on write) replaces the hand-patched `_utc` reads; comparison responses carry `created_at`; one frontend `lib/time.ts` (+ `<Timestamp>` with a shared 30 s clock) replaces `relativeTime`, `timeAgo` and every raw `toLocale*` |
| 5 | done: the USD estimate, the per-workspace cap and its guard are removed (the cost was a flat-rate guess, and it was never written, so it always read $0); usage comes only from the `llm_calls` ledger in the provider's own counts; `GET /api/v1/usage?range=7d|30d|90d|all[&workspace_id]` returns totals (input/cached, output/reasoning, calls/failed/unreported) by feature, model and workspace; every model call is labelled (stages by name; compare, summary and key points by route); stage runs keep the real tokens of their calls; Gemini now counts thinking tokens as output like every other adapter; Settings → Model usage replaces the budget editor, and the workspace overview shows its 30-day usage |
| 6 | done: one deterministic refinement (`services/profile/refine.py`) runs when a profile is built and when it is read, so all stored profiles benefit without re-extraction: abstract cleaned (label, markup, publisher/licence block, keyword tail, U+FFFD; `normalize/text.py`, also applied to discovery abstracts at ingestion), a verbatim two-sentence summary, `abstract_found=false` when a PDF had no abstract; metric values only when written in the metric's own verified evidence (`reported_value`, "respectively" mapped in order, ranges and series never guessed); sentence case and no stray full stops; near-duplicates merged and an item kept only under its most specific heading. Extraction: the JSON shape is now in the first request with JSON mode and temperature 0 (measured live: 1 DeepSeek call per profile instead of a parse failure plus a repair), short canonical names, metric `result`s with what they were measured on. `analyze` works for abstract-only papers (`grounding=abstract`). Frontend: one `ResearchProfileView` on both `/seed/[id]` and `/papers/[id]` (summary first, full abstract on demand, metrics table, evidence per item, only unmatched items marked); the legacy app shell uses its dark palette and the cinematic scrim, so its pages are legible |
| 7 | done: a paper found by discovery gets its full text from the sources ResearchNexus already uses, by its own identifiers (arXiv PDF; OpenAlex's open-access locations and PMC id; Europe PMC's full-text XML; Semantic Scholar's `openAccessPdf`), downloaded only from a fixed list of open-access hosts (every redirect hop re-checked, size-capped, a landing page is not a PDF), parsed by the same code as an upload, and attached to the existing paper (its abstract chunk kept for answers that cite it; every workspace's grounding moves to full text). Migration 0019 records what came of it (`papers.fulltext_*`), so nothing is downloaded twice and a negative answer is believed for a week (a failure for a day) before an automatic run asks again. Coverage state on every paper (`full_text` / `abstract_only` / `retrieval_failed` / `no_text`, with the reason), `POST /papers/{id}/fulltext`, `GET/POST /workspaces/{id}/coverage|fulltext`, and a background run when papers join a workspace. RAG and comparison read the new chunks at once; the gap engine re-profiles a paper read from its abstract once its full text exists. UI: coverage note with get/retry on both paper pages, per-paper coverage and a live run on the workspace overview, comparison headings say when full text arrived since |
| 8 | done: measured on two real seeds, a run took 62–64 s -- every strategy asked its sources one request after another, citation looked its reference DOIs up one at a time and hit its 30 s limit (and a stopped strategy lost everything it had found: citation returned nothing on every real run of 27 September), requests whose source asked for a 60 s pause (OpenAlex's paused anonymous search) were retried anyway, and 230–700 candidates were embedded on the event loop after every source had answered, then a quadratic near-duplicate pass (20 s at 650 candidates) and two commits per candidate. Now: a strategy's requests go out together (per-host spacing kept; arXiv's 3 s now honoured), read back in plan order so candidates and ranking don't depend on network timing; a strategy stopped by its limit keeps what it found; the search plan and the seed lookup run side by side; a 5xx asking for longer than the run can wait is not retried; only the records of candidates under the run's cap are scored, on a worker thread, while others are embedded as they arrive; the near-duplicate pass prunes with exact bounds (identical flags, 0.3 s); the run is saved in one transaction. Same two seeds: 31.0 s and 32.8 s with all six strategies complete; a re-run within 5 minutes 9.0 s (shared response cache). Ranking ties now break by the paper, never by a random id (re-ranking saved real runs reproduces the same order). Live job progress (`services/discovery/progress.py`): each step's state, time and enforced limit, each strategy's papers, each source's answers and refusals, the first papers in; kept on the run as `report` (migration 0020) so a partial run says what is missing. Jobs: cancel (`POST /jobs/{id}/cancel`), a start that follows the seed's run already going, `?job=` in the URL so a refresh resumes, jobs cut off by a restart failed at startup, a run silent for 60 s reported as stopped, failures that name the step and the reason, a failed save no longer leaving its job "running". Optional `openalex_api_key` (sent as a Bearer header). Search plan at temperature 0. UI: live step timeline with searches, sources and the first papers to arrive, cancel, partial-results notice and "How this search ran" |
| 9 | done: six ranking criteria (topic similarity -- document and passage, 2:1 --, research problem, methods, datasets, citation links, recency), 0–100 each, only their proportions matter, at least one must count; the defaults are the initial weights (`w0-initial`), any other setting is stamped `c-<t>.<p>.<m>.<d>.<c>.<r>`. They reach the real job (`POST /papers/{id}/discover-related {criteria}`, kept on the job) and re-rank a saved run without searching again (`POST /papers/{id}/related/rerank`): stored signals re-fused, the same order a fresh ranking gives, ties broken by the paper. Fusion renormalises over the signals a paper actually has. "Why this rank" is the real decision: each signal's value × its weight and its share of the score, and which signals were missing. Criteria are kept per device |
| 10 | done: the results are a scan-friendly list with full titles, rank, band, score bar and a contribution strip; search, band and found-by filters and five sorts; a detail pane ("Why this rank", abstract, authors, venue, found by); keyboard navigation; the criteria panel re-ranks in place; selection and "Create workspace…" in the toolbar |
| 11 | done: Chat verified end to end against DeepSeek with a real saved key: streamed stages, a verified answer with 4 citations (faithfulness 0.91), regenerate replacing the answer, the conversation read back, every call in the usage ledger with the provider's own token counts; a real timeout and a real rejected key arrive as `provider_error` with their kind and a message naming DeepSeek, never the generic one. Root cause found doing it: production chat and comparison searched with the hash stand-in embedder and a token-overlap reranker (`rag_embedder="fake"`, `rag_reranker="fake"` were the defaults), so a question about the workspace's one full-text paper retrieved unrelated abstracts and was refused as "not answerable". Now: the same real embedder as discovery (bge-small via fastembed, loaded once, cached), the lexical index if it can't load, no stand-in reranker (`none` keeps the retrieval order; a cross-encoder stays opt-in); tests pin the stand-ins in `conftest.py`. Full text is preferred: once a paper has full-text chunks its abstract chunk is left out of search (kept for answers that cite it); an abstract-only paper is searched by its abstract. A cited passage is the verbatim window of its chunk around the sentence that supports the claim (it used to be the chunk's first 700 characters, which often cut the very words cited), with "…" where cut and that sentence marked. "Faithfulness 0.83" reads "83% of its wording is in its sources". Chat already was a focused three-pane surface (conversations, answer, evidence) |
| 12 | done: one comparison table model on the server (`services/synthesis/comparison_table.py`, `GET .../compare/{id}/table`) that the page draws and the Word export writes, so they can't differ: same headings (full titles, authors · year · what each was read from), rows, cells (the quoted value and any "the same passage also says", or why the cell is empty), order. `GET .../compare/{id}/export.docx?papers=` writes a real Word table with the standard library (`docx_export.py`: OOXML parts, a repeating heading row, landscape from four papers, control characters dropped) for the columns on screen. Verified: pytest reads the package back with an independent reader and compares it cell for cell with the model; a Playwright check downloads the file from the page and compares it with the on-screen table (all columns, and after removing one); Microsoft Word opened the exported files (1 table, 5×4 and 5×5, heading row repeating, landscape) and exported them to PDF. The page: a compact header with "Papers and fields" and "Export to Word", a viewport-height table with a pinned heading row and field column, numbered columns with full titles, a searchable paper picker with full titles, authors, year and coverage, a legend of only the states the table has |
| 13 | done: each place the workspace cites a paper reads claim, then the verbatim passage with the supporting sentence marked and "…" where cut, then section and page, then where it is used (the same window as chat; the CSS clamp that could hide the cited sentence is gone); one `VerbatimQuote` renders passages in chat and citations; a paper with only a title says so instead of "has no title" |
| 14 | done: one background host with Auto / Animated / Static (kept per device, an explicit choice overrides Auto). Auto reads the graphics the browser really uses (WebGL renderer): a dedicated GPU runs the neural network, integrated graphics GhostFibers (React Bits, `ogl`, the user's configuration, drawn at 1× and 30 fps), software rendering a still background; the launcher's GPU detection is the start-up hint. Verified on the RTX 4060 Ti, on integrated graphics (pinned), and in software rendering |
| 15 | done: graph labels and edges re-weighted for legibility; the background becomes the graph in all three modes -- the network condenses onto the papers, GhostFibers surges then dims behind the graph, the still background fades -- and is given back on leaving; verified frame by frame in each mode, settled by about 4 s |
| 16 | done: a method gap's evidence now includes the using paper's own words about the method ("States it", shown first), not only the other papers' problem statements, which named no method at all -- the gap's papers stay the ones lacking the method, so its statement, confidence, id and decisions are unchanged (the full Playwright run caught a first version that counted the using paper too); live runs on real workspaces: 23 candidates checked by DeepSeek in 13.5 s with live progress, accepted and rejected decisions kept across re-runs, undecided ones replaced, never duplicated. Launcher: no NVIDIA tool, CUDA or driver is needed anywhere (Windows asks the OS for its adapters; `nvidia-smi` only on Linux and only if present); tests and real `start.py status` runs for Intel-only, AMD APU, no driver, a VM, no GPU reported and an unavailable query. Model usage verified against today's real calls (no cost shown, by design). Full regression: see the handoff |

## Follow-up: the user's own papers (reported 2026-10-02)
The user's report: an IEEE upload showed no abstract or authors although the PDF has both; every paper said "no abstract was found"; discovery showed no publisher; no selected paper had full text; a workspace of the user's 16 own papers couldn't get a research trail (it went straight to discovery); comparison had no content even after a full-text upload; and more public sources were wanted. The user chose: publishers as a ranking criterion plus a filter; full text from any public host an API names; their own contact email for the sources' polite pools (kept in the git-ignored `backend/.env`); re-read every upload at once.

| Area | Done, and measured on the user's data |
|---|---|
| Reading PDFs | Root causes: two-column pages were read across both columns, words were glued together (pdfplumber's default gap), sideways margin text (where IEEE prints the DOI) was dropped, and "Abstract—" / "Index Terms—" inline headings weren't recognised. Now: word gaps at 0.15 of the font size (measured on 129 PDFs: 301 glued words down to 1, none split), the column gutter found from line coverage and each band between full-width lines read left column then right, sideways text kept for the DOI, inline headings split. The abstract and DOI are stored on the paper. On the OnBoard PDF: six authors in the publisher's order, 2025, ISCI venue, IEEE, DOI, abstract |
| Completing the record | After an upload is read, the record is completed from Crossref, then OpenAlex, by DOI; by exact title (normalised, ≥ 0.93 similar) from Crossref, Semantic Scholar or arXiv when there is no DOI. Each field comes from the first source that has it; the PDF's own title and abstract are never replaced; a DOI another paper already holds is not taken (it is unique) |
| Re-reading uploads | `python -m app.maintenance.reread_uploads` (database backed up first), and per paper "Read the PDF again". All 127 stored uploads re-read, 0 failed, 122 now have an abstract. A profile built from an earlier read now shows the paper's stored abstract |
| Publishers | From the sources (Crossref `publisher`, OpenAlex host organisation), else the DOI prefix's registrant; names normalised (IEEE, Springer, ACM, Elsevier, ...). 1,083 stored papers named by `backfill_publishers`. Shown on results, paper pages, workspace rows, comparison headings and citations. A seventh ranking criterion, "Preferred publisher" (IEEE, Springer, ACM, Elsevier; default weight 15), and a publisher filter. A ranking stamped before it existed (6-part `c-` version, or `w0-initial`) is read with publisher 0, so it reproduces; criteria kept on a device from before get the new default |
| More sources | Discovery adds Crossref (every keyword query), DBLP (title and first keyword query) and CORE (the title query; small keyless quota). On OnBoard: all three answered, 181 results, the top 15 IEEE, Springer and Elsevier bus-tracking papers |
| Full text | Downloaded from any public HTTPS host a scholarly API names (bare names, private suffixes and non-public addresses refused, every redirect hop and its DNS answer checked), with Unpaywall and CORE added as sources. Paywalled papers get "Upload PDF" on their paper page and workspace row (`POST /papers/{id}/pdf`). The Bus Tracking workspace went from 1 to 8 full-text papers |
| Trail from own papers | "Connect this workspace's papers": the workspace's papers are ranked against the seed with discovery's own signals (no off-topic cut: the reader chose them), citation links taken from both papers' reference lists, and typed by the trail's rules. One run per workspace, rebuilt in place, decisions kept. Test-1: 12 of 15 papers connected; Bus Tracking: 17 of 17; about 3 s each. Rows say "ranked #N of this workspace's papers", not "in discovery" |
| Comparison | Retrieval is scoped to the papers being compared, with a query per field (problem, method, results, limitations) and up to 12 passages per paper; the papers are read concurrently (4 at once). Test-1: 13 of 16 cells quoted, where before they were "No text" or "Unverified" |

Open from this round:
- Paywalled publisher PDFs (most IEEE, ACM, Elsevier and Springer articles) can't be fetched; "Upload PDF" is the way in.
- Keyless quotas: OpenAlex's daily budget (shared per IP address), Semantic Scholar's rate limit and CORE's small allowance. Free keys raise each (see `backend/README.md`).
- The public-host check resolves a host's DNS before downloading, but the download resolves it again, so a host that changes its answer in between (DNS rebinding) isn't caught.
- A profile's other fields (problem, methods, ...) were extracted from the earlier read; only the abstract is replaced on read. "Analyze" again refreshes them.
- Some uploads' titles match no source record (theses, course reports, preprints without a DOI), so their records stay as the PDF gives them.

## Final round: one app, a real library, Settings in sections (reported 2026-10-06)
The user's report: the Papers and Workspaces pages were still in the old theme, Settings was one long scroll, and the app needed a last pass before a college presentation. The user chose: Settings sections for discovery defaults, sources & full text, and library & data; a server-side library with safer sign-in; pins, tags and notes moved onto the workspace overview.

| Area | Done |
|---|---|
| One dark world | `/papers` (library + upload), `/papers/[id]` (the seed page), `/workspaces`, `/workspace/[id]/activity` rebuilt in the cinematic world; the old shell (`(app)` group, AppShell and its light components) deleted; old URLs redirect. The root is dark before anything paints; selection, caret, placeholders, scrollbars and focus rings use the palette; the header marks the current section |
| Paper library | `GET /api/v1/papers`: every paper the reader uploaded (now credited to them), analysed, searched from or collected, with coverage, profile, workspaces and its next step; search, views, sort. The paper page names the reader's workspaces holding it and offers "Skip discovery, start a workspace with just this paper" again (the old page had it; the new one had lost it) |
| Workspaces | The list shows each seed, counts (one grouped query per table: 2 s → 0.4 s for 1,300 workspaces), rename in place and delete behind a confirmation that says what stays. Overview rows gain pin, tags and a note |
| Settings | A sidebar of sections, one pane at a time, addressed by the URL hash (old `#models`/`#usage` links work): Account, Library & workspaces, Discovery defaults (weights; preferred publishers chosen from the publishers the server knows, sent with every discovery and re-rank and recorded on the run), Sources & full text (each source's use and set-up, a live check, never a key), Language models, Model usage, Appearance, Service & about |
| Accounts | Sign-in matches an email whatever its case (exact spelling first, so no existing account becomes unreachable), says when it made a new account, and the sign-in page offers this browser's accounts and flags a new email before it makes one. Each session has its own data cache, so nothing fetched for one account can show for another (a sign-out and sign-in within 2 s used to reuse the old `/me`) |
| Reliability | SQLite runs in WAL mode (a request awaiting the network made others queue: an upload took 5.5 s, the library never loaded); backups use SQLite's own backup. PDF columns: the gutter is looked for in the middle band only and columns need not share baselines -- measured on 975 stored pages: 34 two-column pages now read in order (a references page, OnBoard's page 3), 30 tables and prose pages no longer cut in half |
| CI | Ruff import order and mypy under the newest SQLAlchemy 2.1/numpy fixed; GitHub Actions green |
| Background (2026-10-09) | Where the GPU is weak (the browser draws in software) Auto now runs GhostFibers at a lighter setting -- half resolution, 24 fps, three layers -- instead of a still frame; only a browser without WebGL gets the still background. Settings > Appearance offers Neural network, Fibers and Static explicitly. The launcher's start-up hint follows the same rule |

Open from this round:
- Uploads made before uploads were credited to an account appear in the library only when they are in a workspace, were analysed or searched from by the reader, or this browser remembers them.
- Preferred publishers and ranking weights are kept per browser, not per account.
- Stored papers are read with the improved column detection only once re-read ("Read the PDF again", or the maintenance script).

Found in Phases 9–16, open:
- Answers stream once they are verified: the first words of a chat answer arrive after the check, about 6–8 s into a turn on DeepSeek (the stages are shown live before that). Streaming unverified words first would show sentences that may then be withdrawn.
- Some source text carries U+FFFD where a PDF or a scholarly API lost a character ("Students’" read as "Students�", "[3�6]"); it is shown as stored, never repaired by guess.
- Two-column PDFs can interleave lines, so a "sentence" the passage window marks may run across both columns; the passage is still verbatim. (Much reduced on 2026-10-02 and 2026-10-07; a page whose columns can't be told apart is still read straight across.)
- No cross-encoder is installed (it needs the torch extra), so chat keeps the embedder's retrieval order; the MS MARCO cross-encoder was measured earlier and rejected for paper-to-paper ranking, not yet for chat.
- The gaps page asks for each member's profile; members not profiled yet answer 404, which the page reports as "N of M papers have a research profile" but the browser console also lists.

Found in Phase 8, open:
- OpenAlex now meters keyless use: a daily budget shared by everyone on this network's IP address (a search costs 10 credits) that resets at midnight UTC; once spent, every OpenAlex request is refused (429, Retry-After of minutes) until then. Measured 2026-10-01 after a few test runs. A free OpenAlex key restores it: `RESEARCHNEXUS_OPENALEX_API_KEY` in `backend/.env` -- getting one is the user's call.
- Semantic Scholar without a key rate-limits about half of a run's requests; `RESEARCHNEXUS_SEMANTIC_SCHOLAR_API_KEY` raises that limit.
- The search step is now bounded by arXiv's requested 3 s between requests (five phrase queries, about 12 s); fewer arXiv queries would be faster but find less.
- A model-written search plan still varies slightly between runs at temperature 0 (measured: three of 35 requests differed), so two runs of one seed can differ by a few candidates; the ranking of a given set of candidates is deterministic.

Found in Phase 7 (measured on the user's two real workspaces, 51 discovered papers), open:
- Only 1 was retrievable (arXiv). 20 more have open-access copies, but on small journal sites (ijraset, jicet, ijsrem, ...) that the fixed full-text host list doesn't include; 26 have no open-access copy at all. Reaching those 20 needs a policy decision: fetching from any public HTTPS host a scholarly API names (with private-address, redirect and size guards) instead of a fixed list -- a wider security boundary, so not done without the user's say-so. Decided 2026-10-02 (any public host); done in the follow-up above.
- MDPI and OUP refuse scripted PDF downloads (HTTP 403); they are reported as such, and the client is not disguised as a browser.
- The section splitter took a numbered reference-like list as headings in one retrieved arXiv paper; parsing quality is otherwise the upload path's.

Found in Phase 6, not fixed:
- Some source abstracts carry mid-line hyphenation the source itself flattened ("a no- table 16% enhancement"); without a line break it can't be told from a real hyphen, so it is left as written.
- The gap matrix still groups methods across papers by lowercase text only; grouping by `refine.item_keys` would re-key saved gap decisions (`match_key`), so it waits for a gaps pass that can migrate them.

Found in Phase 5, not fixed (outside its scope):
- Gemini's default model is still `gemini-1.5-flash`, which Google has retired; a Gemini key would fail on first use. This belongs with provider reliability, like Phase 2 did for DeepSeek, and needs a Gemini key to verify.
- Stage runs recorded before Phase 5 carry no tokens (the UI shows none rather than "0"); their usage is in the ledger totals.
- Key checks from Settings (two ~5-token calls) are not metered.

Found along the way, not yet scheduled: sign-in treats email case as a different account ("Varshan@gmail.com" and "varshan@gmail.com" are two users, each with its own workspaces and key) -- belongs with the time/data-contract work (Phase 4) or its own small fix, and needs a decision on merging the existing duplicate accounts.
