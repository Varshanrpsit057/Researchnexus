"use client";

import { useEffect, useImperativeHandle, useRef, type ReactNode, type Ref } from "react";
import { X } from "@phosphor-icons/react/dist/ssr";

export interface DialogHandle {
  show: () => void;
  close: () => void;
}

interface DialogProps {
  ref: Ref<DialogHandle>;
  title: string;
  children: ReactNode;
  onClose?: () => void;
}

/** Native <dialog> in modal state: the browser makes outside content inert
 * and handles Esc-to-close and focus containment on its own -- no
 * hand-rolled focus trap (modern-web-guidance §11). */
export function Dialog({ ref, title, children, onClose }: DialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);

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
      aria-labelledby="dialog-title"
      className="m-auto w-full max-w-md border border-border-strong bg-surface-raised p-0
        shadow-[0_16px_40px_rgb(var(--shadow-color)/0.22)] backdrop:bg-ink/40 backdrop:backdrop-blur-[2px]
        open:animate-[dialog-in_180ms_cubic-bezier(0.23,1,0.32,1)]"
    >
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 id="dialog-title" className="text-sm font-semibold text-ink">
          {title}
        </h2>
        <button
          type="button"
          onClick={() => dialogRef.current?.close()}
          aria-label="Close dialog"
          className="rounded-sm p-1 text-ink-muted hover:bg-surface-sunken hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--focus-ring)]"
        >
          <X className="size-4" aria-hidden />
        </button>
      </div>
      <div className="p-4">{children}</div>
    </dialog>
  );
}
