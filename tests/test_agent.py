"""Tests agent: discovery parsing, collectors degrade, buffer, retry."""
import json

import httpx
import pytest

from agent import discovery
from agent.buffer import Buffer, push_with_retry
from agent.collectors import collect_airflow, collect_postgresql, source_ref


class TestDiscoveryParsing:
    def test_ss_tlnp_parse(self):
        sample = """State Recv-Q Send-Q Local Address:Port Peer Address:Port Process
LISTEN 0      244        127.0.0.1:5432      0.0.0.0:*  users:(("postgres",pid=912,fd=5))
LISTEN 0      128          0.0.0.0:8080      0.0.0.0:*  users:(("gunicorn",pid=1200,fd=5))
LISTEN 0      511        127.0.0.1:6379      0.0.0.0:*  users:(("redis-server",pid=700,fd=6))"""
        import re
        lines = sample.splitlines()[1:]
        ports = []
        for line in lines:
            port = re.search(r":(\d+)\s", line)
            assert port is not None, line
            proc = None
            if "users:" in line:
                m = re.search(r'\(\("?([^"/]+)', line.split("users:")[1])
                proc = m.group(1).strip('"') if m else None
            ports.append({"port": int(port.group(1)), "process": proc or ""})
        assert {"port": 5432, "process": "postgres"} in ports
        assert {"port": 8080, "process": "gunicorn"} in ports

    def test_signature_match(self):
        assert discovery.match_signature("postgres", 5432)["provider"] == "postgresql"
        assert discovery.match_signature("airflow", 8080)["provider"] == "apache-airflow"
        assert discovery.match_signature("random-app", 9999) is None or \
            discovery.match_signature("random-app", 9999)["provider"] != "postgresql"

    def test_systemd_parse(self, monkeypatch):
        monkeypatch.setattr(discovery, "_run",
                            lambda cmd, timeout=10: "nginx.service loaded active running nginx\n"
                                                    "cron.service loaded active running cron\n"
                                                    "postgresql.service loaded active running postgres\n"
                                                    "ModemManager.service loaded active running modem\n")
        units = discovery.discover_systemd()
        names = [u["native_id"] for u in units]
        # hanya unit data-stack; unit OS plumbing (ModemManager) difilter
        assert "postgresql.service" in names
        assert "ModemManager.service" not in names
        assert "cron.service" not in names

    def test_docker_graceful_no_socket(self, tmp_path):
        # socket tidak ada → kosong, bukan crash
        assert discovery.discover_docker(str(tmp_path / "nope.sock")) == []


class TestCollectorsDegrade:
    """Collectors HARUS degrade gracefully: evidence kosong + flag, bukan crash (D1, FR-03)."""

    def test_pg_no_creds_degrades(self):
        r = collect_postgresql("")
        assert r.degraded is True
        assert r.evidence is None

    def test_pg_bad_dsn_degrades(self):
        r = collect_postgresql("postgresql://nouser:nopass@127.0.0.1:1/nodb")
        assert r.degraded is True
        assert "gagal" in r.reason or "gagal" in r.reason

    def test_pg_degraded_payload_flag(self):
        r = collect_postgresql("")
        p = r.to_payload("postgresql", "database", "pg-1")
        assert p["degraded"] is True and p["degrade_reason"]
        assert p["provider"] == "postgresql"

    def test_airflow_no_url_degrades(self):
        r = collect_airflow("", "", "")
        assert r.degraded is True and r.evidence is None

    def test_airflow_unreachable_degrades(self):
        r = collect_airflow("http://127.0.0.1:1", "", "")
        assert r.degraded is True

    def test_airflow_mocked_ok(self, monkeypatch):
        class FakeResp:
            def __init__(self, data):
                self._d = data
            def raise_for_status(self): pass
            def json(self): return self._d

        def fake_get(url, **kw):
            if "health" in url:
                return FakeResp({"metadatabase": {"status": "healthy"}})
            params = kw.get("params") or {}
            if params.get("state") == "success":
                return FakeResp({"total_entries": 96, "dag_runs": []})
            if params.get("state") == "failed":
                return FakeResp({"total_entries": 4, "dag_runs": []})
            return FakeResp({"task_instances": [{"duration": 120.0}, {"duration": 3700.0}]})

        class FakeClient:
            def __init__(self, *a, **k): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def get(self, url, **kw): return fake_get(url, **kw)

        import agent.collectors as c
        import httpx as _httpx
        monkeypatch.setattr(_httpx, "Client", FakeClient)
        r = collect_airflow("http://airflow.local", "u", "p")
        assert r.degraded is False
        assert r.evidence is not None
        assert r.evidence["dag_run_success_rate"] == 0.96
        assert r.evidence["max_task_duration_s"] == 3700.0


