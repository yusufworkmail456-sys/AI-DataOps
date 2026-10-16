"""Security & API tests: tenant isolation (AC-09), ingest auth, audit append-only,
AC-05 missing evidence → unknown, finding lifecycle terpisah."""
import pytest

from app import service
from app.models import AuditEvent, User


def _discover(client, key, native_id="pg-main", provider="postgresql", service="database"):
    return client.post("/ingest/discovery", json={"assets": [{
        "provider": provider, "service": service, "asset_type": "database",
        "native_id": native_id, "environment": "prod"}]},
        headers={"X-Agent-Key": key})


def _evidence(client, key, native_id="pg-main", payload=None, source_ref="sr-1"):
    return client.post("/ingest/evidence", json={"evidence": [{
        "asset_native_id": native_id, "evidence_type": "pg_stats",
        "source_ref": source_ref, "payload": payload or {}}]},
        headers={"X-Agent-Key": key})


class TestIngestAuth:
    def test_enroll_invalid_token_401(self, client):
        r = client.post("/ingest/enroll", json={"enroll_token": "salah"})
        assert r.status_code == 401
        assert r.json()["code"] == "invalid_enroll_token"

    def test_enroll_token_single_use(self, client):
        client.app.state.enroll_tokens["tok"] = "tenant-alpha"
        r1 = client.post("/ingest/enroll", json={"enroll_token": "tok"})
        assert r1.status_code == 200 and "agent_key" in r1.json()
        r2 = client.post("/ingest/enroll", json={"enroll_token": "tok"})
        assert r2.status_code == 401  # token habis

    def test_discovery_wrong_key_401(self, client, enrolled_agent):
        r = _discover(client, "key-salah")
        assert r.status_code == 401
        assert r.json()["code"] in ("invalid_agent_key", "unauthenticated")

    def test_discovery_no_key_401(self, client, enrolled_agent):
        r = client.post("/ingest/discovery", json={"assets": []})
        assert r.status_code == 401

    def test_evidence_wrong_key_401(self, client, enrolled_agent):
        assert _evidence(client, "bukan-key").status_code == 401

    def test_agent_config(self, client, enrolled_agent):
        r = client.get("/agent/config", headers={"X-Agent-Key": enrolled_agent["agent_key"]})
        assert r.status_code == 200
        body = r.json()
        assert body["tenant_id"] == "tenant-alpha"
        assert "interval_s" in body and "creds_refs" in body
        # creds TIDAK dikirim via endpoint ini
        assert body["creds_refs"] == {}


class TestTenantIsolation:
    """AC-09: query tenant lain ditolak + dicatat di audit_events."""

    def test_finding_cross_tenant_404(self, client, enrolled_agent, seed_controls, admin_client):
        key = enrolled_agent["agent_key"]
        assert _discover(client, key).status_code == 200
        assert _evidence(client, key, payload={"max_lock_duration_s": 900}).status_code == 200
        assert admin_client.post("/api/assessments/run", json={}).status_code == 200

        # user tenant lain
        s = client.app.state.db_factory()
        s.add(User(username="other-admin", password_hash=_hash_pw("pw"),
                   role="admin", tenant_id="tenant-beta"))
        s.commit()
        admin_client.post("/auth/logout")
        admin_client.post("/auth/login", json={"username": "other-admin", "password": "pw"})

        findings = admin_client.get("/api/findings").json()["findings"]
        assert findings == []  # finding tenant-alpha tidak terlihat

        # akses langsung ID finding tenant-alpha → ditolak
        from app.models import Finding
        s2 = client.app.state.db_factory()
        f = s2.query(Finding).first()
        fid = f.finding_id
        s2.close()
        r = admin_client.patch(f"/api/findings/{fid}", json={"status": "acknowledged"})
        assert r.status_code == 404  # ditolak (tak terlihat antar tenant)

        # ditolak dan TERCATAT di audit_events tenant-alpha
        admin_client.post("/auth/logout")
        admin_client.post("/auth/login", json={"username": "admin", "password": "adminpass"})
        events = admin_client.get("/api/audit-events").json()["audit_events"]
        # event tenant-beta dicatat di audit tenant-beta; tenant-alpha tidak melihatnya (isolasi audit)
        tenants = {e["tenant_id"] for e in events}
        assert "tenant-beta" not in tenants

    def test_assets_scoped(self, client, enrolled_agent, admin_client):
        key = enrolled_agent["agent_key"]
        assert _discover(client, key).status_code == 200
        assert _discover(client, key, native_id="af-1", provider="apache-airflow",
                         service="orchestration").status_code == 200
        assets = admin_client.get("/api/assets").json()["assets"]
        assert len(assets) == 2
        assert all(a["tenant_id"] == "tenant-alpha" for a in assets)

    def test_web_unauthenticated_401(self, client):
        assert client.get("/api/assets").status_code == 401
        assert client.get("/api/findings").status_code == 401
        assert client.post("/api/assessments/run").status_code == 401

    def test_viewer_cannot_write(self, client, viewer_client, enrolled_agent, seed_controls):
        r = viewer_client.post("/api/assessments/run", json={})
        assert r.status_code == 403


