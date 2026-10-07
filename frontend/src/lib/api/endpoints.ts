import { apiDownload, apiFetch, apiUpload } from "./client";
import type {
  ActivityResponse,
  AddPapersResponse,
  AnalyzeResponse,
  ApiKeySummary,
  ChatResponse,
  ChatSessionDetailResponse,
  ChatSessionsResponse,
  CitationFormat,
  CitationLedger,
  CitationsResponse,
  ComparisonResponse,
  ComparisonTable,
  EdgeUserState,
  DirectionsGenerateResponse,
  DiscoverJobResponse,
  DirectionsListResponse,
  DirectionUserState,
  GapsJobResponse,
  KeyCheckResponse,
  HealthResponse,
  GapsListResponse,
  GapUserState,
  GroupedTrail,
  Job,
  KeypointsResponse,
  LibraryResponse,
  LlmProvider,
  LlmTestResult,
  MeResponse,
  Paper,
  ResearchGap,
  ResearchGraph,
  ResearchProfile,
  ResearchDirection,
  RankingCriteria,
  RelatedResponse,
  SessionResponse,
  SourceCheck,
  SourcesResponse,
  PublishersResponse,
  StageName,
  SummaryResponse,
  TrailEdge,
  UploadResponse,
  UsageRange,
  UsageReport,
  FullTextJob,
  FullTextOutcome,
  PaperTextOutcome,
  WorkspaceTrailBuild,
  WorkspaceCoverage,
  Workspace,
  WorkspaceListResponse,
  WorkspacePaper,
} from "./types";

// --- auth -----------------------------------------------------------------

export const auth = {
  createSession: (email: string, password: string) =>
    apiFetch<SessionResponse>("/api/v1/auth/session", { method: "POST", body: { email, password } }),
  me: () => apiFetch<MeResponse>("/api/v1/me"),
  updateMe: (body: { default_provider: LlmProvider | null }) => apiFetch<MeResponse>("/api/v1/me", { method: "PATCH", body }),
};

export const service = {
  health: () => apiFetch<HealthResponse>("/health"),
  /** each scholarly source, what it's for and how it is set up (never a key) */
  sources: () => apiFetch<SourcesResponse>("/api/v1/service/sources"),
  /** ask every source one question now */
  checkSources: () => apiFetch<{ results: SourceCheck[] }>("/api/v1/service/sources/check", { method: "POST" }),
  publishers: () => apiFetch<PublishersResponse>("/api/v1/publishers"),
};

// --- model usage --------------------------------------------------------

export const usage = {
  /** The signed-in user's usage over `range`, for every workspace or one. */
  get: (range: UsageRange, workspaceId?: string) =>
    apiFetch<UsageReport>("/api/v1/usage", { query: { range, workspace_id: workspaceId } }),
};

// --- BYOK keys --------------------------------------------------------

export const llmKeys = {
  list: () => apiFetch<{ keys: ApiKeySummary[] }>("/api/v1/settings/llm-keys"),
  test: (provider: LlmProvider, api_key: string) =>
    apiFetch<LlmTestResult>("/api/v1/settings/llm-keys/test", { method: "POST", body: { provider, api_key } }),
  save: (provider: LlmProvider, api_key: string) =>
    apiFetch<ApiKeySummary>("/api/v1/settings/llm-keys", { method: "PUT", body: { provider, api_key } }),
  remove: (provider: LlmProvider) =>
    apiFetch<void>(`/api/v1/settings/llm-keys/${provider}`, { method: "DELETE" }),
  /** Probe the stored key again, server side; the key never travels. */
  check: (provider: LlmProvider) =>
    apiFetch<KeyCheckResponse>(`/api/v1/settings/llm-keys/${provider}/check`, { method: "POST" }),
};

// --- papers -----------------------------------------------------------

