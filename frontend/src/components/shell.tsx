"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth } from "./auth";
import { cx } from "./ui";

const NAV = [
  { href: "/", label: "Dashboard", icon: "M3 3h6v8H3zM11 3h6v4h-6zM11 9h6v8h-6zM3 13h6v4H3z" },
  { href: "/explorer", label: "Publisher explorer", icon: "M3 4h14M3 8h14M3 12h14M3 16h9" },
  { href: "/discovery", label: "Discovery", icon: "M9 3a6 6 0 1 0 0 12A6 6 0 0 0 9 3zm4.5 10.5L17 17" },
  { href: "/pipeline", label: "Opportunity pipeline", icon: "M3 4h4v12H3zM8 4h4v8H8zM13 4h4v5h-4z" },
  { href: "/import", label: "Import", icon: "M10 3v9m0 0-3.5-3.5M10 12l3.5-3.5M4 14v3h12v-3" },
  { href: "/settings", label: "Settings", icon: "M10 7a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM10 2v2m0 12v2M2 10h2m12 0h2M4.3 4.3l1.4 1.4m8.6 8.6 1.4 1.4m0-11.4-1.4 1.4m-8.6 8.6-1.4 1.4" },
];

function Icon({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 20 20" className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d={d} />
    </svg>
  );
}

function ThemeToggle() {
  const [dark, setDark] = useState(false);
  useEffect(() => {
    let saved: string | null = null;
    try { saved = localStorage.getItem("purify.theme"); } catch { /* ignore */ }
    const isDark = saved === "dark";
    setDark(isDark);
    document.documentElement.dataset.theme = isDark ? "dark" : "light";
  }, []);
  const toggle = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.dataset.theme = next ? "dark" : "light";
    try { localStorage.setItem("purify.theme", next ? "dark" : "light"); } catch { /* ignore */ }
  };
  return (
    <button onClick={toggle} className="rounded px-1.5 py-0.5 text-xs text-muted hover:bg-sunken hover:text-ink" aria-label="Toggle dark mode">
      {dark ? "Light" : "Dark"}
    </button>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const { user, logout } = useAuth();
  const [navOpen, setNavOpen] = useState(false);
  useEffect(() => setNavOpen(false), [path]);
  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href) || (href === "/explorer" && path.startsWith("/websites")));

  return (
    <div className="flex min-h-screen">
      <nav className={cx(
        "fixed inset-y-0 left-0 z-40 flex w-[200px] flex-col border-r border-rule bg-panel transition-transform md:translate-x-0",
        navOpen ? "translate-x-0" : "-translate-x-full")}>
        <div className="flex h-11 items-center gap-2 border-b border-rule px-3">
          <span aria-hidden className="grid h-5 w-5 place-items-center rounded-sm bg-accent text-[11px] font-bold text-white dark:text-paper">P</span>
          <span className="text-sm font-semibold leading-tight">Purify<span className="block text-2xs font-normal text-muted">Publisher Intelligence</span></span>
        </div>
        <ul className="flex-1 space-y-px p-2">
          {NAV.map((n) => (
            <li key={n.href}>
              <Link href={n.href} aria-current={active(n.href) ? "page" : undefined}
                className={cx("flex items-center gap-2 rounded px-2 py-1.5 text-sm",
                  active(n.href) ? "bg-accent-soft font-medium text-accent" : "text-muted hover:bg-sunken hover:text-ink")}>
                <Icon d={n.icon} /> {n.label}
              </Link>
            </li>
          ))}
        </ul>
        <p className="border-t border-rule px-3 py-2 text-2xs leading-snug text-faint">
          Popularity is CrUX/Tranco only. Traffic estimates are not collected in this build.
        </p>
      </nav>
      {navOpen && <div className="fixed inset-0 z-30 bg-ink/20 md:hidden" onClick={() => setNavOpen(false)} />}

      <div className="flex min-w-0 flex-1 flex-col md:pl-[200px]">
        <header className="sticky top-0 z-20 flex h-11 items-center justify-between gap-2 border-b border-rule bg-panel/95 px-3 backdrop-blur md:px-4">
          <button className="rounded px-1.5 py-1 text-muted hover:bg-sunken md:hidden" onClick={() => setNavOpen(true)} aria-label="Open navigation">
            <Icon d="M3 5h14M3 10h14M3 15h14" />
          </button>
          <div className="hidden text-xs text-muted md:block">{NAV.find((n) => active(n.href))?.label}</div>
          <div className="flex items-center gap-2 text-sm">
            <ThemeToggle />
            {user && (
              <span className="flex items-center gap-1.5 text-muted">
                <span className="max-w-[200px] truncate text-ink">{user.email}</span>
                <span className="rounded-sm bg-sunken px-1 text-2xs">{user.role}</span>
              </span>
            )}
            <button onClick={logout} className="rounded px-1.5 py-0.5 text-xs text-muted hover:bg-sunken hover:text-ink">Sign out</button>
          </div>
        </header>
        <main className="min-w-0 flex-1 p-3 md:p-4">{children}</main>
      </div>
    </div>
  );
}
