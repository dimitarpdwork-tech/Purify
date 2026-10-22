"use client";

import { forwardRef, useEffect, useId, useRef, useState } from "react";
import type { ApiError } from "@/lib/api";

export function cx(...xs: (string | false | null | undefined)[]) {
  return xs.filter(Boolean).join(" ");
}

/* ---------------------------------------------------------------- Tooltip */
export function Tip({ text, children, className, side = "top" }: { text: React.ReactNode; children: React.ReactNode; className?: string; side?: "top" | "bottom" }) {
  const id = useId();
  return (
    <span className={cx("group/tip relative inline-flex", className)} aria-describedby={id} tabIndex={-1}>
      {children}
      <span id={id} role="tooltip"
        className={cx(
          "pointer-events-none invisible absolute left-1/2 z-50 w-max max-w-[280px] -translate-x-1/2 rounded border border-rule bg-ink px-2 py-1.5 text-xs font-normal normal-case leading-snug text-paper opacity-0 shadow-md transition-opacity group-hover/tip:visible group-hover/tip:opacity-100 group-focus-within/tip:visible group-focus-within/tip:opacity-100",
          side === "top" ? "bottom-full mb-1.5" : "top-full mt-1.5")}>
        {text}
      </span>
    </span>
  );
}

/* ---------------------------------------------------------------- Badge */
type Tone = "neutral" | "accent" | "active" | "possible" | "declared" | "danger" | "outline";
const TONES: Record<Tone, string> = {
  neutral: "bg-sunken text-muted border-transparent",
  accent: "bg-accent-soft text-accent border-transparent",
  active: "bg-active-soft text-active border-transparent",
  possible: "bg-possible-soft text-possible border-transparent",
  declared: "bg-declared-soft text-declared border-transparent",
  danger: "bg-danger-soft text-danger border-transparent",
  outline: "bg-transparent text-muted border-rule",
};
export function Badge({ tone = "neutral", children, className, title }: { tone?: Tone; children: React.ReactNode; className?: string; title?: string }) {
  return (
    <span title={title} className={cx("inline-flex h-[18px] items-center gap-1 whitespace-nowrap rounded-sm border px-1.5 text-2xs font-medium", TONES[tone], className)}>
      {children}
    </span>
  );
}

/* ---------------------------------------------------------------- Button */
type BtnVariant = "primary" | "secondary" | "ghost" | "danger";
export const Button = forwardRef<HTMLButtonElement, React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: BtnVariant; size?: "sm" | "md"; busy?: boolean }>(
  function Button({ variant = "secondary", size = "md", busy, className, children, disabled, ...rest }, ref) {
    return (
      <button ref={ref} disabled={disabled || busy}
        className={cx(
          "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded border font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
          size === "sm" ? "h-6 px-2 text-xs" : "h-7 px-2.5 text-sm",
          variant === "primary" && "border-accent bg-accent text-white hover:bg-accent/90 dark:text-paper",
          variant === "secondary" && "border-rule bg-panel text-ink hover:bg-sunken",
          variant === "ghost" && "border-transparent bg-transparent text-muted hover:bg-sunken hover:text-ink",
          variant === "danger" && "border-danger/50 bg-panel text-danger hover:bg-danger-soft",
          className)}
        {...rest}>
        {busy && <Spinner />}
        {children}
      </button>
    );
  });

export function Spinner({ className }: { className?: string }) {
  return <span aria-hidden className={cx("inline-block h-3 w-3 animate-spin rounded-full border-[1.5px] border-current border-r-transparent", className)} />;
}