export const papers = {
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return apiUpload<UploadResponse>("/api/v1/papers/upload", form);
  },
  /** The reader's library: every paper they uploaded, analysed, searched from or collected. */
  library: () => apiFetch<LibraryResponse>("/api/v1/papers"),
  get: (paperId: string) => apiFetch<Paper>(`/api/v1/papers/${paperId}`),
  getProfile: (paperId: string) => apiFetch<ResearchProfile>(`/api/v1/papers/${paperId}/profile`),
  analyze: (paperId: string) => apiFetch<AnalyzeResponse>(`/api/v1/papers/${paperId}/analyze`, { method: "POST" }),
  /** Looks for this paper's full text now; can take tens of seconds. */
  retrieveFullText: (paperId: string) =>
    apiFetch<FullTextOutcome>(`/api/v1/papers/${paperId}/fulltext`, { method: "POST" }),
  /** A PDF the reader has becomes this paper's full text (a paper whose copy can't be fetched). */
  uploadPdf: (paperId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return apiUpload<PaperTextOutcome>(`/api/v1/papers/${paperId}/pdf`, form);
  },
  /** Reads an uploaded paper's PDF again with the current reader, and completes its record. */
  reread: (paperId: string) => apiFetch<PaperTextOutcome>(`/api/v1/papers/${paperId}/reread`, { method: "POST" }),
  patchProfile: (paperId: string, patch: Record<string, unknown>) =>
    apiFetch<{ profile: ResearchProfile }>(`/api/v1/papers/${paperId}/profile`, { method: "PATCH", body: patch }),
  /** `criteria`: how the results are to be ranked; omitted, the initial weights.
   * `preferredPublishers`: the publishers the reader prefers; omitted, the default four. */
  discoverRelated: (paperId: string, criteria?: RankingCriteria, preferredPublishers?: string[]) =>
    apiFetch<DiscoverJobResponse>(`/api/v1/papers/${paperId}/discover-related`, {
      method: "POST",
      ...(criteria || preferredPublishers
        ? { body: { ...(criteria ? { criteria } : {}), ...(preferredPublishers ? { preferred_publishers: preferredPublishers } : {}) } }
        : {}),
    }),
  /** re-weigh a saved run's ranking; returns the results as `related` does */
  rerankRelated: (paperId: string, runId: string, criteria: RankingCriteria, preferredPublishers?: string[]) =>
    apiFetch<RelatedResponse>(`/api/v1/papers/${paperId}/related/rerank`, {
      method: "POST",
      body: { run_id: runId, criteria, ...(preferredPublishers ? { preferred_publishers: preferredPublishers } : {}) },
    }),
  related: (paperId: string, runId: string) =>
    apiFetch<RelatedResponse>(`/api/v1/papers/${paperId}/related`, { query: { run_id: runId } }),
};

export const jobs = {
  get: (jobId: string) => apiFetch<Job>(`/api/v1/jobs/${jobId}`),
  /** stop a running discovery; one already finished is returned as it is */
  cancel: (jobId: string) => apiFetch<Job>(`/api/v1/jobs/${jobId}/cancel`, { method: "POST" }),
};

// --- workspaces -------------------------------------------------------

