"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { BoardResp, Profile, WebsiteRow } from "@/lib/types";
import { fmtInt, humanize, OUTREACH_STAGES } from "@/lib/domain";
import { CruxCell, OppChips, QueueBadge, SiteLink, StatusBadge, TrancoCell } from "@/components/domain";
import { useToast } from "@/components/toast";
import { useAuth } from "@/components/auth";
import { Button, cx, Drawer, Empty, ErrorState, Field, Input, Loading, PageHeader, Select, Textarea } from "@/components/ui";

function Card({ r, stages, onMove, onOpen, canEdit, dragging, setDragging }: {
  r: WebsiteRow; stages: string[]; onMove: (r: WebsiteRow, s: string) => void; onOpen: (r: WebsiteRow) => void; canEdit: boolean;
  dragging: number | null; setDragging: (id: number | null) => void;
}) {
  return (
    <li draggable={canEdit} onDragStart={(e) => { e.dataTransfer.setData("text/plain", String(r.id)); setDragging(r.id); }} onDragEnd={() => setDragging(null)}
      className={cx("rounded border border-rule bg-panel p-2 text-sm", canEdit && "cursor-grab active:cursor-grabbing", dragging === r.id && "opacity-40")}>
      <div className="flex items-start justify-between gap-1">
        <SiteLink id={r.id} host={r.host} className="min-w-0 truncate" />
        <span className="tnum shrink-0 text-xs font-semibold">{r.score_total === null ? "—" : Math.round(r.score_total)}</span>
      </div>
      <div className="mt-0.5 truncate text-xs text-muted">{r.primary_category ? humanize(r.primary_category) : "Unclassified"}{r.primary_geo && ` · ${r.primary_geo}`}</div>
      <div className="mt-1 flex flex-wrap items-center gap-1 text-xs">
        <CruxCell bucket={r.crux_best_bucket} />{r.tranco_best_rank && <span className="text-faint">·</span>}<TrancoCell rank={r.tranco_best_rank} />
        <span className="ml-auto"><OppChips types={r.opportunity_types} /></span>
      </div>
      <div className="mt-1 flex flex-wrap gap-1"><StatusBadge status={r.gam_status} prefix="GAM" compact /><StatusBadge status={r.prebid_status} prefix="PB" compact /><StatusBadge status={r.adsense_status} prefix="AS" compact /></div>
      <div className="mt-1.5 flex items-center gap-1">
        <QueueBadge queue={r.queue} />
        <span className="ml-auto flex items-center gap-1">
          <button className="text-xs text-accent hover:underline" onClick={() => onOpen(r)}>Notes</button>
          {canEdit && (
            <select aria-label={`Move ${r.host}`} className="h-5 rounded border border-rule bg-panel text-2xs" value={r.outreach_stage ?? "Discovered"} onChange={(e) => onMove(r, e.target.value)}>
              {stages.map((s) => <option key={s}>{s}</option>)}
            </select>
          )}
        </span>
      </div>
    </li>
  );
}

