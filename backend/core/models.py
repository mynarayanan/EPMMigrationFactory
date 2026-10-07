from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Float, Text, DateTime, JSON, Boolean, Index, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow(): return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase): pass


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    client: Mapped[str] = mapped_column(String(200), default="")
    pattern: Mapped[str] = mapped_column(String(50), default="cloud_to_cloud")
    owner: Mapped[str] = mapped_column(String(100), default="")
    planned_date: Mapped[str] = mapped_column(String(30), default="")
    status: Mapped[str] = mapped_column(String(30), default="DRAFT")
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[dict] = mapped_column(JSON, default=dict)
    target: Mapped[dict] = mapped_column(JSON, default=dict)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Inventory(Base):
    __tablename__ = "inventories"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    side: Mapped[str] = mapped_column(String(20))  # source | target | target_post
    data: Mapped[dict] = mapped_column(JSON)
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Connectivity(Base):
    __tablename__ = "connectivity"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    run_no: Mapped[int] = mapped_column(Integer)
    side: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(10))
    detail: Mapped[str] = mapped_column(Text, default="")
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CompatRun(Base):
    __tablename__ = "compat_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    findings: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ReadinessRun(Base):
    __tablename__ = "readiness_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    score: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(10))
    categories: Mapped[dict] = mapped_column(JSON)
    blockers: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Step(Base):
    __tablename__ = "migration_steps"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    seq: Mapped[int] = mapped_column(Integer)
    key: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(50))
    state: Mapped[str] = mapped_column(String(20), default="BLOCKED")
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    destructive: Mapped[bool] = mapped_column(Boolean, default=False)
    skippable: Mapped[bool] = mapped_column(Boolean, default=False)
    retryable: Mapped[bool] = mapped_column(Boolean, default=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    failure_class: Mapped[str] = mapped_column(String(30), default="")
    message: Mapped[str] = mapped_column(Text, default="")


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    subject: Mapped[str] = mapped_column(String(80))  # readiness_amber | step:<key>
    approver: Mapped[str] = mapped_column(String(100))
    decision: Mapped[str] = mapped_column(String(10))  # APPROVED | REJECTED
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RunLog(Base):
    __tablename__ = "migration_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    step_key: Mapped[str] = mapped_column(String(50), default="")
    level: Mapped[str] = mapped_column(String(10), default="INFO")
    message: Mapped[str] = mapped_column(Text)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    step_key: Mapped[str] = mapped_column(String(50))
    kind: Mapped[str] = mapped_column(String(50))
    content: Mapped[dict] = mapped_column(JSON)
    sha256: Mapped[str] = mapped_column(String(64))
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ValidationResult(Base):
    __tablename__ = "validation_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    category: Mapped[str] = mapped_column(String(20))  # technical | business
    check: Mapped[str] = mapped_column(String(100))
    source_value: Mapped[float] = mapped_column(Float)
    target_value: Mapped[float] = mapped_column(Float)
    diff: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(10))
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditEntry(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    actor: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(80))
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64), default="")
    hash: Mapped[str] = mapped_column(String(64), default="")


class Job(Base):
    """Durable background execution record. One active job per project, enforced by a partial unique index
    so it holds across multiple API workers."""
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    mode: Mapped[str] = mapped_column(String(10))  # next | all
    status: Mapped[str] = mapped_column(String(12), default="QUEUED")  # QUEUED RUNNING SUCCEEDED FAILED
    actor: Mapped[str] = mapped_column(String(100))
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    __table_args__ = (Index("uq_job_active_per_project", "project_id", unique=True,
                            sqlite_where=text("status IN ('QUEUED','RUNNING')"),
                            postgresql_where=text("status IN ('QUEUED','RUNNING')")),)