/* ---------------------------------------------------------------- Panel */
export function Panel({ title, actions, children, className, bodyClass, note }: {
  title?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode; className?: string; bodyClass?: string; note?: React.ReactNode;
}) {
  return (
    <section className={cx("rounded border border-rule bg-panel", className)}>
      {(title || actions) && (
        <header className="flex min-h-[34px] items-center justify-between gap-2 border-b border-rule px-3 py-1.5">
          <div className="min-w-0">
            {title && <h2 className="truncate text-sm font-semibold text-ink">{title}</h2>}
            {note && <p className="text-xs text-muted">{note}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-1.5">{actions}</div>}
        </header>
      )}
      <div className={cx(bodyClass ?? "p-3")}>{children}</div>
    </section>
  );
}

/* ---------------------------------------------------------------- Inputs */
const fieldCls = "h-7 w-full rounded border border-rule bg-panel px-2 text-sm text-ink placeholder:text-faint focus:border-accent focus:outline-none disabled:opacity-60";
export const Input = forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...rest }, ref) {
  return <input ref={ref} className={cx(fieldCls, className)} {...rest} />;
});
export const Textarea = forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, ...rest }, ref) {
  return <textarea ref={ref} className={cx(fieldCls, "h-auto py-1.5 leading-snug", className)} {...rest} />;
});
export function Select({ className, children, ...rest }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={cx(fieldCls, "pr-6", className)} {...rest}>{children}</select>;
}
export function Field({ label, hint, children, className }: { label: string; hint?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <label className={cx("block", className)}>
      <span className="mb-1 block text-xs font-medium text-muted">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-2xs text-faint">{hint}</span>}
    </label>
  );
}
export function Checkbox({ checked, onChange, label, className, indeterminate }: { checked: boolean; onChange: (v: boolean) => void; label?: React.ReactNode; className?: string; indeterminate?: boolean }) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => { if (ref.current) ref.current.indeterminate = !!indeterminate; }, [indeterminate]);
  return (
    <label className={cx("inline-flex cursor-pointer items-center gap-1.5 text-sm", className)}>
      <input ref={ref} type="checkbox" className="h-3.5 w-3.5 accent-[rgb(var(--accent))]" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

/** Popover multi-select with search. Values are strings; labels optional. */
export function MultiSelect({ options, value, onChange, placeholder = "Any", labels, className }: {
  options: string[]; value: string[]; onChange: (v: string[]) => void; placeholder?: string; labels?: (v: string) => React.ReactNode; className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);
  const shown = options.filter((o) => !q || o.toLowerCase().includes(q.toLowerCase()) || String(labels?.(o) ?? "").toLowerCase().includes(q.toLowerCase()));
  const toggle = (o: string) => onChange(value.includes(o) ? value.filter((x) => x !== o) : [...value, o]);
  return (
    <div ref={box} className={cx("relative", className)}>
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}
        className={cx(fieldCls, "flex items-center justify-between text-left")}>
        <span className={cx("truncate", !value.length && "text-faint")}>
          {value.length === 0 ? placeholder : value.length <= 2 ? value.map((v) => (typeof labels?.(v) === "string" ? labels(v) : v)).join(", ") : `${value.length} selected`}
        </span>
        <span className="ml-1 text-faint" aria-hidden>▾</span>
      </button>
      {open && (
        <div className="absolute left-0 z-40 mt-1 w-full min-w-[220px] rounded border border-rule bg-panel shadow-lg">
          {options.length > 8 && (
            <div className="border-b border-rule p-1.5"><Input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search…" /></div>
          )}
          <div className="max-h-64 overflow-auto py-1">
            {shown.length === 0 && <div className="px-2 py-1.5 text-xs text-faint">No matches</div>}
            {shown.map((o) => (
              <label key={o} className="flex cursor-pointer items-center gap-2 px-2 py-1 text-sm hover:bg-sunken">
                <input type="checkbox" className="h-3.5 w-3.5 accent-[rgb(var(--accent))]" checked={value.includes(o)} onChange={() => toggle(o)} />
                <span className="truncate">{labels ? labels(o) : o}</span>
              </label>
            ))}
          </div>
          {value.length > 0 && (
            <div className="border-t border-rule p-1 text-right"><Button size="sm" variant="ghost" onClick={() => onChange([])}>Clear</Button></div>
          )}
        </div>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- Tabs */
export function Tabs({ tabs, value, onChange }: { tabs: { id: string; label: React.ReactNode }[]; value: string; onChange: (id: string) => void }) {
  return (
    <div role="tablist" className="flex gap-0.5 overflow-x-auto border-b border-rule">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)}
          className={cx("-mb-px whitespace-nowrap border-b-2 px-3 py-1.5 text-sm transition-colors",
            value === t.id ? "border-accent font-medium text-ink" : "border-transparent text-muted hover:text-ink")}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------- Overlay: Modal + Drawer */
function useEsc(on: boolean, close: () => void) {
  useEffect(() => {
    if (!on) return;
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [on, close]);
}

export function Modal({ open, onClose, title, children, footer, width = 480 }: {
  open: boolean; onClose: () => void; title: string; children: React.ReactNode; footer?: React.ReactNode; width?: number;
}) {
  useEsc(open, onClose);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-ink/30 p-4 pt-[10vh]" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div role="dialog" aria-modal aria-label={title} className="w-full rounded border border-rule bg-panel shadow-xl" style={{ maxWidth: width }}>
        <header className="flex items-center justify-between border-b border-rule px-4 py-2">
          <h2 className="text-base font-semibold">{title}</h2>
          <button onClick={onClose} className="text-lg leading-none text-faint hover:text-ink" aria-label="Close">×</button>
        </header>
        <div className="max-h-[65vh] overflow-auto p-4">{children}</div>
        {footer && <footer className="flex justify-end gap-2 border-t border-rule px-4 py-2">{footer}</footer>}
      </div>
    </div>
  );
}

export function Drawer({ open, onClose, title, children, width = 720 }: { open: boolean; onClose: () => void; title: React.ReactNode; children: React.ReactNode; width?: number }) {
  useEsc(open, onClose);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-ink/25" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <aside role="dialog" aria-modal className="drawer-in flex h-full w-full flex-col border-l border-rule bg-panel shadow-xl" style={{ maxWidth: width }}>
        <header className="flex items-center justify-between gap-2 border-b border-rule px-4 py-2">
          <div className="min-w-0 text-base font-semibold">{title}</div>
          <button onClick={onClose} className="text-lg leading-none text-faint hover:text-ink" aria-label="Close">×</button>
        </header>
        <div className="min-h-0 flex-1 overflow-auto">{children}</div>
      </aside>
    </div>
  );
}

/* ---------------------------------------------------------------- States */
export function Loading({ label = "Loading…", className }: { label?: string; className?: string }) {
  return <div className={cx("flex items-center gap-2 px-3 py-6 text-sm text-muted", className)}><Spinner /> {label}</div>;
}
export function Empty({ title, children, className }: { title: string; children?: React.ReactNode; className?: string }) {
  return (
    <div className={cx("px-3 py-6 text-sm", className)}>
      <p className="font-medium text-ink">{title}</p>
      {children && <div className="mt-1 max-w-prose text-muted">{children}</div>}
    </div>
  );
}
export function ErrorState({ error, onRetry, className }: { error: ApiError | Error | null; onRetry?: () => void; className?: string }) {
  if (!error) return null;
  return (
    <div className={cx("flex items-start justify-between gap-3 rounded border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger", className)}>
      <span>{error.message}</span>
      {onRetry && <Button size="sm" variant="secondary" onClick={onRetry}>Retry</Button>}
    </div>
  );
}

/* ---------------------------------------------------------------- Misc */
export function KV({ rows, className }: { rows: [React.ReactNode, React.ReactNode][]; className?: string }) {
  return (
    <dl className={cx("grid grid-cols-[minmax(110px,max-content)_1fr] gap-x-4 gap-y-1 text-sm", className)}>
      {rows.map(([k, v], i) => (
        <div key={i} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="min-w-0 break-words">{v === null || v === undefined || v === "" ? <span className="text-faint">—</span> : v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Json({ value, className }: { value: unknown; className?: string }) {
  return (
    <pre className={cx("overflow-auto rounded bg-sunken p-2 font-mono text-2xs leading-relaxed text-ink", className)}>
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export function Dash() { return <span className="text-faint">—</span>; }

/** A tiny confidence meter: 0..1 as a 5-step bar with % label. */
export function Confidence({ value, className }: { value: number | null | undefined; className?: string }) {
  if (value === null || value === undefined) return <Dash />;
  const pct = Math.max(0, Math.min(1, value));
  return (
    <Tip text={`Evidence confidence ${Math.round(pct * 100)}% (how sure the engine is, not a revenue estimate)`}>
      <span className={cx("inline-flex items-center gap-1.5 tnum text-xs text-muted", className)}>
        <span className="relative h-1.5 w-10 overflow-hidden rounded-full bg-sunken">
          <span className={cx("absolute inset-y-0 left-0 rounded-full", pct >= 0.66 ? "bg-active" : pct >= 0.4 ? "bg-possible" : "bg-faint")} style={{ width: `${pct * 100}%` }} />
        </span>
        {Math.round(pct * 100)}%
      </span>
    </Tip>
  );
}

export function PageHeader({ title, sub, actions }: { title: React.ReactNode; sub?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
      <div className="min-w-0">
        <h1 className="text-[19px] font-semibold leading-7 tracking-[-0.01em]">{title}</h1>
        {sub && <p className="text-sm text-muted">{sub}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-1.5">{actions}</div>}
    </div>
  );
}
