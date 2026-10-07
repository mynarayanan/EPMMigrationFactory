import type * as T from "./types";

const BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";
const KEY = "epmwb.token";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

let token: string | null = typeof sessionStorage !== "undefined" ? sessionStorage.getItem(KEY) : null;
let onUnauthorized: () => void = () => {};
export const setUnauthorizedHandler = (fn: () => void) => { onUnauthorized = fn; };
export const getToken = () => token;
export function setToken(t: string | null) {
  token = t;
  if (typeof sessionStorage !== "undefined") t ? sessionStorage.setItem(KEY, t) : sessionStorage.removeItem(KEY);
}

async function raw(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const res = await fetch(`${BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : Array.isArray(j.detail) ? j.detail.map((d: { msg: string }) => d.msg).join("; ") : detail;
    } catch { /* non-JSON error body */ }
    if (res.status === 401 && token) { setToken(null); onUnauthorized(); }
    throw new ApiError(res.status, detail);
  }
  return res;
}

async function json<R>(path: string, init?: RequestInit): Promise<R> { return (await raw(path, init)).json() as Promise<R>; }
const post = <R>(path: string, body?: unknown) => json<R>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  config: () => json<T.AppConfig>("/api/config"),
  login: (username: string, password: string) => post<{ access_token: string }>("/api/auth/login", { username, password }),
  me: () => json<T.Me>("/api/me"),
  projects: () => json<T.Project[]>("/api/projects"),
  demo: (scenario: "clean" | "issues") => post<T.Project>("/api/projects/demo", { scenario }),
  project: (id: number) => json<T.ProjectDetail>(`/api/projects/${id}`),
  patchSettings: (id: number, body: T.Settings) => json<T.Project>(`/api/projects/${id}/settings`, { method: "PATCH", body: JSON.stringify(body) }),
  connectivity: (id: number) => json<T.ConnCheck[]>(`/api/projects/${id}/connectivity`),
  runConnectivity: (id: number) => post<T.ConnCheck[]>(`/api/projects/${id}/connectivity`),
  inventory: (id: number) => json<Record<string, T.Inventory>>(`/api/projects/${id}/inventory`),
  collectInventory: (id: number) => post<Record<string, string>>(`/api/projects/${id}/inventory`),
  assess: (id: number) => post<T.Readiness>(`/api/projects/${id}/assess`),
  readiness: (id: number) => json<T.Readiness | null>(`/api/projects/${id}/readiness`),
  compatibility: (id: number) => json<T.Finding[]>(`/api/projects/${id}/compatibility`),
  approvals: (id: number) => json<T.Approval[]>(`/api/projects/${id}/approvals`),
  approve: (id: number, subject: string, comment = "") => post<{ ok: boolean }>(`/api/projects/${id}/approvals`, { subject, decision: "APPROVED", comment }),
  plan: (id: number) => post<T.Step[]>(`/api/projects/${id}/plan`),
  steps: (id: number) => json<T.Step[]>(`/api/projects/${id}/steps`),
  execute: (id: number, mode: "next" | "all") => post<T.Job>(`/api/projects/${id}/execute`, { mode }),
  jobs: (id: number) => json<T.Job[]>(`/api/projects/${id}/jobs`),
  retry: (id: number, key: string) => post<T.Step[]>(`/api/projects/${id}/steps/${key}/retry`),
  rerun: (id: number, from_step: string) => post<T.Step[]>(`/api/projects/${id}/rerun`, { from_step }),
  pause: (id: number) => post<T.Project>(`/api/projects/${id}/pause`),
  resume: (id: number) => post<T.Project>(`/api/projects/${id}/resume`),
  validation: (id: number) => json<T.Validation[]>(`/api/projects/${id}/validation`),
  logs: (id: number) => json<T.LogLine[]>(`/api/projects/${id}/logs`),
  audit: (id: number) => json<T.AuditTrail>(`/api/projects/${id}/audit`),
  async download(id: number, fmt: "xlsx" | "json") {
    const blob = await (await raw(`/api/projects/${id}/report.${fmt}`)).blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `epm_report_${id}.${fmt}`; a.click();
    URL.revokeObjectURL(url);
  },
};
