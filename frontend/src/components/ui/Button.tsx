import { forwardRef, type ButtonHTMLAttributes } from "react";
import { CircleNotch } from "@phosphor-icons/react/dist/ssr";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
}

const variantClasses: Record<Variant, string> = {
  primary:
    "bg-accent text-accent-foreground hover:bg-accent-strong disabled:hover:bg-accent",
  secondary:
    "bg-surface-raised text-ink border border-border-strong hover:border-ink-subtle disabled:hover:border-border-strong",
  ghost: "text-ink-muted hover:text-ink hover:bg-surface-sunken",
  danger: "bg-danger text-accent-foreground hover:brightness-110",
};

const sizeClasses: Record<Size, string> = {
  sm: "h-8 px-3 text-sm gap-1.5",
  md: "h-10 px-4 text-sm gap-2",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", loading = false, disabled, className = "", children, ...props },
  ref
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={`inline-flex items-center justify-center rounded-sm font-medium
        transition-[transform,background-color,border-color,color] duration-150 ease-out
        active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100
        focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring)]
        ${variantClasses[variant]} ${sizeClasses[size]} ${className}`}
      {...props}
    >
      {loading && <CircleNotch className="size-4 animate-spin" aria-hidden weight="bold" />}
      {children}
    </button>
  );
});
