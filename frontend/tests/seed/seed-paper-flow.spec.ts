// spec: Phase 4 (Seed Paper) critical flow -- mirrors
// tests/papers/analyze-flow.spec.ts exactly (same justification for mocking
// only the LLM-touched analyze call: profile extraction needs a real BYOK
// key that does not exist in this test environment), but exercises the new
// cinematic /seed/[paperId] front door instead of the legacy
// /papers/[paperId] page. "Start discovery" itself is only a real link into
// /discover/[seedId] here -- tests/discover/discover-flow.spec.ts is where
// that page's own job-kickoff, ranked results, and workspace flow are
// covered, so this spec stops at confirming the hand-off, not repeating it.
import path from "node:path";
import { test, expect } from "../fixtures";

const PROFILE = {
  profile_id: "prof_pw_seed_001",
  paper_id: "__PAPER_ID__",
  workspace_id: null,
  grounding: "full_text",
  title: "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
  abstract: "Large pre-trained language models store factual knowledge in their parameters, but access to this knowledge is imprecise and hard to inspect or revise.",
  authors: [] as string[],
  year: null,
  venue: null,
  doi: null,
  arxiv_id: null,
  domain: { value: "Natural language processing", source_span: null, status: "verified" },
  subdomains: { items: [] as unknown[] },
  research_problem: { value: "Parametric knowledge is hard to inspect or revise.", source_span: null, status: "verified" },
  research_questions: { items: [] as unknown[] },
  objectives: { items: [] as unknown[] },
  keywords: ["retrieval-augmented generation"],
  methods: { items: [{ value: "Dense passage retrieval.", source_span: null, status: "unverified" }] },
  models: { items: [] as unknown[] },
  algorithms: { items: [] as unknown[] },
  datasets: { items: [{ value: "Natural Questions.", source_span: null, status: "unverified" }] },
  evaluation_metrics: { items: [] as unknown[] },
  findings: { items: [{ value: "Reduces hallucination on open-domain QA.", source_span: null, status: "unverified" }] },
  limitations: { items: [] as unknown[] },
  future_work: { items: [] as unknown[] },
  important_entities: { items: [] as unknown[] },
  cited_methods: { items: [] as unknown[] },
  candidate_search_queries: [] as string[],
  extraction_confidence: "high",
  extraction_model: "playwright-mock",
  tokens: { prompt: 0, completion: 0 },
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

test.describe("Seed Paper", () => {
  test("shows real paper metadata, runs analysis, and starting discovery hands off to the real discovery page", async ({ page }) => {
    // 1. Real upload against the real backend (same as every other seed
    //    flow test) to get a real paper id to navigate the new page with.
    const fileChooserPromise = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: "Browse for a file" }).click();
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles(path.join(process.cwd(), "tests", "fixtures", "sample-paper.pdf"));
    await page.waitForURL(/\/papers\/pap_/, { timeout: 15_000 });
    const paperId = page.url().split("/papers/")[1].split("?")[0];
    const profile = { ...PROFILE, paper_id: paperId };

    // 2. The new cinematic front door, reached the way Home actually links
    //    to it -- real metadata (title, id, document status) from the real
    //    GET /papers/{id}, no profile yet so an honest "Run analysis" CTA
    //    and a "Start discovery" affordance that isn't a real link yet.
    await page.goto(`/seed/${paperId}`);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Retrieval-Augmented Generation");
    await expect(page.getByText(paperId)).toBeVisible();
    await expect(page.getByRole("button", { name: "Run analysis" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Start discovery" })).not.toBeVisible();
    await expect(page.getByText("Run analysis first.")).toBeVisible();

    // 3. Mock only the LLM-touched analyze call.
    await page.route(`**/api/v1/papers/${paperId}/analyze`, (route) =>
      route.fulfill({ json: { profile, extraction_confidence: "high", warnings: [] } })
    );
    await page.getByRole("button", { name: "Run analysis" }).click();
    await expect(page.getByText(profile.abstract)).toBeVisible();
    await expect(page.getByText("Dense passage retrieval.")).toBeVisible();
    await expect(page.getByText("Reduces hallucination on open-domain QA.")).toBeVisible();

    // 4. "Start discovery" is now a real link into the dedicated discovery
    //    page -- confirm only the hand-off; that page's own job-kickoff,
    //    ranked results, and workspace flow are discover-flow.spec.ts's job.
    const discoveryLink = page.getByRole("link", { name: "Start discovery" });
    await expect(discoveryLink).toBeVisible();
    await expect(discoveryLink).toHaveAttribute("href", `/discover/${paperId}`);
  });

  test("shows an honest not-found state for a seed paper id that does not exist", async ({ page }) => {
    await page.goto("/seed/pap_does_not_exist");
    await expect(page.getByText("Paper not found")).toBeVisible();
    await expect(page.getByRole("link", { name: "Back to papers" })).toBeVisible();
  });
});
