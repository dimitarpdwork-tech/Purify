"use client";

import { Fragment, useState } from "react";
import { api } from "@/lib/api";
import type { Job } from "@/lib/types";
import { fmtDate, fmtInt, fmtRelative, humanize } from "@/lib/domain";
import { JobStatus } from "./domain";
import { useToast } from "./toast";
import { useAuth } from "./auth";
import { Button, cx, Empty, Json } from "./ui";

/** Pull a progress fraction out of a free-form progress dict if it has done/total style keys. */
export function progressFraction(p: Record<string, unknown> | null): number | null {
  if (!p) return null;
  const num = (k: string) => (typeof p[k] === "number" ? (p[k] as number) : null);
  const done = num("done") ?? num("processed") ?? num("rows") ?? num("row");
  const total = num("total") ?? num("total_rows");
  if (done !== null && total) return Math.max(0, Math.min(1, done / total));
  return null;
}

function scalarProgress(p: Record<string, unknown> | null): [string, string][] {
  if (!p) return [];
  return Object.entries(p).filter(([, v]) => typeof v === "number" || typeof v === "string" || typeof v === "boolean")
    .slice(0, 8).map(([k, v]) => [humanize(k), typeof v === "number" ? fmtInt(v) : String(v)]);
}

export function JobsTable({ jobs, onChanged, compact }: { jobs: Job[]; onChanged: () => void; compact?: boolean }) {
  const toast = useToast();
  const { can } = useAuth();
  const [open, setOpen] = useState<number | null>(null);
  const act = async (id: number, action: "cancel" | "resume") => {
    try {
      await api(`/api/jobs/${id}/${action}`, { method: "POST" });
      toast(action === "cancel" ? `Cancellation requested for job #${id}` : `Job #${id} resumed`);
      onChanged();
    } catch (e) { toast((e as Error).message, "error"); }
  };
  if (jobs.length === 0) return <Empty title="No jobs yet">Start one above.</Empty>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead><tr className="border-b border-rule text-left text-xs text-muted">
          <th className="px-3 py-1.5 font-medium">Job</th><th className="px-2 py-1.5 font-medium">Status</th><th className="px-2 py-1.5 font-medium">Progress</th>
          {!compact && <th className="px-2 py-1.5 font-medium">Started</th>}<th className="px-3 py-1.5 text-right font-medium" />
        </tr></thead>
        <tbody>
          {jobs.map((j) => {
            const frac = progressFraction(j.progress);
            const live = j.status === "RUNNING" || j.status === "QUEUED";
            const stale = j.status === "RUNNING" && j.heartbeat_at && Date.now() - new Date(j.heartbeat_at).getTime() > 5 * 60 * 1000;
            return (
              <Fragment key={j.id}>
                <tr className="border-b border-rule/60 align-top">
                  <td className="px-3 py-1.5">
                    <span className="tnum text-faint">#{j.id}</span> <span className="font-medium">{humanize(j.kind)}</span>
                    {j.params && Object.keys(j.params).length > 0 && !compact && (
                      <div className="max-w-[320px] truncate font-mono text-2xs text-faint" title={JSON.stringify(j.params)}>{JSON.stringify(j.params)}</div>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-2 py-1.5">
                    <JobStatus status={j.status} />
                    {stale && <div className="text-2xs text-possible">no heartbeat {fmtRelative(j.heartbeat_at)}</div>}
                  </td>
                  <td className="min-w-[180px] px-2 py-1.5">
                    {frac !== null && (
                      <div className="mb-1 flex items-center gap-2">
                        <div className="relative h-1.5 flex-1 rounded-full bg-sunken"><div className={cx("absolute inset-y-0 left-0 rounded-full", j.status === "FAILED" ? "bg-danger" : "bg-accent")} style={{ width: `${frac * 100}%` }} /></div>
                        <span className="tnum text-xs text-muted">{Math.round(frac * 100)}%</span>
                      </div>
                    )}
                    <div className="flex flex-wrap gap-x-3 text-xs text-muted">
                      {scalarProgress(j.progress).map(([k, v]) => <span key={k}>{k}: <span className="tnum text-ink">{v}</span></span>)}
                      {!j.progress || Object.keys(j.progress).length === 0 ? <span className="text-faint">{live ? "waiting for worker…" : "—"}</span> : null}
                    </div>
                    {j.error && <p className="mt-0.5 line-clamp-2 font-mono text-2xs text-danger" title={j.error}>{j.error}</p>}
                  </td>
                  {!compact && <td className="whitespace-nowrap px-2 py-1.5 text-xs text-muted" title={fmtDate(j.created_at, true)}>
                    {fmtRelative(j.started_at ?? j.created_at)}{j.finished_at && <div className="text-faint">finished {fmtRelative(j.finished_at)}</div>}
                  </td>}
                  <td className="whitespace-nowrap px-3 py-1.5 text-right">
                    <Button size="sm" variant="ghost" onClick={() => setOpen(open === j.id ? null : j.id)}>{open === j.id ? "Hide" : "Details"}</Button>
                    {can("analyst") && live && <Button size="sm" variant="ghost" onClick={() => act(j.id, "cancel")}>Cancel</Button>}
                    {can("analyst") && (j.status === "FAILED" || j.status === "CANCELLED") && <Button size="sm" variant="ghost" onClick={() => act(j.id, "resume")}>Resume</Button>}
                  </td>
                </tr>
                {open === j.id && (
                  <tr className="border-b border-rule/60 bg-sunken/40">
                    <td colSpan={compact ? 4 : 5} className="px-3 py-2">
                      <div className="grid gap-2 md:grid-cols-2">
                        <div><p className="mb-1 text-xs font-medium text-muted">Params</p><Json value={j.params ?? {}} className="max-h-60 bg-panel" /></div>
                        <div><p className="mb-1 text-xs font-medium text-muted">Progress</p><Json value={j.progress ?? {}} className="max-h-60 bg-panel" /></div>
                      </div>
                      {j.error && <pre className="mt-2 whitespace-pre-wrap rounded bg-danger-soft p-2 font-mono text-2xs text-danger">{j.error}</pre>}
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
