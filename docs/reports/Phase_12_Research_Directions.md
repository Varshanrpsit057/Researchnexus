# ResearchNexus — Phase 12 Completion Report: Research Directions

**Scope.** `DirectionGenerator` (Architecture §4): turning an **accepted**
`ResearchGap` into concrete next-step research directions — LLM generate →
LLM critique → deterministic `kind` labelling and confidence band → human
accept/reject. Implements only directions; no research graph, UI, or
orchestrator hardening.

**Companion docs.** `ResearchNexus_Implementation_Architecture.md` (§4
`DirectionGenerator`), `ResearchNexus_Data_Model.md` (§9 `ResearchDirection`,
§13), `ResearchNexus_API_Specification.md` (§6 `directions`),
`ResearchNexus_Implementation_Roadmap.md` (Phase 12),
`ResearchNexus_Evaluation_Plan.md` (§8c Research directions).

---

## Status

| Gate | Command | Result |
|---|---|---|
| Tests | `pytest -q` | **647 passed**, 2 warnings (pre-existing Starlette/anyio deprecations) |
| Lint | `ruff check .` | **All checks passed** |
| Types | `mypy app tests` | **Success: no issues in 249 source files** |
| Migrations | `test_migrations.py` + manual `0001->0011` up / `base` down / `0011` step | **round-trips clean**; ORM `create_all` and Alembic head schemas match for `research_directions` (20 cols, index names aligned) |

37 new tests were added (all green); the rest of the suite is unchanged.
**No new dependencies.**

---

## Pipeline (per requested `gap_id`, fixed order)

```
load gap  ->  must be user_state="accepted" AND self_support_passed, else SKIP
  ->  LLM generate (grounded, or that draft is DROPPED)
  ->  LLM critique (novelty / specificity / feasibility / groundedness, 1-5)
  ->  deterministic kind label + confidence band
  ->  persist as user_state="candidate"
```

A `gap_id` that does not resolve to an accepted, self-supported gap in the
workspace is **skipped and counted** — never generated from. This is the
phase's central guarantee: *never allow the LLM to invent a gap, and never
generate a direction from an unaccepted or unsupported gap.*

