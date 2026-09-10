# ResearchNexus — Phase 7 Completion Report: Typed Research Trail

**Scope.** Stage S11 of the pipeline (Architecture §3): turn the ranked candidate
list for a seed into a set of **typed, evidence-bearing** relationship edges —
the auditable answer to *"why is this paper related?"*. Implements only the
typed research trail (Roadmap Phase 7, second contribution area). No workspace,
RAG, comparison, gaps, directions, UI, or orchestrator hardening.

**Companion docs.** `docs/architecture/ResearchNexus_Implementation_Architecture.md`
(§3 S11), `ResearchNexus_Data_Model.md` (§13 `paper_relationships`),
`ResearchNexus_Implementation_Roadmap.md` (Phase 7),
`ResearchNexus_Seed_Paper_Research_Trail.md`,
`docs/evaluation/ResearchNexus_Evaluation_Plan.md` (§Trail).

---

## Status

| Gate | Command | Result |
|---|---|---|
| Tests | `pytest -q` | **429 passed**, 2 warnings (pre-existing Starlette/anyio deprecations) |
| Lint | `ruff check .` | **All checks passed** |
| Types | `mypy app tests` | **Success: no issues in 172 source files** |
| Migrations | `test_migrations.py` + manual `0001->0006` up / `base` down / `0006<->0005` step | **round-trips clean**; `ix_paper_relationships_run` + unique constraint present |

64 new tests were added (all green); the rest of the suite is unchanged.

---

## What was built

All new code is deterministic-first: the rule layer alone produces a valid trail;
the LLM only *confirms* (it never invents a type or a span), and every optional
step degrades to "no edge" rather than a guess.

| Module | Responsibility |
|---|---|
| `app/domain/trail.py` | `RelationshipType` (7 values), `DetectionMethod`, `UserState`, `Evidence` (span + role), `TrailEdge` (validator: >= 1 evidence item required). |
| `app/services/trail/verify_span.py` | `verify_quote_in_text` / `find_span` — exact then whitespace/case-normalised then `difflib` partial-ratio >= 0.9. Stdlib only, no new dependency. |
| `app/services/trail/rules.py` | `TrailThresholds` (fixed "w0" values), `TrailContext`, `CandidateView`, `RuleResult`; 7 rule functions + `apply_rules` (multi-type; `SIMILAR` suppressed when a specific type also fires). |
| `app/services/trail/confirm_llm.py` | `confirm_rule_results` — one batched chat call; drops any type not proposed by the rules; re-verifies the returned `target_span` in the candidate abstract; returns `{}` on no session / provider error / bad JSON. |
| `app/services/trail/contradiction.py` | `verify_contradiction` — NLI pass for `POTENTIALLY_CONTRADICTORY`; requires a quotable span verified in **both** the seed claim and the candidate abstract, else `None`. |
| `app/services/trail/confidence.py` | `assign_confidence` — fixed deterministic band (LOW/MEDIUM/HIGH) from rule strength, ranking-signal agreement, evidence completeness, LLM certainty. **Not** a calibrated model (calibration is Phase 16). Returns the band **and** its `confidence_basis`. |
| `app/services/trail/pipeline.py` | `build_trail` — the S11 orchestration: rules -> LLM confirm -> contradiction NLI -> confidence -> persist. Run-scoped for the pre-workspace MVP. |

Prompts are inlined as module constants in `confirm_llm.py` / `contradiction.py`,
consistent with Phases 5–6 (`search_concepts`, `ranking/explain`); the Roadmap's
`.jinja` path was never the established pattern (no jinja templates exist in the
repo).

### Data model

`app/db/models.py::PaperRelationshipORM` + migration
`migrations/versions/0006_paper_relationships.py` (revision `0006`, down-revision
`0005`).

- Scoped to `run_id` (`FK -> search_runs.id`, `ON DELETE CASCADE`) for the
  pre-workspace MVP; `workspace_id` / `owner_id` are nullable and unpopulated —
  they get FKs and population in Phase 8.
- `UniqueConstraint(run_id, source_paper_id, target_paper_id, relationship_type)`
  — one edge per (seed, target, type) per run.
- Columns mirror `TrailEdge`: `detection_method`, `rule_fired`, `llm_confirmed`,
  `evidence` (JSON), `supporting_references` (JSON), `confidence`,
  `confidence_basis` (JSON), `user_state`, `created_at`.
- Numbered `0006` (sequential) rather than the Roadmap's `0007_*` label — Phase 5
  added no migration, so the Roadmap numbering is off by one.

### Persistence (`app/db/repository.py`)

- `save_trail_edges(db, run_id, edges)` — upsert by `edge_id`; deletes non-rejected
  rows no longer produced; **preserves `user_state="rejected"` rows** and their
  `created_at`.
- `get_trail_edges(db, run_id)` — ordered by `(target_paper_id, relationship_type)`.
- `get_rejected_trail_keys(db, run_id)` — `{(target_paper_id, relationship_type)}`
  the pipeline must not re-propose.
- `set_trail_edge_user_state(db, edge_id, state)` — accept / reject / pending.

### Config (`app/config.py`)

`trail_top_k = 40`, `trail_max_seed_claims = 3`. Rule thresholds are **not**
surfaced as settings — they live in `TrailThresholds` as fixed values pending
Phase 16 calibration (ablation A9).

---

## Determinism & evidence guarantees

- **No evidence -> no edge.** `TrailEdge` rejects an empty evidence list at
  construction; every rule attaches at least one `SourceSpan` (a citation fact, a
  verbatim dataset mention, or a verified quote).
