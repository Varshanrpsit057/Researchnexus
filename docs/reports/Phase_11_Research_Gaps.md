# ResearchNexus — Phase 11 Completion Report: Research Gap Objects

**Scope.** The third contribution area (Architecture §9): the structured,
evidence-grounded, confidence-labelled `ResearchGap`. This phase directly
addresses the tracked **IEEE BigData 2024 limitation** — the source paper
generates meta-analysis prose with *no explicit, auditable, evidence-backed
research-gap identification step*. Implements only gap identification; no
research directions, research graph, UI, or orchestrator hardening.

**Companion docs.** `ResearchNexus_Implementation_Architecture.md` (§1.1 gap
rows, §4 `GapAnalyzer`, §9 limitation traceability),
`ResearchNexus_Data_Model.md` (§8 `ResearchGap`, §13),
`ResearchNexus_API_Specification.md` (§6 gaps),
`ResearchNexus_Implementation_Roadmap.md` (Phase 11),
`ResearchNexus_Evaluation_Plan.md` (§7 Gap detection).

---

## Status

| Gate | Command | Result |
|---|---|---|
| Tests | `pytest -q` | **610 passed**, 2 warnings (pre-existing Starlette/anyio deprecations) |
| Lint | `ruff check .` | **All checks passed** |
| Types | `mypy app tests` | **Success: no issues in 236 source files** |
| Migrations | `test_migrations.py` + manual `0001->0010` up / `base` down / `0010` step | **round-trips clean**; ORM `create_all` and Alembic head schemas match for `research_gaps` (21 cols) |

56 new tests were added (all green); the rest of the suite is unchanged.
**No new dependencies.**

---

## Pipeline (Data Model §8, enforced in code order)

```
build matrix (deterministic, from profiles)
  ->  deterministic rule candidates  (+ trail POTENTIALLY_CONTRADICTORY edges)
  ->  evidence assembly: >= 2 real papers with spans, or DROP
  ->  constrained LLM articulation:  introduces an unsupported term  -> DROP
  ->  Self-RAG self-support check:   statement not entailed by evidence -> DROP
  ->  deterministic confidence band (enum, from confidence_basis only)
  ->  persist as user_state="candidate"
```

The LLM never sees a paper before a rule has fired; no `ResearchGap` is
ever constructed from fewer than two evidence spans (enforced by a
`field_validator` on the domain model).

| Module | Responsibility |
|---|---|
| `app/domain/gap.py` | `GapType` (the 9 Data Model values), `GapEvidence`, `ResearchGap` (`>= 2` supporting-papers and `>= 1` evidence-span validators; `confidence` is a `Confidence` **enum**, never a number). |
| `services/gaps/matrix.py` | Deterministic cross-paper matrix: rows = papers, columns = `problem / method / dataset / metric / limitation / future_work / subdomain`, each cell pulled verbatim from the `ResearchProfile` with its `SourceSpan`. |
| `services/gaps/candidates.py` | 6 matrix rules + `contradiction_candidates` (from Phase 7 trail edges). Each `GapCandidate` carries deterministic `facts` and real `GapEvidence`. |
| `services/gaps/evidence.py` | `assemble`: `>= min_papers` distinct papers with spans or `None`; `CONTRADICTION` needs conflicting spans from `>= 2`; computes `evidence_coverage` (fraction of supporting papers whose span is full-text-grounded). |
| `services/gaps/articulate_llm.py` | Constrained LLM phrasing of `statement` / `why_unaddressed` / `proposed_direction` from `facts` + quotes. `is_grounded` deterministically rejects any long technical term (>= 8 chars, not generic vocabulary) absent from the facts/evidence -> the candidate is dropped. No session -> a deterministic template (`generator_model=None`). |
| `services/gaps/confidence.py` | `self_support_check` reuses the Phase 9 `IsSupported?` verifier over (statement, evidence quotes); no session / failure -> `False`. `assign_confidence` returns a band **enum** + the `confidence_basis` dict (`n_supporting`, `limitation_agreement`, `recency`, `self_support`, `evidence_coverage`, `detection_rule`). |
| `services/gaps/pipeline.py` | Orchestrates the fixed order; deterministic `gap_id = gap_<sha256(workspace|type|rule|papers|key)[:20]>` so a rerun upserts; a `rejected` gap is preserved and never re-proposed. |

### Rules implemented

| `detection_rule` | `GapType` | Fires when |
|---|---|---|
| `method_coverage` | METHOD_GAP | a method used by some papers is absent from >= 2 others that share a research context |
| `dataset_divergence` | DATASET_GAP | >= 2 papers use datasets but none is shared by two of them |
| `metric_divergence` | EVALUATION_GAP | >= 2 papers report metrics but none is shared |
| `shared_limitation` | GENERALIZATION_GAP | >= 2 papers state the same limitation and none resolves it |
| `method_dataset_combination` | UNEXPLORED_COMBINATION | a method (>= 2 papers) and a dataset (>= 2 papers) are never combined |
| `temporal_staleness` | TEMPORAL_GAP | a topic in >= 2 papers has no paper within `gap_temporal_years` of the workspace's newest |
| `trail_contradiction` | CONTRADICTION | a Phase 7 `POTENTIALLY_CONTRADICTORY` edge with conflicting spans from both papers |

