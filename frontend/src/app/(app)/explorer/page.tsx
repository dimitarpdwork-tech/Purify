"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { flexRender, getCoreRowModel, useReactTable, type ColumnDef, type RowSelectionState, type VisibilityState } from "@tanstack/react-table";
import { api, ApiError, downloadPost } from "@/lib/api";
import { useApi, useLocalStorage } from "@/lib/hooks";
import type { SavedView, SearchResult, VendorsResp, WebsiteFilter, WebsiteRow } from "@/lib/types";
import { fmtDate, fmtInt, fmtPct, fmtRelative, humanize, OUTREACH_STAGES, PIPELINE_STAGES } from "@/lib/domain";
import { cleanFilter, countFilters, describeFilter, FilterEditor } from "@/components/filter-editor";
import { CruxCell, OppChips, QueueBadge, Score, SiteLink, StatusBadge, StatusLegend, TrancoCell } from "@/components/domain";
import { Badge, Button, Checkbox, Confidence, cx, Dash, Empty, ErrorState, Field, Input, Modal, PageHeader, Select, Spinner, Textarea, Tip } from "@/components/ui";
import { useToast } from "@/components/toast";
import { useAuth } from "@/components/auth";

const SORTABLE = new Set(["host", "score_total", "crux_best_bucket", "tranco_best_rank", "last_analyzed_at", "primary_category",
  "classification_confidence", "evidence_confidence", "first_discovered_at", "queue", "discovery_priority"]);

const DEFAULT_FILTER: WebsiteFilter = { excluded: false, sort: ["-score_total", "crux_best_bucket"] };

const DEFAULT_HIDDEN: VisibilityState = {
  registrable_domain: false, is_publisher: false, country_signals: false, language: false, declared_ad_systems_count: false,
  excluded: false, exclusion_reason: false, first_discovered_at: false, discovery_priority: false, classification_confidence: false,
};

const COL_LABELS: Record<string, string> = {
  host: "Domain", registrable_domain: "Registrable domain", primary_category: "Category", is_publisher: "Publisher",
  classification_confidence: "Class. confidence", primary_geo: "Primary GEO", country_signals: "Country signals", language: "Language",
  crux_best_bucket: "CrUX bucket", tranco_best_rank: "Tranco rank", monetization_type: "Monetization", gam_status: "GAM",
  adsense_status: "AdSense", prebid_status: "Prebid", observed_partners: "Observed partners", declared_ad_systems_count: "ads.txt systems",
  opportunity_types: "Opportunities", score_total: "Score", queue: "Queue", evidence_confidence: "Confidence", contact_status: "Contact",
  last_analyzed_at: "Last analyzed", outreach_stage: "Outreach", excluded: "Excluded", exclusion_reason: "Exclusion reason",
  first_discovered_at: "Discovered", discovery_priority: "Discovery priority",
};

