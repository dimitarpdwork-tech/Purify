"use client";

import Link from "next/link";
import { useApi } from "@/lib/hooks";
import type { PipelineProgress } from "@/lib/types";
import { fmtInt, fmtRelative, humanize } from "@/lib/domain";
import { cx, Panel } from "@/components/ui";

const LIGHT: Record<string, { dot: string; text: string; label: string }> = {
  working: { dot: "bg-active animate-pulse", text: "text-active", label: "Working" },
  idle: { dot: "bg-faint", text: "text-muted", label: "Idle" },
  stalled: { dot: "bg-danger", text: "text-danger", label: "Stalled?" },
  paused: { dot: "bg-possible", text: "text-possible", label: "Paused" },
};

export function fmtEta(min: number | null | undefined): string {
  if (min === null || min === undefined) return "estimating…";
  if (min <= 0) return "done";
  if (min < 60) return `~${min} min`;
  const h = Math.floor(min / 60), m = min % 60;
  if (h < 48) return `~${h} h${m ? ` ${m} min` : ""}`;
  return `~${Math.round(h / 24)} days`;
}

/** Small status light for the top bar: visible on every page. */
export function ActivityLight() {
  const { data } = useApi<PipelineProgress>("/api/pipeline/progress", { poll: 10000 });
  if (!data) return null;
  const l = LIGHT[data.health.state] ?? LIGHT.idle;
  return (
    <Link href="/" title={data.health.message} className="flex items-center gap-1.5 rounded px-1.5 py-0.5 text-xs hover:bg-sunken">
      <span className={cx("inline-block h-2 w-2 rounded-full", l.dot)} aria-hidden />
      <span className={l.text}>{l.label}</span>
      {data.health.state === "working" && (
        <span className="hidden text-muted sm:inline">· {fmtInt(data.remaining)} left · {data.overall_eta_partial && data.overall_eta_minutes ? "≥ " : ""}{fmtEta(data.overall_eta_minutes)}</span>
      )}
    </Link>
  );
}

