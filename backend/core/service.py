"""Workbench service: project lifecycle, gating, plan generation, execution state machine, validation."""
from __future__ import annotations
import hashlib, json, os
from contextlib import contextmanager
from pathlib import Path
from sqlalchemy import select, delete, func
from sqlalchemy.orm import Session
from connectors.base import ConnectorError
from connectors.factory import build_connector
from .models import (Project, Inventory, Connectivity, CompatRun, ReadinessRun, Step, Approval, RunLog,
                     Evidence, ValidationResult, AuditEntry, Job, utcnow)
from .support import Actor, GateError, NotFound, audit, load_config, make_engine, init_db
from .assessment import evaluate_compatibility, score_readiness

TERMINAL = ("COMPLETE", "SKIPPED")
DEFAULT_SETTINGS = {"data_scope": "full", "privileged_access_reviewed": False, "backup_plan": False,
                    "rollback_plan": "", "cutover_window": "", "remediation_approved": False}


class StepFailure(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message); self.kind = kind


class Workbench:
    def __init__(self, engine=None, config: dict | None = None, state_dir: str | None = None):
        self.engine = engine or make_engine()
        if engine is None and str(self.engine.url).startswith("sqlite:///:memory:"): init_db(self.engine)
        self.cfg = config or load_config()
        self.state_dir = state_dir or os.environ.get("EPM_MOCK_STATE_DIR", ".mock_state")

    # ---------- plumbing
    @contextmanager
    def session(self):
        with Session(self.engine, expire_on_commit=False) as s:
            yield s
            s.commit()

    def _connector(self, p: Project, side: str):
        return build_connector(p.source if side == "source" else p.target, p.id, side, self.state_dir)

    def _project(self, s, pid) -> Project:
        p = s.get(Project, pid)
        if not p: raise NotFound(f"Project {pid} not found")
        return p

    def _latest_inv(self, s, pid, side):
        r = s.scalars(select(Inventory).where(Inventory.project_id == pid, Inventory.side == side)
                      .order_by(Inventory.id.desc()).limit(1)).first()
        return r.data if r else None

    def _log(self, s, pid, key, msg, level="INFO"):
        s.add(RunLog(project_id=pid, step_key=key, level=level, message=msg))

    def _evidence(self, s, pid, key, kind, content):
        raw = json.dumps(content, sort_keys=True, default=str)
        s.add(Evidence(project_id=pid, step_key=key, kind=kind, content=content,
                       sha256=hashlib.sha256(raw.encode()).hexdigest()))

    # ---------- project + discovery
    def create_project(self, actor: Actor, name, source: dict, target: dict, client="", owner="",
                       planned_date="", pattern="cloud_to_cloud", settings: dict | None = None) -> Project:
        actor.require("create_project")
        if pattern not in self.cfg["migration_patterns"]["patterns"]:
            raise GateError(f"Unsupported pattern: {pattern}")
        with self.session() as s:
            p = Project(name=name, client=client, owner=owner, planned_date=planned_date, pattern=pattern,
                        source=source, target=target, settings={**DEFAULT_SETTINGS, **(settings or {})},
                        created_by=actor.username)
            s.add(p); s.flush()
            import shutil
            for side in ("source", "target"):  # fresh simulated state for a new project id
                shutil.rmtree(Path(self.state_dir) / f"p{p.id}_{side}", ignore_errors=True)
            audit(s, actor.username, "project.create", p.id, name=name, pattern=pattern)
            return p

    def update_settings(self, actor: Actor, pid: int, **kv):
        actor.require("configure")
        with self.session() as s:
            p = self._project(s, pid)
            p.settings = {**p.settings, **kv}
            audit(s, actor.username, "project.settings", pid, **kv)

    def run_connectivity(self, actor: Actor, pid: int) -> dict:
        actor.require("assess")
        with self.session() as s:
            p = self._project(s, pid)
            run_no = (s.scalar(select(func.max(Connectivity.run_no)).where(Connectivity.project_id == pid)) or 0) + 1
            out = {}
            for side in ("source", "target"):
                try:
                    res = self._connector(p, side).check_connectivity()
                except ConnectorError as e:
                    from connectors.base import CheckResult
                    res = [CheckResult("connection", "FAIL", str(e))]
                out[side] = res
                for r in res:
                    s.add(Connectivity(project_id=pid, run_no=run_no, side=side, name=r.name, status=r.status, detail=r.detail))
            audit(s, actor.username, "connectivity.run", pid, run_no=run_no,
                  failed=[f"{k}:{r.name}" for k, v in out.items() for r in v if r.status != "PASS"])
            return out

    def collect_inventory(self, actor: Actor, pid: int) -> dict:
        actor.require("assess")
        status = {}
        with self.session() as s:
            p = self._project(s, pid)
            for side in ("source", "target"):
                try:
                    inv = self._connector(p, side).get_inventory()
                    s.add(Inventory(project_id=pid, side=side, data=inv)); status[side] = "OK"
                except ConnectorError as e:
                    status[side] = f"{e.kind}: {e}"
            audit(s, actor.username, "inventory.collect", pid, status=status)
        return status

    # ---------- assessment
    def _conn_latest(self, s, pid) -> dict:
        run = s.scalar(select(func.max(Connectivity.run_no)).where(Connectivity.project_id == pid))
        out: dict = {}
        if run:
            for c in s.scalars(select(Connectivity).where(Connectivity.project_id == pid, Connectivity.run_no == run)):
                out.setdefault(c.side, {})[c.name] = c.status
        return out

    def assess(self, actor: Actor, pid: int) -> ReadinessRun:
        actor.require("assess")
        with self.session() as s:
            p = self._project(s, pid)
            src, tgt = self._latest_inv(s, pid, "source"), self._latest_inv(s, pid, "target")
            findings = evaluate_compatibility(src, self.cfg["compatibility"]) if src else []
            s.add(CompatRun(project_id=pid, findings=findings))
            res = score_readiness({"src": src, "tgt": tgt, "connectivity": self._conn_latest(s, pid),
                                   "findings": findings, "settings": p.settings}, self.cfg["readiness"])
            run = ReadinessRun(project_id=pid, **res)
            s.add(run)
            p.status = "ASSESSED"
            s.flush()
            audit(s, actor.username, "readiness.assess", pid, score=res["score"], status=res["status"])
            return run

    def gate(self, pid: int) -> dict:
        with self.session() as s:
            return self._gate(s, pid)

    def _valid_approval(self, s, p: Project, subject: str, after=None):
        a = s.scalars(select(Approval).where(Approval.project_id == p.id, Approval.subject == subject)
                      .order_by(Approval.id.desc()).limit(1)).first()
        if not a or a.decision != "APPROVED": return None
        floor = p.settings.get("approval_floor", {}).get(subject)
        if floor and a.created_at.isoformat() < floor: return None
        if after and a.created_at < after: return None
        return a

    def _gate(self, s, pid) -> dict:
        p = self._project(s, pid)
        r = s.scalars(select(ReadinessRun).where(ReadinessRun.project_id == pid).order_by(ReadinessRun.id.desc()).limit(1)).first()
        if not r: return {"allowed": False, "status": None, "reason": "No readiness assessment has been run"}
        if r.status == "GREEN": return {"allowed": True, "status": "GREEN", "reason": "", "score": r.score}
        if r.status == "AMBER":
            ok = self._valid_approval(s, p, "readiness_amber", after=r.created_at)
            return {"allowed": bool(ok), "status": "AMBER", "score": r.score,
                    "reason": "" if ok else "AMBER: remediation must be explicitly accepted by an approver"}
        return {"allowed": False, "status": "RED", "score": r.score, "reason": "RED: " + "; ".join(r.blockers or ["score below threshold"])}

    # ---------- approvals
    def approve(self, actor: Actor, pid: int, subject: str, decision="APPROVED", comment=""):
        actor.require("approve")
        with self.session() as s:
            p = self._project(s, pid)
            if subject.startswith("step:"):
                st = s.scalars(select(Step).where(Step.project_id == pid, Step.key == subject[5:])).first()
                if not st or not st.requires_approval: raise GateError(f"No approvable step '{subject}'")
            elif subject != "readiness_amber":
                raise GateError(f"Unknown approval subject '{subject}'")
            s.add(Approval(project_id=pid, subject=subject, approver=actor.username, decision=decision, comment=comment))
            s.flush()
            audit(s, actor.username, "approval.record", pid, subject=subject, decision=decision, comment=comment)
            self._refresh(s, pid)

    # ---------- plan + state machine
    def generate_plan(self, actor: Actor, pid: int) -> list[Step]:
        actor.require("assess")
        with self.session() as s:
            p = self._project(s, pid)
            g = self._gate(s, pid)
            if not g["allowed"]: raise GateError(f"Plan blocked by readiness gate: {g['reason']}")
            existing = list(s.scalars(select(Step).where(Step.project_id == pid)))
            if any(e.attempts > 0 for e in existing): raise GateError("Plan already executing; cannot regenerate")
            s.execute(delete(Step).where(Step.project_id == pid))
            steps = []
            for i, d in enumerate(self.cfg["migration_patterns"]["patterns"][p.pattern]["steps"], 1):
                st = Step(project_id=pid, seq=i, key=d["key"], name=d["name"], action=d["action"],
                          requires_approval=d.get("requires_approval", False), destructive=d.get("destructive", False),
                          skippable=d.get("skippable", False), retryable=d.get("retryable", True))
                s.add(st); steps.append(st)
            p.status = "PLANNED"
            s.flush(); self._refresh(s, pid)
            audit(s, actor.username, "plan.generate", pid, steps=[x.key for x in steps])
            return steps

    def steps(self, pid: int) -> list[Step]:
        with self.session() as s:
            return list(s.scalars(select(Step).where(Step.project_id == pid).order_by(Step.seq)))

    def _refresh(self, s, pid):
        p = self._project(s, pid)
        active = False
        for st in s.scalars(select(Step).where(Step.project_id == pid).order_by(Step.seq)):
            if st.state in TERMINAL: continue
            if st.state == "FAILED" or active:
                active = True
                if st.state != "FAILED": st.state = "BLOCKED"
                continue
            active = True
            st.state = "AWAITING_APPROVAL" if st.requires_approval and not self._valid_approval(s, p, f"step:{st.key}") else "READY"
        s.flush()

    def _next_step(self, s, pid):
        return s.scalars(select(Step).where(Step.project_id == pid, Step.state.notin_(TERMINAL)).order_by(Step.seq).limit(1)).first()

    def run_next(self, actor: Actor, pid: int) -> Step:
        actor.require("execute")
        with self.session() as s:
            p = self._project(s, pid)
            if p.paused: raise GateError("Execution is paused")
            g = self._gate(s, pid)
            if not g["allowed"]: raise GateError(f"Readiness gate blocks execution: {g['reason']}")
            self._refresh(s, pid)
            st = self._next_step(s, pid)
            if st is None: raise GateError("Plan complete or no plan generated")
            if st.state == "FAILED": raise GateError(f"Step '{st.key}' failed ({st.failure_class}); retry or rerun")
            if st.requires_approval:
                a = self._valid_approval(s, p, f"step:{st.key}")
                if not a: raise GateError(f"Approval required for step '{st.key}'")
                if a.approver == actor.username:
                    raise GateError("Segregation of duties: approver and executor must be different people")
            st.state, st.attempts, st.started_at, st.failure_class = "RUNNING", st.attempts + 1, utcnow(), ""
            p.status = "EXECUTING"
            self._log(s, pid, st.key, f"Started (attempt {st.attempts}) by {actor.username}")
            s.flush()
            try:
                result = self._do(s, p, st, actor)
                st.state, st.message = "COMPLETE", result.get("message", "ok")
                self._evidence(s, pid, st.key, "step_result", result)
                self._log(s, pid, st.key, f"Completed: {st.message}")
            except (ConnectorError, StepFailure) as e:
                st.state, st.failure_class, st.message = "FAILED", e.kind, str(e)
                self._log(s, pid, st.key, f"FAILED [{e.kind}]: {e}", "ERROR")
                self._evidence(s, pid, st.key, "failure", {"kind": e.kind, "message": str(e)})
            except Exception as e:  # noqa: BLE001
                st.state, st.failure_class, st.message = "FAILED", "UNKNOWN", repr(e)
                self._log(s, pid, st.key, f"FAILED [UNKNOWN]: {e!r}", "ERROR")
            st.finished_at = utcnow()
            audit(s, actor.username, "step.run", pid, step=st.key, state=st.state, failure=st.failure_class)
            self._refresh(s, pid)
            allst = list(s.scalars(select(Step).where(Step.project_id == pid)))
            p.status = "COMPLETED" if all(x.state in TERMINAL for x in allst) else ("ATTENTION" if st.state == "FAILED" else "EXECUTING")
            return st

    def run_all(self, actor: Actor, pid: int) -> dict:
        ran, reason = [], "plan complete"
        while True:
            try:
                st = self.run_next(actor, pid)
            except GateError as e:
                reason = str(e); break
            ran.append((st.key, st.state))
            if st.state == "FAILED":
                reason = f"step '{st.key}' failed"; break
        return {"ran": ran, "stopped": reason}

    def _step_for(self, s, pid, key):
        st = s.scalars(select(Step).where(Step.project_id == pid, Step.key == key)).first()
        if not st: raise GateError(f"Unknown step '{key}'")
        return st

    def retry_step(self, actor: Actor, pid: int, key: str):
        actor.require("execute")
        with self.session() as s:
            st = self._step_for(s, pid, key)
            mx = self.cfg["validation"]["max_attempts_per_step"]
            if st.state != "FAILED": raise GateError("Only FAILED steps can be retried")
            if not st.retryable or st.attempts >= mx: raise GateError(f"Step not retryable (attempts {st.attempts}/{mx})")
            st.state = "BLOCKED"
            audit(s, actor.username, "step.retry", pid, step=key)
            self._refresh(s, pid)

    def skip_step(self, actor: Actor, pid: int, key: str, reason: str):
        actor.require("execute")
        with self.session() as s:
            st = self._step_for(s, pid, key)
            if not st.skippable: raise GateError(f"Step '{key}' is not safe to skip")
            st.state, st.message = "SKIPPED", reason
            audit(s, actor.username, "step.skip", pid, step=key, reason=reason)
            self._refresh(s, pid)

    def rerun_from(self, actor: Actor, pid: int, key: str):
        """Reset a step and everything after it (e.g. re-import after a validation failure). Approvals must be re-granted."""
        actor.require("execute")
        with self.session() as s:
            p = self._project(s, pid)
            first = self._step_for(s, pid, key)
            now = utcnow().isoformat()
            floors = dict(p.settings.get("approval_floor", {}))
            for st in s.scalars(select(Step).where(Step.project_id == pid, Step.seq >= first.seq)):
                if st.state in (*TERMINAL, "FAILED"):
                    st.state = "BLOCKED"
                if st.requires_approval: floors[f"step:{st.key}"] = now
            p.settings = {**p.settings, "approval_floor": floors}
            audit(s, actor.username, "step.rerun_from", pid, step=key)
            self._refresh(s, pid)

    def set_paused(self, actor: Actor, pid: int, paused: bool):
        actor.require("execute")
        with self.session() as s:
            self._project(s, pid).paused = paused
            audit(s, actor.username, "execution.pause" if paused else "execution.resume", pid)

    # ---------- step actions
    def _snap(self, p): return p.settings.get("snapshot_name") or f"EPMWB_{p.id}"

    def _do(self, s, p: Project, st: Step, actor: Actor) -> dict:
        a = st.action
        src, tgt = self._connector(p, "source"), self._connector(p, "target")
        if a == "backup_source":
            n = f"{self._snap(p)}_backup"
            return {"message": f"Backup snapshot {n} created", **src.export_snapshot(n)}
        if a == "validate_target":
            r = tgt.check_target_ready()
            if not r.get("application_exists"): raise StepFailure("VALIDATION", "Target application does not exist")
            vol = (self._latest_inv(s, p.id, "source") or {}).get("counts", {}).get("data_intersections", 0)
            cap = r.get("capacity", {}).get("max_intersections", 0)
            if vol > cap: raise StepFailure("VALIDATION", f"Data volume {vol:,} exceeds target capacity {cap:,}")
            return {"message": "Target validated", **r}
        if a == "export_snapshot":
            return {"message": f"Snapshot {self._snap(p)} exported", **src.export_snapshot(self._snap(p))}
        if a == "transfer_snapshot":
            work = Path(self.state_dir) / "transfer" / f"p{p.id}"
            path = src.download_snapshot(self._snap(p), str(work))
            return {"message": "Snapshot transferred", "path": path, **tgt.upload_snapshot(path)}
        if a == "import_snapshot":
            return {"message": "Snapshot imported into target", **tgt.import_snapshot(self._snap(p))}
        if a == "technical_validation": return self._validate(s, p, tgt, "technical")
        if a == "data_reconciliation": return self._validate(s, p, tgt, "business")
        if a == "signoff":
            ap = self._valid_approval(s, p, f"step:{st.key}")
            return {"message": f"Business sign-off by {ap.approver}", "approver": ap.approver}
        raise StepFailure("UNSUPPORTED", f"No handler for action '{a}'")

    def _validate(self, s, p, tgt, category) -> dict:
        v = self.cfg["validation"]
        src_inv = self._latest_inv(s, p.id, "source")
        tgt_inv = tgt.get_inventory()
        s.add(Inventory(project_id=p.id, side="target_post", data=tgt_inv))
        s.execute(delete(ValidationResult).where(ValidationResult.project_id == p.id, ValidationResult.category == category))
        rows = []
        if category == "technical":
            for k, sv in src_inv["counts"].items():
                tv = tgt_inv["counts"].get(k, 0)
                rows.append((k, sv, tv, abs(tv - sv) <= v["count_tolerance_abs"]))
        else:
            for k, sv in src_inv["control_totals"].items():
                tv = tgt_inv["control_totals"].get(k, 0.0)
                tol = max(v["control_total_tolerance_abs"], abs(sv) * v["control_total_tolerance_pct"] / 100)
                rows.append((k, sv, tv, abs(tv - sv) <= tol))
        bad = []
        for k, sv, tv, ok in rows:
            s.add(ValidationResult(project_id=p.id, category=category, check=k, source_value=sv, target_value=tv,
                                   diff=round(tv - sv, 4), status="PASS" if ok else "FAIL"))
            if not ok: bad.append(f"{k} (src {sv:,} vs tgt {tv:,})")
        if bad: raise StepFailure("VALIDATION", f"{len(bad)} {category} mismatch(es): " + "; ".join(bad))
        return {"message": f"{len(rows)} {category} checks passed", "checks": len(rows)}

    # ---------- read helpers (UI / reports)
    def get_project(self, pid): 
        with self.session() as s: return self._project(s, pid)

    def list_projects(self):
        with self.session() as s: return list(s.scalars(select(Project).order_by(Project.id.desc())))

    def _latest(self, model, pid):
        with self.session() as s:
            return s.scalars(select(model).where(model.project_id == pid).order_by(model.id.desc()).limit(1)).first()

    def latest_readiness(self, pid): return self._latest(ReadinessRun, pid)
    def latest_compat(self, pid): return self._latest(CompatRun, pid)

    def rows(self, model, pid, order=None):
        with self.session() as s:
            return list(s.scalars(select(model).where(model.project_id == pid).order_by(order or model.id)))

    def connectivity_latest(self, pid):
        with self.session() as s:
            run = s.scalar(select(func.max(Connectivity.run_no)).where(Connectivity.project_id == pid))
            return list(s.scalars(select(Connectivity).where(Connectivity.project_id == pid, Connectivity.run_no == run))) if run else []

    # ---------- crash recovery
    def recover_interrupted(self, stale_seconds: int = 120) -> list[int]:
        """Fail jobs whose worker stopped heartbeating (process crash/restart) and mark their in-flight steps
        INTERRUPTED. Safe with several API workers: only jobs with a stale heartbeat are touched."""
        from datetime import timedelta
        cutoff = utcnow() - timedelta(seconds=stale_seconds)
        out = []
        with self.session() as s:
            for j in s.scalars(select(Job).where(Job.status.in_(("QUEUED", "RUNNING")), Job.heartbeat_at <= cutoff)):
                j.status, j.error, j.finished_at = "FAILED", "Interrupted: worker stopped (restart/crash)", utcnow()
                for st in s.scalars(select(Step).where(Step.project_id == j.project_id, Step.state == "RUNNING")):
                    st.state, st.failure_class = "FAILED", "INTERRUPTED"
                    st.message = "Interrupted mid-run. Verify target state before retrying (import may be partially applied)."
                    self._log(s, j.project_id, st.key, st.message, "ERROR")
                self._project(s, j.project_id).status = "ATTENTION"
                audit(s, "system", "job.interrupted", j.project_id, job=j.id)
                out.append(j.id)
        return out

    # ---------- demo
    def create_demo(self, actor: Actor, scenario="clean") -> Project:
        src = {"connector": "mock", "profile": "clean" if scenario == "clean" else "issues", "version": "25.09",
               "url": "https://source-test.example.oraclecloud.com"}
        tgt = {"connector": "mock", "profile": "empty_target", "version": "25.10",
               "url": "https://target-test.example.oraclecloud.com"}
        p = self.create_project(actor, f"Demo {scenario} {utcnow():%H:%M:%S}", src, tgt, client="Demo Client",
                                owner=actor.username, planned_date="2026-11-14",
                                settings={"privileged_access_reviewed": True, "backup_plan": True,
                                          "rollback_plan": "Restore pre-migration snapshot on target",
                                          "cutover_window": "Sat 22:00-02:00"})
        self.run_connectivity(actor, p.id); self.collect_inventory(actor, p.id); self.assess(actor, p.id)
        return p