function cellFor(key: string, r: WebsiteRow): React.ReactNode {
  const v = (r as unknown as Record<string, unknown>)[key];
  switch (key) {
    case "host": return <SiteLink id={r.id} host={r.host} />;
    case "primary_category": return v ? <span className="text-muted">{humanize(String(v))}</span> : <Dash />;
    case "crux_best_bucket": return <CruxCell bucket={r.crux_best_bucket} />;
    case "tranco_best_rank": return <TrancoCell rank={r.tranco_best_rank} />;
    case "gam_status": case "adsense_status": case "prebid_status": return <StatusBadge status={v as string | null} />;
    case "observed_partners": {
      const xs = (v as string[] | null) ?? [];
      if (!xs.length) return <Dash />;
      return <Tip text={`Active signals observed: ${xs.join(", ")}`}><span className="block max-w-[180px] truncate text-xs text-muted">{xs.join(", ")}</span></Tip>;
    }
    case "opportunity_types": return <OppChips types={r.opportunity_types} />;
    case "score_total": return <Score value={r.score_total} />;
    case "queue": return <QueueBadge queue={r.queue} />;
    case "evidence_confidence": case "classification_confidence": return <Confidence value={v as number | null} />;
    case "monetization_type": return v ? <Badge tone="outline">{humanize(String(v))}</Badge> : <Dash />;
    case "last_analyzed_at": case "first_discovered_at": return v ? <span title={fmtDate(String(v), true)} className="text-xs text-muted">{fmtRelative(String(v))}</span> : <span className="text-xs text-faint">never</span>;
    case "contact_status": return v === "FOUND" ? <Badge tone="active">Found</Badge> : <span className="text-xs text-faint">{v ? humanize(String(v)) : "—"}</span>;
    case "is_publisher": case "excluded": return v === true ? "Yes" : v === false ? <span className="text-faint">No</span> : <Dash />;
    case "outreach_stage": return v ? <span className="text-xs">{String(v)}</span> : <Dash />;
    case "country_signals": return v ? <span className="font-mono text-2xs text-muted">{JSON.stringify(v)}</span> : <Dash />;
    case "declared_ad_systems_count": case "discovery_priority": return v === null || v === undefined ? <Dash /> : <span className="tnum">{fmtInt(Number(v))}</span>;
    default: return v === null || v === undefined || v === "" ? <Dash /> : String(v);
  }
}

