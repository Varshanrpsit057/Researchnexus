# ResearchNexus — Data Model

**Purpose.** Production-ready domain schemas (Pydantic v2) and the normalized relational model. **Design only — no application code is created here and nothing is migrated yet.**

**Companions:** `ResearchNexus_Implementation_Architecture.md`, `ResearchNexus_API_Specification.md`, `ResearchNexus_Implementation_Roadmap.md`, `docs/evaluation/ResearchNexus_Evaluation_Plan.md`, `ResearchNexus_Seed_Paper_Research_Trail.md`.

**Conventions**
- IDs: string ULIDs (`ws_...`, `pap_...`, `chk_...`, `gap_...`, `dir_...`, `edge_...`, `run_...`, `job_...`). Rationale: sortable, URL-safe, no central sequence.
- Timestamps: UTC, ISO-8601, `*_at`.
- **Tenant isolation:** every workspace-scoped row carries `owner_id`; every query filters by it; Postgres deployment adds Row-Level Security as defence-in-depth.
- **Provenance is mandatory** for anything an LLM produced from a document: a `SourceSpan` (paper_id + section + page + char range + quote).
- **No fabricated scores.** Every numeric score is defined below with its meaning and range; bands (`high/medium/low`) are derived from thresholds fixed on a validation set, never invented percentages *[review §11, §18]*.
- LLM output is **always** parsed into these models and validated; invalid → one `schema_repair` retry → typed failure (`task §5`).

---

## 1. Shared value objects

```python
from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime

class SourceSpan(BaseModel):
    paper_id: str
    section: str | None = None          # e.g. "abstract", "4.2 Method"
    page: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    quote: str                          # verbatim text at the span (<= 400 chars)

class ProvenanceStatus(str, Enum):
    verified = "verified"               # quote found in the source text (fuzzy match passed)
    unverified = "unverified"           # LLM produced it but the span could not be confirmed
    user_edited = "user_edited"         # a human overrode the value

class Confidence(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"

class Money(BaseModel):
    usd: float = 0.0

class TokenUsage(BaseModel):
    prompt: int = 0
    completion: int = 0
```

---

## 2. ResearchProfile (Stage S4)

Production schema. Every substantive field is a `ProfileField` carrying its value + provenance + status, so the UI can show "source" links and the gap engine can down-weight `unverified`/abstract-only fields.

```python
class ProfileField(BaseModel):
    value: str
    source_span: SourceSpan | None = None
    status: ProvenanceStatus = ProvenanceStatus.unverified

class ProfileList(BaseModel):
    items: list[ProfileField] = Field(default_factory=list)

class ResearchProfile(BaseModel):
    profile_id: str
    paper_id: str
    workspace_id: str | None = None     # null = the seed's canonical profile
    grounding: str                      # "full_text" (seed) | "abstract" (discovered)

    # --- bibliographic (deterministic, not LLM) ---
    title: str
    abstract: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None

    # --- understanding (LLM-extracted, validated, provenance-checked) ---
    domain: ProfileField
    subdomains: ProfileList
    research_problem: ProfileField
    research_questions: ProfileList
    objectives: ProfileList
    keywords: list[str] = Field(default_factory=list)         # short strings; no provenance needed
    methods: ProfileList
    models: ProfileList
    algorithms: ProfileList
    datasets: ProfileList
    evaluation_metrics: ProfileList                            # metric names / protocols reported
    findings: ProfileList
    limitations: ProfileList
    future_work: ProfileList
    important_entities: ProfileList                            # named systems/benchmarks/tools/concepts
    cited_methods: ProfileList                                 # prior methods the paper builds on

    # --- derived for discovery ---
    candidate_search_queries: list[str] = Field(default_factory=list)   # seeds S5

    extraction_confidence: Confidence = Confidence.low
    extraction_model: str | None = None                        # provider/model id used
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    created_at: datetime
    updated_at: datetime
```

**Validation rules (in `services/profile/validator.py` + `provenance_check.py`):**
- `title`, `abstract` non-empty; `year` in `[1950, current_year+1]` or `None`.
- Each `ProfileField.source_span.quote` must fuzzy-match (`ratio >= 0.9`) a substring of the paper text; else `status = unverified`.
- `extraction_confidence` = `high` iff ≥ 80 % of `ProfileField`s verified **and** an explicit *Limitations* or *Future Work* section was found; `medium` iff ≥ 50 %; else `low`.
- `keywords` deduplicated, lowercased, length 1–5 words each, max 25.
- On any `ValidationError` after the single repair retry → return a `ResearchProfile` with the bibliographic fields filled, understanding fields empty, `extraction_confidence = low`, and a `profile_extraction_failed` flag surfaced to the UI for manual entry.

