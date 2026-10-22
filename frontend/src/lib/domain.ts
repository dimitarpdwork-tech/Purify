import type { AdStatus } from "./types";

export const AD_STATUSES: AdStatus[] = [
  "DETECTED_ACTIVE_SIGNALS", "POSSIBLE", "DECLARED_AUTHORIZATION_ONLY", "NOT_OBSERVED", "SCAN_INCONCLUSIVE",
];

export const STATUS_META: Record<AdStatus, { label: string; tip: string; tone: "active" | "possible" | "declared" | "none" | "inconclusive" }> = {
  DETECTED_ACTIVE_SIGNALS: {
    label: "Active signals", tone: "active",
    tip: "Runtime evidence the integration executes on the page. Not proof of auctions, fill or a commercial agreement.",
  },
  POSSIBLE: {
    label: "Possible", tone: "possible",
    tip: "Weak or static evidence only (e.g. a script reference or code pattern). Needs confirmation in a rendered scan or a browser.",
  },
  DECLARED_AUTHORIZATION_ONLY: {
    label: "ads.txt only", tone: "declared",
    tip: "Listed in ads.txt only. Authorization to sell is declared, but no integration was observed on the inspected pages.",
  },
  NOT_OBSERVED: {
    label: "Not observed", tone: "none",
    tip: "Not seen on the pages inspected. It may still run on pages that were not sampled.",
  },
  SCAN_INCONCLUSIVE: {
    label: "Inconclusive", tone: "inconclusive",
    tip: "Scan failed or was blocked. Absence cannot be inferred.",
  },
};

export const OPPORTUNITY_LABELS: Record<string, string> = {
  A: "AdSense-focused publisher",
  B: "GAM without observed header bidding",
  C: "Limited observed header bidding competition",
  D: "Possibly underutilised ad inventory",
  E: "Existing monetization partner",
  F: "Popular site, no advertising observed",
  G: "Insufficient evidence",
};
export const OPPORTUNITY_TYPES = Object.keys(OPPORTUNITY_LABELS);

export const QUEUES = [
  "VERIFIED_HIGH_VALUE", "HIGH_POTENTIAL_VERIFY_TRAFFIC", "TECHNICAL_OPPORTUNITY", "NEEDS_REVIEW", "LOW_PRIORITY", "EXCLUDED",
];
export const QUEUE_META: Record<string, { label: string; tip: string }> = {
  VERIFIED_HIGH_VALUE: { label: "Verified high value", tip: "Set manually only, after traffic has been researched and confirmed." },
  HIGH_POTENTIAL_VERIFY_TRAFFIC: { label: "High potential, verify traffic", tip: "Strong opportunity and popularity signals. Research traffic manually before promoting." },
  TECHNICAL_OPPORTUNITY: { label: "Technical opportunity", tip: "Clear ad-tech opportunity on a less popular site. Check traffic before investing time." },
  NEEDS_REVIEW: { label: "Needs review", tip: "Classification or ad-tech evidence is uncertain. Inspect manually." },
  LOW_PRIORITY: { label: "Low priority", tip: "No strong opportunity or popularity signal. Monitor." },
  EXCLUDED: { label: "Excluded", tip: "Excluded by rule, manual decision or non-publisher category." },
  UNSCORED: { label: "Unscored", tip: "Not scored yet." },
};

export const OUTREACH_STAGES = [
  "Discovered", "Qualified", "Researching", "Ready to Contact", "Contacted", "In Discussion", "Testing", "Signed", "Rejected", "Existing Partner",
];

export const PUBLISHER_CATEGORIES = [
  "NEWS_PUBLISHER", "ENTERTAINMENT_PUBLISHER", "SPORTS_PUBLISHER", "GAMING_PUBLISHER", "TECHNOLOGY_PUBLISHER",
  "FINANCE_PUBLISHER", "LIFESTYLE_PUBLISHER", "EDUCATIONAL_PUBLISHER", "FORUM_COMMUNITY", "CONTENT_TOOL", "GENERAL_CONTENT_PUBLISHER",
];
export const CATEGORIES = [...PUBLISHER_CATEGORIES, "ECOMMERCE", "CORPORATE", "SAAS", "MARKETPLACE", "GOVERNMENT", "PARKED_DOMAIN", "OTHER", "UNKNOWN"];

// Base types come from runtime evidence; the _UNCONFIRMED variants are static-only (POSSIBLE) evidence.
const _MONETIZATION_BASE = ["GAM_HEADER_BIDDING", "GAM_ONLY_OBSERVED", "ADSENSE_ONLY_OBSERVED", "MANAGED_PARTNER", "OTHER_AD_TECH"];
export const MONETIZATION_TYPES = [
  ..._MONETIZATION_BASE,
  ..._MONETIZATION_BASE.map((t) => `${t}_UNCONFIRMED`),
  "NONE_OBSERVED", "INCONCLUSIVE", "UNSCANNED",
];

export const CRUX_BUCKETS = [1000, 5000, 10000, 50000, 100000, 500000, 1000000];
export const SOURCE_TYPES = ["crux", "tranco", "sellers_json", "legacy", "manual", "redirect"];
export const PIPELINE_STAGES = ["qualify", "classify", "supply", "adtech", "score"];
export const STAGE_STATUSES = ["PENDING", "RUNNING", "DONE", "SKIPPED", "FAILED"];

export function humanize(s: string | null | undefined): string {
  if (!s) return "";
  const t = s.replace(/_/g, " ").toLowerCase();
  return t.charAt(0).toUpperCase() + t.slice(1);
}

export function cruxLabel(b: number | string | null | undefined): string {
  if (b === null || b === undefined || b === "") return "";
  const n = Number(b);
  if (!Number.isFinite(n)) return String(b);
  if (n >= 1_000_000) return `Top ${n / 1_000_000}M`;
  if (n >= 1000) return `Top ${n / 1000}K`;
  return `Top ${n}`;
}

export function fmtInt(n: number | null | undefined): string {
  if (n === null || n === undefined) return "";
  return n.toLocaleString("en-US");
}

export function fmtPct(n: number | null | undefined): string {
  if (n === null || n === undefined) return "";
  return `${Math.round(n * 100)}%`;
}

export function fmtDate(iso: string | null | undefined, withTime = false): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const date = d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
  if (!withTime) return date;
  return `${date} ${d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}`;
}

export function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso).getTime();
  if (Number.isNaN(d)) return iso;
  const s = Math.round((Date.now() - d) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

export function fmtScore(n: number | null | undefined): string {
  if (n === null || n === undefined) return "";
  return n.toFixed(n % 1 === 0 ? 0 : 1);
}
