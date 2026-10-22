"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { Profile } from "@/lib/types";
import { fmtInt, humanize, OUTREACH_STAGES, PIPELINE_STAGES, QUEUE_META, QUEUES } from "@/lib/domain";
import { CruxCell, OppChips, QueueBadge, StatusBadge, TrancoCell } from "@/components/domain";
import { AdsTxt, AdTech, Classification, Inventory, Opportunities, Overview, Scans, ScoreTab, Supply } from "@/components/profile-sections";
import { Badge, Button, Checkbox, Confidence, Empty, ErrorState, Field, Input, Loading, Modal, Select, Tabs, Textarea, Tip } from "@/components/ui";
import { useToast } from "@/components/toast";
import { useAuth } from "@/components/auth";

const TABS = [
  { id: "overview", label: "Overview" }, { id: "classification", label: "Classification" }, { id: "adtech", label: "Ad-tech stack" },
  { id: "inventory", label: "Inventory" }, { id: "adstxt", label: "ads.txt" }, { id: "supply", label: "Supply chain" },
  { id: "opportunities", label: "Opportunities" }, { id: "score", label: "Score" }, { id: "scans", label: "Scans" },
];

export default function WebsitePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const wid = Number(id);
  const { data, error, loading, reload } = useApi<Profile>(Number.isFinite(wid) ? `/api/websites/${wid}` : null);
  const [tab, setTab] = useState("overview");
  const [modal, setModal] = useState<null | "rescan" | "override" | "exclude" | "outreach">(null);
  const { can } = useAuth();

  useEffect(() => {
    const h = window.location.hash.slice(1);
    if (TABS.some((t) => t.id === h)) setTab(h);
  }, []);
  const changeTab = (t: string) => { setTab(t); history.replaceState(null, "", `#${t}`); };

  if (!Number.isFinite(wid)) return <Empty title="Invalid website id" />;
  if (loading && !data) return <Loading label="Loading profile…" />;
  if (error && !data) {
    return error.status === 404
      ? <Empty title="Website not found">It may have been merged into another host. <Link href="/explorer" className="text-accent underline">Back to the explorer</Link>.</Empty>
      : <ErrorState error={error} onRetry={reload} />;
  }
  if (!data) return null;
  const w = data.website;
  const technologies = data.technologies;
  const running = data.stages.some((s) => s.status === "RUNNING" || s.status === "PENDING");

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="rounded border border-rule bg-panel">
        <div className="flex flex-wrap items-start justify-between gap-3 px-3 py-2.5">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="truncate text-[19px] font-semibold leading-7">{w.host}</h1>
              {w.preferred_origin && <a href={w.preferred_origin} target="_blank" rel="noreferrer noopener" className="text-xs text-accent hover:underline">open site</a>}
              {w.excluded && <Tip text={w.exclusion_reason ?? "Excluded"}><Badge tone="danger">Excluded</Badge></Tip>}
              {running && <Badge tone="accent"><span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />stages queued</Badge>}
            </div>
            <p className="text-sm text-muted">
              {w.primary_category ? humanize(w.primary_category) : "Unclassified"}
              {w.primary_geo && <> · GEO {w.primary_geo}</>}
              {w.registrable_domain && w.registrable_domain !== w.host && <> · {w.registrable_domain}</>}
              {w.outreach_stage && <> · Outreach: {w.outreach_stage}</>}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <Button size="sm" variant="ghost" onClick={reload}>Refresh</Button>
            {can("analyst") && <>
              <Button size="sm" onClick={() => setModal("rescan")}>Rescan</Button>
              <Button size="sm" onClick={() => setModal("outreach")}>Outreach</Button>
              <Button size="sm" onClick={() => setModal("override")}>Override queue</Button>
              <Button size="sm" variant={w.excluded ? "secondary" : "danger"} onClick={() => setModal("exclude")}>{w.excluded ? "Include" : "Exclude"}</Button>
            </>}
          </div>
        </div>
        <div className="grid grid-cols-2 border-t border-rule text-sm sm:grid-cols-4 lg:grid-cols-8">
          {[
            ["Score", <span key="s" className="tnum text-base font-semibold">{w.score_total === null ? "—" : Math.round(w.score_total)}</span>],
            ["Queue", <QueueBadge key="q" queue={w.queue} />],
            ["Opportunities", <OppChips key="o" types={w.opportunity_types} />],
            ["CrUX bucket", <CruxCell key="c" bucket={w.crux_best_bucket} />],
            ["Tranco rank", <TrancoCell key="t" rank={w.tranco_best_rank} />],
            ["GAM", <StatusBadge key="g" status={w.gam_status} />],
            ["AdSense", <StatusBadge key="a" status={w.adsense_status} />],
            ["Prebid", <StatusBadge key="p" status={w.prebid_status} />],
          ].map(([label, v], i) => (
            <div key={i} className="border-b border-r border-rule px-3 py-1.5 lg:border-b-0">
              <div className="text-2xs text-muted">{label}</div>
              <div className="flex min-h-[24px] items-center">{v}</div>
            </div>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-rule px-3 py-1.5 text-xs text-muted">
          <span>Evidence confidence <Confidence value={w.evidence_confidence} /></span>
          <span>Observed partners: {w.observed_partners?.length ? w.observed_partners.join(", ") : "none"}</span>
          <span>ads.txt systems: {fmtInt(w.declared_ad_systems_count) || "0"}</span>
          <span>Monetization: {w.monetization_type ? humanize(w.monetization_type) : "unknown"}</span>
        </div>
      </div>

      <Tabs value={tab} onChange={changeTab} tabs={TABS.map((t) => ({
        ...t,
        label: t.id === "adtech" ? `Ad-tech stack (${technologies.length})` : t.id === "opportunities" ? `Opportunities (${data.opportunities.length})`
          : t.id === "adstxt" ? `ads.txt (${data.ads_txt.records.length})` : t.id === "scans" ? `Scans (${data.scans.length})` : t.label,
      }))} />

      <div>
        {tab === "overview" && <Overview p={data} />}
        {tab === "classification" && <Classification p={data} />}
        {tab === "adtech" && <AdTech p={data} />}
        {tab === "inventory" && <Inventory p={data} />}
        {tab === "adstxt" && <AdsTxt p={data} />}
        {tab === "supply" && <Supply id={wid} />}
        {tab === "opportunities" && <Opportunities p={data} />}
        {tab === "score" && <ScoreTab p={data} />}
        {tab === "scans" && <Scans p={data} />}
      </div>

      <RescanModal open={modal === "rescan"} onClose={() => setModal(null)} wid={wid} onDone={reload} />
      <OverrideModal open={modal === "override"} onClose={() => setModal(null)} wid={wid} current={data.score?.queue ?? w.queue} computed={data.score?.computed_queue ?? null} onDone={reload} />
      <ExcludeModal open={modal === "exclude"} onClose={() => setModal(null)} wid={wid} excluded={!!w.excluded} onDone={reload} />
      <OutreachModal open={modal === "outreach"} onClose={() => setModal(null)} wid={wid} stage={data.outreach?.stage ?? w.outreach_stage ?? "Discovered"}
        notes={data.outreach?.notes ?? ""} imported={data.outreach?.imported_status ?? null} onDone={reload} />
    </div>
  );
}

function RescanModal({ open, onClose, wid, onDone }: { open: boolean; onClose: () => void; wid: number; onDone: () => void }) {
  const toast = useToast();
  const [stages, setStages] = useState<string[]>(["classify"]);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      const r = await api<{ queued: string[] }>(`/api/websites/${wid}/rescan`, { body: { stages } });
      toast(`Queued ${r.queued.join(", ")}`);
      onDone(); onClose();
    } catch (e) { toast((e as Error).message, "error"); } finally { setBusy(false); }
  };
  return (
    <Modal open={open} onClose={onClose} title="Rescan stages" footer={<>
      <Button size="sm" variant="ghost" onClick={onClose}>Cancel</Button>
      <Button size="sm" variant="primary" busy={busy} disabled={!stages.length} onClick={run}>Queue rescan</Button></>}>
      <p className="mb-2 text-sm text-muted">Selected stages are queued at top priority. Downstream stages run automatically when a stage completes.</p>
      <div className="space-y-1">
        {PIPELINE_STAGES.map((s) => (
          <Checkbox key={s} checked={stages.includes(s)} label={humanize(s)} onChange={(v) => setStages(v ? [...stages, s] : stages.filter((x) => x !== s))} className="flex" />
        ))}
      </div>
    </Modal>
  );
}

