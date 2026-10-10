from __future__ import annotations
import tempfile
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from core.models import (Approval, ValidationResult, RunLog, Evidence, AuditEntry, Inventory, Connectivity)
from core.reports import build_report, export_json, export_xlsx
from core.support import Actor, verify_audit_chain
from . import schemas as S
from .auth import get_actor

router = APIRouter(prefix="/api")


def check_live_host(url: str, suffixes: tuple) -> None:
    """Server-side request forgery guard: live URLs must be https, on the default port, carry no credentials,
    not be an IP literal/localhost, and end with an allowed Oracle cloud suffix."""
    import ipaddress
    from urllib.parse import urlparse
    u = urlparse(url)
    host = (u.hostname or "").lower()
    bad = None
    if u.scheme != "https": bad = "URL must use https"
    elif u.username or u.password: bad = "URL must not contain credentials"
    elif u.port not in (None, 443): bad = "Only the default HTTPS port is allowed"
    elif not host or host == "localhost": bad = "Host not allowed"
    else:
        try:
            ipaddress.ip_address(host); bad = "IP addresses are not allowed; use the environment host name"
        except ValueError:
            if not any(host.endswith(s) for s in suffixes):
                bad = f"Host must end with one of: {', '.join(suffixes)} (set EPM_ALLOWED_HOST_SUFFIXES to change)"
    if bad: raise HTTPException(422, bad)


def wb(request: Request): return request.app.state.wb
def runner(request: Request): return request.app.state.runner


def _project_out(p) -> dict:
    d = S.ProjectOut.model_validate(p).model_dump(mode="json")
    d["settings"] = {k: v for k, v in p.settings.items() if k != "approval_floor"}
    return d


def _lifecycle(w, pid) -> list[dict]:
    """Phase rail for the UI: discovery -> readiness -> plan -> import -> validation -> sign-off."""
    p, steps = w.get_project(pid), {s.key: s for s in w.steps(pid)}
    with w.session() as s:
        has_inv = bool(s.scalars(select(Inventory).where(Inventory.project_id == pid, Inventory.side == "source").limit(1)).first())
    rr, g = w.latest_readiness(pid), w.gate(pid)

    def st(key): return steps[key].state if key in steps else "PENDING"
    def phase(keys):
        sts = [st(k) for k in keys]
        if any(x == "FAILED" for x in sts): return "FAILED"
        if all(x in ("COMPLETE", "SKIPPED") for x in sts): return "DONE"
        if any(x in ("RUNNING", "READY", "AWAITING_APPROVAL") or x in ("COMPLETE", "SKIPPED") for x in sts): return "ACTIVE"
        return "PENDING"
    readiness = "PENDING" if not rr else ("DONE" if g["allowed"] else "FAILED")
    return [
        {"key": "discovery", "label": "Discovery", "state": "DONE" if has_inv else "ACTIVE"},
        {"key": "readiness", "label": "Readiness gate", "state": readiness if has_inv else "PENDING"},
        {"key": "plan", "label": "Plan", "state": "DONE" if steps else "PENDING"},
        {"key": "prepare", "label": "Backup & transfer", "state": phase(["backup_source", "validate_target", "export_snapshot", "transfer_snapshot"])},
        {"key": "import", "label": "Import", "state": phase(["import_snapshot"])},
        {"key": "validate", "label": "Validation", "state": phase(["technical_validation", "data_reconciliation"])},
        {"key": "signoff", "label": "Sign-off", "state": phase(["business_signoff"])},
    ]


# ---- identity
@router.post("/auth/login")
def login(body: S.LoginIn, request: Request):
    if request.app.state.settings.auth_mode != "dev": raise HTTPException(404, "Not found")
    return {"access_token": request.app.state.auth.login(body.username, body.password), "token_type": "bearer"}


@router.get("/me")
def me(actor: Actor = Depends(get_actor)):
    return {"username": actor.username, "roles": sorted(actor.roles),
            "can": {p: actor.can(p) for p in ("create_project", "configure", "assess", "execute", "approve")}}


@router.get("/config")
def public_config(request: Request):
    s = request.app.state.settings
    return {"auth_mode": s.auth_mode, "demo_enabled": s.enable_demo, "env": s.env, "epm_host_suffixes": list(s.epm_host_suffixes)}


# ---- projects
@router.get("/projects")
def list_projects(w=Depends(wb), actor: Actor = Depends(get_actor)):
    out = []
    for p in w.list_projects():
        rr = w.latest_readiness(p.id)
        out.append({**_project_out(p), "readiness": None if not rr else {"score": rr.score, "status": rr.status}})
    return out


