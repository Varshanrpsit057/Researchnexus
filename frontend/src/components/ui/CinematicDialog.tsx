"use client";

import { useEffect, useId, useImperativeHandle, useRef, type ReactNode, type Ref } from "react";
import { X } from "@phosphor-icons/react/dist/ssr";
import { CINEMATIC } from "@/lib/cinematic-theme";

export interface CinematicDialogHandle {
  show: () => void;
  close: () => void;
}

interface CinematicDialogProps {
  ref: Ref<CinematicDialogHandle>;
  title: string;
  children: ReactNode;
  onClose?: () => void;
}

/** The same native <dialog> pattern as the real (light-system) Dialog
 * component -- showModal/close, the browser's own Esc handling and
 * outside-content inertness, no hand-rolled focus trap -- restyled dark for
 * cinematic pages instead of duplicating that logic with a different look. */
export function CinematicDialog({ ref, title, children, onClose }: CinematicDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  // one id per dialog: a page may hold several (one per workspace row)
  const titleId = useId();

  useImperativeHandle(ref, () => ({
    show: () => dialogRef.current?.showModal(),
    close: () => dialogRef.current?.close(),
  }));

  useEffect(() => {
    const node = dialogRef.current;
    if (!node) return;
    const handleClose = () => onClose?.();
    node.addEventListener("close", handleClose);
    return () => node.removeEventListener("close", handleClose);
  }, [onClose]);

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby={titleId}
      className="m-auto w-full max-w-md rounded-2xl p-0 text-[color:var(--dlg-ink)] backdrop:bg-black/60 backdrop:backdrop-blur-[2px] open:animate-[dialog-in_180ms_cubic-bezier(0.23,1,0.32,1)]"
      style={
        {
          background: CINEMATIC.glass2,
          border: `1px solid ${CINEMATIC.lineStrong}`,
          boxShadow: "0 30px 80px -30px rgba(0,0,0,.75)",
          "--dlg-ink": CINEMATIC.ink,
        } as React.CSSProperties
      }
    >
      <div className="flex items-center justify-between border-b px-5 py-3.5" style={{ borderColor: CINEMATIC.line }}>
        <h2 id={titleId} className="text-sm font-semibold">
          {title}
        </h2>
        <button
          type="button"
          onClick={() => dialogRef.current?.close()}
          aria-label="Close dialog"
          className="rounded-full p-1.5 transition-colors hover:bg-white/10"
          style={{ color: CINEMATIC.muted }}
        >
          <X className="size-4" aria-hidden />
        </button>
      </div>
      <div className="p-5">{children}</div>
    </dialog>
  );
}
