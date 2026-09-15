import { forwardRef, useId, type InputHTMLAttributes, type ReactNode, type TextareaHTMLAttributes } from "react";

interface FieldWrapperProps {
  label: string;
  hint?: ReactNode;
  error?: string;
  htmlFor: string;
  required?: boolean;
  children: ReactNode;
}

export function FieldWrapper({ label, hint, error, htmlFor, required, children }: FieldWrapperProps) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-sm font-medium text-ink">
        {label}
        {required && (
          <span aria-hidden className="text-danger">
            {" "}
            *
          </span>
        )}
      </label>
      {hint && (
        <p id={`${htmlFor}-hint`} className="text-xs text-ink-muted">
          {hint}
        </p>
      )}
      {children}
      {error && (
        <p id={`${htmlFor}-error`} role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

interface TextInputProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  hint?: ReactNode;
  error?: string;
}

export const TextInput = forwardRef<HTMLInputElement, TextInputProps>(function TextInput(
  { label, hint, error, id, className = "", ...props },
  ref
) {
  const autoId = useId();
  const inputId = id ?? autoId;
  const describedBy = [hint ? `${inputId}-hint` : null, error ? `${inputId}-error` : null].filter(Boolean).join(" ") || undefined;

  return (
    <FieldWrapper label={label} hint={hint} error={error} htmlFor={inputId} required={props.required}>
      <input
        ref={ref}
        id={inputId}
        aria-describedby={describedBy}
        aria-invalid={error ? true : undefined}
        className={`h-10 rounded-sm border border-border-strong bg-surface-raised px-3 text-sm text-ink
          placeholder:text-ink-subtle transition-colors duration-150
          focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--focus-ring)]
          user-invalid:border-danger user-invalid:bg-danger-wash
          disabled:cursor-not-allowed disabled:opacity-60 ${className}`}
        {...props}
      />
    </FieldWrapper>
  );
});

interface TextAreaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label: string;
  hint?: ReactNode;
  error?: string;
}

export const TextArea = forwardRef<HTMLTextAreaElement, TextAreaProps>(function TextArea(
  { label, hint, error, id, className = "", ...props },
  ref
) {
  const autoId = useId();
  const inputId = id ?? autoId;
  const describedBy = [hint ? `${inputId}-hint` : null, error ? `${inputId}-error` : null].filter(Boolean).join(" ") || undefined;

  return (
    <FieldWrapper label={label} hint={hint} error={error} htmlFor={inputId} required={props.required}>
      <textarea
        ref={ref}
        id={inputId}
        aria-describedby={describedBy}
        aria-invalid={error ? true : undefined}
        className={`min-h-24 rounded-sm border border-border-strong bg-surface-raised px-3 py-2 text-sm text-ink
          placeholder:text-ink-subtle transition-colors duration-150
          focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--focus-ring)]
          disabled:cursor-not-allowed disabled:opacity-60 ${className}`}
        {...props}
      />
    </FieldWrapper>
  );
});