function OverrideModal({ open, onClose, wid, current, computed, onDone }: { open: boolean; onClose: () => void; wid: number; current: string | null; computed: string | null; onDone: () => void }) {
  const toast = useToast();
  const [value, setValue] = useState(current ?? "NEEDS_REVIEW");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) { setValue(current ?? "NEEDS_REVIEW"); setReason(""); } }, [open, current]);
  const run = async () => {
    setBusy(true);
    try {
      await api(`/api/websites/${wid}/override`, { body: { field: "queue", value, reason } });
      toast(value === "CLEAR" ? "Queue override cleared" : `Queue set to ${QUEUE_META[value]?.label ?? value}`);
      onDone(); onClose();
    } catch (e) { toast((e as Error).message, "error"); } finally { setBusy(false); }
  };
  return (
    <Modal open={open} onClose={onClose} title="Override queue" footer={<>
      <Button size="sm" variant="ghost" onClick={onClose}>Cancel</Button>
      <Button size="sm" variant="primary" busy={busy} disabled={reason.trim().length < 3} onClick={run}>Save override</Button></>}>
      <div className="space-y-3">
        <p className="text-sm text-muted">Computed queue: <QueueBadge queue={computed} />. A manual override stays in place through rescoring until cleared.</p>
        <Field label="Queue">
          <Select value={value} onChange={(e) => setValue(e.target.value)}>
            {QUEUES.map((q) => <option key={q} value={q}>{QUEUE_META[q].label}</option>)}
            <option value="CLEAR">Clear override (use computed queue)</option>
          </Select>
        </Field>
        {value === "VERIFIED_HIGH_VALUE" && <p className="rounded bg-possible-soft px-2 py-1.5 text-xs text-possible">Only promote after researching traffic manually. Note the source of your traffic estimate in the reason.</p>}
        <Field label="Reason" hint="Required, at least 3 characters. Recorded in the audit log.">
          <Textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
      </div>
    </Modal>
  );
}

