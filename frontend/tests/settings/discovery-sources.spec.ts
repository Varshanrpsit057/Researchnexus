// spec: Settings > Discovery defaults and Sources & full text (2026-10-07).
//
// The publishers list and each source's set-up come from the real backend.
// The live check asks eight outside services, so its answer is given at the
// network layer here: tests never call them.
import { test, expect } from "../fixtures";

test.describe("Settings: discovery and sources", () => {
  test("preferred publishers are chosen, kept and reset; the sources say how they are set up and how a check went", async ({ page }) => {
    await page.goto("/settings#discovery");
    await expect(page.getByRole("heading", { level: 2, name: "Discovery defaults" })).toBeVisible();
    const publishers = page.getByRole("group", { name: "Preferred publishers" });
    await expect(publishers.getByRole("button", { name: "IEEE" })).toHaveAttribute("aria-pressed", "true");
    await expect(publishers.getByRole("button", { name: "MDPI" })).toHaveAttribute("aria-pressed", "false");

    // choosing: MDPI in, IEEE out -- kept in this browser, named everywhere it counts
    await publishers.getByRole("button", { name: "MDPI" }).click();
    await publishers.getByRole("button", { name: "IEEE" }).click();
    await expect(page.getByText("Preferred: Springer, ACM, Elsevier or MDPI.")).toBeVisible();
    expect(JSON.parse((await page.evaluate(() => localStorage.getItem("researchnexus.pref.preferredPublishers"))) ?? "[]")).toEqual([
      "Springer",
      "ACM",
      "Elsevier",
      "MDPI",
    ]);
    await expect(page.getByTestId("ranking-criteria")).toContainText("Published by Springer, ACM, Elsevier or MDPI");
    await page.reload();
    await expect(page.getByRole("group", { name: "Preferred publishers" }).getByRole("button", { name: "MDPI" })).toHaveAttribute("aria-pressed", "true");
    await page.getByRole("button", { name: "Back to IEEE, Springer, ACM and Elsevier" }).click();
    await expect(page.getByText("Preferred: IEEE, Springer, ACM or Elsevier.")).toBeVisible();

    // sources: how each is set up, and a check's answer
    await page.route("**/api/v1/service/sources/check", (route) =>
      route.fulfill({
        json: {
          results: [
            { id: "openalex", status: "limited", http_status: 429, latency_ms: 90, detail: "It asks to wait 25 min." },
            { id: "semantic_scholar", status: "ok", http_status: 200, latency_ms: 412 },
            { id: "arxiv", status: "ok", http_status: 200, latency_ms: 1530 },
            { id: "crossref", status: "unreachable", detail: "It didn't answer, or answered with a server error." },
            { id: "dblp", status: "ok", http_status: 200, latency_ms: 300 },
            { id: "core", status: "refused", http_status: 401, latency_ms: 80, detail: "It refused the request; check its key." },
            { id: "europepmc", status: "ok", http_status: 200, latency_ms: 500 },
            { id: "unpaywall", status: "not_set_up", detail: "No contact email is set, so it isn't asked." },
          ],
        },
      }),
    );
    await page.getByRole("navigation", { name: "Settings sections" }).getByRole("link", { name: "Sources & full text" }).click();
    const table = page.getByTestId("sources");
    const row = (name: string) => table.getByRole("row").filter({ has: page.getByRole("rowheader", { name, exact: true }) });
    await expect(row("OpenAlex")).toContainText("Discovery · Paper records · Full text");
    await expect(row("DBLP")).toContainText("Open; computer science only");
    await expect(row("OpenAlex")).toContainText("Not checked yet");
    await page.getByRole("button", { name: "Check every source now" }).click();
    await expect(row("OpenAlex")).toContainText("Limiting requests");
    await expect(row("OpenAlex")).toContainText("It asks to wait 25 min.");
    await expect(row("Semantic Scholar")).toContainText("Answered in 412 ms");
    await expect(row("arXiv")).toContainText("Answered in 1.5 s");
    await expect(row("Crossref")).toContainText("Unreachable");
    await expect(row("CORE")).toContainText("Refused");
    await expect(row("Unpaywall")).toContainText("Not asked");
    await expect(page.getByRole("button", { name: "Check again" })).toBeVisible();
    // a key's value is never on the page, only the setting's name
    await expect(page.locator("main")).not.toContainText(/Bearer|x-api-key/i);
  });
});
