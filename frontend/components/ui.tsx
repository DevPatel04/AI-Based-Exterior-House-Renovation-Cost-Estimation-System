"use client";

import clsx from "clsx";
import { ReactNode, useEffect, useId, useRef } from "react";
import { Icon, IconName } from "@/components/icons";

/* ---------- Spinner ---------- */

export function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg className={clsx("animate-spin", className)} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function PageLoader({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex min-h-[40vh] items-center justify-center gap-3 text-sm text-slate-500" role="status">
      <Spinner className="h-5 w-5 text-brand-600" />
      {label}
    </div>
  );
}

/* ---------- Page header ---------- */

export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  eyebrow?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        {eyebrow && <div className="mb-2">{eyebrow}</div>}
        <h1 className="text-2xl font-bold text-slate-900 sm:text-3xl">{title}</h1>
        {description && <p className="mt-1.5 max-w-2xl text-sm text-slate-600 sm:text-base">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

/* ---------- Card ---------- */

export function Card({
  title,
  description,
  actions,
  children,
  className,
  bodyClassName,
}: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={clsx("card-panel", className)}>
      {(title || actions) && (
        <div className="flex flex-col gap-3 border-b border-slate-100 px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <div className="min-w-0">
            {title && <h2 className="text-base font-semibold text-slate-900">{title}</h2>}
            {description && <p className="mt-0.5 text-sm text-slate-500">{description}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={clsx("p-5 sm:p-6", bodyClassName)}>{children}</div>
    </section>
  );
}

/* ---------- Alert ---------- */

const ALERT_STYLES = {
  error: { box: "bg-red-50 border-red-200 text-red-800", icon: "alert" as IconName, iconColor: "text-red-500" },
  success: { box: "bg-emerald-50 border-emerald-200 text-emerald-800", icon: "checkCircle" as IconName, iconColor: "text-emerald-500" },
  info: { box: "bg-sky-50 border-sky-200 text-sky-800", icon: "info" as IconName, iconColor: "text-sky-500" },
  warning: { box: "bg-amber-50 border-amber-200 text-amber-900", icon: "alert" as IconName, iconColor: "text-amber-500" },
};

export function Alert({
  tone = "info",
  title,
  children,
  onDismiss,
  className,
}: {
  tone?: keyof typeof ALERT_STYLES;
  title?: ReactNode;
  children?: ReactNode;
  onDismiss?: () => void;
  className?: string;
}) {
  const s = ALERT_STYLES[tone];
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={clsx("flex items-start gap-3 rounded-xl border px-4 py-3 text-sm", s.box, className)}
    >
      <Icon name={s.icon} className={clsx("mt-0.5 h-4 w-4 shrink-0", s.iconColor)} />
      <div className="min-w-0 flex-1">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className={clsx(title && "mt-0.5", "break-words")}>{children}</div>}
      </div>
      {onDismiss && (
        <button type="button" onClick={onDismiss} className="-m-1 rounded p-1 opacity-60 hover:opacity-100" aria-label="Dismiss">
          <Icon name="x" className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}

/* ---------- Badge ---------- */

const BADGE_TONES = {
  neutral: "bg-slate-100 text-slate-700 ring-slate-200",
  brand: "bg-brand-50 text-brand-700 ring-brand-200",
  accent: "bg-accent-50 text-accent-700 ring-accent-200",
  success: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  warning: "bg-amber-50 text-amber-800 ring-amber-200",
  danger: "bg-red-50 text-red-700 ring-red-200",
  info: "bg-sky-50 text-sky-700 ring-sky-200",
  violet: "bg-violet-50 text-violet-700 ring-violet-200",
};
export type BadgeTone = keyof typeof BADGE_TONES;

export function Badge({
  tone = "neutral",
  children,
  className,
  dot,
}: {
  tone?: BadgeTone;
  children: ReactNode;
  className?: string;
  dot?: boolean;
}) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        BADGE_TONES[tone],
        className
      )}
    >
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}

const STATUS_TONES: Record<string, BadgeTone> = {
  draft: "neutral",
  designed: "info",
  estimated: "warning",
  reported: "success",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <Badge tone={STATUS_TONES[status] || "neutral"} dot>
      {humanize(status)}
    </Badge>
  );
}

/* ---------- Form field ---------- */

export function Field({
  label,
  hint,
  error,
  required,
  children,
  className,
}: {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  /** Render prop receives the generated id to wire label ↔ control. */
  children: (id: string) => ReactNode;
  className?: string;
}) {
  const id = useId();
  return (
    <div className={className}>
      <label htmlFor={id} className="label mb-1.5">
        {label}
        {required && <span className="ml-0.5 text-red-500" aria-hidden="true">*</span>}
      </label>
      {children(id)}
      {error ? <p className="mt-1.5 text-xs text-red-600">{error}</p> : hint ? <p className="hint">{hint}</p> : null}
    </div>
  );
}