| Module | Responsibility |
|---|---|
| `app/domain/direction.py` | `DirectionKind` (mandatory, validated), `DirectionUserState`, `ResearchDirection`. Validators: `supporting_evidence` non-empty (inherited from the gap), `kind` must be one of the two labelled values, `critique` scores clamped to `[1,5]` with `feasibility` further capped at 3 — feasibility is *always* treated as uncertain (Si et al.), never claimed high, regardless of what the LLM or the fallback returns. |
| `services/directions/generate.py` | LLM proposes `proposal` / `motivation` / `suggested_method` / `possible_dataset` / `evaluation_strategy` / `risks` from the gap's statement + evidence. Deterministic grounding check: any long technical term in `proposal`+`motivation` that is neither in the gap's own vocabulary nor this draft's own `suggested_method`/`possible_dataset` drops the draft outright (never silently templated over). `kind` is deterministic: `evidence_backed_inference` when the proposed method/dataset is already named by the gap; `llm_hypothesis` when it is new. No session / malformed LLM output -> exactly one deterministic direction built from the gap's own `proposed_direction` / `why_unaddressed` (Phase 11 produced them for this). |
| `services/directions/critique.py` | LLM critique pass; no session / failure -> a conservative deterministic critique (never claims high groundedness for an unchecked hypothesis). |
| `services/directions/confidence.py` | `assign_confidence(kind, critique, gap)` — a band **enum**, derived only from `confidence_basis` (`kind`, the 4 critique scores, the gap's own `confidence`/`self_support_passed`, `low_critique`). `HIGH` needs `evidence_backed_inference` + strong critique + a non-LOW gap; an unsupported gap forces `LOW` regardless of critique (defensive; Phase 11 never persists one, but the rule holds anyway). |
| `services/directions/pipeline.py` | Orchestrates the above per `gap_id`; deterministic `direction_id = dir_<sha256(workspace|gap|method|proposal)[:20]>` so a rerun with the same LLM output upserts; `accepted`/`rejected` rows survive a rerun untouched. |

### Persistence & API

`research_directions` table (migration `0011`, FK `gap_id -> research_gaps.id`
`ON DELETE CASCADE`, cascades with the workspace too). `confidence_basis`,
`flags` and `user_state` are additions beyond the Data Model §13 column
list — the brief requires an explicit confidence basis and accept/reject
handling, the same documented deviation as Phase 11's
`research_gaps.user_state`.

| Endpoint | Notes |
|---|---|
| `POST /workspaces/{id}/directions` | **Synchronous** (per API spec, unlike `gaps`). Body `{gap_ids:[...]}`, non-empty. `409 llm_key_required`; `404` cross-tenant; `422` empty `gap_ids`. Response reports `generated` / `skipped_not_accepted` / `skipped_not_found` / `dropped_unsupported` alongside the full `directions` list. |
| `GET /workspaces/{id}/directions?state=&gap_id=` | `{directions: [ResearchDirection]}`. |
| `POST /workspaces/{id}/directions/{direction_id}` | `{user_state: "accepted"\|"rejected"}` -> `200`; `404` if not in this workspace. |

---

## Guarantees (verified by tests)

- **Never from an unaccepted or unsupported gap** — `pipeline.build_directions`
  checks `user_state == "accepted"` *and* `self_support_passed` before
  calling the LLM at all; a candidate/rejected/missing gap is skipped and
  counted, not silently ignored.
- **Every direction traces to accepted-gap evidence** — `supporting_evidence`
  and `related_papers` are copied verbatim from the gap (never re-derived
  or re-asserted by the LLM); the domain validator rejects an empty list.
- **The LLM may propose wording, not unsupported technical claims** — the
  deterministic grounding check in `generate.py` (mirroring Phase 11's
  `is_grounded`) drops any draft that names a method/claim outside the
  gap's vocabulary and its own declared `suggested_method`/`possible_dataset`.
- **`kind` is mandatory and never a fact** — a direction is always labelled
  `evidence_backed_inference` or `llm_hypothesis`; `ResearchDirection`
  rejects any other value.
- **Feasibility stays uncertain** — capped at 3/5 in the domain model,
  independent of what any LLM call returns.
- **No calibrated probability** — `confidence` is a `high|medium|low` enum;
  `confidence_basis` carries only counts/booleans/small ints; tests assert
  no `%` in the basis.
- **Low critique is flagged, not dropped** — a direction with any critique
  score `<= 2` is still persisted, with `"low_critique"` in `flags` and
  `confidence_basis`.
- **Deterministic rerun** — deterministic `direction_id`; two runs with the
  same LLM output produce identical rows (`model_dump(exclude={
  "generated_at"})`).
- **Multiple directions per gap** — `direction_max_per_gap` bounds, not
  caps at one; each gets its own id keyed by `(gap, suggested_method,
  proposal)`.
- **Tenant isolation** — every route resolves the workspace through the
  Phase 8 owner gate (`404`, never `403`); `get_direction` /
  `set_direction_user_state` are workspace- and owner-scoped.

---

## Tests (37 new)

| File | N | Covers |
|---|---|---|
| `test_direction_domain.py` | 5 | `kind` mandatory + validated; non-empty evidence required; critique clamped + feasibility capped at 3; confidence is a band; candidate defaults. |
| `test_direction_generate.py` | 7 | no-session template is grounded; LLM drafts kept + classified by `kind` (already-named method vs new method); **adversarial unsupported claim dropped**; multiple directions per gap; `max_directions` cap; LLM-failure template fallback. |
| `test_direction_critique.py` | 4 | LLM scores returned + clamped; conservative no-session fallback (high groundedness only when evidence-backed, feasibility low); fallback less confident for a hypothesis; LLM-failure fallback. |
| `test_direction_confidence.py` | 6 | HIGH needs evidence-backed + strong critique + non-LOW gap; an `llm_hypothesis` cannot reach HIGH; MEDIUM/LOW bands; an unsupported gap forces LOW; enum never a `%`. |
| `test_direction_pipeline.py` | 4 | **direction only for an accepted gap** (candidate/missing gap skipped + counted); unsupported LLM output dropped, not persisted; **deterministic rerun**; no-session yields exactly one template direction. |
| `test_db_repository_direction.py` | 6 | save/get round-trip; `state`/`gap_id` filter + workspace scope; rerun keeps accepted/rejected, drops stale candidates; tenant-scoped state change; gap delete cascades; workspace delete cascades. |
| `test_direction_api.py` | 5 | `409` no key / `404` cross-tenant / `422` empty `gap_ids`; **generated only from an accepted gap** + persisted + listed; non-accepted gap skipped via the API; unsupported LLM output dropped via the API; accept/reject + `state` filter + `404` unknown. |

Maps to the Roadmap Phase 12 test list: a direction cannot be generated for
a non-accepted gap; every direction carries `kind`, `critique` scores, and
`confidence`; `motivation` cites the gap's evidence; a low critique score
flags rather than drops.

---

## Acceptance criteria

| Criterion (Roadmap Phase 12) | State |
|---|---|
| Directions from accepted gaps only; LLM generate -> LLM critique; `kind` label; feasibility explicitly uncertain | **Met** — enforced pipeline order; `kind` mandatory-validated; `feasibility` capped at 3. |
| A direction cannot be generated for a non-accepted gap | **Met** — `skipped_not_accepted`, verified at both the pipeline and API level. |
| Every direction carries `kind`, `critique`, `confidence`; `motivation` cites the gap's evidence; low critique flags, does not drop | **Met** — `supporting_evidence` inherited verbatim; `flags: ["low_critique"]` when any score `<= 2`, direction still persisted. |
| Expert rubric (novelty/specificity/feasibility/groundedness, 1-5): median groundedness >= 3.5; directions never phrased as established facts (lint prompt + human spot-check) | **Deferred to Phase 16** — needs the expert-rated fixture and a "phrased as fact" lint pass over a labelled set (Evaluation Plan §8c). The `_SYSTEM` prompt already instructs proposal/motivation to stay hypothetical ("propose", "suggested"), and `kind` makes the evidence-backed/hypothesis distinction structurally explicit, but the human-rated median and the automated lint check are eval-run deliverables. |

---

## Deferred / explicitly out of scope

- **Expert-rated groundedness median + "phrased as fact" lint check** ->
  Phase 16.
- **Research graph** (`GET /workspaces/{id}/graph`) — Phase 13.
- **`artefacts` cache**, async job variants — same deferrals carried from
  Phases 8-11.
- **UI / orchestrator hardening** — never in scope for this phase.

---

## Traceability

Continues the *IEEE BigData 2024 limitation -> ResearchNexus solution ->
evidence* chain one stage further: a direction is not a free-standing LLM
suggestion but a labelled extension of a specific, already-evidence-backed
`ResearchGap` — it inherits that gap's spans, cannot introduce a claim the
gap's evidence does not support, and is explicitly marked
`evidence_backed_inference` vs `llm_hypothesis` so the user never mistakes
a proposal for a stated fact.

---

## Files changed

**New**

- `app/domain/direction.py`
- `app/services/directions/{__init__,generate,critique,confidence,pipeline}.py`
- `migrations/versions/0011_research_directions.py`
- `tests/unit/test_direction_{domain,generate,critique,confidence,pipeline}.py`
- `tests/unit/test_db_repository_direction.py`
- `tests/integration/test_direction_api.py`

**Modified**

- `app/db/models.py` — `ResearchDirectionORM`.
- `app/db/repository.py` — the Phase 12 direction-persistence section.
- `app/routers/synthesis.py` — `POST`/`GET .../directions`, `POST .../directions/{direction_id}`.
- `app/config.py` — `direction_max_per_gap`.
- `tests/unit/test_migrations.py` — assert `research_directions` on upgrade / gone on downgrade.
- `pyproject.toml` — description bumped to "Phases 1-12".