---

## 3. PaperCandidate (Stages S6–S8) and SearchRun

```python
class DiscoveryStrategy(str, Enum):
    keyword = "keyword"
    semantic = "semantic"                 # chunk-level
    semantic_doc = "semantic_doc"         # SPECTER2 document-level
    query_expansion = "query_expansion"
    citation = "citation"
    method = "method"
    topic = "topic"
    research_question = "research_question"

class CitationRelationship(str, Enum):
    cited_by_seed = "cited_by_seed"       # seed -> candidate (out-edge)
    cites_seed = "cites_seed"             # candidate -> seed (in-edge)
    co_cited = "co_cited"
    none = "none"

class RawSignalScores(BaseModel):
    # each in [0,1] AFTER per-strategy min-max normalisation within a run; meaning documented per field
    semantic_score: float | None = None      # max cosine(seed chunk emb, candidate abstract chunk emb)
    semantic_doc_score: float | None = None   # cosine(SPECTER2(seed), SPECTER2(candidate))
    keyword_score: float | None = None        # BM25 score of candidate vs seed query set, normalised
    method_score: float | None = None         # cosine(profile.methods emb, candidate method text emb)
    topic_score: float | None = None          # cosine(profile.domain+subdomains emb, candidate emb)
    rq_score: float | None = None             # cosine(profile.research_questions emb, candidate emb)
    recency_score: float | None = None        # exp(-(now_year - year)/H), H default 4.0

class PaperCandidate(BaseModel):
    candidate_id: str
    run_id: str
    # identity / bibliographic (normalised from arXiv/OpenAlex/S2/Crossref)
    external_ids: dict[str, str] = Field(default_factory=dict)   # {"doi":..., "arxiv":..., "openalex":..., "s2":...}
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    abstract: str | None = None
    venue: str | None = None
    url: str | None = None
    # discovery bookkeeping
    discovery_methods: list[DiscoveryStrategy]                    # accumulated across strategies after dedupe
    citation_relationship: CitationRelationship = CitationRelationship.none
    citation_hops: int | None = None                             # 1 or 2 (citation strategy only)
    raw_signals: RawSignalScores = Field(default_factory=RawSignalScores)
    preliminary_rank: int | None = None                          # rank by max raw signal, pre-fusion
    possible_duplicate_of: str | None = None
    filter_kept: bool = True
    filter_reasons: list[str] = Field(default_factory=list)

class SearchRun(BaseModel):
    run_id: str
    workspace_id: str | None
    seed_paper_id: str
    strategies_requested: list[DiscoveryStrategy]
    strategies_succeeded: list[DiscoveryStrategy]
    strategies_failed: list[DiscoveryStrategy]
    filters: dict                                                 # {max_results, date_from, date_to, domains}
    extra_citation_hop_used: bool = False
    candidate_count_raw: int
    candidate_count_after_dedupe: int
    candidate_count_after_filter: int
    started_at: datetime
    finished_at: datetime | None = None
    tokens: TokenUsage = Field(default_factory=TokenUsage)
```

**Score meaning is documented, not fabricated.** `raw_signals.*` are only populated by the strategy that can compute them; `None` means "not computed by any strategy", which the ranker handles by renormalising weights.

---

## 4. Ranking (Stage S9–S10)

```python
class RankingWeights(BaseModel):
    """INITIAL EXPERIMENTAL VALUES — chosen from the literature review, to be tuned on an RN
    validation set (see Evaluation Plan A1-A6). NOT empirically optimal yet."""
    version: str = "w0-initial"
    semantic_doc: float = 0.28     # doc-level similarity is the strongest single scholarly signal [SPECTER2, LitSearch]
    semantic_chunk: float = 0.14
    problem_sim: float = 0.18      # "same problem" is the review's #1 typed-trail signal [review §11-12]
    method_sim: float = 0.14
    dataset_overlap: float = 0.08
    citation: float = 0.12         # capped: citation signal carries popularity/recency bias [CitationNet-LLM]
    recency: float = 0.06
    # sum = 1.00

class SignalScores(BaseModel):
    semantic_doc: float | None = None
    semantic_chunk: float | None = None
    problem_sim: float | None = None
    method_sim: float | None = None
    dataset_overlap: float | None = None
    citation: float | None = None
    recency: float | None = None

class RankingExplanation(BaseModel):
    bullet_reasons: list[str]       # each maps to a signal above its display threshold
    prose: str                      # one sentence; LLM rephrase of the bullets, must cite a span from each paper
    signals_used: list[str]
    template_only: bool = False     # true if the LLM rephrase failed and only the deterministic template is shown

class RankedPaper(BaseModel):
    candidate_id: str
    signals: SignalScores           # the ACTUAL per-signal values (retained; shown on expand)
    weights_version: str
    fused_score: float              # sum(w_i * signal_i) over available signals, weights renormalised
    rerank_score: float | None = None   # cross-encoder score for the top slice (else None)
    final_rank: int
    band: Confidence                # threshold-derived from fused/rerank score on a validation set
    explanation: RankingExplanation
```

