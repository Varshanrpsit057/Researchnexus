/**
 * Types mirror the REAL, verified backend wire format (confirmed by reading
 * every router in backend/app/routers/*.py and every model in
 * backend/app/domain/*.py this session) -- not the aspirational
 * ResearchNexus_API_Specification.md, which diverges from the shipped
 * backend in several places noted inline below.
 */

// --- shared -----------------------------------------------------------

export type Confidence = "high" | "medium" | "low";

export interface SourceSpan {
  paper_id: string;
  section: string | null;
  page: number | null;
  char_start: number | null;
  char_end: number | null;
  quote: string;
}

export interface TokenUsage {
  prompt: number;
  completion: number;
}

// --- auth / me ----------------------------------------------------------

export interface SessionResponse {
  token: string;
  expires_at: string;
  /** a new, empty account was made for this email (absent from older servers) */
  created?: boolean;
}

export interface MeResponse {
  id: string;
  email: string;
  created_at: string;
  has_working_llm_key: boolean;
  /** The provider the user chose for every LLM stage. */
  default_provider: LlmProvider | null;
  /** The provider in use right now: the default when its key works, else the first working key saved. */
  active_provider: LlmProvider | null;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  version: string;
  checks: Record<string, string>;
}

// --- BYOK keys ------------------------------------------------------------

export type LlmProvider =
  | "openai"
  | "groq"
  | "deepseek"
  | "openrouter"
  | "together"
  | "gemini";

export type ApiKeyStatus = "unverified" | "working" | "failed";

export interface ApiKeySummary {
  provider: LlmProvider;
  status: ApiKeyStatus;
  key_last4: string;
  checked_at: string | null;
}

export interface LlmCapabilities {
  json_mode: boolean;
  context_tokens: number;
  streaming: boolean;
}

export interface LlmTestResult {
  success: boolean;
  latency_ms?: number;
  capabilities?: LlmCapabilities;
  message?: string;
}

/** POST .../llm-keys/{provider}/check: the stored key, probed again. */
export interface KeyCheckResponse {
  key: ApiKeySummary;
  result: LlmTestResult;
}

// --- papers ---------------------------------------------------------------

export type ParseConfidence = "high" | "medium" | "low";

export interface PaperSection {
  title: string;
  order: number;
  page_span: [number, number];
}

export interface PaperTable {
  caption: string | null;
  page: number;
}

// --- full-text coverage (remediation Phase 7) -------------------------------

/** The text a paper is read from. */
export type CoverageState = "full_text" | "abstract_only" | "retrieval_failed" | "no_text";

export interface PaperCoverage {
  state: CoverageState;
  /** Where the full text came from: arxiv, europepmc, openalex, semantic_scholar, or upload. */
  source: string | null;
  /** retrieved | unavailable | failed; null when its full text was never looked for. */
  status: "retrieved" | "unavailable" | "failed" | null;
  /** Why it isn't full text: a code (no_open_access_copy, elsewhere:<host>, not_a_pdf, http_403, ...). */
  reason: string | null;
  checked_at: string | null;
  has_abstract: boolean;
  /** Whether looking for its full text can help (a paper found by discovery). */
  retrievable: boolean;
}

export interface FullTextJob {
  job_id: string;
  kind: "fulltext";
  status: JobStatus;
  progress: Record<string, string>;
  error: string | null;
  poll_url: string;
}

export interface WorkspaceCoverage {
  papers: { paper_id: string; title: string; role: WorkspacePaperRole; coverage: PaperCoverage }[];
  summary: Record<CoverageState, number>;
  job: FullTextJob | null;
}

/** A trail built from a workspace's own papers (POST /workspaces/{id}/trail/build). */
export interface WorkspaceTrailBuild {
  run_id: string;
  papers: number;
  edges: number;
  connected_papers: number;
  unconnected_papers: number;
}

/** What a PDF given to a paper produced (POST /papers/{id}/pdf | /reread). */
export interface PaperTextOutcome {
  outcome: { chunks: number; sections: number; abstract_found: boolean; doi: string | null };
  /** the record lookup that followed a re-read: found | not_found | failed | timed_out */
  metadata: { metadata?: string; filled?: string[] };
  coverage: PaperCoverage;
}

