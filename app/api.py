"""FastAPI backend — AI DataOps Intelligence P0. Port 9150 (D8), dashboard di /dataops/."""
import json
import logging
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select

from . import rule_engine, service
from .auth import (AuthContext, ROLE_RANK, get_agent, get_auth, hash_key,
                   hash_password, verify_password)
from .models import (Agent, AssessmentRun, Asset, AuditEvent, Control,
                     ControlResult, EvidenceRecord, Finding, Integration,
                     Session, User, make_engine, make_session_factory)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dataops.api")

DB_PATH = os.environ.get("DATAOPS_DB", "data/dataops.db")
DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard"

app = FastAPI(title="AI DataOps Intelligence", version="0.1.0")

_engine = None


def init(db_path: str | None = None):
    global _engine
    db_path = db_path or DB_PATH
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    _engine = make_engine(f"sqlite:///{db_path}")
    from .models import Base
    Base.metadata.create_all(_engine)
    app.state.db_factory = make_session_factory(_engine)
    app.state.enroll_tokens = {}  # token → tenant_id (dibuat admin)


init()
DEFAULT_TENANT = os.environ.get("DATAOPS_TENANT", "tenant-alpha")


def get_db():
    s = app.state.db_factory()
    try:
        yield s
    finally:
        s.close()


class EnrollBody(BaseModel):
    enroll_token: str
    agent_name: str = "agent"


class DiscoveryItem(BaseModel):
    provider: str
    service: str
    asset_type: str
    native_id: str
    environment: str = "prod"
    owner: str = ""
    classification: str = "internal"
    observed_at: str | None = None
    meta: dict = Field(default_factory=dict)


class DiscoveryBody(BaseModel):
    assets: list[DiscoveryItem]


class EvidenceItem(BaseModel):
    asset_native_id: str
    evidence_type: str
    source_ref: str
    collected_at: str | None = None
    payload: dict = Field(default_factory=dict)
    freshness: str = "fresh"
    access_classification: str = "internal"


class EvidenceBody(BaseModel):
    evidence: list[EvidenceItem]


class LoginBody(BaseModel):
    username: str
    password: str


def err(status: int, message: str, code: str):
    return JSONResponse(status_code=status, content={"error": message, "code": code})


@app.exception_handler(HTTPException)
async def http_exc_handler(request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc.detail)}
    return JSONResponse(status_code=exc.status_code,
                        content={"error": detail.get("error", str(exc.detail)),
                                 "code": detail.get("code", "error")})


# --- Health & dashboard ---

@app.get("/health")
def health():
    return {"status": "ok", "service": "dataops-backend", "version": "0.1.0"}


@app.get("/dataops/")
def dashboard_index():
    return FileResponse(DASHBOARD_DIR / "index.html")


app.mount("/dataops", StaticFiles(directory=str(DASHBOARD_DIR), html=True), name="dashboard")


# --- Web auth (session cookie + RBAC) ---

@app.post("/auth/login")
def login(body: LoginBody, s=Depends(get_db)):
    user = s.execute(select(User).where(User.username == body.username)).scalars().first()
    if user is None or not user.active or not verify_password(body.password, user.password_hash):
        service.audit(s, "", body.username, "auth.login", outcome="deny")
        s.commit()
        return err(401, "kredensial salah", "invalid_credentials")
    sess = Session(user_id=user.user_id, tenant_id=user.tenant_id)
    s.add(sess)
    s.commit()
    resp = JSONResponse({"ok": True, "username": user.username, "role": user.role,
                         "tenant_id": user.tenant_id})
    resp.set_cookie("dataops_session", sess.session_id, httponly=True, samesite="lax")
    return resp


@app.post("/auth/logout")
def logout(request: Request, s=Depends(get_db)):
    sid = request.cookies.get("dataops_session", "")
    if sid:
        obj = s.get(Session, sid)
        if obj:
            s.delete(obj)
            s.commit()
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("dataops_session")
    return resp


@app.post("/admin/enroll-token")
def create_enroll_token(auth: AuthContext = Depends(get_auth), s=Depends(get_db)):
    """Admin buat token enrol agent (sekali pakai)."""
    auth.require_write()
    if auth.role != "admin":
        return err(403, "hanya admin", "forbidden")
    token = secrets.token_urlsafe(24)
    app.state.enroll_tokens[token] = auth.tenant_id
    service.audit(s, auth.tenant_id, auth.actor, "agent.enroll_token.created", outcome="allow")
    s.commit()
    return {"enroll_token": token, "tenant_id": auth.tenant_id}


# --- Ingest API (kontrak design.md, auth X-Agent-Key) ---

