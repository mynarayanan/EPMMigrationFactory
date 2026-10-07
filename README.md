# Oracle EPM Migration Workbench (v0.2)

Gated, auditable Oracle EPM migrations. **Cloud EPM → Cloud EPM (snapshot)** is implemented end to end.

```
frontend/   React + TypeScript (Vite)         → talks only to the REST API
backend/
  api/        FastAPI: auth, routes, schemas   → thin; no business logic
  core/       domain: state machine, gates, readiness, audit, jobs, reports
  connectors/ mock (fault-injecting), live EPM Automate
  alembic/    schema migrations (owned by Alembic, not create_all)
  config/     YAML rules: readiness, compatibility, patterns, validation
```

## Run locally (simulated EPM, no Oracle needed)
```bash
cd backend && pip install -r requirements.txt
DEV_PASSWORD=choose-one uvicorn api.main:app_factory --factory --port 8000     # migrates SQLite automatically
cd ../frontend && npm install && npm run dev                                   # http://localhost:5173 (proxies /api)
```
Sign in as `olivia` (operator), `alan` / `amy` (approvers), `root` (admin) or `sam` (operator+approver) with `DEV_PASSWORD`.
Click **New demo (clean)** or **(with issues)**.

Single container: `npm run build`, then `STATIC_DIR=../frontend/dist` on the API. See `Dockerfile` / `docker-compose.yml` (PostgreSQL).

## Tests
```bash
cd backend && pytest -q                         # 51 tests: domain, API, auth, OIDC, jobs, recovery, migrations
TEST_PG_URI=postgresql://… pytest -q            # the same suite on PostgreSQL
cd frontend && npm test                         # unit
npm run test:integration                        # real React app ↔ real uvicorn/FastAPI/SQLite, 3 users end to end
```

## Design decisions
- **API first.** All logic is behind FastAPI; the UI is replaceable. Domain code never imports web code.
- **Auth.** `dev` (local users, refused when `APP_ENV=production`, no default password) or `oidc` (RS256/ES256 via JWKS; issuer,
  audience, expiry enforced; `alg=none`/HS256-confusion rejected; roles mapped from a token claim). Roles are never taken from the client.
- **Segregation of duties.** Approver and executor of a step must be different people, even for a combined-role user.
- **Jobs.** Execution is queued in a durable `jobs` table (202 + polling). A partial unique index allows one active job per project
  across any number of API workers. Heartbeats + startup recovery mark crashed work `INTERRUPTED` without touching live workers.
- **Gates are enforced in the domain**, re-checked at every step; failed critical readiness checks force RED regardless of score.
- **Audit.** Hash-chained append-only log; SHA-256 evidence per step; Excel/JSON reports.
- **Secrets.** Only references (env-var name → password-file path). Raw `password` fields are rejected by the API schema.

## Known gaps (read before relying on this)
1. **Never run against a real Oracle EPM instance.** `connectors/epm_automate.py` follows Oracle's documented commands and is tested with a
   fake command runner only. Live **inventory (REST) is not implemented** and raises UNSUPPORTED rather than returning fake data.
2. **OIDC is verified with locally generated keys and a stubbed JWKS, not a real IdP.** The browser UI has **no OIDC login flow**
   (authorization-code + PKCE, e.g. `oidc-client-ts`); SSO deployments need that added. Dev login works.
3. **UI verified in jsdom, not a real browser.** Behaviour is tested end to end; visual layout, responsive behaviour and
   cross-browser rendering have not been looked at.
4. `Dockerfile` / `docker-compose.yml` were written but **not built or run** (no Docker in the build environment).
5. Jobs run on in-process threads (durable state, recoverable). Move to Celery/Arq for horizontal scale.
6. All authenticated users can see all projects (no per-project ACL). Only the `cloud_to_cloud` pattern exists.
   No approved-exception workflow for failed validations yet; failures are retried or rerun.