export interface FullTextOutcome {
  outcome: { status: "retrieved" | "already" | "unavailable" | "failed" | "cached"; source: string | null; reason: string | null; chunks: number };
  coverage: PaperCoverage;
}

export interface Paper {
  id: string;
  title: string;
  authors: string[];
  year: number | null;
  venue: string | null;
  /** who published it, as readers know them ("IEEE", "Springer") */
  publisher?: string | null;
  url?: string | null;
  doi: string | null;
  arxiv_id: string | null;
  has_full_text: boolean;
  /** An uploaded PDF, or a paper found by discovery (at most its abstract). */
  source?: "upload" | "discovery";
  has_abstract?: boolean;
  /** Absent from papers served before remediation Phase 7. */
  coverage?: PaperCoverage;
  /** the signed-in reader's workspaces that hold it (absent from older servers) */
  workspaces?: { workspace_id: string; title: string }[];
  parse_confidence: ParseConfidence | null;
  page_count: number | null;
  sections: PaperSection[];
  tables: PaperTable[];
  warnings: string[];
}

/** How a paper got into the reader's library. */
export type LibraryRole = "uploaded" | "seed" | "searched" | "analyzed" | "collected";

/** One paper in the reader's library (GET /api/v1/papers). */
export interface LibraryPaper {
  id: string;
  title: string;
  authors: string[];
  year: number | null;
  venue: string | null;
  publisher: string | null;
  doi: string | null;
  source: "upload" | "discovery";
  has_abstract: boolean;
  has_full_text: boolean;
  coverage: PaperCoverage;
  /** it has a research profile */
  analyzed: boolean;
  roles: LibraryRole[];
  workspaces: { workspace_id: string; title: string }[];
  /** the latest discovery run started from it, if the reader ran one */
  last_run_id: string | null;
  last_active_at: string;
}

export interface LibraryResponse {
  papers: LibraryPaper[];
  counts: { papers: number; uploaded: number; analyzed: number; in_workspaces: number; discovery_runs: number; workspaces: number };
}

export interface UploadJobRef {
  job_id: string;
  kind: "ingest";
  status: "queued";
  poll_url: string;
}

export interface UploadResponse {
  paper_id: string;
  file: { sha256: string; size_bytes: number; page_count: number };
  job: UploadJobRef | null;
  deduplicated?: true;
}

export type ProvenanceStatus = "verified" | "unverified" | "user_edited";

/** The value a paper reports for a field (a metric's "95.83%"), verbatim.
 * "verified" only when it is written in the field's own evidence; an
 * unverified one was claimed but not found, and is never shown as a result. */
export interface ReportedValue {
  text: string;
  status: ProvenanceStatus;
}

export interface ProfileField {
  value: string;
  source_span: SourceSpan | null;
  status: ProvenanceStatus;
  reported_value?: ReportedValue | null;
}

export interface ProfileList {
  items: ProfileField[];
}

export interface ResearchProfile {
  profile_id: string;
  paper_id: string;
  workspace_id: string | null;
  grounding: string;
  title: string;
  abstract: string;
  /** False when no abstract was found and `abstract` is stand-in body text. Absent before remediation Phase 6. */
  abstract_found?: boolean;
  /** At most two of the abstract's own sentences. Absent before remediation Phase 6. */
  summary?: string;
  authors: string[];
  year: number | null;
  venue: string | null;
  doi: string | null;
  arxiv_id: string | null;
  domain: ProfileField;
  subdomains: ProfileList;
  research_problem: ProfileField;
  research_questions: ProfileList;
  objectives: ProfileList;
  keywords: string[];
  methods: ProfileList;
  models: ProfileList;
  algorithms: ProfileList;
  datasets: ProfileList;
  evaluation_metrics: ProfileList;
  findings: ProfileList;
  limitations: ProfileList;
  future_work: ProfileList;
  important_entities: ProfileList;
  cited_methods: ProfileList;
  candidate_search_queries: string[];
  extraction_confidence: Confidence;
  extraction_model: string | null;
  tokens: TokenUsage;
  created_at: string;
  updated_at: string;
}

export interface AnalyzeResponse {
  profile: ResearchProfile;
  extraction_confidence: string;
  warnings: string[];
}

// --- jobs -------------------------------------------------------------