- **The LLM cannot invent.** `confirm_rule_results` only ever *narrows* the
  rule-proposed set and re-verifies every span it returns against the candidate
  abstract; an unparseable or absent response yields `{}` and the rule-only edges
  still persist (at a capped band).
- **`POTENTIALLY_CONTRADICTORY` is high-precision.** Never emitted without an LLM
  session *and* a span verified in **both** papers; capped at `MEDIUM` even when
  fully confirmed.
- **"Prefer UNKNOWN."** A candidate for which no rule fires gets no edge (the enum
  has no `UNKNOWN` member — absence is the signal).
- **Reproducible.** `edge_id = edge_<sha256(run_id|target_paper_id|type)[:20]>`, so
  a re-run upserts the same rows; a user-`rejected` edge survives re-runs and its
  `(target, type)` key is never re-proposed. Tests assert byte-identical output
  across repeated runs (`model_dump(exclude={"created_at"})`).

---

## Tests (64 new)

| File | N | Covers |
|---|---|---|
| `test_trail_domain.py` | 6 | enum values; `Evidence`/`TrailEdge` shape; empty-evidence rejection. |
| `test_trail_verify_span.py` | 6 | exact / normalised / fuzzy match; offset recovery; non-match -> `None`. |
| `test_trail_rules.py` | 22 | **every rule fires on a crafted fixture and not on a near-miss**; missing year/abstract; multi-type; `SIMILAR` suppression; signal-agreement count. |
| `test_trail_confidence.py` | 6 | band vs `confidence_basis` consistency; no-session cap at MEDIUM; LLM-disagreed -> LOW; contradiction cap at MEDIUM. |
| `test_trail_confirm_llm.py` | 6 | confirm / reject; unproposed type dropped; span re-verification; no session / provider error / malformed JSON -> `{}`. |
| `test_trail_contradiction.py` | 5 | span required in both papers; one-sided or unparseable -> `None`; negative (non-contradictory) case. |
| `test_db_repository_trail.py` | 6 | round-trip; re-save drops stale edges; rejected edge preserved + key reported; accept; `run` delete cascades; unique constraint. |
| `test_trail_pipeline.py` | 7 | end-to-end rule-only vs confirming session; contradiction edge; rejected-key suppression on re-run; deterministic repeat; provenance persisted. |

Maps to the Roadmap Phase 7 test list: each rule fires / near-miss (yes);
contradiction needs a span from both papers (yes); multi-type allowed (yes);
rejected edge suppresses re-run (yes); band matches `confidence_basis` (yes).

---

## Acceptance criteria

| Criterion (Roadmap Phase 7) | State |
|---|---|
| 7 relationship types via deterministic rules -> LLM confirm with spans -> contradiction pass -> confidence band | **Met** — implemented and unit-verified end to end. |
| User accept / reject; rejected edge suppresses the same rule on re-run | **Met** — `set_trail_edge_user_state` + `get_rejected_trail_keys` + pipeline skip; preserved across re-runs. |
| Every edge carries evidence; LLM never invents a type or a span | **Met** — enforced at construction and in `confirm_llm` / `contradiction`. |
| Per-type F1 on a >= 150-edge human-labelled set (`FOUNDATIONAL`/`RECENT`/`DATASET_RELATED` >= 0.75, `SIMILAR`/`METHOD_EXTENSION`/`COMPETING` >= 0.6, `POTENTIALLY_CONTRADICTORY` precision >= 0.8) | **Deferred to Phase 16** — needs the labelled trail set + `run_eval.py` (Evaluation Plan §Trail). No labelled data exists yet. |
| Confidence calibration monotone vs human agreement | **Deferred to Phase 16** — the band is a fixed rule here by design; calibration (ECE / reliability) is out of scope for Phase 7 per the brief. |

---

## Deferred / explicitly out of scope

- **HTTP surface.** `GET /papers/{id}/related` `trail_edges` payload and
  `POST .../trail/{edge_id}` (accept/reject) / `POST .../trail/retype` routes are
  not wired — same treatment as the deferred Phase 5/6 endpoints; the service and
  repository layers are complete and callable.
- **Rule-threshold tuning** -> Phase 16 ablation A9 (`TrailThresholds` holds the
  "w0" guesses).
- **Confidence calibration** -> Phase 16.
- **Benchmark F1 numbers** -> Phase 16 (`run_eval.py` + labelled trail set).
- **Workspace scoping** (`workspace_id` / `owner_id` FKs + population) -> Phase 8.

---

## Traceability

Preserves the *IEEE BigData 2024 limitation -> ResearchNexus solution -> evidence*
chain: prior related-work tooling returns an untyped, unexplained list; Phase 7
attaches a **type**, a **rule that fired**, the **spans** that justify it, and a
**confidence basis** to every edge — so a reviewer can audit each relationship
back to quotable text in the two papers.

---

## Files changed

**New**

- `app/domain/trail.py`
- `app/services/trail/{__init__,rules,confirm_llm,contradiction,confidence,pipeline}.py`
- `app/services/trail/verify_span.py`
- `migrations/versions/0006_paper_relationships.py`
- `tests/unit/test_trail_{domain,verify_span,rules,confidence,confirm_llm,contradiction,pipeline}.py`
- `tests/unit/test_db_repository_trail.py`

**Modified**

- `app/db/models.py` — `PaperRelationshipORM`; removed a stray duplicate
  `explanation` column on `RankedPaperORM` (a Phase 6 leftover that `mypy`
  flagged `no-redef`).
- `app/db/repository.py` — the five `*trail*` functions above.
- `app/config.py` — `trail_top_k`, `trail_max_seed_claims`.
- `tests/unit/test_migrations.py` — assert `paper_relationships` on upgrade / gone on downgrade.
- `pyproject.toml` — description bumped to "Phases 1-7".