**Fusion (`services/ranking/fuse.py`, deterministic):**
`fused = Σ_{i in available} (w_i / Σ_{j in available} w_j) * signal_i`. Cross-encoder rerank is applied to the top `RERANK_TOP_N` (default 50); `final_rank` orders by `rerank_score` where present, else `fused_score`. `band` cutoffs are config (`RANK_BAND_HIGH`, `RANK_BAND_MED`) calibrated in evaluation, **never** shown as a percentage.

---

## 5. Typed research trail (Stage S11)

```python
class RelationshipType(str, Enum):
    SIMILAR = "SIMILAR"
    FOUNDATIONAL = "FOUNDATIONAL"
    RECENT = "RECENT"
    COMPETING = "COMPETING"
    METHOD_EXTENSION = "METHOD_EXTENSION"
    DATASET_RELATED = "DATASET_RELATED"
    POTENTIALLY_CONTRADICTORY = "POTENTIALLY_CONTRADICTORY"

class DetectionMethod(str, Enum):
    rule = "rule"                     # deterministic rule fired
    rule_llm_confirmed = "rule_llm_confirmed"
    contradiction_nli = "contradiction_nli"
    user = "user"

class Evidence(BaseModel):
    span: SourceSpan
    role: str                        # "seed_claim" | "target_claim" | "shared_dataset" | "citation" | ...

class TrailEdge(BaseModel):
    edge_id: str
    workspace_id: str
    source_paper_id: str             # always the seed at trail-build time
    target_paper_id: str
    relationship_type: RelationshipType
    detection_method: DetectionMethod
    rule_fired: str | None = None    # e.g. "shared_dataset AND method_sim<0.45"
    llm_confirmed: bool = False
    evidence: list[Evidence]         # >=1; POTENTIALLY_CONTRADICTORY requires a span from BOTH papers
    supporting_references: list[str] = Field(default_factory=list)  # candidate_ids / paper_ids used as support
    confidence: Confidence
    confidence_basis: dict           # {signal_agreement:int, evidence_complete:bool, recency:str, llm_certainty:str}
    user_state: str = "pending"      # "pending" | "accepted" | "rejected"
    created_at: datetime
```

**Rule → confirm → confidence** (deterministic rules in `trail/rules.py`, one batched LLM confirmation per type, deterministic band). `POTENTIALLY_CONTRADICTORY` is **never** created without a quotable span from both papers *[SciFact, PaperQA2/ContraCrow; task §8]*. A target paper may have multiple `TrailEdge`s.

---

## 6. PaperChunk (Stages S3, S13, RAG)

```python
class PaperChunk(BaseModel):
    chunk_id: str
    paper_id: str
    workspace_id: str | None = None   # null for the seed's own per-paper index
    section: str | None = None
    section_order: int | None = None
    page: int | None = None
    char_start: int
    char_end: int
    kind: str = "body"                # "body" | "table" | "figure_caption" | "abstract"
    text: str
    token_count: int
    embedding_ref: str                # (faiss_index_path, row_id)
```

Every retrieved chunk resolves back to `{workspace_id, paper_id, section, page, chunk_id, text}` for citation grounding *[task §10]*.

---

## 7. ResearchWorkspace (Stage S13)

```python
class WorkspacePaper(BaseModel):
    workspace_id: str
    paper_id: str
    added_by: str                    # "trail" | "manual"
    role: str = "related"            # "seed" | "related"
    grounding: str = "abstract"      # "full_text" | "abstract"
    pinned: bool = False
    tags: list[str] = Field(default_factory=list)
    note: str | None = None
    order: int = 0
    ranking_snapshot: RankedPaper | None = None
    added_at: datetime

class ComparisonSchema(BaseModel):
    columns: list[str]               # union of method/model/dataset/metric aspects across workspace profiles
    generated_by: str                # "deterministic_union" | "llm_schema" (ArxivDIGESTables-style)

class ResearchWorkspace(BaseModel):
    workspace_id: str
    owner_id: str
    title: str
    seed_paper_id: str
    seed_profile_id: str
    papers: list[WorkspacePaper]
    combined_index_path: str | None = None
    graph_json_ref: str | None = None            # research graph (Section 11)
    comparison_schema: ComparisonSchema | None = None
    token_budget_usd: float = 5.0
    tokens_used: TokenUsage = Field(default_factory=TokenUsage)
    cost_used: Money = Field(default_factory=Money)
    created_at: datetime
    updated_at: datetime
```

