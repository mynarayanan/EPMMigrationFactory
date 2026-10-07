import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

type Kind = "ok" | "error";
interface Toast { id: number; kind: Kind; text: string; }
const Ctx = createContext<(kind: Kind, text: string) => void>(() => {});
let seq = 0;

export function NotifyProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((kind: Kind, text: string) => {
    const id = ++seq;
    setToasts((t) => [...t, { id, kind, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "error" ? 9000 : 3500);
  }, []);
  return (
    <Ctx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (<div key={t.id} className={`alert ${t.kind === "ok" ? "ok" : ""}`}>{t.text}</div>))}
      </div>
    </Ctx.Provider>
  );
}
export const useNotify = () => useContext(Ctx);
