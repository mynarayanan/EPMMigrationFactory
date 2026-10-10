import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { useAuth } from "../auth";
import { useNotify } from "../notify";
import type { EnvInput, ProjectInput } from "../types";
import { emptyEnv, toPayload, validateProject } from "../validation";

type FieldProps = { id: string; label: string; value: string; error?: string; hint?: string; onValue: (v: string) => void } &
  Omit<React.InputHTMLAttributes<HTMLInputElement>, "id" | "value" | "onChange">;

// Defined at module level on purpose: a component declared inside another component is a new type on every render,
// which remounts the <input> and drops focus after each keystroke.
function Field({ id, label, value, error, hint, onValue, ...rest }: FieldProps) {
  return (
    <div><label htmlFor={id}>{label}</label>
      <input id={id} value={value} aria-invalid={!!error} aria-describedby={error ? `${id}-e` : undefined} onChange={(e) => onValue(e.target.value)} {...rest} />
      {hint && !error && <small className="muted">{hint}</small>}
      {error && <small id={`${id}-e`} className="field-error" role="alert">{error}</small>}</div>
  );
}

function EnvFields({ side, env, onChange, errors, hostHint }: {
  side: "source" | "target"; env: EnvInput; onChange: (e: EnvInput) => void; errors: Record<string, string>; hostHint: string;
}) {
  const set = (k: keyof EnvInput, v: string) => onChange({ ...env, [k]: v });
  const f = (k: keyof EnvInput, label: string, extra: Partial<FieldProps> = {}) => (
    <Field id={`${side}-${k}`} label={label} value={env[k]} error={errors[`${side}.${k}`]} onValue={(v) => set(k, v)} {...extra} />);
  const id = (k: string) => `${side}-${k}`;
  return (
    <fieldset className="panel stack">
      <legend><b>{side === "source" ? "Source environment" : "Target environment"}</b></legend>
      <div><label htmlFor={id("connector")}>Connection type</label>
        <select id={id("connector")} value={env.connector} onChange={(e) => onChange({ ...env, connector: e.target.value as EnvInput["connector"] })}>
          <option value="mock">Simulated environment (demo / testing)</option><option value="live">Oracle Cloud EPM (live)</option></select></div>
      {env.connector === "mock" ? (
        <div><label htmlFor={id("profile")}>Simulated profile</label>
          <select id={id("profile")} value={env.profile} onChange={(e) => set("profile", e.target.value)}>
            {side === "source" ? <><option value="clean">Clean Planning application</option><option value="issues">Planning application with compatibility issues</option></>
                               : <option value="empty_target">Empty target environment</option>}</select></div>
      ) : (
        <>
          {f("url", "Environment URL", { placeholder: "https://<name>.epm.<region>.ocs.oraclecloud.com", hint: hostHint, inputMode: "url" })}
          <div className="fields">
            {f("user", "Service account", { autoComplete: "off" })}
            {f("identity_domain", "Identity domain (optional)", { autoComplete: "off" })}
          </div>
          {f("password_file_env", "Password-file variable name", { placeholder: `EPM_${side.toUpperCase()}_PWF`, autoComplete: "off", spellCheck: false,
            hint: "Not a password. The name of a server-side environment variable that holds the path to an EPM Automate encrypted password file." })}
        </>)}
      {f("version", "Version (optional)", { placeholder: "e.g. 25.09" })}
    </fieldset>
  );
}

export default function NewProject() {
  const { me } = useAuth(); const nav = useNavigate(); const notify = useNotify(); const qc = useQueryClient();
  const cfg = useQuery({ queryKey: ["config"], queryFn: api.config });
  const [p, setP] = useState<ProjectInput>({ name: "", client: "", owner: me?.username ?? "", planned_date: "", pattern: "cloud_to_cloud",
    source: emptyEnv("clean"), target: emptyEnv("empty_target"), settings: {} });
  const [errors, setErrors] = useState<Record<string, string>>({}); const [busy, setBusy] = useState(false); const [serverErr, setServerErr] = useState("");
  const suffixes = cfg.data?.epm_host_suffixes ?? [];
  const live = p.source.connector === "live" || p.target.connector === "live";
  const hint = suffixes.length ? `Must end with ${suffixes.join(" or ")}` : "";

  if (me && !me.can.create_project) return <div className="alert warn">Your role cannot create projects.</div>;

  async function submit(e: React.FormEvent) {
    e.preventDefault(); setServerErr("");
    const errs = validateProject(p, suffixes); setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    try {
      const created = await api.createProject(toPayload(p));
      await qc.invalidateQueries({ queryKey: ["projects"] });
      notify("ok", "Project created. Run discovery on the Readiness tab.");
      nav(`/projects/${created.id}`);
    } catch (x) { setServerErr(x instanceof ApiError ? x.message : "Could not create the project"); } finally { setBusy(false); }
  }

  return (
    <form className="stack" onSubmit={submit} noValidate aria-label="Create migration project">
      <p><Link to="/">← Portfolio</Link></p>
      <h2>New migration project</h2>
      <div className="panel stack">
        <div className="fields">
          <div><label htmlFor="name">Project name</label><input id="name" value={p.name} aria-invalid={!!errors.name} onChange={(e) => setP({ ...p, name: e.target.value })} />
            {errors.name && <small className="field-error" role="alert">{errors.name}</small>}</div>
          <div><label htmlFor="client">Client / business unit</label><input id="client" value={p.client} onChange={(e) => setP({ ...p, client: e.target.value })} /></div>
          <div><label htmlFor="owner">Migration owner</label><input id="owner" value={p.owner} onChange={(e) => setP({ ...p, owner: e.target.value })} /></div>
          <div><label htmlFor="date">Planned migration date</label><input id="date" type="date" value={p.planned_date} onChange={(e) => setP({ ...p, planned_date: e.target.value })} /></div>
          <div><label htmlFor="pattern">Migration pattern</label><select id="pattern" value={p.pattern} onChange={(e) => setP({ ...p, pattern: e.target.value })}>
            <option value="cloud_to_cloud">Cloud EPM → Cloud EPM (snapshot)</option></select></div>
        </div>
      </div>
      <div className="row" style={{ alignItems: "flex-start", gap: 20 }}>
        <div className="grow"><EnvFields side="source" env={p.source} errors={errors} hostHint={hint} onChange={(source) => setP({ ...p, source })} /></div>
        <div className="grow"><EnvFields side="target" env={p.target} errors={errors} hostHint={hint} onChange={(target) => setP({ ...p, target })} /></div>
      </div>
      {live && <div className="alert warn"><b>Live connections are not proven yet.</b> They need EPM Automate installed on the API server and the password file mounted there.
        Live inventory is not implemented, so discovery and assessment cannot complete for a live environment until it is.</div>}
      {serverErr && <div className="alert" role="alert">{serverErr}</div>}
      <div className="row"><button className="btn" disabled={busy}>Create project</button><Link className="btn ghost" to="/" style={{ textDecoration: "none" }}>Cancel</Link></div>
    </form>
  );
}
