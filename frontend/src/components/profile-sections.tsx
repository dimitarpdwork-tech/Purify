"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useApi } from "@/lib/hooks";
import type { AdsTxtRecordT, NetworkResp, Profile, RelatedResp, SupplyGraph, Technology } from "@/lib/types";
import { cruxLabel, fmtDate, fmtInt, fmtPct, fmtRelative, fmtScore, humanize, OPPORTUNITY_LABELS, QUEUE_META } from "@/lib/domain";
import { QueueBadge, StageStatus, StatusBadge, StatusLegend } from "./domain";
import { Sparkline } from "./charts";
import { Badge, Button, Confidence, cx, Dash, Drawer, Empty, ErrorState, Input, Json, KV, Loading, Panel, Tip } from "./ui";

function Ext({ href, children }: { href: string | null | undefined; children?: React.ReactNode }) {
  if (!href) return <Dash />;
  return <a href={href} target="_blank" rel="noreferrer noopener" className="break-all text-accent hover:underline">{children ?? href}</a>;
}

function val(v: unknown): React.ReactNode {
  if (v === null || v === undefined || v === "") return <Dash />;
  if (Array.isArray(v)) return v.length ? v.map((x) => (typeof x === "object" ? JSON.stringify(x) : String(x))).join(", ") : <Dash />;
  if (typeof v === "object") return <span className="font-mono text-xs">{JSON.stringify(v)}</span>;
  if (typeof v === "boolean") return v ? "yes" : "no";
  return String(v);
}

