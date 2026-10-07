"""Config loading, RBAC, and tamper-evident audit log."""
from __future__ import annotations
import hashlib, json, os
from dataclasses import dataclass
from pathlib import Path
import yaml
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from .models import Base, AuditEntry, utcnow

ROOT = Path(__file__).resolve().parent.parent


def load_config(config_dir: str | Path | None = None) -> dict:
    d = Path(config_dir or ROOT / "config")
    return {p.stem: yaml.safe_load(p.read_text()) for p in d.glob("*.yaml")}


def make_engine(url: str | None = None):
    """Engine only. Schema is owned by Alembic migrations (see init_db for tests/dev)."""
    from sqlalchemy import event
    url = url or os.environ.get("DATABASE_URL", f"sqlite:///{ROOT / 'epm_workbench.db'}")
    if url.startswith("sqlite"):
        eng = create_engine(url, future=True, connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(eng, "connect")
        def _pragmas(conn, _):  # WAL lets the API and background jobs read while a job writes
            cur = conn.cursor(); cur.execute("PRAGMA journal_mode=WAL"); cur.execute("PRAGMA foreign_keys=ON"); cur.close()
    else:
        eng = create_engine(url, future=True, pool_pre_ping=True)
    return eng


def init_db(engine):
    """create_all - tests and throwaway demos only. Real deployments run `alembic upgrade head`."""
    Base.metadata.create_all(engine)


class GateError(Exception):
    """A readiness/approval/state gate blocks the requested action."""


class NotFound(GateError): pass


class Conflict(GateError):
    """Concurrent/duplicate operation (e.g. a job is already running for the project)."""


class PermissionDenied(Exception): pass


PERMISSIONS = {
    "operator": {"create_project", "configure", "assess", "execute", "validate"},
    "approver": {"approve"},
    "admin": {"create_project", "configure", "assess", "execute", "validate", "approve", "admin"},
}


@dataclass(frozen=True)
class Actor:
    username: str
    role: str  # operator | approver | admin, or several joined with '+', e.g. "operator+approver"

    @property
    def roles(self) -> set[str]:
        return {r for r in self.role.split("+") if r}

    def can(self, perm: str) -> bool:
        return any(perm in PERMISSIONS.get(r, set()) for r in self.roles)

    def require(self, perm: str):
        if not self.can(perm):
            raise PermissionDenied(f"Role '{self.role}' ({self.username}) may not '{perm}'")


def _hash(prev: str, payload: dict) -> str:
    return hashlib.sha256((prev + json.dumps(payload, sort_keys=True, default=str)).encode()).hexdigest()


def audit(s: Session, actor: str, action: str, project_id: int | None = None, **details):
    last = s.scalars(select(AuditEntry).order_by(AuditEntry.id.desc()).limit(1)).first()
    prev = last.hash if last else ""
    ts = utcnow()
    e = AuditEntry(ts=ts, actor=actor, action=action, project_id=project_id, details=details, prev_hash=prev)
    e.hash = _hash(prev, {"ts": ts.isoformat(), "actor": actor, "action": action, "project_id": project_id, "details": details})
    s.add(e)
    s.flush()


def verify_audit_chain(s: Session) -> tuple[bool, int | None]:
    prev = ""
    for e in s.scalars(select(AuditEntry).order_by(AuditEntry.id)):
        h = _hash(prev, {"ts": e.ts.isoformat(), "actor": e.actor, "action": e.action,
                         "project_id": e.project_id, "details": e.details})
        if e.prev_hash != prev or e.hash != h:
            return False, e.id
        prev = e.hash
    return True, None
