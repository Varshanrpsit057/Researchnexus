export interface LabelCandidate {
  id: string;
  /** Node centre and radius, in screen px. */
  x: number;
  y: number;
  r: number;
  text: string;
  /** Higher places first and wins any overlap. */
  priority: number;
  maxChars: number;
}

export interface PlacedLabel {
  id: string;
  x: number;
  y: number;
  anchor: "start" | "end" | "middle";
  text: string;
  /** True when the title was cut to fit. */
  truncated: boolean;
}

interface Box {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

const overlaps = (a: Box, b: Box) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;

export function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  const cut = text.slice(0, max - 1);
  const space = cut.lastIndexOf(" ");
  return `${(space > max * 0.6 ? cut.slice(0, space) : cut).replace(/[\s,.:;–-]+$/, "")}…`;
}

/** Greedy label placement: highest priority first, each label tries the
 * right of its node, then the left, then below, and is dropped (left to
 * hover) when every spot would collide with a placed label or a node.
 * Labels keep `pad` px of clear space from each other: flush labels read
 * as one run-on title. */
export function placeLabels(
  candidates: LabelCandidate[],
  nodes: { x: number; y: number; r: number }[],
  viewport: { width: number; height: number },
  /** Rendered width of a label; defaults to an average-glyph estimate. */
  measure: (text: string, id: string) => number = (text) => text.length * 6.7,
  lineHeight = 16,
  pad = { x: 10, y: 3 },
): PlacedLabel[] {
  const padded = (b: Box): Box => ({ x0: b.x0 - pad.x, y0: b.y0 - pad.y, x1: b.x1 + pad.x, y1: b.y1 + pad.y });
  const placed: PlacedLabel[] = [];
  const boxes: Box[] = [];
  const circles: Box[] = nodes.map((n) => ({ x0: n.x - n.r, y0: n.y - n.r, x1: n.x + n.r, y1: n.y + n.r }));
  const sorted = [...candidates].sort((a, b) => b.priority - a.priority || a.id.localeCompare(b.id));
  for (const c of sorted) {
    if (c.x < -200 || c.y < -40 || c.x > viewport.width + 200 || c.y > viewport.height + 40) continue;
    // a long title that fits nowhere is tried shorter before it is dropped
    for (const max of [c.maxChars, Math.round(c.maxChars * 0.62), 16]) {
      const text = truncate(c.text, max);
      const w = measure(text, c.id);
      const h = lineHeight;
      const gap = c.r + 7;
      const options: { box: Box; x: number; y: number; anchor: PlacedLabel["anchor"] }[] = [
        { box: { x0: c.x + gap, y0: c.y - h / 2, x1: c.x + gap + w, y1: c.y + h / 2 }, x: c.x + gap, y: c.y, anchor: "start" },
        { box: { x0: c.x - gap - w, y0: c.y - h / 2, x1: c.x - gap, y1: c.y + h / 2 }, x: c.x - gap, y: c.y, anchor: "end" },
        { box: { x0: c.x - w / 2, y0: c.y + gap - 2, x1: c.x + w / 2, y1: c.y + gap - 2 + h }, x: c.x, y: c.y + gap - 2 + h / 2, anchor: "middle" },
      ];
      const fit = options.find(
        (opt) =>
          // a label that would run off the edge of the stage takes another side
          opt.box.x0 >= 4 &&
          opt.box.x1 <= viewport.width - 4 &&
          opt.box.y1 <= viewport.height &&
          !boxes.some((b) => overlaps(b, padded(opt.box))) &&
          !circles.some((b, i) => !(Math.abs(nodes[i].x - c.x) < 0.5 && Math.abs(nodes[i].y - c.y) < 0.5) && overlaps(b, opt.box)),
      );
      if (fit) {
        boxes.push(fit.box);
        placed.push({ id: c.id, x: fit.x, y: fit.y, anchor: fit.anchor, text, truncated: text !== c.text });
        break;
      }
      if (text.length <= 16) break;
    }
  }
  return placed;
}
