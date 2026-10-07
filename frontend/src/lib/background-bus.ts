import type { MorphTarget } from "@/components/effects/constellation/field";

export type { MorphTarget };

/** Commands a page can send the one global background, whichever effect it
 * is drawing (neural network, GhostFibers or still). */
export type BackgroundCommand = { type: "morph"; targets: MorphTarget[] } | { type: "release" };

type Listener = (command: BackgroundCommand) => void;

const listeners = new Set<Listener>();
// The background's current state, not a one-off message: an effect mounted
// later -- the first one, or another one after the background setting
// changes while the graph is open -- starts in it at once.
let current: Extract<BackgroundCommand, { type: "morph" }> | null = null;

export function sendToBackground(command: BackgroundCommand): void {
  current = command.type === "morph" ? command : null;
  for (const listener of listeners) listener(command);
}

export function onBackgroundCommand(listener: Listener): () => void {
  listeners.add(listener);
  if (current) listener(current);
  return () => {
    listeners.delete(listener);
  };
}

/** Whether a page is holding the background in its graph state. */
export function backgroundMorphed(): boolean {
  return current !== null;
}
