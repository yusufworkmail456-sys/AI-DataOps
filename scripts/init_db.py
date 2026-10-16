"""Seed DB: schema + katalog rule pilot + integrations + user admin default dari env.

Env: DATAOPS_ADMIN_USER (default admin), DATAOPS_ADMIN_PASS (wajib utk produksi;
default 'admin' hanya dev), DATAOPS_TENANT (default tenant-alpha).
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import rule_engine  # noqa: E402
from app.models import (Base, Control, Integration, User, make_engine,  # noqa: E402
                        make_session_factory)
from app.auth import hash_password  # noqa: E402

DB_PATH = os.environ.get("DATAOPS_DB", "data/dataops.db")

INTEGRATIONS = [
    {
        "provider": "postgresql", "service": "database", "adapter_version": "0.1.0",
        "support_status": "pilot",
        "capabilities": {"discover": True, "observe": True, "evaluate": True,
                         "diagnose": False, "act": False},
        "permissions": {"pg_monitor": "baca pg_stat_* read-only",
                        "pg_read_all_data": "baca metadata"},
        "limitations": "L1-L3 only (discover/observe/evaluate); diagnose & act belum didukung P0. "
                       "Evidence: pg_stat_activity, pg_stat_user_tables, pg_stat_ssl, pg_database_size.",
    },
    {
        "provider": "apache-airflow", "service": "orchestration", "adapter_version": "0.1.0",
        "support_status": "pilot",
        "capabilities": {"discover": True, "observe": True, "evaluate": True,
                         "diagnose": False, "act": False},
        "permissions": {"REST API readonly role": "GET /api/v1/dags, dagRuns, taskInstances, health"},
        "limitations": "L1-L3 only; lineage terbatas pada facets yang ada; act belum didukung P0.",
    },
    {
        "provider": "docker", "service": "runtime", "adapter_version": "0.1.0",
        "support_status": "pilot",
        "capabilities": {"discover": True, "observe": False, "evaluate": False,
                         "diagnose": False, "act": False},
        "permissions": {"docker.sock read-only": "list containers/images/ports"},
        "limitations": "discovered, L1 only (jujur — FR-01).",
    },
]


def main() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    engine = make_engine(f"sqlite:///{DB_PATH}")
    Base.metadata.create_all(engine)
    s = make_session_factory(engine)()

    # katalog rule pilot
    for c in rule_engine.catalog_seed():
        if s.get(Control, c["control_id"]) is None:
            s.add(Control(control_id=c["control_id"], version=c["version"],
                          domain=c["domain"], statement=c["statement"],
                          applicability=c["applicability"], test_method=c["test_method"],
                          rule_type=c["rule_type"], params=c["params"],
                          severity=c["severity"], knowledge_ref=c["knowledge_ref"]))
            print(f"seed control {c['control_id']} v{c['version']} ({c['rule_type']})")

    # integration registry
    for i in INTEGRATIONS:
        existing = s.query(Integration).filter_by(provider=i["provider"],
                                                  service=i["service"]).first()
        if existing is None:
            s.add(Integration(**i))
            print(f"seed integration {i['provider']}/{i['service']}")

    # user admin default dari env
    username = os.environ.get("DATAOPS_ADMIN_USER", "admin")
    password = os.environ.get("DATAOPS_ADMIN_PASS", "admin")
    tenant = os.environ.get("DATAOPS_TENANT", "tenant-alpha")
    if s.query(User).filter_by(username=username).first() is None:
        s.add(User(username=username, password_hash=hash_password(password),
                   role="admin", tenant_id=tenant))
        print(f"seed user admin '{username}' (tenant {tenant}) "
              f"{'[DEV default password]' if password == 'admin' else ''}")

    s.commit()
    s.close()
    print(f"init_db ok: {DB_PATH}")


if __name__ == "__main__":
    main()
