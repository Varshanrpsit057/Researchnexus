import { describe, expect, it } from "vitest";
import { placeLabels, truncate } from "./labels";

const measure = (text: string) => text.length * 6;

describe("graph labels", () => {
  it("never lets two labels touch: each keeps clear space around it", () => {
    // two nodes one label-height apart: right next to each other, the labels would touch
    const placed = placeLabels(
      [
        { id: "a", x: 100, y: 100, r: 5, text: "Alpha paper title", priority: 2, maxChars: 40 },
        { id: "b", x: 100, y: 117, r: 5, text: "Beta paper title", priority: 1, maxChars: 40 },
      ],
      [],
      { width: 800, height: 600 },
      measure,
    );
    const a = placed.find((l) => l.id === "a")!;
    const b = placed.find((l) => l.id === "b");
    expect(a.anchor).toBe("start");
    // b had to go elsewhere (left or below), or be left to hover -- never flush against a
    expect(b?.anchor === "start" && b.y === 117).toBe(false);
  });

  it("gives the higher-priority paper its full title first", () => {
    const placed = placeLabels(
      [
        { id: "seed", x: 200, y: 200, r: 8, text: "A long seed paper title that names its method", priority: 60, maxChars: 52 },
        { id: "other", x: 210, y: 200, r: 5, text: "Another paper", priority: 10, maxChars: 30 },
      ],
      [],
      { width: 800, height: 600 },
      measure,
    );
    expect(placed[0]).toMatchObject({ id: "seed", text: "A long seed paper title that names its method", truncated: false });
  });

  it("cuts a long title at a word", () => {
    expect(truncate("Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks", 30)).toBe("Retrieval-Augmented…");
  });
});
