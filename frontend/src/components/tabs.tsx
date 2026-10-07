import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { useAuth } from "../auth";
import type { ProjectDetail, Settings, Step } from "../types";
import { Empty, Pill, ScoreBar, fmt } from "./ui";
import { useAct } from "./useAct";

type TabProps = { pid: number; detail: ProjectDetail };

/* ───────────── Readiness ───────────── */
export function ReadinessTab({ pid, detail }: TabProps) {
  const { me } = useAuth();
  const act = useAct(pid);
  const { data: r } = useQuery({ queryKey: ["p", pid, "readiness"], queryFn: () => api.readiness(pid) });
  const s = detail.project.settings;
  const [form, setForm] = useState<Settings>(s);
  useEffect(() => setForm(s), [JSON.stringify(s)]); // eslint-disable-line react-hooks/exhaustive-deps
  const canConfigure = !!me?.can.configure;

  const discover = () => act(async () => { await api.runConnectivity(pid); await api.collectInventory(pid); await api.assess(pid); }, "Discovery and assessment complete");
  const save = () => act(async () => { await api.patchSettings(pid, form); await api.assess(pid); }, "Saved and re-assessed");
  const chk = (k: keyof Settings, label: string) => (
    <label className="chk"><input type="checkbox" disabled={!canConfigure} checked={!!form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.checked })} />{label}</label>
  );

  return (
    <div className="stack">
      <div className="row spread">
        <div className="row" style={{ gap: 28 }}>
          {r ? <div><div className="score">{r.score}<small> / 100</small></div><div style={{ marginTop: 8 }}><Pill value={r.status} /></div></div>
             : <Empty>No assessment yet.</Empty>}
        </div>
        <button className="btn" disabled={!me?.can.assess} onClick={discover}>Run discovery &amp; assessment</button>
      </div>

      {r?.blockers.map((b) => <div key={b} className="alert"><b>Critical gate failed.</b> {b}</div>)}
      {r?.status === "AMBER" && !r.gate.allowed && (
        <div className="alert warn row spread"><span>AMBER: remediation must be explicitly accepted before migration can proceed.</span>
          <button className="btn small" disabled={!me?.can.approve} onClick={() => act(() => api.approve(pid, "readiness_amber", "Accepted"), "Acceptance recorded")}>Accept as approver</button></div>
      )}

      {r && (
        <table aria-label="Readiness categories">
          <thead><tr><th>Category</th><th>Weight</th><th>Score</th><th style={{ width: "30%" }} /><th>Checks</th></tr></thead>
          <tbody>
            {Object.entries(r.categories).map(([name, c]) => (
              <tr key={name}>
                <td>{name.replace(/_/g, " ")}</td><td className="num">{c.weight}%</td><td className="num">{c.score}</td>
                <td><ScoreBar score={c.score} /></td>
                <td><details><summary>{c.checks.filter((x) => x.passed).length}/{c.checks.length} passed</summary>
                  {c.checks.map((x) => <div key={x.id} className="muted">{x.passed ? "✓" : "✗"} {x.id}{x.critical ? " (critical)" : ""} — {x.detail}</div>)}</details></td>
              </tr>))}
          </tbody>
        </table>
      )}

      <div className="panel stack">
        <h3>Readiness attestations</h3>
        {!canConfigure && <p className="muted">Your role cannot edit these.</p>}
        <div className="fields">
          {chk("privileged_access_reviewed", "Privileged access reviewed")}
          {chk("backup_plan", "Backup plan defined")}
          {chk("remediation_approved", "Remediation approved for blocking findings")}
          <label>Rollback plan<input disabled={!canConfigure} value={form.rollback_plan ?? ""} onChange={(e) => setForm({ ...form, rollback_plan: e.target.value })} /></label>
          <label>Cutover window<input disabled={!canConfigure} value={form.cutover_window ?? ""} onChange={(e) => setForm({ ...form, cutover_window: e.target.value })} /></label>
          <label>Data scope<select disabled={!canConfigure} value={form.data_scope ?? "full"} onChange={(e) => setForm({ ...form, data_scope: e.target.value })}>
            {["full", "incremental", "current_year", "actuals_only", "historical"].map((o) => <option key={o}>{o}</option>)}</select></label>
        </div>
        <div><button className="btn ghost" disabled={!canConfigure} onClick={save}>Save &amp; re-assess</button></div>
      </div>
    </div>
  );
}

