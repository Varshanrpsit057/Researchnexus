// spec: Slice 2 (Seed -> Discover -> Understand) critical flow.
//
// Discovery's `keyword`/`query_expansion` strategies call real external
// literature APIs (arXiv, OpenAlex, Semantic Scholar, Crossref), which are
// not reachable from this sandboxed test environment -- confirmed live: a
// real discover-related run against a genuinely well-cited paper
// ("Attention Is All You Need") still found zero ranked candidates and the
// backend job failed. Auth, upload, and parsing stay real; the job-status
// poll and the related-results fetch are mocked at the network layer so
// the real frontend code path -- progress labels, the ranked-results
// render (prose explanation, rank ordinal, per-signal leader rows,
// discovery-method tracings), and the clean failure message -- is what
// gets exercised, not a third party's uptime.
import path from "node:path";
import { test, expect } from "../fixtures";

const RELATED_RESPONSE = {
  run: {
    run_id: "run_pw_mock_001",
    seed_paper_id: "__PAPER_ID__",
    strategies_succeeded: ["semantic", "citation"],
    strategies_failed: ["keyword"],
    counts: { raw: 40, after_dedupe: 22, after_filter: 5 },
    extra_citation_hop_used: true,
    weights_version: "v1",
  },
  results: [
    {
      paper: {
        id: "pap_pw_related_001",
        title: "Dense Passage Retrieval for Open-Domain Question Answering",
        authors: ["V. Karpukhin", "B. Oguz"],
        year: 2020,
        venue: "EMNLP",
        doi: null,
        url: null,
      },
      discovery_methods: ["semantic_doc", "citation"],
      citation_relationship: "cites_seed",
      signals: { semantic_doc: 0.82, semantic_chunk: null, problem_sim: 0.71, method_sim: 0.65, dataset_overlap: null, citation: 1.0, recency: 0.4 },
      weights_version: "v1",
      fused_score: 0.78,
      rerank_score: null,
      final_rank: 1,
      band: "high",
      explanation: {
        bullet_reasons: ["cites the seed paper directly", "high semantic similarity on the core method"],
        prose: "This paper cites the seed directly and shares a strong semantic match on its core retrieval method.",
        signals_used: ["semantic_doc", "citation"],
        template_only: true,
      },
    },
  ],
};

