import time, pytest
from fastapi.testclient import TestClient
from api.main import create_app
from api.settings import Settings

PW = "test-password"


def settings(tmp_path, **kw):
    from conftest import new_db_url
    return Settings(database_url=new_db_url(tmp_path, "api.db"), mock_state_dir=str(tmp_path / "mock"),
                    dev_password=PW, heartbeat_seconds=0.2, jwt_secret="x" * 32, **kw)


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as c:
        yield c


def login(c, user):
    r = c.post("/api/auth/login", json={"username": user, "password": PW})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def H(client):
    return {u: login(client, u) for u in ("olivia", "alan", "amy", "root", "sam")}


def wait_job(c, jid, h, timeout=20):
    t = time.time()
    while time.time() - t < timeout:
        j = c.get(f"/api/jobs/{jid}", headers=h).json()
        if j["status"] in ("SUCCEEDED", "FAILED"): return j
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def demo(c, h, scenario="clean"):
    r = c.post("/api/projects/demo", json={"scenario": scenario}, headers=h["olivia"])
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---------- auth
def test_health_and_unauthenticated(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/api/projects").status_code == 401
    assert client.get("/api/projects", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_login_rejects_bad_password(client):
    assert client.post("/api/auth/login", json={"username": "olivia", "password": "nope"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "mallory", "password": PW}).status_code == 401


def test_me_reports_roles_and_capabilities(client, H):
    me = client.get("/api/me", headers=H["alan"]).json()
    assert me["roles"] == ["approver"] and me["can"]["approve"] and not me["can"]["execute"]
    sam = client.get("/api/me", headers=H["sam"]).json()
    assert sam["roles"] == ["approver", "operator"] and sam["can"]["approve"] and sam["can"]["execute"]


def test_expired_and_tampered_tokens_rejected(client, tmp_path):
    import jwt, time as t
    expired = jwt.encode({"sub": "olivia", "roles": ["operator"], "iss": "epm-workbench-dev", "exp": int(t.time()) - 5}, "x" * 32, "HS256")
    assert client.get("/api/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    forged = jwt.encode({"sub": "olivia", "roles": ["admin"], "iss": "epm-workbench-dev", "exp": int(t.time()) + 99}, "wrong-secret-wrong-secret-wrong!", "HS256")
    assert client.get("/api/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_startup_refuses_unsafe_configs(tmp_path):
    with pytest.raises(RuntimeError, match="not allowed"): create_app(Settings(env="production", auth_mode="dev", dev_password="x"))
    with pytest.raises(RuntimeError, match="DEV_PASSWORD"): create_app(Settings(auth_mode="dev", dev_password=""))
    with pytest.raises(RuntimeError, match="OIDC_ISSUER"): create_app(Settings(auth_mode="oidc"))


# ---------- OIDC
@pytest.fixture
def oidc(tmp_path):
    import jwt as pyjwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class FakeJwks:
        def get_signing_key_from_jwt(self, token):
            class K: pass
            k = K(); k.key = key.public_key(); return k

    s = Settings(auth_mode="oidc", oidc_issuer="https://idp.example", oidc_audience="epm-workbench",
                 oidc_jwks_url="https://idp.example/jwks", database_url=__import__("conftest").new_db_url(tmp_path, "o.db"),
                 mock_state_dir=str(tmp_path / "m"), enable_demo=True)
    def tok(**over):
        now = int(time.time())
        c = {"iss": "https://idp.example", "aud": "epm-workbench", "exp": now + 300, "preferred_username": "dana",
             "roles": ["epm-operator"], **over}
        return pyjwt.encode({k: v for k, v in c.items() if v is not None}, key, algorithm="RS256")
    with TestClient(create_app(s, FakeJwks())) as c:
        yield c, tok, key


def bearer(t): return {"Authorization": f"Bearer {t}"}


def test_oidc_valid_token_and_role_mapping(oidc):
    c, tok, _ = oidc
    assert c.post("/api/auth/login", json={"username": "a", "password": "b"}).status_code == 404  # no local login in oidc mode
    me = c.get("/api/me", headers=bearer(tok())).json()
    assert me["username"] == "dana" and me["roles"] == ["operator"]
    both = c.get("/api/me", headers=bearer(tok(roles=["epm-operator", "epm-approver", "unrelated"]))).json()
    assert both["roles"] == ["approver", "operator"]


@pytest.mark.parametrize("over", [{"exp": 1}, {"aud": "other-app"}, {"iss": "https://evil.example"}, {"exp": None}])
def test_oidc_rejects_bad_claims(oidc, over):
    c, tok, _ = oidc
    assert c.get("/api/me", headers=bearer(tok(**over))).status_code == 401


def test_oidc_no_role_is_forbidden(oidc):
    c, tok, _ = oidc
    assert c.get("/api/me", headers=bearer(tok(roles=["random-group"]))).status_code == 403
    assert c.get("/api/me", headers=bearer(tok(roles=None))).status_code == 403


def test_oidc_rejects_alg_none_and_hs256_confusion(oidc):
    import jwt as pyjwt, base64, json
    c, tok, key = oidc
    pub = key.public_key().public_bytes(__import__("cryptography").hazmat.primitives.serialization.Encoding.PEM,
                                        __import__("cryptography").hazmat.primitives.serialization.PublicFormat.SubjectPublicKeyInfo)
    now = int(time.time()); claims = {"iss": "https://idp.example", "aud": "epm-workbench", "exp": now + 300, "roles": ["epm-admin"], "sub": "x"}
    b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    none_tok = f"{b({'alg': 'none', 'typ': 'JWT'})}.{b(claims)}."
    assert c.get("/api/me", headers=bearer(none_tok)).status_code == 401
    try:  # classic algorithm-confusion attempt: HS256 signed with the public key
        hs = pyjwt.encode(claims, pub, algorithm="HS256")
    except Exception:
        hs = None  # PyJWT itself refuses; nothing to send
    if hs: assert c.get("/api/me", headers=bearer(hs)).status_code == 401


# ---------- end-to-end over HTTP
def test_full_migration_over_http(client, H):
    pid = demo(client, H)
    p = client.get(f"/api/projects/{pid}", headers=H["olivia"]).json()
    assert p["gate"]["allowed"] and p["readiness"]["status"] == "GREEN"
    assert [x["state"] for x in p["lifecycle"][:2]] == ["DONE", "DONE"]
    assert len(client.post(f"/api/projects/{pid}/plan", headers=H["olivia"]).json()) == 8

    r = client.post(f"/api/projects/{pid}/execute", json={"mode": "all"}, headers=H["olivia"])
    assert r.status_code == 202
    j = wait_job(client, r.json()["id"], H["olivia"])
    assert j["status"] == "SUCCEEDED" and len(j["result"]["ran"]) == 4 and "Approval required" in j["result"]["stopped"]

    # approver cannot run; operator cannot approve
    assert client.post(f"/api/projects/{pid}/execute", json={}, headers=H["alan"]).status_code == 403
    assert client.post(f"/api/projects/{pid}/approvals", json={"subject": "step:import_snapshot"}, headers=H["olivia"]).status_code == 403
    assert client.post(f"/api/projects/{pid}/approvals", json={"subject": "step:import_snapshot"}, headers=H["alan"]).status_code == 201

    j = wait_job(client, client.post(f"/api/projects/{pid}/execute", json={}, headers=H["olivia"]).json()["id"], H["olivia"])
    assert [k for k, _ in j["result"]["ran"]] == ["import_snapshot", "technical_validation", "data_reconciliation"]
    client.post(f"/api/projects/{pid}/approvals", json={"subject": "step:business_signoff", "comment": "ok"}, headers=H["amy"])
    wait_job(client, client.post(f"/api/projects/{pid}/execute", json={}, headers=H["olivia"]).json()["id"], H["olivia"])

    steps = client.get(f"/api/projects/{pid}/steps", headers=H["olivia"]).json()
    assert all(s["state"] == "COMPLETE" for s in steps)
    assert all(v["status"] == "PASS" for v in client.get(f"/api/projects/{pid}/validation", headers=H["olivia"]).json())
    assert all(x["state"] == "DONE" for x in client.get(f"/api/projects/{pid}", headers=H["olivia"]).json()["lifecycle"])
    a = client.get(f"/api/projects/{pid}/audit", headers=H["olivia"]).json()
    assert a["chain_intact"] and any(e["action"] == "job.submit" for e in a["entries"])
    x = client.get(f"/api/projects/{pid}/report.xlsx", headers=H["olivia"])
    assert x.status_code == 200 and x.content[:2] == b"PK"
    assert client.get(f"/api/projects/{pid}/report.json", headers=H["olivia"]).json()["audit_chain_intact"]
    assert client.get(f"/api/projects/{pid}/report.pdf", headers=H["olivia"]).status_code == 404


def test_self_approval_blocked_for_combined_role_user(client, H):
    pid = demo(client, H)
    client.post(f"/api/projects/{pid}/plan", headers=H["sam"])
    wait_job(client, client.post(f"/api/projects/{pid}/execute", json={}, headers=H["sam"]).json()["id"], H["sam"])
    client.post(f"/api/projects/{pid}/approvals", json={"subject": "step:import_snapshot"}, headers=H["sam"])
    j = wait_job(client, client.post(f"/api/projects/{pid}/execute", json={"mode": "next"}, headers=H["sam"]).json()["id"], H["sam"])
    assert j["status"] == "FAILED" and "Segregation" in j["error"]


def test_red_project_cannot_plan_or_execute(client, H):
    pid = demo(client, H, "issues")
    assert client.get(f"/api/projects/{pid}", headers=H["olivia"]).json()["readiness"]["status"] == "RED"
    r = client.post(f"/api/projects/{pid}/plan", headers=H["olivia"])
    assert r.status_code == 409 and "readiness gate" in r.json()["detail"]
    j = wait_job(client, client.post(f"/api/projects/{pid}/execute", json={}, headers=H["olivia"]).json()["id"], H["olivia"])
    assert j["status"] == "FAILED" and "blocks execution" in j["error"]


def test_concurrent_execution_rejected_by_db_constraint(client, H):
    from core.models import Job
    pid = demo(client, H); client.post(f"/api/projects/{pid}/plan", headers=H["olivia"])
    with client.app.state.wb.session() as s:
        s.add(Job(project_id=pid, mode="all", actor="x", status="RUNNING"))
    r = client.post(f"/api/projects/{pid}/execute", json={}, headers=H["olivia"])
    assert r.status_code == 409 and "already" in r.json()["detail"]


def test_crash_recovery_marks_interrupted_but_spares_live_jobs(client, H):
    from datetime import timedelta
    from core.models import Job, Step, utcnow
    pid, pid2 = demo(client, H), demo(client, H)
    for p in (pid, pid2): client.post(f"/api/projects/{p}/plan", headers=H["olivia"])
    with client.app.state.wb.session() as s:
        s.add(Job(project_id=pid, mode="all", actor="x", status="RUNNING", heartbeat_at=utcnow() - timedelta(minutes=10)))
        s.add(Job(project_id=pid2, mode="all", actor="x", status="RUNNING", heartbeat_at=utcnow()))
        s.query(Step).filter_by(project_id=pid, seq=1).one().state = "RUNNING"
        s.query(Step).filter_by(project_id=pid2, seq=1).one().state = "RUNNING"
    assert len(client.app.state.wb.recover_interrupted(60)) == 1
    s1 = client.get(f"/api/projects/{pid}/steps", headers=H["olivia"]).json()[0]
    s2 = client.get(f"/api/projects/{pid2}/steps", headers=H["olivia"]).json()[0]
    assert s1["state"] == "FAILED" and s1["failure_class"] == "INTERRUPTED"
    assert s2["state"] == "RUNNING"          # healthy worker's job untouched
    client.post(f"/api/projects/{pid}/steps/backup_source/retry", headers=H["olivia"])  # operator can recover
    assert client.get(f"/api/projects/{pid}/steps", headers=H["olivia"]).json()[0]["state"] == "READY"


# ---------- input validation / errors
def test_input_validation(client, H):
    base = {"name": "x", "source": {"connector": "mock", "profile": "clean"}, "target": {"connector": "mock", "profile": "empty_target"}}
    assert client.post("/api/projects", json=base, headers=H["olivia"]).status_code == 201
    pw = {**base, "source": {"connector": "live", "url": "https://x.com", "user": "u", "password": "hunter2"}}
    assert client.post("/api/projects", json=pw, headers=H["olivia"]).status_code == 422       # raw passwords not accepted
    live = {**base, "source": {"connector": "live", "url": "http://insecure", "user": "u", "password_file_env": "E"}}
    assert client.post("/api/projects", json=live, headers=H["olivia"]).status_code == 422     # https required
    assert client.post("/api/projects", json=base, headers=H["alan"]).status_code == 403
    assert client.patch("/api/projects/1/settings", json={"bogus": 1}, headers=H["olivia"]).status_code == 422
    assert client.get("/api/projects/999", headers=H["olivia"]).status_code == 404
    assert client.get("/api/jobs/999", headers=H["olivia"]).status_code == 404


def test_settings_patch_reassess_flow(client, H):
    pid = demo(client, H)
    client.patch(f"/api/projects/{pid}/settings", json={"rollback_plan": ""}, headers=H["olivia"])
    r = client.post(f"/api/projects/{pid}/assess", headers=H["olivia"]).json()
    assert r["categories"]["cutover"]["score"] < 100 and r["status"] == "GREEN"
    assert "approval_floor" not in client.get(f"/api/projects/{pid}", headers=H["olivia"]).json()["project"]["settings"]


def test_demo_can_be_disabled(tmp_path):
    with TestClient(create_app(settings(tmp_path, enable_demo=False))) as c:
        h = login(c, "olivia")
        assert c.post("/api/projects/demo", json={}, headers=h).status_code == 404
        assert c.get("/api/config").json()["demo_enabled"] is False


# ---------- migrations
def test_alembic_schema_matches_models(tmp_path):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine
    from api.main import run_migrations
    from core.models import Base
    from conftest import new_db_url
    url = new_db_url(tmp_path, "mig.db")
    run_migrations(url)
    with create_engine(url).connect() as conn:
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []


def test_spa_static_serving(tmp_path):
    (tmp_path / "dist").mkdir(); (tmp_path / "dist" / "index.html").write_text("<html>app</html>")
    (tmp_path / "dist" / "a.js").write_text("x=1"); (tmp_path / "secret.txt").write_text("nope")
    with TestClient(create_app(settings(tmp_path, static_dir=str(tmp_path / "dist")))) as c:
        assert c.get("/projects/3").text == "<html>app</html>"
        assert c.get("/a.js").text == "x=1"
        assert "nope" not in c.get("/../secret.txt").text and "nope" not in c.get("/%2e%2e/secret.txt").text
        assert c.get("/api/nothing").status_code in (401, 404)
