# ResearchNexus — Phase 13 Completion Report: Research Graph

**Scope.** `GraphBuilder` (Architecture §5): a small, deterministic,
per-workspace `ResearchGraph` -- a `PAPER` node for every workspace member
and a typed edge for every non-rejected Phase 7 `TrailEdge` between two
current members. JSON-persisted on the workspace
(`workspaces.graph_json`). No entity extraction, no GraphRAG routing, no
`mode:"themes"` chat routing -- foundation only, per this phase's brief.

**Companion docs.** `ResearchNexus_Implementation_Architecture.md` (§5
"Research graph -- why workspace-level is the right MVP"),
`ResearchNexus_Data_Model.md` (§11 `ResearchGraph`, §13),
`ResearchNexus_Implementation_Roadmap.md` (Phase 13),
`ResearchNexus_Evaluation_Plan.md` (A13 ablation).

---

## Status

| Gate | Command | Result |
|---|---|---|
| Tests | `pytest -q` | **689 passed**, 2 warnings (pre-existing Starlette/anyio deprecations) |
| Lint | `ruff check .` | **All checks passed** |
| Types | `mypy app tests` | **Success: no issues in 258 source files** |
| Migrations | `test_migrations.py` + manual `0001->0012` up / `0012->0011` / `base` down round-trip | **clean**; ORM `create_all` and Alembic head schemas match for `workspaces.graph_json` (column present, correctly ordered after `comparison_schema`) |

42 new tests were added (all green); the rest of the suite is unchanged.
**No new dependencies** (see "`networkx` deferred" below).

---

## Design decisions

**Scope of this cut.** The Roadmap's full Phase 13 description covers all
eight node types (Paper/Method/Dataset/Topic/RQ/Claim/Gap/Direction) and
GraphRAG routing. The user's brief for *this* phase narrows that to "nodes
for workspace papers," "edges from typed research-trail relationships,"
and explicitly "every edge must trace back to an existing Phase 7
TrailEdge" -- no mention of profiles/gaps/directions as edge sources, and
"do not implement GraphRAG routing yet." `app/domain/graph.py` therefore
fixes the **full** `GraphNodeType` / `GraphEdgeType` vocabulary now (so
later phases populate into an already-stable schema), but
`services/graph/builder.py` populates only `PAPER` nodes and
trail-derived edges this phase. Method/Dataset/Topic/RQ/Claim/Gap/
Direction projection and GraphRAG traversal are explicitly deferred.

**`RelationshipType -> GraphEdgeType` mapping.** Fixed and total (all 7
trail relationship types map somewhere; no trail edge is silently
unmapped), grounded in what each rule actually detects
(`services/trail/rules.py`), not guessed:

| Trail `RelationshipType` | Rule signal | Graph `GraphEdgeType` |
|---|---|---|
| `FOUNDATIONAL` | `cited_by_seed AND target_year < seed_year` -- a citation fact | `CITES` |
| `METHOD_EXTENSION` | `cites_seed AND method_sim>=0.55` -- a citation fact | `EXTENDS` |
| `SIMILAR` | base topical/semantic similarity | `SIMILAR` |
| `RECENT` | `target_year > seed_year AND topically related`, no citation | `SIMILAR` (same family as the base rule) |
| `COMPETING` | `problem_sim high, method_sim low, no citation` | `COMPETES_WITH` |
| `DATASET_RELATED` | shared/overlapping dataset | `USES_DATASET` |
| `POTENTIALLY_CONTRADICTORY` | NLI-verified contradiction | `CONTRADICTS` |

`SUPPORTS`, `ADDRESSES`, `EXPOSES_GAP` and `USES_METHOD` are reserved for
node types (Method, Gap, Direction) this phase does not populate.

**Deduplication is a real scenario, not defensive-only.** Because
`RECENT` and `SIMILAR` both map to `GraphEdgeType.SIMILAR`, a paper pair
where *both* trail rules fire produces two `TrailEdge` rows that collapse
onto the same `(src, dst, type)` graph edge. `build_graph` merges these:
evidence spans are unioned (deduplicated by `paper_id`+`quote`) and the
higher of the two confidences is kept -- never dropped, never duplicated.