@router.post("/projects", status_code=201)
def create_project(body: S.ProjectCreate, request: Request, w=Depends(wb), actor: Actor = Depends(get_actor)):
    actor.require("create_project")
    for env in (body.source, body.target):
        if env.connector == "live": check_live_host(env.url, request.app.state.settings.epm_host_suffixes)
    p = w.create_project(actor, body.name, {**body.source.model_dump(exclude_defaults=True), "connector": body.source.connector},
                         {**body.target.model_dump(exclude_defaults=True), "connector": body.target.connector},
                         body.client, body.owner, body.planned_date, body.pattern, body.settings.model_dump(exclude_none=True))
    return _project_out(p)


@router.post("/projects/demo", status_code=201)
def create_demo(body: S.DemoRequest, request: Request, w=Depends(wb), actor: Actor = Depends(get_actor)):
    if not request.app.state.settings.enable_demo: raise HTTPException(404, "Demo mode is disabled")
    return _project_out(w.create_demo(actor, body.scenario))


@router.get("/projects/{pid}")
def get_project(pid: int, w=Depends(wb), actor: Actor = Depends(get_actor)):
    p = w.get_project(pid); rr = w.latest_readiness(pid)
    return {"project": _project_out(p), "gate": w.gate(pid), "lifecycle": _lifecycle(w, pid),
            "readiness": None if not rr else {"score": rr.score, "status": rr.status}}


@router.patch("/projects/{pid}/settings")
def patch_settings(pid: int, body: S.SettingsPatch, w=Depends(wb), actor: Actor = Depends(get_actor)):
    w.update_settings(actor, pid, **body.model_dump(exclude_none=True))
    return _project_out(w.get_project(pid))


# ---- discovery + assessment
@router.post("/projects/{pid}/connectivity")
def run_connectivity(pid: int, w=Depends(wb), actor: Actor = Depends(get_actor)):
    w.run_connectivity(actor, pid)
    return get_connectivity(pid, w, actor)


@router.get("/projects/{pid}/connectivity")
def get_connectivity(pid: int, w=Depends(wb), actor: Actor = Depends(get_actor)):
    w.get_project(pid)
    return [{"side": c.side, "name": c.name, "status": c.status, "detail": c.detail} for c in w.connectivity_latest(pid)]


@router.post("/projects/{pid}/inventory")
def collect_inventory(pid: int, w=Depends(wb), actor: Actor = Depends(get_actor)):
    return w.collect_inventory(actor, pid)


@router.get("/projects/{pid}/inventory")
def get_inventory(pid: int, w=Depends(wb), actor: Actor = Depends(get_actor)):
    w.get_project(pid)
    latest: dict = {}
    for r in w.rows(Inventory, pid): latest[r.side] = r.data
    return latest


@router.post("/projects/{pid}/assess")
def assess(pid: int, w=Depends(wb), actor: Actor = Depends(get_actor)):
    w.assess(actor, pid)
    return get_readiness(pid, w, actor)


@router.get("/projects/{pid}/readiness")
def get_readiness(pid: int, w=Depends(wb), actor: Actor = Depends(get_actor)):
    w.get_project(pid); r = w.latest_readiness(pid)
    return None if not r else {"score": r.score, "status": r.status, "categories": r.categories,
                               "blockers": r.blockers, "assessed_at": r.created_at, "gate": w.gate(pid)}


@router.get("/projects/{pid}/compatibility")
def get_compat(pid: int, w=Depends(wb), actor: Actor = Depends(get_actor)):
    w.get_project(pid); c = w.latest_compat(pid)
    return [] if not c else c.findings


# ---- approvals, plan, execution
@router.post("/projects/{pid}/approvals", status_code=201)
def approve(pid: int, body: S.ApprovalIn, w=Depends(wb), actor: Actor = Depends(get_actor)):
    w.approve(actor, pid, body.subject, body.decision, body.comment)
    return {"ok": True}


@router.get("/projects/{pid}/approvals")
def approvals(pid: int, w=Depends(wb), actor: Actor = Depends(get_actor)):
    w.get_project(pid)
    return [{"subject": a.subject, "approver": a.approver, "decision": a.decision, "comment": a.comment,
             "created_at": a.created_at} for a in w.rows(Approval, pid)]


@router.post("/projects/{pid}/plan", status_code=201)
def generate_plan(pid: int, w=Depends(wb), actor: Actor = Depends(get_actor)):
    w.generate_plan(actor, pid)
    return get_steps(pid, w, actor)


