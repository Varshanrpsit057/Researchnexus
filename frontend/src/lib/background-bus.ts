import type { MorphTarget } from "@/components/effects/constellation/field";

export type { MorphTarget };

/** Commands a page can send the one global constellation background. */
export type BackgroundCommand = { type: "morph"; targets: MorphTarget[] } | { type: "release" };

type Listener = (command: BackgroundCommand) => void;

const listeners = new Set<Listener>();
// A command sent before the background has mounted is kept until it does.
let pending: BackgroundCommand | null = null;

export function sendToBackground(command: BackgroundCommand): void {
  if (listeners.size === 0) {
    pending = command;
    return;
  }
  for (const listener of listeners) listener(command);
}

export function onBackgroundCommand(listener: Listener): () => void {
  listeners.add(listener);
  if (pending) {
    const command = pending;
    pending = null;
    listener(command);
  }
  return () => {
    listeners.delete(listener);
  };
}
