import { WarningCircle } from "@phosphor-icons/react/dist/ssr";
import { CINEMATIC } from "@/lib/cinematic-theme";

// Shared by the workspace page and its add-papers panel.
export const C = CINEMATIC;
export const focusRing = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#5df0a8]";
export const primaryButton = {
  color: C.mintInk,
  background: `linear-gradient(180deg, ${C.mint}, ${C.mint2})`,
} as const;
export const quietButton = { background: "rgba(255,255,255,.05)", border: `1px solid ${C.lineStrong}` } as const;
export const panel = { background: C.glass, border: `1px solid ${C.line}` } as const;

export function InlineError({ message }: { message: string }) {
  return (
    <p role="alert" className="flex items-start gap-1.5 text-sm" style={{ color: C.danger }}>
      <WarningCircle className="mt-0.5 size-4 shrink-0" weight="bold" aria-hidden />
      {message}
    </p>
  );
}