export type JobKind =
  | "ingest"
  | "profile"
  | "discover"
  | "rank"
  | "trail"
  | "gaps"
  | "directions"
  | "index_rebuild"
  | "pipeline";

// cancelled: stopped by its owner (discovery only)
export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "partial" | "cancelled";

export interface Job {
  job_id: string;
  owner_id: string;
  workspace_id: string | null;
  kind: JobKind;
  status: JobStatus;
  progress: Record<string, string>;
  result_ref: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

// --- workspaces -------------------------------------------------------

export type WorkspacePaperRole = "seed" | "related";
export type AddedBy = "trail" | "manual";
export type Grounding = "full_text" | "abstract";

export type SignalName = keyof SignalScores;

/** One signal's part in a paper's score: weight x value (remediation Phase 9). */
export interface SignalContribution {
  signal: SignalName;
  value: number;
  /** renormalised over the signals that could be computed for this paper */
  weight: number;
  contribution: number;
}

export interface RankingExplanation {
  bullet_reasons: string[];
  prose: string;
  signals_used: string[];
  template_only: boolean;
  /** largest first; they sum to the fused score (absent on older rankings) */
  contributions?: SignalContribution[];
  missing_signals?: SignalName[];
}

/** How much each criterion counts, 0-100; only the proportions matter. */
export interface RankingCriteria {
  topic: number;
  problem: number;
  methods: number;
  datasets: number;
  citations: number;
  recency: number;
  /** papers from IEEE, Springer, ACM or Elsevier (absent from criteria saved before it existed) */
  publisher: number;
}

export interface SignalScores {
  semantic_doc: number | null;
  semantic_chunk: number | null;
  problem_sim: number | null;
  method_sim: number | null;
  dataset_overlap: number | null;
  citation: number | null;
  recency: number | null;
  /** 1 from a preferred publisher, else 0; absent from rankings made before it existed */
  publisher?: number | null;
}

export interface RankedPaperSnapshot {
  candidate_id: string;
  signals: SignalScores;
  weights_version: string;
  fused_score: number;
  rerank_score: number | null;
  final_rank: number;
  band: Confidence;
  explanation: RankingExplanation;
}

export interface WorkspacePaper {
  workspace_id: string;
  paper_id: string;
  added_by: AddedBy;
  role: WorkspacePaperRole;
  grounding: Grounding;
  pinned: boolean;
  tags: string[];
  note: string | null;
  order: number;
  ranking_snapshot: RankedPaperSnapshot | null;
  added_at: string;
}

export interface WorkspaceCounts {
  papers: number;
  /** Trail edges, excluding rejected. */
  edges: number;
  /** Excluding rejected. */
  gaps: number;
  /** Excluding rejected. */
  directions: number;
  comparisons: number;
}

export interface Workspace {
  workspace_id: string;
  owner_id: string;
  title: string;
  seed_paper_id: string;
  seed_profile_id: string;
  papers: WorkspacePaper[];
  combined_index_path: string | null;
  source_run_id: string | null;
  created_at: string;
  updated_at: string;
  counts?: WorkspaceCounts;
  /** the seed paper's title (in the list only) */
  seed_title?: string | null;
}

export interface WorkspaceListResponse {
  workspaces: Workspace[];
  next_cursor: string | null;
}

export interface AddPapersResponse {
  workspace: Workspace;
  added: string[];
}

// --- discovery / related papers (Roadmap Phase 15: the first HTTP path to
// the Phase 5/6 discovery+ranking pipelines) ------------------------------

export type DiscoveryStrategy =
  | "keyword"
  | "semantic"
  | "semantic_doc"
  | "query_expansion"
  | "citation"
  | "method"
  | "topic"
  | "research_question"
  | "recommendation";

export type CitationRelationship = "cited_by_seed" | "cites_seed" | "co_cited" | "none";

export interface DiscoverJobRef {
  job_id: string;
  kind: "discover";
  status: JobStatus;
  poll_url: string;
}

export interface DiscoverJobResponse {
  job: DiscoverJobRef;
  /** a run of this seed was already going (a refresh, a second tab): this is it */
  resumed?: boolean;
}

// A discover job's progress, and -- once saved -- its run's report
// (backend app/services/discovery/progress.py). Only measured times, real
// counts, and the limits the run enforces.
export type DiscoveryStep = "plan" | "resolve" | "search" | "score" | "save" | "rank" | "trail";
export type DiscoveryStepState = "pending" | "running" | "done" | "failed" | "skipped";

export interface DiscoveryStepEntry {
  state: DiscoveryStepState;
  /** seconds into the run it began */
  started_s?: number;
  seconds?: number;
  /** the most it is allowed to take */
  limit_s?: number;
  total?: number;
  note?: string;
  found?: number;
  ranked?: number;
  off_topic?: number;
  edges?: number;
}

export interface DiscoveryStrategyEntry {
  /** timed_out: stopped by its limit, what it had found kept */
  state: "running" | "done" | "timed_out" | "failed";
  found: number;
  seconds?: number;
  notes?: string[];
}

export interface DiscoverySourceEntry {
  answered: number;
  failed: number;
  cached: number;
  seconds?: number;
  /** rate_limited, http_503, unreachable ... */
  last_failure?: string;
}

export interface DiscoveryReport {
  started_at: string;
  elapsed_s: number;
  steps: Partial<Record<DiscoveryStep, DiscoveryStepEntry>>;
  strategies: Partial<Record<DiscoveryStrategy, DiscoveryStrategyEntry>>;
  sources: Record<string, DiscoverySourceEntry>;
  warnings: string[];
  status?: "succeeded" | "partial" | "failed";
  strategies_timed_out?: DiscoveryStrategy[];
}

export interface DiscoveryPreviewPaper {
  title: string;
  year: number | null;
  source: string;
}

export interface DiscoveryProgress extends DiscoveryReport {
  /** discovery | ranking | trail | done | failed | cancelled | interrupted */
  stage: string;
  step: DiscoveryStep | "";
  /** distinct papers the sources have returned so far */
  found: number;
  /** the first few that arrived: not ranked */
  preview: DiscoveryPreviewPaper[];
}

export interface RelatedRunSummary {
  run_id: string;
  seed_paper_id: string;
  strategies_succeeded: DiscoveryStrategy[];
  strategies_failed: DiscoveryStrategy[];
  // off_topic: candidates the ranking's relevance floor set aside (already
  // excluded from after_filter); absent on runs from before it existed
  counts: { raw: number; after_dedupe: number; after_filter: number; off_topic?: number };
  extra_citation_hop_used: boolean;
  weights_version: string | null;
  /** how the run went; null for runs saved before it was kept */
  report?: DiscoveryReport | null;
  /** what the ranking was weighted by; null when its version doesn't say */
  ranking_criteria?: RankingCriteria | null;
  /** the publishers its ranking preferred (absent from older servers) */
  preferred_publishers?: string[] | null;
  /** the fused score each band starts at */
  bands?: { high: number; medium: number };
  started_at?: string | null;
  finished_at?: string | null;
}

export interface RelatedPaperSummary {
  id: string;
  title: string;
  authors: string[];
  year: number | null;
  venue: string | null;
  publisher?: string | null;
  doi: string | null;
  url: string | null;
  abstract?: string | null;
}

export interface RelatedResult {
  paper: RelatedPaperSummary;
  discovery_methods: DiscoveryStrategy[];
  citation_relationship: CitationRelationship;
  signals: SignalScores | null;
  weights_version: string | null;
  fused_score: number | null;
  rerank_score: number | null;
  final_rank: number | null;
  band: Confidence | null;
  explanation: RankingExplanation | null;
}

export interface RelatedResponse {
  run: RelatedRunSummary;
  results: RelatedResult[];
}

// --- research trail -----------------------------------------------------

export type RelationshipType =
  | "SIMILAR"
  | "FOUNDATIONAL"
  | "RECENT"
  | "COMPETING"
  | "METHOD_EXTENSION"
  | "DATASET_RELATED"
  | "POTENTIALLY_CONTRADICTORY";

export type DetectionMethod = "rule" | "rule_llm_confirmed" | "contradiction_nli" | "user";
export type EdgeUserState = "pending" | "accepted" | "rejected";

export interface TrailEvidence {
  span: SourceSpan;
  role: string;
}

export interface TrailEdge {
  edge_id: string;
  run_id: string;
  workspace_id: string | null;
  source_paper_id: string;
  target_paper_id: string;
  relationship_type: RelationshipType;
  detection_method: DetectionMethod;
  rule_fired: string | null;
  llm_confirmed: boolean;
  evidence: TrailEvidence[];
  supporting_references: string[];
  confidence: Confidence;
  confidence_basis: Record<string, unknown>;
  user_state: EdgeUserState;
  created_at: string;
}

export interface TrailTarget {
  id: string;
  title: string | null;
  year: number | null;
  authors?: string[];
  venue?: string | null;
}

/** The target's standing in the discovery run the edge came from: the
 * measured signals the relationship rule fired on. Null when that run has
 * no ranking for it. */
export interface TrailRanking {
  final_rank: number;
  band: Confidence;
  signals: Partial<Record<keyof SignalScores, number>>;
}

export interface TrailGroupEntry {
  target: TrailTarget;
  edge: TrailEdge;
  ranking?: TrailRanking | null;
}

export type TrailGroups = Record<RelationshipType, TrailGroupEntry[]>;

export interface GroupedTrail {
  seed_paper_id: string;
  seed?: { id: string; title: string | null; year: number | null };
  groups: TrailGroups;
}

export const RELATIONSHIP_TYPES: RelationshipType[] = [
  "FOUNDATIONAL",
  "SIMILAR",
  "RECENT",
  "COMPETING",
  "METHOD_EXTENSION",
  "DATASET_RELATED",
  "POTENTIALLY_CONTRADICTORY",
];

// --- claims / citations ---------------------------------------------------

export interface Claim {
  claim_id: string;
  workspace_id: string;
  artefact_kind: string;
  artefact_id: string;
  sentence: string;
  supporting_chunk_ids: string[];
  supporting_paper_ids: string[];
  is_supported: boolean;
  citation_precision: number | null;
  citation_recall: number | null;
}

export type CitationFormat = "apa" | "ieee" | "bibtex";

export interface CitationEntry {
  paper_id: string;
  resolved_from: string;
  formatted: Partial<Record<CitationFormat, string>>;
}

/** Where the workspace cites a paper (GET .../citations, the ledger). */
export type CitationUseKind = "answer" | "comparison" | "gap" | "direction";

export interface CitationUse {
  kind: CitationUseKind;
  artefact_id: string;
  /** The workspace's own words: an answer's sentence, a cell's value, a gap's statement, a direction's proposal. */
  text: string;
  /** The part of this paper's passage the workspace's words rest on, verbatim. */
  quote: string | null;
  /** The passage goes on before / after the quote (answers only). */
  cut_before?: boolean;
  cut_after?: boolean;
  /** The sentence that best supports the words, as [start, end) offsets into `quote`. */
  highlight?: [number, number] | null;
  section: string | null;
  page: number | null;
  created_at: string | null;
  session_id?: string;
  field?: string;
  state?: string;
  role?: string;
  gap_id?: string;
}

export interface LedgerConnection {
  edge_id: string;
  type: RelationshipType;
  other_paper_id: string;
  direction: "in" | "out";
  state: string;
}

export interface LedgerPaper {
  paper_id: string;
  title: string;
  authors: string[];
  year: number | null;
  venue: string | null;
  publisher?: string | null;
  doi: string | null;
  arxiv_id: string | null;
  url: string | null;
  role: "seed" | "member";
  grounding: Grounding;
  reference: { resolved_from: string; formatted: Partial<Record<CitationFormat, string>> };
  reference_count: number | null;
  seed_relation: CitationRelationship | null;
  connections: LedgerConnection[];
  uses: CitationUse[];
  counts: Record<CitationUseKind, number>;
}

export interface SeedReference {
  order: number;
  text: string;
  paper_id: string | null;
  in_workspace: boolean;
}

export interface CitationLedger {
  workspace_id: string;
  papers: LedgerPaper[];
  seed_references: SeedReference[];
}

export interface CitationsResponse {
  citations: CitationEntry[];
  unresolved: string[];
}

// --- chat / RAG -------------------------------------------------------

export type ChatRole = "user" | "assistant";

export interface ChatSession {
  session_id: string;
  workspace_id: string;
  owner_id: string;
  title: string | null;
  created_at: string;
  /** Session list only: how many questions were asked, and when the last message landed. */
  questions?: number;
  last_active_at?: string;
}

/** A passage that supports one sentence of an answer, resolved from the stored chunk. */
export interface ChatSource {
  chunk_id: string;
  paper_id: string;
  paper_title: string | null;
  section: string | null;
  page: number | null;
  /** The part of the passage that supports the sentence, verbatim. */
  quote: string;
  /** The passage goes on after the quote. */
  truncated: boolean;
  /** The passage starts before the quote (absent from older answers). */
  cut_before?: boolean;
  /** The sentence that best supports the claim, as [start, end) offsets into `quote`. */
  highlight?: [number, number] | null;
}

export interface ChatClaim extends Claim {
  sources: ChatSource[];
}

export interface ChatMessage {
  message_id: string;
  session_id: string;
  role: ChatRole;
  content: string;
  citations: string[];
  tokens_prompt: number;
  tokens_completion: number;
  faithfulness: number | null;
  answerable: boolean;
  /** Assistant turns: what to try instead when the workspace can't answer. */
  suggestion?: string | null;
  /** Sentences left out because no source supported them. */
  unsupported_dropped?: number;
  warnings?: string[];
  created_at: string;
  claims?: ChatClaim[];
}

export interface ChatSessionsResponse {
  sessions: ChatSession[];
}

export interface ChatSessionDetailResponse {
  session: ChatSession;
  messages: ChatMessage[];
}

export interface ChatResponse {
  message_id: string;
  session_id: string;
  text: string;
  answerable: boolean;
  faithfulness: number | null;
  unsupported_dropped: number;
  suggestion: string | null;
  claims: Claim[];
  warnings: string[];
}

export type RagStage = "searching" | "reading" | "writing" | "checking" | "rewriting";

export interface SseStatusEvent {
  stage: RagStage;
}

export interface SseCitationEvent {
  marker: string;
  claim_id: string;
  paper_id: string | null;
  chunk_id: string;
  quote: string;
  section: string | null;
  page: number | null;
  /** The cited sentence and every passage that supports it (absent from older backends). */
  sentence?: string;
  sources?: ChatSource[];
}

export interface SseUsageEvent {
  prompt: number;
  completion: number;
}

export interface SseDoneEvent {
  message_id: string;
  session_id: string;
  faithfulness?: number | null;
  answerable: boolean;
  unsupported_dropped?: number;
  suggestion?: string | null;
  warnings?: string[];
  /** A regenerated answer replaced these. */
  replaced_message_ids?: string[];
}

export interface SseErrorEvent {
  code: string;
  message: string;
  /** With `provider_error`: auth, insufficient_balance, rate_limited, timeout, unavailable, bad_request, bad_response. */
  kind?: string;
}

// --- summary / keypoints ------------------------------------------------

export interface SummaryResponse {
  summary_id: string;
  text: string;
  faithfulness: number | null;
  unsupported_dropped: number;
  claims: Claim[];
  warnings: string[];
}

export interface KeyPoint {
  facet: string;
  text: string;
  span: SourceSpan;
}

export interface PaperKeyPoints {
  paper_id: string;
  points: KeyPoint[];
  warnings: string[];
}

export interface KeypointsResponse {
  papers: PaperKeyPoints[];
}

// --- comparison ---------------------------------------------------------

/** Why a comparison cell looks the way it does (absent from older backends). */
export type CellStatus = "found" | "not_stated" | "unsupported" | "no_text" | "not_extracted" | "unknown";

export interface ComparisonCell {
  column: string;
  text: string | null;
  span: SourceSpan | null;
  claim_id: string | null;
  grounding: string;
  conflicting: string[];
  status?: CellStatus;
}

export interface ComparisonRow {
  paper_id: string;
  cells: Record<string, ComparisonCell>;
}

/** Shape of Comparison.api_dict() -- the real wire format, not the raw model. */
export interface ComparisonResponse {
  comparison_id: string;
  schema: string[];
  generated_by: string;
  paper_ids: string[];
  rows: ComparisonRow[];
  coverage: number;
  decontext_eval: number | null;
  warnings?: string[];
  /** When it was made (UTC); absent from comparisons served before remediation Phase 4. */
  created_at?: string;
}

/** One column of the comparison table: a paper, named in full. */
export interface ComparisonTablePaper {
  paper_id: string;
  title: string;
  authors: string;
  year: number | null;
  publisher?: string | null;
  kind: "seed" | "member" | "connected";
  /** what the paper was read from when compared */
  read_from: "full_text" | "abstract" | "none";
  in_workspace: boolean;
  /** the heading's second line: authors · year · what it was read from */
  meta: string;
}

export interface ComparisonTableCell {
  paper_id: string;
  status: CellStatus;
  /** the quoted value, or the label of why the cell is empty */
  text: string;
  /** other values the same passage states */
  note: string | null;
}

export interface ComparisonTableRow {
  field: string;
  label: string;
  cells: ComparisonTableCell[];
}

/** The comparison as a table: what the page draws and the Word export writes
 * (GET /workspaces/{id}/compare/{comparison_id}/table). */
export interface ComparisonTable {
  comparison_id: string;
  created_at: string;
  corner: string;
  papers: ComparisonTablePaper[];
  rows: ComparisonTableRow[];
}

// --- research gaps ------------------------------------------------------

export type GapType =
  | "METHOD_GAP"
  | "DATASET_GAP"
  | "EVALUATION_GAP"
  | "DOMAIN_GAP"
  | "PERFORMANCE_GAP"
  | "GENERALIZATION_GAP"
  | "CONTRADICTION"
  | "UNEXPLORED_COMBINATION"
  | "TEMPORAL_GAP";

export type GapUserState = "candidate" | "accepted" | "rejected";

export interface GapEvidence {
  paper_id: string;
  span: SourceSpan;
  role: string;
}

export interface ResearchGap {
  gap_id: string;
  workspace_id: string;
  statement: string;
  gap_type: GapType;
  supporting_papers: string[];
  supporting_evidence: GapEvidence[];
  conflicting_evidence: GapEvidence[];
  why_unaddressed: string;
  affected_methods: string[];
  affected_datasets: string[];
  evidence_coverage: number;
  novelty_assessment: string;
  confidence: Confidence;
  confidence_basis: Record<string, unknown>;
  proposed_direction: string;
  detection_rule: string;
  self_support_passed: boolean;
  user_state: GapUserState;
  generated_at: string;
  generator_model: string | null;
}

export interface GapsListResponse {
  gaps: ResearchGap[];
}

export interface GapsJobRef {
  job_id: string;
  kind: "gaps";
  status: "queued";
  poll_url: string;
}

export interface GapsJobResponse {
  job: GapsJobRef;
}

// --- research directions --------------------------------------------------

export type DirectionKind = "evidence_backed_inference" | "llm_hypothesis";
export type DirectionUserState = "candidate" | "accepted" | "rejected";

export interface DirectionCritique {
  novelty?: number;
  specificity?: number;
  feasibility?: number;
  groundedness?: number;
  [key: string]: unknown;
}

export interface ResearchDirection {
  direction_id: string;
  workspace_id: string;
  gap_id: string;
  proposal: string;
  motivation: string;
  supporting_evidence: GapEvidence[];
  related_papers: string[];
  suggested_method: string;
  possible_dataset: string | null;
  evaluation_strategy: string;
  risks: string[];
  kind: DirectionKind;
  critique: DirectionCritique;
  confidence: Confidence;
  confidence_basis: Record<string, unknown>;
  flags: string[];
  user_state: DirectionUserState;
  generated_at: string;
  generator_model: string | null;
}

export interface DirectionsListResponse {
  directions: ResearchDirection[];
}

export interface DirectionsGenerateResponse {
  directions: ResearchDirection[];
  requested: number;
  generated: number;
  skipped_not_accepted: number;
  skipped_not_found: number;
  dropped_unsupported: number;
}

// --- research graph -----------------------------------------------------

export type GraphNodeType =
  | "PAPER"
  | "METHOD"
  | "DATASET"
  | "TOPIC"
  | "RESEARCH_QUESTION"
  | "CLAIM"
  | "GAP"
  | "DIRECTION";

export type GraphEdgeType =
  | "SIMILAR"
  | "CITES"
  | "EXTENDS"
  | "USES_METHOD"
  | "USES_DATASET"
  | "COMPETES_WITH"
  | "SUPPORTS"
  | "CONTRADICTS"
  | "ADDRESSES"
  | "EXPOSES_GAP";

export interface GraphNode {
  id: string;
  type: GraphNodeType;
  label: string;
  paper_ids: string[];
  span: SourceSpan | null;
  /** PAPER nodes: false for a paper reached only through a trail edge
   * (a connected paper that was never added to the workspace). Absent from
   * older backends, where every node was a member. */
  in_workspace?: boolean;
  role?: WorkspacePaperRole | null;
  year?: number | null;
  authors?: string[];
  venue?: string | null;
}

export interface GraphEdgeRecord {
  src: string;
  dst: string;
  type: GraphEdgeType;
  evidence: SourceSpan[];
  confidence: Confidence;
  /** The trail edges folded into this graph edge (absent from older backends). */
  trail_edge_ids?: string[];
  relationship_types?: RelationshipType[];
  /** "pending" while any of those trail edges still awaits review. */
  user_state?: Exclude<EdgeUserState, "rejected">;
}

export interface ResearchGraph {
  workspace_id: string;
  nodes: GraphNode[];
  edges: GraphEdgeRecord[];
  built_at: string;
  node_count: number;
  edge_count: number;
}

// --- activity / stage_runs ------------------------------------------------

export type StageName =
  | "ingest"
  | "profile"
  | "discovery"
  | "ranking"
  | "trail"
  | "workspace"
  | "rag"
  | "comparison"
  | "gaps"
  | "directions"
  | "citations";

export interface StageRun {
  id: string;
  owner_id: string;
  workspace_id: string | null;
  job_id: string | null;
  stage: StageName;
  tool: string;
  input_hash: string;
  output_hash: string;
  /** The provider-reported tokens of the model calls this run made. */
  tokens_prompt: number;
  tokens_completion: number;
  latency_ms: number;
  ok: boolean;
  error: string | null;
  ts: string;
}

export interface ActivityResponse {
  stage_runs: StageRun[];
}

// --- model usage (remediation Phase 5) -------------------------------------

export type UsageRange = "7d" | "30d" | "90d" | "all";

/** The provider's own counts: prompt includes cached, completion includes reasoning. */
export interface UsageTotals {
  calls: number;
  failed_calls: number;
  /** Answered calls whose provider sent no usage: their tokens are unknown, not zero. */
  unreported_calls: number;
  prompt_tokens: number;
  cached_prompt_tokens: number;
  completion_tokens: number;
  reasoning_tokens: number;
  total_tokens: number;
}

export interface UsageReport {
  /** A rolling window ending `until`; `since` is null for all time. */
  range: { key: UsageRange; days: number | null; since: string | null; until: string };
  workspace_id: string | null;
  totals: UsageTotals;
  first_call_at: string | null;
  last_call_at: string | null;
  by_feature: (UsageTotals & { feature: string })[];
  by_model: (UsageTotals & { provider: string; model: string })[];
  /** Absent when the report is for one workspace. A null id: work outside any workspace; a null title: a deleted one. */
  by_workspace?: (UsageTotals & { workspace_id: string | null; title: string | null })[];
}

// --- error envelope -------------------------------------------------------

export interface ApiErrorBody {
  detail: {
    error: {
      code: string;
      message: string;
      details?: Record<string, unknown>;
      request_id?: string;
    };
  };
}

// --- scholarly sources (Settings > Sources & full text, 2026-10-06) ------

export type SourceUse = "discovery" | "records" | "full_text";

export interface ScholarlySource {
  id: string;
  name: string;
  used_for: SourceUse[];
  /** "configured" / "not_set": a key this source accepts; "none": it has no key */
  key: "configured" | "not_set" | "none";
  /** the backend/.env setting that holds its key */
  key_setting: string | null;
  /** what using it without a key means */
  keyless: string;
  /** false when it can't be asked as set up (Unpaywall without a contact email) */
  available: boolean;
}

export interface SourcesResponse {
  contact_email_set: boolean;
  sources: ScholarlySource[];
}

export interface SourceCheck {
  id: string;
  status: "ok" | "limited" | "refused" | "unreachable" | "error" | "not_set_up";
  http_status?: number | null;
  latency_ms?: number;
  detail?: string;
}

export interface PublishersResponse {
  default: string[];
  known: string[];
}
