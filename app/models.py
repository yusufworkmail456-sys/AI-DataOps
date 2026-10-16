"""Models DB — skema design.md. tenant_id di SEMUA tabel (D10, AC-09)."""
import sqlite3
import uuid
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, CheckConstraint, DateTime, Float,
                        ForeignKey, Integer, String, Text, UniqueConstraint,
                        create_engine, event)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def uid() -> str:
    return uuid.uuid4().hex


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TenantMixin:
    """tenant_id wajib di semua tabel ber-data (AC-09, D10)."""
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)


# --- Registry (tanpa tenant: definisi global, read-only untuk tenant) ---

class Integration(Base):
    __tablename__ = "integrations"
    integration_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    service: Mapped[str] = mapped_column(String(64), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(32), nullable=False, default="0.1.0")
    support_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pilot")
    capabilities: Mapped[dict] = mapped_column(JSON, default=dict)   # {discover, observe, evaluate, diagnose, act}
    permissions: Mapped[dict] = mapped_column(JSON, default=dict)    # required permissions + alasan
    limitations: Mapped[str] = mapped_column(Text, default="")


class Control(Base):
    __tablename__ = "controls"
    control_id: Mapped[str] = mapped_column(String(64), primary_key=True)  # RULE-ENG-001 dst
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    domain: Mapped[str] = mapped_column(String(32), nullable=False)   # engineering/dba/security/governance/ops/lineage
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    applicability: Mapped[dict] = mapped_column(JSON, default=dict)   # {provider, service, ...}
    test_method: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(32), nullable=False)  # 7 tipe tervalidasi
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    knowledge_ref: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class User(Base):
    __tablename__ = "users"
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # admin|sre|dba|viewer
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Session(Base):
    __tablename__ = "user_sessions"
    session_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Agent(Base):
    """Agent enrol: agent_key disimpan (hashed) di cloud; creds target TIDAK pernah dikirim balik."""
    __tablename__ = "agents"
    agent_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    agent_key_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    enroll_token: Mapped[str | None] = mapped_column(String(128), nullable=True)  # habis dipakai sekali
    enrolled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


# --- Canonical data (tenant) ---

class Asset(TenantMixin, Base):
    __tablename__ = "assets"
    asset_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    service: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False)
    native_id: Mapped[str] = mapped_column(String(256), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), default="prod")
    owner: Mapped[str] = mapped_column(String(128), default="")
    classification: Mapped[str] = mapped_column(String(32), default="internal")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("tenant_id", "provider", "service", "native_id",
                                       name="uq_asset_native"),)


class EvidenceRecord(TenantMixin, Base):
    __tablename__ = "evidence_records"
    evidence_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    asset_id: Mapped[str] = mapped_column(String(64), ForeignKey("assets.asset_id"), nullable=False, index=True)
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False)  # pg_stat_activity dll
    source_ref: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)  # idempotensi
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    freshness: Mapped[str] = mapped_column(String(16), default="fresh")  # fresh|stale|missing
    access_classification: Mapped[str] = mapped_column(String(32), default="internal")


class AssessmentRun(TenantMixin, Base):
    __tablename__ = "assessment_runs"
    assessment_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    scope: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    engine_version: Mapped[str] = mapped_column(String(32), nullable=False, default="0.1.0")
    policy_set_version: Mapped[str] = mapped_column(String(64), default="pilot-1")


class ControlResult(Base):
    """Control result status (pass/fail/unknown/not_applicable) — TERPISAH dari finding lifecycle."""
    __tablename__ = "control_results"
    result_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    assessment_id: Mapped[str] = mapped_column(String(64), ForeignKey("assessment_runs.assessment_id"), nullable=False, index=True)
    control_id: Mapped[str] = mapped_column(String(64), ForeignKey("controls.control_id"), nullable=False)
    control_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(16), CheckConstraint("status IN ('pass','fail','unknown','not_applicable')"), nullable=False)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    reason: Mapped[str] = mapped_column(Text, default="")
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Finding(TenantMixin, Base):
    """Finding lifecycle TERPISAH dari control result status (FR-09)."""
    __tablename__ = "findings"
    finding_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    asset_id: Mapped[str] = mapped_column(String(64), ForeignKey("assets.asset_id"), nullable=False, index=True)
    control_id: Mapped[str] = mapped_column(String(64), ForeignKey("controls.control_id"), nullable=False)
    control_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    assessment_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), CheckConstraint("status IN ('open','acknowledged','remediating','resolved','accepted_risk')"), nullable=False, default="open")
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    knowledge_refs: Mapped[list] = mapped_column(JSON, default=list)
    reason: Mapped[str] = mapped_column(Text, default="")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Exception_(Base):
    __tablename__ = "exceptions"
    exception_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    finding_id: Mapped[str] = mapped_column(String(64), ForeignKey("findings.finding_id"), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    owner: Mapped[str] = mapped_column(String(128), nullable=False)
    approver: Mapped[str] = mapped_column(String(128), nullable=False)
    expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")


class AuditEvent(Base):
    """Append-only (AC-09/FR-12): tanpa UPDATE/DELETE — diblokir di engine level."""
    __tablename__ = "audit_events"
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target: Mapped[str] = mapped_column(String(256), default="")
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)  # allow|deny|error
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


def _attach_audit_guard(dbapi_conn, _record):
    """Append-only di DB level: sqlite authorizer menolak UPDATE/DELETE audit_events."""
    def _auth(action, arg1, arg2, dbname, source):
        if action in (sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE) and arg1 == "audit_events":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    dbapi_conn.set_authorizer(_auth)


_last_guard = None  # (engine, fn) — untuk melepas guard sementara (mis. test drop_all)


def make_engine(db_url: str):
    global _last_guard
    engine = create_engine(db_url, connect_args={"check_same_thread": False} if db_url.startswith("sqlite") else {})
    if db_url.startswith("sqlite"):
        _last_guard = (engine, _attach_audit_guard)
        event.listen(engine, "connect", _attach_audit_guard)
    return engine


def make_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)
