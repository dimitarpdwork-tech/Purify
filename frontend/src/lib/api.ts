"use client";

const TOKEN_KEY = "purify.token";
const USER_KEY = "purify.user";

export type Role = "viewer" | "analyst" | "admin";
export interface SessionUser { id: number; email: string; role: Role }

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

export function getToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}
export function getStoredUser(): SessionUser | null {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as SessionUser) : null;
  } catch { return null; }
}
export function setSession(token: string, user: SessionUser) {
  try {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  } catch { /* storage unavailable */ }
}
export function clearSession() {
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  } catch { /* ignore */ }
}

function redirectToLogin() {
  clearSession();
  if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.href = `/login?next=${next}`;
  }
}

/** FastAPI errors come back as {detail: string} or {detail: [{loc, msg}]} (validation). */
function describe(status: number, body: unknown): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      return d.map((e) => {
        const it = e as { loc?: unknown[]; msg?: string };
        const loc = Array.isArray(it.loc) ? it.loc.filter((x) => x !== "body").join(".") : "";
        return loc ? `${loc}: ${it.msg}` : it.msg ?? "invalid";
      }).join("; ");
    }
  }
  if (status === 403) return "Your role does not allow this action.";
  if (status >= 500) return `Server error (${status}). Check the API logs.`;
  return `Request failed (${status}).`;
}

async function raw(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers, cache: "no-store" });
  } catch {
    throw new ApiError(0, "Cannot reach the API. Is the backend running?");
  }
  if (res.status === 401) {
    redirectToLogin();
    throw new ApiError(401, "Session expired. Sign in again.");
  }
  if (!res.ok) {
    let body: unknown = null;
    try { body = await res.json(); } catch { /* non-json */ }
    throw new ApiError(res.status, describe(res.status, body), body);
  }
  return res;
}

export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const opts: RequestInit = { method: init.method ?? (init.body !== undefined ? "POST" : "GET") };
  if (init.body !== undefined) {
    opts.body = JSON.stringify(init.body);
    opts.headers = { "Content-Type": "application/json" };
  }
  const res = await raw(path, opts);
  const text = await res.text();
  return (text ? JSON.parse(text) : null) as T;
}

export async function apiForm<T>(path: string, form: FormData | URLSearchParams): Promise<T> {
  const res = await raw(path, { method: "POST", body: form });
  return (await res.json()) as T;
}

/** POST returning a file (export). Triggers a browser download using the server filename. */
export async function downloadPost(path: string, body: unknown, fallbackName: string): Promise<string> {
  const res = await raw(path, { method: "POST", body: JSON.stringify(body), headers: { "Content-Type": "application/json" } });
  const cd = res.headers.get("Content-Disposition") || "";
  const m = /filename="?([^";]+)"?/i.exec(cd);
  const name = m ? m[1] : fallbackName;
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
  return name;
}

export async function login(username: string, password: string): Promise<SessionUser> {
  const form = new URLSearchParams();
  form.set("username", username);
  form.set("password", password);
  let res: Response;
  try {
    res = await fetch("/api/auth/login", { method: "POST", body: form });
  } catch {
    throw new ApiError(0, "Cannot reach the API. Is the backend running?");
  }
  if (!res.ok) {
    let body: unknown = null;
    try { body = await res.json(); } catch { /* ignore */ }
    throw new ApiError(res.status, res.status === 401 ? "Incorrect email or password." : describe(res.status, body));
  }
  const data = (await res.json()) as { access_token: string; user: SessionUser };
  setSession(data.access_token, data.user);
  return data.user;
}