**Stale/dangling edges are filtered, not just rejected ones.**
`repo.remove_workspace_paper` deletes only the `workspace_papers` row; the
underlying `paper_relationships` (trail edge) rows are untouched and keep
pointing at a paper no longer in the workspace. `build_graph` therefore
drops any edge whose source *or* target is not a current workspace member,
in addition to dropping `user_state == "rejected"` edges -- confirmed by
`test_an_edge_whose_target_left_the_workspace_is_dropped`. This mirrors
the existing `grouped_trail` precedent
(`app/services/workspace/pipeline.py`: "rejected edges are hidden unless
explicitly asked for").

**Rebuild-on-read, not incremental.** `pipeline.get_graph` recomputes the
graph from the workspace's current papers + trail edges on every call and
re-persists it to `workspaces.graph_json`. The graph has no state beyond
those two already-authoritative sources, so a fresh deterministic rebuild
is simpler and strictly safer than an incremental diff -- it is
automatically correct after *any* add/remove/accept/reject, including
paths this phase doesn't specifically hook (e.g. future bulk operations),
with zero changes required to the already-tested Phase 8 `add_papers` /
`remove_paper` / `set_edge_state` functions.

**Column name: `graph_json`, not `graph_json_ref`.** Data Model §7's
Pydantic sketch of `ResearchWorkspace` uses `graph_json_ref`, but §13's
relational schema and the Roadmap's own migration label both say
`workspaces.graph_json`, and `WorkspaceORM`'s docstring had already
reserved that exact name ("`graph_json` / `comparison_schema` ... are
added by Phases 10/13 when those stages need them"). `graph_json` is used
throughout; no field was added to the `ResearchWorkspace` Pydantic model
(same treatment as Phase 10's `comparison_schema` -- ORM-only, since no
domain-layer logic needs it on the workspace object itself).

**`networkx` deferred, not added.** The Roadmap lists `networkx` as this
phase's dependency, but Phase 13 as scoped here needs no graph algorithm --
no traversal, shortest-path, or centrality (that's GraphRAG routing,
explicitly out of scope). The Data Model's own persisted `ResearchGraph`
schema is already plain `nodes: list[dict]` / `edges: list[dict]`; "built
with `networkx` in memory" describes a possible implementation detail of a
*future* traversal-heavy builder, not the wire format. Per this project's
established pattern (`pyproject.toml`: "Heavy/optional retrieval backends
[are] kept OUT of the default install" until a phase actually exercises
them -- the same reasoning that deferred `sentence-transformers`/
`faiss-cpu` past Phase 9 and `ragas` past Phase 16), `build_graph` is a
plain deterministic function over dataclasses/Pydantic models. `networkx`
is deferred to whichever future phase implements real GraphRAG traversal.

---

## Pipeline

```
GET /workspaces/{id}/graph
  -> resolve owned workspace (404, never 403, on a foreign workspace)
  -> load workspace.papers + repo.get_workspace_trail_edges(workspace_id)
  -> build_graph(workspace, trail_edges, paper_titles):
       nodes  = PAPER node per workspace member (id = paper_id, sorted)
       edges  = non-rejected trail edges, both endpoints still members,
                relationship_type mapped to GraphEdgeType,
                same-(src,dst,type) edges merged (evidence union, max confidence)
  -> persist to workspaces.graph_json (repo.set_workspace_graph)
  -> return ResearchGraph
```

| Module | Responsibility |
|---|---|
| `app/domain/graph.py` | `GraphNodeType` (8 values), `GraphEdgeType` (10 values), `GraphNode`, `GraphEdge`, `ResearchGraph`. `node_count`/`edge_count` are derived in a `model_validator`, never independently settable. |
| `app/services/graph/builder.py` | `build_graph(workspace, trail_edges, paper_titles) -> ResearchGraph` -- pure, DB-free, deterministic (sorts every input before folding it in, so caller order never affects the result). |
| `app/services/graph/query.py` | `GraphQuery` -- id lookup, type filters, undirected `neighbors()`, `to_json`/`from_json`. Read-only foundation; no scoring or path-finding. |
| `app/services/workspace/pipeline.py::get_graph` | Owner-gated fetch, title lookup, calls `build_graph`, persists, returns. |
| `app/routers/workspaces.py` | `GET /{workspace_id}/graph` -- tenant-scoped, 404 on a foreign/missing workspace. |

### Persistence

No new table: `workspaces.graph_json` (migration `0012`, nullable JSON),
same JSON-on-workspace pattern as Phase 10's `comparison_schema` (`0009`).
`repo.set_workspace_graph` / `repo.get_workspace_graph` mirror
`set_workspace_comparison_schema` exactly, including owner-gating (a
foreign `owner_id` is a silent no-op / `None`, never raises).

---

## Guarantees (verified by tests)

- **No invented nodes** -- a `PAPER` node exists only for an actual
  `workspace_papers` row; removing a paper removes its node on the next
  fetch (`test_removing_a_paper_drops_its_node_and_edges_from_the_graph`).
- **Every edge traces to a real, non-rejected `TrailEdge`** -- the mapping
  table is total and grounded in the actual trail-rule semantics (table
  above); a `user_state == "rejected"` edge is never emitted
  (`test_rejected_trail_edges_are_excluded`,
  `test_rejecting_a_trail_edge_removes_it_from_the_graph_but_keeps_the_node`).
- **No dangling edges** -- an edge whose endpoint left the workspace is
  dropped even though the underlying trail row still exists
  (`test_an_edge_whose_target_left_the_workspace_is_dropped`).
- **Deterministic and reproducible** -- `build_graph` sorts nodes, sorts
  trail edges before folding, and sorts the merged-edge keys before
  emitting the final list; two builds from equivalent input (any order)
  produce identical output modulo `built_at`
  (`test_construction_is_deterministic_regardless_of_input_order`,
  `test_rerun_with_identical_input_is_byte_identical`).
- **Node/edge counts can never lie** -- `ResearchGraph.node_count` /
  `edge_count` are derived by a `model_validator`, not accepted as
  independent input (`test_node_and_edge_counts_are_derived_not_freely_settable`).
- **Tenant isolation** -- `GET .../graph` resolves the workspace through
  the Phase 8 owner gate; a foreign or missing workspace is `404`, never
  `403` (`test_graph_is_invisible_to_other_tenants`).
- **Always current** -- rebuilt fresh on every read, so add/remove/
  accept/reject are reflected on the very next fetch with no separate
  invalidation path to keep in sync.

---

## Tests (42 new)

| File | N | Covers |
|---|---|---|
| `test_graph_domain.py` | 7 | all 8 node types / 10 edge types defined; invalid `type` rejected; `node_count`/`edge_count` derived, not settable; empty graph; JSON round-trip. |
| `test_graph_builder.py` | 15 | node per workspace paper; title fallback to id; no invented nodes; each `RelationshipType -> GraphEdgeType` mapping; evidence traced verbatim; **two relationship types merging into one graph edge** (evidence union, max confidence, no duplicate spans); rejected edges excluded; pending/accepted included; **dangling edge (removed paper) dropped**; deterministic regardless of input order; byte-identical rerun. |
| `test_graph_query.py` | 5 | node-by-id lookup; type filters; undirected neighbors excluding self; JSON round-trip. |
| `test_db_repository_graph.py` | 6 | get-before-set is `None`; set/get round-trip; stored as plain JSON on the workspace row; set and get are both owner-gated; overwrite replaces. |
| `test_workspace_graph_api.py` | 8 | requires auth; fresh workspace has only the seed node; tenant isolation; missing workspace 404; **adding a paper adds its node + trail edge**; **removing a paper drops its node + edges**; **rejecting an edge removes it, keeps the node**; persisted to the workspace row. |
| `test_migrations.py` (+1) | 1 | `graph_json` present after upgrade to head, gone after downgrade to `0011`. |

Maps to the user's brief test list: graph construction, node/edge
deduplication, trail-to-graph projection, workspace isolation, add/remove
paper updates, deleted/rejected edges, deterministic serialization,
persistence and migration, and API behavior.

---

## Acceptance criteria

| Criterion (this phase's brief) | State |
|---|---|
| Per-workspace `ResearchGraph` model and persistence | **Met** -- `app/domain/graph.py`, `workspaces.graph_json`. |
| Nodes for workspace papers | **Met** -- one `PAPER` node per `workspace_papers` row. |
| Edges from typed research-trail relationships | **Met** -- total, grounded `RelationshipType -> GraphEdgeType` mapping. |
| Graph projection from accepted/relevant workspace evidence | **Met** -- rejected edges and edges to non-member papers excluded. |
| Deterministic graph construction | **Met** -- sorted inputs/outputs; byte-identical reruns verified. |
| Graph update when papers/edges change | **Met** -- rebuild-on-read against live DB state; verified for add, remove, and reject. |
| Graph serialization/query interface | **Met** -- `ResearchGraph.model_dump`/`model_validate` (serialization) + `GraphQuery` (typed lookups/adjacency). |
| Workspace-scoped graph API | **Met** -- `GET /workspaces/{id}/graph`, tenant-isolated. |
| Foundation for later GraphRAG/theme queries | **Met** -- full `GraphNodeType`/`GraphEdgeType` vocabulary fixed now; `GraphQuery` has room to grow traversal methods without changing the persisted schema. |
| No invented nodes/relationships; every edge traces to a Phase 7 `TrailEdge` | **Met** -- see Guarantees. |
| Tenant isolation preserved | **Met**. |

---

## Deferred / explicitly out of scope

- **GraphRAG routing / `mode:"themes"` chat routing** -- Phase 14+, per
  explicit instruction this phase.
- **Method/Dataset/Topic/ResearchQuestion/Claim/Gap/Direction node
  projection** (profiles, gaps, directions as graph inputs) -- the
  vocabulary is reserved (`GraphNodeType`/`GraphEdgeType` already cover
  all 8/10 values) but not populated; this phase's brief scoped edges to
  "existing Phase 7 TrailEdge/evidence" only.
- **`networkx` dependency** -- deferred to the phase that implements real
  graph traversal; see "Design decisions" above.
- **Node/edge count bounding, user correction of a node persisting** --
  in the Roadmap's full Phase 13 description but not in this phase's
  brief or test list; would matter once entity-extraction nodes exist.
- **UI / orchestrator hardening** -- never in scope for this phase.

---

## Traceability

Continues the *IEEE BigData 2024 limitation -> ResearchNexus solution ->
evidence* chain: the source paper's meta-analysis has no auditable
structure connecting its papers, methods, and gaps. `ResearchGraph` is
that explicit structure -- but only for what is already verified: a node
is never anything but a real workspace paper, and an edge is never
anything but a labelled, evidence-carrying Phase 7 `TrailEdge` the user
has not rejected. It is intentionally *not* a knowledge graph built by
extracting new entities from text (Architecture §5's "no global knowledge
graph in the MVP" rationale) -- it is small, inspectable, and correctable,
and it is the projection Phase 11's gap matrix and any future GraphRAG
routing build on top of.

---

## Files changed

**New**

- `app/domain/graph.py`
- `app/services/graph/{__init__,builder,query}.py`
- `migrations/versions/0012_workspace_graph.py`
- `tests/unit/test_graph_{domain,builder,query}.py`
- `tests/unit/test_db_repository_graph.py`
- `tests/integration/test_workspace_graph_api.py`

**Modified**

- `app/db/models.py` -- `WorkspaceORM.graph_json`.
- `app/db/repository.py` -- `set_workspace_graph` / `get_workspace_graph`.
- `app/services/workspace/pipeline.py` -- `get_graph`.
- `app/routers/workspaces.py` -- `GET /{workspace_id}/graph`.
- `tests/unit/test_migrations.py` -- assert `graph_json` on upgrade / gone on downgrade to `0011`.
- `pyproject.toml` -- description bumped to "Phases 1-13".

**Not committed** -- per this phase's instruction, all changes above are
in the working tree only.
