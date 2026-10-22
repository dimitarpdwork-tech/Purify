"use client";

import Link from "next/link";
import { cruxLabel, fmtInt, humanize, OPPORTUNITY_LABELS, QUEUE_META, STATUS_META } from "@/lib/domain";
import type { AdStatus } from "@/lib/types";
import { Badge, cx, Dash, Tip } from "./ui";

/** Glyph per evidence state, so status is never conveyed by colour alone. */
function StatusGlyph({ status }: { status: AdStatus }) {
  const base = "inline-block h-[7px] w-[7px] shrink-0";
  switch (status) {
    case "DETECTED_ACTIVE_SIGNALS": return <span className={cx(base, "rounded-full bg-current")} />;
    case "POSSIBLE": return <span className={cx(base, "rounded-full border border-current")} style={{ background: "linear-gradient(90deg, currentColor 50%, transparent 50%)" }} />;
    case "DECLARED_AUTHORIZATION_ONLY": return <span className={cx(base, "rounded-[1px] border border-current")} />;
    case "NOT_OBSERVED": return <span className={cx(base, "rounded-full border border-current opacity-70")} />;
    case "SCAN_INCONCLUSIVE": return <span className={cx(base, "rounded-[1px] border border-dashed border-current")} />;
  }
}

const STATUS_CLS: Record<string, string> = {
  active: "bg-active-soft text-active",
  possible: "bg-possible-soft text-possible",
  declared: "bg-declared-soft text-declared",
  none: "bg-transparent text-faint border-rule",
  inconclusive: "hatch text-muted border-rule",
};

export function StatusBadge({ status, prefix, compact }: { status: string | null | undefined; prefix?: string; compact?: boolean }) {
  if (!status) {
    return (
      <Tip text="No scan result for this vendor yet.">
        <span className="inline-flex h-[18px] items-center rounded-sm border border-dashed border-rule px-1.5 text-2xs text-faint">{prefix ? `${prefix}: ` : ""}not scanned</span>
      </Tip>
    );
  }
  const meta = STATUS_META[status as AdStatus];
  if (!meta) return <Badge>{status}</Badge>;
  return (
    <Tip text={<><b className="font-semibold">{meta.label}.</b> {meta.tip}</>}>
      <span className={cx("inline-flex h-[18px] items-center gap-1 whitespace-nowrap rounded-sm border border-transparent px-1.5 text-2xs font-medium", STATUS_CLS[meta.tone])}>
        <StatusGlyph status={status as AdStatus} />
        {prefix && <span className="opacity-75">{prefix}</span>}
        {!compact && meta.label}
      </span>
    </Tip>
  );
}

export function StatusLegend() {
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
      {(Object.keys(STATUS_META) as AdStatus[]).map((s) => <StatusBadge key={s} status={s} />)}
    </div>
  );
}

export function OppChips({ types }: { types: string[] | null | undefined }) {
  if (!types || types.length === 0) return <Dash />;
  return (
    <span className="inline-flex flex-wrap gap-0.5">
      {types.map((t) => (
        <Tip key={t} text={`${t}: ${OPPORTUNITY_LABELS[t] ?? "Unknown type"}`}>
          <span className={cx("inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-sm border px-1 font-mono text-2xs font-semibold",
            t === "G" ? "border-dashed border-rule text-faint" : t === "E" ? "border-declared/40 text-declared" : "border-accent/40 bg-accent-soft text-accent")}>
            {t}
          </span>
        </Tip>
      ))}
    </span>
  );
}

export function QueueBadge({ queue }: { queue: string | null | undefined }) {
  if (!queue) return <Dash />;
  const m = QUEUE_META[queue];
  const tone = queue === "VERIFIED_HIGH_VALUE" ? "active" : queue === "HIGH_POTENTIAL_VERIFY_TRAFFIC" ? "accent"
    : queue === "TECHNICAL_OPPORTUNITY" ? "declared" : queue === "NEEDS_REVIEW" ? "possible" : queue === "EXCLUDED" ? "danger" : "neutral";
  return (
    <Tip text={m?.tip ?? queue}>
      <Badge tone={tone}>{m?.label ?? humanize(queue)}</Badge>
    </Tip>
  );
}

export function CruxCell({ bucket }: { bucket: number | null | undefined }) {
  if (!bucket) return <Dash />;
  return (
    <Tip text="CrUX popularity bucket: a coarse band of origins by Chrome usage. Not a rank, not visits.">
      <span className="tnum">{cruxLabel(bucket)}</span>
    </Tip>
  );
}

export function TrancoCell({ rank }: { rank: number | null | undefined }) {
  if (!rank) return <Dash />;
  return (
    <Tip text="Tranco list rank: a research ranking of domain popularity. Not visits.">
      <span className="tnum">#{fmtInt(rank)}</span>
    </Tip>
  );
}

export function SiteLink({ id, host, className }: { id: number; host: string; className?: string }) {
  return <Link href={`/websites/${id}`} className={cx("font-medium text-ink hover:text-accent hover:underline", className)}>{host}</Link>;
}

export function Score({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return <Dash />;
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="tnum w-7 text-right font-medium">{Math.round(value)}</span>
      <span className="relative hidden h-1 w-10 rounded-full bg-sunken sm:inline-block">
        <span className="absolute inset-y-0 left-0 rounded-full bg-accent" style={{ width: `${Math.min(100, value)}%` }} />
      </span>
    </span>
  );
}

export function JobStatus({ status }: { status: string }) {
  const tone = status === "DONE" || status === "SUCCEEDED" || status === "COMPLETED" ? "active"
    : status === "RUNNING" ? "accent" : status === "QUEUED" ? "neutral" : status === "FAILED" ? "danger" : status === "CANCELLED" ? "outline" : "neutral";
  return <Badge tone={tone}>{status === "RUNNING" && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />}{humanize(status)}</Badge>;
}

export function StageStatus({ status }: { status: string }) {
  const tone = status === "DONE" ? "active" : status === "RUNNING" ? "accent" : status === "FAILED" ? "danger" : status === "PENDING" ? "possible" : "outline";
  return <Badge tone={tone}>{humanize(status)}</Badge>;
}

export function PopularityNote({ className }: { className?: string }) {
  return (
    <p className={cx("text-xs text-muted", className)}>
      Popularity comes from CrUX buckets and Tranco ranks. Neither is a traffic or visits figure.
    </p>
  );
}
