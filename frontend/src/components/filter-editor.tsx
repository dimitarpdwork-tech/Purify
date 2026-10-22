"use client";

import { AD_STATUSES, CATEGORIES, CRUX_BUCKETS, cruxLabel, humanize, MONETIZATION_TYPES, OPPORTUNITY_LABELS, OPPORTUNITY_TYPES, OUTREACH_STAGES, QUEUE_META, QUEUES, SOURCE_TYPES, STATUS_META } from "@/lib/domain";
import type { AdStatus, Vendor, WebsiteFilter } from "@/lib/types";
import { Checkbox, Field, Input, MultiSelect, Select } from "./ui";

const statusLabel = (s: string) => STATUS_META[s as AdStatus]?.label ?? s;

/** Remove empty values so the request body and saved views stay minimal. */
export function cleanFilter(f: WebsiteFilter): WebsiteFilter {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(f)) {
    if (v === undefined || v === "" || (Array.isArray(v) && v.length === 0)) continue;
    if (v === null && k !== "excluded") continue;
    out[k] = v;
  }
  return out as WebsiteFilter;
}

/** Number of active (non-default) filter conditions, for the "Filters (n)" chip. */
export function countFilters(f: WebsiteFilter): number {
  return Object.entries(cleanFilter(f)).filter(([k, v]) => k !== "sort" && !(k === "excluded" && v === false)).length;
}

function csvList(s: string): string[] {
  return s.split(/[,\s]+/).map((x) => x.trim()).filter(Boolean);
}

function ListInput({ value, onChange, placeholder, upper }: { value: string[] | null | undefined; onChange: (v: string[]) => void; placeholder?: string; upper?: boolean }) {
  return (
    <Input key={(value ?? []).join(",")} defaultValue={(value ?? []).join(", ")} placeholder={placeholder}
      onBlur={(e) => onChange(csvList(upper ? e.target.value.toUpperCase() : e.target.value.toLowerCase()))}
      onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
  );
}

