import Link from "next/link";
import { WarningCircle } from "@phosphor-icons/react/dist/ssr";
import { ApiError } from "@/lib/api/client";
import { CINEMATIC } from "@/lib/cinematic-theme";

// Shared by the workspace pages (overview, trail) and the add-papers panel.
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

/** A workspace that could not be loaded: gone (404) or a failure worth retrying. */
export function WorkspaceLoadError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const notFound = error instanceof ApiError && error.status === 404;
  return (
    <div className="mx-auto mt-10 max-w-md rounded-2xl px-6 py-12 text-center" style={{ ...panel, border: `1px dashed ${C.lineStrong}` }}>
      <h1 className="text-lg font-bold">{notFound ? "Workspace not found" : "Could not load this workspace"}</h1>
      <p className="mt-2 text-sm" style={{ color: C.muted }}>
        {notFound
          ? "It may have been deleted, or it belongs to a different account."
          : error instanceof ApiError && error.status >= 500
            ? "The server hit an error while loading it. Try again in a moment."
            : error instanceof ApiError
              ? `${error.message}. Try again.`
              : "The server couldn't be reached. Check your connection and try again."}
      </p>
      <div className="mt-6 flex justify-center gap-2">
        {notFound ? (
          <Link href="/workspaces" className={`rounded-full px-5 py-2.5 text-sm font-semibold ${focusRing}`} style={primaryButton}>
            All workspaces
          </Link>
        ) : (
          <button type="button" onClick={onRetry} className={`rounded-full px-5 py-2.5 text-sm font-semibold ${focusRing}`} style={primaryButton}>
            Try again
          </button>
        )}
      </div>
    </div>
  );
}