function NotesDrawer({ row, onClose, onSaved }: { row: WebsiteRow | null; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const { can } = useAuth();
  const prof = useApi<Profile>(row ? `/api/websites/${row.id}` : null);
  const [notes, setNotes] = useState<string | null>(null);
  const [stage, setStage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const curNotes = notes ?? prof.data?.outreach?.notes ?? "";
  const curStage = stage ?? prof.data?.outreach?.stage ?? row?.outreach_stage ?? "Discovered";
  const close = () => { setNotes(null); setStage(null); onClose(); };
  const save = async () => {
    if (!row) return;
    setBusy(true);
    try {
      await api(`/api/websites/${row.id}/outreach`, { method: "PATCH", body: { stage: curStage, notes: curNotes } });
      toast("Outreach saved"); onSaved(); close();
    } catch (e) { toast((e as Error).message, "error"); } finally { setBusy(false); }
  };
  return (
    <Drawer open={!!row} onClose={close} width={460} title={row?.host}>
      {prof.loading && !prof.data ? <Loading /> : prof.error ? <ErrorState error={prof.error} className="m-3" /> : prof.data && (
        <div className="space-y-3 p-4">
          <Field label="Stage">
            <Select value={curStage} onChange={(e) => setStage(e.target.value)} disabled={!can("analyst")}>{OUTREACH_STAGES.map((s) => <option key={s}>{s}</option>)}</Select>
          </Field>
          <Field label="Notes"><Textarea rows={10} value={curNotes} onChange={(e) => setNotes(e.target.value)} disabled={!can("analyst")} /></Field>
          {prof.data.outreach?.imported_status && <p className="text-xs text-muted">Imported status: {prof.data.outreach.imported_status}</p>}
          {prof.data.score?.next_action && <p className="rounded bg-sunken px-2 py-1.5 text-xs"><span className="text-muted">Next action: </span>{prof.data.score.next_action}</p>}
          {prof.data.contacts.length > 0 && (
            <div><p className="mb-1 text-xs font-medium text-muted">Contacts</p>
              <ul className="text-sm">{prof.data.contacts.map((c, i) => <li key={i}>{c.email ?? c.name} <span className="text-xs text-faint">{c.verification_status}</span></li>)}</ul></div>
          )}
          <div className="flex justify-between gap-2">
            <SiteLink id={row!.id} host="Open full profile" className="text-sm text-accent" />
            {can("analyst") && <Button variant="primary" size="sm" busy={busy} onClick={save}>Save outreach</Button>}
          </div>
        </div>
      )}
    </Drawer>
  );
}

export default function PipelinePage() {
  const toast = useToast();
  const { can } = useAuth();
  const board = useApi<BoardResp>("/api/outreach/board", { poll: 10000 });
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<WebsiteRow | null>(null);
  const [dragging, setDragging] = useState<number | null>(null);
  const [over, setOver] = useState<string | null>(null);

  const move = async (r: WebsiteRow, stage: string) => {
    if (stage === r.outreach_stage) return;
    const prev = board.data;
    if (prev) {
      const next: BoardResp = { ...prev, board: Object.fromEntries(Object.entries(prev.board).map(([s, rows]) => [s, rows.filter((x) => x.id !== r.id)])) };
      next.board[stage] = [{ ...r, outreach_stage: stage }, ...(next.board[stage] ?? [])];
      board.setData(next);
    }
    try {
      await api(`/api/websites/${r.id}/outreach`, { method: "PATCH", body: { stage } });
      toast(`Moved ${r.host} to ${stage}`);
      void board.reload();
    } catch (e) {
      board.setData(prev);
      toast((e as Error).message, "error");
    }
  };

  if (board.loading && !board.data) return <Loading label="Loading pipeline…" />;
  if (board.error && !board.data) return <ErrorState error={board.error} onRetry={board.reload} />;
  const data = board.data!;
  const stages = data.stages.length ? data.stages : OUTREACH_STAGES;
  const filt = (rows: WebsiteRow[]) => rows.filter((r) => !q || r.host.includes(q.toLowerCase()));
  const totalCards = Object.values(data.board).reduce((a, r) => a + r.length, 0);

  return (
    <div className="flex h-[calc(100vh-76px)] flex-col gap-3">
      <PageHeader title="Opportunity pipeline"
        sub="Drag a card or use its stage menu to move it. Discovered shows suggested prospects from the high-potential and technical queues."
        actions={<><Input className="w-52" placeholder="Filter by domain…" value={q} onChange={(e) => setQ(e.target.value)} /><Button size="sm" variant="ghost" onClick={board.reload}>Refresh</Button></>} />
      {board.error && <ErrorState error={board.error} onRetry={board.reload} />}
      {totalCards === 0 ? (
        <Empty title="The pipeline is empty">Prospects appear in Discovered once websites are scored into the high-potential or technical-opportunity queues. You can also set an outreach stage from a website profile or with explorer bulk actions.</Empty>
      ) : (
        <div className="min-h-0 flex-1 overflow-x-auto">
          <div className="flex h-full gap-2">
            {stages.map((s) => {
              const rows = filt(data.board[s] ?? []);
              return (
                <section key={s}
                  onDragOver={(e) => { if (can("analyst")) { e.preventDefault(); setOver(s); } }} onDragLeave={() => setOver(null)}
                  onDrop={(e) => {
                    e.preventDefault(); setOver(null);
                    const id = Number(e.dataTransfer.getData("text/plain"));
                    const r = Object.values(data.board).flat().find((x) => x.id === id);
                    if (r) void move(r, s);
                  }}
                  className={cx("flex h-full w-[250px] shrink-0 flex-col rounded border bg-sunken/60", over === s ? "border-accent" : "border-rule")}>
                  <header className="flex items-center justify-between border-b border-rule px-2 py-1.5">
                    <h2 className="text-sm font-semibold">{s}</h2>
                    <span className="tnum text-xs text-muted">{fmtInt(rows.length)}</span>
                  </header>
                  {s === "Discovered" && <p className="border-b border-rule px-2 py-1 text-2xs text-muted">Suggested, top 100 by score. Verify traffic before contacting.</p>}
                  <ul className="min-h-0 flex-1 space-y-1.5 overflow-y-auto p-1.5">
                    {rows.length === 0 && <li className="px-1 py-2 text-xs text-faint">Empty</li>}
                    {rows.map((r) => <Card key={r.id} r={r} stages={stages} onMove={move} onOpen={setOpen} canEdit={can("analyst")} dragging={dragging} setDragging={setDragging} />)}
                  </ul>
                </section>
              );
            })}
          </div>
        </div>
      )}
      <NotesDrawer row={open} onClose={() => setOpen(null)} onSaved={board.reload} />
    </div>
  );
}