/* ---------- Empty state ---------- */

export function EmptyState({
  icon = "folder",
  title,
  description,
  action,
  className,
}: {
  icon?: IconName;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={clsx(
        "flex flex-col items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-white/60 px-6 py-12 text-center",
        className
      )}
    >
      <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-brand-50 text-brand-600">
        <Icon name={icon} className="h-6 w-6" />
      </div>
      <h3 className="text-base font-semibold text-slate-900">{title}</h3>
      {description && <p className="mt-1 max-w-sm text-sm text-slate-500">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

/* ---------- Stat ---------- */

export function Stat({
  label,
  value,
  emphasis,
  hint,
}: {
  label: ReactNode;
  value: ReactNode;
  emphasis?: boolean;
  hint?: ReactNode;
}) {
  return (
    <div
      className={clsx(
        "rounded-xl border p-4",
        emphasis ? "border-brand-200 bg-brand-50" : "border-slate-200 bg-white"
      )}
    >
      <p className={clsx("text-xs font-medium uppercase tracking-wide", emphasis ? "text-brand-700" : "text-slate-500")}>
        {label}
      </p>
      <p className={clsx("mt-1 font-bold tabular-nums", emphasis ? "text-2xl text-brand-800" : "text-xl text-slate-900")}>
        {value}
      </p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

/* ---------- Modal ---------- */

export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  footer,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    const prevFocus = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onCloseRef.current();
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    // Focus first focusable control inside the dialog
    const first = panelRef.current?.querySelector<HTMLElement>(
      "input, select, textarea, button:not([data-close])"
    );
    first?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
      prevFocus?.focus?.();
    };
  }, [open]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center p-0 sm:items-center sm:p-4">
      <div className="absolute inset-0 animate-fade-in bg-slate-900/40 backdrop-blur-[2px]" onClick={onClose} />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative w-full max-w-lg animate-slide-up rounded-t-2xl bg-white shadow-pop sm:rounded-2xl"
      >
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-6 py-4">
          <div>
            <h2 id={titleId} className="text-lg font-semibold text-slate-900">
              {title}
            </h2>
            {description && <p className="mt-0.5 text-sm text-slate-500">{description}</p>}
          </div>
          <button type="button" data-close onClick={onClose} className="btn-icon -mr-2" aria-label="Close dialog">
            <Icon name="x" className="h-5 w-5" />
          </button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto px-6 py-5">{children}</div>
        {footer && (
          <div className="flex flex-col-reverse gap-2 border-t border-slate-100 bg-slate-50/60 px-6 py-4 sm:flex-row sm:justify-end rounded-b-2xl">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}

/* ---------- Helpers ---------- */

/** "main_wall" → "Main wall" */
export function humanize(value?: string | null) {
  if (!value) return "";
  const s = value.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 });
export function formatINR(value: number | string | null | undefined) {
  const n = Number(value);
  return Number.isFinite(n) ? inr.format(n) : "—";
}

const num = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });
export function formatNumber(value: number | string | null | undefined) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? num.format(n) : String(value);
}

export function formatDate(value?: string | null) {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function initials(name?: string | null) {
  if (!name) return "?";
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]!.toUpperCase())
    .join("");
}

export function errorMessage(err: unknown, fallback = "Something went wrong") {
  if (err instanceof Error && err.message) return err.message;
  if (typeof err === "string" && err) return err;
  return fallback;
}

/* ---------- File button (styled, keyboard accessible file picker) ---------- */

export function FileButton({
  onFile,
  accept = "image/*",
  busy,
  disabled,
  children,
  className = "btn-outline",
}: {
  onFile: (file: File) => void;
  accept?: string;
  busy?: boolean;
  disabled?: boolean;
  children: ReactNode;
  className?: string;
}) {
  const id = useId();
  const inactive = busy || disabled;
  return (
    <span className="inline-flex">
      <input
        id={id}
        type="file"
        accept={accept}
        disabled={inactive}
        className="peer sr-only"
        onChange={(e) => {
          const f = e.target.files?.[0];
          e.target.value = "";
          if (f) onFile(f);
        }}
      />
      <label
        htmlFor={id}
        className={clsx(
          className,
          "cursor-pointer peer-focus-visible:ring-2 peer-focus-visible:ring-brand-500/60 peer-focus-visible:ring-offset-2",
          inactive && "pointer-events-none opacity-60"
        )}
      >
        {busy ? <Spinner /> : <Icon name="upload" />}
        {children}
      </label>
    </span>
  );
}