@app.post("/ingest/enroll")
def ingest_enroll(body: EnrollBody, s=Depends(get_db)):
    """Enrol agent via token → agent_key (sekali). Token habis setelah dipakai."""
    tenant_id = app.state.enroll_tokens.get(body.enroll_token)
    if tenant_id is None:
        return err(401, "enroll token tidak valid / sudah dipakai", "invalid_enroll_token")
    agent_key = secrets.token_urlsafe(32)
    agent = Agent(tenant_id=tenant_id, name=body.agent_name,
                  agent_key_hash=hash_key(agent_key), enroll_token=None,
                  enrolled_at=datetime.now(timezone.utc))
    s.add(agent)
    del app.state.enroll_tokens[body.enroll_token]
    service.audit(s, tenant_id, f"agent:{body.agent_name}", "agent.enrolled", outcome="allow")
    s.commit()
    # agent_key dikirim SEKALI saat enrol; tidak pernah bisa ditarik lagi
    return {"agent_key": agent_key, "agent_id": agent.agent_id, "tenant_id": tenant_id}


@app.post("/ingest/discovery")
def ingest_discovery(body: DiscoveryBody, request: Request, s=Depends(get_db)):
    try:
        tenant_id, agent = get_agent(request)
    except HTTPException as e:
        service.audit(s, "", "agent:unknown", "ingest.discovery", outcome="deny",
                      detail={"code": getattr(e.detail, 'get', lambda *_: 'err')("code")})
        s.commit()
        raise
    agent.last_seen_at = datetime.now(timezone.utc)
    upserted = []
    for item in body.assets:
        asset = s.execute(
            select(Asset).where(Asset.tenant_id == tenant_id,
                                Asset.provider == item.provider,
                                Asset.service == item.service,
                                Asset.native_id == item.native_id)).scalars().first()
        if asset is None:
            asset = Asset(tenant_id=tenant_id, provider=item.provider, service=item.service,
                          asset_type=item.asset_type, native_id=item.native_id,
                          environment=item.environment, owner=item.owner,
                          classification=item.classification,
                          observed_at=_parse_dt(item.observed_at),
                          meta={"discovered_by": agent.name})
            s.add(asset)
            s.flush()
        else:
            asset.observed_at = _parse_dt(item.observed_at) or asset.observed_at
            asset.meta = {**asset.meta, "discovered_by": agent.name}
        upserted.append({"asset_id": asset.asset_id, "native_id": asset.native_id,
                         "provider": asset.provider, "service": asset.service})
    service.audit(s, tenant_id, f"agent:{agent.name}", "ingest.discovery",
                  target=f"{len(upserted)} assets")
    s.commit()
    return {"ok": True, "assets": upserted}


@app.post("/ingest/evidence")
def ingest_evidence(body: EvidenceBody, request: Request, s=Depends(get_db)):
    """Batch, idempotent by source_ref. Creds tidak pernah masuk payload (agent-side)."""
    try:
        tenant_id, agent = get_agent(request)
    except HTTPException as e:
        service.audit(s, "", "agent:unknown", "ingest.evidence", outcome="deny")
        s.commit()
        raise
    agent.last_seen_at = datetime.now(timezone.utc)
    stored, skipped = 0, 0
    for item in body.evidence:
        existing = s.execute(select(EvidenceRecord).where(
            EvidenceRecord.tenant_id == tenant_id,
            EvidenceRecord.source_ref == item.source_ref)).scalars().first()
        if existing is not None:
            skipped += 1
            continue
        asset = s.execute(select(Asset).where(
            Asset.tenant_id == tenant_id,
            Asset.native_id == item.asset_native_id)).scalars().first()
        if asset is None:
            return err(422, f"asset {item.asset_native_id} belum terdaftar (discovery dulu)",
                       "unknown_asset")
        s.add(EvidenceRecord(
            tenant_id=tenant_id, asset_id=asset.asset_id,
            evidence_type=item.evidence_type, source_ref=item.source_ref,
            payload=item.payload, collected_at=_parse_dt(item.collected_at),
            freshness=item.freshness,
            access_classification=item.access_classification))
        stored += 1
    service.audit(s, tenant_id, f"agent:{agent.name}", "ingest.evidence",
                  target=f"stored={stored},skipped={skipped}")
    s.commit()
    return {"ok": True, "stored": stored, "skipped": skipped}


@app.get("/agent/config")
def agent_config(request: Request, s=Depends(get_db)):
    """interval, rules version, creds refs — TANPA nilai creds (agent tarik terenkripsi nanti)."""
    tenant_id, agent = get_agent(request)
    controls = s.execute(select(Control).where(Control.active == True)).scalars().all()  # noqa: E712
    return {
        "agent_id": agent.agent_id, "tenant_id": tenant_id,
        "interval_s": int(os.environ.get("DATAOPS_AGENT_INTERVAL", "300")),
        "policy_set_version": "pilot-1",
        "rules": [{"control_id": c.control_id, "version": c.version,
                   "rule_type": c.rule_type, "severity": c.severity} for c in controls],
        "creds_refs": {},  # ref terenkripsi; agent dekripsi lokal — nilai tidak lewat sini
        "note": "creds tidak pernah dikirim via endpoint ini; agent pull terenkripsi di fase berikut",
    }


# --- Dashboard read API (auth user) ---

@app.get("/api/assets")
def api_assets(auth: AuthContext = Depends(get_auth), s=Depends(get_db)):
    rows = s.execute(select(Asset).where(Asset.tenant_id == auth.tenant_id)).scalars().all()
    return {"assets": [_asset_json(a) for a in rows]}