function ExcludeModal({ open, onClose, wid, excluded, onDone }: { open: boolean; onClose: () => void; wid: number; excluded: boolean; onDone: () => void }) {
  const toast = useToast();
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) setReason(""); }, [open]);
  const run = async () => {
    setBusy(true);
    try {
      await api(`/api/websites/${wid}/override`, { body: { field: "excluded", value: excluded ? "false" : "true", reason } });
      toast(excluded ? "Website included" : "Website excluded");
      onDone(); onClose();
    } catch (e) { toast((e as Error).message, "error"); } finally { setBusy(false); }
  };
  return (
    <Modal open={open} onClose={onClose} title={excluded ? "Include website" : "Exclude website"} footer={<>
      <Button size="sm" variant="ghost" onClick={onClose}>Cancel</Button>
      <Button size="sm" variant={excluded ? "primary" : "danger"} busy={busy} disabled={reason.trim().length < 3} onClick={run}>{excluded ? "Include" : "Exclude"}</Button></>}>
      <Field label="Reason" hint="Required. The site is rescored immediately.">
        <Input autoFocus value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
    </Modal>
  );
}

function OutreachModal({ open, onClose, wid, stage, notes, imported, onDone }: {
  open: boolean; onClose: () => void; wid: number; stage: string; notes: string; imported: string | null; onDone: () => void;
}) {
  const toast = useToast();
  const [s, setS] = useState(stage);
  const [n, setN] = useState(notes);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) { setS(stage); setN(notes); } }, [open, stage, notes]);
  const run = async () => {
    setBusy(true);
    try {
      await api(`/api/websites/${wid}/outreach`, { method: "PATCH", body: { stage: s, notes: n } });
      toast("Outreach saved");
      onDone(); onClose();
    } catch (e) { toast((e as Error).message, "error"); } finally { setBusy(false); }
  };
  return (
    <Modal open={open} onClose={onClose} title="Outreach" footer={<>
      <Button size="sm" variant="ghost" onClick={onClose}>Cancel</Button>
      <Button size="sm" variant="primary" busy={busy} onClick={run}>Save outreach</Button></>}>
      <div className="space-y-3">
        <Field label="Stage">
          <Select value={s} onChange={(e) => setS(e.target.value)}>{OUTREACH_STAGES.map((x) => <option key={x}>{x}</option>)}</Select>
        </Field>
        {imported && <p className="text-xs text-muted">Imported status: {imported}</p>}
        <Field label="Notes"><Textarea rows={6} value={n} onChange={(e) => setN(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}
