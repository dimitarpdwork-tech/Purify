"use client";

import { createContext, useCallback, useContext, useState } from "react";

type Tone = "ok" | "error" | "info";
interface ToastItem { id: number; text: string; tone: Tone }
const Ctx = createContext<(text: string, tone?: Tone) => void>(() => {});

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const push = useCallback((text: string, tone: Tone = "ok") => {
    const id = Date.now() + Math.random();
    setItems((xs) => [...xs, { id, text, tone }]);
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), tone === "error" ? 7000 : 3500);
  }, []);
  return (
    <Ctx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[340px] flex-col gap-2" role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id}
            className={`toast-in pointer-events-auto rounded border px-3 py-2 text-sm shadow-sm ${
              t.tone === "error" ? "border-danger/40 bg-danger-soft text-danger"
              : t.tone === "info" ? "border-rule bg-panel text-ink"
              : "border-active/40 bg-active-soft text-active"}`}>
            {t.text}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}
export const useToast = () => useContext(Ctx);
