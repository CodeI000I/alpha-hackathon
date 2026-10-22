import { forwardRef, useId } from "react";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react";
import { Icon } from "./Icon";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost";
  size?: "default" | "large";
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "default", loading = false, className = "", disabled, children, type = "button", ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={`ui-button ui-button--${variant} ui-button--${size} ${className}`.trim()}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading && <span className="ui-spinner" aria-hidden="true" />}
      {children}
    </button>
  );
});

interface FieldMeta {
  label: string;
  hint?: string;
  error?: string;
}

export interface TextFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "size">, FieldMeta {}

export const TextField = forwardRef<HTMLInputElement, TextFieldProps>(function TextField(
  { label, hint, error, id, className = "", ...props },
  ref,
) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const describedBy = [hint && `${inputId}-hint`, error && `${inputId}-error`].filter(Boolean).join(" ") || undefined;

  return (
    <label className={`ui-field ${className}`.trim()} htmlFor={inputId}>
      <span className="ui-field__label">{label}</span>
      <input
        ref={ref}
        id={inputId}
        className="ui-input"
        aria-invalid={Boolean(error)}
        aria-describedby={describedBy}
        {...props}
      />
      {hint && (
        <span className="ui-field__hint" id={`${inputId}-hint`}>
          {hint}
        </span>
      )}
      {error && (
        <span className="ui-field__error" id={`${inputId}-error`} role="alert">
          {error}
        </span>
      )}
    </label>
  );
});

export interface SearchFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "size"> {
  label?: string;
  hideLabel?: boolean;
  onClear?: () => void;
}

export const SearchField = forwardRef<HTMLInputElement, SearchFieldProps>(function SearchField(
  { label = "Поиск", hideLabel = true, onClear, className = "", value, defaultValue, ...props },
  ref,
) {
  const hasValue = value !== undefined ? String(value).length > 0 : defaultValue !== undefined && String(defaultValue).length > 0;

  return (
    <label className={`ui-search ${className}`.trim()}>
      <span className={hideLabel ? "sr-only" : "ui-search__label"}>{label}</span>
      <Icon name="search" size={19} />
      <input ref={ref} type="search" value={value} defaultValue={defaultValue} {...props} />
      {hasValue && onClear && (
        <button type="button" className="ui-icon-button" onClick={onClear} aria-label="Очистить поиск">
          <Icon name="close" size={17} />
        </button>
      )}
    </label>
  );
});

export type BadgeTone = "event" | "risk" | "opportunity" | "demo" | "neutral";

export function Badge({ tone = "neutral", children, className = "" }: { tone?: BadgeTone; children: ReactNode; className?: string }) {
  return <span className={`ui-badge ui-badge--${tone} ${className}`.trim()}>{children}</span>;
}

export function DemoBadge({ className = "", children = "Демо" }: { className?: string; children?: ReactNode }) {
  return (
    <Badge tone="demo" className={className}>
      {children}
    </Badge>
  );
}

type StateKind = "loading" | "empty" | "error";

export interface StatePanelProps {
  state?: StateKind;
  tone?: "error";
  title?: string;
  description?: string;
  text?: string;
  action?: ReactNode;
  compact?: boolean;
}

const STATE_DEFAULTS: Record<StateKind, { title: string; description: string }> = {
  loading: { title: "Загружаем данные", description: "Это займёт несколько секунд." },
  empty: { title: "Здесь пока пусто", description: "Данные появятся, когда будут готовы." },
  error: { title: "Не получилось загрузить данные", description: "Проверьте соединение и попробуйте ещё раз." },
};

export function StatePanel({ state: requestedState, tone, title, description, text, action, compact = false }: StatePanelProps) {
  const state = requestedState ?? (tone === "error" ? "error" : "empty");
  const fallback = STATE_DEFAULTS[state];
  return (
    <div
      className={`state-panel state-panel--${state}${compact ? " state-panel--compact" : ""}`}
      role={state === "error" ? "alert" : "status"}
      aria-live={state === "loading" ? "polite" : undefined}
    >
      <span className="state-panel__icon" aria-hidden="true">
        {state === "loading" ? <span className="ui-spinner" /> : <Icon name={state === "error" ? "close" : "spark"} size={22} />}
      </span>
      <div>
        <h2>{title ?? fallback.title}</h2>
        <p>{description ?? text ?? fallback.description}</p>
        {action && <div className="state-panel__action">{action}</div>}
      </div>
    </div>
  );
}
