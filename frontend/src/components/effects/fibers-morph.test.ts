import { describe, expect, it } from "vitest";
import { FIBERS_AT_REST, fibersDuringMorph, fibersReleasing } from "./fibers-morph";
import { MORPH } from "./constellation/field";

describe("GhostFibers through the graph transition", () => {
  it("starts exactly at rest", () => {
    expect(fibersDuringMorph(0)).toEqual(FIBERS_AT_REST);
  });

  it("speeds up and glows as the transition opens", () => {
    const peak = fibersDuringMorph(MORPH.energize[1]);
    expect(peak.speed).toBeGreaterThan(FIBERS_AT_REST.speed * 2);
    expect(peak.glowIntensity).toBeGreaterThan(FIBERS_AT_REST.glowIntensity);
    expect(peak.twist).toBeGreaterThan(FIBERS_AT_REST.twist);
  });

  it("draws in and dims toward an ambient level while the graph emerges", () => {
    const mid = fibersDuringMorph((MORPH.converge[0] + MORPH.converge[1]) / 2);
    expect(mid.zoom).toBeGreaterThan(1);
    const settled = fibersDuringMorph(10);
    expect(settled.brightness).toBeLessThan(FIBERS_AT_REST.brightness);
    expect(settled.vignette).toBeGreaterThan(FIBERS_AT_REST.vignette);
    expect(settled.speed).toBeLessThan(FIBERS_AT_REST.speed); // calmer behind the graph, still moving
    expect(settled.speed).toBeGreaterThan(0);
  });

  it("holds its ambient state once settled", () => {
    expect(fibersDuringMorph(5)).toEqual(fibersDuringMorph(50));
  });

  it("returns to rest when released, from wherever it was", () => {
    const from = fibersDuringMorph(1.1);
    expect(fibersReleasing(from, 0)).toEqual(from);
    expect(fibersReleasing(from, MORPH.release)).toEqual(FIBERS_AT_REST);
    const half = fibersReleasing(from, MORPH.release / 2);
    expect(half.brightness).toBeGreaterThan(Math.min(from.brightness, FIBERS_AT_REST.brightness));
    expect(half.brightness).toBeLessThan(Math.max(from.brightness, FIBERS_AT_REST.brightness));
  });
});