test.describe("Seed -> Discover -> Understand", () => {
  test("discovering related papers renders ranked results with their explanation, and a failed run shows a clean retryable message", async ({ page }) => {
    const fileChooserPromise = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: "Browse for a file" }).click();
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles(path.join(process.cwd(), "tests", "fixtures", "sample-paper.pdf"));
    await page.waitForURL(/\/papers\/pap_/, { timeout: 15_000 });
    const paperId = page.url().split("/papers/")[1].split("?")[0];

    // Give it a profile (mocked -- Slice 1's own concern) so discovery is
    // reachable at all: the real backend 409s discover-related without one.
    const emptyList = { items: [] as unknown[] };
    const mockedProfile = {
      profile_id: "prof_pw",
      paper_id: paperId,
      workspace_id: null,
      grounding: "full_text",
      title: "ResearchNexus: A Synthetic Test Paper on Retrieval-Augmented Generation",
      abstract: "",
      authors: [] as string[],
      year: null,
      venue: null,
      doi: null,
      arxiv_id: null,
      domain: { value: "NLP", source_span: null, status: "verified" },
      subdomains: emptyList,
      research_problem: { value: "", source_span: null, status: "unverified" },
      research_questions: emptyList,
      objectives: emptyList,
      keywords: [] as string[],
      methods: emptyList,
      models: emptyList,
      algorithms: emptyList,
      datasets: emptyList,
      evaluation_metrics: emptyList,
      findings: emptyList,
      limitations: emptyList,
      future_work: emptyList,
      important_entities: emptyList,
      cited_methods: emptyList,
      candidate_search_queries: [] as string[],
      extraction_confidence: "high",
      extraction_model: "playwright-mock",
      tokens: { prompt: 0, completion: 0 },
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    };
    await page.route(`**/api/v1/papers/${paperId}/analyze`, (route) =>
      route.fulfill({ json: { profile: mockedProfile, extraction_confidence: "high", warnings: [] } })
    );
    await page.getByRole("button", { name: "Run analysis" }).click();
    await expect(page.getByRole("button", { name: "Discover related papers" }).first()).toBeEnabled();

    // 1. A failed run first: clean primary message, raw detail demoted.
    let jobStatus: "queued" | "failed" = "queued";
    await page.route("**/api/v1/papers/*/discover-related", (route) =>
      route.fulfill({ json: { job: { job_id: "job_pw_mock", kind: "discover", status: "queued", poll_url: "/api/v1/jobs/job_pw_mock" } } })
    );
    await page.route("**/api/v1/jobs/job_pw_mock", (route) => {
      const body =
        jobStatus === "queued"
          ? { job_id: "job_pw_mock", status: "running", progress: { stage: "discovery" }, result_ref: null, error: null }
          : { job_id: "job_pw_mock", status: "failed", progress: { stage: "trail" }, result_ref: null, error: "run_hidden_id_001" };
      route.fulfill({ json: body });
    });
    await page.getByRole("button", { name: "Discover related papers" }).last().click();
    await expect(page.getByText("Searching external sources")).toBeVisible();
    jobStatus = "failed";
    await expect(page.getByText("Discovery failed. Try again, or try a different seed paper.")).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("run_hidden_id_001")).not.toBeVisible();
    await page.getByText("Technical details").click();
    await expect(page.getByText("run_hidden_id_001")).toBeVisible();

    // 2. Retry, this time succeeding, to verify the ranked-results render.
    // A real retry always gets a fresh job id from the backend (`new_id`) --
    // reusing the failed run's id here would leave the already-terminal,
    // no-longer-polling SWR cache entry stale, which is a test-mock
    // artifact, not app behavior worth asserting on.
    await page.unroute("**/api/v1/papers/*/discover-related");
    await page.route("**/api/v1/papers/*/discover-related", (route) =>
      route.fulfill({ json: { job: { job_id: "job_pw_mock_2", kind: "discover", status: "queued", poll_url: "/api/v1/jobs/job_pw_mock_2" } } })
    );
    let attempt = 0;
    await page.route("**/api/v1/jobs/job_pw_mock_2", (route) => {
      attempt += 1;
      const body =
        attempt < 2
          ? { job_id: "job_pw_mock_2", status: "running", progress: { stage: "ranking" }, result_ref: null, error: null }
          : { job_id: "job_pw_mock_2", status: "succeeded", progress: { stage: "done" }, result_ref: "run_pw_mock_001", error: null };
      route.fulfill({ json: body });
    });
    await page.route(`**/api/v1/papers/${paperId}/related*`, (route) =>
      route.fulfill({ json: { ...RELATED_RESPONSE, run: { ...RELATED_RESPONSE.run, seed_paper_id: paperId } } })
    );
    await page.getByRole("button", { name: "Discover related papers" }).last().click();

    await expect(page.getByText("Dense Passage Retrieval for Open-Domain Question Answering")).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("#1")).toBeVisible();
    await expect(page.getByText("This paper cites the seed directly")).toBeVisible();
    await expect(page.getByText("semantic doc")).toBeVisible();
    await expect(page.getByText("cites seed")).toBeVisible();

    await page.getByText("How this search ran").click();
    const searchDetails = page.locator("details", { hasText: "How this search ran" });
    await expect(searchDetails.getByText("found")).toBeVisible();
    await expect(searchDetails.getByText("40", { exact: true })).toBeVisible();
    await expect(searchDetails.getByText("used", { exact: true })).toBeVisible();
  });
});
