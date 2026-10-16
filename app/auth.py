"""Auth: session cookie + RBAC sederhana (admin/sre/dba/viewer) + agent key."""
import hashlib
import hmac
import secrets

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select

from .models import Agent, Session, User, make_session_factory

ROLE_RANK = {"viewer": 1, "dba": 2, "sre": 2, "admin": 4}
# permission minimal per aksi tulis; read semua role
WRITE_ROLES = {"admin", "sre", "dba"}


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def hash_password(pw: str) -> str:
    # ponytail: hashlib sha256+salt, add when real auth hardening (argon2/bcrypt) needed
    salt = secrets.token_hex(8)
    return f"{salt}${hashlib.sha256((salt + pw).encode()).hexdigest()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        salt, h = stored.split("$", 1)
    except ValueError:
        return False
    return hmac.compare_digest(hashlib.sha256((salt + pw).encode()).hexdigest(), h)


class AuthContext:
    def __init__(self, user: User | None = None, tenant_id: str = "", role: str = "viewer",
                 actor: str = "anonymous"):
        self.user = user
        self.tenant_id = tenant_id
        self.role = role
        self.actor = actor

    @property
    def can_write(self) -> bool:
        return self.role in WRITE_ROLES

    def require_write(self):
        if not self.can_write:
            raise HTTPException(403, {"error": "role tidak diizinkan", "code": "forbidden"})


def get_auth(request: Request) -> AuthContext:
    factory = request.app.state.db_factory
    sid = request.cookies.get("dataops_session")
    if not sid:
        raise HTTPException(401, {"error": "belum login", "code": "unauthenticated"})
    s = factory()
    try:
        sess = s.get(Session, sid)
        if sess is None:
            raise HTTPException(401, {"error": "session tidak valid", "code": "unauthenticated"})
        user = s.get(User, sess.user_id)
        if user is None or not user.active:
            raise HTTPException(401, {"error": "user tidak aktif", "code": "unauthenticated"})
        return AuthContext(user=user, tenant_id=user.tenant_id, role=user.role,
                           actor=f"user:{user.username}")
    finally:
        s.close()


def get_agent(request: Request) -> tuple[str, Agent]:
    """Auth agent via X-Agent-Key → (tenant_id, Agent). Key salah/absen → 401 dgn code."""
    key = request.headers.get("X-Agent-Key", "")
    if not key:
        raise HTTPException(401, {"error": "X-Agent-Key wajib", "code": "unauthenticated"})
    factory = request.app.state.db_factory
    s = factory()
    try:
        kh = hash_key(key)
        agent = s.execute(select(Agent).where(Agent.agent_key_hash == kh,
                                              Agent.active == True)).scalars().first()  # noqa: E712
        if agent is None:
            raise HTTPException(401, {"error": "agent key tidak valid",
                                      "code": "invalid_agent_key"})
        return agent.tenant_id, agent
    finally:
        s.close()
