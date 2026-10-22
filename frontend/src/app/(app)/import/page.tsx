"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { apiForm, api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { Job, UploadPreview } from "@/lib/types";
import { fmtInt, humanize } from "@/lib/domain";
import { JobsTable } from "@/components/jobs";
import { JobStatus } from "@/components/domain";
import { useToast } from "@/components/toast";
import { useAuth } from "@/components/auth";
import { Button, Checkbox, Empty, ErrorState, Field, Input, Loading, PageHeader, Panel, Select, Spinner } from "@/components/ui";

const TARGETS: { key: string; label: string; help: string; required?: boolean }[] = [
  { key: "domain", label: "Domain", help: "Domain or URL. Rows that can't be normalised are reported as invalid.", required: true },
  { key: "legacy_label", label: "Legacy label", help: "Old classification. EXCLUDED rows can be honoured as exclusions." },
  { key: "category", label: "Category", help: "Kept as provenance; does not override automatic classification." },
  { key: "notes", label: "Notes", help: "Free text stored with the source record." },
  { key: "geo", label: "GEO", help: "Country hint." },
  { key: "source", label: "Source", help: "Where the row originally came from." },
  { key: "outreach_status", label: "Outreach status", help: "Previous outreach state, stored as the imported status." },
];

function fmtBytes(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function ImportProgress({ jobId }: { jobId: number }) {
  const jobs = useApi<Job[]>("/api/jobs?limit=100", { poll: 3000 });
  const job = jobs.data?.find((j) => j.id === jobId);
  if (!job) return jobs.error ? <ErrorState error={jobs.error} onRetry={jobs.reload} /> : <Loading label={`Waiting for job #${jobId}…`} />;
  const p = (job.progress ?? {}) as Record<string, unknown>;
  const invalid = (p.invalid_sample as { row: number; value: string; error: string }[] | undefined) ?? [];
  const stats: [string, unknown][] = [
    ["Rows processed", p.finished_rows ?? (p.checkpoint as { row?: number } | undefined)?.row], ["Registered", p.registered], ["New websites", p.new_websites],
    ["Already known", p.existing_websites], ["Duplicates in file", p.duplicates], ["Invalid rows", p.invalid],
  ];
  const others = Object.entries(p).filter(([k, v]) => !["registered", "new_websites", "existing_websites", "duplicates", "invalid", "invalid_sample", "finished_rows", "checkpoint"].includes(k) && typeof v !== "object");
  return (
    <Panel title={<span className="flex items-center gap-2">Import job #{job.id} <JobStatus status={job.status} /></span>}
      actions={job.status === "DONE" ? <Link href={`/explorer?f=${encodeURIComponent(JSON.stringify({ sources: ["legacy"] }))}`} className="text-xs text-accent hover:underline">Open imported sites in explorer</Link> : <Spinner className="text-faint" />}>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {[...stats, ...others].map(([k, v]) => (
          <div key={k} className="rounded bg-sunken px-2 py-1.5">
            <div className="text-2xs text-muted">{humanize(k)}</div>
            <div className="tnum text-base font-semibold">{typeof v === "number" ? fmtInt(v) : v === undefined || v === null ? "—" : String(v)}</div>
          </div>
        ))}
      </div>
      {job.error && <p className="mt-2 rounded bg-danger-soft px-2 py-1.5 font-mono text-xs text-danger">{job.error}</p>}
      <h3 className="mb-1 mt-3 text-xs font-medium text-muted">Invalid row samples {invalid.length > 0 && `(first ${invalid.length})`}</h3>
      {invalid.length === 0 ? <p className="text-sm text-faint">None so far.</p> : (
        <div className="max-h-64 overflow-auto rounded border border-rule">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-panel"><tr className="border-b border-rule text-left text-muted"><th className="px-2 py-1 font-medium">Row</th><th className="px-2 py-1 font-medium">Value</th><th className="px-2 py-1 font-medium">Error</th></tr></thead>
            <tbody>{invalid.map((r, i) => (
              <tr key={i} className="border-b border-rule/60"><td className="tnum px-2 py-0.5">{r.row}</td><td className="break-all px-2 py-0.5 font-mono">{r.value}</td><td className="px-2 py-0.5 text-danger">{r.error}</td></tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

export default function ImportPage() {
  const toast = useToast();
  const { can } = useAuth();
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadErr, setUploadErr] = useState<string | null>(null);
  const [preview, setPreview] = useState<UploadPreview | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [label, setLabel] = useState("");
  const [honor, setHonor] = useState(true);
  const [starting, setStarting] = useState(false);
  const [jobId, setJobId] = useState<number | null>(null);
  const [drag, setDrag] = useState(false);
  const jobs = useApi<Job[]>("/api/jobs?limit=100", { poll: 10000 });
  const importJobs = (jobs.data ?? []).filter((j) => j.kind === "import_file");

  const upload = async (f: File) => {
    setFile(f); setUploading(true); setUploadErr(null); setPreview(null); setJobId(null);
    const fd = new FormData();
    fd.append("file", f);
    try {
      const r = await apiForm<UploadPreview>("/api/imports/upload", fd);
      setPreview(r);
      setMapping(r.suggested_mapping ?? {});
      setLabel(r.filename.replace(/\.[^.]+$/, ""));
    } catch (e) { setUploadErr((e as Error).message); }
    finally { setUploading(false); }
  };

  const start = async () => {
    if (!preview) return;
    setStarting(true);
    try {
      const clean = Object.fromEntries(Object.entries(mapping).filter(([, v]) => v));
      const r = await api<{ job_id: number }>("/api/imports/start", { body: { token: preview.token, mapping: clean, label: label || null, honor_legacy_exclusions: honor } });
      setJobId(r.job_id);
      toast(`Import started as job #${r.job_id}`);
      void jobs.reload();
    } catch (e) { toast((e as Error).message, "error"); }
    finally { setStarting(false); }
  };

  const used = new Set(Object.values(mapping).filter(Boolean));

  return (
    <div className="space-y-3">
      <PageHeader title="Import" sub="Upload a legacy CSV or XLSX list of domains. Imported sites go through the same pipeline as discovered ones." />

      {!can("analyst") && <p className="rounded border border-rule bg-panel px-3 py-2 text-sm text-muted">Imports require the analyst role.</p>}

      <Panel title="1. Upload file">
        <div onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files[0]; if (f && can("analyst")) void upload(f); }}
          className={`flex flex-wrap items-center gap-3 rounded border border-dashed px-4 py-5 ${drag ? "border-accent bg-accent-soft/50" : "border-rule"}`}>
          <input ref={fileRef} type="file" accept=".csv,.tsv,.txt,.xlsx,.xlsm" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); e.target.value = ""; }} />
          <Button onClick={() => fileRef.current?.click()} disabled={!can("analyst")} busy={uploading}>Choose file</Button>
          <span className="text-sm text-muted">
            {file ? <>{file.name} <span className="text-faint">({fmtBytes(file.size)})</span></> : "or drop a CSV, TSV, TXT or XLSX file here. Up to 1 GB."}
          </span>
        </div>
        {uploadErr && <ErrorState error={new Error(uploadErr)} className="mt-2" />}
      </Panel>

      {preview && (
        <>
          <Panel title="2. Map columns" note={`${preview.columns.length} columns detected. Suggested mapping applied.`}>
            {preview.columns.length === 0 ? <Empty title="No columns found">The file looks empty or has no header row.</Empty> : (
              <div className="space-y-3">
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  {TARGETS.map((t) => (
                    <Field key={t.key} label={`${t.label}${t.required ? " (required)" : ""}`} hint={t.help}>
                      <Select value={mapping[t.key] ?? ""} onChange={(e) => setMapping({ ...mapping, [t.key]: e.target.value })}
                        className={t.required && !mapping[t.key] ? "border-danger" : ""}>
                        <option value="">{t.required ? "Choose a column…" : "Not mapped"}</option>
                        {preview.columns.map((c) => <option key={c} value={c}>{c}{used.has(c) && mapping[t.key] !== c ? " (in use)" : ""}</option>)}
                      </Select>
                    </Field>
                  ))}
                </div>
                <div className="grid gap-3 border-t border-rule pt-3 sm:grid-cols-2 lg:grid-cols-4">
                  <Field label="Import label" hint="Shown as the source reference"><Input value={label} onChange={(e) => setLabel(e.target.value)} /></Field>
                  <div className="flex items-end pb-1 lg:col-span-2">
                    <Checkbox checked={honor} onChange={setHonor} label="Honour legacy exclusions (rows labelled EXCLUDED become excluded websites)" />
                  </div>
                  <div className="flex items-end justify-end">
                    <Button variant="primary" busy={starting} disabled={!mapping.domain || !can("analyst") || jobId !== null} onClick={start}>Start import</Button>
                  </div>
                </div>
              </div>
            )}
          </Panel>

          <Panel title={`Preview (${preview.rows.length} rows)`} bodyClass="">
            <div className="max-h-80 overflow-auto">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-panel"><tr className="border-b border-rule text-left">
                  {preview.columns.map((c) => {
                    const target = Object.entries(mapping).find(([, v]) => v === c)?.[0];
                    return <th key={c} className="whitespace-nowrap px-2 py-1.5 font-medium">{c}{target && <span className="ml-1 rounded-sm bg-accent-soft px-1 text-2xs font-normal text-accent">{TARGETS.find((t) => t.key === target)?.label}</span>}</th>;
                  })}
                </tr></thead>
                <tbody>
                  {preview.rows.map((r, i) => (
                    <tr key={i} className="border-b border-rule/60">
                      {preview.columns.map((c) => <td key={c} className="max-w-[240px] truncate px-2 py-0.5">{r[c] === null || r[c] === undefined ? "" : String(r[c])}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </>
      )}

      {jobId !== null && <ImportProgress jobId={jobId} />}

      <Panel title="Previous imports" bodyClass="">
        {jobs.loading && !jobs.data ? <Loading /> : jobs.error && !jobs.data ? <ErrorState error={jobs.error} onRetry={jobs.reload} className="m-3" /> :
          importJobs.length === 0 ? <Empty title="No imports yet" /> : <JobsTable jobs={importJobs} onChanged={jobs.reload} />}
      </Panel>
    </div>
  );
}