function Bar({ done, total }: { done: number; total: number }) {
  const pct = total ? Math.round((done / total) * 100) : 0;
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-full min-w-[80px] overflow-hidden rounded-full bg-sunken">
        <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${pct}%` }} />
      </div>
      <span className="tnum w-9 text-right text-xs text-muted">{pct}%</span>
    </div>
  );
}

/** Live processing panel for the dashboard. Polls every 5 s. */
export function ProgressPanel() {
  const { data } = useApi<PipelineProgress>("/api/pipeline/progress", { poll: 5000 });
  if (!data) return null;
  const nothingYet = data.stages.every((s) => s.pending + s.running + s.done + s.skipped + s.failed === 0) && data.jobs.length === 0;
  if (nothingYet) return null;
  const l = LIGHT[data.health.state] ?? LIGHT.idle;

  return (
    <Panel title={<span className="flex items-center gap-2"><span className={cx("inline-block h-2.5 w-2.5 rounded-full", l.dot)} aria-hidden />
      Processing <span className={cx("text-sm font-normal", l.text)}>{l.label}</span></span>}
      note={data.health.message} bodyClass="">
      <div className="grid gap-px bg-rule sm:grid-cols-3">
        {[
          ["Websites still in progress", fmtInt(data.remaining)],
          ["Estimated time left", data.remaining
            ? (data.overall_eta_partial && data.overall_eta_minutes ? `at least ${fmtEta(data.overall_eta_minutes)}` : fmtEta(data.overall_eta_minutes))
            : "—"],
          ["Last activity", data.health.last_activity_at ? fmtRelative(data.health.last_activity_at) : "—"],
        ].map(([k, v]) => (
          <div key={k} className="bg-panel px-3 py-2">
            <div className="text-xs text-muted">{k}</div>
            <div className="tnum text-[18px] font-semibold leading-7">{v}</div>
          </div>
        ))}
      </div>

      {data.jobs.length > 0 && (
        <div className="border-t border-rule px-3 py-2">
          <div className="mb-1 text-xs font-medium text-muted">Discovery / import jobs running</div>
          <ul className="space-y-0.5 text-sm">
            {data.jobs.map((j) => (
              <li key={j.id} className="flex flex-wrap items-center gap-x-3">
                <span className="font-medium">#{j.id} {humanize(j.kind)}</span>
                <span className="text-xs text-muted">{j.status.toLowerCase()}</span>
                {"registered" in j.progress && <span className="tnum text-xs text-muted">{fmtInt(Number(j.progress.registered))} rows read</span>}
                {"new_websites" in j.progress && <span className="tnum text-xs text-muted">{fmtInt(Number(j.progress.new_websites))} new websites</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="overflow-x-auto border-t border-rule">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-rule text-left text-xs text-muted">
            <th className="px-3 py-1.5 font-medium">Step</th>
            <th className="px-2 py-1.5 font-medium">Progress</th>
            <th className="px-2 py-1.5 text-right font-medium">Waiting</th>
            <th className="px-2 py-1.5 text-right font-medium">Working now</th>
            <th className="px-2 py-1.5 text-right font-medium">Finished</th>
            <th className="px-2 py-1.5 text-right font-medium">Failed</th>
            <th className="px-2 py-1.5 text-right font-medium">Speed</th>
            <th className="px-3 py-1.5 text-right font-medium">Time left</th>
          </tr></thead>
          <tbody>
            {data.stages.map((s) => {
              const finished = s.done + s.skipped;
              const total = finished + s.failed + s.pending + s.running;
              return (
                <tr key={s.stage} className="border-b border-rule/60 last:border-0">
                  <td className="whitespace-nowrap px-3 py-1.5">{s.label}</td>
                  <td className="w-[28%] px-2 py-1.5">{total ? <Bar done={finished + s.failed} total={total} /> : <span className="text-xs text-faint">not started</span>}</td>
                  <td className="tnum px-2 py-1.5 text-right">{fmtInt(s.pending)}</td>
                  <td className={cx("tnum px-2 py-1.5 text-right", s.running > 0 && "font-medium text-accent")}>{fmtInt(s.running)}</td>
                  <td className="tnum px-2 py-1.5 text-right">{fmtInt(finished)}</td>
                  <td className={cx("tnum px-2 py-1.5 text-right", s.failed ? "text-danger" : "text-faint")}>{fmtInt(s.failed)}</td>
                  <td className="tnum whitespace-nowrap px-2 py-1.5 text-right text-muted">{s.rate_per_hour ? `${fmtInt(s.rate_per_hour)}/h` : "—"}</td>
                  <td className="tnum whitespace-nowrap px-3 py-1.5 text-right">{s.pending + s.running ? fmtEta(s.eta_minutes) : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="px-3 py-1.5 text-2xs text-faint">
          Speed and time left are estimated from the last 10–60 minutes. &ldquo;Finished&rdquo; includes websites skipped on purpose
          (e.g. not popular enough, or not a publisher). The browser scan is the slowest step.
        </p>
      </div>

      <div className="grid gap-px border-t border-rule bg-rule lg:grid-cols-2">
        <div className="bg-panel px-3 py-2">
          <div className="mb-1 text-xs font-medium text-muted">Working on right now</div>
          {data.active.length === 0 ? <p className="text-sm text-faint">Nothing at this moment.</p> : (
            <ul className="space-y-0.5 text-sm">
              {data.active.map((a) => (
                <li key={`${a.id}-${a.stage}`} className="flex justify-between gap-2">
                  <Link href={`/websites/${a.id}`} className="truncate hover:text-accent hover:underline">{a.host}</Link>
                  <span className="shrink-0 text-xs text-muted">{a.label} · {fmtRelative(a.since)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="bg-panel px-3 py-2">
          <div className="mb-1 text-xs font-medium text-muted">Just finished</div>
          {data.recent.length === 0 ? <p className="text-sm text-faint">Nothing finished in the last day.</p> : (
            <ul className="space-y-0.5 text-sm">
              {data.recent.map((r, i) => (
                <li key={`${r.id}-${r.stage}-${i}`} className="flex justify-between gap-2">
                  <Link href={`/websites/${r.id}`} className="truncate hover:text-accent hover:underline">{r.host}</Link>
                  <span className="shrink-0 text-xs text-muted">
                    {r.label}
                    {r.status === "FAILED" ? <span className="text-danger"> · failed</span> : r.status === "SKIPPED" ? " · skipped" : ""}
                    {r.stage === "score" && r.score !== null ? ` · score ${Math.round(r.score)}` : ""}
                    {" · "}{fmtRelative(r.at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </Panel>
  );
}
