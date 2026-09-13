# ResearchNexus — Phase 14 Completion Report: Orchestrator Hardening

**Scope.** `ResearchOrchestrator` (Architecture §4): a fixed workflow DAG
integrating the already-built Phase 1-13 stages, with the five bounded
decisions the architecture allows, stage-boundary telemetry (`stage_runs`
/ `ToolLog`), a real budget guard, bounded retries, and a workspace
activity feed. No agent swarm, no runtime tool/node creation, no new
stage logic reimplemented.

**Companion docs.** `ResearchNexus_Implementation_Architecture.md` (§4
"Agentic orchestrator — component table", top-level layer diagram §1.1,
actor table), `ResearchNexus_Data_Model.md` (§12 `Job`, §13 `stage_runs`),
`ResearchNexus_Implementation_Roadmap.md` (Phase 14),
`ResearchNexus_API_Specification.md` (§6 budget/degradation contract),
`ResearchNexus_Evaluation_Plan.md` (A10, A-agentic ablations).

---

## Status

| Gate | Command | Result |
|---|---|---|
| Tests | `pytest -q` | **767 passed**, 2 warnings (pre-existing Starlette/anyio deprecations) |
| Lint | `ruff check .` | **All checks passed** |
| Types | `mypy app tests` | **Success: no issues in 276 source files** |
| Migrations | `test_migrations.py` + manual `0001->0013` up / `0013->0012` / `base` down round-trip | **clean**; ORM `create_all` and Alembic head schemas match for `stage_runs` (15 cols, index names aligned) |

78 new tests were added (all green); the rest of the suite (689 tests)
runs unchanged — **zero regressions**, including the pre-existing
gaps/directions endpoints now routed through the orchestrator.
**No new dependencies.**

---

## What "integrate the existing stages" meant here

