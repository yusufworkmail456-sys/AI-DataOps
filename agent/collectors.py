"""Collectors: PostgreSQL (psycopg read-only) + Airflow REST.

Keduanya degrade gracefully: creds belum diisi / koneksi gagal → return evidence kosong
+ flag degrade (bukan crash). Creds HANYA dipakai lokal, tidak pernah dikirim ke cloud.
"""
import logging
import re
from datetime import datetime, timezone

log = logging.getLogger("agent.collectors")

PG_EVIDENCE_TYPE = "pg_stats"
AF_EVIDENCE_TYPE = "airflow_api"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class CollectorResult:
    def __init__(self, evidence: dict | None, degraded: bool, reason: str = ""):
        self.evidence = evidence  # None / {} → evidence kosong
        self.degraded = degraded
        self.reason = reason

    def to_payload(self, provider: str, service: str, native_id: str) -> dict:
        base = {"provider": provider, "service": service, "asset": native_id,
                "collected_at": _utcnow(), "degraded": self.degraded,
                "degrade_reason": self.reason}
        if self.evidence:
            base.update(self.evidence)
        return base


# --- PostgreSQL (read-only: pg_stat_activity, pg_stat_user_tables, pg_stat_ssl,
#     pg_database_size) ---

def collect_postgresql(dsn: str) -> CollectorResult:
    """Read-only stats. Tanpa creds / gagal connect → evidence kosong + degraded."""
    if not dsn:
        return CollectorResult(None, True,
                               "PG_DSN belum diisi (set DATAOPS_PG_DSN / config yaml) — "
                               "evidence kosong, bukan pass")
    try:
        import psycopg
    except ImportError:
        return CollectorResult(None, True, "psycopg tidak terpasang")

    try:
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                # pg_stat_activity: durasi lock/transaksi aktif terlama (detik)
                cur.execute("""
                    SELECT COALESCE(MAX(EXTRACT(EPOCH FROM (now() - xact_start))), 0)
                    FROM pg_stat_activity
                    WHERE state <> 'idle' AND backend_type = 'client backend'""")
                max_lock_duration_s = float(cur.fetchone()[0] or 0)  # type: ignore[index]

                # pg_stat_user_tables: dead tuple ratio per tabel
                cur.execute("""
                    SELECT relname, n_live_tup, n_dead_tup
                    FROM pg_stat_user_tables""")
                tables: dict[str, float] = {}
                for relname, live, dead in cur.fetchall():
                    denom = (live or 0) + (dead or 0)
                    tables[relname] = round((dead or 0) / denom, 6) if denom else 0.0

                # pg_stat_ssl: apakah ada koneksi user dengan SSL aktif
                cur.execute("""
                    SELECT COUNT(*) FILTER (WHERE ssl), COUNT(*)
                    FROM pg_stat_ssl WHERE ssl IS NOT NULL""")
                row = cur.fetchone()
                ssl_on, ssl_total = (row[0], row[1]) if row else (0, 0)

                # pg_database_size
                cur.execute("SELECT pg_database_size(current_database())")
                r2 = cur.fetchone()
                db_size = int(r2[0]) if r2 else 0

                cur.execute("SELECT version()")
                r3 = cur.fetchone()
                version = str(r3[0]) if r3 else ""
        version_short = (version.split(" ")[1] if len(version.split(" ")) > 1 else "") if version else ""
        return CollectorResult({
            "max_lock_duration_s": max_lock_duration_s,
            "tables": {"dead_tuple_ratio": tables},
            "ssl_enabled": bool(ssl_on and ssl_total and ssl_on > 0),
            "ssl_connections": int(ssl_on or 0), "total_connections": int(ssl_total or 0),
            "database_size_bytes": db_size,
            "pg_version": version_short,
            "audit_purge": {},   # tidak ada evidence purge tercatat dari stats bawaan
        }, False)
    except Exception as e:  # noqa: BLE001 — graceful degrade
        return CollectorResult(None, True, f"postgresql collect gagal: {type(e).__name__}")


# --- Airflow REST /api/v1 (dag runs, task instances, health) ---

def collect_airflow(base_url: str, username: str, password: str) -> CollectorResult:
    if not base_url:
        return CollectorResult(None, True,
                               "Airflow base_url belum diisi (DATAOPS_AIRFLOW_URL) — "
                               "evidence kosong, bukan pass")
    try:
        import httpx
    except ImportError:
        return CollectorResult(None, True, "httpx tidak terpasang")

    auth = (username, password) if username else None
    try:
        with httpx.Client(timeout=10, auth=auth) as client:
            health = client.get(f"{base_url.rstrip('/')}/api/v1/health")
            health.raise_for_status()
            dag_runs = client.get(
                f"{base_url.rstrip('/')}/api/v1/dags/~/dagRuns",
                params={"limit": 100, "state": "success"}).json()
            failed_runs = client.get(
                f"{base_url.rstrip('/')}/api/v1/dags/~/dagRuns",
                params={"limit": 100, "state": "failed"}).json()
            total_success = dag_runs.get("total_entries", 0)
            total_failed = failed_runs.get("total_entries", 0)
            denom = total_success + total_failed
            success_rate = round(total_success / denom, 4) if denom else None

            # task duration (task instance duration field, detik) — max dari recent TIs
            max_task_duration_s = 0.0
            tis = client.get(
                f"{base_url.rstrip('/')}/api/v1/dags/~/dagRuns/~/taskInstances",
                params={"limit": 100}).json()
            for ti in tis.get("task_instances", []):
                d = ti.get("duration")
                if isinstance(d, (int, float)) and d > max_task_duration_s:
                    max_task_duration_s = float(d)

            return CollectorResult({
                "health": health.json(),
                "dag_run_success_rate": success_rate,
                "dag_runs_total": denom,
                "max_task_duration_s": max_task_duration_s,
                "lineage": {"facets": {}},  # facets OpenLineage belum tersedia via REST → unknown
            }, False)
    except Exception as e:  # noqa: BLE001 — graceful degrade
        return CollectorResult(None, True, f"airflow collect gagal: {type(e).__name__}")


def source_ref(agent_name: str, provider: str, native_id: str, ts: datetime | None = None) -> str:
    """source_ref idempotensi: agent:provider:asset:YYYYMMDDTHHMMSSZ."""
    ts = ts or datetime.now(timezone.utc)
    stamp = ts.strftime("%Y%m%dT%H%M%SZ")
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{agent_name}:{provider}:{native_id}")
    return f"{safe}:{stamp}"
