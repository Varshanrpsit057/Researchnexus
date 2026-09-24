/* Worker entry: runs the constellation engine on an OffscreenCanvas handed
 * over by the page, so the background's per-frame work never competes with
 * the app's own UI thread. */

import { startEngine, type Engine, type EngineOptions } from "./engine";

export type ToWorker =
  | { type: "init"; canvas: OffscreenCanvas; options: EngineOptions }
  | { type: "resize"; width: number; height: number; dpr: number }
  | { type: "pointer"; x: number; y: number }
  | { type: "visible"; visible: boolean }
  | { type: "stop" };

export type FromWorker = { type: "ready"; renderer: Engine["rendererName"] } | { type: "failed" };

// typed narrowly instead of pulling the "webworker" lib into a DOM project
const scope = self as unknown as {
  onmessage: ((e: MessageEvent<ToWorker>) => void) | null;
  postMessage(message: FromWorker): void;
};

let engine: Engine | null = null;

scope.onmessage = (e) => {
  const msg = e.data;
  switch (msg.type) {
    case "init":
      engine = startEngine(msg.canvas, msg.options);
      scope.postMessage(engine ? { type: "ready", renderer: engine.rendererName } : { type: "failed" });
      break;
    case "resize":
      engine?.resize(msg.width, msg.height, msg.dpr);
      break;
    case "pointer":
      engine?.pointer(msg.x, msg.y);
      break;
    case "visible":
      engine?.setVisible(msg.visible);
      break;
    case "stop":
      engine?.stop();
      engine = null;
      break;
  }
};
