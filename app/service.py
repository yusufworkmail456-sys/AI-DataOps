"""Service layer: assessment run (rule engine atas evidence terbaru), audit helper, findings upsert."""
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from .models import (AssessmentRun, Asset, AuditEvent, Control, ControlResult,
                     EvidenceRecord, Exception_, Finding, make_session_factory)
from . import rule_engine
from .rule_engine import ENGINE_VERSION

log = logging.getLogger("dataops.service")


def audit(session, tenant_id: str, actor: str, action: str, target: str = "",
          outcome: str = "allow", detail: dict | None = None) -> None:
    """Append-only audit (satu-satunya jalur tulis audit_events)."""
    session.add(AuditEvent(tenant_id=tenant_id, actor=actor, action=action,
                           target=target, outcome=outcome, detail=detail or {}))


def upsert_finding(session, tenant_id: str, asset_id: str, control_id: str,
                   control_version: int, assessment_id: str, severity: str,
                   evidence_refs: list, knowledge_refs: list, reason: str,
                   now: datetime) -> None:
    """Finding lifecycle terpisah dari control result status: fail baru → open;
    fail ulang asset+control sama → update last_seen (status lifecycle tidak diubah).
    Exception aktif (approved, tak expired) → status accepted_risk, bukan open."""
    # Exception aktif utk asset+control ini: lewat finding mana pun (lama/baru) yg cocok.
    active_exc_ids = select(Exception_.finding_id).where(
        Exception_.tenant_id == tenant_id, Exception_.finding_id.is_not(None),
        Exception_.status == "active",
        (Exception_.expiry.is_(None)) | (Exception_.expiry > now)).scalar_subquery()
    has_active_exc = session.execute(
        select(Finding.finding_id).where(
            Finding.tenant_id == tenant_id, Finding.asset_id == asset_id,
            Finding.control_id == control_id,
            Finding.finding_id.in_(active_exc_ids)
        ).limit(1)).scalar() is not None
    status = "accepted_risk" if has_active_exc else "open"
    f = session.execute(
        select(Finding).where(Finding.tenant_id == tenant_id,
                              Finding.asset_id == asset_id,
                              Finding.control_id == control_id,
                              Finding.status != "resolved")
    ).scalars().first()
    if f is None:
        session.add(Finding(
            tenant_id=tenant_id, asset_id=asset_id, control_id=control_id,
            control_version=control_version, assessment_id=assessment_id,
            severity=severity, status=status, evidence_refs=evidence_refs,
            knowledge_refs=knowledge_refs, reason=reason,
            first_seen_at=now, last_seen_at=now))
    else:
        f.last_seen_at = now
        f.assessment_id = assessment_id
        f.evidence_refs = evidence_refs
        f.reason = reason
        # exception bisa revoke/expired antar run — lifecycle ikut keadaan terkini
        if f.status == "accepted_risk" and not has_active_exc:
            f.status = "open"
        elif f.status == "open" and has_active_exc:
            f.status = "accepted_risk"