Supported operations (API doc §Workspaces): add / remove / reorder / pin / tag / annotate paper; regenerate any artefact; persist state. Removing/adding a paper triggers incremental rebuild of `combined_index_path` and `graph_json_ref` and invalidates dependent `artefacts`.

---

## 8. ResearchGap (Stage: gap workflow — a key contribution area)

```python
class GapType(str, Enum):
    METHOD_GAP = "METHOD_GAP"
    DATASET_GAP = "DATASET_GAP"
    EVALUATION_GAP = "EVALUATION_GAP"
    DOMAIN_GAP = "DOMAIN_GAP"
    PERFORMANCE_GAP = "PERFORMANCE_GAP"
    GENERALIZATION_GAP = "GENERALIZATION_GAP"
    CONTRADICTION = "CONTRADICTION"
    UNEXPLORED_COMBINATION = "UNEXPLORED_COMBINATION"
    TEMPORAL_GAP = "TEMPORAL_GAP"

class GapEvidence(BaseModel):
    paper_id: str
    span: SourceSpan
    role: str                        # "supports_gap" | "conflicts_with_gap" | "shared_context"

class ResearchGap(BaseModel):
    gap_id: str
    workspace_id: str
    statement: str                   # LLM-phrased, constrained to attached evidence
    gap_type: GapType
    supporting_papers: list[str]     # >= 2 required or the candidate is dropped
    supporting_evidence: list[GapEvidence]
    conflicting_evidence: list[GapEvidence] = Field(default_factory=list)
    why_unaddressed: str             # LLM, from evidence only
    affected_methods: list[str] = Field(default_factory=list)
    affected_datasets: list[str] = Field(default_factory=list)
    evidence_coverage: float         # fraction of supporting_papers with a full-text-grounded span, [0,1]
    novelty_assessment: str          # "under-addressed in this workspace" — scoped claim, not a global one
    confidence: Confidence
    confidence_basis: dict           # {n_supporting:int, limitation_agreement:bool, recency:str, self_support:bool}
    proposed_direction: str          # short; a full ResearchDirection is generated on user acceptance
    detection_rule: str              # which deterministic rule produced the candidate
    self_support_passed: bool        # Self-RAG-style IsSupported? over (statement, evidence)
    user_state: str = "candidate"    # "candidate" | "accepted" | "rejected"
    generated_at: datetime
    generator_model: str | None = None
```

**Pipeline (enforced in code order):** discover (matrix) → retrieve evidence → extract claims → compare papers → identify differences/absences → verify (`self_support_passed`, `>=2` supporting papers) → create object → assign `confidence` band → short `proposed_direction`. The LLM **cannot** introduce a gap not derivable from the matrix + evidence *[RA-FSM; task §12]*.

---

## 9. ResearchDirection

```python
class ResearchDirection(BaseModel):
    direction_id: str
    workspace_id: str
    gap_id: str                      # every direction is tied to an accepted gap
    proposal: str
    motivation: str                  # cites the gap's evidence
    supporting_evidence: list[GapEvidence]
    related_papers: list[str]
    suggested_method: str
    possible_dataset: str | None = None
    evaluation_strategy: str
    risks: list[str]
    kind: str                        # "evidence_backed_inference" | "llm_hypothesis"  -- MUST be labelled
    critique: dict                   # {novelty:int, specificity:int, feasibility:int, groundedness:int} 1-5
    confidence: Confidence           # feasibility is explicitly uncertain [Si et al.]
    generated_at: datetime
```

`kind` is mandatory and surfaced in the UI: an inference the evidence supports vs an LLM-proposed hypothesis. Directions are **never** presented as established facts *[task §13]*.

---

## 10. Citation & Claim

```python
class Citation(BaseModel):
    citation_id: str
    workspace_id: str
    paper_id: str
    csl_json: dict                   # canonical metadata from Crossref/OpenAlex/arXiv
    formatted: dict[str, str]        # {"apa": "...", "ieee": "...", "bibtex": "..."} -- DETERMINISTICALLY built
    resolved_from: str               # "crossref" | "openalex" | "arxiv" | "unresolved"

class Claim(BaseModel):
    claim_id: str
    workspace_id: str
    artefact_kind: str               # "answer" | "summary" | "comparison_cell" | "gap_statement" | "direction"
    artefact_id: str
    sentence: str
    supporting_chunk_ids: list[str]  # >=1 or the sentence is dropped/flagged
    supporting_paper_ids: list[str]
    is_supported: bool               # Self-RAG-style check
    citation_precision: float | None = None   # ALCE-style, set by eval runs
    citation_recall: float | None = None
```

