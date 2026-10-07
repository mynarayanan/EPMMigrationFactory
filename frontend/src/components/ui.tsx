import type { ReactNode } from "react";
import type { Phase } from "../types";

export const Pill = ({ value }: { value: string }) => <span className={`pill ${value}`}>{value.replace(/_/g, " ")}</span>;

export function GateRail({ phases }: { phases: Phase[] }) {
  return (
    <ol className="rail" aria-label="Migration lifecycle">
      {phases.map((p, i) => (
        <li key={p.key} className={p.state}>
          <span className="node" aria-hidden>{p.state === "DONE" ? "✓" : p.state === "FAILED" ? "!" : i + 1}</span>
          {p.label}<span className="sr"> — {p.state.toLowerCase()}</span>
        </li>
      ))}
    </ol>
  );
}

export const ScoreBar = ({ score }: { score: number }) => (
  <div className="bar" role="meter" aria-valuenow={score} aria-valuemin={0} aria-valuemax={100}>
    <i className={score >= 90 ? "" : score >= 75 ? "mid" : "low"} style={{ width: `${score}%` }} />
  </div>
);

export const fmt = (n: number) => n.toLocaleString("en-US", { maximumFractionDigits: 2 });
export const Empty = ({ children }: { children: ReactNode }) => <p className="muted">{children}</p>;
