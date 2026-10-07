import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { CompatibilityTab, EnvironmentsTab, EvidenceTab, ExecutionTab, ReadinessTab, ValidationTab } from "../components/tabs";
import { Empty, GateRail, Pill } from "../components/ui";

const TABS = [["readiness", "Readiness", ReadinessTab], ["env", "Environments", EnvironmentsTab], ["compat", "Compatibility", CompatibilityTab],
  ["exec", "Plan & execution", ExecutionTab], ["val", "Validation", ValidationTab], ["evidence", "Evidence & audit", EvidenceTab]] as const;

export default function ProjectPage() {
  const pid = Number(useParams().id);
  const [tab, setTab] = useState<(typeof TABS)[number][0]>("readiness");
  const { data, error } = useQuery({ queryKey: ["p", pid, "detail"], queryFn: () => api.project(pid) });
  if (error) return <div className="alert">{(error as Error).message}</div>;
  if (!data) return <Empty>Loading…</Empty>;
  const { project: p } = data;
  const Active = TABS.find((t) => t[0] === tab)![2];
  return (
    <div>
      <p><Link to="/">← Portfolio</Link></p>
      <div className="row spread">
        <div><h2>{p.name}</h2><div className="muted">#{p.id} · {p.client || "no client"} · {p.pattern.replace(/_/g, " ")} · {p.status.toLowerCase()}{p.paused ? " · PAUSED" : ""}</div></div>
        <div className="row"><span className="muted">Execution gate</span>{data.gate.status ? <Pill value={data.gate.allowed ? "OPEN" : "BLOCKED"} /> : <Pill value="PENDING" />}</div>
      </div>
      <GateRail phases={data.lifecycle} />
      <div className="tabs" role="tablist">
        {TABS.map(([k, label]) => <button key={k} role="tab" aria-selected={tab === k} className="tab" onClick={() => setTab(k)}>{label}</button>)}
      </div>
      <Active pid={pid} detail={data} />
    </div>
  );
}