/* ───────────── Environments ───────────── */
export function EnvironmentsTab({ pid }: TabProps) {
  const conn = useQuery({ queryKey: ["p", pid, "conn"], queryFn: () => api.connectivity(pid) });
  const inv = useQuery({ queryKey: ["p", pid, "inv"], queryFn: () => api.inventory(pid) });
  return (
    <div className="stack">
      <h3>Connectivity</h3>
      {conn.data?.length ? (
        <table><thead><tr><th>Side</th><th>Check</th><th>Status</th><th>Detail</th></tr></thead>
          <tbody>{conn.data.map((c, i) => <tr key={i}><td>{c.side}</td><td>{c.name}</td><td><Pill value={c.status} /></td><td className="muted">{c.detail}</td></tr>)}</tbody></table>
      ) : <Empty>No connectivity run yet. Use “Run discovery” on the Readiness tab.</Empty>}
      <div className="row" style={{ alignItems: "flex-start", gap: 24 }}>
        {(["source", "target"] as const).map((side) => (
          <div key={side} className="grow">
            <h3>{side[0].toUpperCase() + side.slice(1)} inventory</h3>
            {inv.data?.[side] ? (<>
              <p className="muted">{inv.data[side].product} {inv.data[side].version} · {inv.data[side].application}</p>
              <table><tbody>{Object.entries(inv.data[side].counts).map(([k, v]) => <tr key={k}><td>{k.replace(/_/g, " ")}</td><td className="num">{fmt(v)}</td></tr>)}</tbody></table>
            </>) : <Empty>Not collected.</Empty>}
          </div>))}
      </div>
    </div>
  );
}

/* ───────────── Compatibility ───────────── */
const ORDER = ["unsupported", "redesign_required", "remap_required", "review_required", "supported"];
export function CompatibilityTab({ pid }: TabProps) {
  const { data } = useQuery({ queryKey: ["p", pid, "compat"], queryFn: () => api.compatibility(pid) });
  if (!data?.length) return <Empty>No findings yet.</Empty>;
  const rows = [...data].sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status));
  return (
    <table><thead><tr><th>Artifact</th><th>Detail</th><th>Classification</th><th>Required action</th></tr></thead>
      <tbody>{rows.map((f, i) => <tr key={i}><td>{f.artifact.replace(/_/g, " ")}</td><td>{f.detail}</td><td><Pill value={f.status} /></td><td>{f.action}</td></tr>)}</tbody></table>
  );
}

/* ───────────── Plan & Execution ───────────── */
export function ExecutionTab({ pid, detail }: TabProps) {
  const { me } = useAuth();
  const act = useAct(pid);
  const qc = useQueryClient();
  const p = detail.project;
  const jobs = useQuery({ queryKey: ["p", pid, "jobs"], queryFn: () => api.jobs(pid), refetchInterval: (q) => q.state.data?.some((j) => j.status === "QUEUED" || j.status === "RUNNING") ? 700 : false });
  const steps = useQuery({ queryKey: ["p", pid, "steps"], queryFn: () => api.steps(pid) });
  const logs = useQuery({ queryKey: ["p", pid, "logs"], queryFn: () => api.logs(pid) });
  const active = jobs.data?.some((j) => j.status === "QUEUED" || j.status === "RUNNING") ?? false;
  const last = jobs.data?.[0];
  const [from, setFrom] = useState("");

  // When a job finishes, refresh everything it may have changed.
  useEffect(() => { if (!active) qc.invalidateQueries({ queryKey: ["p", pid] }); }, [active, pid, qc]);

  const list: Step[] = steps.data ?? [];
  if (!list.length) return (
    <div className="stack">
      <Empty>No plan yet. Plan generation requires an open readiness gate.</Empty>
      {!detail.gate.allowed && detail.gate.reason && <div className="alert warn">{detail.gate.reason}</div>}
      <button className="btn" disabled={!me?.can.assess} onClick={() => act(() => api.plan(pid), "Plan generated")}>Generate migration plan</button>
    </div>
  );
  const failed = list.find((s) => s.state === "FAILED");
  return (
    <div className="stack">
      <div className="row">
        <button className="btn" disabled={!me?.can.execute || active || p.paused} onClick={() => act(() => api.execute(pid, "next"))}>Run next step</button>
        <button className="btn accent" disabled={!me?.can.execute || active || p.paused} onClick={() => act(() => api.execute(pid, "all"))}>Run until blocked</button>
        <button className="btn ghost" disabled={!me?.can.execute} onClick={() => act(() => (p.paused ? api.resume(pid) : api.pause(pid)))}>{p.paused ? "Resume" : "Pause"}</button>
        {active && <span className="muted" role="status">Job running…</span>}
      </div>
      {last && last.status === "FAILED" && <div className="alert">Not executed: {last.error}</div>}
      {last && last.status === "SUCCEEDED" && last.result.stopped && <div className="alert warn">Stopped: {last.result.stopped}</div>}

      <ol className="ledger" aria-label="Migration steps">
        {list.map((s) => (
          <li key={s.key}>
            <span className="seq">{String(s.seq).padStart(3, "0")}</span>
            <div><b>{s.name}</b>{s.destructive && <span className="muted"> · destructive</span>}
              {s.message && <div className={s.state === "FAILED" ? "" : "muted"} style={s.state === "FAILED" ? { color: "var(--red)" } : undefined}>{s.failure_class && `[${s.failure_class}] `}{s.message}</div>}</div>
            <div className="row">
              {s.state === "AWAITING_APPROVAL" && <button className="btn small" disabled={!me?.can.approve} title={me?.can.approve ? "" : "Requires approver role"} onClick={() => act(() => api.approve(pid, `step:${s.key}`, "Approved"), "Approval recorded")}>Approve</button>}
              {s.state === "FAILED" && s.retryable && <button className="btn small ghost" disabled={!me?.can.execute} onClick={() => act(() => api.retry(pid, s.key))}>Retry</button>}
              <Pill value={s.state} />
            </div>
          </li>))}
      </ol>

      <details><summary>Rerun from an earlier step{failed ? "" : " (e.g. re-import after a validation failure)"}</summary>
        <div className="row" style={{ marginTop: 10 }}>
          <select aria-label="Rerun from step" value={from} onChange={(e) => setFrom(e.target.value)} style={{ maxWidth: 320 }}>
            <option value="">Select step…</option>{list.map((s) => <option key={s.key} value={s.key}>{s.name}</option>)}</select>
          <button className="btn ghost small" disabled={!from || !me?.can.execute || active} onClick={() => act(() => api.rerun(pid, from), "Reset. Approvals must be re-granted.")}>Reset from here</button>
        </div></details>
      <details><summary>Execution log</summary>
        <pre className="log">{(logs.data ?? []).map((l) => `${l.ts.slice(11, 19)} ${l.level.padEnd(5)} ${l.step || "-"}: ${l.message}`).join("\n") || "No log lines yet."}</pre></details>
    </div>
  );
}

