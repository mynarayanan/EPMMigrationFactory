"""Authentication. Two modes behind one interface:
  dev  - local users, HS256 tokens issued by /api/auth/login (development only; refused in production)
  oidc - validates RS256/ES256 access tokens from an enterprise IdP via JWKS (issuer, audience, expiry enforced)
Roles come from the token (OIDC role claim mapped to operator/approver/admin); the API never trusts client-sent roles."""
from __future__ import annotations
import hmac, time
import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from core.support import Actor
from .settings import Settings

DEV_USERS = {"olivia": "operator", "alan": "approver", "amy": "approver", "root": "admin",
             "sam": "operator+approver"}  # sam shows the combined-role case; segregation still blocks self-approval
bearer = HTTPBearer(auto_error=False)


def unauthorized(msg="Invalid or missing credentials"):
    return HTTPException(401, msg, headers={"WWW-Authenticate": "Bearer"})


class DevAuth:
    def __init__(self, s: Settings): self.s = s

    def login(self, username: str, password: str) -> str:
        ok = username in DEV_USERS and hmac.compare_digest(password.encode(), self.s.dev_password.encode())
        if not ok: raise unauthorized("Invalid username or password")
        now = int(time.time())
        return jwt.encode({"sub": username, "roles": DEV_USERS[username].split("+"), "iat": now,
                           "exp": now + self.s.jwt_ttl_minutes * 60, "iss": "epm-workbench-dev"},
                          self.s.jwt_secret, algorithm="HS256")

    def verify(self, token: str) -> Actor:
        try:
            c = jwt.decode(token, self.s.jwt_secret, algorithms=["HS256"], issuer="epm-workbench-dev",
                           options={"require": ["exp", "sub"]})
        except jwt.PyJWTError as e:
            raise unauthorized(f"Invalid token: {e}") from e
        return Actor(c["sub"], "+".join(c.get("roles", [])))


class OidcAuth:
    def __init__(self, s: Settings, jwks_client=None):
        self.s = s
        self.jwks = jwks_client or jwt.PyJWKClient(s.oidc_jwks_url, cache_keys=True)
        self.role_map = dict(s.oidc_role_map)

    def verify(self, token: str) -> Actor:
        try:
            key = self.jwks.get_signing_key_from_jwt(token).key
            c = jwt.decode(token, key, algorithms=["RS256", "ES256"], audience=self.s.oidc_audience,
                           issuer=self.s.oidc_issuer, options={"require": ["exp", "iss", "aud"]})
        except jwt.PyJWTError as e:
            raise unauthorized(f"Invalid token: {e}") from e
        user = c.get(self.s.oidc_user_claim) or c.get("sub")
        claim = c.get(self.s.oidc_role_claim, [])
        claim = [claim] if isinstance(claim, str) else claim
        roles = sorted({self.role_map[r] for r in claim if r in self.role_map})
        if not user or not roles:
            raise HTTPException(403, "Authenticated, but no EPM Workbench role is assigned to this identity")
        return Actor(user, "+".join(roles))


def get_actor(request: Request, cred: HTTPAuthorizationCredentials | None = Depends(bearer)) -> Actor:
    if cred is None: raise unauthorized()
    return request.app.state.auth.verify(cred.credentials)