**Invariant:** no `Claim` is rendered to the user with `supporting_chunk_ids == []`. Reference strings live only in `Citation.formatted`, built by `services/citations/formatter.py` — **the LLM never emits them** *[OpenScholar 78–90 % hallucination; task §14]*.

---

## 11. ResearchGraph (per workspace)

```python
class GraphNodeType(str, Enum):
    PAPER = "PAPER"; METHOD = "METHOD"; DATASET = "DATASET"; TOPIC = "TOPIC"
    RESEARCH_QUESTION = "RESEARCH_QUESTION"; CLAIM = "CLAIM"; GAP = "GAP"; DIRECTION = "DIRECTION"

class GraphEdgeType(str, Enum):
    SIMILAR = "SIMILAR"; CITES = "CITES"; EXTENDS = "EXTENDS"
    USES_METHOD = "USES_METHOD"; USES_DATASET = "USES_DATASET"
    COMPETES_WITH = "COMPETES_WITH"; SUPPORTS = "SUPPORTS"; CONTRADICTS = "CONTRADICTS"
    ADDRESSES = "ADDRESSES"; EXPOSES_GAP = "EXPOSES_GAP"

class ResearchGraph(BaseModel):
    workspace_id: str
    nodes: list[dict]                # {id, type: GraphNodeType, label, paper_ids:[...], span: SourceSpan|None}
    edges: list[dict]                # {src, dst, type: GraphEdgeType, evidence:[SourceSpan], confidence}
    built_at: datetime
    node_count: int
    edge_count: int
```

Stored as JSON on the workspace (`graph_json_ref`); built with `networkx` in memory. **No global knowledge graph** in the MVP — rationale in `ResearchNexus_Implementation_Architecture.md` §5.

---

## 12. Jobs (async)

```python
class JobKind(str, Enum):
    ingest = "ingest"; profile = "profile"; discover = "discover"
    rank = "rank"; trail = "trail"; gaps = "gaps"; directions = "directions"; index_rebuild = "index_rebuild"

class JobStatus(str, Enum):
    queued = "queued"; running = "running"; succeeded = "succeeded"; failed = "failed"; partial = "partial"

class Job(BaseModel):
    job_id: str
    owner_id: str
    workspace_id: str | None
    kind: JobKind
    status: JobStatus
    progress: dict                   # {"semantic": "done", "citation": "running", ...}
    result_ref: str | None = None    # id of the produced artefact / run
    error: str | None = None
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    cost: Money = Field(default_factory=Money)
    created_at: datetime
    updated_at: datetime
```

---

## 13. Relational schema

SQLite (MVP) / PostgreSQL (research/prod). SQLAlchemy 2.0 ORM in `app/db/models.py`; migrations via Alembic. JSON columns are `JSON` (SQLite) / `JSONB` (Postgres). **Every workspace-scoped table has `owner_id` and is filtered by it in every query.**

### users
| column | type | notes |
|---|---|---|
| `id` | text | PK (`usr_...`) |
| `email` | text | UNIQUE, NOT NULL |
| `auth_provider` | text | e.g. "cognito", "local" |
| `auth_subject` | text | provider subject id; UNIQUE(`auth_provider`,`auth_subject`) |
| `created_at` | timestamptz | |
Indexes: `ux_users_email`.

### api_keys  (BYOK — ciphertext only)
| column | type | notes |
|---|---|---|
| `id` | text | PK |
| `owner_id` | text | FK → users.id, ON DELETE CASCADE |
| `provider` | text | enum: openai\|groq\|deepseek\|openrouter\|together\|gemini (fixed list — SSRF) |
| `key_ciphertext` | bytea | envelope-encrypted; **plaintext never stored/logged** |
| `key_last4` | text | for display only |
| `status` | text | "unverified"\|"working"\|"failed" |
| `checked_at` | timestamptz | last connection test |
| `created_at` | timestamptz | |
Constraints: `UNIQUE(owner_id, provider)`. Index: `ix_api_keys_owner`.

