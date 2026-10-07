import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { useAuth } from "../auth";
import { useNotify } from "../notify";
import { Empty, Pill } from "../components/ui";

export default function Projects() {
  const { me } = useAuth(); const notify = useNotify(); const qc = useQueryClient();
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const cfg = useQuery({ queryKey: ["config"], queryFn: api.config });
  const demo = async (s: "clean" | "issues") => {
    try { await api.demo(s); await qc.invalidateQueries({ queryKey: ["projects"] }); notify("ok", "Demo project created"); }
    catch (e) { notify("error", e instanceof ApiError ? e.message : "Failed"); }
  };
  return (
    <div className="stack">
      <div className="row spread"><h2>Migration portfolio</h2>
        {cfg.data?.demo_enabled && <div className="row">
          <button className="btn ghost" disabled={!me?.can.create_project} onClick={() => demo("clean")}>New demo (clean)</button>
          <button className="btn ghost" disabled={!me?.can.create_project} onClick={() => demo("issues")}>New demo (with issues)</button></div>}
      </div>
      {projects.isLoading ? <Empty>Loading…</Empty> : !projects.data?.length ? <Empty>No projects yet.{cfg.data?.demo_enabled ? " Create a demo project against the simulated EPM environment." : ""}</Empty> : (
        <div className="cards">{projects.data.map((p) => (
          <Link key={p.id} className="card" to={`/projects/${p.id}`}>
            <div className="row spread"><b>{p.name}</b>{p.readiness && <Pill value={p.readiness.status} />}</div>
            <div className="muted">{p.client || "—"} · {p.pattern.replace(/_/g, " ")}</div>
            <div className="row spread" style={{ marginTop: 10 }}><span className="muted">#{p.id} · {p.status.toLowerCase()}</span>{p.readiness && <span>{p.readiness.score}</span>}</div>
          </Link>))}</div>)}
    </div>
  );
}
