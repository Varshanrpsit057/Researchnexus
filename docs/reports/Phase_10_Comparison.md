# ResearchNexus — Phase 10 Completion Report: Multi-Paper Comparison

**Scope.** The comparison row of Stage S13 (Architecture §1.1): a
profile-grounded comparison table across selected workspace papers --
deterministic schema, per-cell LLM value *proposal* gated by deterministic
evidence validation, persistence, and the `POST /workspaces/{id}/compare`
endpoint. Implements only comparison; no gaps, directions, research graph,
UI, or orchestrator hardening.

**Companion docs.** `ResearchNexus_Implementation_Architecture.md` (§1.1
"Comparison cell grounding check", §3 S13, §4 `Synthesis`),
`ResearchNexus_Data_Model.md` (§7 `ComparisonSchema`, §10 `Claim`, §13),
`ResearchNexus_API_Specification.md` (§6 `compare`),
`ResearchNexus_Implementation_Roadmap.md` (Phase 10),
`ResearchNexus_Evaluation_Plan.md` (§8b Comparison).

---

## Status

| Gate | Command | Result |
|---|---|---|
| Tests | `pytest -q` | **554 passed**, 2 warnings (pre-existing Starlette/anyio deprecations) |
| Lint | `ruff check .` | **All checks passed** |
| Types | `mypy app tests` | **Success: no issues in 219 source files** |
| Migrations | `test_migrations.py` + manual `0001->0009` up / `base` down / `0009<->0008` step (`add_column` + `create_table`, both reversible) | **round-trips clean**; ORM `create_all` and Alembic head schemas match for `comparisons` **and** `workspaces` (the new column is appended to match `ADD COLUMN` order) |

26 new tests were added (all green); the rest of the suite is unchanged.
**No new dependencies.**

---

## How it works

### 1. Schema (deterministic -- no LLM)

`build_schema(profiles, explicit)`:
- an explicit column list is normalised (trim / lowercase / dedupe) and
  returned as `generated_by="deterministic_union"`;
- otherwise the schema is the **union of the canonical facets that at least
  one selected paper's `ResearchProfile` has data for**, in fixed order
  `problem, method, dataset, metric, result, limitation` (`method` =
  `methods ∪ models ∪ algorithms`);
- with no profile data it falls back to `["method", "dataset", "metric",
  "result"]`.

Same inputs -> same columns, every time.

### 2. Cells (LLM proposes, deterministic validation gates)

For each `(paper, column)`:
1. retrieve the paper's evidence with the **existing RAG retriever** over
   the FAISS workspace index, scoped to that paper (`compare_retrieve_k`);
2. one batched LLM call per paper proposes `{value, chunk_id, quote,
   alternates}` for every column, or `null` where the paper does not state
   it;
3. **evidence validation before anything is written** (`_grounded_cell`):
   the value is kept **only if** `chunk_id` was actually retrieved for this
   paper *and* `quote` is a verbatim span of that chunk. Otherwise the cell
   is `text=None` -- a *missing* value, never a guess.
4. a kept cell gets a `SourceSpan` (paper / section / page / quote), a
   `grounding` flag from the paper's `WorkspacePaper.grounding`
   (`"abstract"` for abstract-only related papers), any verified
   `alternates` as `conflicting`, and a persisted `Claim`
   (`artefact_kind="comparison_cell"`, `artefact_id=comparison_id`).

`coverage` = grounded cells / (papers × columns) -- the API-spec's "fraction
of cells with a valid supporting span".

Degradation: no session -> every cell `null`, `coverage=0`, warning; an LLM
failure for one paper leaves **only that paper's** cells missing.

### 3. Persistence & API

- `comparisons` table (migration `0009`) + `workspaces.comparison_schema`
  column (Data Model §13); `save_comparison` (upsert), `get_comparison`
  (workspace-scoped), `list_comparisons`, `set_workspace_comparison_schema`
  (owner-gated).
- `POST /api/v1/workspaces/{id}/compare` -- body `{paper_ids, schema}`;
  `409 llm_key_required` without a key; `404` cross-tenant; `422` for fewer
  than two workspace papers; persists the `Comparison` + its cell `Claim`s +
  the workspace schema; returns the API-spec shape (`schema` is the flat
  column list, `rows[].cells[col] = {text, span, claim_id, grounding,
  conflicting}`, `coverage`, `decontext_eval: null`).
- `GET /api/v1/workspaces/{id}/compare/{comparison_id}` -- workspace-scoped
  fetch (`404` otherwise).

---

## Guarantees (verified by tests)

- **Every factual cell has evidence** -- a non-null `text` always carries a
  `span` into a real retrieved chunk and a `claim_id`; `ComparisonCell.
  has_evidence` and the `_grounded_cell` gate enforce it.
- **Missing values are never invented** -- a `null`/unsupported/
  bad-quote/unretrieved-chunk proposal yields `text=None`, no `Claim`, and
  lowers `coverage`.
