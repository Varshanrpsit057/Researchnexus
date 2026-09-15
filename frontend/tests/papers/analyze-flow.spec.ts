// spec: Slice 1 (Seed -> Analyze) critical flow.
//
// Profile extraction itself needs a real BYOK LLM provider key, which does
// not exist in this test environment (there is no fake/test LLM provider
// reachable outside pytest's own in-process monkeypatching -- confirmed by
// reading app/llm/*, app/routers/settings_keys.py, and app/deps.py). Upload,
// auth, parsing, and routing all still hit the real running backend; only
// the two LLM-touched calls (POST .../analyze and GET .../profile) are
// fulfilled at the network layer so the real UI code path -- rendering a
// full ResearchProfile, then a page reload reading it back without a
// second "Run analysis" click -- is exercised for real.
import path from "node:path";
import { test, expect } from "../fixtures";

const PROFILE = {
  profile_id: "prof_pw_test_001",
  paper_id: "__PAPER_ID__",
  workspace_id: null,
  grounding: "full_text",
  title: "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
  abstract: "Large pre-trained language models store factual knowledge in their parameters, but access to this knowledge is imprecise and hard to inspect or revise.",
  authors: [],
  year: null,
  venue: null,
  doi: null,
  arxiv_id: null,
  domain: { value: "Natural language processing", source_span: null, status: "verified" },
  subdomains: { items: [{ value: "Retrieval-augmented generation", source_span: null, status: "unverified" }] },
  research_problem: { value: "Parametric knowledge is hard to inspect or revise.", source_span: null, status: "verified" },
  research_questions: { items: [] },
  objectives: { items: [] },
  keywords: ["retrieval-augmented generation"],
  methods: { items: [{ value: "Dense passage retrieval.", source_span: null, status: "unverified" }] },
  models: { items: [] },
  algorithms: { items: [{ value: "Maximum inner product search.", source_span: null, status: "unverified" }] },
  datasets: { items: [] },
  evaluation_metrics: { items: [] },
  findings: { items: [] },
  limitations: { items: [] },
  future_work: { items: [] },
  important_entities: { items: [] },
  cited_methods: { items: [] },
  candidate_search_queries: [],
  extraction_confidence: "high",
  extraction_model: "playwright-mock",
  tokens: { prompt: 0, completion: 0 },
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

test.describe("Seed -> Analyze", () => {
  test("a fresh upload shows the run-analysis prompt, and a successful analysis renders the full profile and survives a reload", async ({ page }) => {
    // 1. Real upload against the real backend.
    const fileChooserPromise = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: "Browse for a file" }).click();
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles(path.join(process.cwd(), "tests", "fixtures", "sample-paper.pdf"));
    await page.waitForURL(/\/papers\/pap_/, { timeout: 15_000 });

    const paperId = page.url().split("/papers/")[1].split("?")[0];
    const profile = { ...PROFILE, paper_id: paperId };

    // 2. Before analysis, the profile GET honestly 404s and the page offers
    //    the real action, not a silent empty section.
    await expect(page.getByRole("button", { name: "Run analysis" })).toBeVisible();

    // 3. Mock only the LLM-touched analyze call; everything else this
    //    click triggers (state update, re-render) is the real component.
    await page.route(`**/api/v1/papers/${paperId}/analyze`, (route) =>
      route.fulfill({ json: { profile, extraction_confidence: "high", warnings: [] } })
    );
    await page.getByRole("button", { name: "Run analysis" }).click();

    await expect(page.getByText(profile.abstract)).toBeVisible();
    await expect(page.getByText("Subdomains")).toBeVisible();
    await expect(page.getByText("Retrieval-augmented generation").first()).toBeVisible();
    await expect(page.getByText("Algorithms")).toBeVisible();
    await expect(page.getByText("Maximum inner product search.")).toBeVisible();

    // 4. The defining behavior this slice was missing: reloading the page
    //    must show the already-extracted profile immediately, with no
    //    second click and no re-billed LLM call -- mock the GET the same
    //    way and confirm the UI reads it back on its own.
    await page.route(`**/api/v1/papers/${paperId}/profile`, (route) => route.fulfill({ json: profile }));
    await page.reload();
    await expect(page.getByText(profile.abstract)).toBeVisible();
    await expect(page.getByRole("button", { name: "Run analysis" })).not.toBeVisible();
  });
});