/* ================================================================ Overview */
export function Overview({ p }: { p: Profile }) {
  const w = p.website;
  const cls = p.classification.find((c) => c.is_current) ?? p.classification[0];
  const links = p.business_links;
  return (
    <div className="grid gap-3 xl:grid-cols-2">
      <Panel title="Summary">
        <KV rows={[
          ["Category", w.primary_category ? <>{humanize(w.primary_category)} {cls?.secondary?.length ? <span className="text-muted">(also {cls.secondary.map(humanize).join(", ")})</span> : null}</> : null],
          ["Publisher", w.is_publisher === null ? <span className="text-faint">unknown</span> : w.is_publisher ? "Yes" : "No"],
          ["Classification confidence", <Confidence key="c" value={w.classification_confidence} />],
          ["Evidence confidence", <Confidence key="e" value={w.evidence_confidence} />],
          ["Primary GEO", w.primary_geo],
          ["Language", w.language],
          ["Monetization type", w.monetization_type ? humanize(w.monetization_type) : null],
          ["Preferred origin", <Ext key="o" href={w.preferred_origin} />],
          ["Canonical host", w.canonical_host],
          ["Redirects to", w.redirects_to_website_id ? <Link className="text-accent hover:underline" href={`/websites/${w.redirects_to_website_id}`}>website #{w.redirects_to_website_id}</Link> : null],
          ["First discovered", fmtDate(w.first_discovered_at, true)],
          ["Last analyzed", w.last_analyzed_at ? `${fmtDate(w.last_analyzed_at, true)} (${fmtRelative(w.last_analyzed_at)})` : <span className="text-faint">never</span>],
          ["Excluded", w.excluded ? <span className="text-danger">Yes: {w.exclusion_reason}</span> : "No"],
        ]} />
      </Panel>

      <Panel title="Pipeline stages" bodyClass="">
        {p.stages.length === 0 ? <Empty title="No stage records" /> : (
          <table className="w-full text-sm">
            <tbody>
              {p.stages.map((s) => (
                <tr key={s.stage} className="border-b border-rule/60 align-top last:border-0">
                  <td className="w-24 px-3 py-1.5 font-medium">{humanize(s.stage)}</td>
                  <td className="px-2 py-1.5"><StageStatus status={s.status} /></td>
                  <td className="px-2 py-1.5 text-xs text-muted">
                    <span className="tnum">{s.attempts} attempt{s.attempts === 1 ? "" : "s"}</span> · {fmtRelative(s.updated_at)}
                    {s.last_error && <p className="mt-0.5 break-all font-mono text-2xs text-danger">{s.last_error}</p>}
                    {s.detail != null && typeof s.detail === "object" && Object.keys(s.detail as object).length > 0 && (
                      <details className="mt-0.5"><summary className="cursor-pointer text-2xs text-faint">detail</summary><Json value={s.detail} className="mt-1 max-h-40" /></details>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      <Panel title="Popularity observations" note="CrUX buckets are coarse bands; Tranco is a research rank. Neither is traffic." bodyClass="">
        {p.popularity.length === 0 ? <Empty title="No popularity data">This site has not appeared in an ingested CrUX or Tranco list.</Empty> : (
          <div className="max-h-72 overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-panel"><tr className="border-b border-rule text-left text-xs text-muted">
                <th className="px-3 py-1.5 font-medium">Source</th><th className="px-2 py-1.5 font-medium">Period</th><th className="px-2 py-1.5 font-medium">Country</th>
                <th className="px-2 py-1.5 font-medium">Bucket / rank</th><th className="px-2 py-1.5 font-medium">Origin</th><th className="px-3 py-1.5 font-medium">Retrieved</th>
              </tr></thead>
              <tbody>
                {p.popularity.map((o, i) => (
                  <tr key={i} className="border-b border-rule/60 last:border-0">
                    <td className="px-3 py-1">{o.source_url ? <Ext href={o.source_url}>{o.source}</Ext> : o.source}</td>
                    <td className="tnum px-2 py-1">{o.period ?? <Dash />}</td>
                    <td className="px-2 py-1 uppercase">{o.country ?? "global"}</td>
                    <td className="tnum px-2 py-1">{o.rank_bucket ? cruxLabel(o.rank_bucket) : o.rank ? `#${fmtInt(o.rank)}` : <Dash />}</td>
                    <td className="max-w-[180px] truncate px-2 py-1 text-xs text-muted">{o.origin ?? <Dash />}</td>
                    <td className="px-3 py-1 text-xs text-faint">{fmtDate(o.retrieved_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title="Sources and provenance" bodyClass="">
        {p.sources.length === 0 ? <Empty title="No sources recorded" /> : (
          <ul className="divide-y divide-rule/60">
            {p.sources.map((s, i) => (
              <li key={i} className="px-3 py-1.5 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone="outline">{humanize(s.type)}</Badge>
                  <span className="min-w-0 truncate text-muted">{s.ref}</span>
                  <span className="ml-auto text-xs text-faint">{fmtDate(s.first_seen)}{s.last_seen !== s.first_seen && ` – ${fmtDate(s.last_seen)}`}</span>
                </div>
                {s.original && <p className="mt-0.5 font-mono text-2xs text-faint">original: {s.original}</p>}
                {s.payload != null && <details><summary className="cursor-pointer text-2xs text-faint">payload</summary><Json value={s.payload} className="mt-1 max-h-40" /></details>}
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel title="Organization and contacts">
        <KV rows={[
          ["Organization", p.organization ? <>{p.organization.name} <span className="text-xs text-faint">({p.organization.source ?? "unknown source"})</span></> : null],
          ["Contact status", humanize(w.contact_status)],
        ]} />
        {p.contacts.length > 0 && (
          <table className="mt-2 w-full text-sm">
            <tbody>
              {p.contacts.map((c, i) => (
                <tr key={i} className="border-t border-rule/60">
                  <td className="py-1 pr-2">{c.email ?? <Dash />}</td>
                  <td className="py-1 pr-2 text-muted">{[c.name, c.role].filter(Boolean).join(", ")}</td>
                  <td className="py-1 pr-2"><Badge tone={c.verification_status === "VERIFIED" ? "active" : "outline"}>{humanize(c.verification_status) || "unverified"}</Badge></td>
                  <td className="py-1 text-xs"><Ext href={c.source_url}>source</Ext></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      <Panel title="Business links" note="Found on the homepage during classification">
        {links == null || (typeof links === "object" && Object.keys(links as object).length === 0) ? <Empty title="None found" className="px-0 py-1" /> : <BusinessLinks links={links} />}
      </Panel>
    </div>
  );
}

function BusinessLinks({ links }: { links: unknown }) {
  if (Array.isArray(links)) {
    return <ul className="space-y-0.5 text-sm">{links.map((l, i) => <li key={i}>{typeof l === "string" ? <Ext href={l} /> : <span className="font-mono text-xs">{JSON.stringify(l)}</span>}</li>)}</ul>;
  }
  if (typeof links === "object" && links) {
    return (
      <KV rows={Object.entries(links as Record<string, unknown>).map(([k, v]) => [humanize(k),
        Array.isArray(v) ? <span className="flex flex-col">{v.map((x, i) => typeof x === "string" && x.startsWith("http") ? <Ext key={i} href={x} /> : <span key={i}>{String(x)}</span>)}</span>
          : typeof v === "string" && v.startsWith("http") ? <Ext href={v} /> : val(v)])} />
    );
  }
  return <span>{String(links)}</span>;
}

/* ================================================================ Classification */
function EvidenceList({ items, tone }: { items: Record<string, unknown>[] | null; tone: "support" | "contra" }) {
  if (!items || items.length === 0) return <p className="text-sm text-faint">None recorded.</p>;
  return (
    <ul className="space-y-1">
      {items.map((e, i) => (
        <li key={i} className={cx("rounded border-l-2 bg-sunken/60 px-2 py-1 text-sm", tone === "support" ? "border-active" : "border-danger")}>
          <span className="font-medium">{String(e.signal ?? "signal")}</span>
          {e.hypothesis != null && <span className="ml-1.5 text-xs text-muted">→ {humanize(String(e.hypothesis))}</span>}
          {typeof e.weight === "number" && <span className="tnum ml-1.5 text-xs text-faint">weight {e.weight}</span>}
          {e.value !== undefined && e.value !== null && <div className="break-all font-mono text-2xs text-muted">{typeof e.value === "object" ? JSON.stringify(e.value) : String(e.value)}</div>}
        </li>
      ))}
    </ul>
  );
}

export function Classification({ p }: { p: Profile }) {
  const [sel, setSel] = useState(0);
  if (p.classification.length === 0) return <Empty title="Not classified yet">Classification runs after the qualify stage. You can queue it with Rescan.</Empty>;
  const c = p.classification[sel];
  return (
    <div className="grid gap-3 xl:grid-cols-[1fr_260px]">
      <div className="space-y-3">
        <Panel title={<>{c.primary_category ? humanize(c.primary_category) : "Unclassified"} {c.is_current && <Badge tone="accent" className="ml-1">current</Badge>}</>}
          actions={<Confidence value={c.confidence} />}
          note={`${c.method ?? "method unknown"} · engine ${c.engine ?? "?"} · ${fmtDate(c.created_at, true)}`}>
          <KV rows={[
            ["Publisher", c.is_publisher === null ? "unknown" : c.is_publisher ? "Yes" : "No"],
            ["Secondary", c.secondary?.length ? c.secondary.map(humanize).join(", ") : null],
          ]} />
        </Panel>
        <div className="grid gap-3 lg:grid-cols-2">
          <Panel title={`Supporting evidence (${c.supporting?.length ?? 0})`}><EvidenceList items={c.supporting} tone="support" /></Panel>
          <Panel title={`Contradictory evidence (${c.contradictory?.length ?? 0})`}><EvidenceList items={c.contradictory} tone="contra" /></Panel>
        </div>
        <Panel title={`Pages inspected (${c.pages_inspected?.length ?? 0})`}>
          {c.pages_inspected?.length ? <ul className="space-y-0.5 text-sm">{c.pages_inspected.map((u) => <li key={u}><Ext href={u} /></li>)}</ul> : <p className="text-sm text-faint">None.</p>}
        </Panel>
        {c.features && <Panel title="Extracted features"><details><summary className="cursor-pointer text-sm text-muted">Show raw features</summary><Json value={c.features} className="mt-2 max-h-96" /></details></Panel>}
      </div>
      <Panel title="History" bodyClass="">
        <ul className="divide-y divide-rule/60">
          {p.classification.map((h, i) => (
            <li key={h.id}>
              <button onClick={() => setSel(i)} className={cx("w-full px-3 py-1.5 text-left text-sm hover:bg-sunken", i === sel && "bg-accent-soft")}>
                <div className="flex items-center justify-between gap-1"><span>{h.primary_category ? humanize(h.primary_category) : "—"}</span><span className="tnum text-xs text-muted">{fmtPct(h.confidence)}</span></div>
                <div className="text-2xs text-faint">{fmtDate(h.created_at, true)}{h.is_current && " · current"}</div>
              </button>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}

/* ================================================================ Ad-tech */
const CAT_ORDER = ["ad_server", "adsense", "header_bidding", "ssp", "monetization_partner", "native", "video", "identity", "cmp", "analytics"];

function TechDetail({ t }: { t: Technology }) {
  const d = t.detail ?? {};
  const entries = Object.entries(d).filter(([, v]) => !(Array.isArray(v) && v.length === 0) && v !== null && v !== "");
  if (entries.length === 0) return null;
  const known: Record<string, string> = {
    configured_bidders: "Bidders configured", requested_bidders: "Bidders requested", responding_bidders: "Bidders responding",
    network_codes: "GAM network codes", mcm_child_networks: "MCM child networks", ad_unit_paths: "Ad unit paths",
    unmapped_bidders: "Unmapped bidder codes", instances: "Instances", s2s_bidders: "Server-side bidders",
  };
  return (
    <div className="mt-2 grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[max-content_1fr]">
      {entries.map(([k, v]) => (
        <div key={k} className="contents">
          <span className="text-muted">
            {known[k] ?? humanize(k)}
            {k === "mcm_child_networks" && <Tip text="Multiple Customer Management: inventory is managed via a parent partner network."><span className="ml-1 cursor-help text-faint">?</span></Tip>}
            {k === "responding_bidders" && <Tip text="Bidders that returned a response on the sampled pages. Not proof of wins, fill or revenue."><span className="ml-1 cursor-help text-faint">?</span></Tip>}
          </span>
          <span className="min-w-0">
            {Array.isArray(v) && v.every((x) => typeof x !== "object")
              ? <span className="flex flex-wrap gap-1">{v.map((x) => <span key={String(x)} className="rounded-sm bg-sunken px-1 font-mono text-2xs">{String(x)}</span>)}</span>
              : Array.isArray(v) ? <Json value={v} className="max-h-32" /> : val(v)}
          </span>
        </div>
      ))}
    </div>
  );
}

export function AdTech({ p }: { p: Profile }) {
  const groups = useMemo(() => {
    const g: Record<string, Technology[]> = {};
    for (const t of p.technologies) (g[t.category] ??= []).push(t);
    return Object.entries(g).sort((a, b) => {
      const ia = CAT_ORDER.indexOf(a[0]), ib = CAT_ORDER.indexOf(b[0]);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a[0].localeCompare(b[0]);
    });
  }, [p.technologies]);
  const [open, setOpen] = useState<Record<number, boolean>>({});

  if (p.technologies.length === 0) return <Empty title="No ad-tech scan results">The ad-tech stage has not run for this website yet, or found nothing to record. Queue it with Rescan → adtech.</Empty>;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded border border-rule bg-panel px-3 py-2">
        <p className="max-w-prose text-xs text-muted">Statuses describe what was observed on sampled pages. Active signals show an integration executing; they do not prove auctions, fill, revenue or a commercial agreement. Hover a badge for its meaning.</p>
        <StatusLegend />
      </div>
      {groups.map(([cat, techs]) => (
        <Panel key={cat} title={`${humanize(cat)} (${techs.length})`} bodyClass="">
          <ul className="divide-y divide-rule/60">
            {techs.map((t) => (
              <li key={t.id} className="px-3 py-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{t.vendor_name}</span>
                  <span className="font-mono text-2xs text-faint">{t.vendor_key}</span>
                  <StatusBadge status={t.status} />
                  <Confidence value={t.confidence} />
                  <button className="ml-auto text-xs text-accent hover:underline" onClick={() => setOpen({ ...open, [t.id]: !open[t.id] })}>
                    {open[t.id] ? "Hide" : "Show"} evidence ({t.evidence.length})
                  </button>
                </div>
                <TechDetail t={t} />
                {open[t.id] && (
                  t.evidence.length === 0 ? <p className="mt-2 text-xs text-faint">No evidence rows. Status derived from absence or scan outcome.</p> : (
                    <table className="mt-2 w-full text-xs">
                      <thead><tr className="text-left text-muted"><th className="py-1 pr-2 font-medium">Kind</th><th className="py-1 pr-2 font-medium">Value</th><th className="py-1 pr-2 font-medium">Observation</th><th className="py-1 font-medium">Page</th></tr></thead>
                      <tbody>
                        {t.evidence.map((e, i) => (
                          <tr key={i} className="border-t border-rule/60 align-top">
                            <td className="whitespace-nowrap py-1 pr-2"><Badge tone="outline">{e.kind}</Badge></td>
                            <td className="max-w-[360px] break-all py-1 pr-2 font-mono text-2xs">{e.value ?? <Dash />}</td>
                            <td className="py-1 pr-2 text-muted">{e.observation ?? <Dash />}</td>
                            <td className="max-w-[240px] truncate py-1"><Ext href={e.page_url} /></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )
                )}
              </li>
            ))}
          </ul>
        </Panel>
      ))}
    </div>
  );
}

/* ================================================================ Inventory */
export function Inventory({ p }: { p: Profile }) {
  const inv = p.inventory;
  if (!inv) return <Empty title="No inventory profile">Requires a successful rendered ad-tech scan.</Empty>;
  const types = (inv.types as Record<string, number> | undefined) ?? {};
  const sizes = (inv.advertised_sizes as string[] | undefined) ?? [];
  const known = new Set(["types", "advertised_sizes", "note", "pages_sampled", "placements_per_page", "containers_with_creative_iframe", "video"]);
  return (
    <div className="space-y-3">
      <p className="rounded border border-possible/30 bg-possible-soft px-3 py-2 text-sm text-possible">
        {String(inv.note ?? "Sampled pages only; counts are placements observed in the DOM, not impressions or fill.")}
      </p>
      <div className="grid gap-3 lg:grid-cols-2">
        <Panel title="Sample">
          <KV rows={[
            ["Pages sampled", val(inv.pages_sampled)],
            ["Placements per page", val(inv.placements_per_page)],
            ["Containers with creative iframe", val(inv.containers_with_creative_iframe)],
            ["Video player (IMA) seen", val(inv.video)],
            ...Object.entries(inv).filter(([k]) => !known.has(k)).map(([k, v]) => [humanize(k), val(v)] as [string, React.ReactNode]),
          ]} />
        </Panel>
        <Panel title="Placement types" note="Placements observed across sampled pages">
          {Object.keys(types).length === 0 ? <p className="text-sm text-faint">None observed.</p> : (
            <table className="w-full text-sm"><tbody>
              {Object.entries(types).sort((a, b) => b[1] - a[1]).map(([k, n]) => (
                <tr key={k} className="border-b border-rule/60 last:border-0"><td className="py-1">{humanize(k)}</td><td className="tnum py-1 text-right">{n}</td></tr>
              ))}
            </tbody></table>
          )}
        </Panel>
      </div>
      <Panel title={`Advertised sizes (${sizes.length})`} note="From GPT slots and Prebid ad units">
        {sizes.length === 0 ? <p className="text-sm text-faint">None declared.</p> : <div className="flex flex-wrap gap-1">{sizes.map((s) => <span key={s} className="rounded-sm bg-sunken px-1.5 py-0.5 font-mono text-xs">{s}</span>)}</div>}
      </Panel>
    </div>
  );
}

/* ================================================================ ads.txt */
export function AdsTxt({ p }: { p: Profile }) {
  const [q, setQ] = useState("");
  const [rel, setRel] = useState<"" | "DIRECT" | "RESELLER">("");
  const files = p.ads_txt.files;
  const cur = files.find((f) => f.is_current);
  const recs = p.ads_txt.records.filter((r) => (!rel || r.relationship === rel) && (!q || `${r.ad_system_domain} ${r.seller_account_id} ${r.vendor_key ?? ""} ${r.seller?.name ?? ""}`.toLowerCase().includes(q.toLowerCase())));
  if (files.length === 0) return <Empty title="No ads.txt fetched">The supply stage fetches ads.txt. Queue it with Rescan → supply.</Empty>;

  const vars = cur?.variables ?? {};
  const malformed = cur?.malformed_sample;
  return (
    <div className="space-y-3">
      <Panel title="Files" bodyClass="">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-rule text-left text-xs text-muted">
            <th className="px-3 py-1.5 font-medium">URL</th><th className="px-2 py-1.5 font-medium">Status</th><th className="px-2 py-1.5 font-medium">HTTP</th>
            <th className="px-2 py-1.5 text-right font-medium">Records</th><th className="px-2 py-1.5 text-right font-medium">Malformed</th><th className="px-3 py-1.5 font-medium">Fetched</th>
          </tr></thead>
          <tbody>
            {files.map((f) => (
              <tr key={f.id} className={cx("border-b border-rule/60 last:border-0", !f.is_current && "text-muted")}>
                <td className="max-w-[360px] truncate px-3 py-1"><Ext href={f.final_url ?? f.url} />{f.is_current && <Badge tone="accent" className="ml-1.5">current</Badge>}</td>
                <td className="px-2 py-1"><Badge tone={f.status === "OK" || f.status === "FOUND" ? "active" : f.status === "NOT_FOUND" ? "outline" : "possible"}>{humanize(f.status) || "?"}</Badge></td>
                <td className="tnum px-2 py-1">{f.http_status ?? <Dash />}</td>
                <td className="tnum px-2 py-1 text-right">{fmtInt(f.record_count)}</td>
                <td className={cx("tnum px-2 py-1 text-right", (f.malformed_count ?? 0) > 0 && "text-danger")}>{fmtInt(f.malformed_count)}</td>
                <td className="px-3 py-1 text-xs text-faint">{fmtDate(f.fetched_at, true)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      {cur && (
        <div className="grid gap-3 lg:grid-cols-2">
          <Panel title="Variables" note="OWNERDOMAIN, MANAGERDOMAIN, CONTACT and others">
            {Object.keys(vars).length === 0 ? <p className="text-sm text-faint">No variables declared.</p> : <KV rows={Object.entries(vars).map(([k, v]) => [<span key={k} className="font-mono text-xs">{k}</span>, val(v)])} />}
          </Panel>
          <Panel title={`Malformed lines (${cur.malformed_count ?? 0})`}>
            {!malformed || (Array.isArray(malformed) && malformed.length === 0) ? <p className="text-sm text-faint">None.</p> : Array.isArray(malformed) ? (
              <ul className="max-h-48 space-y-0.5 overflow-auto font-mono text-2xs">
                {malformed.map((m, i) => <li key={i} className="break-all rounded bg-danger-soft/60 px-1.5 py-0.5">{typeof m === "string" ? m : JSON.stringify(m)}</li>)}
              </ul>
            ) : <Json value={malformed} />}
          </Panel>
        </div>
      )}

      <Panel title={`Records (${p.ads_txt.records.length})`} note="Seller info joined from sellers.json where available" bodyClass=""
        actions={<>
          <Input className="h-6 w-44 text-xs" placeholder="Filter records…" value={q} onChange={(e) => setQ(e.target.value)} />
          {(["", "DIRECT", "RESELLER"] as const).map((r) => <Button key={r} size="sm" variant={rel === r ? "secondary" : "ghost"} onClick={() => setRel(r)}>{r || "All"}</Button>)}
        </>}>
        {recs.length === 0 ? <Empty title="No records" /> : (
          <div className="max-h-[520px] overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-panel"><tr className="border-b border-rule text-left text-xs text-muted">
                <th className="px-3 py-1.5 font-medium">Line</th><th className="px-2 py-1.5 font-medium">Ad system</th><th className="px-2 py-1.5 font-medium">Account ID</th>
                <th className="px-2 py-1.5 font-medium">Relationship</th><th className="px-2 py-1.5 font-medium">Vendor</th><th className="px-2 py-1.5 font-medium">Seller (sellers.json)</th>
                <th className="px-2 py-1.5 font-medium">Type</th><th className="px-3 py-1.5 font-medium">Domain match</th>
              </tr></thead>
              <tbody>{recs.map((r, i) => <RecordRow key={i} r={r} />)}</tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}

function RecordRow({ r }: { r: AdsTxtRecordT }) {
  const s = r.seller;
  return (
    <tr className="border-b border-rule/60 last:border-0">
      <td className="tnum px-3 py-1 text-faint">{r.line_no ?? ""}</td>
      <td className="px-2 py-1">{r.ad_system_domain}</td>
      <td className="max-w-[180px] truncate px-2 py-1 font-mono text-xs" title={r.seller_account_id}>
        <Link className="hover:text-accent hover:underline" href={`/explorer?f=${encodeURIComponent(JSON.stringify({ seller_account_id: r.seller_account_id, ads_txt_systems: [r.ad_system_domain] }))}`}>{r.seller_account_id}</Link>
      </td>
      <td className="px-2 py-1"><Badge tone={r.relationship === "DIRECT" ? "accent" : "outline"}>{r.relationship ?? "?"}</Badge></td>
      <td className="px-2 py-1 text-xs text-muted">{r.vendor_key ?? <Dash />}</td>
      <td className="max-w-[220px] truncate px-2 py-1">{s ? (s.is_confidential ? <span className="text-faint">confidential</span> : s.name ?? <Dash />) : <span className="text-xs text-faint">not in sellers.json</span>}</td>
      <td className="px-2 py-1 text-xs">{s?.seller_type ? humanize(s.seller_type) : <Dash />}</td>
      <td className="px-3 py-1 text-xs">
        {!s ? <Dash /> : s.domain_matches_site
          ? <Tip text={`sellers.json domain ${s.domain} matches this site`}><Badge tone="active">matches</Badge></Tip>
          : <Tip text={s.domain ? `sellers.json domain is ${s.domain}` : "No domain in sellers.json"}><span className="text-muted">{s.domain ?? "no domain"}</span></Tip>}
      </td>
    </tr>
  );
}

/* ================================================================ Supply chain */
export function Supply({ id }: { id: number }) {
  const graph = useApi<SupplyGraph>(`/api/supply/graph/${id}`);
  const related = useApi<RelatedResp>(`/api/websites/${id}/related`);
  return (
    <div className="grid gap-3 xl:grid-cols-[3fr_2fr]">
      <Panel title="Declared supply paths" note="ads.txt ad systems. Line style shows the declared relationship; node fill shows what was observed on the page.">
        {graph.loading && !graph.data ? <Loading /> : graph.error ? <ErrorState error={graph.error} onRetry={graph.reload} /> :
          !graph.data || graph.data.edges.length === 0 ? <Empty title="No ads.txt records" className="px-0">Nothing declared, or ads.txt was not fetched yet.</Empty> : <SupplyGraphView g={graph.data} />}
      </Panel>
      <Panel title="Possibly related publishers" note="Other sites sharing a DIRECT seller account. A hypothesis only." bodyClass="">
        {related.loading && !related.data ? <Loading /> : related.error ? <ErrorState error={related.error} onRetry={related.reload} className="m-3" /> :
          !related.data || related.data.groups.length === 0 ? <Empty title="No shared DIRECT accounts found" /> : (
            <ul className="divide-y divide-rule/60">
              {related.data.groups.map((g) => {
                const network = g.hypothesis.startsWith("shared account of an intermediary");
                return (
                  <li key={`${g.ad_system_domain}|${g.seller_account_id}`} className="px-3 py-2 text-sm">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="font-medium">{g.ad_system_domain}</span>
                      <span className="font-mono text-xs text-muted">{g.seller_account_id}</span>
                      {g.seller_type && <Badge tone="outline">{humanize(g.seller_type)}</Badge>}
                      <span className="tnum ml-auto text-xs text-muted">{g.websites.length} site{g.websites.length === 1 ? "" : "s"}</span>
                    </div>
                    {(g.seller_name || g.seller_domain) && <p className="text-xs text-muted">{g.seller_name}{g.seller_domain && ` (${g.seller_domain})`}</p>}
                    <p className={cx("mt-1 text-xs", network ? "text-faint" : "text-possible")}>{g.hypothesis}</p>
                    <div className="mt-1 flex flex-wrap gap-x-2 gap-y-0.5 text-xs">
                      {g.websites.slice(0, 30).map((w) => <Link key={w.id} href={`/websites/${w.id}`} className="text-accent hover:underline">{w.host}</Link>)}
                      {g.websites.length > 30 && <span className="text-faint">+{g.websites.length - 30} more</span>}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
      </Panel>
    </div>
  );
}

function nodeFill(status: string | null | undefined) {
  switch (status) {
    case "DETECTED_ACTIVE_SIGNALS": return { fill: "rgb(var(--active-soft))", stroke: "rgb(var(--active))" };
    case "POSSIBLE": return { fill: "rgb(var(--possible-soft))", stroke: "rgb(var(--possible))" };
    case "DECLARED_AUTHORIZATION_ONLY": return { fill: "rgb(var(--declared-soft))", stroke: "rgb(var(--declared))" };
    default: return { fill: "rgb(var(--panel))", stroke: "rgb(var(--rule))" };
  }
}

function SupplyGraphView({ g }: { g: SupplyGraph }) {
  const site = g.nodes.find((n) => n.type === "site");
  const sys = g.nodes.filter((n) => n.type === "ad_system");
  const edgesBy = new Map<string, SupplyGraph["edges"]>();
  for (const e of g.edges) edgesBy.set(e.to, [...(edgesBy.get(e.to) ?? []), e]);
  const sorted = [...sys].sort((a, b) => {
    const da = edgesBy.get(a.id)?.some((e) => e.relationship === "DIRECT") ? 0 : 1;
    const db = edgesBy.get(b.id)?.some((e) => e.relationship === "DIRECT") ? 0 : 1;
    return da - db || a.label.localeCompare(b.label);
  });
  const shown = sorted.slice(0, 40);
  const size = 560, cx0 = size / 2, cy0 = size / 2, R = 210;
  const [hover, setHover] = useState<string | null>(null);

  return (
    <div>
      <svg viewBox={`0 0 ${size} ${size}`} className="mx-auto block h-auto w-full max-w-[560px]" role="img" aria-label={`Supply graph for ${site?.label}`}>
        {shown.map((n, i) => {
          const a = (i / shown.length) * Math.PI * 2 - Math.PI / 2;
          const x = cx0 + R * Math.cos(a), y = cy0 + R * Math.sin(a);
          const es = edgesBy.get(n.id) ?? [];
          const direct = es.some((e) => e.relationship === "DIRECT");
          const reseller = es.some((e) => e.relationship !== "DIRECT");
          const accounts = es.reduce((s, e) => s + e.accounts, 0);
          const dim = hover && hover !== n.id;
          return (
            <line key={`l${n.id}`} x1={cx0} y1={cy0} x2={x} y2={y} stroke={direct ? "rgb(var(--accent))" : "rgb(var(--faint))"}
              strokeWidth={Math.min(1 + accounts * 0.4, 3)} strokeDasharray={direct && !reseller ? undefined : direct ? "6 2" : "3 3"} opacity={dim ? 0.15 : 0.7} />
          );
        })}
        {shown.map((n, i) => {
          const a = (i / shown.length) * Math.PI * 2 - Math.PI / 2;
          const x = cx0 + R * Math.cos(a), y = cy0 + R * Math.sin(a);
          const c = nodeFill(n.observed_status);
          const es = edgesBy.get(n.id) ?? [];
          const right = Math.cos(a) >= 0;
          const label = n.label.length > 22 ? n.label.slice(0, 21) + "…" : n.label;
          return (
            <g key={n.id} onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)} opacity={hover && hover !== n.id ? 0.35 : 1}>
              <title>{`${n.label}\n${es.map((e) => `${e.relationship ?? "?"}: ${e.accounts} account(s)`).join("\n")}\nObserved: ${n.observed_status ?? "no vendor mapping / not scanned"}`}</title>
              <circle cx={x} cy={y} r={14} fill="transparent" />
              <circle cx={x} cy={y} r={6} fill={c.fill} stroke={c.stroke} strokeWidth={2} />
              <text x={x + (right ? 10 : -10)} y={y + 3.5} fontSize={10.5} textAnchor={right ? "start" : "end"} fill="rgb(var(--muted))" fontFamily="IBM Plex Sans, sans-serif">{label}</text>
            </g>
          );
        })}
        <circle cx={cx0} cy={cy0} r={34} fill="rgb(var(--accent-soft))" stroke="rgb(var(--accent))" strokeWidth={2} />
        <text x={cx0} y={cy0 + 4} fontSize={11} fontWeight={600} textAnchor="middle" fill="rgb(var(--ink))" fontFamily="IBM Plex Sans, sans-serif">
          {(site?.label ?? "").length > 14 ? (site?.label ?? "").slice(0, 13) + "…" : site?.label}
        </text>
      </svg>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
        <span className="inline-flex items-center gap-1.5"><svg width="24" height="6"><line x1="0" y1="3" x2="24" y2="3" stroke="rgb(var(--accent))" strokeWidth="2" /></svg>DIRECT</span>
        <span className="inline-flex items-center gap-1.5"><svg width="24" height="6"><line x1="0" y1="3" x2="24" y2="3" stroke="rgb(var(--faint))" strokeWidth="2" strokeDasharray="3 3" /></svg>RESELLER</span>
        <span className="inline-flex items-center gap-1.5"><svg width="24" height="6"><line x1="0" y1="3" x2="24" y2="3" stroke="rgb(var(--accent))" strokeWidth="2" strokeDasharray="6 2" /></svg>both</span>
        <span>Node fill: green active signals, amber possible, violet ads.txt only, white not observed or unmapped.</span>
      </div>
      {sorted.length > shown.length && <p className="mt-1 text-xs text-faint">Showing 40 of {sorted.length} ad systems (DIRECT first). See the ads.txt tab for all records.</p>}
    </div>
  );
}

/* ================================================================ Opportunities */
export function Opportunities({ p }: { p: Profile }) {
  if (p.opportunities.length === 0) return <Empty title="No opportunity hypotheses">Opportunities are assessed in the score stage. Non-publishers get none.</Empty>;
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted">Each opportunity is a hypothesis built from observed evidence. None of them asserts revenue, fill, impressions or existing contracts.</p>
      {p.opportunities.map((o, i) => (
        <Panel key={i} title={<span className="flex items-center gap-2"><span className="grid h-5 w-5 place-items-center rounded-sm bg-accent-soft font-mono text-xs font-semibold text-accent">{o.type}</span>{o.label || OPPORTUNITY_LABELS[o.type]}</span>}
          actions={<Confidence value={o.confidence} />}>
          <div className="grid gap-x-6 gap-y-3 lg:grid-cols-2">
            <div className="space-y-3">
              <section><h3 className="mb-0.5 text-xs font-medium text-muted">Hypothesis</h3><p className="text-sm">{o.hypothesis ?? <Dash />}</p></section>
              <section>
                <h3 className="mb-1 text-xs font-medium text-muted">Evidence</h3>
                {o.evidence?.length ? (
                  <ul className="space-y-1">
                    {o.evidence.map((e, k) => (
                      <li key={k} className="flex flex-wrap items-center gap-1.5 text-sm">
                        {"vendor" in e ? <>
                          <span className="font-mono text-xs">{String(e.vendor)}</span>
                          <StatusBadge status={e.status as string | null} />
                          {typeof e.confidence === "number" && <Confidence value={e.confidence} />}
                        </> : <>
                          <span>{String(e.signal ?? "")}</span>
                          {Object.entries(e).filter(([k2]) => k2 !== "signal").map(([k2, v]) => <span key={k2} className="font-mono text-2xs text-muted">{k2}: {typeof v === "object" ? JSON.stringify(v) : String(v)}</span>)}
                        </>}
                      </li>
                    ))}
                  </ul>
                ) : <p className="text-sm text-faint">None listed.</p>}
              </section>
            </div>
            <div className="space-y-3">
              <section>
                <h3 className="mb-0.5 text-xs font-medium text-muted">Missing information</h3>
                {o.missing?.length ? <ul className="list-disc space-y-0.5 pl-4 text-sm text-possible">{o.missing.map((m) => <li key={m}><span className="text-ink">{m}</span></li>)}</ul> : <p className="text-sm text-faint">Nothing flagged.</p>}
              </section>
              <section><h3 className="mb-0.5 text-xs font-medium text-muted">How to verify</h3><p className="text-sm">{o.verification ?? <Dash />}</p></section>
              <section><h3 className="mb-0.5 text-xs font-medium text-muted">Suggested approach</h3><p className="text-sm">{o.approach ?? <Dash />}</p></section>
            </div>
          </div>
          <p className="mt-2 text-2xs text-faint">engine {o.engine} · {fmtDate(o.created_at, true)}</p>
        </Panel>
      ))}
    </div>
  );
}

/* ================================================================ Score */
const COMPONENTS: [keyof NonNullable<Profile["score"]>, string][] = [
  ["popularity", "Popularity"], ["ad_opportunity", "Ad opportunity"], ["audience_geo", "Audience GEO"],
  ["inventory", "Inventory"], ["actionability", "Actionability"], ["evidence_quality", "Evidence quality"],
];

export function ScoreTab({ p }: { p: Profile }) {
  const s = p.score;
  if (!s) return <Empty title="Not scored yet">Scoring runs after the ad-tech stage.</Empty>;
  const max = s.max ?? {};
  const overridden = s.queue !== s.computed_queue;
  return (
    <div className="grid gap-3 xl:grid-cols-2">
      <Panel title={<span className="flex items-baseline gap-2">Score <span className="tnum text-[20px] font-semibold">{fmtScore(s.total)}</span><span className="text-xs font-normal text-muted">/ 100</span></span>}
        actions={<Confidence value={s.evidence_confidence} />} note={`engine ${s.engine ?? "?"} · ${fmtDate(s.created_at, true)}`}>
        <div className="space-y-2.5">
          {COMPONENTS.map(([k, label]) => {
            const v = (s[k] as number | null) ?? 0;
            const m = max[k as string] ?? 0;
            const lines = s.explanation?.[k as string] ?? [];
            return (
              <div key={k}>
                <div className="flex items-center justify-between text-sm"><span>{label}</span><span className="tnum text-muted">{fmtScore(v)} / {m || "?"}</span></div>
                <div className="relative mt-0.5 h-2 rounded-full bg-sunken">
                  <div className="absolute inset-y-0 left-0 rounded-full bg-accent" style={{ width: m ? `${Math.min(100, (v / m) * 100)}%` : "0%" }} />
                </div>
                {lines.length > 0 && <ul className="mt-1 space-y-0.5 text-xs text-muted">{lines.map((l, i) => <li key={i}>{l}</li>)}</ul>}
              </div>
            );
          })}
          {Object.entries(s.explanation ?? {}).filter(([k]) => !COMPONENTS.some(([c]) => c === k)).map(([k, lines]) => (
            <div key={k}><p className="text-sm">{humanize(k)}</p><ul className="text-xs text-muted">{lines.map((l, i) => <li key={i}>{l}</li>)}</ul></div>
          ))}
        </div>
      </Panel>
      <div className="space-y-3">
        <Panel title="Queue">
          <KV rows={[
            ["Effective queue", <QueueBadge key="q" queue={s.queue} />],
            ["Computed queue", <span key="c" className="inline-flex items-center gap-1.5"><QueueBadge queue={s.computed_queue} />{overridden && <span className="text-xs text-possible">manually overridden</span>}</span>],
            ["Next action", s.next_action],
          ]} />
          {s.queue === "HIGH_POTENTIAL_VERIFY_TRAFFIC" && <p className="mt-2 text-xs text-muted">{QUEUE_META.VERIFIED_HIGH_VALUE.tip} Use “Override queue” above after researching traffic.</p>}
        </Panel>
        <Panel title={`Missing critical fields (${s.missing_critical?.length ?? 0})`} note="Missing data scores zero">
          {s.missing_critical?.length ? <ul className="list-disc space-y-0.5 pl-4 text-sm">{s.missing_critical.map((m) => <li key={m}>{m}</li>)}</ul> : <p className="text-sm text-faint">None.</p>}
        </Panel>
        <Panel title="Score history">
          {p.score_history.length === 0 ? <p className="text-sm text-faint">No history.</p> : (
            <>
              <Sparkline points={[...p.score_history].reverse().map((h) => ({ x: h.at, y: h.total ?? 0, label: `${fmtDate(h.at, true)}: ${fmtScore(h.total)} (${QUEUE_META[h.queue ?? ""]?.label ?? h.queue ?? "?"})` }))} />
              <table className="mt-2 w-full text-xs"><tbody>
                {p.score_history.map((h, i) => (
                  <tr key={i} className="border-t border-rule/60"><td className="py-1 text-muted">{fmtDate(h.at, true)}</td><td className="tnum py-1 text-right">{fmtScore(h.total)}</td><td className="py-1 pl-3 text-right"><QueueBadge queue={h.queue} /></td></tr>
                ))}
              </tbody></table>
            </>
          )}
        </Panel>
        {p.overrides.length > 0 && (
          <Panel title="Manual overrides" bodyClass="">
            <table className="w-full text-xs"><tbody>
              {p.overrides.map((o, i) => (
                <tr key={i} className={cx("border-b border-rule/60 last:border-0", !o.active && "text-faint line-through")}>
                  <td className="px-3 py-1">{o.field}</td><td className="px-2 py-1 font-medium">{o.value}</td><td className="px-2 py-1">{o.reason}</td>
                  <td className="px-2 py-1">user #{o.user_id}</td><td className="px-3 py-1 text-right">{fmtDate(o.created_at, true)}</td>
                </tr>
              ))}
            </tbody></table>
          </Panel>
        )}
      </div>
    </div>
  );
}

/* ================================================================ Scans */
export function Scans({ p }: { p: Profile }) {
  const [page, setPage] = useState<{ id: number; url: string } | null>(null);
  if (p.scans.length === 0) return <Empty title="No scans yet" />;
  return (
    <div className="space-y-3">
      {p.scans.map((s) => (
        <Panel key={s.id} bodyClass=""
          title={<span className="flex flex-wrap items-center gap-2">Scan #{s.id} <Badge tone="outline">{s.kind}</Badge>{s.method && <Badge tone="outline">{s.method}</Badge>}
            <Badge tone={s.status === "OK" || s.status === "DONE" ? "active" : s.status === "FAILED" ? "danger" : "possible"}>{humanize(s.status)}</Badge></span>}
          actions={<span className="text-xs text-faint">{fmtDate(s.started_at, true)}</span>}>
          {s.error && <p className="border-b border-rule px-3 py-1.5 font-mono text-xs text-danger">{s.error}</p>}
          {s.pages.length === 0 ? <p className="px-3 py-2 text-sm text-faint">No pages recorded.</p> : (
            <table className="w-full text-sm"><tbody>
              {s.pages.map((pg) => (
                <tr key={pg.id} className="border-b border-rule/60 last:border-0">
                  <td className="w-24 px-3 py-1 text-xs text-muted">{pg.role ?? "page"}</td>
                  <td className="max-w-[420px] truncate px-2 py-1"><Ext href={pg.final_url ?? pg.url} />{pg.final_url && pg.final_url !== pg.url && <span className="ml-1 text-2xs text-faint">(redirected)</span>}</td>
                  <td className="tnum px-2 py-1">{pg.http_status ?? <Dash />}</td>
                  <td className="px-2 py-1 text-xs">{pg.blocked_reason ? <Badge tone="possible">blocked: {pg.blocked_reason}</Badge> : null}</td>
                  <td className="px-3 py-1 text-right">
                    <Button size="sm" variant="ghost" disabled={!pg.network_request_count} onClick={() => setPage({ id: pg.id, url: pg.url })}>
                      {fmtInt(pg.network_request_count)} requests
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody></table>
          )}
        </Panel>
      ))}
      <NetworkDrawer page={page} onClose={() => setPage(null)} />
    </div>
  );
}

function NetworkDrawer({ page, onClose }: { page: { id: number; url: string } | null; onClose: () => void }) {
  const r = useApi<NetworkResp>(page ? `/api/scan-pages/${page.id}/network` : null);
  const [q, setQ] = useState("");
  const [tab, setTab] = useState<"net" | "scripts" | "globals">("net");
  const reqs = (r.data?.network_requests ?? []).filter((n) => !q || JSON.stringify(n).toLowerCase().includes(q.toLowerCase()));
  const keys = useMemo(() => {
    const ks = new Set<string>();
    for (const n of (r.data?.network_requests ?? []).slice(0, 50)) Object.keys(n).forEach((k) => ks.add(k));
    return ["url", ...[...ks].filter((k) => k !== "url")].slice(0, 5);
  }, [r.data]);
  return (
    <Drawer open={!!page} onClose={onClose} width={900} title={<span className="block truncate">Network: <span className="font-normal text-muted">{page?.url}</span></span>}>
      {r.loading && !r.data ? <Loading /> : r.error ? <ErrorState error={r.error} onRetry={r.reload} className="m-3" /> : r.data && (
        <div>
          <div className="sticky top-0 z-10 flex flex-wrap items-center gap-2 border-b border-rule bg-panel px-3 py-2">
            {(["net", "scripts", "globals"] as const).map((t) => (
              <Button key={t} size="sm" variant={tab === t ? "secondary" : "ghost"} onClick={() => setTab(t)}>
                {t === "net" ? `Requests (${r.data!.network_requests.length})` : t === "scripts" ? `Scripts (${r.data!.script_urls.length})` : "Page globals"}
              </Button>
            ))}
            {tab !== "globals" && <Input className="ml-auto h-6 w-56 text-xs" placeholder="Filter…" value={q} onChange={(e) => setQ(e.target.value)} />}
          </div>
          {tab === "net" && (
            <table className="w-full text-xs">
              <thead><tr className="border-b border-rule text-left text-muted">{keys.map((k) => <th key={k} className="px-3 py-1 font-medium">{k}</th>)}</tr></thead>
              <tbody>
                {reqs.slice(0, 2000).map((n, i) => (
                  <tr key={i} className="border-b border-rule/60 align-top">
                    {keys.map((k) => <td key={k} className={cx("px-3 py-0.5", k === "url" ? "max-w-[560px] break-all font-mono text-2xs" : "whitespace-nowrap")}>{val(n[k])}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {tab === "scripts" && (
            <ul className="divide-y divide-rule/60 font-mono text-2xs">
              {r.data.script_urls.filter((u) => !q || u.toLowerCase().includes(q.toLowerCase())).map((u, i) => <li key={i} className="break-all px-3 py-1">{u}</li>)}
            </ul>
          )}
          {tab === "globals" && <div className="p-3"><Json value={r.data.page_globals} /></div>}
        </div>
      )}
    </Drawer>
  );
}