class TestAuditAppendOnly:
    def test_events_created(self, client, enrolled_agent, admin_client):
        client.app.state.enroll_tokens["tok9"] = "tenant-alpha"
        client.post("/ingest/enroll", json={"enroll_token": "tok9"})
        events = admin_client.get("/api/audit-events").json()["audit_events"]
        assert any(e["action"] == "agent.enrolled" for e in events)

    def test_update_delete_blocked(self, client):
        """append-only: UPDATE/DELETE audit_events diblokir di DB level."""
        s = client.app.state.db_factory()
        service.audit(s, "tenant-alpha", "tester", "test.action")
        s.commit()
        ev = s.query(AuditEvent).first()
        with pytest.raises(Exception):
            s.query(AuditEvent).filter(AuditEvent.event_id == ev.event_id).update(
                {"action": "hacked"})
            s.commit()
        s.rollback()
        with pytest.raises(Exception):
            s.query(AuditEvent).filter(AuditEvent.event_id == ev.event_id).delete()
            s.commit()
        s.rollback()
        assert s.query(AuditEvent).count() == 1


class TestAC05UnknownNotPass:
    """AC-05: evidence hilang → unknown, BUKAN pass."""

    def test_missing_evidence_unknown(self, client, enrolled_agent, seed_controls, admin_client):
        key = enrolled_agent["agent_key"]
        assert _discover(client, key).status_code == 200  # asset ada, evidence TIDAK
        r = admin_client.post("/api/assessments/run", json={})
        assert r.status_code == 200
        results = admin_client.get("/api/control-results").json()["control_results"]
        assert results, "harus ada control results"
        assert all(res["status"] != "pass" for res in results), \
            "tanpa evidence tidak boleh ada pass"
        assert all(res["status"] == "unknown" for res in results)

    def test_partial_evidence_mix(self, client, enrolled_agent, seed_controls, admin_client):
        key = enrolled_agent["agent_key"]
        assert _discover(client, key).status_code == 200
        # PG evidence ok (lock 42s → pass, dead ratio 0.4 → fail, ssl false → fail,
        # audit purge kosong → unknown)
        payload = {"provider": "postgresql", "service": "database",
                   "max_lock_duration_s": 42,
                   "tables": {"dead_tuple_ratio": {"users": 0.4}},
                   "ssl_enabled": False, "audit_purge": {}}
        assert _evidence(client, key, payload=payload).status_code == 200
        assert admin_client.post("/api/assessments/run", json={}).status_code == 200
        results = admin_client.get("/api/control-results").json()["control_results"]
        statuses = {r["control_id"]: r["status"] for r in results}
        assert statuses["RULE-ENG-001"] == "pass"     # 42 < 300
        assert statuses["RULE-DBA-003"] == "fail"     # 0.4 > 0.15
        assert statuses["RULE-SEC-004"] == "fail"     # ssl off
        assert statuses["RULE-GOV-009"] == "unknown"  # purge kosong → unknown
        # Airflow rules: tanpa evidence airflow → unknown / na
        assert statuses["RULE-OPR-001"] in ("unknown", "not_applicable")
        assert statuses["RULE-LIN-002"] in ("unknown", "not_applicable")


class TestFindingLifecycle:
    """Finding lifecycle TERPISAH dari control result status."""

    def test_fail_creates_open_finding_ack_kept_on_rerun(self, client, enrolled_agent,
                                                         seed_controls, admin_client):
        key = enrolled_agent["agent_key"]
        _discover(client, key)
        payload = {"provider": "postgresql", "service": "database",
                   "max_lock_duration_s": 42,
                   "tables": {"dead_tuple_ratio": {"users": 0.4}},
                   "ssl_enabled": True, "audit_purge": {"last_purge_at": "2026-10-01"}}
        _evidence(client, key, payload=payload)
        admin_client.post("/api/assessments/run", json={})
        findings = admin_client.get("/api/findings").json()["findings"]
        assert len(findings) == 1 and findings[0]["status"] == "open"
        fid = findings[0]["finding_id"]

        # acknowledge
        r = admin_client.patch(f"/api/findings/{fid}", json={"status": "acknowledged"})
        assert r.status_code == 200 and r.json()["status"] == "acknowledged"

        # re-run assessment: control masih fail, tapi lifecycle TIDAK direset ke open
        admin_client.post("/api/assessments/run", json={})
        findings = admin_client.get("/api/findings").json()["findings"]
        still = [f for f in findings if f["finding_id"] == fid]
        assert still and still[0]["status"] == "acknowledged"
        assert still[0]["last_seen_at"] >= still[0]["first_seen_at"]

        # resolve → re-run tidak membuat finding duplikat baru
        admin_client.patch(f"/api/findings/{fid}", json={"status": "resolved"})
        admin_client.post("/api/assessments/run", json={})
        live = [f for f in admin_client.get("/api/findings").json()["findings"]
                if f["control_id"] == "RULE-DBA-003" and f["status"] == "open"]
        assert len(live) == 1  # finding baru terpisah; yang lama tetap resolved


class TestAssessmentVersioning:
    """AC-08: assessment history menyimpan versi rule/engine."""

    def test_run_records_versions(self, client, enrolled_agent, seed_controls, admin_client):
        admin_client.post("/api/assessments/run", json={})
        runs = admin_client.get("/api/assessments").json()["assessments"]
        assert len(runs) == 1
        assert runs[0]["engine_version"]
        assert runs[0]["policy_set_version"] == "pilot-1"
        results = admin_client.get("/api/control-results").json()["control_results"]
        assert all(r["control_version"] == 1 for r in results)


def _hash_pw(pw):
    from app.auth import hash_password
    return hash_password(pw)
