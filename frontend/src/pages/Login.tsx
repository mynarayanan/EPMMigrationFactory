import { useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { useAuth } from "../auth";

export default function Login() {
  const { login } = useAuth();
  const cfg = useQuery({ queryKey: ["config"], queryFn: api.config });
  const [u, setU] = useState(""); const [p, setP] = useState(""); const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setErr("");
    try { await login(u, p); } catch (x) { setErr(x instanceof ApiError ? x.message : "Sign-in failed"); } finally { setBusy(false); }
  }
  if (cfg.data?.auth_mode === "oidc") return (
    <div className="login" style={{ maxWidth: 420, margin: "12vh auto" }}>
      <h2><span className="brand">EPM <b>Migration</b> Workbench</span></h2>
      <p className="muted">This deployment uses enterprise SSO. Sign in through your identity provider; the browser UI needs the OIDC redirect
        integration (see README → “Known gaps”) before it can obtain a token.</p>
    </div>);
  return (
    <form className="login" onSubmit={submit}>
      <h2 className="brand">EPM <b>Migration</b> Workbench</h2>
      <label>Username<input autoFocus value={u} onChange={(e) => setU(e.target.value)} autoComplete="username" /></label>
      <label>Password<input type="password" value={p} onChange={(e) => setP(e.target.value)} autoComplete="current-password" /></label>
      {err && <div className="alert" role="alert">{err}</div>}
      <button className="btn" disabled={busy || !u || !p}>Sign in</button>
      <p className="muted">Development sign-in. Production uses SSO/OIDC.</p>
    </form>
  );
}
