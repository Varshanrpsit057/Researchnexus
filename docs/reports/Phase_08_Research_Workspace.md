# ResearchNexus — Phase 8 Completion Report: Research Workspace

**Scope.** Stages S12-S13 of the pipeline (Architecture §3): the persistent
`ResearchWorkspace` container that every later synthesis stage reads from —
its paper collection, tenant isolation, the trail-review surface, and the
combined-index seam Phase 9 RAG builds on. Implements only the workspace;
no RAG, comparison, gaps, directions, UI, orchestrator hardening, or
`stage_runs` telemetry.

**Companion docs.** `ResearchNexus_Implementation_Architecture.md` (§3
S12-S13, §5), `ResearchNexus_Data_Model.md` (§7 / §13 `workspaces`,
`workspace_papers`), `ResearchNexus_Implementation_Roadmap.md` (Phase 8),
`ResearchNexus_API_Specification.md` (§5).

---

## Status

| Gate | Command | Result |
|---|---|---|
| Tests | `pytest -q` | **472 passed**, 2 warnings (pre-existing Starlette/anyio deprecations) |
| Lint | `ruff check .` | **All checks passed** |
| Types | `mypy app tests` | **Success: no issues in 182 source files** |
| Migrations | `test_migrations.py` + manual `0001->0007` up / `base` down / `0007<->0006` step | **round-trips clean**; ORM `create_all` and Alembic head schemas match |

43 new tests were added (all green); the rest of the suite is unchanged.

---

## What was built

| Module | Responsibility |
|---|---|
| `app/domain/workspace.py` | `ResearchWorkspace`, `WorkspacePaper`, and the `WorkspacePaperRole` / `AddedBy` / `Grounding` enums. Tag normalisation (strip, dedupe, order-preserving, capped) and a non-blank title validator live here; `.paper()` / `.related_papers` helpers. |
| `app/db/models.py` | `WorkspaceORM` + `WorkspacePaperORM` (composite PK `(workspace_id, paper_id)`, `ix_wp_owner`); `ix_paper_relationships_workspace` added to the Phase 7 table. |
| `migrations/versions/0007_workspaces.py` | Creates both tables + the trail-membership index. Revision `0007`, down-revision `0006`. |
| `app/db/repository.py` | 20 workspace functions: CRUD, the paper-collection row ops, `attach_run_edges_to_workspace` / `get_workspace_trail_edges` / `accept_reject_workspace_edge`, `workspace_child_counts`, `set_workspace_index_path`. `_owned_workspace_row` is the single tenant gate. |
| `app/retrieval/workspace_index.py` | `WorkspaceChunkIndex` Protocol — the seam Phase 9 implements over FAISS — plus `DbBackedWorkspaceIndex`, a deterministic dependency-free reference implementation (membership list + lexical `search` over `paper_chunks`), and `get_workspace_index` factory. A JSON manifest is persisted to `combined_index_path`. |
| `app/services/workspace/pipeline.py` | The service layer: workspace lifecycle, `add_papers` / `remove_paper` (each re-runs the index), `update_paper` (pin / tag / note / order), and the trail-review surface (`grouped_trail`, `set_edge_state`). Tenant isolation is enforced here — a foreign workspace raises `WorkspaceNotFound`. |
| `app/routers/workspaces.py` | The 10 Phase 8 endpoints; every route is `CurrentUser`-scoped; a foreign workspace is a `404`, never `403`. |

### Tenant isolation

Every workspace-scoped read goes through `repo._owned_workspace_row(db,
workspace_id, owner_id)` — a row whose `owner_id` does not match the acting
user is returned as `None`, which the service turns into `WorkspaceNotFound`
and the router into `404`. Integration tests assert this on `GET`, `PATCH`,
`DELETE`, `add_papers`, and `GET /trail` for a second tenant, and that
`list` never leaks another user's workspaces.

### Trail membership (S12)