`DOMAIN_GAP` and `PERFORMANCE_GAP` are valid enum values whose deterministic
rule is **deferred** (they need a domain taxonomy / numeric-metric
parsing) — no candidate of those types is produced.

### Persistence & API

`research_gaps` table (migration `0010`, `ix_research_gaps_workspace`,
cascade-delete with the workspace). Repository: `save_gaps` (upsert;
`accepted` / `rejected` rows untouched), `get_gaps(state=?)`, `get_gap`,
`get_rejected_gap_ids`, `set_gap_user_state` (tenant-scoped).

| Endpoint | Notes |
|---|---|
| `POST /workspaces/{id}/gaps` | **`202` + `Job(kind="gaps")`** run via `BackgroundTasks` (`run_gaps_job`). `409 llm_key_required`; `404` cross-tenant; `422` for an unknown `gap_types` value. |
| `GET /workspaces/{id}/gaps?state=candidate\|accepted\|rejected` | `{gaps: [ResearchGap]}`. |
| `POST /workspaces/{id}/gaps/{gap_id}` | `{user_state: "accepted"\|"rejected"}` -> `200` updated gap; `404` if the gap is not in this workspace. |

---

## Guarantees (verified by tests)

- **The LLM cannot invent a gap** — every gap starts from a deterministic
  rule over the matrix; the LLM only phrases three strings and any term it
  adds that is not in the facts/evidence is caught by `is_grounded` (an
  adversarial "quantum annealing" fixture is dropped), with the
  self-support check as a second line.
- **>= 2-paper evidence is mandatory** — enforced in `evidence.assemble`
  *and* re-enforced by the `ResearchGap` validator; a 1-paper candidate
  never reaches persistence.
- **Unsupported candidates are dropped** — `self_support_passed=False`
  (which includes "no LLM session") -> the candidate is not persisted.
- **No calibrated probability** — `confidence` is a `high|medium|low` enum;
  `confidence_basis` holds only counts / booleans / a coverage fraction;
  tests assert no `%` and no out-of-range float.
- **Confidence derives only from the basis** — `assign_confidence` is a pure
  function of `(n_supporting, self_support, evidence_coverage,
  limitation_agreement, gap_type)`.
- **Human decisions stick** — `accepted` / `rejected` rows survive a rerun;
  a `rejected` gap_id is skipped by the pipeline (`skipped_rejected`).
- **Deterministic rerun** — deterministic `gap_id` + upsert; tests compare
  `model_dump(exclude={"generated_at"})` across two runs.
- **Tenant isolation** — every route resolves the workspace through the
  Phase 8 owner gate (`404`, never `403`); `get_gap` / `set_gap_user_state`
  are workspace- and owner-scoped.

---

## Tests (56 new)

| File | N | Covers |
|---|---|---|
| `test_gap_domain.py` | 5 | 9 enum values; `>= 2` distinct supporting papers; `>= 1` evidence span; confidence is a band not a `%`; candidate defaults. |
| `test_gap_matrix.py` | 4 | rows = papers; facet pull with spans; normalised `papers_with` / `papers_without`; `value_counts` / `newest_year`; no-profile paper is an empty row. |
| `test_gap_candidates.py` | 14 | **each rule fires on a crafted fixture and not on a near-miss** (method coverage / shared-context requirement / dataset & metric divergence / shared limitation / unexplored combination / temporal staleness); CONTRADICTION only from `POTENTIALLY_CONTRADICTORY` edges; `gap_types` filter. |
| `test_gap_evidence.py` | 5 | `< 2` papers dropped; dedupe supporting papers; `evidence_coverage` = full-text-grounded fraction; CONTRADICTION needs conflicting spans from 2 papers. |
| `test_gap_articulate.py` | 5 | phrases from facts/evidence; **adversarial LLM adding an unsupported method is caught**; `is_grounded` helper; no-session deterministic template; LLM-failure fallback. |
| `test_gap_confidence.py` | 6 | self-support uses the `IsSupported?` verifier; `False` without session/evidence/on failure; failed self-support -> `LOW` + basis recorded; band from basis only; enum never a `%`; CONTRADICTION counts as strong support. |
| `test_gap_pipeline.py` | 7 | end-to-end grounded gaps; **articulation that invents a claim dropped**; **self-support failure dropped**; no session -> no gaps; **deterministic rerun**; **rejected not re-proposed**; `gap_types` filter. |
| `test_db_repository_gap.py` | 6 | save/get round-trip; `state` filter + workspace scope; rerun keeps `accepted`/`rejected`, drops stale candidates; `get_rejected_gap_ids`; `set_gap_user_state` tenant-scoped; workspace delete cascades. |
| `test_gap_api.py` | 5 | `409` no key / `404` cross-tenant; `202` job -> persisted evidence-grounded candidates (spans, band, basis, `self_support_passed`); `422` bad type; accept / reject / `state` filter / `404` unknown gap; rerun deterministic + keeps rejections. |

