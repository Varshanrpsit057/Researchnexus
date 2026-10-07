/**
 * Which background this device gets (remediation Phase 14).
 *
 * Auto looks at the graphics the browser actually draws with -- the WebGL
 * renderer, which on a laptop with two GPUs is the one in use, not merely the
 * one installed -- and picks:
 *   dedicated GPU          -> the neural network (the richer animation)
 *   integrated graphics    -> GhostFibers (one light full-screen shader)
 *   software rendering     -> a still background (no animation at all)
 * When the browser won't name its graphics, the startup hint from start.py
 * (NEXT_PUBLIC_RN_BACKGROUND, from the machine's own adapter list) decides.
 * Nothing assumes NVIDIA or CUDA exists. An explicit Animated or Static
 * choice overrides Auto; it is kept in this browser only.
 */
"use client";

import { useSyncExternalStore } from "react";

export type GpuTier = "dedicated" | "integrated" | "software" | "unknown";
export type BackgroundChoice = "auto" | "animated" | "static";
export type BackgroundEffect = "neural" | "fibers" | "static";

const SOFTWARE = [
  "swiftshader", "llvmpipe", "softpipe", "microsoft basic", "basic render", "software", "remote display",
  "virtualbox", "vmware", "parallels", "hyper-v", "virgl", "virtio",
];

/** The same rules start.py applies to the machine's adapter names, applied to
 * the renderer string the browser reports (often wrapped by ANGLE). */
export function classifyRenderer(renderer: string): GpuTier {
  const n = renderer.toLowerCase().replace(/\s+/g, " ").trim();
  if (!n) return "unknown";
  if (SOFTWARE.some((s) => n.includes(s))) return "software";
  if (/nvidia|geforce|quadro|tesla|\brtx\b/.test(n)) return "dedicated";
  if (/\barc(\(tm\))? [ab]\d/.test(n)) return "dedicated"; // Intel Arc cards
  if (/\bapple m\d/.test(n)) return "dedicated"; // Apple silicon: integrated, but discrete-class
  if (/radeon|firepro/.test(n)) return /\b(rx|pro|r9|r7|vii|firepro)\b/.test(n) ? "dedicated" : "integrated";
  if (/intel|\buhd\b|iris|adreno|mali|vega|powervr/.test(n)) return "integrated";
  return "unknown";
}

export interface DetectedGraphics {
  tier: GpuTier;
  renderer: string | null;
}

let detected: DetectedGraphics | null = null;

/** The graphics this browser draws with, probed once per page load. A test
 * may pin the tier with `window.__RN_GPU__`. */
export function detectGraphics(): DetectedGraphics {
  if (detected) return detected;
  const pinned = (window as unknown as { __RN_GPU__?: GpuTier }).__RN_GPU__;
  if (pinned) return (detected = { tier: pinned, renderer: null });
  let renderer: string | null = null;
  try {
    const canvas = document.createElement("canvas");
    const gl = (canvas.getContext("webgl2") ?? canvas.getContext("webgl")) as WebGLRenderingContext | null;
    if (!gl) return (detected = { tier: "software", renderer: null }); // no WebGL: nothing animated can run well
    const info = gl.getExtension("WEBGL_debug_renderer_info");
    renderer = String(info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER));
    gl.getExtension("WEBGL_lose_context")?.loseContext();
  } catch {
    return (detected = { tier: "unknown", renderer: null });
  }
  return (detected = { tier: classifyRenderer(renderer), renderer });
}

const HINTS: Record<string, BackgroundEffect | undefined> = { neural: "neural", fibers: "fibers", static: "static" };

export function resolveBackground(
  choice: BackgroundChoice,
  tier: GpuTier,
  hint: string | undefined,
): { effect: BackgroundEffect; reason: string } {
  if (choice === "static") return { effect: "static", reason: "You chose a still background." };
  if (choice === "animated") return { effect: "neural", reason: "You chose the animated background." };
  if (tier === "dedicated") return { effect: "neural", reason: "Auto: dedicated graphics found, so the animated neural network." };
  if (tier === "integrated") return { effect: "fibers", reason: "Auto: no dedicated graphics found, so the lightweight fibers." };
  if (tier === "software") return { effect: "static", reason: "Auto: this browser draws in software, so a still background." };
  const fromStart = hint ? HINTS[hint] : undefined;
  if (fromStart) return { effect: fromStart, reason: "Auto: the browser didn't name its graphics, so the startup check decided." };
  return { effect: "fibers", reason: "Auto: the graphics couldn't be identified, so the lightweight fibers." };
}

// -- the setting, kept in this browser -----------------------------------------

const KEY = "researchnexus.pref.background";
const LEGACY_KEY = "researchnexus.pref.backgroundMotion"; // "moving" | "still", before Phase 14
const EVENT = "researchnexus:background";
const CHOICES: readonly BackgroundChoice[] = ["auto", "animated", "static"];

export function readBackgroundChoice(): BackgroundChoice {
  try {
    const v = window.localStorage.getItem(KEY);
    if (v != null) return (CHOICES as readonly string[]).includes(v) ? (v as BackgroundChoice) : "auto";
    return window.localStorage.getItem(LEGACY_KEY) === "still" ? "static" : "auto";
  } catch {
    return "auto";
  }
}

export function writeBackgroundChoice(choice: BackgroundChoice): boolean {
  try {
    window.localStorage.setItem(KEY, choice);
  } catch {
    return false;
  }
  window.dispatchEvent(new CustomEvent(EVENT));
  return true;
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener(EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

const subscribeNever = () => () => {};

export function useBackgroundChoice(): BackgroundChoice {
  return useSyncExternalStore(subscribe, readBackgroundChoice, () => "auto");
}

/** The background in effect here, once the browser is known (null before:
 * the server can't know the device, so nothing is drawn until the client does). */
export function useBackground(): ({ effect: BackgroundEffect; reason: string } & DetectedGraphics & { choice: BackgroundChoice }) | null {
  const choice = useBackgroundChoice();
  // probed once, on the client; the server renders without it
  const graphics = useSyncExternalStore(subscribeNever, detectGraphics, () => null);
  if (!graphics) return null;
  return { ...resolveBackground(choice, graphics.tier, process.env.NEXT_PUBLIC_RN_BACKGROUND), ...graphics, choice };
}
