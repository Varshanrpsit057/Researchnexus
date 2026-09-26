// spec: Phase 9 (Research Chat) critical flow at /workspace/[id]/chat.
//
// Generation is LLM-gated and no BYOK key exists in this environment, so
// exactly two things are mocked: the `me` flag saying a key is saved, and
// the chat POST's SSE stream. The stream follows the backend's real
// protocol (status -> tokens with each citation right after its sentence
// -> usage -> done) and points at a turn seed-chat-turn.py stored through
// the backend's own repository, with claims citing REAL chunks of the
// uploaded seed paper. Everything read back -- the conversation list, the
// reloaded thread, every source's paper/section/page/quote -- comes from
// the real backend. The no-key state and the backend's own 409 are real,
// unmocked calls.
import { execFileSync } from "node:child_process";
import path from "node:path";
import type { Page, Route } from "@playwright/test";
import { test, expect } from "../fixtures";

const PYTHON = String.raw`H:\Researchnexus\backend\.venv\Scripts\python.exe`;
const helper = (name: string) => path.join(__dirname, name);

interface SeededClaim {
  claim_id: string;
  sentence: string;
  chunk_id: string;
  paper_id: string;
  section: string | null;
  page: number | null;
  quote: string;
}
interface SeededTurn {
  session_id: string;
  message_id: string;
  question: string;
  seed_paper_id: string;
  claims: SeededClaim[];
}

function seedTurn(mode: "answer" | "unanswerable", workspaceId: string, tag: string) {
  return JSON.parse(execFileSync(PYTHON, [helper("seed-chat-turn.py"), mode, workspaceId, tag]).toString());
}

function sse(events: { event: string; data: object }[]): string {
  return events.map((e) => `event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`).join("");
}

/** The stream the backend would send for the stored turn. */
function answerStream(turn: SeededTurn, seedTitle: string): string {
  const events: { event: string; data: object }[] = ["searching", "reading", "writing", "checking"].map((stage) => ({ event: "status", data: { stage } }));
  turn.claims.forEach((c, i) => {
    for (const word of c.sentence.split(" ")) events.push({ event: "token", data: { text: `${word} ` } });
    const source = { chunk_id: c.chunk_id, paper_id: c.paper_id, paper_title: seedTitle, section: c.section, page: c.page, quote: c.quote, truncated: false };
    events.push({
      event: "citation",
      data: { marker: `[${i + 1}]`, claim_id: c.claim_id, sentence: c.sentence, paper_id: c.paper_id, chunk_id: c.chunk_id, quote: c.quote, section: c.section, page: c.page, sources: [source] },
    });
  });
  events.push({ event: "usage", data: { prompt: 900, completion: 60 } });
  events.push({
    event: "done",
    data: { message_id: turn.message_id, session_id: turn.session_id, answerable: true, faithfulness: 0.93, unsupported_dropped: 1, warnings: [], replaced_message_ids: [] },
  });
  return sse(events);
}

