"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { login } from "@/lib/api";
import { Button, Field, Input } from "@/components/ui";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email.trim(), password);
      const next = params.get("next");
      router.replace(next && next.startsWith("/") && !next.startsWith("/login") ? next : "/");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <Field label="Email">
        <Input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
      </Field>
      <Field label="Password">
        <Input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
      </Field>
      {error && <p className="rounded border border-danger/30 bg-danger-soft px-2 py-1.5 text-sm text-danger" role="alert">{error}</p>}
      <Button type="submit" variant="primary" className="w-full" busy={busy}>Sign in</Button>
    </form>
  );
}

export default function LoginPage() {
  return (
    <div className="grid min-h-screen place-items-center bg-paper p-4">
      <div className="w-full max-w-[340px]">
        <div className="mb-5 flex items-center gap-2">
          <span aria-hidden className="grid h-7 w-7 place-items-center rounded bg-accent text-sm font-bold text-white dark:text-paper">P</span>
          <div>
            <h1 className="text-base font-semibold leading-tight">Purify Publisher Intelligence</h1>
            <p className="text-xs text-muted">Internal tool for Purify Digital ad-ops and sales</p>
          </div>
        </div>
        <div className="rounded border border-rule bg-panel p-4">
          <Suspense fallback={null}><LoginForm /></Suspense>
        </div>
        <p className="mt-3 text-xs text-faint">Accounts are created by an admin under Settings → Users.</p>
      </div>
    </div>
  );
}
