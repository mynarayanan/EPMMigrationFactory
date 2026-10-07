from __future__ import annotations
import os, secrets
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    env: str = "development"                    # development | production
    auth_mode: str = "dev"                      # dev | oidc
    database_url: str = ""
    mock_state_dir: str = ".mock_state"
    cors_origins: tuple = ()
    static_dir: str = ""
    enable_demo: bool = True
    job_workers: int = 4
    heartbeat_seconds: float = 10
    stale_seconds: int = 120
    auto_migrate: bool = True
    # dev auth
    jwt_secret: str = field(default_factory=lambda: secrets.token_urlsafe(32), repr=False)
    jwt_ttl_minutes: int = 60
    dev_password: str = field(default="", repr=False)
    # oidc
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    oidc_user_claim: str = "preferred_username"
    oidc_role_claim: str = "roles"
    oidc_role_map: tuple = (("epm-operator", "operator"), ("epm-approver", "approver"), ("epm-admin", "admin"))

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.environ.get
        prod = e("APP_ENV", "development") == "production"
        rm = e("OIDC_ROLE_MAP")
        kw = dict(
            env="production" if prod else "development", auth_mode=e("AUTH_MODE", "oidc" if prod else "dev"),
            database_url=e("DATABASE_URL", ""), mock_state_dir=e("EPM_MOCK_STATE_DIR", ".mock_state"),
            cors_origins=tuple(x for x in e("CORS_ORIGINS", "").split(",") if x), static_dir=e("STATIC_DIR", ""),
            enable_demo=e("ENABLE_DEMO", "false" if prod else "true").lower() == "true",
            job_workers=int(e("JOB_WORKERS", "4")), stale_seconds=int(e("JOB_STALE_SECONDS", "120")),
            auto_migrate=e("AUTO_MIGRATE", "false" if prod else "true").lower() == "true",
            dev_password=e("DEV_PASSWORD", ""), oidc_issuer=e("OIDC_ISSUER", ""), oidc_audience=e("OIDC_AUDIENCE", ""),
            oidc_jwks_url=e("OIDC_JWKS_URL", ""), oidc_user_claim=e("OIDC_USER_CLAIM", "preferred_username"),
            oidc_role_claim=e("OIDC_ROLE_CLAIM", "roles"))
        if e("JWT_SECRET"): kw["jwt_secret"] = e("JWT_SECRET")
        if rm: kw["oidc_role_map"] = tuple(tuple(p.split(":", 1)) for p in rm.split(","))
        return cls(**kw)

    def validate(self):
        if self.env == "production" and self.auth_mode == "dev":
            raise RuntimeError("Refusing to start: AUTH_MODE=dev is not allowed when APP_ENV=production")
        if self.auth_mode == "oidc" and not (self.oidc_issuer and self.oidc_audience and self.oidc_jwks_url):
            raise RuntimeError("AUTH_MODE=oidc requires OIDC_ISSUER, OIDC_AUDIENCE and OIDC_JWKS_URL")
        if self.auth_mode == "dev" and not self.dev_password:
            raise RuntimeError("AUTH_MODE=dev requires DEV_PASSWORD to be set explicitly (no default credentials)")