### papers  (global, de-duplicated; not tenant-scoped — content is public metadata)
| column | type | notes |
|---|---|---|
| `id` | text | PK (`pap_...`) |
| `doi` | text | NULLABLE; UNIQUE where not null |
| `arxiv_id` | text | NULLABLE; UNIQUE where not null |
| `openalex_id` | text | NULLABLE |
| `s2_id` | text | NULLABLE |
| `title` | text | NOT NULL |
| `title_hash` | text | normalised-title hash; INDEX (dedupe) |
| `authors` | json | list[str] |
| `year` | int | NULLABLE |
| `venue` | text | NULLABLE |
| `publisher` | text | NULLABLE |
| `url` | text | NULLABLE |
| `abstract` | text | NULLABLE |
| `has_full_text` | bool | true once a PDF is parsed |
| `pdf_path` | text | object-storage key; NULLABLE |
| `pdf_sha256` | text | NULLABLE; INDEX |
| `page_count` | int | NULLABLE |
| `parse_confidence` | text | "high"\|"medium"\|"low"\|null |
| `source` | text | "upload"\|"arxiv"\|"discovery" |
| `created_at` | timestamptz | |
Indexes: `ux_papers_doi`, `ux_papers_arxiv`, `ix_papers_title_hash`, `ix_papers_sha256`.

### research_profiles
| column | type | notes |
|---|---|---|
| `id` | text | PK (`prof_...`) |
| `paper_id` | text | FK → papers.id, ON DELETE CASCADE |
| `workspace_id` | text | FK → workspaces.id NULLABLE (null = canonical seed profile) |
| `owner_id` | text | FK → users.id (null when canonical & unowned; else set) |
| `grounding` | text | "full_text"\|"abstract" |
| `profile_json` | json | the `ResearchProfile` model |
| `extraction_confidence` | text | high\|medium\|low |
| `extraction_model` | text | provider/model id |
| `created_at` / `updated_at` | timestamptz | |
Constraints: `UNIQUE(paper_id, workspace_id)`. Indexes: `ix_profiles_paper`, `ix_profiles_workspace`.

### workspaces
| column | type | notes |
|---|---|---|
| `id` | text | PK (`ws_...`) |
| `owner_id` | text | FK → users.id, ON DELETE CASCADE; INDEX |
| `title` | text | NOT NULL |
| `seed_paper_id` | text | FK → papers.id |
| `seed_profile_id` | text | FK → research_profiles.id |
| `combined_index_path` | text | NULLABLE |
| `graph_json` | json | the `ResearchGraph`; NULLABLE |
| `comparison_schema` | json | NULLABLE |
| `token_budget_usd` | numeric | default 5.00 |
| `tokens_prompt` / `tokens_completion` | bigint | running totals |
| `cost_usd` | numeric | running total |
| `created_at` / `updated_at` | timestamptz | |

### workspace_papers
| column | type | notes |
|---|---|---|
| `workspace_id` | text | FK → workspaces.id, ON DELETE CASCADE |
| `paper_id` | text | FK → papers.id |
| `owner_id` | text | FK → users.id (denormalised for RLS/tenant filter) |
| `added_by` | text | "trail"\|"manual" |
| `role` | text | "seed"\|"related" |
| `grounding` | text | "full_text"\|"abstract" |
| `pinned` | bool | default false |
| `tags` | json | list[str] |
| `note` | text | NULLABLE |
| `order` | int | default 0 |
| `ranking_snapshot` | json | `RankedPaper` at add time; NULLABLE |
| `added_at` | timestamptz | |
PK: `(workspace_id, paper_id)`. Index: `ix_wp_owner`.

### paper_chunks
| column | type | notes |
|---|---|---|
| `id` | text | PK (`chk_...`) |
| `paper_id` | text | FK → papers.id, ON DELETE CASCADE |
| `workspace_id` | text | FK → workspaces.id NULLABLE (null = per-paper seed index) |
| `section` | text | NULLABLE |
| `section_order` | int | NULLABLE |
| `page` | int | NULLABLE |
| `char_start` / `char_end` | int | |
| `kind` | text | "body"\|"table"\|"figure_caption"\|"abstract" |
| `text` | text | NOT NULL |
| `token_count` | int | |
| `faiss_index_path` | text | which index file |
| `faiss_row_id` | bigint | row in that index |
Indexes: `ix_chunks_paper`, `ix_chunks_workspace`, `ux_chunks_index_row (faiss_index_path, faiss_row_id)`.

### search_runs
| column | type | notes |
|---|---|---|
| `id` | text | PK (`run_...`) |
| `owner_id` | text | FK → users.id; INDEX |
| `workspace_id` | text | FK → workspaces.id NULLABLE |
| `seed_paper_id` | text | FK → papers.id |
| `strategies_requested` / `_succeeded` / `_failed` | json | list[str] |
| `filters` | json | |
| `extra_citation_hop_used` | bool | |
| `counts` | json | {raw, after_dedupe, after_filter} |
| `tokens_prompt` / `tokens_completion` | int | |
| `started_at` / `finished_at` | timestamptz | |