A workspace records the discovery run it was built from (`source_run_id`,
nullable, `SET NULL` on run delete). `create_workspace(import_run_id=...)`
calls `attach_run_edges_to_workspace`, which stamps `workspace_id` /
`owner_id` onto that run's Phase 7 `paper_relationships` rows.
`GET /workspaces/{id}/trail` reads them grouped by relationship type;
rejected edges are hidden unless `?state=rejected`. `POST
/workspaces/{id}/trail/{edge_id}` accepts / rejects — a rejection is written
through `set_trail_edge_user_state` semantics, so the Phase 7
`get_rejected_trail_keys` suppression still sees it on a re-run. Adding a
paper from the trail flips its pending edges to `accepted` (API spec
§Workspaces).

### Combined-index seam (S13)

`WorkspaceChunkIndex` is the stable contract: `rebuild` / `add_paper` /
`remove_paper` (each returns the fresh manifest), `paper_ids`, `search`,
`manifest`. Phase 8 ships `DbBackedWorkspaceIndex` — no FAISS, no
embeddings; it resolves the workspace's chunks from `paper_chunks` by paper
membership and scores `search` with token-Jaccard overlap. This exists so
the pipeline has a real call to make after every membership change and so
incremental-rebuild correctness ("a removed paper's chunks are gone from
search") is verified now. Phase 9 swaps in the FAISS + LRU implementation
behind the same Protocol via the `get_workspace_index` factory.

---

## Determinism & isolation guarantees

- **A paper appears at most once per workspace** — enforced by the
  `(workspace_id, paper_id)` composite PK; the service `add_papers` is
  idempotent (already-member ids are skipped, `added` reflects only real
  inserts).
- **The seed cannot be removed** — `remove_paper` raises `CannotRemoveSeed`
  for the `role="seed"` row.
- **Deleting a workspace** cascades to `workspace_papers` (FK `ON DELETE
  CASCADE`) and releases trail membership (`workspace_id` / `owner_id`
  nulled on the still-run-scoped `paper_relationships` rows).
- **Index rebuilds are deterministic** — same membership -> byte-identical
  manifest (excluding `built_at`) and identical `search` ordering
  (score desc, then `chunk_id` asc).
- **Tenant gate is uniform** — one helper, applied on every route.

---

## Tests (43 new)

| File | N | Covers |
|---|---|---|
| `test_workspace_domain.py` | 7 | enum vocabulary; `WorkspacePaper` / `ResearchWorkspace` defaults; non-blank title; tag strip/dedupe/order; `.paper()` / `.related_papers`; `ranking_snapshot` round-trip. |
| `test_db_repository_workspace.py` | 9 | create/get round-trip; **tenant isolation** on get/list/update; partial update; delete cascade + trail-membership release; add/get/remove; **duplicate add -> IntegrityError**; pin/tag/note/reorder + partial update; child counts; workspace-scoped edge accept/reject feeding `get_rejected_trail_keys`. |
| `test_workspace_index.py` | 7 | rebuild indexes only members; lexical ranking + `k`; `add_paper` makes chunks searchable; **`remove_paper` evicts chunks** (incremental correctness); empty-paper add is a no-op; manifest persisted + reloadable; deterministic rebuild. |
| `test_workspace_pipeline.py` | 10 | create seeds with the analysed paper + writes the index; requires an analysed seed (409) / rejects unknown seed (404); `add_papers` idempotent + unknown-id 404; add/remove re-indexes; cannot remove seed; **foreign-workspace ops raise `WorkspaceNotFound`**; pin/tag/annotate normalisation; import-run attaches trail + accepts imported edges + snapshots ranking; rejected hidden by default. |
| `test_workspaces_api.py` | 10 | auth required; create -> get with counts + `cost_used`; unanalysed seed 409 / missing seed 404; **cross-tenant get/patch/delete/list all 404 / empty**; patch title + budget; add / dup-add / pin+tag+annotate / remove; cannot-remove-seed 409 + unknown-paper 404; delete 204 then gone; trail grouped read + reject + `?state=` + invalid-state 422 + unknown-edge 404. |

Maps to the Roadmap Phase 8 test list: add/remove rebuilds the combined
index (`_reindex` after every membership change, asserted via the manifest);
tenant scoping on every read, cross-tenant -> 404; incremental rebuild
correctness (removed paper's chunks gone from search). The FAISS LRU cache
eviction test is deferred with the FAISS backend (Phase 9).

---

## Acceptance criteria

| Criterion (Roadmap Phase 8) | State |
|---|---|
| Persistent `ResearchWorkspace`; add / remove / reorder / pin / tag / annotate | **Met** — domain + ORM + migration + repository + service + API, unit- and integration-tested. |
| Ownership + tenant isolation (cross-tenant -> 404) | **Met** — single `_owned_workspace_row` gate, asserted on every route for a second tenant. |
| Workspace membership for trail edges; grouped trail read + accept/reject | **Met** — `attach_run_edges_to_workspace` + `get_workspace_trail_edges` + `ix_paper_relationships_workspace`; `GET /trail` grouped, rejected hidden by default. |
| Combined chunk index rebuilds incrementally on paper-set change; a removed paper's chunks leave search | **Met at the interface** — `WorkspaceChunkIndex` + `DbBackedWorkspaceIndex`; `_reindex` runs inline on every change. |
| `stage_runs` rows written for every stage with latency / tokens / cost | **Deferred** — `stage_runs` telemetry belongs with the orchestrator and the synthesis stages it times (Phase 14); no stage runs in a Phase 8 workspace. |
| 20-paper combined-index rebuild < 20 s; workspace load < 1 s | **Load: met** (`GET /{id}` is two indexed queries, ms in tests). **Rebuild perf: deferred** — the number is meaningful only against the FAISS combined index (Phase 9); the deterministic stand-in is O(chunks) and trivially within budget. |
| First Postgres CI leg | **Deferred** — infra/CI change, out of the Phase 8 code scope. |

---

## Deferred / explicitly out of scope

- **`POST .../trail/retype`** — trail regeneration is Phase 7 pipeline work
  (needs a target-subset re-run); the accept/reject review action is
  delivered.
- **`POST .../papers` with `{ "manual": {doi|arxiv_id|url} }`** — manual
  metadata resolution reuses the Phase 4 external clients; only
  `{paper_ids, from_run_id}` is accepted now.
- **Async `202 -> Job(kind=index_rebuild|workspace_delete|trail)`** — the
  index rebuild runs inline in the service; `DELETE /workspaces/{id}` is a
  synchronous `204` (same treatment as the `papers.py` async fallback).
- **FAISS combined index + LRU cache + metadata sidecar** — Phase 9;
  `DbBackedWorkspaceIndex` is the placeholder behind the Protocol.
- **`stage_runs` / `artefacts` tables, `telemetry/{stage_timer,cost}.py`,
  `services/orchestrator/*`** — Phase 14.
- **`workspaces.graph_json` / `comparison_schema` columns** — Phases 13 / 10
  add them when those stages need them.
- **Synthesis routes** (chat / summary / keypoints / compare / gaps /
  directions / citations / presentation) — Phases 9-14.

---

## Traceability

Preserves the *IEEE BigData 2024 limitation -> ResearchNexus solution ->
evidence* chain: the workspace is where the typed, evidence-bearing trail
from Phase 7 becomes a curated set — the user accepts / rejects each edge,
and every imported paper keeps its `ranking_snapshot` (the Phase 6 signal
values and explanation as of import). Downstream gap / direction work reads
this audited collection, not an unexplained pile of PDFs.

---

## Files changed

**New**

- `app/domain/workspace.py`
- `app/retrieval/workspace_index.py`
- `app/services/workspace/{__init__,pipeline}.py`
- `app/routers/workspaces.py`
- `migrations/versions/0007_workspaces.py`
- `tests/unit/test_workspace_{domain,index,pipeline}.py`
- `tests/unit/test_db_repository_workspace.py`
- `tests/integration/test_workspaces_api.py`

**Modified**

- `app/db/models.py` — `WorkspaceORM`, `WorkspacePaperORM`,
  `ix_paper_relationships_workspace`.
- `app/db/repository.py` — the Phase 8 workspace section (20 functions).
- `app/main.py` — register `workspaces.router`.
- `tests/unit/test_migrations.py` — assert both tables on upgrade / gone on downgrade.
- `pyproject.toml` — description bumped to "Phases 1-8".