def run_assessment(session, tenant_id: str, scope: dict | None = None,
                   actor: str = "system") -> dict:
    """Jalankan rule engine atas evidence terbaru per asset (tenant-scoped).

    Scope: {"provider": ...} / {"service": ...} / {} = semua asset tenant.
    Missing evidence → unknown (AC-05). Return ringkasan run.
    """
    scope = scope or {}
    run = AssessmentRun(tenant_id=tenant_id, scope=scope,
                        engine_version=ENGINE_VERSION, policy_set_version="pilot-1")
    session.add(run)
    session.flush()

    assets = session.execute(
        select(Asset).where(Asset.tenant_id == tenant_id)).scalars().all()
    if scope.get("provider"):
        assets = [a for a in assets if a.provider == scope["provider"]]
    if scope.get("service"):
        assets = [a for a in assets if a.service == scope["service"]]
    if scope.get("asset_id"):
        assets = [a for a in assets if a.asset_id == scope["asset_id"]]

    controls = session.execute(
        select(Control).where(Control.active == True)).scalars().all()  # noqa: E712

    counts = {"pass": 0, "fail": 0, "unknown": 0, "not_applicable": 0}
    for asset in assets:
        # evidence terbaru per evidence_type untuk asset ini (tenant-scoped)
        evs = session.execute(
            select(EvidenceRecord).where(
                EvidenceRecord.tenant_id == tenant_id,
                EvidenceRecord.asset_id == asset.asset_id)
            .order_by(EvidenceRecord.collected_at.desc())).scalars().all()
        latest: dict[str, EvidenceRecord] = {}
        for e in evs:
            latest.setdefault(e.evidence_type, e)
        evid_pool = [
            {"evidence_id": e.evidence_id, "evidence_type": e.evidence_type,
             "source_ref": e.source_ref, "payload": e.payload,
             "collected_at": e.collected_at.isoformat(), "freshness": e.freshness}
            for e in latest.values()
        ]
        for control in controls:
            # pilih evidence paling relevan: cocokkan applicability provider/service.
            # Prefer evidence yang punya field yang dibutuhkan rule (mis. 'facets' utk lineage_check).
            rp = control.params or {}
            prefer_field = rp.get("facets_field") or rp.get("field", "")
            if not prefer_field and control.rule_type == "lineage_check":
                prefer_field = "facets"
            chosen = None
            fallback = None
            for e in evid_pool:
                if e["payload"].get("provider") not in (None, control.applicability.get("provider")):
                    continue
                if e["payload"].get("service") not in (None, control.applicability.get("service")):
                    continue
                if prefer_field and prefer_field in e["payload"]:
                    chosen = e
                    break
                if fallback is None:
                    fallback = e
            if chosen is None:
                chosen = fallback
            if chosen is None:
                # Tidak ada evidence sama sekali utk asset ini. Kalau kontrol menarget
                # provider tertentu dan asset jelas beda provider → not_applicable
                # (keputusan eksplisit), bukan unknown. Kalau kontrol generik (tanpa
                # target provider) → unknown (bukti memang belum ada).
                app = control.applicability or {}
                if app.get("provider") and app["provider"] != asset.provider:
                    counts["not_applicable"] += 1
                    session.add(ControlResult(
                        tenant_id=tenant_id, assessment_id=run.assessment_id,
                        control_id=control.control_id, control_version=control.version,
                        status="not_applicable", evidence_refs=[],
                        reason=f"control utk {app['provider']}, asset ini {asset.provider}"))
                    continue
            result = rule_engine.evaluate(control, chosen)
            counts[result.status] = counts.get(result.status, 0) + 1
            session.add(ControlResult(
                tenant_id=tenant_id, assessment_id=run.assessment_id,
                control_id=control.control_id, control_version=control.version,
                status=result.status, evidence_refs=result.evidence_refs,
                reason=result.reason))
            if result.status == "fail":
                upsert_finding(
                    session, tenant_id, asset.asset_id, control.control_id,
                    control.version, run.assessment_id, control.severity,
                    result.evidence_refs, result.knowledge_refs, result.reason,
                    datetime.now(timezone.utc))

    run.completed_at = datetime.now(timezone.utc)
    session.flush()
    audit(session, tenant_id, actor, "assessment.run", target=run.assessment_id,
          detail={"counts": counts, "assets": len(assets), "controls": len(controls)})
    session.commit()
    return {
        "assessment_id": run.assessment_id, "tenant_id": tenant_id,
        "started_at": run.started_at.isoformat(),
        "completed_at": (run.completed_at or run.started_at).isoformat(),
        "engine_version": run.engine_version, "policy_set_version": run.policy_set_version,
        "scope": scope, "assets": len(assets), "controls": len(controls),
        "results": counts,
    }