### search_candidates
| column | type | notes |
|---|---|---|
| `id` | text | PK (`cand_...`) |
| `run_id` | text | FK → search_runs.id, ON DELETE CASCADE; INDEX |
| `paper_id` | text | FK → papers.id (created/linked during normalisation) |
| `discovery_methods` | json | list[str] |
| `citation_relationship` | text | enum |
| `citation_hops` | int | NULLABLE |
| `raw_signals` | json | `RawSignalScores` |
| `preliminary_rank` | int | NULLABLE |
| `possible_duplicate_of` | text | NULLABLE |
| `filter_kept` | bool | |
| `filter_reasons` | json | list[str] |
Constraint: `UNIQUE(run_id, paper_id)`.

### ranked_papers   (result of S9–S10, per run)
| column | type | notes |
|---|---|---|
| `id` | text | PK |
| `run_id` | text | FK → search_runs.id, ON DELETE CASCADE |
| `paper_id` | text | FK → papers.id |
| `signals` | json | `SignalScores` (actual values retained) |
| `weights_version` | text | e.g. "w0-initial" |
| `fused_score` | numeric | |
| `rerank_score` | numeric | NULLABLE |
| `final_rank` | int | |
| `band` | text | high\|medium\|low |
| `explanation` | json | `RankingExplanation` |
Index: `ix_ranked_run_rank (run_id, final_rank)`.

### paper_relationships   (the typed trail)
| column | type | notes |
|---|---|---|
| `id` | text | PK (`edge_...`) |
| `workspace_id` | text | FK → workspaces.id, ON DELETE CASCADE; INDEX |
| `owner_id` | text | FK → users.id |
| `source_paper_id` | text | FK → papers.id (the seed at build time) |
| `target_paper_id` | text | FK → papers.id |
| `relationship_type` | text | enum (7 values) |
| `detection_method` | text | rule\|rule_llm_confirmed\|contradiction_nli\|user |
| `rule_fired` | text | NULLABLE |
| `llm_confirmed` | bool | |
| `evidence` | json | list[Evidence] |
| `supporting_references` | json | list[paper_id] |
| `confidence` | text | high\|medium\|low |
| `confidence_basis` | json | |
| `user_state` | text | pending\|accepted\|rejected |
| `created_at` | timestamptz | |
Constraint: `UNIQUE(workspace_id, source_paper_id, target_paper_id, relationship_type)`.

### research_gaps
| column | type | notes |
|---|---|---|
| `id` | text | PK (`gap_...`) |
| `workspace_id` | text | FK → workspaces.id, ON DELETE CASCADE; INDEX |
| `owner_id` | text | FK → users.id |
| `statement` | text | |
| `gap_type` | text | enum (9 values) |
| `supporting_papers` | json | list[paper_id] (len ≥ 2) |
| `supporting_evidence` | json | list[GapEvidence] |
| `conflicting_evidence` | json | list[GapEvidence] |
| `why_unaddressed` | text | |
| `affected_methods` / `affected_datasets` | json | list[str] |
| `evidence_coverage` | numeric | [0,1] |
| `novelty_assessment` | text | scoped to the workspace |
| `confidence` | text | high\|medium\|low |
| `confidence_basis` | json | |
| `proposed_direction` | text | short |
| `detection_rule` | text | |
| `self_support_passed` | bool | |
| `user_state` | text | candidate\|accepted\|rejected |
| `generator_model` | text | |
| `generated_at` | timestamptz | |

### research_directions
| column | type | notes |
|---|---|---|
| `id` | text | PK (`dir_...`) |
| `workspace_id` | text | FK → workspaces.id, ON DELETE CASCADE |
| `owner_id` | text | FK → users.id |
| `gap_id` | text | FK → research_gaps.id, ON DELETE CASCADE |
| `proposal` / `motivation` / `suggested_method` / `evaluation_strategy` | text | |
| `possible_dataset` | text | NULLABLE |
| `supporting_evidence` | json | list[GapEvidence] |
| `related_papers` | json | list[paper_id] |
| `risks` | json | list[str] |
| `kind` | text | "evidence_backed_inference"\|"llm_hypothesis" (mandatory) |
| `critique` | json | {novelty,specificity,feasibility,groundedness} 1–5 |
| `confidence` | text | high\|medium\|low |
| `generated_at` | timestamptz | |