function ExplorerInner() {
  const toast = useToast();
  const router = useRouter();
  const params = useSearchParams();
  const { can } = useAuth();

  const initial = useMemo<WebsiteFilter>(() => {
    const raw = params.get("f");
    if (raw) {
      try { return { ...DEFAULT_FILTER, ...(JSON.parse(raw) as WebsiteFilter) }; } catch { /* ignore */ }
    }
    return DEFAULT_FILTER;
  }, [params]);

  const [filter, setFilter] = useState<WebsiteFilter>(initial);
  const [draft, setDraft] = useState<WebsiteFilter>(initial);
  useEffect(() => { setFilter(initial); setDraft(initial); setPage(1); }, [initial]);

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useLocalStorage<number>("purify.explorer.pageSize", 50);
  const [visibility, setVisibility] = useLocalStorage<VisibilityState>("purify.explorer.columns", DEFAULT_HIDDEN);
  const [showFilters, setShowFilters] = useState(true);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});

  const [data, setData] = useState<SearchResult | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);

  const vendors = useApi<VendorsResp>("/api/vendors");
  const views = useApi<SavedView[]>("/api/views");
  const vendorList = useMemo(() => vendors.data?.vendors ?? [], [vendors.data]);
  const vendorName = useCallback((k: string) => vendorList.find((v) => v.key === k)?.name ?? k, [vendorList]);

  const search = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api<SearchResult>(`/api/websites/search?page=${page}&page_size=${pageSize}`, { body: cleanFilter(filter) });
      setData(res);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, String(e)));
    } finally {
      setLoading(false);
    }
  }, [filter, page, pageSize]);
  useEffect(() => { void search(); }, [search]);

  const applyFilter = (f: WebsiteFilter) => { setFilter(f); setPage(1); setRowSelection({}); };

  // ---- sort (server side, multi-column with shift-click)
  const sort = filter.sort ?? [];
  const sortState = (key: string): { dir: "asc" | "desc"; idx: number } | null => {
    const i = sort.findIndex((s) => s.replace(/^-/, "") === key);
    return i < 0 ? null : { dir: sort[i].startsWith("-") ? "desc" : "asc", idx: i };
  };
  const toggleSort = (key: string, multi: boolean) => {
    const cur = sortState(key);
    const nextDir = !cur ? (key === "host" || key === "crux_best_bucket" || key === "tranco_best_rank" || key === "primary_category" ? "asc" : "desc") : cur.dir === "desc" ? "asc" : cur.dir === "asc" && multi ? null : "desc";
    const token = nextDir === "desc" ? `-${key}` : nextDir === "asc" ? key : null;
    let next: string[];
    if (multi) {
      next = cur ? sort.map((s, i) => (i === cur.idx ? token : s)).filter((s): s is string => !!s) : [...sort, token!];
    } else {
      next = token ? [token] : [];
    }
    applyFilter({ ...filter, sort: next });
  };

  // ---- columns
  const columnKeys = data?.columns ?? Object.keys(COL_LABELS);
  const columns = useMemo<ColumnDef<WebsiteRow>[]>(() => [
    {
      id: "_select",
      enableHiding: false,
      header: ({ table }) => (
        <Checkbox checked={table.getIsAllPageRowsSelected()} indeterminate={table.getIsSomePageRowsSelected()} onChange={(v) => table.toggleAllPageRowsSelected(v)} />
      ),
      cell: ({ row }) => <Checkbox checked={row.getIsSelected()} onChange={(v) => row.toggleSelected(v)} />,
    },
    ...columnKeys.filter((k) => k !== "id").map<ColumnDef<WebsiteRow>>((k) => ({
      id: k,
      accessorKey: k,
      enableHiding: k !== "host",
      header: COL_LABELS[k] ?? humanize(k),
      cell: ({ row }) => cellFor(k, row.original),
    })),
  ], [columnKeys]);

  const table = useReactTable({
    data: data?.rows ?? [],
    columns,
    getCoreRowModel: getCoreRowModel(),
    getRowId: (r) => String(r.id),
    manualPagination: true,
    manualSorting: true,
    enableRowSelection: true,
    state: { rowSelection, columnVisibility: visibility },
    onRowSelectionChange: setRowSelection,
    onColumnVisibilityChange: (u) => setVisibility(typeof u === "function" ? u(visibility) : u),
  });

  const selectedIds = Object.keys(rowSelection).filter((k) => rowSelection[k]).map(Number);
  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const visibleCols = columnKeys.filter((k) => k !== "id" && visibility[k] !== false);

  // ---- modals
  const [modal, setModal] = useState<null | "add" | "columns" | "save" | "bulk" | "export">(null);

  return (
    <div className="space-y-2">
      <PageHeader title="Publisher explorer"
        sub="Server-side filter, sort and export. Shift-click column headers to sort by several columns."
        actions={<>
          <Button size="sm" onClick={() => setModal("columns")}>Columns</Button>
          <Button size="sm" onClick={() => setModal("export")}>Export</Button>
          {can("analyst") && <Button size="sm" variant="primary" onClick={() => setModal("add")}>Add domains</Button>}
        </>} />

      {/* Saved views + filter toggle */}
      <div className="flex flex-wrap items-center gap-1.5">
        <Button size="sm" variant={showFilters ? "secondary" : "ghost"} onClick={() => setShowFilters((v) => !v)}>
          Filters{countFilters(filter) ? ` (${countFilters(filter)})` : ""}
        </Button>
        <span className="mx-1 h-4 w-px bg-rule" aria-hidden />
        <span className="text-xs text-muted">Views</span>
        {views.loading && !views.data && <Spinner className="text-faint" />}
        {views.error && <span className="text-xs text-danger">{views.error.message}</span>}
        {views.data?.length === 0 && <span className="text-xs text-faint">none saved</span>}
        {views.data?.map((v) => (
          <span key={v.id} className="inline-flex items-center rounded border border-rule bg-panel text-xs">
            <Tip text={describeFilter(v.filters, vendorName).join("; ") || "No conditions"}>
              <button className="px-2 py-0.5 hover:text-accent" onClick={() => {
                const f = { ...DEFAULT_FILTER, ...v.filters };
                setDraft(f); applyFilter(f);
                if (v.columns?.length) setVisibility(Object.fromEntries(columnKeys.map((k) => [k, v.columns!.includes(k) || k === "host"])));
              }}>{v.name}</button>
            </Tip>
            <button aria-label={`Delete view ${v.name}`} className="border-l border-rule px-1.5 text-faint hover:text-danger" onClick={async () => {
              if (!confirm(`Delete saved view "${v.name}"?`)) return;
              try { await api(`/api/views/${v.id}`, { method: "DELETE" }); toast("View deleted"); void views.reload(); }
              catch (e) { toast((e as Error).message, "error"); }
            }}>×</button>
          </span>
        ))}
        <Button size="sm" variant="ghost" onClick={() => setModal("save")}>Save current view</Button>
      </div>

      {showFilters && (
        <div className="rounded border border-rule bg-panel p-3">
          <FilterEditor value={draft} onChange={setDraft} vendors={vendorList} dense />
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-rule pt-2">
            <StatusLegend />
            <div className="flex gap-1.5">
              <Button size="sm" variant="ghost" onClick={() => { setDraft(DEFAULT_FILTER); applyFilter(DEFAULT_FILTER); router.replace("/explorer"); }}>Reset</Button>
              <Button size="sm" variant="primary" onClick={() => applyFilter({ ...draft, sort: filter.sort })}>Apply filters</Button>
            </div>
          </div>
        </div>
      )}

      {/* Result bar */}
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <span className="tnum font-medium">{fmtInt(total)} websites</span>
          {loading && <Spinner className="text-faint" />}
          {sort.length > 0 && (
            <span className="text-xs text-muted">
              Sorted by {sort.map((s, i) => <span key={s}>{i > 0 && ", "}{COL_LABELS[s.replace(/^-/, "")] ?? s} {s.startsWith("-") ? "↓" : "↑"}</span>)}
            </span>
          )}
        </div>
        {selectedIds.length > 0 && (
          <div className="flex items-center gap-1.5 rounded border border-accent/40 bg-accent-soft px-2 py-0.5">
            <span className="text-xs font-medium text-accent">{selectedIds.length} selected</span>
            {can("analyst") && <Button size="sm" onClick={() => setModal("bulk")}>Bulk actions</Button>}
            <Button size="sm" onClick={() => setModal("export")}>Export selected</Button>
            <Button size="sm" variant="ghost" onClick={() => setRowSelection({})}>Clear</Button>
          </div>
        )}
      </div>

      {error && <ErrorState error={error} onRetry={search} />}

      <div className="overflow-hidden rounded border border-rule bg-panel">
        <div className="max-h-[calc(100vh-260px)] min-h-[200px] overflow-auto">
          <table className="w-full border-separate border-spacing-0 text-sm">
            <thead className="sticky top-0 z-10 bg-panel">
              {table.getHeaderGroups().map((hg) => (
                <tr key={hg.id}>
                  {hg.headers.map((h) => {
                    const key = h.column.id;
                    const sortable = SORTABLE.has(key);
                    const st = sortable ? sortState(key) : null;
                    return (
                      <th key={h.id} className={cx("whitespace-nowrap border-b border-rule px-2 py-1.5 text-left text-xs font-medium text-muted",
                        key === "_select" && "w-7 pl-3", key === "host" && "sticky left-0 z-10 bg-panel")}>
                        {sortable ? (
                          <button className={cx("inline-flex items-center gap-1 hover:text-ink", st && "text-ink")} onClick={(e) => toggleSort(key, e.shiftKey)}
                            title="Click to sort, shift-click to add as secondary sort">
                            {flexRender(h.column.columnDef.header, h.getContext())}
                            <span className="text-2xs text-faint">{st ? `${st.dir === "desc" ? "↓" : "↑"}${sort.length > 1 ? st.idx + 1 : ""}` : "↕"}</span>
                          </button>
                        ) : flexRender(h.column.columnDef.header, h.getContext())}
                      </th>
                    );
                  })}
                </tr>
              ))}
            </thead>
            <tbody className={cx(loading && "opacity-60")}>
              {table.getRowModel().rows.map((row) => (
                <tr key={row.id} className={cx("group", row.getIsSelected() ? "bg-accent-soft/60" : "hover:bg-sunken/60", row.original.excluded && "text-muted")}>
                  {row.getVisibleCells().map((c) => (
                    <td key={c.id} className={cx("whitespace-nowrap border-b border-rule/60 px-2 py-1 align-middle",
                      c.column.id === "_select" && "pl-3", c.column.id === "host" && "sticky left-0 max-w-[240px] truncate bg-panel group-hover:bg-sunken")}>
                      {flexRender(c.column.columnDef.cell, c.getContext())}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {!loading && !error && data && data.rows.length === 0 && (
            <Empty title={countFilters(filter) ? "No websites match these filters" : "No websites yet"}>
              {countFilters(filter) ? "Loosen a condition or reset the filters." : "Add domains, import a list, or start a discovery job to populate the explorer."}
            </Empty>
          )}
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-rule px-3 py-1.5 text-xs text-muted">
          <span>Popularity columns are CrUX buckets and Tranco ranks, not traffic.</span>
          <div className="flex items-center gap-1.5">
            <Select className="h-6 w-auto text-xs" value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}>
              {[25, 50, 100, 250, 500].map((n) => <option key={n} value={n}>{n} / page</option>)}
            </Select>
            <Button size="sm" disabled={page <= 1} onClick={() => setPage(1)} aria-label="First page">«</Button>
            <Button size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Prev</Button>
            <span className="tnum whitespace-nowrap px-1">Page {page} of {fmtInt(pages)}</span>
            <Button size="sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</Button>
          </div>
        </div>
      </div>

      <ColumnsModal open={modal === "columns"} onClose={() => setModal(null)} keys={columnKeys.filter((k) => k !== "id" && k !== "host")}
        visibility={visibility} setVisibility={setVisibility} />
      <AddDomainsModal open={modal === "add"} onClose={() => setModal(null)} onDone={() => { void search(); }} />
      <SaveViewModal open={modal === "save"} onClose={() => setModal(null)} filter={cleanFilter(filter)} columns={visibleCols} onSaved={() => void views.reload()} />
      <BulkModal open={modal === "bulk"} onClose={() => setModal(null)} ids={selectedIds} onDone={() => { setRowSelection({}); void search(); }} />
      <ExportModal open={modal === "export"} onClose={() => setModal(null)} filter={cleanFilter(filter)} selectedIds={selectedIds} total={total} columns={visibleCols} />
    </div>
  );
}

function ColumnsModal({ open, onClose, keys, visibility, setVisibility }: {
  open: boolean; onClose: () => void; keys: string[]; visibility: VisibilityState; setVisibility: (v: VisibilityState) => void;
}) {
  return (
    <Modal open={open} onClose={onClose} title="Columns" footer={<>
      <Button size="sm" variant="ghost" onClick={() => setVisibility(DEFAULT_HIDDEN)}>Reset to default</Button>
      <Button size="sm" variant="primary" onClick={onClose}>Done</Button></>}>
      <p className="mb-2 text-xs text-muted">Saved in this browser.</p>
      <div className="grid grid-cols-2 gap-1">
        {keys.map((k) => (
          <Checkbox key={k} checked={visibility[k] !== false} label={COL_LABELS[k] ?? humanize(k)} onChange={(v) => setVisibility({ ...visibility, [k]: v })} />
        ))}
      </div>
    </Modal>
  );
}

function AddDomainsModal({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const router = useRouter();
  const [text, setText] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ added: number; existing: number; invalid: { value: string; error: string }[]; ids: number[] } | null>(null);
  const domains = text.split(/[\s,;]+/).map((d) => d.trim()).filter(Boolean);
  const close = () => { setResult(null); setText(""); setNote(""); onClose(); };
  const submit = async () => {
    setBusy(true);
    try {
      const r = await api<typeof result>("/api/websites", { body: { domains, note: note || null } });
      setResult(r);
      toast(`Added ${r!.added} new, ${r!.existing} already known`);
      onDone();
    } catch (e) { toast((e as Error).message, "error"); }
    finally { setBusy(false); }
  };
  return (
    <Modal open={open} onClose={close} title="Add domains" width={560} footer={result ? <>
      {result.ids.length === 1 && <Button size="sm" onClick={() => router.push(`/websites/${result.ids[0]}`)}>Open profile</Button>}
      <Button size="sm" variant="primary" onClick={close}>Done</Button>
    </> : <>
      <Button size="sm" variant="ghost" onClick={close}>Cancel</Button>
      <Button size="sm" variant="primary" busy={busy} disabled={domains.length === 0 || domains.length > 1000} onClick={submit}>Add {domains.length || ""} domains</Button>
    </>}>
      {result ? (
        <div className="space-y-2 text-sm">
          <p><b className="tnum">{result.added}</b> new websites queued for analysis, <b className="tnum">{result.existing}</b> already known.</p>
          {result.invalid.length > 0 && (
            <div>
              <p className="mb-1 font-medium text-danger">{result.invalid.length} invalid</p>
              <ul className="max-h-40 overflow-auto rounded bg-sunken p-2 font-mono text-xs">
                {result.invalid.map((i, k) => <li key={k}>{i.value}: <span className="text-danger">{i.error}</span></li>)}
              </ul>
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          <Field label="Domains or URLs" hint="One per line, or separated by commas. Up to 1,000.">
            <Textarea rows={8} value={text} onChange={(e) => setText(e.target.value)} placeholder={"example.com\nhttps://news.example.org/article"} className="font-mono text-xs" />
          </Field>
          <Field label="Note (optional)"><Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Where these came from" /></Field>
        </div>
      )}
    </Modal>
  );
}

function SaveViewModal({ open, onClose, filter, columns, onSaved }: { open: boolean; onClose: () => void; filter: WebsiteFilter; columns: string[]; onSaved: () => void }) {
  const toast = useToast();
  const [name, setName] = useState("");
  const [withCols, setWithCols] = useState(true);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      await api("/api/views", { body: { name, filters: filter, columns: withCols ? columns : null } });
      toast(`Saved view "${name}"`);
      onSaved(); setName(""); onClose();
    } catch (e) { toast((e as Error).message, "error"); }
    finally { setBusy(false); }
  };
  return (
    <Modal open={open} onClose={onClose} title="Save view" footer={<>
      <Button size="sm" variant="ghost" onClick={onClose}>Cancel</Button>
      <Button size="sm" variant="primary" busy={busy} disabled={!name.trim()} onClick={save}>Save view</Button></>}>
      <div className="space-y-3">
        <Field label="Name"><Input autoFocus value={name} maxLength={120} onChange={(e) => setName(e.target.value)} /></Field>
        <Checkbox checked={withCols} onChange={setWithCols} label="Also save the visible columns" />
        <p className="text-xs text-muted">{describeFilter(filter).join("; ") || "No filter conditions."}</p>
      </div>
    </Modal>
  );
}

function BulkModal({ open, onClose, ids, onDone }: { open: boolean; onClose: () => void; ids: number[]; onDone: () => void }) {
  const toast = useToast();
  const [action, setAction] = useState<"rescan" | "exclude" | "include" | "outreach_stage">("rescan");
  const [stage, setStage] = useState("classify");
  const [outreach, setOutreach] = useState("Qualified");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      const body = { ids, action, value: action === "rescan" ? stage : action === "outreach_stage" ? outreach : null, reason: action === "exclude" ? reason : null };
      const r = await api<{ count: number }>("/api/websites/bulk", { body });
      toast(`${humanize(action)} applied to ${r.count} websites`);
      onDone(); onClose();
    } catch (e) { toast((e as Error).message, "error"); }
    finally { setBusy(false); }
  };
  return (
    <Modal open={open} onClose={onClose} title={`Bulk action on ${ids.length} websites`} footer={<>
      <Button size="sm" variant="ghost" onClick={onClose}>Cancel</Button>
      <Button size="sm" variant={action === "exclude" ? "danger" : "primary"} busy={busy} disabled={action === "exclude" && reason.trim().length < 3} onClick={run}>Apply</Button></>}>
      <div className="space-y-3">
        <Field label="Action">
          <Select value={action} onChange={(e) => setAction(e.target.value as typeof action)}>
            <option value="rescan">Rescan a stage</option>
            <option value="exclude">Exclude</option>
            <option value="include">Include (undo exclusion)</option>
            <option value="outreach_stage">Set outreach stage</option>
          </Select>
        </Field>
        {action === "rescan" && (
          <Field label="Stage" hint="Queued at elevated priority. Later stages follow automatically.">
            <Select value={stage} onChange={(e) => setStage(e.target.value)}>{PIPELINE_STAGES.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}</Select>
          </Field>
        )}
        {action === "exclude" && (
          <Field label="Reason" hint="Required. Recorded in the audit log."><Input value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        )}
        {action === "outreach_stage" && (
          <Field label="Outreach stage">
            <Select value={outreach} onChange={(e) => setOutreach(e.target.value)}>{OUTREACH_STAGES.map((s) => <option key={s}>{s}</option>)}</Select>
          </Field>
        )}
      </div>
    </Modal>
  );
}

function ExportModal({ open, onClose, filter, selectedIds, total, columns }: {
  open: boolean; onClose: () => void; filter: WebsiteFilter; selectedIds: number[]; total: number; columns: string[];
}) {
  const toast = useToast();
  const [format, setFormat] = useState<"csv" | "xlsx">("csv");
  const [scope, setScope] = useState<"filter" | "selected">("filter");
  const [allCols, setAllCols] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setScope(selectedIds.length ? "selected" : "filter"); }, [selectedIds.length, open]);
  const run = async () => {
    setBusy(true);
    try {
      const f: WebsiteFilter = scope === "selected" ? { ids: selectedIds, excluded: null, sort: filter.sort } : filter;
      const name = await downloadPost("/api/export", { filter: f, format, columns: allCols ? null : ["id", ...columns], limit: 200000 }, `purify_publishers.${format}`);
      toast(`Exported ${name}`);
      onClose();
    } catch (e) { toast((e as Error).message, "error"); }
    finally { setBusy(false); }
  };
  return (
    <Modal open={open} onClose={onClose} title="Export" footer={<>
      <Button size="sm" variant="ghost" onClick={onClose}>Cancel</Button>
      <Button size="sm" variant="primary" busy={busy} onClick={run}>Download {format.toUpperCase()}</Button></>}>
      <div className="space-y-3 text-sm">
        <Field label="Rows">
          <Select value={scope} onChange={(e) => setScope(e.target.value as typeof scope)}>
            <option value="filter">Current filter ({fmtInt(Math.min(total, 200000))} rows)</option>
            <option value="selected" disabled={!selectedIds.length}>Selected rows ({selectedIds.length})</option>
          </Select>
        </Field>
        <Field label="Format">
          <Select value={format} onChange={(e) => setFormat(e.target.value as typeof format)}>
            <option value="csv">CSV</option><option value="xlsx">Excel (XLSX)</option>
          </Select>
        </Field>
        <Checkbox checked={allCols} onChange={setAllCols} label="All columns (otherwise the visible ones)" />
        <p className="text-xs text-muted">The file includes a note that popularity is CrUX/Tranco (not visits) and that active signals do not prove auctions, fill or contracts. Export is capped at 200,000 rows. Confidence values are fractions (e.g. {fmtPct(0.7)} exports as 0.7).</p>
      </div>
    </Modal>
  );
}

export default function ExplorerPage() {
  return <Suspense fallback={null}><ExplorerInner /></Suspense>;
}