Two stages the codebase already fully implements had **no HTTP endpoint
at all** before this phase: discovery (`services/discovery/pipeline.py`)
and ranking (`services/ranking/pipeline.py`) were built and unit-tested in
Phases 5-6 but never wired to a router — their own module docstrings say
so explicitly ("the async `POST /papers/{id}/discover-related` job... is
deferred", "the one extra citation hop discretionary decision... belongs
to the final orchestrator"). `ResearchOrchestrator.run_full_pipeline` is
the first place that actually calls them, chained with ingest, profile,
trail, and workspace creation — the pre-workspace half of "seed ingestion
→ profile → search plan → discovery → ranking → trail → workspace" the
brief asked for. It calls the real Phase 1-13 functions directly; nothing
about how any of those stages work was changed or reimplemented.

The post-workspace half (RAG, comparison, gaps, directions, citations)
already has endpoints (Phases 9-12). Those are individually
user-triggered and not sequential, so `run_full_pipeline` does not chain
them — instead, `ResearchOrchestrator` exposes one wrapped method per
stage (`run_rag_stage`, `run_gaps_stage`, `run_directions_stage`,
`run_comparison_stage`, `run_citations_stage`), each still just calling
the existing pipeline function. Per the Roadmap's own "APIs delivered"
line ("orchestrated variants of discover/gaps/directions already
exposed"), the **existing** gaps job (`app/jobs/runner.py::run_gaps_job`)
and directions endpoint (`routers/synthesis.py`) now call through
`run_gaps_stage` / `run_directions_stage` — identical inputs, identical
results, identical error handling, with a `stage_runs` row as the only
observable addition (all pre-existing Phase 11/12 tests pass unchanged).
RAG and comparison get the same wrapper methods, fully tested, but their
routers are untouched this phase — not in that Roadmap line, and
widening the diff into two more endpoints wasn't needed to satisfy the
brief.

**"Search plan" is not a separate stage_runs row.** `services/discovery/
pipeline.py::run_discovery` is documented as the combined "Stage S5+S6
orchestration entry point" and already calls `generate_search_plan`
internally. Giving search-plan its own `stage_runs` entry would mean
either calling it a second time (silently doubling its LLM cost) or
reaching into Phase 5's function to split it apart (a change to P1-P13
logic the brief said not to make). `StageName` therefore has 11 values,
not 12; discovery's `stage_runs` row covers both.

**Presentation/outline does not exist.** The user's stage list said
"citations/outline where applicable" — no `services/presentation` or
outline-generation module exists anywhere in Phases 1-13 to integrate;
building one would be new stage logic, out of scope for a hardening
phase. Citations does exist and is integrated (`services/citations/
pipeline.py::build_citations`, a new thin extraction of the router's
existing per-paper loop so the orchestrator has one callable to wrap —
the router's own inline loop is untouched).

---

## The five bounded decisions

| Decision | Status before this phase | This phase |
|---|---|---|
| **Strategy selection** | Config-driven (`DiscoveryOptions.strategies`), already bounded | Unchanged; the orchestrator passes it through and can shrink it under budget (`budget.degrade_discovery_options`) |
| **One extra citation hop** | Column (`extra_citation_hop_used`) reserved since Phase 4/5; decision logic explicitly deferred ("belongs to the final orchestrator") | **New.** `should_authorise_extra_citation_hop` (thin candidates or low strategy diversity) triggers exactly one re-run of discovery with an expanded, citation-inclusive strategy set; the richer result is adopted only if it is not worse, and `extra_citation_hop_used` is set on the run |
| **Regenerate once on failed faithfulness** | Fully implemented (`services/rag/pipeline.py`, Phase 9) | Unchanged — integrated as-is via `run_rag_stage` |
| **Answer vs "I don't know"** | Fully implemented (`services/rag/answerability.py`, Phase 9) | Unchanged — integrated as-is via `run_rag_stage` |
| **Graceful degradation under budget** | Fields existed (`token_budget_usd`, `cost_used_usd`) but **`cost_usd` was never once written** by any Phase 1-13 code | **New.** `BudgetGuard` (`services/orchestrator/budget.py`) is deterministic: ALLOW / DEGRADE (past a configurable fraction of budget — fewer discovery strategies, half the RAG retrieval `k`, floored) / BLOCK (at the cap — the stage is never even attempted, no tokens spent). `run_stage` now records real spend via `repo.add_workspace_spend` whenever a stage's result exposes `prompt_tokens`/`completion_tokens` (RAG, comparison, directions) |

`BudgetGuard`'s cost figure is a deliberately simple, configured blended
rate (`Settings.orchestrator_cost_per_1k_tokens_usd`, default $0.002/1k
tokens) — BYOK means ResearchNexus has no way to know a user's actual
provider pricing; this is only ever compared against the workspace's own
declared `token_budget_usd`, never presented as a real invoice.

---

## Pipeline

```
run_full_pipeline (fixed DAG, no runtime branching):
  ingest (sync)  ->  profile (async, mandatory LLM)  ->  discovery (async;
    S5+S6; + one bounded extra citation hop)  ->  ranking (async)  ->
    trail (async)  ->  workspace (sync)

each step -> ResearchOrchestrator.run_stage(...):
  time it (StageTimer)  ->  run with a bounded timeout  ->  on failure,
  retry up to Settings.orchestrator_max_stage_attempts (hard cap,
  independent of what a caller requests)  ->  write exactly one
  stage_runs row per attempt (ok / error, latency, token/cost, sha256
  input/output hashes -- never a prompt or response body)  ->  propagate
  the stage's own exception unchanged once attempts are exhausted
```

| Module | Responsibility |
|---|---|
| `app/domain/orchestrator.py` | `StageName` (11 values), `BudgetDecision`, `StageRun` — the exact Data Model §13 `stage_runs` shape. |
| `app/telemetry/stage_timer.py` | `StageTimer` — wall-clock latency, set even when the block raises. |
| `app/services/orchestrator/tools.py` | `FIXED_STAGE_ORDER` (a tuple — structurally not mutable at runtime), `STAGE_PREREQUISITE`, `TOOL_REGISTRY` (typed name/description/input-type/output-type metadata per stage). |
| `app/services/orchestrator/budget.py` | `decide_budget`, `estimate_cost_usd`, `degrade_discovery_options`, `degrade_top_k`, `should_authorise_extra_citation_hop` — pure, deterministic, no I/O. |
| `app/services/orchestrator/orchestrator.py` | `ResearchOrchestrator.run_stage` (the universal wrapper), `run_full_pipeline` (the fixed pre-workspace DAG), `run_{rag,gaps,directions,comparison,citations}_stage` (post-workspace wrappers). |
| `app/services/citations/pipeline.py` | `build_citations` — new, mirrors the router's existing logic so the orchestrator has one callable to wrap. |

### Why sync stages don't get a preemptible timeout

`run_ingestion` and `create_workspace` are synchronous and share this
orchestrator's one `Session`. Running them via `asyncio.to_thread` was
tried and reverted: a second thread touching the same SQLite connection
corrupted query parameter binding under load (caught by the end-to-end
test before it ever reached production code). A sync stage's timeout is
therefore measured and logged but not preemptive — the honest trade-off
documented in `orchestrator.py`'s module docstring, not a silent gap.

### Job/status tracking

`run_full_pipeline` accepts an optional `job_id` and drives the existing
`Job`/`JobORM` (Phase 1-2) through `QUEUED -> RUNNING -> SUCCEEDED |
FAILED`, with `progress={"stage": <name>}` updated at each step and
`result_ref` set to the final workspace id — reusing `GET /jobs/{id}`
(Phase 2) rather than adding a second tracking mechanism. A new
`JobKind.PIPELINE` value is added (`JobKind.PROFILE` / `DISCOVER` /
`RANK` / `TRAIL` have sat unused in the enum since Phase 2's own
docstring said so). No new endpoint creates such a job this phase — see
Deferred.

---

## Guarantees (verified by tests)

- **The plan is a fixed DAG** — `FIXED_STAGE_ORDER` is a module-level
  tuple; nothing in `ResearchOrchestrator` appends to it or builds a node
  at runtime.
- **No unbounded loops** — `run_stage` clamps `max_attempts` to
  `Settings.orchestrator_max_stage_attempts` regardless of what a caller
  passes; the extra citation hop fires at most once per pipeline run.
- **Never blocks the path** — a `stage_runs` write happens on every
  attempt, success or failure, and a logging call never replaces the
  stage's own exception.
- **Budget is real, not decorative** — `cost_usd`/`tokens_prompt`/
  `tokens_completion` on `workspaces` are actually incremented now
  (`repo.add_workspace_spend`), and `BudgetBlocked` genuinely prevents
  the wrapped call (`answer_fn`) from ever running once a workspace is at
  its cap — verified by asserting the fake call counter stays at zero.
  `KeyboardInterrupt`/`SystemExit` are never caught by `run_stage` (only
  `Exception`, not `BaseException`).
- **No invented graph edges elsewhere disturbed** — the gaps/directions
  rewire is call-site only; `build_gaps`/`build_directions` themselves
  are untouched, and every pre-existing Phase 11/12 test passes unchanged.
- **stage_runs never carries a prompt or response body** — the domain
  model has no field wide enough to hold one; verified by asserting the
  exact field set on both the model and the API response.
- **Tenant isolation** — `GET .../activity` resolves the workspace
  through the Phase 8 owner gate (404, never 403); `run_stage` itself
  never swallows a `WorkspaceNotFound` raised inside a wrapped call.

---

## Tests (78 new)

| File | N | Covers |
|---|---|---|
| `test_orchestrator_domain.py` | 7 | `StageName` (11 values), `BudgetDecision` (3), invalid stage rejected, no prompt/response field exists, JSON round-trip. |
| `test_stage_timer.py` | 4 | `None` before exit; non-negative int after; reflects real elapsed time; set even when the block raises. |
| `test_db_repository_stage_runs.py` | 8 | round-trip; newest-first; stage filter; limit; workspace scoping; pre-workspace rows have `workspace_id=None`; failure recorded; cascade-deletes with the workspace. |
| `test_db_repository_workspace_spend.py` | 2 | accumulates across calls; owner-gated. |
| `test_orchestrator_budget.py` | 12 | cost estimate; ALLOW/DEGRADE/BLOCK at and around the threshold and cap; discovery degradation keeps only cheap strategies (never empty); top-k halves with a floor; extra-hop boundary (thin candidates, low diversity, healthy, exactly-at-minimum). |
| `test_orchestrator_tools.py` | 7 | fixed order matches the documented chain; it's a tuple; every stage appears exactly once; registry covers every stage with typed metadata; every stage but ingest has a prerequisite; prerequisites only point earlier in the order. |
| `test_orchestrator_run_stage.py` | 8 | sync and async success; failure logs + re-raises; retry succeeds on attempt 2 (both attempts logged); max-attempts capped regardless of request; timeout fails and is logged; workspace/job ids recorded; deterministic hashing. |
| `test_orchestrator_pipeline.py` | 12 | **complete end-to-end orchestration** (real ingest of a fixture PDF, mocked-LLM profile extraction, mocked-HTTP discovery, through to a created workspace); every pre-workspace stage writes a row; **exactly one** extra citation hop when thin, none when healthy; invalid stage input (no full text / missing paper); **stage failure/recovery** (no LLM key stops at PROFILE, nothing further runs); job progress tracked to SUCCEEDED/FAILED; `run_stage` does not swallow `WorkspaceNotFound`; **deterministic reruns** (re-ingesting identical bytes reuses the same paper id). |
| `test_orchestrator_post_workspace_stages.py` | 6 | RAG stage allows + records spend; degrades `k` past the threshold; blocks and never calls `answer_question` at the cap; gaps/directions/citations wrappers log a `stage_runs` row; directions records spend. |
| `test_citations_pipeline.py` | 5 | one citation per workspace paper by default; scoped subset; a foreign paper id ignored; unrecognised formats fall back to all three; persisted. |
| `test_workspace_activity_api.py` | 7 | empty for a fresh workspace; a real directions run produces a visible row; stage filter; unknown stage is `422`; tenant isolation; missing workspace `404`; response never carries anything beyond the documented field set. |

Maps directly to the brief's test list: complete end-to-end
orchestration, stage failure/recovery, timeout and budget degradation,
retry/idempotency, bounded decision rules, invalid stage inputs, partial
upstream failure, tenant isolation, deterministic reruns.

---

## Acceptance criteria

| Criterion (this phase's brief) | State |
|---|---|
| Fixed `ResearchOrchestrator` workflow DAG | **Met** — `FIXED_STAGE_ORDER`, a tuple constant; `run_full_pipeline` walks it. |
| Integrate the existing stages (seed ingestion → … → citations, where applicable) | **Met** — see "What 'integrate the existing stages' meant here"; outline excluded (does not exist). |
| Only the 5 bounded decisions, no others | **Met** — table above; no new discretion introduced anywhere else. |
| Stage boundaries and typed inputs/outputs | **Met** — `TOOL_REGISTRY` (name/description/input-type/output-type per stage); every stage call already passes/returns the existing typed Pydantic/dataclass domain objects. |
| Failure isolation and recovery | **Met** — a failed required stage stops the pipeline and reports `failed_stage`/`error`; discovery's own per-strategy isolation (Phase 5) is untouched and still applies underneath. |
| Per-stage timeout/budget handling | **Met** — real (async) or measured (sync) timeout; `BudgetGuard` ALLOW/DEGRADE/BLOCK. |
| Idempotent/retry-safe execution | **Met** — bounded retry in `run_stage`; underlying stages' own idempotency (content-hash ingest, deterministic IDs) is preserved and exercised. |
| Job/status tracking | **Met** — `Job`/`JobORM` driven through `run_full_pipeline`; `JobKind.PIPELINE` added. |
| Stage transition logging/telemetry hooks | **Met** — `stage_runs` + `GET /workspaces/{id}/activity`. |
| Deterministic execution where applicable | **Met** — hashing, retries, and the extra-hop decision are all pure functions of their inputs; verified reruns. |
| No agent swarm / dynamic agents | **Met** — one hand-written class, a fixed tuple of stages, no tool-creation or planning loop of any kind. |

---

## Deferred / explicitly out of scope

- **A new "trigger the full pipeline" HTTP endpoint.** The Roadmap's own
  "APIs delivered" line for this phase lists only `GET .../activity` plus
  the already-exposed gaps/directions/discover variants — no new
  pipeline-trigger route. `run_full_pipeline` (with `job_id` for tracking)
  is a complete, tested service-layer capability; wiring a `POST` to it is
  a small, natural addition once Phase 15 (frontend integration) actually
  needs a UI action to call it from.
- **RAG and comparison routers left un-rewired.** `run_rag_stage` /
  `run_comparison_stage` exist and are tested; `routers/synthesis.py`'s
  chat and compare endpoints still call the underlying functions directly.
  Not in the Roadmap's explicit "already exposed" list for this phase.
- **GraphRAG / `mode:"themes"` routing** — explicitly out of scope
  (Phase 13's own deferral; not part of "bounded decisions" here either).
- **Method/Dataset/Topic/... node projection onto the research graph** —
  unrelated to orchestration; still Phase 13's own deferral.
- **A-agentic / A10 ablation switchboard** — the five decisions are each
  independently swappable in principle (bounded, isolated functions), but
  building the actual eval-harness toggle is Phase 16 work, matching
  every prior phase's own "expert-rated eval deliverables → Phase 16"
  pattern.
- **New UI, deployment** — never in scope for this phase.

---

## Traceability

Continues the *IEEE BigData 2024 limitation → ResearchNexus solution →
evidence* chain at the orchestration layer itself: the tracked paper's
pipeline has no auditable record of what ran, in what order, at what
cost, or why a step was skipped. `stage_runs` is that record for every
future run — latency, token/cost, and a content hash of what went in and
what came out, for every stage, whether it succeeded or failed — without
ever capturing a prompt or a response body. The bounded decisions
(one extra citation hop, regenerate-once, answer-vs-IDK, budget
degradation) are each a narrow, logged, single-shot escape hatch, never a
general planning loop — the same anti-hallucination, anti-overreach
discipline every earlier phase applied to its own artefact now applies to
the thing that calls them all.

---

## Files changed

**New**

- `app/domain/orchestrator.py`
- `app/telemetry/{__init__,stage_timer}.py`
- `app/services/orchestrator/{__init__,orchestrator,tools,budget}.py`
- `app/services/citations/pipeline.py`
- `migrations/versions/0013_stage_runs.py`
- `tests/unit/test_orchestrator_{domain,tools,budget,run_stage,pipeline,post_workspace_stages}.py`
- `tests/unit/test_stage_timer.py`
- `tests/unit/test_db_repository_stage_runs.py`
- `tests/unit/test_db_repository_workspace_spend.py`
- `tests/unit/test_citations_pipeline.py`
- `tests/integration/test_workspace_activity_api.py`

**Modified**

- `app/config.py` — `orchestrator_*` settings (cost rate, degrade threshold, stage timeout, max attempts, extra-hop thresholds).
- `app/db/models.py` — `StageRunORM`.
- `app/db/repository.py` — `add_workspace_spend`, `mark_extra_citation_hop`, `record_stage_run`, `list_stage_runs`.
- `app/domain/jobs.py` — `JobKind.PIPELINE`.
- `app/jobs/runner.py` — `run_gaps_job` now calls `run_gaps_stage`.
- `app/routers/synthesis.py` — directions endpoint now calls `run_directions_stage`.
- `app/routers/workspaces.py` — `GET /{workspace_id}/activity`.
- `app/services/workspace/pipeline.py` — `get_activity`.
- `tests/unit/test_migrations.py` — assert `stage_runs` on upgrade / gone on downgrade.
- `pyproject.toml` — description bumped to "Phases 1-14".

**Not committed** — per this phase's instruction, all changes above are
in the working tree only.
