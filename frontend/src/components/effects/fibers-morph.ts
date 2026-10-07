/**
 * GhostFibers through the graph transition (remediation Phase 14-15), on the
 * neural field's own MORPH clock, so the graph page's entrance -- nodes
 * emerging, edges drawing, the graph growing into focus -- meets the
 * fibers exactly as it meets the neural field:
 *   energize  activity rises: the fibers speed up, twist and glow;
 *   converge  the field draws in toward the graph (a slow zoom);
 *   fade      everything not the graph dims to an ambient level;
 *   settle    the surge passes; the fibers keep moving, calmer, behind it.
 * Releasing (leaving the graph) eases back to rest over MORPH.release.
 * Pure functions of time: the component only renders what these return.
 */
import { MORPH } from "./constellation/field";

export interface FibersDynamics {
  speed: number;
  glowIntensity: number;
  twist: number;
  brightness: number;
  vignette: number;
  /** CSS zoom of the fiber layer: the field drawing in */
  zoom: number;
}

/** The user's GhostFibers configuration's moving parts, at rest. */
export const FIBERS_AT_REST: FibersDynamics = { speed: 0.2, glowIntensity: 1.6, twist: 0.1, brightness: 2, vignette: 0.8, zoom: 1 };
const SURGE: FibersDynamics = { speed: 0.62, glowIntensity: 2.5, twist: 0.32, brightness: 2.3, vignette: 0.8, zoom: 1 };
/** Behind the settled graph: alive, but quiet enough to read over. */
export const FIBERS_AMBIENT: FibersDynamics = { speed: 0.12, glowIntensity: 1.15, twist: 0.12, brightness: 1.05, vignette: 0.93, zoom: 1.06 };

const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const span = (t: number, [a, b]: readonly [number, number]) => easeInOut(clamp01((t - a) / (b - a)));
const mix = (a: number, b: number, t: number) => a + (b - a) * t;
const round = (v: number) => Math.round(v * 1e4) / 1e4;

/** The fibers `t` seconds after the graph asked for the morph. */
export function fibersDuringMorph(t: number): FibersDynamics {
  const [rise0, rise1, fall0, fall1] = MORPH.energize;
  // the surge: up over [rise0, rise1], held, then down to ambient over [fall0, fall1]
  const up = span(t, [rise0, rise1]);
  const down = span(t, [fall0, fall1]);
  const surge = up * (1 - down);
  const dim = span(t, MORPH.fade);
  const draw = span(t, MORPH.converge);
  const settled = (k: keyof FibersDynamics, ambient: number) => mix(FIBERS_AT_REST[k], ambient, k === "zoom" ? draw : dim);
  const at = (k: keyof FibersDynamics) => round(mix(settled(k, FIBERS_AMBIENT[k]), SURGE[k] + (FIBERS_AMBIENT[k] - FIBERS_AT_REST[k]) * dim, surge));
  return {
    speed: round(mix(mix(FIBERS_AT_REST.speed, SURGE.speed, up), FIBERS_AMBIENT.speed, down)),
    glowIntensity: at("glowIntensity"),
    twist: round(mix(mix(FIBERS_AT_REST.twist, SURGE.twist, up), FIBERS_AMBIENT.twist, down)),
    brightness: at("brightness"),
    vignette: round(settled("vignette", FIBERS_AMBIENT.vignette)),
    zoom: round(settled("zoom", FIBERS_AMBIENT.zoom)),
  };
}

/** Easing back to rest, `t` seconds after leaving the graph, from `from`. */
export function fibersReleasing(from: FibersDynamics, t: number): FibersDynamics {
  const k = span(t, [0, MORPH.release]);
  return {
    speed: round(mix(from.speed, FIBERS_AT_REST.speed, k)),
    glowIntensity: round(mix(from.glowIntensity, FIBERS_AT_REST.glowIntensity, k)),
    twist: round(mix(from.twist, FIBERS_AT_REST.twist, k)),
    brightness: round(mix(from.brightness, FIBERS_AT_REST.brightness, k)),
    vignette: round(mix(from.vignette, FIBERS_AT_REST.vignette, k)),
    zoom: round(mix(from.zoom, FIBERS_AT_REST.zoom, k)),
  };
}
