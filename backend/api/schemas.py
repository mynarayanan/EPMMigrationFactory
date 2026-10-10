from __future__ import annotations
from datetime import datetime
import re
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EnvConfig(BaseModel):
    """Environment reference. Raw passwords are not accepted anywhere: live connectors take only a *name* of an
    environment variable that holds a path to an EPM Automate encrypted password file."""
    model_config = ConfigDict(extra="forbid")
    connector: Literal["mock", "live"] = "mock"
    url: str = ""
    version: str = ""
    profile: Literal["clean", "issues", "empty_target"] | None = None
    user: str = ""
    identity_domain: str = ""
    password_file_env: str = ""
    faults: dict[str, Any] = Field(default_factory=dict)

    @field_validator("profile", mode="before")
    @classmethod
    def _blank_profile_is_none(cls, v):
        return None if v in ("", None) else v

    @model_validator(mode="after")
    def _live(self):
        if self.connector == "live":
            if not (self.url.startswith("https://") and self.user and self.password_file_env):
                raise ValueError("live connector requires https url, user and password_file_env")
            if self.faults or self.profile:
                raise ValueError("faults/profile are only for the simulated connector")
            # Only EPM_* names: a user must not be able to point the connector at DATABASE_URL, JWT_SECRET, etc.
            if not re.fullmatch(r"EPM_[A-Z0-9_]{1,60}", self.password_file_env):
                raise ValueError("password_file_env must be an environment variable name like EPM_SOURCE_PWF (EPM_ prefix, A-Z 0-9 _)")
            if not re.fullmatch(r"[A-Za-z0-9._@\-]{1,100}", self.user):
                raise ValueError("user contains unsupported characters")
            if self.identity_domain and not re.fullmatch(r"[A-Za-z0-9._\-]{1,100}", self.identity_domain):
                raise ValueError("identity_domain contains unsupported characters")
        return self


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    client: str = ""
    owner: str = ""
    planned_date: str = ""
    pattern: str = "cloud_to_cloud"
    source: EnvConfig
    target: EnvConfig
    settings: "SettingsPatch" = Field(default_factory=lambda: SettingsPatch())


class DemoRequest(BaseModel):
    scenario: Literal["clean", "issues"] = "clean"


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    privileged_access_reviewed: bool | None = None
    backup_plan: bool | None = None
    remediation_approved: bool | None = None
    rollback_plan: str | None = None
    cutover_window: str | None = None
    data_scope: Literal["full", "incremental", "current_year", "actuals_only", "historical"] | None = None


class ApprovalIn(BaseModel):
    subject: str
    decision: Literal["APPROVED", "REJECTED"] = "APPROVED"
    comment: str = ""


class ExecuteIn(BaseModel):
    mode: Literal["next", "all"] = "all"


class RerunIn(BaseModel):
    from_step: str


class LoginIn(BaseModel):
    username: str
    password: str


class Orm(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProjectOut(Orm):
    id: int; name: str; client: str; pattern: str; owner: str; planned_date: str; status: str
    paused: bool; created_by: str; created_at: datetime
    source: dict; target: dict; settings: dict


class StepOut(Orm):
    seq: int; key: str; name: str; state: str; requires_approval: bool; destructive: bool; skippable: bool
    retryable: bool; attempts: int; failure_class: str; message: str
    started_at: datetime | None = None; finished_at: datetime | None = None


class JobOut(Orm):
    id: int; project_id: int; mode: str; status: str; actor: str; result: dict; error: str
    created_at: datetime; finished_at: datetime | None = None


ProjectCreate.model_rebuild()
