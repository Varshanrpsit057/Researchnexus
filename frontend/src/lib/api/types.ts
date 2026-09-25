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
}

export interface MeResponse {
  id: string;
  email: string;
  created_at: string;
  has_working_llm_key: boolean;
  default_provider: string | null;
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

export interface Paper {
  id: string;
  title: string;
  authors: string[];
  year: number | null;
  venue: string | null;
  doi: string | null;
  arxiv_id: string | null;
  has_full_text: boolean;
  parse_confidence: ParseConfidence | null;
  page_count: number | null;
  sections: PaperSection[];
  tables: PaperTable[];
  warnings: string[];
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

export interface ProfileField {
  value: string;
  source_span: SourceSpan | null;
  status: ProvenanceStatus;
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

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "partial";

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

export interface RankingExplanation {
  bullet_reasons: string[];
  prose: string;
  signals_used: string[];
  template_only: boolean;
}

export interface SignalScores {
  semantic_doc: number | null;
  semantic_chunk: number | null;
  problem_sim: number | null;
  method_sim: number | null;
  dataset_overlap: number | null;
  citation: number | null;
  recency: number | null;
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
  token_budget_usd: number;
  tokens_used: TokenUsage;
  cost_used_usd: number;
  cost_used: number;
  source_run_id: string | null;
  created_at: string;
  updated_at: string;
  counts?: WorkspaceCounts;
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
  status: "queued";
  poll_url: string;
}

export interface DiscoverJobResponse {
  job: DiscoverJobRef;
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
}

export interface RelatedPaperSummary {
  id: string;
  title: string;
  authors: string[];
  year: number | null;
  venue: string | null;
  doi: string | null;
  url: string | null;
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
  quote: string;
  /** The quote was cut to a readable length. */
  truncated: boolean;
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

export interface ComparisonCell {
  column: string;
  text: string | null;
  span: SourceSpan | null;
  claim_id: string | null;
  grounding: string;
  conflicting: string[];
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
  tokens_prompt: number;
  tokens_completion: number;
  cost_usd: number;
  latency_ms: number;
  ok: boolean;
  error: string | null;
  ts: string;
}

export interface ActivityResponse {
  stage_runs: StageRun[];
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