@router.get("/projects/{pid}/steps")
def get_steps(pid: int, w=Depends(wb), actor: Actor = Depends(get_actor)):
    w.get_project(pid)
    return [S.StepOut.model_validate(s).model_dump(mode="json") for s in w.steps(pid)]


@router.post("/projects/{pid}/execute", status_code=202)
def execute(pid: int, body: S.ExecuteIn, r=Depends(runner), actor: Actor = Depends(get_actor)):
    return S.JobOut.model_validate(r.submit(actor, pid, body.mode)).model_dump(mode="json")


@router.get("/projects/{pid}/jobs")
def project_jobs(pid: int, r=Depends(runner), w=Depends(wb), actor: Actor = Depends(get_actor)):
    w.get_project(pid)
    return [S.JobOut.model_validate(j).model_dump(mode="json") for j in r.for_project(pid)]


@router.get("/jobs/{job_id}")
def get_job(job_id: int, r=Depends(runner), actor: Actor = Depends(get_actor)):
    return S.JobOut.model_validate(r.get(job_id)).model_dump(mode="json")


@router.post("/projects/{pid}/steps/{key}/retry")
def retry(pid: int, key: str, w=Depends(wb), actor: Actor = Depends(get_actor)):
    w.retry_step(actor, pid, key); return get_steps(pid, w, actor)


@router.post("/projects/{pid}/steps/{key}/skip")
def skip(pid: int, key: str, body: dict | None = None, w=Depends(wb), actor: Actor = Depends(get_actor)):
    w.skip_step(actor, pid, key, (body or {}).get("reason", "")); return get_steps(pid, w, actor)


@router.post("/projects/{pid}/rerun")
def rerun(pid: int, body: S.RerunIn, w=Depends(wb), actor: Actor = Depends(get_actor)):
    w.rerun_from(actor, pid, body.from_step); return get_steps(pid, w, actor)


@router.post("/projects/{pid}/pause")
def pause(pid: int, w=Depends(wb), actor: Actor = Depends(get_actor)):
    w.set_paused(actor, pid, True); return _project_out(w.get_project(pid))


@router.post("/projects/{pid}/resume")
def resume(pid: int, w=Depends(wb), actor: Actor = Depends(get_actor)):
    w.set_paused(actor, pid, False); return _project_out(w.get_project(pid))


# ---- evidence + reporting
@router.get("/projects/{pid}/validation")
def validation(pid: int, w=Depends(wb), actor: Actor = Depends(get_actor)):
    w.get_project(pid)
    return [{"category": v.category, "check": v.check, "source": v.source_value, "target": v.target_value,
             "diff": v.diff, "status": v.status} for v in w.rows(ValidationResult, pid)]


@router.get("/projects/{pid}/logs")
def logs(pid: int, limit: int = Query(500, le=2000), w=Depends(wb), actor: Actor = Depends(get_actor)):
    w.get_project(pid)
    return [{"ts": l.ts, "step": l.step_key, "level": l.level, "message": l.message} for l in w.rows(RunLog, pid)][-limit:]


@router.get("/projects/{pid}/evidence")
def evidence(pid: int, w=Depends(wb), actor: Actor = Depends(get_actor)):
    w.get_project(pid)
    return [{"step": e.step_key, "kind": e.kind, "sha256": e.sha256, "ts": e.ts, "content": e.content} for e in w.rows(Evidence, pid)]


@router.get("/projects/{pid}/audit")
def audit_trail(pid: int, limit: int = Query(500, le=2000), w=Depends(wb), actor: Actor = Depends(get_actor)):
    w.get_project(pid)
    with w.session() as s:
        rows = list(s.scalars(select(AuditEntry).where(AuditEntry.project_id == pid).order_by(AuditEntry.id.desc()).limit(limit)))
        ok, bad = verify_audit_chain(s)
    return {"chain_intact": ok, "first_bad_id": bad,
            "entries": [{"id": e.id, "ts": e.ts, "actor": e.actor, "action": e.action, "details": e.details} for e in rows]}


@router.get("/projects/{pid}/report.{fmt}")
def report(pid: int, fmt: str, w=Depends(wb), actor: Actor = Depends(get_actor)):
    if fmt not in ("json", "xlsx"): raise HTTPException(404, "Unknown report format")
    w.get_project(pid)
    with tempfile.TemporaryDirectory() as d:
        path = (export_json if fmt == "json" else export_xlsx)(w, pid, Path(d) / f"report.{fmt}")
        data = Path(path).read_bytes()
    mt = "application/json" if fmt == "json" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(data, media_type=mt, headers={"Content-Disposition": f'attachment; filename="epm_report_{pid}.{fmt}"'})
