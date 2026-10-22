"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useApi } from "@/lib/hooks";
import type { Dashboard } from "@/lib/types";
import { cruxLabel, fmtInt, fmtRelative, humanize, OPPORTUNITY_LABELS, PIPELINE_STAGES, QUEUE_META, QUEUES, STAGE_STATUSES } from "@/lib/domain";
import { BarList } from "@/components/charts";
import { JobStatus } from "@/components/domain";
import { SiteTable } from "@/components/site-table";
import { Button, Empty, ErrorState, Loading, PageHeader, Panel, Tip } from "@/components/ui";

function explorerHref(f: Record<string, unknown>) {
  return `/explorer?f=${encodeURIComponent(JSON.stringify(f))}`;
}

function Totals({ t }: { t: Record<string, number> }) {
  const items: [string, string, string][] = [
    ["websites", "Websites", "All registered websites, including excluded."],
    ["classified", "Classified", "Websites with a primary category."],
    ["publishers", "Publishers", "Classified as advertising-supported publishers."],
    ["adtech_analyzed", "Ad-tech analyzed", "At least one ad-tech scan completed."],
    ["with_opportunity", "With opportunity", "At least one opportunity hypothesis (A–G)."],
    ["high_potential", "High potential", "In the verified-high-value or high-potential-verify-traffic queues."],
    ["needs_review", "Needs review", "Uncertain classification or inconclusive ad-tech evidence."],
    ["excluded", "Excluded", "Excluded by rule or manual decision."],
  ];
  return (
    <div className="grid grid-cols-2 overflow-hidden rounded border border-rule bg-panel sm:grid-cols-4 xl:grid-cols-8">
      {items.map(([k, label, tip]) => (
        <Tip key={k} text={tip} className="block border-b border-r border-rule px-3 py-2 last:border-r-0">
          <div className="w-full">
            <div className="text-xs text-muted">{label}</div>
            <div className="tnum text-[20px] font-semibold leading-7">{fmtInt(t[k] ?? 0)}</div>
          </div>
        </Tip>
      ))}
    </div>
  );
}

