"use client";

import type { WebsiteRow } from "@/lib/types";
import { humanize } from "@/lib/domain";
import { CruxCell, OppChips, QueueBadge, Score, SiteLink, StatusBadge, TrancoCell } from "./domain";
import { Dash, Empty } from "./ui";

/** Compact read-only website list used on the dashboard. */
export function SiteTable({ rows, empty }: { rows: WebsiteRow[]; empty: React.ReactNode }) {
  if (rows.length === 0) return <Empty title="Nothing here yet">{empty}</Empty>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-rule text-left text-xs text-muted">
            <th className="px-3 py-1.5 font-medium">Domain</th>
            <th className="px-2 py-1.5 font-medium">Category</th>
            <th className="px-2 py-1.5 font-medium">CrUX</th>
            <th className="px-2 py-1.5 font-medium">Tranco</th>
            <th className="px-2 py-1.5 font-medium">GAM · Prebid</th>
            <th className="px-2 py-1.5 font-medium">Opp.</th>
            <th className="px-2 py-1.5 font-medium">Queue</th>
            <th className="px-3 py-1.5 text-right font-medium">Score</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-b border-rule/60 last:border-0 hover:bg-sunken/60">
              <td className="max-w-[220px] truncate px-3 py-1"><SiteLink id={r.id} host={r.host} /></td>
              <td className="whitespace-nowrap px-2 py-1 text-muted">{r.primary_category ? humanize(r.primary_category) : <Dash />}</td>
              <td className="whitespace-nowrap px-2 py-1"><CruxCell bucket={r.crux_best_bucket} /></td>
              <td className="whitespace-nowrap px-2 py-1"><TrancoCell rank={r.tranco_best_rank} /></td>
              <td className="whitespace-nowrap px-2 py-1"><span className="inline-flex gap-1"><StatusBadge status={r.gam_status} prefix="GAM" compact /><StatusBadge status={r.prebid_status} prefix="PB" compact /></span></td>
              <td className="px-2 py-1"><OppChips types={r.opportunity_types} /></td>
              <td className="whitespace-nowrap px-2 py-1"><QueueBadge queue={r.queue} /></td>
              <td className="px-3 py-1 text-right"><Score value={r.score_total} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