Maps to the Roadmap Phase 11 test list: a `< 2`-paper candidate is dropped;
the articulation prompt cannot introduce a claim without a cited span
(adversarial fixture caught); `CONTRADICTION` needs conflicting spans from
`>= 2` papers; confidence band derives only from `confidence_basis`;
`self_support_passed=false` -> dropped; no percentage in `confidence`.

---

## Acceptance criteria

| Criterion (Roadmap Phase 11) | State |
|---|---|
| Pipeline: matrix -> rule candidates -> evidence assembly (>= 2) -> constrained articulation -> self-support -> confidence band -> human accept/reject | **Met** — implemented in that fixed order, each step a hard gate; endpoints deliver `202`/`GET`/accept-reject. |
| The LLM cannot invent a gap; a gap must have sufficient real-paper evidence before articulation; unsupported candidates rejected/marked | **Met** — deterministic rules gate the LLM; `is_grounded` + `self_support_check` drop unsupported output; `>= 2` spans enforced twice. |
| `confidence` is a band, never a calibrated probability (calibration -> Phase 16) | **Met by construction** — `Confidence` enum only; `confidence_basis` carries the inputs. |
| Directly addresses the IEEE BigData 2024 limitation | **Met** — every surfaced gap is a persisted object with `>= 2` `GapEvidence` spans (`paper_id` + `section`/`page`/`char` offsets + `quote`), a `detection_rule`, a `why_unaddressed`, and a `confidence_basis` — the auditable evidence trail the source paper does not provide. |
| Expert-rated set (>= 150 edges / 10 workspaces): >= 60 % rated relevant/plausible; evidence-support rate = 100 %; hallucination rate <= 0.02/gap; beats the "ask GPT-4 for gaps" baseline | **Deferred to Phase 16** — needs the D-RN-GAP expert-rated fixture and `eval/gap_eval.py` (Evaluation Plan §7). Evidence-support = 100 % holds *by construction* here (no gap without `>= 2` valid spans); the expert-relevance and baseline-delta numbers are eval-run deliverables. |

---

## Deferred / explicitly out of scope

- **`eval/gap_eval.py` + the D-RN-GAP expert-rated fixture + baseline
  comparison** -> Phase 16.
- **`DOMAIN_GAP` / `PERFORMANCE_GAP` deterministic rules** — enum values
  present; rules need a domain taxonomy / numeric-metric parsing (the
  latter can build on a persisted `Comparison`).
- **Graph-projected matrix** — the roadmap notes the matrix is "a graph
  projection" once Phase 13 lands; the MVP builds it straight from
  profiles.
- **Research directions** (`POST /workspaces/{id}/directions`) — Phase 12;
  accepting a gap here only sets `user_state="accepted"`.

---

## Traceability

This phase *is* the ResearchNexus answer to the tracked limitation
(Architecture §9): *"no explicit, auditable, evidence-backed research-gap
identification workflow across multiple papers."* A surfaced
`ResearchGap` names which deterministic rule found it, cites `>= 2`
verbatim `SourceSpan`s from real papers, states why it is unaddressed from
that evidence only, is checked for self-support, carries a band + an
explicit `confidence_basis`, and waits for a human accept/reject — none of
which the source approach produces.

---

## Files changed

**New**

- `app/domain/gap.py`
- `app/services/gaps/{__init__,matrix,candidates,evidence,articulate_llm,confidence,pipeline}.py`
- `migrations/versions/0010_research_gaps.py`
- `tests/unit/test_gap_{domain,matrix,candidates,evidence,articulate,confidence,pipeline}.py`
- `tests/unit/test_db_repository_gap.py`
- `tests/integration/test_gap_api.py`

**Modified**

- `app/db/models.py` — `ResearchGapORM`.
- `app/db/repository.py` — the Phase 11 gap-persistence section.
- `app/jobs/runner.py` — `run_gaps_job` (BackgroundTasks).
- `app/routers/synthesis.py` — `POST`/`GET .../gaps`, `POST .../gaps/{gap_id}`.
- `app/config.py` — `gap_min_supporting_papers`, `gap_temporal_years`.
- `tests/unit/test_migrations.py` — assert `research_gaps` on upgrade / gone on downgrade.
- `pyproject.toml` — description bumped to "Phases 1-11".
