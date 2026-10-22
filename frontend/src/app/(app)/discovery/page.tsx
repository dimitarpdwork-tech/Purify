"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { Job, SearchResult, VendorsResp, WebsiteFilter } from "@/lib/types";
import { CRUX_BUCKETS, cruxLabel, fmtInt, humanize, PIPELINE_STAGES, STAGE_STATUSES } from "@/lib/domain";
import { cleanFilter, describeFilter, FilterEditor } from "@/components/filter-editor";
import { JobsTable } from "@/components/jobs";
import { SiteTable } from "@/components/site-table";
import { useToast } from "@/components/toast";
import { useAuth } from "@/components/auth";
import { Button, Checkbox, ErrorState, Field, Input, Loading, Modal, PageHeader, Panel, Select, Spinner, Tabs } from "@/components/ui";
import { PUBLISHER_CATEGORIES } from "@/lib/domain";

type Kind = "crux_ingest" | "tranco_ingest" | "sellers_discovery" | "requeue_stage" | "rescore_all";
const KINDS: { id: Kind; label: string; help: string }[] = [
  { id: "crux_ingest", label: "CrUX ingest", help: "Import origins from the Chrome UX Report popularity buckets (global or one country). Requires BigQuery to be configured." },
  { id: "tranco_ingest", label: "Tranco ingest", help: "Import domains from the latest Tranco research ranking, down to a maximum rank." },
  { id: "sellers_discovery", label: "sellers.json discovery", help: "Fetch configured sellers.json files and register PUBLISHER seller domains as candidate websites." },
  { id: "requeue_stage", label: "Requeue stage", help: "Put websites back into a pipeline stage, e.g. retry everything FAILED in adtech." },
  { id: "rescore_all", label: "Rescore all", help: "Recompute scores, opportunities and queues for every website with current settings." },
];