- **The schema is deterministic where possible** -- pure function of the
  profiles (or the caller's list); `generated_by` records which.
- **Validation happens before persistence** -- `build_comparison` returns
  the `Comparison` + `claims`; the router persists only after the gate.
- **The LLM cannot widen the table** -- a proposed column outside the
  schema is ignored.
- **Tenant isolation preserved** -- compare / get resolve the workspace
  through the Phase 8 owner gate (`404`, never `403`); `get_comparison` is
  workspace-scoped.
- **Deterministic output** -- given the deterministic retriever + a fixed
  LLM response, repeated `compare` calls produce identical schema, rows,
  cells and coverage (only the fresh `comparison_id` and its derived
  `claim_id`s differ).

---

## Tests (26 new)

| File | N | Covers |
|---|---|---|
| `test_comparison_domain.py` | 2 | `has_evidence`; `api_dict` flattens `schema` to the column list and nulls empty cells. |
| `test_comparison_schema.py` | 4 | default = union of populated profile facets; fallback to `DEFAULT_COLUMNS`; explicit list normalised; deterministic across profile order. |
| `test_comparison_build.py` | 9 | grounded cells carry span/claim/grounding + coverage; **non-verbatim quote rejected**; **unretrieved chunk rejected**; **null value stays missing**; verified `conflicting` alternates recorded; LLM cannot add a column; no session -> all missing; per-paper LLM failure isolates; deterministic build. |
| `test_db_repository_comparison.py` | 6 | save/get round-trip (schema, rows, cells, coverage); workspace-scoped get; upsert by id; workspace delete cascades comparisons; `set_workspace_comparison_schema` owner-gated; `list_comparisons`. |
| `test_comparison_api.py` | 5 | `409` no key / `404` cross-tenant; `422` fewer than two papers; grounded table + persisted + fetchable + tenant-scoped GET + bad-quote cell null + coverage; default schema from profiles; deterministic output. |

Maps to the Roadmap Phase 10 test list: schema = union of profile fields
when `schema:null`; every populated cell has a `span` and a `claim_id`;
cells with no support are `null`, not hallucinated; multiple papers;
tenant isolation; deterministic output; API behaviour.

---

## Acceptance criteria

| Criterion (Roadmap Phase 10) | State |
|---|---|
| Deterministic schema (union of method/model/dataset/metric fields) when `schema:null` | **Met** -- `build_schema` over the selected papers' profiles. |
| Per-cell LLM value generation; every cell cites a span; unsupported cells are `null` | **Met** -- LLM proposes, `_grounded_cell` validates verbatim-in-retrieved-chunk before persistence. |
| Comparison persistence + `POST /workspaces/{id}/compare` | **Met** -- `comparisons` table + `comparison_schema` column + endpoint + a `GET` for retrieval. |
| Abstract-only related papers -> `grounding:"abstract"` on the cell | **Met** -- from `WorkspacePaper.grounding`. |
| **DecontextEval in CI**; column/value recall >= 0.6; per-cell evidence coverage >= 0.9 on a 10-workspace arxivDIGESTables-style fixture | **Deferred to Phase 16** -- `eval/decontext_eval.py` and the D-ADT reference-table fixture are eval-harness deliverables (Evaluation Plan §8b). `coverage` is computed and returned at request time; `decontext_eval` stays `null` (set by eval runs). |
| `202 -> Job` for larger paper sets | **Deferred** -- comparison runs synchronously; sets a `large_comparison_ran_sync` warning above `compare_max_sync_papers` (4). Same treatment as the deferred async paths in Phases 8-9. |

---

## Deferred / explicitly out of scope

- **`eval/decontext_eval.py` + DecontextEval CI + column/value-recall
  benchmark** -> Phase 16 (Evaluation Plan §8b).
- **Async `202 -> Job(kind=compare)`** for large sets.
- **`llm_schema` (ArxivDIGESTables-style LLM schema induction)** -- the
  `ComparisonSchema.generated_by` value exists; only the deterministic union
  is built. LLM schema induction is an eval-comparison variant.
- **`artefacts` cache table** -- comparisons persist to their own table;
  a generic artefact cache with invalidation is still deferred (from
  Phase 8/9).
- **gaps / directions / graph / presentation** -- Phases 11-14.

---

## Traceability

Preserves the *IEEE BigData 2024 limitation -> ResearchNexus solution ->
evidence* chain: the source paper produces meta-analysis prose with no
per-claim evidence trail. Phase 10 turns cross-paper comparison into a
table where **every populated cell** is a persisted `Claim` pointing at a
verbatim span in a real `paper_chunks` row, and a value the evidence does
not support is left blank rather than guessed -- the auditable,
non-hallucinated comparison the source approach does not provide.

---

## Files changed

**New**

- `app/domain/comparison.py`
- `app/services/synthesis/compare.py`
- `migrations/versions/0009_comparisons.py`
- `tests/unit/test_comparison_{domain,schema,build}.py`
- `tests/unit/test_db_repository_comparison.py`
- `tests/integration/test_comparison_api.py`

**Modified**

- `app/db/models.py` -- `ComparisonORM`; `WorkspaceORM.comparison_schema` column.
- `app/db/repository.py` -- the Phase 10 comparison persistence section.
- `app/routers/synthesis.py` -- `POST` / `GET .../compare`.
- `app/config.py` -- `compare_retrieve_k`, `compare_max_sync_papers`.
- `tests/unit/test_migrations.py` -- assert `comparisons` on upgrade / gone on downgrade.
- `pyproject.toml` -- description bumped to "Phases 1-10".