function NumInput({ value, onChange, placeholder }: { value: number | null | undefined; onChange: (v: number | null) => void; placeholder?: string }) {
  return (
    <Input type="number" min={0} key={String(value ?? "")} defaultValue={value ?? ""} placeholder={placeholder}
      onBlur={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
      onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
  );
}

export function FilterEditor({ value, onChange, vendors, dense }: { value: WebsiteFilter; onChange: (f: WebsiteFilter) => void; vendors: Vendor[]; dense?: boolean }) {
  const set = <K extends keyof WebsiteFilter>(k: K, v: WebsiteFilter[K]) => onChange({ ...value, [k]: v });
  const vendorKeys = vendors.map((v) => v.key);
  const vendorName = (k: string) => vendors.find((v) => v.key === k)?.name ?? k;
  const has = value.has_vendors ?? [];
  const hasActiveOnly = has.length > 0 && has.every((h) => h.statuses?.length === 1 && h.statuses[0] === "DETECTED_ACTIVE_SIGNALS");

  const grid = dense ? "grid gap-x-3 gap-y-2.5 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6" : "grid gap-x-3 gap-y-2.5 sm:grid-cols-2 lg:grid-cols-3";

  return (
    <div className="space-y-3">
      <div className={grid}>
        <Field label="Domain contains">
          <Input key={value.q ?? ""} defaultValue={value.q ?? ""} placeholder="e.g. news or example.com"
            onBlur={(e) => set("q", e.target.value.trim() || null)} onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
        </Field>
        <Field label="Category">
          <MultiSelect options={CATEGORIES} value={value.categories ?? []} onChange={(v) => set("categories", v)} labels={humanize} />
        </Field>
        <Field label="Publisher">
          <Select value={value.is_publisher === true ? "yes" : value.is_publisher === false ? "no" : ""} onChange={(e) => set("is_publisher", e.target.value === "" ? null : e.target.value === "yes")}>
            <option value="">Any</option><option value="yes">Publishers only</option><option value="no">Non-publishers</option>
          </Select>
        </Field>
        <Field label="Queue">
          <MultiSelect options={QUEUES} value={value.queues ?? []} onChange={(v) => set("queues", v)} labels={(q) => QUEUE_META[q]?.label ?? q} />
        </Field>
        <Field label="Opportunity types" hint="Matches any selected">
          <MultiSelect options={OPPORTUNITY_TYPES} value={value.opportunity_types ?? []} onChange={(v) => set("opportunity_types", v)} labels={(t) => `${t}: ${OPPORTUNITY_LABELS[t]}`} />
        </Field>
        <Field label="Min score">
          <NumInput value={value.min_score} onChange={(v) => set("min_score", v)} placeholder="0–100" />
        </Field>

        <Field label="CrUX bucket at most" hint="Popularity band, not visits">
          <Select value={value.max_crux_bucket ?? ""} onChange={(e) => set("max_crux_bucket", e.target.value ? Number(e.target.value) : null)}>
            <option value="">Any</option>
            {CRUX_BUCKETS.map((b) => <option key={b} value={b}>{cruxLabel(b)}</option>)}
          </Select>
        </Field>
        <Field label="Tranco rank at most">
          <NumInput value={value.max_tranco_rank} onChange={(v) => set("max_tranco_rank", v)} placeholder="e.g. 100000" />
        </Field>
        <Field label="Primary GEO" hint="ISO2, comma separated">
          <ListInput value={value.geos} onChange={(v) => set("geos", v)} placeholder="US, GB, DE" upper />
        </Field>
        <Field label="Monetization type">
          <MultiSelect options={MONETIZATION_TYPES} value={value.monetization_types ?? []} onChange={(v) => set("monetization_types", v)} labels={humanize} />
        </Field>
        <Field label="Outreach stage">
          <MultiSelect options={OUTREACH_STAGES} value={value.outreach_stages ?? []} onChange={(v) => set("outreach_stages", v)} />
        </Field>
        <Field label="Source">
          <MultiSelect options={SOURCE_TYPES} value={value.sources ?? []} onChange={(v) => set("sources", v)} labels={humanize} />
        </Field>

        <Field label="GAM status">
          <MultiSelect options={AD_STATUSES} value={value.gam ?? []} onChange={(v) => set("gam", v)} labels={statusLabel} />
        </Field>
        <Field label="AdSense status">
          <MultiSelect options={AD_STATUSES} value={value.adsense ?? []} onChange={(v) => set("adsense", v)} labels={statusLabel} />
        </Field>
        <Field label="Prebid status">
          <MultiSelect options={AD_STATUSES} value={value.prebid ?? []} onChange={(v) => set("prebid", v)} labels={statusLabel} />
        </Field>
        <Field label="Has vendors" hint={<Checkbox className="text-2xs" checked={hasActiveOnly} label="active signals only (all must match)"
          onChange={(on) => set("has_vendors", has.map((h) => ({ vendor: h.vendor, statuses: on ? ["DETECTED_ACTIVE_SIGNALS"] : ["DETECTED_ACTIVE_SIGNALS", "POSSIBLE"] })))} />}>
          <MultiSelect options={vendorKeys} value={has.map((h) => h.vendor)} labels={vendorName} placeholder={vendors.length ? "Any" : "No vendors loaded"}
            onChange={(v) => set("has_vendors", v.map((k) => ({ vendor: k, statuses: hasActiveOnly ? ["DETECTED_ACTIVE_SIGNALS"] : ["DETECTED_ACTIVE_SIGNALS", "POSSIBLE"] })))} />
        </Field>
        <Field label="Lacks vendors" hint="None active or possible (may still be unscanned pages)">
          <MultiSelect options={vendorKeys} value={value.lacks_vendors ?? []} onChange={(v) => set("lacks_vendors", v)} labels={vendorName} placeholder={vendors.length ? "Any" : "No vendors loaded"} />
        </Field>
        <Field label="ads.txt ad system" hint="Declares any of these">
          <ListInput value={value.ads_txt_systems} onChange={(v) => set("ads_txt_systems", v)} placeholder="google.com, pubmatic.com" />
        </Field>

        <Field label="Seller account ID" hint="Exact ads.txt account">
          <Input key={value.seller_account_id ?? ""} defaultValue={value.seller_account_id ?? ""} placeholder="pub-1234…"
            onBlur={(e) => set("seller_account_id", e.target.value.trim() || null)} onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
        </Field>
        <Field label="Ad-tech analyzed">
          <Select value={value.analyzed === true ? "yes" : value.analyzed === false ? "no" : ""} onChange={(e) => set("analyzed", e.target.value === "" ? null : e.target.value === "yes")}>
            <option value="">Any</option><option value="yes">Analyzed</option><option value="no">Not analyzed yet</option>
          </Select>
        </Field>
        <Field label="Excluded">
          <Select value={value.excluded === true ? "yes" : value.excluded === null ? "any" : "no"} onChange={(e) => set("excluded", e.target.value === "any" ? null : e.target.value === "yes")}>
            <option value="no">Hide excluded</option><option value="yes">Excluded only</option><option value="any">Include excluded</option>
          </Select>
        </Field>
      </div>
    </div>
  );
}

/** Human-readable summary of a filter for previews / saved view tooltips. */
export function describeFilter(f: WebsiteFilter, vendorName: (k: string) => string = (k) => k): string[] {
  const out: string[] = [];
  if (f.q) out.push(`domain contains "${f.q}"`);
  if (f.categories?.length) out.push(`category in ${f.categories.map(humanize).join(", ")}`);
  if (f.is_publisher !== undefined && f.is_publisher !== null) out.push(f.is_publisher ? "publishers only" : "non-publishers");
  if (f.queues?.length) out.push(`queue in ${f.queues.map((q) => QUEUE_META[q]?.label ?? q).join(", ")}`);
  if (f.opportunity_types?.length) out.push(`opportunity ${f.opportunity_types.join("/")}`);
  if (f.max_crux_bucket) out.push(`CrUX ${cruxLabel(f.max_crux_bucket)} or better`);
  if (f.max_tranco_rank) out.push(`Tranco ≤ ${f.max_tranco_rank.toLocaleString()}`);
  if (f.geos?.length) out.push(`GEO ${f.geos.join(", ")}`);
  if (f.monetization_types?.length) out.push(`monetization ${f.monetization_types.map(humanize).join(", ")}`);
  if (f.gam?.length) out.push(`GAM ${f.gam.map(statusLabel).join("/")}`);
  if (f.adsense?.length) out.push(`AdSense ${f.adsense.map(statusLabel).join("/")}`);
  if (f.prebid?.length) out.push(`Prebid ${f.prebid.map(statusLabel).join("/")}`);
  if (f.has_vendors?.length) out.push(`has ${f.has_vendors.map((h) => vendorName(h.vendor)).join(" + ")}`);
  if (f.lacks_vendors?.length) out.push(`no ${f.lacks_vendors.map(vendorName).join(", ")} observed`);
  if (f.ads_txt_systems?.length) out.push(`ads.txt declares ${f.ads_txt_systems.join(", ")}`);
  if (f.seller_account_id) out.push(`seller account ${f.seller_account_id}`);
  if (f.min_score !== undefined && f.min_score !== null) out.push(`score ≥ ${f.min_score}`);
  if (f.outreach_stages?.length) out.push(`outreach ${f.outreach_stages.join(", ")}`);
  if (f.sources?.length) out.push(`source ${f.sources.join(", ")}`);
  if (f.analyzed === true) out.push("ad-tech analyzed");
  if (f.analyzed === false) out.push("not analyzed yet");
  if (f.excluded === true) out.push("excluded only");
  if (f.excluded === null) out.push("including excluded");
  return out;
}
