export type Role = "operator" | "approver" | "admin";
export interface Me { username: string; roles: Role[]; can: Record<"create_project" | "configure" | "assess" | "execute" | "approve", boolean>; }
export interface AppConfig { auth_mode: "dev" | "oidc"; demo_enabled: boolean; env: string; }
export type GateStatus = "GREEN" | "AMBER" | "RED";
export interface Gate { allowed: boolean; status: GateStatus | null; reason: string; score?: number; }
export interface Project {
  id: number; name: string; client: string; pattern: string; owner: string; planned_date: string; status: string;
  paused: boolean; created_by: string; created_at: string; source: Record<string, unknown>; target: Record<string, unknown>;
  settings: Settings; readiness?: { score: number; status: GateStatus } | null;
}
export interface Settings {
  privileged_access_reviewed?: boolean; backup_plan?: boolean; remediation_approved?: boolean;
  rollback_plan?: string; cutover_window?: string; data_scope?: string;
}
export type PhaseState = "PENDING" | "ACTIVE" | "DONE" | "FAILED";
export interface Phase { key: string; label: string; state: PhaseState; }
export interface ProjectDetail { project: Project; gate: Gate; lifecycle: Phase[]; readiness: { score: number; status: GateStatus } | null; }
export interface Check { id: string; passed: boolean; critical: boolean; detail: string; }
export interface Readiness {
  score: number; status: GateStatus; blockers: string[]; assessed_at: string; gate: Gate;
  categories: Record<string, { weight: number; score: number; checks: Check[] }>;
}
export interface Finding { artifact: string; detail: string; status: string; action: string; group: string; }
export interface ConnCheck { side: string; name: string; status: "PASS" | "FAIL"; detail: string; }
export type StepState = "BLOCKED" | "READY" | "AWAITING_APPROVAL" | "RUNNING" | "COMPLETE" | "FAILED" | "SKIPPED";
export interface Step {
  seq: number; key: string; name: string; state: StepState; requires_approval: boolean; destructive: boolean;
  skippable: boolean; retryable: boolean; attempts: number; failure_class: string; message: string;
}
export interface Job {
  id: number; project_id: number; mode: "next" | "all"; status: "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED";
  actor: string; result: { ran?: [string, string][]; stopped?: string }; error: string; created_at: string; finished_at: string | null;
}
export interface Validation { category: string; check: string; source: number; target: number; diff: number; status: "PASS" | "FAIL"; }
export interface Approval { subject: string; approver: string; decision: string; comment: string; created_at: string; }
export interface AuditTrail { chain_intact: boolean; first_bad_id: number | null; entries: { id: number; ts: string; actor: string; action: string; details: Record<string, unknown> }[]; }
export interface LogLine { ts: string; step: string; level: string; message: string; }
export interface Inventory { product: string; version: string; application: string; counts: Record<string, number>; }