export const workspaces = {
  list: () => apiFetch<WorkspaceListResponse>("/api/v1/workspaces"),
  create: (body: { title: string; seed_paper_id: string; import_run_id?: string | null }) =>
    apiFetch<Workspace>("/api/v1/workspaces", { method: "POST", body }),
  get: (workspaceId: string) => apiFetch<Workspace>(`/api/v1/workspaces/${workspaceId}`),
  update: (workspaceId: string, body: { title?: string }) =>
    apiFetch<Workspace>(`/api/v1/workspaces/${workspaceId}`, { method: "PATCH", body }),
  remove: (workspaceId: string) => apiFetch<void>(`/api/v1/workspaces/${workspaceId}`, { method: "DELETE" }),

  addPapers: (workspaceId: string, body: { paper_ids: string[]; from_run_id?: string | null }) =>
    apiFetch<AddPapersResponse>(`/api/v1/workspaces/${workspaceId}/papers`, { method: "POST", body }),
  removePaper: (workspaceId: string, paperId: string) =>
    apiFetch<Workspace>(`/api/v1/workspaces/${workspaceId}/papers/${paperId}`, { method: "DELETE" }),
  updatePaper: (
    workspaceId: string,
    paperId: string,
    body: Partial<{ pinned: boolean; tags: string[]; note: string | null; order: number }>
  ) => apiFetch<WorkspacePaper>(`/api/v1/workspaces/${workspaceId}/papers/${paperId}`, { method: "PATCH", body }),

  // state: omitted = pending + accepted; "all" includes rejected edges too
  trail: (workspaceId: string, query?: { type?: string; band?: string; state?: EdgeUserState | "all" }) =>
    apiFetch<GroupedTrail>(`/api/v1/workspaces/${workspaceId}/trail`, { query }),
  setEdgeState: (workspaceId: string, edgeId: string, user_state: "accepted" | "rejected" | "pending") =>
    apiFetch<TrailEdge>(`/api/v1/workspaces/${workspaceId}/trail/${edgeId}`, { method: "POST", body: { user_state } }),

  graph: (workspaceId: string) => apiFetch<ResearchGraph>(`/api/v1/workspaces/${workspaceId}/graph`),

  /** What text each paper is read from, and the latest full-text run. */
  coverage: (workspaceId: string) => apiFetch<WorkspaceCoverage>(`/api/v1/workspaces/${workspaceId}/coverage`),
  /** Looks again for the full text of every abstract-only paper (in the background). */
  retrieveFullText: (workspaceId: string) =>
    apiFetch<{ job: FullTextJob | null }>(`/api/v1/workspaces/${workspaceId}/fulltext`, { method: "POST" }),
  /** Connects the workspace's own papers to its seed: a trail without a discovery run. */
  buildTrail: (workspaceId: string) =>
    apiFetch<WorkspaceTrailBuild>(`/api/v1/workspaces/${workspaceId}/trail/build`, { method: "POST" }),

  activity: (workspaceId: string, query?: { stage?: StageName; limit?: number }) =>
    apiFetch<ActivityResponse>(`/api/v1/workspaces/${workspaceId}/activity`, { query }),

  summary: (workspaceId: string, body: { scope?: "all" | { paper_ids: string[] }; length?: "short" | "medium" | "long" }) =>
    apiFetch<SummaryResponse>(`/api/v1/workspaces/${workspaceId}/summary`, { method: "POST", body }),
  keypoints: (workspaceId: string, body: { paper_ids?: string[] }) =>
    apiFetch<KeypointsResponse>(`/api/v1/workspaces/${workspaceId}/keypoints`, { method: "POST", body }),

  chat: (workspaceId: string, body: { message: string; session_id?: string | null; scope?: "all" | { paper_ids: string[] } }) =>
    apiFetch<ChatResponse>(`/api/v1/workspaces/${workspaceId}/chat`, { method: "POST", body }),
  chatSessions: (workspaceId: string) => apiFetch<ChatSessionsResponse>(`/api/v1/workspaces/${workspaceId}/chat/sessions`),
  chatSession: (workspaceId: string, sessionId: string) =>
    apiFetch<ChatSessionDetailResponse>(`/api/v1/workspaces/${workspaceId}/chat/sessions/${sessionId}`),

  compare: (workspaceId: string, body: { paper_ids: string[]; schema?: string[] | null }) =>
    apiFetch<ComparisonResponse>(`/api/v1/workspaces/${workspaceId}/compare`, { method: "POST", body }),
  getComparison: (workspaceId: string, comparisonId: string) =>
    apiFetch<ComparisonResponse>(`/api/v1/workspaces/${workspaceId}/compare/${comparisonId}`),
  getLatestComparison: (workspaceId: string) =>
    apiFetch<ComparisonResponse>(`/api/v1/workspaces/${workspaceId}/compare`),
  /** The table the page draws and the Word export writes; `paperIds` picks the columns shown. */
  comparisonTable: (workspaceId: string, comparisonId: string, paperIds?: string[]) =>
    apiFetch<ComparisonTable>(`/api/v1/workspaces/${workspaceId}/compare/${comparisonId}/table`, {
      query: { papers: paperIds?.join(",") },
    }),
  exportComparisonDocx: (workspaceId: string, comparisonId: string, paperIds: string[]) =>
    apiDownload(`/api/v1/workspaces/${workspaceId}/compare/${comparisonId}/export.docx`, { papers: paperIds.join(",") }),

  generateGaps: (workspaceId: string, body: { gap_types?: string[] | null; min_supporting_papers?: number }) =>
    apiFetch<GapsJobResponse>(`/api/v1/workspaces/${workspaceId}/gaps`, { method: "POST", body }),
  listGaps: (workspaceId: string, state?: GapUserState) =>
    apiFetch<GapsListResponse>(`/api/v1/workspaces/${workspaceId}/gaps`, { query: { state } }),
  setGapState: (workspaceId: string, gapId: string, user_state: GapUserState) =>
    apiFetch<ResearchGap>(`/api/v1/workspaces/${workspaceId}/gaps/${gapId}`, { method: "POST", body: { user_state } }),

  generateDirections: (workspaceId: string, gap_ids: string[]) =>
    apiFetch<DirectionsGenerateResponse>(`/api/v1/workspaces/${workspaceId}/directions`, { method: "POST", body: { gap_ids } }),
  listDirections: (workspaceId: string, query?: { state?: DirectionUserState; gap_id?: string }) =>
    apiFetch<DirectionsListResponse>(`/api/v1/workspaces/${workspaceId}/directions`, { query }),
  setDirectionState: (workspaceId: string, directionId: string, user_state: DirectionUserState) =>
    apiFetch<ResearchDirection>(`/api/v1/workspaces/${workspaceId}/directions/${directionId}`, {
      method: "POST",
      body: { user_state },
    }),

  citationLedger: (workspaceId: string) => apiFetch<CitationLedger>(`/api/v1/workspaces/${workspaceId}/citations`),
  citations: (workspaceId: string, body: { paper_ids?: string[] | "all"; formats?: CitationFormat[] }) =>
    apiFetch<CitationsResponse>(`/api/v1/workspaces/${workspaceId}/citations`, { method: "POST", body }),
};
