"""conftest: app test-client dengan DB tmp per-test + helper auth."""
import os
import sys
from pathlib import Path

from sqlalchemy import event
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """App test-client dgn DB SQLite tmp file per-test (bukan :memory: shared-state)."""
    from fastapi.testclient import TestClient

    from app import api
    from app import models
    db = tmp_path / "test.db"
    monkeypatch.setattr(api, "DB_PATH", str(db))
    api.init()
    api.app.state.enroll_tokens = {}
    c = TestClient(api.app)
    return c


@pytest.fixture()
def admin_client(client):
    """Client ter-login admin (tenant-alpha)."""
    from app.models import User
    from app import api as api_mod
    s = api_mod.app.state.db_factory()
    s.add(User(username="admin", password_hash=_hash("adminpass"),
               role="admin", tenant_id="tenant-alpha"))
    s.commit()
    s.close()
    r = client.post("/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    return client


@pytest.fixture()
def viewer_client(client):
    from app.models import User
    from app import api as api_mod
    s = api_mod.app.state.db_factory()
    s.add(User(username="viewer1", password_hash=_hash("viewpass"),
               role="viewer", tenant_id="tenant-alpha"))
    s.commit()
    s.close()
    r = client.post("/auth/login", json={"username": "viewer1", "password": "viewpass"})
    assert r.status_code == 200, r.text
    return client


def _hash(pw: str) -> str:
    from app.auth import hash_password
    return hash_password(pw)


@pytest.fixture()
def enrolled_agent(client):
    """Token enrol + key agent valid (tenant-alpha)."""
    from app import api as api_mod
    client.app.state.enroll_tokens["tok-1"] = "tenant-alpha"
    r = client.post("/ingest/enroll", json={"enroll_token": "tok-1", "agent_name": "a1"})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def seed_controls(client):
    """Seed katalog rule pilot + integrations ke DB test."""
    from app import api as api_mod
    from app.models import Control, Integration
    from app.rule_engine import catalog_seed
    s = api_mod.app.state.db_factory()
    for c in catalog_seed():
        s.add(Control(**c))
    s.add(Integration(provider="postgresql", service="database",
                      capabilities={"discover": True}, permissions={},
                      limitations="L1-L3"))
    s.commit()
    s.close()
    return catalog_seed()
