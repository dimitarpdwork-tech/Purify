"use client";

import { cx, Tip } from "./ui";
import { fmtInt } from "@/lib/domain";

/** Single-series horizontal bar list: one hue (accent), value in ink, per-row hover tooltip. */
export function BarList({ data, label, onClickRow, tip, className, max }: {
  data: [string, number][];
  label?: (k: string) => React.ReactNode;
  onClickRow?: (k: string) => void;
  tip?: (k: string, v: number) => React.ReactNode;
  className?: string;
  max?: number;
}) {
  const top = max ?? Math.max(1, ...data.map(([, v]) => v));
  const total = data.reduce((a, [, v]) => a + v, 0);
  return (
    <ul className={cx("space-y-1", className)}>
      {data.map(([k, v]) => {
        const row = (
          <div className={cx("grid w-full grid-cols-[minmax(0,1.6fr)_minmax(48px,1fr)_auto] items-center gap-2 rounded px-1 py-0.5 text-sm",
            onClickRow && "cursor-pointer hover:bg-sunken")}>
            <span className="truncate text-ink">{label ? label(k) : k}</span>
            <span className="relative h-2.5">
              <span className="absolute inset-y-0 left-0 rounded-r-[4px] bg-accent/80" style={{ width: `${Math.max(v > 0 ? 1.5 : 0, (v / top) * 100)}%` }} />
            </span>
            <span className="tnum w-14 text-right text-muted">{fmtInt(v)}</span>
          </div>
        );
        const t = tip ? tip(k, v) : `${fmtInt(v)} websites (${total ? Math.round((v / total) * 100) : 0}% of shown)`;
        return (
          <li key={k}>
            <Tip text={t} className="flex w-full">
              {onClickRow ? <button type="button" className="w-full text-left" onClick={() => onClickRow(k)}>{row}</button> : row}
            </Tip>
          </li>
        );
      })}
    </ul>
  );
}

/** Compact line chart for score history (single series, 2px line, hover dots with native tooltip). */
export function Sparkline({ points, height = 60, max = 100 }: { points: { x: string; y: number; label: string }[]; height?: number; max?: number }) {
  if (points.length === 0) return null;
  const w = 320;
  const pad = 6;
  const xs = (i: number) => (points.length === 1 ? w / 2 : pad + (i * (w - 2 * pad)) / (points.length - 1));
  const ys = (v: number) => height - pad - (Math.min(v, max) / max) * (height - 2 * pad);
  const d = points.map((p, i) => `${i ? "L" : "M"}${xs(i).toFixed(1)},${ys(p.y).toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${height}`} className="h-auto w-full max-w-[420px]" role="img" aria-label="Score history">
      <line x1={0} x2={w} y1={ys(50)} y2={ys(50)} stroke="rgb(var(--rule))" strokeDasharray="2 3" />
      <path d={d} fill="none" stroke="rgb(var(--accent))" strokeWidth={2} strokeLinejoin="round" />
      {points.map((p, i) => (
        <g key={i}>
          <circle cx={xs(i)} cy={ys(p.y)} r={4} fill="rgb(var(--accent))" stroke="rgb(var(--panel))" strokeWidth={2} />
          <circle cx={xs(i)} cy={ys(p.y)} r={10} fill="transparent"><title>{p.label}</title></circle>
        </g>
      ))}
    </svg>
  );
}
