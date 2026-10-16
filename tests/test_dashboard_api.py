"""Test /api/summary (KPI), /api/chat (stub deterministik), /api/evidence, remediation decision."""
import pytest


@pytest.fixture()
def assessed(client, enrolled_agent, seed_controls, admin_client):
    """Tenant dgn asset PG + evidence bercampur (pass/fail/unknown) + assessment dijalankan."""
    key = enrolled_agent["agent_key"]
    client.post("/ingest/discovery", json={"assets": [{
        "provider": "postgresql", "service": "database", "asset_type": "database",
        "native_id": "pg-main", "environment": "prod"}]}, headers={"X-Agent-Key": key})
    payload = {"provider": "postgresql", "service": "database",
               "max_lock_duration_s": 42,
               "tables": {"dead_tuple_ratio": {"users": 0.4}},
               "ssl_enabled": False, "audit_purge": {}}
    client.post("/ingest/evidence", json={"evidence": [{
        "asset_native_id": "pg-main", "evidence_type": "pg_stats",
        "source_ref": "sr-pg-1", "payload": payload}]}, headers={"X-Agent-Key": key})
    admin_client.post("/api/assessments/run", json={})
    return key


class TestSummary:
    def test_requires_auth(self, client):
        assert client.get("/api/summary").status_code == 401

    def test_empty_tenant(self, admin_client):
        d = admin_client.get("/api/summary").json()
        assert d["rule_engine"]["total"] == 0
        assert d["rule_engine"]["pass_rate"] is None
        assert d["rule_engine"]["has_assessment"] is False
        assert d["pipelines"]["assets"] == 0

    def test_kpi_from_assessment(self, client, assessed, admin_client):
        d = admin_client.get("/api/summary").json()
        re = d["rule_engine"]
        assert re["total"] == 7
        assert re["has_assessment"] is True
        # 1 pass (ENG-001), 2 fail (DBA-003, SEC-004), 1 unknown (GOV-009 — kontrol
        # generik tanpa bukti), 3 not_applicable (kontrol Airflow vs asset PG)
        assert (re["pass"], re["fail"], re["unknown"]) == (1, 2, 1)
        assert re.get("not_applicable") == 3
        assert abs(re["pass_rate"] - 33.3) < 0.1  # pass/pass+fail, N/A & unknown tak dihitung
        assert d["pipelines"]["pg_assets"] == 1
        assert d["pipelines"]["open_findings"] == 2
        assert d["agents"]["supervisor"] == "P0" and len(d["agents"]["specialists"]) == 4
        assert d["maturity"]["level"] == "L4"

    def test_tenant_scoped(self, client, assessed, admin_client):
        from app.models import User
        from app.auth import hash_password
        s = client.app.state.db_factory()
        s.add(User(username="beta", password_hash=hash_password("pw"),
                   role="admin", tenant_id="tenant-beta"))
        s.commit()
        s.close()
        admin_client.post("/auth/logout")
        admin_client.post("/auth/login", json={"username": "beta", "password": "pw"})
        d = admin_client.get("/api/summary").json()
        assert d["tenant_id"] == "tenant-beta"
        assert d["rule_engine"]["total"] == 0 and d["pipelines"]["assets"] == 0


class TestChat:
    def test_requires_auth(self, client):
        assert client.post("/api/chat", json={"message": "hai"}).status_code == 401

    def test_contract_fields(self, client, assessed, admin_client):
        d = admin_client.post("/api/chat", json={"message": "status lock database?"}).json()
        for k in ("claims", "evidence_refs", "knowledge_refs", "uncertainty",
                  "risks", "verification_steps"):
            assert k in d, k
        assert d["mode"] == "deterministic-stub" and d["llm"] is False
        assert d["claims"], "harus ada claims"
        assert d["evidence_refs"] == ["sr-pg-1"]  # terikat bukti fail RULE-DBA-003/SEC-004
        assert d["knowledge_refs"]
        assert d["risks"] and d["verification_steps"]

    def test_topic_routing_lock(self, client, assessed, admin_client):
        d = admin_client.post("/api/chat", json={"message": "ada masalah dead tuple?"}).json()
        assert any("RULE-DBA-003" in c for c in d["claims"])  # domain dba dipilih
        assert d["agents"] and d["agents"][0]["role"] == "DBA"

    def test_no_findings_honest(self, client, enrolled_agent, seed_controls, admin_client):
        r = client.post("/ingest/discovery", json={"assets": [{
            "provider": "postgresql", "service": "database", "asset_type": "database",
            "native_id": "pg-clean", "environment": "prod"}]},
            headers={"X-Agent-Key": enrolled_agent["agent_key"]})
        assert r.status_code == 200
        admin_client.post("/api/assessments/run", json={})
        d = admin_client.post("/api/chat", json={"message": "ringkas kondisi"}).json()
        assert any("Tidak ada temuan aktif" in c for c in d["claims"])
        assert "tinggi" in d["uncertainty"] or "sedang" in d["uncertainty"]

    def test_no_assessment_high_uncertainty(self, client, admin_client):
        d = admin_client.post("/api/chat", json={"message": "hai"}).json()
        assert "tinggi" in d["uncertainty"]
        assert any("Belum ada assessment" in c for c in d["claims"])


class TestEvidenceEndpoint:
    def test_requires_auth(self, client):
        assert client.get("/api/evidence").status_code == 401

    def test_list_and_filter(self, client, assessed, admin_client):
        d = admin_client.get("/api/evidence").json()
        assert len(d["evidence"]) == 1
        assert d["evidence"][0]["source_ref"] == "sr-pg-1"
        assert d["evidence"][0]["payload"]["max_lock_duration_s"] == 42
        d2 = admin_client.get("/api/evidence?source_ref=tidak-ada").json()
        assert d2["evidence"] == []


class TestRemediationDecision:
    def test_requires_write(self, client, assessed, viewer_client):
        fid = client.app.state.db_factory().query(
            __import__("app.models", fromlist=["Finding"]).Finding).first().finding_id
        r = viewer_client.post("/api/remediation/decision",
                               json={"finding_id": fid, "decision": "approved"})
        assert r.status_code == 403

    def test_invalid_decision_422(self, client, assessed, admin_client):
        fid = _first_finding(client)
        r = admin_client.post("/api/remediation/decision",
                              json={"finding_id": fid, "decision": "execute"})
        assert r.status_code == 422

    def test_decision_audited_not_executed(self, client, assessed, admin_client):
        fid = _first_finding(client)
        r = admin_client.post("/api/remediation/decision",
                              json={"finding_id": fid, "decision": "approved"})
        assert r.status_code == 200
        body = r.json()
        assert body["executed"] is False  # D5: recommendation-only
        events = admin_client.get("/api/audit-events").json()["audit_events"]
        ev = [e for e in events if e["action"] == "remediation.decision"]
        assert ev and ev[0]["target"] == fid

    def test_unknown_finding_404(self, client, assessed, admin_client):
        assert admin_client.post("/api/remediation/decision",
                                 json={"finding_id": "nope", "decision": "approved"}
                                 ).status_code == 404


def _first_finding(client):
    from app.models import Finding
    s = client.app.state.db_factory()
    f = s.query(Finding).first()
    fid = f.finding_id
    s.close()
    return fid
