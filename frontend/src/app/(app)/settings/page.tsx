"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { AuditT, ExclusionT, SettingsResp, UserT } from "@/lib/types";
import { fmtDate, humanize } from "@/lib/domain";
import { useToast } from "@/components/toast";
import { useAuth } from "@/components/auth";
import { Badge, Button, Checkbox, cx, Empty, ErrorState, Field, Input, KV, Loading, Modal, PageHeader, Panel, Select, Tabs, Textarea } from "@/components/ui";

type J = unknown;
const isObj = (v: J): v is Record<string, J> => !!v && typeof v === "object" && !Array.isArray(v);

const HELP: Record<string, string> = {
  scoring_weights: "Points per score component and the thresholds that decide queues. Changes apply on the next rescore (Discovery → Rescore all).",
  qualification: "Popularity gate for the cheap qualify stage. Sites outside it are skipped, not deleted, and re-queued if newer data puts them inside.",
  dispatcher: "Batch sizes per pipeline stage. Pause stops new work being claimed.",
  schedules: "Recurring discovery jobs (cron in UTC).",
};

/** Recursive structured editor. Primitives get inputs, string arrays a comma list, anything else inline JSON. */
function ValueEditor({ value, onChange, path, disabled }: { value: J; onChange: (v: J) => void; path: string; disabled: boolean }) {
  if (typeof value === "boolean") return <Checkbox checked={value} onChange={onChange} label={value ? "On" : "Off"} />;
  if (typeof value === "number") return <Input type="number" step="any" disabled={disabled} className="w-36" value={String(value)} onChange={(e) => onChange(e.target.value === "" ? 0 : Number(e.target.value))} />;
  if (typeof value === "string") return <Input disabled={disabled} className={path.endsWith("cron") ? "w-40 font-mono" : ""} value={value} onChange={(e) => onChange(e.target.value)} />;
  if (Array.isArray(value) && value.every((x) => typeof x === "string")) {
    return <Input disabled={disabled} defaultValue={value.join(", ")} key={value.join(",")} onBlur={(e) => onChange(e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} />;
  }
  if (isObj(value)) {
    return (
      <div className="space-y-1.5 border-l border-rule pl-3">
        {Object.entries(value).map(([k, v]) => (
          <div key={k} className={cx("grid gap-2", isObj(v) ? "grid-cols-1" : "grid-cols-[minmax(140px,220px)_1fr] items-center")}>
            <span className="text-sm text-muted">{humanize(k)}<span className="ml-1 font-mono text-2xs text-faint">{k}</span></span>
            <ValueEditor value={v} path={`${path}.${k}`} disabled={disabled} onChange={(nv) => onChange({ ...value, [k]: nv })} />
          </div>
        ))}
      </div>
    );
  }
  return <InlineJson value={value} onChange={onChange} disabled={disabled} />;
}

function InlineJson({ value, onChange, disabled }: { value: J; onChange: (v: J) => void; disabled: boolean }) {
  const [text, setText] = useState(JSON.stringify(value));
  const [bad, setBad] = useState(false);
  useEffect(() => setText(JSON.stringify(value)), [value]);
  return (
    <Input disabled={disabled} className={cx("font-mono text-xs", bad && "border-danger")} value={text}
      onChange={(e) => { setText(e.target.value); try { JSON.parse(e.target.value); setBad(false); } catch { setBad(true); } }}
      onBlur={() => { try { onChange(JSON.parse(text)); setBad(false); } catch { setBad(true); } }} />
  );
}

function SettingCard({ k, value, onSaved, isAdmin }: { k: string; value: J; onSaved: () => void; isAdmin: boolean }) {
  const toast = useToast();
  const [mode, setMode] = useState<"form" | "json">("form");
  const [draft, setDraft] = useState<J>(value);
  const [text, setText] = useState(JSON.stringify(value, null, 2));
  const [jsonErr, setJsonErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setDraft(value); setText(JSON.stringify(value, null, 2)); }, [value]);
  const dirty = JSON.stringify(mode === "form" ? draft : (() => { try { return JSON.parse(text); } catch { return null; } })()) !== JSON.stringify(value);

  const switchMode = (m: "form" | "json") => {
    if (m === "json") { setText(JSON.stringify(draft, null, 2)); setJsonErr(null); }
    else { try { setDraft(JSON.parse(text)); } catch (e) { setJsonErr((e as Error).message); return; } }
    setMode(m);
  };
  const save = async () => {
    let v: J = draft;
    if (mode === "json") { try { v = JSON.parse(text); } catch (e) { setJsonErr((e as Error).message); return; } }
    setBusy(true);
    try { await api(`/api/settings/${k}`, { method: "PUT", body: { value: v } }); toast(`Saved ${humanize(k)}`); onSaved(); }
    catch (e) { toast((e as Error).message, "error"); } finally { setBusy(false); }
  };
  return (
    <Panel title={humanize(k)} note={HELP[k]} actions={<>
      <Button size="sm" variant={mode === "form" ? "secondary" : "ghost"} onClick={() => switchMode("form")}>Form</Button>
      <Button size="sm" variant={mode === "json" ? "secondary" : "ghost"} onClick={() => switchMode("json")}>JSON</Button>
    </>}>
      {mode === "form" ? <ValueEditor value={draft} onChange={setDraft} path={k} disabled={!isAdmin} /> : (
        <>
          <Textarea rows={14} className="font-mono text-xs" value={text} disabled={!isAdmin}
            onChange={(e) => { setText(e.target.value); try { JSON.parse(e.target.value); setJsonErr(null); } catch (err) { setJsonErr((err as Error).message); } }} />
          {jsonErr && <p className="mt-1 text-xs text-danger">{jsonErr}</p>}
        </>
      )}
      {isAdmin && (
        <div className="mt-3 flex justify-end gap-1.5 border-t border-rule pt-2">
          <Button size="sm" variant="ghost" disabled={!dirty} onClick={() => { setDraft(value); setText(JSON.stringify(value, null, 2)); setJsonErr(null); }}>Discard</Button>
          <Button size="sm" variant="primary" busy={busy} disabled={!dirty || !!jsonErr} onClick={save}>Save {humanize(k).toLowerCase()}</Button>
        </div>
      )}
    </Panel>
  );
}