@app.get("/api/findings")
def api_findings(auth: AuthContext = Depends(get_auth), s=Depends(get_db)):
    rows = s.execute(select(Finding).where(Finding.tenant_id == auth.tenant_id)
                     .order_by(Finding.last_seen_at.desc())).scalars().all()
    return {"findings": [_finding_json(f) for f in rows]}


@app.patch("/api/findings/{finding_id}")
def api_finding_update(finding_id: str, body: dict, auth: AuthContext = Depends(get_auth),
                       s=Depends(get_db)):
    """Ubah lifecycle status finding (bukan control result)."""
    auth.require_write()
    f = s.execute(select(Finding).where(Finding.tenant_id == auth.tenant_id,
                                        Finding.finding_id == finding_id)).scalars().first()
    if f is None:
        return err(404, "finding tidak ditemukan di tenant ini", "not_found")
    status = body.get("status")
    allowed = ("open", "acknowledged", "remediating", "resolved", "accepted_risk")
    if status not in allowed:
        return err(422, f"status harus salah satu dari {allowed}", "invalid_status")
    f.status = status
    service.audit(s, auth.tenant_id, auth.actor, "finding.status",
                  target=finding_id, detail={"status": status})
    s.commit()
    return _finding_json(f)


@app.get("/api/control-results")
def api_control_results(auth: AuthContext = Depends(get_auth), s=Depends(get_db)):
    rows = s.execute(select(ControlResult).where(
        ControlResult.tenant_id == auth.tenant_id)
        .order_by(ControlResult.evaluated_at.desc()).limit(500)).scalars().all()
    return {"control_results": [_result_json(r) for r in rows]}


@app.get("/api/assessments")
def api_assessments(auth: AuthContext = Depends(get_auth), s=Depends(get_db)):
    rows = s.execute(select(AssessmentRun).where(AssessmentRun.tenant_id == auth.tenant_id)
                     .order_by(AssessmentRun.started_at.desc()).limit(50)).scalars().all()
    return {"assessments": [{
        "assessment_id": a.assessment_id, "scope": a.scope,
        "started_at": a.started_at.isoformat(),
        "completed_at": (a.completed_at or a.started_at).isoformat(),
        "engine_version": a.engine_version, "policy_set_version": a.policy_set_version,
    } for a in rows]}


@app.get("/api/audit-events")
def api_audit(auth: AuthContext = Depends(get_auth), s=Depends(get_db)):
    rows = s.execute(select(AuditEvent).where(AuditEvent.tenant_id == auth.tenant_id)
                     .order_by(AuditEvent.timestamp.desc()).limit(200)).scalars().all()
    return {"audit_events": [{
        "event_id": e.event_id, "tenant_id": e.tenant_id, "actor": e.actor,
        "action": e.action, "target": e.target, "outcome": e.outcome,
        "timestamp": e.timestamp.isoformat(),
    } for e in rows]}


@app.post("/api/assessments/run")
def api_assessment_run(body: dict | None = None, auth: AuthContext = Depends(get_auth),
                       s=Depends(get_db)):
    """Trigger assessment: rule engine atas evidence terbaru (tenant-scope user)."""
    auth.require_write()
    scope = (body or {}).get("scope", {})
    return service.run_assessment(s, auth.tenant_id, scope, actor=auth.actor)


@app.get("/api/integrations")
def api_integrations(auth: AuthContext = Depends(get_auth), s=Depends(get_db)):
    rows = s.execute(select(Integration)).scalars().all()
    return {"integrations": [{
        "integration_id": i.integration_id, "provider": i.provider, "service": i.service,
        "adapter_version": i.adapter_version, "support_status": i.support_status,
        "capabilities": i.capabilities, "permissions": i.permissions,
        "limitations": i.limitations,
    } for i in rows]}


def _parse_dt(v: str | None):
    if not v:
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None


def _asset_json(a: Asset) -> dict:
    return {"asset_id": a.asset_id, "tenant_id": a.tenant_id, "provider": a.provider,
            "service": a.service, "asset_type": a.asset_type, "native_id": a.native_id,
            "environment": a.environment, "owner": a.owner,
            "classification": a.classification, "observed_at": a.observed_at.isoformat()}


def _finding_json(f: Finding) -> dict:
    return {"finding_id": f.finding_id, "tenant_id": f.tenant_id, "asset_id": f.asset_id,
            "control_id": f.control_id, "control_version": f.control_version,
            "severity": f.severity, "status": f.status, "evidence_refs": f.evidence_refs,
            "knowledge_refs": f.knowledge_refs, "reason": f.reason,
            "first_seen_at": f.first_seen_at.isoformat(),
            "last_seen_at": f.last_seen_at.isoformat()}


def _result_json(r: ControlResult) -> dict:
    return {"result_id": r.result_id, "assessment_id": r.assessment_id,
            "control_id": r.control_id, "control_version": r.control_version,
            "status": r.status, "evidence_refs": r.evidence_refs, "reason": r.reason,
            "evaluated_at": r.evaluated_at.isoformat()}
