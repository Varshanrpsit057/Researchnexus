import { afterEach, describe, expect, it } from "vitest";
import { classifyRenderer, readBackgroundChoice, resolveBackground, writeBackgroundChoice } from "./background-mode";

afterEach(() => window.localStorage.clear());

describe("classifying the graphics the browser draws with", () => {
  it.each([
    ["ANGLE (NVIDIA, NVIDIA GeForce RTX 4060 Ti (0x00002803) Direct3D11 vs_5_0 ps_5_0, D3D11)", "dedicated"],
    ["ANGLE (AMD, AMD Radeon RX 6600 XT Direct3D11 vs_5_0 ps_5_0, D3D11)", "dedicated"],
    ["ANGLE (Intel, Intel(R) Arc(TM) A770 Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)", "dedicated"],
    ["ANGLE (Apple, ANGLE Metal Renderer: Apple M2 Pro, Unspecified Version)", "dedicated"],
    ["ANGLE (Intel, Intel(R) UHD Graphics 620 (0x00005917) Direct3D11 vs_5_0 ps_5_0, D3D11)", "integrated"],
    ["ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)", "integrated"],
    ["ANGLE (AMD, AMD Radeon(TM) Graphics (0x00001638) Direct3D11 vs_5_0 ps_5_0, D3D11)", "integrated"],
    ["Mesa Intel(R) HD Graphics 520 (SKL GT2)", "integrated"],
    ["ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver)", "software"],
    ["ANGLE (Microsoft, Microsoft Basic Render Driver Direct3D11 vs_5_0 ps_5_0, D3D11)", "software"],
    ["llvmpipe (LLVM 15.0.7, 256 bits)", "software"],
    ["WebKit WebGL", "unknown"],
    ["", "unknown"],
  ])("%s -> %s", (renderer, tier) => {
    expect(classifyRenderer(renderer)).toBe(tier);
  });
});

describe("choosing the background", () => {
  it("auto follows the graphics: dedicated -> neural, integrated -> fibers, software -> static", () => {
    expect(resolveBackground("auto", "dedicated", "auto").effect).toBe("neural");
    expect(resolveBackground("auto", "integrated", "auto").effect).toBe("fibers");
    expect(resolveBackground("auto", "software", "auto").effect).toBe("static");
  });

  it("auto with graphics it can't name falls back to the startup hint, else the light animation", () => {
    expect(resolveBackground("auto", "unknown", "neural").effect).toBe("neural");
    expect(resolveBackground("auto", "unknown", "static").effect).toBe("static");
    expect(resolveBackground("auto", "unknown", "fibers").effect).toBe("fibers");
    expect(resolveBackground("auto", "unknown", undefined).effect).toBe("fibers");
  });

  it("an explicit choice overrides auto, whatever the graphics", () => {
    expect(resolveBackground("animated", "software", "static").effect).toBe("neural");
    expect(resolveBackground("static", "dedicated", "neural").effect).toBe("static");
  });

  it("says why it chose", () => {
    expect(resolveBackground("auto", "integrated", "auto").reason).toBe("Auto: no dedicated graphics found, so the lightweight fibers.");
    expect(resolveBackground("static", "dedicated", "auto").reason).toBe("You chose a still background.");
  });
});

describe("the background setting", () => {
  it("defaults to auto, and keeps a choice in this browser", () => {
    expect(readBackgroundChoice()).toBe("auto");
    writeBackgroundChoice("static");
    expect(readBackgroundChoice()).toBe("static");
    window.localStorage.setItem("researchnexus.pref.background", "sparkles");
    expect(readBackgroundChoice()).toBe("auto");
  });

  it("carries over the older still-background preference", () => {
    window.localStorage.setItem("researchnexus.pref.backgroundMotion", "still");
    expect(readBackgroundChoice()).toBe("static");
    window.localStorage.setItem("researchnexus.pref.backgroundMotion", "moving");
    expect(readBackgroundChoice()).toBe("auto");
  });
});