function SettingsTab({ isAdmin }: { isAdmin: boolean }) {
  const s = useApi<SettingsResp>("/api/settings");
  if (s.loading && !s.data) return <Loading />;
  if (s.error && !s.data) return <ErrorState error={s.error} onRetry={s.reload} />;
  const d = s.data!;
  return (
    <div className="grid gap-3 xl:grid-cols-[2fr_1fr]">
      <div className="space-y-3">
        {!isAdmin && <p className="rounded border border-rule bg-panel px-3 py-2 text-sm text-muted">Read only. Editing settings requires the admin role.</p>}
        {Object.entries(d.settings).map(([k, v]) => <SettingCard key={k} k={k} value={v} onSaved={s.reload} isAdmin={isAdmin} />)}
      </div>
      <Panel title="Environment" note="Read only. Set through backend environment variables.">
        <KV rows={Object.entries(d.environment).map(([k, v]) => [humanize(k),
          typeof v === "boolean" ? <Badge key={k} tone={v ? "active" : "outline"}>{v ? "yes" : "no"}</Badge>
            : Array.isArray(v) ? (v.length ? <ul key={k} className="font-mono text-2xs">{v.map((x) => <li key={String(x)} className="break-all">{String(x)}</li>)}</ul> : "none")
              : <span key={k} className="break-all">{String(v)}</span>])} />
      </Panel>
    </div>
  );
}