### citations
| column | type | notes |
|---|---|---|
| `id` | text | PK (`cit_...`) |
| `workspace_id` | text | FK → workspaces.id, ON DELETE CASCADE |
| `owner_id` | text | FK → users.id |
| `paper_id` | text | FK → papers.id |
| `csl_json` | json | canonical metadata |
| `formatted` | json | {apa, ieee, bibtex} — deterministically built |
| `resolved_from` | text | crossref\|openalex\|arxiv\|unresolved |
Constraint: `UNIQUE(workspace_id, paper_id)`.

### claims   (grounding audit trail)
| column | type | notes |
|---|---|---|
| `id` | text | PK |
| `workspace_id` | text | FK → workspaces.id, ON DELETE CASCADE; INDEX |
| `artefact_kind` | text | answer\|summary\|comparison_cell\|gap_statement\|direction |
| `artefact_id` | text | id of the artefact/message |
| `sentence` | text | |
| `supporting_chunk_ids` | json | list[chunk_id] (len ≥ 1) |
| `supporting_paper_ids` | json | list[paper_id] |
| `is_supported` | bool | |
| `citation_precision` / `citation_recall` | numeric | NULLABLE (set by eval) |

### chat_sessions / chat_messages
`chat_sessions(id PK, workspace_id FK, owner_id FK, title, created_at)`.
`chat_messages(id PK, session_id FK ON DELETE CASCADE, role ['user'|'assistant'], content text, citations json [list[Claim.id]], tokens_prompt int, tokens_completion int, faithfulness numeric NULLABLE, created_at)`. Index `ix_msg_session (session_id, created_at)`.

### artefacts   (cache for summary/keypoints/compare/outline/gap-report)
`artefacts(id PK, workspace_id FK ON DELETE CASCADE, owner_id FK, kind text, content_json json, source_hash text [hash of the paper set + params], invalidated bool default false, created_at)`. Index `ix_artefacts_ws_kind (workspace_id, kind)`.

### stage_runs   (observability — Evaluation Plan)
`stage_runs(id PK, owner_id FK, workspace_id FK NULLABLE, job_id text, stage text, tool text, input_hash text, output_hash text, tokens_prompt int, tokens_completion int, cost_usd numeric, latency_ms int, ok bool, error text NULLABLE, ts timestamptz)`. Indexes `ix_stage_runs_ws_stage`, `ix_stage_runs_ts`. **No prompt/response bodies, no secrets.**

### jobs
`jobs(id PK, owner_id FK, workspace_id FK NULLABLE, kind text, status text, progress json, result_ref text, error text, tokens_prompt int, tokens_completion int, cost_usd numeric, created_at, updated_at)`. Index `ix_jobs_owner_status`.

---

## 14. Entity-relationship overview

```
users ──1:N── api_keys
users ──1:N── workspaces ──1:1── papers            (seed_paper_id)
                     │        └── research_profiles (seed_profile_id)
workspaces ──1:N── workspace_papers ──N:1── papers
workspaces ──1:N── paper_relationships (source=seed, target ∈ workspace_papers)
workspaces ──1:N── paper_chunks ──N:1── papers
workspaces ──1:N── research_gaps ──1:N── research_directions
workspaces ──1:N── citations ──N:1── papers
workspaces ──1:N── chat_sessions ──1:N── chat_messages
workspaces ──1:N── artefacts
users ──1:N── search_runs ──1:N── search_candidates ──N:1── papers
              search_runs ──1:N── ranked_papers ──N:1── papers
papers ──1:N── research_profiles   (one canonical + one per workspace where re-grounded)
* ──── stage_runs / jobs           (telemetry & async, reference owner_id + optional workspace_id)
```

---

## 15. Migration approach

- **Alembic**, one migration per roadmap phase that adds tables (see `ResearchNexus_Implementation_Roadmap.md`): P1 `users, api_keys`; P2 `papers, paper_chunks`; P3 `research_profiles`; P4 `search_runs, search_candidates`; P5 (extends candidates); P6 `ranked_papers`; P7 `paper_relationships`; P8 `workspaces, workspace_papers, artefacts, jobs, stage_runs`; P9 `chat_sessions, chat_messages, claims`; P11 `research_gaps`; P12 `research_directions`; P13 (`workspaces.graph_json`).
- **Reversible** migrations only; `--autogenerate` reviewed by hand (never trusted blind).
- SQLite for local/CI; a Postgres CI leg from P8 onward (JSONB + partial unique indexes + RLS policies).
- Seed/fixture data (`scripts/seed_dev.py`) for a demo user + one sample seed paper — **never** in a migration.

*Design only. No tables are created and no application code is written by this document. No facial-recognition / attendance content appears anywhere.*
