import type { EnvInput, ProjectInput } from "./types";

export const emptyEnv = (profile: EnvInput["profile"]): EnvInput => ({
  connector: "mock", url: "", version: "", profile, user: "", identity_domain: "", password_file_env: "",
});

/** Mirrors the server rules so users get instant feedback; the server remains the authority. */
export function validateEnv(e: EnvInput, suffixes: string[]): Record<string, string> {
  const err: Record<string, string> = {};
  if (e.connector === "mock") { if (!e.profile) err.profile = "Choose a simulated profile"; return err; }
  let u: URL | null = null;
  try { u = new URL(e.url); } catch { /* handled below */ }
  if (!u) err.url = "Enter the full environment URL, e.g. https://<name>.epm.<region>.ocs.oraclecloud.com";
  else if (u.protocol !== "https:") err.url = "URL must use https";
  else if (u.username || u.password) err.url = "Do not put credentials in the URL";
  else if (u.port && u.port !== "443") err.url = "Only the default HTTPS port is allowed";
  else if (/^[\d.]+$/.test(u.hostname) || u.hostname.includes(":") || u.hostname === "localhost") err.url = "Use the environment host name, not an IP address";
  else if (suffixes.length && !suffixes.some((s) => u!.hostname.toLowerCase().endsWith(s))) err.url = `Host must end with ${suffixes.join(" or ")}`;
  if (!/^[A-Za-z0-9._@-]{1,100}$/.test(e.user)) err.user = "Service account name is required (letters, digits . _ @ -)";
  if (e.identity_domain && !/^[A-Za-z0-9._-]{1,100}$/.test(e.identity_domain)) err.identity_domain = "Unsupported characters";
  if (!/^EPM_[A-Z0-9_]{1,60}$/.test(e.password_file_env)) err.password_file_env = "Must be a variable name like EPM_SOURCE_PWF (EPM_ prefix, capitals, digits, _)";
  return err;
}

export function validateProject(p: ProjectInput, suffixes: string[]) {
  const errors: Record<string, string> = {};
  if (!p.name.trim()) errors.name = "Project name is required";
  for (const side of ["source", "target"] as const)
    for (const [k, v] of Object.entries(validateEnv(p[side], suffixes))) errors[`${side}.${k}`] = v;
  return errors;
}

/** Strip fields that don't apply to the chosen connector so the request body is minimal and valid. */
export function toPayload(p: ProjectInput): ProjectInput {
  const clean = (e: EnvInput): EnvInput => e.connector === "mock"
    ? { ...emptyEnv(e.profile), connector: "mock", version: e.version.trim() }
    : { ...emptyEnv(""), connector: "live", url: e.url.trim(), user: e.user.trim(), identity_domain: e.identity_domain.trim(),
        password_file_env: e.password_file_env.trim(), version: e.version.trim() };
  return { ...p, name: p.name.trim(), source: clean(p.source), target: clean(p.target) };
}
