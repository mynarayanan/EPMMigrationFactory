"""Durable background job runner. API requests never hold a long EPM operation open: they enqueue a Job row and
return 202; a worker thread executes it and a heartbeat keeps it alive. State lives in the database, so any API
worker can report progress and crash recovery (Workbench.recover_interrupted) is possible.
To scale out, replace ThreadPoolExecutor with Celery/Arq calling JobRunner.execute(job_id, actor)."""
from __future__ import annotations
import threading
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .models import Job, utcnow
from .support import Actor, Conflict, GateError, NotFound, PermissionDenied, audit


class JobRunner:
    def __init__(self, wb, workers: int = 4, heartbeat_seconds: float = 10):
        self.wb, self.hb = wb, heartbeat_seconds
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="epm-job")

    def submit(self, actor: Actor, pid: int, mode: str) -> Job:
        actor.require("execute")
        if mode not in ("next", "all"): raise GateError("mode must be 'next' or 'all'")
        try:
            with self.wb.session() as s:
                self.wb._project(s, pid)
                job = Job(project_id=pid, mode=mode, actor=actor.username)
                s.add(job); s.flush()
                audit(s, actor.username, "job.submit", pid, job=job.id, mode=mode)
        except IntegrityError as e:  # partial unique index: another active job exists
            raise Conflict("An execution job is already queued or running for this project") from e
        self.pool.submit(self.execute, job.id, actor)
        return job

    def _beat(self, job_id: int, stop: threading.Event):
        while not stop.wait(self.hb):
            try:
                with self.wb.session() as s:
                    j = s.get(Job, job_id)
                    if j: j.heartbeat_at = utcnow()
            except Exception:  # noqa: BLE001  heartbeat must never kill the job
                pass

    def execute(self, job_id: int, actor: Actor):
        with self.wb.session() as s:
            j = s.get(Job, job_id)
            if j.status != "QUEUED": return          # already picked up / recovered
            j.status, j.heartbeat_at = "RUNNING", utcnow(); pid, mode = j.project_id, j.mode
        stop = threading.Event()
        threading.Thread(target=self._beat, args=(job_id, stop), daemon=True).start()
        status, result, error = "SUCCEEDED", {}, ""
        try:
            if mode == "next":
                st = self.wb.run_next(actor, pid)
                result = {"ran": [[st.key, st.state]], "stopped": "single step"}
            else:
                result = self.wb.run_all(actor, pid)
                result["ran"] = [list(r) for r in result["ran"]]
                if not result["ran"]:  # nothing executed: a gate rejected the request, report it as such
                    status, error = "FAILED", result["stopped"]
        except (GateError, PermissionDenied) as e:  # rejected by a gate before/while running
            status, error = "FAILED", str(e)
        except Exception as e:  # noqa: BLE001
            status, error = "FAILED", f"Unexpected error: {e!r}"
        finally:
            stop.set()
        with self.wb.session() as s:
            j = s.get(Job, job_id)
            if j.status == "RUNNING":  # not already failed by recovery
                j.status, j.result, j.error, j.finished_at = status, result, error, utcnow()

    def get(self, job_id: int) -> Job:
        with self.wb.session() as s:
            j = s.get(Job, job_id)
            if not j: raise NotFound(f"Job {job_id} not found")
            return j

    def for_project(self, pid: int, limit: int = 20) -> list[Job]:
        with self.wb.session() as s:
            return list(s.scalars(select(Job).where(Job.project_id == pid).order_by(Job.id.desc()).limit(limit)))

    def shutdown(self): self.pool.shutdown(wait=True, cancel_futures=False)