function JobLauncher({ onStarted }: { onStarted: () => void }) {
  const toast = useToast();
  const { can } = useAuth();
  const [kind, setKind] = useState<Kind>("crux_ingest");
  const [country, setCountry] = useState("");
  const [bucket, setBucket] = useState(10000);
  const [period, setPeriod] = useState("");
  const [excludeTop, setExcludeTop] = useState(0);
  const [limit, setLimit] = useState("");
  const [maxRank, setMaxRank] = useState(100000);
  const [stage, setStage] = useState("adtech");
  const [statuses, setStatuses] = useState<string[]>(["FAILED"]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const params = (): Record<string, unknown> | null => {
    if (kind === "crux_ingest") {
      const p: Record<string, unknown> = { max_bucket: bucket };
      if (excludeTop) { if (excludeTop >= bucket) return null; p.exclude_top = excludeTop; }
      if (limit.trim()) { if (!/^\d+$/.test(limit.trim()) || Number(limit) < 1) return null; p.limit = Number(limit); }
      const c = country.trim().toLowerCase();
      if (c) { if (!/^[a-z]{2}$/.test(c)) return null; p.country = c; }
      if (period.trim()) { if (!/^\d{6}$/.test(period.trim())) return null; p.period = period.trim(); }
      return p;
    }
    if (kind === "tranco_ingest") return { max_rank: maxRank };
    if (kind === "requeue_stage") return { stage, statuses };
    return {};
  };
  const p = params();
  const start = async () => {
    if (!p) return;
    setBusy(true); setErr(null);
    try {
      const r = await api<{ job_id: number }>("/api/jobs", { body: { kind, params: p } });
      toast(`Started job #${r.job_id}`);
      onStarted();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const help = KINDS.find((k) => k.id === kind)!.help;

  return (
    <Panel title="Start a discovery job">
      <div className="space-y-3">
        <div className="flex flex-wrap gap-1">
          {KINDS.map((k) => <Button key={k.id} size="sm" variant={kind === k.id ? "secondary" : "ghost"} className={kind === k.id ? "border-accent text-accent" : ""} onClick={() => setKind(k.id)}>{k.label}</Button>)}
        </div>
        <p className="max-w-prose text-sm text-muted">{help}</p>
        <div className="grid gap-3 sm:grid-cols-3">
          {kind === "crux_ingest" && <>
            <Field label="Country (optional)" hint="ISO2 lowercase, blank for global">
              <Input value={country} maxLength={2} onChange={(e) => setCountry(e.target.value.toLowerCase())} placeholder="us" />
            </Field>
            <Field label="Start after" hint="Skip sites already in this band (e.g. Top 10K = start at rank ~10,001)">
              <Select value={excludeTop} onChange={(e) => setExcludeTop(Number(e.target.value))}>
                <option value={0}>Start from #1</option>
                {CRUX_BUCKETS.filter((b) => b < bucket).map((b) => <option key={b} value={b}>{cruxLabel(b)}</option>)}
              </Select>
            </Field>
            <Field label="Up to" hint="Popularity band, not visits">
              <Select value={bucket} onChange={(e) => { const v = Number(e.target.value); setBucket(v); if (excludeTop >= v) setExcludeTop(0); }}>
                {CRUX_BUCKETS.map((b) => <option key={b} value={b}>{cruxLabel(b)}</option>)}
              </Select>
            </Field>
            <Field label="Max websites (optional)" hint="Stop after this many; most popular band first">
              <Input value={limit} inputMode="numeric" onChange={(e) => setLimit(e.target.value.replace(/\D/g, ""))} placeholder="e.g. 2000" />
            </Field>
            <Field label="Period (optional)" hint="YYYYMM, blank for latest">
              <Input value={period} maxLength={6} onChange={(e) => setPeriod(e.target.value.replace(/\D/g, ""))} placeholder="202609" />
            </Field>
          </>}
          {kind === "tranco_ingest" && (
            <Field label="Max rank"><Input type="number" min={1} max={1000000} value={maxRank} onChange={(e) => setMaxRank(Number(e.target.value))} /></Field>
          )}
          {kind === "requeue_stage" && <>
            <Field label="Stage"><Select value={stage} onChange={(e) => setStage(e.target.value)}>{PIPELINE_STAGES.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}</Select></Field>
            <div className="sm:col-span-2">
              <span className="mb-1 block text-xs font-medium text-muted">Requeue websites currently in</span>
              <div className="flex flex-wrap gap-3">
                {STAGE_STATUSES.filter((s) => s !== "RUNNING").map((s) => (
                  <Checkbox key={s} checked={statuses.includes(s)} label={humanize(s)} onChange={(v) => setStatuses(v ? [...statuses, s] : statuses.filter((x) => x !== s))} />
                ))}
              </div>
            </div>
          </>}
        </div>
        {!p && <p className="text-xs text-danger">Check the country (two letters) and period (YYYYMM).</p>}
        {err && <p className="rounded bg-danger-soft px-2 py-1.5 text-sm text-danger">{err}</p>}
        <div className="flex justify-end">
          <Button variant="primary" busy={busy} disabled={!p || !can("analyst") || (kind === "requeue_stage" && statuses.length === 0)} onClick={start}
            title={can("analyst") ? undefined : "Analyst role required"}>
            Start {KINDS.find((k) => k.id === kind)!.label.toLowerCase()}
          </Button>
        </div>
      </div>
    </Panel>
  );
}

const PRESETS: { name: string; desc: string; filter: WebsiteFilter }[] = [
  {
    name: "GAM, no header bidding observed",
    desc: "Publishers in the top 100K CrUX buckets with GAM active signals and no Prebid, Amazon APS or OpenWrap observed.",
    filter: { categories: PUBLISHER_CATEGORIES, max_crux_bucket: 100000, gam: ["DETECTED_ACTIVE_SIGNALS"], lacks_vendors: ["prebid", "amazon_aps", "pubmatic_openwrap"], excluded: false, sort: ["-score_total", "crux_best_bucket"] },
  },
  {
    name: "AdSense-only publishers",
    desc: "Top 50K CrUX publishers where AdSense is active and GAM is not observed.",
    filter: { is_publisher: true, max_crux_bucket: 50000, adsense: ["DETECTED_ACTIVE_SIGNALS"], gam: ["NOT_OBSERVED"], excluded: false, sort: ["crux_best_bucket", "-score_total"] },
  },
  {
    name: "Popular, no advertising observed",
    desc: "Opportunity F: popular sites with no ad-tech observed. Worth a manual look.",
    filter: { opportunity_types: ["F"], max_crux_bucket: 50000, excluded: false, sort: ["crux_best_bucket"] },
  },
  {
    name: "Limited HB competition",
    desc: "Opportunity C on publishers in the top 100K buckets.",
    filter: { opportunity_types: ["C"], is_publisher: true, max_crux_bucket: 100000, excluded: false, sort: ["-score_total"] },
  },
  {
    name: "Inconclusive scans to review",
    desc: "Popular publishers whose GAM scan was blocked or failed. Absence cannot be inferred.",
    filter: { gam: ["SCAN_INCONCLUSIVE"], max_crux_bucket: 100000, excluded: false, sort: ["crux_best_bucket"] },
  },
  {
    name: "Not analyzed yet, top 10K",
    desc: "Discovered sites in the top 10K buckets still waiting for an ad-tech scan.",
    filter: { analyzed: false, max_crux_bucket: 10000, excluded: false, sort: ["crux_best_bucket"] },
  },
];

function QueryBuilder() {
  const router = useRouter();
  const toast = useToast();
  const vendors = useApi<VendorsResp>("/api/vendors");
  const vendorList = vendors.data?.vendors ?? [];
  const vendorName = (k: string) => vendorList.find((v) => v.key === k)?.name ?? k;
  const [filter, setFilter] = useState<WebsiteFilter>(PRESETS[0].filter);
  const [preview, setPreview] = useState<SearchResult | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [saveOpen, setSaveOpen] = useState(false);
  const [name, setName] = useState("");

  useEffect(() => {
    let cancel = false;
    const t = setTimeout(async () => {
      setBusy(true);
      try {
        const r = await api<SearchResult>("/api/websites/search?page=1&page_size=10", { body: cleanFilter(filter) });
        if (!cancel) { setPreview(r); setErr(null); }
      } catch (e) { if (!cancel) setErr(e as ApiError); }
      finally { if (!cancel) setBusy(false); }
    }, 350);
    return () => { cancel = true; clearTimeout(t); };
  }, [filter]);

  const summary = describeFilter(cleanFilter(filter), vendorName);
  const save = async () => {
    try {
      await api("/api/views", { body: { name, filters: cleanFilter(filter), columns: null } });
      toast(`Saved view "${name}". Find it in the explorer.`);
      setSaveOpen(false); setName("");
    } catch (e) { toast((e as Error).message, "error"); }
  };

  return (
    <div className="space-y-3">
      <Panel title="Preset queries">
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {PRESETS.map((p) => (
            <button key={p.name} onClick={() => setFilter(p.filter)} className="rounded border border-rule px-3 py-2 text-left hover:border-accent hover:bg-accent-soft/40">
              <span className="block text-sm font-medium">{p.name}</span>
              <span className="block text-xs text-muted">{p.desc}</span>
            </button>
          ))}
        </div>
      </Panel>
      <Panel title="Query">
        <FilterEditor value={filter} onChange={setFilter} vendors={vendorList} />
      </Panel>
      <Panel title={<span className="flex items-center gap-2">Result {busy && <Spinner className="text-faint" />}</span>}
        note={summary.length ? summary.join("; ") : "No conditions: all non-excluded websites"}
        actions={<>
          <Button size="sm" onClick={() => setSaveOpen(true)}>Save as view</Button>
          <Button size="sm" variant="primary" onClick={() => router.push(`/explorer?f=${encodeURIComponent(JSON.stringify(cleanFilter(filter)))}`)}>Open in explorer</Button>
        </>} bodyClass="">
        {err ? <ErrorState error={err} className="m-3" /> : !preview ? <Loading /> : (
          <>
            <p className="border-b border-rule px-3 py-1.5 text-sm"><b className="tnum">{fmtInt(preview.total)}</b> websites match{preview.total > 10 && ", first 10 shown"}.</p>
            <SiteTable rows={preview.rows} empty="No websites match. Loosen a condition, or run discovery and wait for scans to complete." />
          </>
        )}
      </Panel>
      <Modal open={saveOpen} onClose={() => setSaveOpen(false)} title="Save as view" footer={<>
        <Button size="sm" variant="ghost" onClick={() => setSaveOpen(false)}>Cancel</Button>
        <Button size="sm" variant="primary" disabled={!name.trim()} onClick={save}>Save view</Button></>}>
        <Field label="Name"><Input autoFocus value={name} onChange={(e) => setName(e.target.value)} maxLength={120} /></Field>
      </Modal>
    </div>
  );
}

export default function DiscoveryPage() {
  const [tab, setTab] = useState("jobs");
  const jobs = useApi<Job[]>("/api/jobs?limit=50", { poll: 5000 });
  return (
    <div className="space-y-3">
      <PageHeader title="Discovery" sub="Bring new websites in and compose queries over everything discovered." />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "jobs", label: "Discovery jobs" }, { id: "query", label: "Query builder" }]} />
      {tab === "jobs" ? (
        <div className="space-y-3">
          <JobLauncher onStarted={jobs.reload} />
          <Panel title="Jobs" note="Refreshes every 5 seconds" bodyClass="" actions={<Button size="sm" variant="ghost" onClick={jobs.reload}>Refresh</Button>}>
            {jobs.loading && !jobs.data ? <Loading /> : jobs.error && !jobs.data ? <ErrorState error={jobs.error} onRetry={jobs.reload} className="m-3" /> :
              <JobsTable jobs={jobs.data ?? []} onChanged={jobs.reload} />}
          </Panel>
        </div>
      ) : <QueryBuilder />}
    </div>
  );
}