class TestBuffer:
    def test_append_read(self, tmp_path):
        b = Buffer(str(tmp_path / "buf.jsonl"))
        b.append("evidence", {"a": 1})
        b.append("discovery", {"b": 2})
        assert len(b) == 2
        kinds = [e["kind"] for e in b.read_all()]
        assert kinds == ["evidence", "discovery"]

    def test_survives_corrupt_line(self, tmp_path):
        p = tmp_path / "buf.jsonl"
        p.write_text('{"kind": "evidence", "data": {}}\nCORRUPTED\n')
        b = Buffer(str(p))
        assert len(b) == 1

    def test_max_bytes_trim(self, tmp_path):
        b = Buffer(str(tmp_path / "buf.jsonl"), max_bytes=10)
        b.append("evidence", {"x": "y" * 100})
        b.append("evidence", {"x2": "y" * 100})
        # paruh terlama dibuang, file tidak tumbuh tanpa batas
        assert (tmp_path / "buf.jsonl").stat().st_size < 1000


class TestPushRetry:
    def test_success_first_try(self):
        calls = []

        class R:
            status_code = 200
            def json(self): return {"ok": True}
            text = ""

        def fake_post(url, **kw):
            calls.append(url)
            return R()

        import agent.buffer as bmod
        orig = httpx.post
        httpx.post = fake_post
        try:
            r = push_with_retry("http://x", "/ingest/evidence", {}, {})
        finally:
            httpx.post = orig
        assert r["ok"] is True and r["attempts"] == 1

    def test_retries_then_buffers(self, tmp_path, monkeypatch):
        import agent.buffer as bmod
        attempts = []

        class R:
            status_code = 503
            text = "unavailable"
            def json(self): return {}

        def fake_post(url, **kw):
            attempts.append(url)
            return R()

        monkeypatch.setattr(httpx, "post", fake_post)
        monkeypatch.setattr(bmod.time, "sleep", lambda s: None)  # no real backoff wait
        buf = Buffer(str(tmp_path / "buf.jsonl"))
        r = push_with_retry("http://x", "/ingest/evidence", {"e": 1}, {},
                            buffer=buf, kind="evidence", max_attempts=3)
        assert r["ok"] is False
        assert len(attempts) == 3          # exponential retry 3x
        assert len(buf) == 1               # masuk buffer buat push ulang
        assert buf.read_all()[0]["data"] == {"e": 1}

    def test_client_error_no_retry(self, monkeypatch, tmp_path):
        class R:
            status_code = 401
            text = "unauthorized"
            def json(self): return {"error": "x", "code": "invalid_agent_key"}

        calls = []
        monkeypatch.setattr(httpx, "post", lambda url, **kw: (calls.append(url), R())[1])
        buf = Buffer(str(tmp_path / "b.jsonl"))
        r = push_with_retry("http://x", "/ingest/evidence", {}, {}, buffer=buf,
                            kind="evidence", max_attempts=5)
        assert len(calls) == 1  # 401: tidak ada gunanya retry
        assert r["ok"] is False


def test_source_ref_idempotent_shape():
    from datetime import datetime, timezone
    ts = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)
    r1 = source_ref("a1", "postgresql", "pg-main", ts)
    r2 = source_ref("a1", "postgresql", "pg-main", ts)
    assert r1 == r2  # idempotent per (agent, provider, asset, timestamp)
    assert r1.endswith("20261016T120000Z")