function ExclusionsTab({ isAdmin }: { isAdmin: boolean }) {
  const toast = useToast();
  const ex = useApi<ExclusionT[]>("/api/exclusions");
  const [kind, setKind] = useState("registrable");
  const [pattern, setPattern] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [q, setQ] = useState("");
  const add = async () => {
    setBusy(true);
    try { await api("/api/exclusions", { body: { kind, pattern, reason } }); toast(`Added exclusion ${pattern}`); setPattern(""); setReason(""); void ex.reload(); }
    catch (e) { toast((e as Error).message, "error"); } finally { setBusy(false); }
  };
  const del = async (e: ExclusionT) => {
    if (!confirm(`Delete exclusion "${e.pattern}"?`)) return;
    try { await api(`/api/exclusions/${e.id}`, { method: "DELETE" }); toast("Exclusion deleted"); void ex.reload(); }
    catch (err) { toast((err as Error).message, "error"); }
  };
  const rows = (ex.data ?? []).filter((e) => !q || e.pattern.includes(q.toLowerCase()) || e.reason.toLowerCase().includes(q.toLowerCase()));
  return (
    <div className="space-y-3">
      {isAdmin && (
        <Panel title="Add exclusion rule" note="Matching websites are excluded at the qualify stage and when rescored.">
          <div className="grid items-end gap-2 sm:grid-cols-[160px_1fr_1.5fr_auto]">
            <Field label="Match on">
              <Select value={kind} onChange={(e) => setKind(e.target.value)}>
                <option value="host">Exact host</option><option value="registrable">Registrable domain</option>
                <option value="suffix">Suffix</option><option value="keyword">Keyword in host</option>
              </Select>
            </Field>
            <Field label="Pattern"><Input value={pattern} onChange={(e) => setPattern(e.target.value)} placeholder="example.com" /></Field>
            <Field label="Reason"><Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Existing partner, competitor…" /></Field>
            <Button variant="primary" busy={busy} disabled={pattern.trim().length < 2 || reason.trim().length < 3} onClick={add}>Add rule</Button>
          </div>
        </Panel>
      )}
      <Panel title={`Exclusion rules (${ex.data?.length ?? 0})`} bodyClass="" actions={<Input className="h-6 w-48 text-xs" placeholder="Filter…" value={q} onChange={(e) => setQ(e.target.value)} />}>
        {ex.loading && !ex.data ? <Loading /> : ex.error ? <ErrorState error={ex.error} onRetry={ex.reload} className="m-3" /> : rows.length === 0 ? <Empty title="No exclusion rules" /> : (
          <table className="w-full text-sm">
            <thead><tr className="border-b border-rule text-left text-xs text-muted"><th className="px-3 py-1.5 font-medium">Kind</th><th className="px-2 py-1.5 font-medium">Pattern</th><th className="px-2 py-1.5 font-medium">Reason</th><th className="px-2 py-1.5 font-medium">Added</th><th /></tr></thead>
            <tbody>{rows.map((e) => (
              <tr key={e.id} className="border-b border-rule/60 last:border-0">
                <td className="px-3 py-1"><Badge tone="outline">{e.kind}</Badge></td>
                <td className="px-2 py-1 font-mono text-xs">{e.pattern}</td>
                <td className="px-2 py-1 text-muted">{e.reason}</td>
                <td className="px-2 py-1 text-xs text-faint">{fmtDate(e.created_at)}</td>
                <td className="px-3 py-1 text-right">{isAdmin && <Button size="sm" variant="ghost" onClick={() => del(e)}>Delete</Button>}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}

function UsersTab() {
  const toast = useToast();
  const { user: me } = useAuth();
  const users = useApi<UserT[]>("/api/users");
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState(""); const [password, setPassword] = useState(""); const [role, setRole] = useState("analyst");
  const [busy, setBusy] = useState(false);
  const [pwFor, setPwFor] = useState<UserT | null>(null);
  const [newPw, setNewPw] = useState("");
  const create = async () => {
    setBusy(true);
    try { await api("/api/users", { body: { email, password, role } }); toast(`Created ${email}`); setOpen(false); setEmail(""); setPassword(""); void users.reload(); }
    catch (e) { toast((e as Error).message, "error"); } finally { setBusy(false); }
  };
  const patch = async (u: UserT, body: Record<string, unknown>, msg: string) => {
    try { await api(`/api/users/${u.id}`, { method: "PATCH", body }); toast(msg); void users.reload(); }
    catch (e) { toast((e as Error).message, "error"); }
  };
  return (
    <Panel title="Users" bodyClass="" actions={<Button size="sm" variant="primary" onClick={() => setOpen(true)}>Add user</Button>}>
      {users.loading && !users.data ? <Loading /> : users.error ? <ErrorState error={users.error} onRetry={users.reload} className="m-3" /> : (
        <table className="w-full text-sm">
          <thead><tr className="border-b border-rule text-left text-xs text-muted"><th className="px-3 py-1.5 font-medium">Email</th><th className="px-2 py-1.5 font-medium">Role</th><th className="px-2 py-1.5 font-medium">Status</th><th /></tr></thead>
          <tbody>{(users.data ?? []).map((u) => (
            <tr key={u.id} className="border-b border-rule/60 last:border-0">
              <td className="px-3 py-1">{u.email}{u.id === me?.id && <span className="ml-1.5 text-xs text-faint">(you)</span>}</td>
              <td className="px-2 py-1">
                <Select className="h-6 w-28 text-xs" value={u.role} disabled={u.id === me?.id} onChange={(e) => patch(u, { role: e.target.value }, `${u.email} is now ${e.target.value}`)}>
                  <option value="viewer">viewer</option><option value="analyst">analyst</option><option value="admin">admin</option>
                </Select>
              </td>
              <td className="px-2 py-1">{u.is_active ? <Badge tone="active">Active</Badge> : <Badge tone="outline">Disabled</Badge>}</td>
              <td className="whitespace-nowrap px-3 py-1 text-right">
                <Button size="sm" variant="ghost" onClick={() => { setPwFor(u); setNewPw(""); }}>Reset password</Button>
                {u.id !== me?.id && <Button size="sm" variant="ghost" onClick={() => patch(u, { is_active: !u.is_active }, u.is_active ? `Disabled ${u.email}` : `Enabled ${u.email}`)}>{u.is_active ? "Disable" : "Enable"}</Button>}
              </td>
            </tr>
          ))}</tbody>
        </table>
      )}
      <Modal open={open} onClose={() => setOpen(false)} title="Add user" footer={<>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
        <Button size="sm" variant="primary" busy={busy} disabled={!email || password.length < 10} onClick={create}>Add user</Button></>}>
        <div className="space-y-3">
          <Field label="Email"><Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
          <Field label="Password" hint="At least 10 characters"><Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
          <Field label="Role" hint="Viewers read; analysts also run jobs, imports and edits; admins manage settings and users.">
            <Select value={role} onChange={(e) => setRole(e.target.value)}><option value="viewer">viewer</option><option value="analyst">analyst</option><option value="admin">admin</option></Select>
          </Field>
        </div>
      </Modal>
      <Modal open={!!pwFor} onClose={() => setPwFor(null)} title={`Reset password for ${pwFor?.email ?? ""}`} footer={<>
        <Button size="sm" variant="ghost" onClick={() => setPwFor(null)}>Cancel</Button>
        <Button size="sm" variant="primary" disabled={newPw.length < 10} onClick={async () => { await patch(pwFor!, { password: newPw }, "Password reset"); setPwFor(null); }}>Reset password</Button></>}>
        <Field label="New password" hint="At least 10 characters"><Input type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} /></Field>
      </Modal>
    </Panel>
  );
}

function AuditTab() {
  const a = useApi<AuditT[]>("/api/audit?limit=500");
  const [q, setQ] = useState("");
  const rows = (a.data ?? []).filter((r) => !q || `${r.action} ${r.entity} ${r.entity_id ?? ""} ${JSON.stringify(r.data ?? "")}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <Panel title="Audit log" note="Last 500 entries" bodyClass="" actions={<Input className="h-6 w-56 text-xs" placeholder="Filter…" value={q} onChange={(e) => setQ(e.target.value)} />}>
      {a.loading && !a.data ? <Loading /> : a.error ? <ErrorState error={a.error} onRetry={a.reload} className="m-3" /> : rows.length === 0 ? <Empty title="No audit entries" /> : (
        <div className="max-h-[70vh] overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-panel"><tr className="border-b border-rule text-left text-xs text-muted"><th className="px-3 py-1.5 font-medium">When</th><th className="px-2 py-1.5 font-medium">User</th><th className="px-2 py-1.5 font-medium">Action</th><th className="px-2 py-1.5 font-medium">Entity</th><th className="px-3 py-1.5 font-medium">Data</th></tr></thead>
            <tbody>{rows.map((r, i) => (
              <tr key={i} className="border-b border-rule/60 align-top last:border-0">
                <td className="whitespace-nowrap px-3 py-1 text-xs text-muted">{fmtDate(r.at, true)}</td>
                <td className="px-2 py-1 text-xs">{r.user_id ? `#${r.user_id}` : "system"}</td>
                <td className="px-2 py-1">{humanize(r.action)}</td>
                <td className="px-2 py-1 text-xs">{r.entity}{r.entity_id && <span className="text-muted"> {r.entity_id}</span>}</td>
                <td className="max-w-[480px] break-all px-3 py-1 font-mono text-2xs text-muted">{r.data ? JSON.stringify(r.data) : ""}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

export default function SettingsPage() {
  const { can } = useAuth();
  const isAdmin = can("admin");
  const [tab, setTab] = useState("settings");
  const tabs = [{ id: "settings", label: "Settings" }, { id: "exclusions", label: "Exclusions" }, ...(isAdmin ? [{ id: "users", label: "Users" }, { id: "audit", label: "Audit log" }] : [])];
  return (
    <div className="space-y-3">
      <PageHeader title="Settings" />
      <Tabs value={tab} onChange={setTab} tabs={tabs} />
      {tab === "settings" && <SettingsTab isAdmin={isAdmin} />}
      {tab === "exclusions" && <ExclusionsTab isAdmin={isAdmin} />}
      {tab === "users" && isAdmin && <UsersTab />}
      {tab === "audit" && isAdmin && <AuditTab />}
    </div>
  );
}
