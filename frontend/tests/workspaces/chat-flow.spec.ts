// spec: Slice 5 (Ask -> Verify) critical flow.
//
// Chat generation is LLM-gated and no working BYOK key exists in this
// environment, so the SSE stream itself is mocked (a plain fetch +
// ReadableStream parse, not EventSource -- a single fulfilled response
// body parses identically to a chunked one, see chat-stream.ts). Reaching
// the chat page still requires a real workspace, seeded the same way as
// curate-flow.spec.ts; the real, unmocked backend call is exercised too
// (a genuine 409 llm_key_required against a message this test never mocks).
import { execFileSync } from "node:child_process";
import path from "node:path";
import { test, expect } from "../fixtures";

const PYTHON = String.raw`H:\Researchnexus\backend\.venv\Scripts\python.exe`;

function seedProfile(paperId: string, title: string) {
  execFileSync(PYTHON, [path.join(__dirname, "seed-real-profile.py"), paperId, title]);
}

function cleanupSeededProfile(paperId: string) {
  execFileSync(PYTHON, [path.join(__dirname, "cleanup-seeded-profile.py"), paperId]);
}

function sse(events: { event: string; data: object }[]): string {
  return events.map((e) => `event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`).join("");
}

async function createWorkspace(page: import("@playwright/test").Page): Promise<{ seedPaperId: string; workspaceId: string }> {
  const fileChooserPromise = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Browse for a file" }).click();
  const fileChooser = await fileChooserPromise;
  await fileChooser.setFiles(path.join(process.cwd(), "tests", "fixtures", "sample-paper.pdf"));
  await page.waitForURL(/\/papers\/pap_/, { timeout: 15_000 });
  const seedPaperId = page.url().split("/papers/")[1].split("?")[0];
  seedProfile(seedPaperId, "Chat Flow Seed Paper");
  await page.reload();
  await page.getByText("Skip discovery, start a workspace with just this paper").click();
  await page.getByRole("dialog", { name: "Create a workspace" }).getByRole("button", { name: "Create workspace" }).click();
  await page.waitForURL(/\/workspace\/ws_/, { timeout: 10_000 });
  const workspaceId = page.url().split("/workspace/")[1].split(/[/?#]/)[0];
  return { seedPaperId, workspaceId };
}

test.describe("Ask -> Verify", () => {
  let seededPaperId: string | null = null;

  test.afterEach(() => {
    if (seededPaperId) cleanupSeededProfile(seededPaperId);
    seededPaperId = null;
  });

  test("an answerable question renders its inline citation and evidence quote", async ({ page }) => {
    const { seedPaperId, workspaceId } = await createWorkspace(page);
    seededPaperId = seedPaperId;

    await page.route(`**/api/v1/workspaces/${workspaceId}/chat`, (route) =>
      route.fulfill({
        contentType: "text/event-stream",
        body: sse([
          { event: "token", data: { text: "Retrieval " } },
          { event: "token", data: { text: "augmentation " } },
          { event: "token", data: { text: "reduces hallucination [1]." } },
          {
            event: "citation",
            data: {
              marker: "[1]",
              claim_id: "claim_pw_1",
              paper_id: seedPaperId,
              chunk_id: "chunk_pw_1",
              quote: "grounding answers in retrieved evidence reduces unsupported claims",
              section: "Findings",
              page: 4,
            },
          },
          { event: "usage", data: { prompt: 10, completion: 8 } },
          { event: "done", data: { message_id: "cm_pw_1", session_id: "cs_pw_1", faithfulness: 0.91, answerable: true, unsupported_dropped: 0 } },
        ]),
      })
    );
    await page.route(`**/api/v1/workspaces/${workspaceId}/chat/sessions/cs_pw_1`, (route) =>
      route.fulfill({
        json: {
          session_id: "cs_pw_1",
          messages: [
            { message_id: "cm_pw_0", session_id: "cs_pw_1", role: "user", content: "Does retrieval reduce hallucination?", citations: [], tokens_prompt: 0, tokens_completion: 0, faithfulness: null, answerable: true, created_at: "2026-01-01T00:00:00Z" },
            { message_id: "cm_pw_1", session_id: "cs_pw_1", role: "assistant", content: "Retrieval augmentation reduces hallucination [1].", citations: ["claim_pw_1"], tokens_prompt: 10, tokens_completion: 8, faithfulness: 0.91, answerable: true, created_at: "2026-01-01T00:00:01Z" },
          ],
        },
      })
    );

    await page.goto(`/workspaces/${workspaceId}/chat`);
    await page.getByPlaceholder("Ask about this workspace's papers…").fill("Does retrieval reduce hallucination?");
    await page.getByRole("button", { name: "Send" }).click();

    await expect(page.getByText("Retrieval augmentation reduces hallucination")).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("faithfulness 0.91")).toBeVisible();
    await page.getByRole("button", { name: "[1]" }).hover();
    await expect(page.getByText("grounding answers in retrieved evidence reduces unsupported claims")).toBeVisible();
    await expect(page.getByText("Findings, p.4")).toBeVisible();
  });

  test("an unanswerable question shows the system's real suggestion instead of a blank reply", async ({ page }) => {
    const { seedPaperId, workspaceId } = await createWorkspace(page);
    seededPaperId = seedPaperId;

    await page.route(`**/api/v1/workspaces/${workspaceId}/chat`, (route) =>
      route.fulfill({
        contentType: "text/event-stream",
        body: sse([
          {
            event: "done",
            data: {
              message_id: "cm_pw_2",
              session_id: "cs_pw_2",
              answerable: false,
              suggestion: "Try asking about the seed paper's own findings instead -- nothing in this workspace addresses that yet.",
            },
          },
        ]),
      })
    );
    await page.route(`**/api/v1/workspaces/${workspaceId}/chat/sessions/cs_pw_2`, (route) =>
      route.fulfill({
        json: {
          session_id: "cs_pw_2",
          messages: [
            { message_id: "cm_pw_1", session_id: "cs_pw_2", role: "user", content: "What does this say about cold fusion?", citations: [], tokens_prompt: 0, tokens_completion: 0, faithfulness: null, answerable: true, created_at: "2026-01-01T00:00:00Z" },
            { message_id: "cm_pw_2", session_id: "cs_pw_2", role: "assistant", content: "", citations: [], tokens_prompt: 0, tokens_completion: 0, faithfulness: null, answerable: false, created_at: "2026-01-01T00:00:01Z" },
          ],
        },
      })
    );

    await page.goto(`/workspaces/${workspaceId}/chat`);
    await page.getByPlaceholder("Ask about this workspace's papers…").fill("What does this say about cold fusion?");
    await page.getByRole("button", { name: "Send" }).click();

    // The real bug this covers: before this session's Slice 5 pass, an
    // unanswerable turn persisted with `content: ""` and re-fetching the
    // session after the SSE stream closed rendered a blank assistant
    // bubble -- the backend's own `suggestion` string was computed and
    // sent over SSE, then silently discarded because ChatMessage has no
    // column for it.
    await expect(page.getByText("Try asking about the seed paper's own findings instead")).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("not answerable from workspace")).toBeVisible();
  });

  test("chatting without a saved LLM key shows the real, specific error", async ({ page }) => {
    const { workspaceId, seedPaperId } = await createWorkspace(page);
    seededPaperId = seedPaperId;

    // No route mock here: this is a real, unmocked call against the real
    // backend, which genuinely has no working key in this environment.
    await page.goto(`/workspaces/${workspaceId}/chat`);
    await page.getByPlaceholder("Ask about this workspace's papers…").fill("Any question");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("No working LLM provider key is saved yet. Add one in Settings, then try again.")).toBeVisible({ timeout: 5_000 });
  });
});
