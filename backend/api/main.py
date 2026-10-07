from __future__ import annotations
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from core.jobs import JobRunner
from core.service import Workbench
from core.support import Conflict, GateError, NotFound, PermissionDenied, load_config, make_engine
from .auth import DevAuth, OidcAuth
from .routes import router
from .settings import Settings

log = logging.getLogger("epm.api")
BACKEND = Path(__file__).resolve().parent.parent


def run_migrations(url: str):
    from alembic import command
    from alembic.config import Config
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(cfg, "head")


def create_app(settings: Settings | None = None, jwks_client=None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.validate()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        url = settings.database_url or f"sqlite:///{BACKEND / 'epm_workbench.db'}"
        if settings.auto_migrate: run_migrations(url)
        engine = make_engine(url)
        app.state.wb = wb = Workbench(engine, load_config(), settings.mock_state_dir)
        app.state.runner = JobRunner(wb, settings.job_workers, settings.heartbeat_seconds)
        recovered = wb.recover_interrupted(settings.stale_seconds)
        if recovered: log.warning("Recovered interrupted jobs: %s", recovered)
        yield
        app.state.runner.shutdown()

    app = FastAPI(title="Oracle EPM Migration Workbench API", version="0.2.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.auth = OidcAuth(settings, jwks_client) if settings.auth_mode == "oidc" else DevAuth(settings)
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["*"], allow_headers=["*"])

    for exc, code in ((NotFound, 404), (Conflict, 409), (GateError, 409), (PermissionDenied, 403)):
        app.add_exception_handler(exc, lambda r, e, c=code: JSONResponse({"detail": str(e)}, status_code=c))
    app.include_router(router)

    @app.get("/healthz")
    def healthz(request: Request):
        from sqlalchemy import text
        with request.app.state.wb.engine.connect() as c: c.execute(text("select 1"))
        return {"status": "ok"}

    static = Path(settings.static_dir) if settings.static_dir else None
    if static and static.is_dir():
        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            f = (static / path).resolve()
            if path and f.is_file() and static.resolve() in f.parents: return FileResponse(f)
            if path.startswith("api/"): return JSONResponse({"detail": "Not found"}, status_code=404)
            return FileResponse(static / "index.html")
    return app


def app_factory() -> FastAPI:  # uvicorn api.main:app_factory --factory
    return create_app()