/* ───────────── Validation ───────────── */
export function ValidationTab({ pid }: TabProps) {
  const { data } = useQuery({ queryKey: ["p", pid, "val"], queryFn: () => api.validation(pid) });
  if (!data?.length) return <Empty>Validation runs after the import step.</Empty>;
  const pass = data.filter((v) => v.status === "PASS").length;
  return (
    <div className="stack">
      <p><b>{pass} / {data.length}</b> checks passed</p>
      <table><thead><tr><th>Category</th><th>Check</th><th>Source</th><th>Target</th><th>Diff</th><th>Status</th></tr></thead>
        <tbody>{data.map((v) => <tr key={v.category + v.check}><td>{v.category}</td><td>{v.check.replace(/_/g, " ")}</td><td className="num">{fmt(v.source)}</td><td className="num">{fmt(v.target)}</td><td className="num">{fmt(v.diff)}</td><td><Pill value={v.status} /></td></tr>)}</tbody></table>
    </div>
  );
}

/* ───────────── Evidence & audit ───────────── */
export function EvidenceTab({ pid }: TabProps) {
  const act = useAct(pid);
  const audit = useQuery({ queryKey: ["p", pid, "audit"], queryFn: () => api.audit(pid) });
  const appr = useQuery({ queryKey: ["p", pid, "appr"], queryFn: () => api.approvals(pid) });
  return (
    <div className="stack">
      <div className="row spread">
        {audit.data && (audit.data.chain_intact ? <div className="alert ok">Audit chain intact</div> : <div className="alert">Audit chain broken at entry {audit.data.first_bad_id}</div>)}
        <div className="row">
          <button className="btn ghost" onClick={() => act(() => api.download(pid, "xlsx"))}>Download Excel report</button>
          <button className="btn ghost" onClick={() => act(() => api.download(pid, "json"))}>Download JSON report</button>
        </div>
      </div>
      <h3>Approvals</h3>
      {appr.data?.length ? <table><thead><tr><th>Subject</th><th>Approver</th><th>Decision</th><th>When</th></tr></thead>
        <tbody>{appr.data.map((a, i) => <tr key={i}><td>{a.subject}</td><td>{a.approver}</td><td><Pill value={a.decision} /></td><td className="muted">{a.created_at.slice(0, 19).replace("T", " ")}</td></tr>)}</tbody></table> : <Empty>None recorded.</Empty>}
      <h3>Audit trail</h3>
      <table><thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Details</th></tr></thead>
        <tbody>{audit.data?.entries.map((e) => <tr key={e.id}><td className="muted">{e.ts.slice(0, 19).replace("T", " ")}</td><td>{e.actor}</td><td>{e.action}</td><td className="muted">{JSON.stringify(e.details)}</td></tr>)}</tbody></table>
    </div>
  );
}