async function createWorkspace(page: Page): Promise<{ seedPaperId: string; workspaceId: string }> {
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Browse for a file" }).click();
  await (await chooser).setFiles(path.join(process.cwd(), "tests", "fixtures", "sample-paper.pdf"));
  await page.waitForURL(/\/papers\/pap_/, { timeout: 15_000 });
  const seedPaperId = page.url().split("/papers/")[1].split("?")[0];
  execFileSync(PYTHON, [helper("seed-real-profile.py"), seedPaperId, "Chat Flow Seed Paper"]);
  await page.reload();
  await page.getByText("Skip discovery, start a workspace with just this paper").click();
  await page.getByRole("dialog", { name: "Create a workspace" }).getByRole("button", { name: "Create workspace" }).click();
  await page.waitForURL(/\/workspace\/ws_/, { timeout: 10_000 });
  return { seedPaperId, workspaceId: page.url().split("/workspace/")[1].split(/[/?#]/)[0] };
}

/** Pretend a key is saved: only the `me` flag changes, the rest is the real response. */
async function claimAKey(page: Page) {
  await page.route("**/api/v1/me", async (route: Route) => {
    const res = await route.fetch();
    route.fulfill({ response: res, json: { ...(await res.json()), has_working_llm_key: true } });
  });
}

function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => {
    // the one intentional failure: the backend's real 409 for a missing key
    if (m.type() === "error" && !m.text().includes("409")) errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

const composer = (page: Page) => page.getByRole("textbox", { name: "Ask a question about this workspace's papers" });
const panel = (page: Page) => page.getByRole("complementary");

test.describe("Research chat", () => {
  let seededPaperId: string | null = null;

  test.afterEach(() => {
    if (seededPaperId) execFileSync(PYTHON, [helper("cleanup-seeded-profile.py"), seededPaperId]);
    seededPaperId = null;
  });

  test("a streamed answer cites its sources inline, keeps them after a reload, and can be inspected, regenerated and followed", async ({ page }) => {
    const { seedPaperId, workspaceId } = await createWorkspace(page);
    seededPaperId = seedPaperId;
    const consoleErrors = collectConsoleErrors(page);

    // 1. Workspace -> Chat. With no key saved (real), asking is off and says why.
    await page.getByRole("link", { name: "Ask this workspace" }).click();
    await page.waitForURL(new RegExp(`/workspace/${workspaceId}/chat$`));
    await expect(page.getByRole("heading", { level: 1, name: "Ask this workspace" })).toBeVisible();
    await expect(page.getByText("No working LLM provider key is saved, so questions can't be answered yet.")).toBeVisible();
    await expect(composer(page)).toBeDisabled();
    await expect(page.getByRole("heading", { name: "Ask anything the paper in this workspace can answer." })).toBeVisible();

    // 2. With a key, a question streams: the stages first, then the answer with its citations.
    const seedTitle = await page.evaluate(async (pid) => {
      const token = localStorage.getItem("researchnexus.token");
      const res = await fetch(`http://localhost:8000/api/v1/papers/${pid}`, { headers: { Authorization: `Bearer ${token}` } });
      return (await res.json()).title as string;
    }, seedPaperId);
    const turn: SeededTurn = seedTurn("answer", workspaceId, `a${Date.now()}`);
    const bodies: Record<string, unknown>[] = [];
    await claimAKey(page);
    await page.route(`**/api/v1/workspaces/${workspaceId}/chat`, async (route) => {
      const body = route.request().postDataJSON();
      bodies.push(body);
      await new Promise((r) => setTimeout(r, 900)); // the pipeline's working time
      if (body.regenerate && bodies.filter((b) => b.regenerate).length === 1) {
        return route.fulfill({ contentType: "text/event-stream", body: sse([{ event: "status", data: { stage: "searching" } }, { event: "error", data: { code: "generation_failed", message: "The language model didn't return a usable answer. Try again in a moment." } }]) });
      }
      return route.fulfill({ contentType: "text/event-stream", body: answerStream(turn, seedTitle) });
    });
    await page.reload();
    await composer(page).fill(turn.question);
    await page.keyboard.press("Enter");
    // the question as asked, in the thread (the conversation list may show it too)
    await expect(page.getByTestId("chat-thread").getByText(turn.question)).toBeVisible();
    await expect(page.getByRole("status").filter({ hasText: /Starting|Searching/ })).toBeVisible();
    await expect(page.getByRole("button", { name: "Stop answering" })).toBeVisible();

    // 3. The stored turn from the real backend: inline citations, sources, outcome.
    await page.waitForURL(new RegExp(`session=${turn.session_id}`), { timeout: 10_000 });
    const answer = page.getByRole("region", { name: "Answer" });
    await expect(answer).toContainText(turn.claims[0].sentence);
    await expect(answer.getByRole("button", { name: /^Source 1: / })).toBeVisible();
    await expect(answer.getByRole("button", { name: /^Source 2: / })).toBeVisible();
    await expect(answer.getByText("1 sentence was left out: no passage in this workspace supported it.")).toBeVisible();
    await expect(answer.getByText("0.93")).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Conversations" }).or(page.getByRole("button", { name: /^Conversations/ })).first()).toBeVisible();
    expect(bodies[0]).toMatchObject({ message: turn.question, session_id: null, regenerate: false });

    // 4. Inspect the evidence: the real chunk's quote, located, with the ways to its paper.
    await answer.getByRole("button", { name: /^Source 1: / }).click();
    await expect(panel(page).getByRole("heading", { name: "Source 1 of 2" })).toBeVisible();
    await expect(panel(page)).toContainText(turn.claims[0].sentence);
    await expect(panel(page)).toContainText(turn.claims[0].quote.slice(0, 60));
    await expect(panel(page).getByRole("link", { name: "Open paper" })).toHaveAttribute("href", `/seed/${seedPaperId}`);
    await expect(panel(page).getByRole("link", { name: "Show in graph" })).toHaveAttribute("href", `/workspace/${workspaceId}/graph?paper=${seedPaperId}`);
    await panel(page).getByRole("button", { name: "Next source" }).click();
    await expect(panel(page).getByRole("heading", { name: "Source 2 of 2" })).toBeVisible();
    await panel(page).getByRole("button", { name: "Close the source" }).click();
    await expect(panel(page)).toHaveCount(0);

    // 5. History: the conversation is listed and reloads as it was, from the real backend.
    await page.reload();
    await expect(page.getByRole("region", { name: "Answer" }).getByRole("button", { name: /^Source 2: / })).toBeVisible({ timeout: 10_000 });
    await page.getByRole("region", { name: "Answer" }).getByRole("button", { name: /^Source 2: / }).click();
    await expect(panel(page)).toContainText(turn.claims[1].quote.slice(0, 60));
    await panel(page).getByRole("button", { name: "Close the source" }).click();

    // 6. Regenerate: a failed attempt says so and offers a retry, which succeeds.
    await page.getByRole("button", { name: "Regenerate" }).click();
    await expect(page.getByText("The language model didn't return a usable answer. Try again in a moment.")).toBeVisible({ timeout: 10_000 });
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByRole("region", { name: "Answer" }).getByRole("button", { name: /^Source 1: / })).toBeVisible({ timeout: 10_000 });
    expect(bodies.filter((b) => b.regenerate)).toEqual([
      expect.objectContaining({ session_id: turn.session_id, regenerate: true }),
      expect.objectContaining({ session_id: turn.session_id, regenerate: true }),
    ]);

    // 7. A source leads into the graph, with its paper selected there.
    await page.getByRole("region", { name: "Answer" }).getByRole("button", { name: /^Source 1: / }).click();
    await panel(page).getByRole("link", { name: "Show in graph" }).click();
    await page.waitForURL(new RegExp(`/workspace/${workspaceId}/graph\\?paper=`));
    await expect(page.getByRole("complementary").getByRole("heading", { level: 2 })).toHaveText(seedTitle, { timeout: 15_000 });

    // 8. The old chat URL forwards here; a new conversation starts clean.
    await page.goto(`/workspaces/${workspaceId}/chat`);
    await page.waitForURL(new RegExp(`/workspace/${workspaceId}/chat$`));
    await expect(page.getByRole("heading", { name: "Ask anything the paper in this workspace can answer." })).toBeVisible();

    expect(consoleErrors).toEqual([]);
  });

  test("an unanswerable question keeps the system's real suggestion, and the backend's own missing-key error is explained", async ({ page }) => {
    const { seedPaperId, workspaceId } = await createWorkspace(page);
    seededPaperId = seedPaperId;
    const stored = seedTurn("unanswerable", workspaceId, `u${Date.now()}`);

    await page.goto(`/workspace/${workspaceId}/chat?session=${stored.session_id}`);
    await expect(page.getByText("This workspace doesn't hold enough to answer that.")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(stored.suggestion)).toBeVisible();

    // `me` claims a key, the chat request is NOT mocked: the real backend answers 409.
    await claimAKey(page);
    await page.reload();
    await composer(page).fill("Any question");
    await page.getByRole("button", { name: "Ask", exact: true }).click();
    await expect(page.getByText("No working LLM provider key is saved. Add one in Settings to ask questions.")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole("link", { name: "Add a key in Settings" })).toHaveAttribute("href", "/settings");
  });

  test("a conversation that isn't in the workspace, and a missing workspace, say so", async ({ page }) => {
    const { seedPaperId, workspaceId } = await createWorkspace(page);
    seededPaperId = seedPaperId;
    await page.goto(`/workspace/${workspaceId}/chat?session=cs_pw_missing`);
    await expect(page.getByText("That conversation isn't in this workspace anymore.")).toBeVisible({ timeout: 10_000 });
    await page.getByRole("button", { name: "Start a new conversation" }).click();
    await page.waitForURL(new RegExp(`/workspace/${workspaceId}/chat$`));

    await page.goto("/workspace/ws_pw_chat_missing/chat");
    await expect(page.getByRole("heading", { name: "Workspace not found" })).toBeVisible({ timeout: 10_000 });
  });
});