function StageTable({ stages }: { stages: Record<string, Record<string, number>> }) {
  const names = [...PIPELINE_STAGES, ...Object.keys(stages).filter((s) => !PIPELINE_STAGES.includes(s))];
  const statuses = [...STAGE_STATUSES, ...new Set(Object.values(stages).flatMap((m) => Object.keys(m)).filter((s) => !STAGE_STATUSES.includes(s)))];
  if (Object.keys(stages).length === 0) return <Empty title="No pipeline work yet">Stages start once websites are discovered or imported.</Empty>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-rule text-xs text-muted">
            <th className="px-3 py-1.5 text-left font-medium">Stage</th>
            {statuses.map((s) => <th key={s} className="px-2 py-1.5 text-right font-medium">{humanize(s)}</th>)}
          </tr>
        </thead>
        <tbody>
          {names.map((st) => (
            <tr key={st} className="border-b border-rule/60 last:border-0">
              <td className="px-3 py-1 font-medium">{humanize(st)}</td>
              {statuses.map((s) => {
                const n = stages[st]?.[s] ?? 0;
                return (
                  <td key={s} className={`tnum px-2 py-1 text-right ${n === 0 ? "text-faint" : s === "FAILED" ? "font-medium text-danger" : s === "RUNNING" ? "text-accent" : ""}`}>
                    {fmtInt(n)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function DashboardPage() {
  const router = useRouter();
  const { data, error, loading, reload } = useApi<Dashboard>("/api/dashboard", { poll: 15000 });

  if (loading && !data) return <Loading label="Loading dashboard…" />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;

  const empty = (data.totals.websites ?? 0) === 0;
  const queueRows = [...QUEUES, "UNSCORED"].filter((q) => data.queues[q] !== undefined).map((q) => [q, data.queues[q]] as [string, number]);
  const oppRows = Object.keys(OPPORTUNITY_LABELS).map((t) => [t, data.opportunities[t] ?? 0] as [string, number]);
  const crux = Object.entries(data.crux_buckets).sort((a, b) => Number(a[0]) - Number(b[0]));

  return (
    <div className="space-y-3">
      <PageHeader title="Dashboard"
        sub={<span className="inline-flex items-center gap-1.5"><span className="inline-block h-1.5 w-1.5 rounded-full bg-possible" aria-hidden />{data.traffic_note}</span>}
        actions={<Button size="sm" variant="ghost" onClick={reload}>Refresh</Button>} />
      {error && <ErrorState error={error} onRetry={reload} />}

      {empty && (
        <Panel title="No websites yet">
          <p className="max-w-prose text-sm text-muted">
            This install has no websites. Start a CrUX or Tranco ingest in <Link className="text-accent underline" href="/discovery">Discovery</Link>,
            upload a legacy list in <Link className="text-accent underline" href="/import">Import</Link>, or add domains manually in the <Link className="text-accent underline" href="/explorer">Publisher explorer</Link>.
          </p>
        </Panel>
      )}

      <Totals t={data.totals} />

      <div className="grid gap-3 lg:grid-cols-3">
        <Panel title="Queues" note="Click a row to open it in the explorer">
          {queueRows.length ? (
            <BarList data={queueRows} label={(q) => QUEUE_META[q]?.label ?? humanize(q)}
              onClickRow={(q) => q !== "UNSCORED" && router.push(explorerHref({ queues: [q], excluded: q === "EXCLUDED" ? true : false }))} />
          ) : <Empty title="No scored websites" />}
        </Panel>
        <Panel title="Opportunity types" note="Hypotheses, not confirmed deals">
          <BarList data={oppRows} label={(t) => <><span className="mr-1.5 font-mono text-xs font-semibold text-accent">{t}</span>{OPPORTUNITY_LABELS[t]}</>}
            tip={(t, v) => `${fmtInt(v)} websites with hypothesis ${t}: ${OPPORTUNITY_LABELS[t]}`}
            onClickRow={(t) => router.push(explorerHref({ opportunity_types: [t] }))} />
        </Panel>
        <Panel title="CrUX popularity buckets" note="Best bucket per site; coarse bands, not visits">
          {crux.length ? (
            <BarList data={crux} label={(b) => cruxLabel(b)} onClickRow={(b) => router.push(explorerHref({ max_crux_bucket: Number(b) }))}
              tip={(b, v) => `${fmtInt(v)} websites whose best CrUX bucket is ${cruxLabel(b)}`} />
          ) : <Empty title="No CrUX data">Run a CrUX ingest in Discovery.</Empty>}
        </Panel>
        <Panel title="Categories">
          {Object.keys(data.categories).length ? (
            <BarList data={Object.entries(data.categories).slice(0, 14)} label={humanize}
              onClickRow={(c) => router.push(explorerHref({ categories: [c] }))} />
          ) : <Empty title="Nothing classified yet" />}
        </Panel>
        <Panel title="Monetization types" note="Derived from observed ad-tech, see status tooltips">
          {Object.keys(data.monetization).length ? (
            <BarList data={Object.entries(data.monetization)} label={humanize}
              onClickRow={(m) => router.push(explorerHref({ monetization_types: [m] }))} />
          ) : <Empty title="No ad-tech scans yet" />}
        </Panel>
        <Panel title="Discovery sources" note="Distinct websites per source">
          {Object.keys(data.sources).length ? (
            <BarList data={Object.entries(data.sources)} label={humanize} onClickRow={(s) => router.push(explorerHref({ sources: [s] }))} />
          ) : <Empty title="No sources yet" />}
        </Panel>
      </div>

      <div className="grid gap-3 xl:grid-cols-[3fr_2fr]">
        <Panel title="Pipeline stages" bodyClass="" actions={<Link href="/discovery" className="text-xs text-accent hover:underline">Requeue a stage</Link>}>
          <StageTable stages={data.stages} />
        </Panel>
        <Panel title="Recent jobs" bodyClass="" actions={<Link href="/discovery" className="text-xs text-accent hover:underline">All jobs</Link>}>
          {data.jobs.length === 0 ? <Empty title="No jobs have run" /> : (
            <ul className="divide-y divide-rule/60">
              {data.jobs.map((j) => (
                <li key={j.id} className="flex items-center justify-between gap-2 px-3 py-1.5 text-sm">
                  <span className="min-w-0 truncate"><span className="tnum text-faint">#{j.id}</span> {humanize(j.kind)}</span>
                  <span className="flex shrink-0 items-center gap-2"><span className="text-xs text-faint">{fmtRelative(j.created_at)}</span><JobStatus status={j.status} /></span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <div className="grid gap-3 xl:grid-cols-2">
        <Panel title="Top prospects" note="High-potential and verified queues. Traffic still needs manual research." bodyClass="">
          <SiteTable rows={data.top_prospects} empty="Prospects appear after websites are scored into the high-potential queues." />
        </Panel>
        <Panel title="Newly discovered, promising" note="First discovered in the last 7 days" bodyClass="">
          <SiteTable rows={data.new_promising} empty="No promising sites discovered this week." />
        </Panel>
      </div>

      <Panel title="Recent stage failures" bodyClass="">
        {data.recent_failures.length === 0 ? <Empty title="No failures" /> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="border-b border-rule text-left text-xs text-muted">
                <th className="px-3 py-1.5 font-medium">Host</th><th className="px-2 py-1.5 font-medium">Stage</th>
                <th className="px-2 py-1.5 font-medium">Error</th><th className="px-3 py-1.5 text-right font-medium">When</th>
              </tr></thead>
              <tbody>
                {data.recent_failures.map((f, i) => (
                  <tr key={i} className="border-b border-rule/60 last:border-0">
                    <td className="px-3 py-1"><Link href={`/explorer?f=${encodeURIComponent(JSON.stringify({ q: f.host }))}`} className="hover:text-accent hover:underline">{f.host}</Link></td>
                    <td className="px-2 py-1">{humanize(f.stage)}</td>
                    <td className="max-w-[520px] truncate px-2 py-1 font-mono text-xs text-danger" title={f.error ?? ""}>{f.error}</td>
                    <td className="whitespace-nowrap px-3 py-1 text-right text-xs text-faint">{fmtRelative(f.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
