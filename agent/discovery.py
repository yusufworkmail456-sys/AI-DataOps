"""Discovery read-only (design.md): docker socket, systemd, ss -tlnp, signature match,
version probe → payload kanonis. Tool tanpa adapter → 'discovered, L1 only' (FR-01)."""
import json
import re
import shutil
import subprocess

# Unit systemd yang relevan utk DataOps: data infra (db, broker, orchestrator, dsb).
# ponytail: substring match sederhana; upgrade path = config pattern per tenant di agent.yaml.
DATA_UNIT_RE = re.compile(
    r"(postgres|mysql|mariadb|mongo|redis|kafka|zookeeper|clickhouse|airflow|airbyte|"
    r"superset|spark|elasticsearch|opensearch|minio|rabbitmq|nats|etcd|cassandra|"
    r"dataops|dbt|dagster|prefect|nifi|flink|solr|neo4j|influx|timescale|pgbouncer)", re.I)

SIGNATURES = [
    {"provider": "postgresql", "service": "database", "asset_type": "database",
     "processes": ["postgres"], "default_ports": [5432],
     "version_probe": "sql:SELECT version()"},
    {"provider": "apache-airflow", "service": "orchestration", "asset_type": "orchestrator",
     "processes": ["airflow", "gunicorn:master [airflow]"], "default_ports": [8080],
     "version_probe": "http:/api/v1/health"},
    {"provider": "redis", "service": "cache", "asset_type": "cache",
     "processes": ["redis-server"], "default_ports": [6379], "version_probe": None},
    {"provider": "nginx", "service": "web", "asset_type": "webserver",
     "processes": ["nginx"], "default_ports": [80, 443], "version_probe": None},
    {"provider": "mysql", "service": "database", "asset_type": "database",
     "processes": ["mysqld", "mariadbd"], "default_ports": [3306], "version_probe": None},
]


def _run(cmd: list[str], timeout: int = 10) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def discover_docker(socket_path: str = "/var/run/docker.sock") -> list[dict]:
    """Docker socket API read-only (tanpa lib eksternal)."""
    out: list[dict] = []
    if not shutil.which("curl"):
        return out
    raw = _run(["curl", "-s", "--max-time", "5", "--unix-socket", socket_path,
                "http://localhost/v1.41/containers/json"])
    if not raw:
        return out
    try:
        containers = json.loads(raw)
    except json.JSONDecodeError:
        return out
    for c in containers if isinstance(containers, list) else []:
        names = [n.lstrip("/") for n in c.get("Names", [])]
        out.append({
            "provider": "docker", "service": "runtime", "asset_type": "container",
            "native_id": c.get("Id", "")[:12],
            "environment": "prod",
            "meta": {"name": names[0] if names else "", "image": c.get("Image", ""),
                     "state": c.get("State", ""), "status": c.get("Status", ""),
                     "ports": [f"{p.get('PrivatePort')}/{p.get('Type')}"
                               for p in c.get("Ports", [])],
                     "level": "L1"},
        })
    return out


def discover_systemd() -> list[dict]:
    """systemd list-units --type=service (read-only). Hanya unit data-stack."""
    out: list[dict] = []
    raw = _run(["systemctl", "list-units", "--type=service", "--no-legend", "--no-pager"])
    for line in raw.splitlines():
        parts = line.split()
        if not parts:
            continue
        unit = parts[0]
        if unit.endswith(".service") and DATA_UNIT_RE.search(unit):
            out.append({
                "provider": "linux", "service": "systemd", "asset_type": "service",
                "native_id": unit, "environment": "prod",
                # unit platform (agent sendiri) → classification 'platform', bukan data infra tenant
                "classification": "platform" if "dataops" in unit.lower() else "internal",
                "meta": {"load": parts[1] if len(parts) > 1 else "",
                         "active": parts[2] if len(parts) > 2 else "",
                         "level": "L1"},
            })
    return out


def discover_ports() -> list[dict]:
    """ss -tlnp → listening ports + proses (read-only)."""
    out: list[dict] = []
    raw = _run(["ss", "-tlnp"])
    for line in raw.splitlines()[1:]:
        m = re.search(r"(?:[*]|[\d.]+):(\d+)\s+.*?users:\(\(?\"([^\"]+)\"", line)
        port = re.search(r":(\d+)\s", line)
        proc = re.search(r'"\((?:")?([^"/]+)', line.split("users:")[1]) if "users:" in line else None
        if port:
            out.append({"port": int(port.group(1)),
                        "process": (proc.group(1).strip('"') if proc else
                                    (m.group(2) if m else ""))})
    return out


def match_signature(proc_name: str, port: int | None) -> dict | None:
    """Signature match proses/port → entry registry."""
    proc = (proc_name or "").lower()
    for sig in SIGNATURES:
        for p in sig["processes"]:
            if p in proc or (port in sig["default_ports"] and proc):
                return sig
    return None


def probe_versions(services: list[dict]) -> None:
    """Version probe ringan: SELECT version() PG (via psql bila ada), GET health Airflow."""
    for svc in services:
        if svc["provider"] == "postgresql" and shutil.which("psql"):
            raw = _run(["psql", "-tAc", "SELECT version();"], timeout=5)
            if raw:
                svc.setdefault("meta", {})["version"] = raw.strip().split(",")[0].split(" ")[1] if " " in raw.strip() else raw.strip()[:20]
        elif svc["provider"] == "apache-airflow" and shutil.which("curl"):
            raw = _run(["curl", "-s", "--max-time", "5", "http://localhost:8080/api/v1/health"])
            try:
                svc.setdefault("meta", {})["health"] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                pass


def run_discovery(cfg: dict) -> dict:
    """Discovery penuh → payload kanonis {assets: [...], ports: [...], notes}."""
    assets: list[dict] = []
    dcfg = cfg.get("discovery", {})
    notes: list[str] = []
    ports: list[dict] = []

    if dcfg.get("enable_docker", True):
        docker_assets = discover_docker(dcfg.get("docker_socket", "/var/run/docker.sock"))
        assets.extend(docker_assets)
        if not docker_assets:
            notes.append("docker socket tidak tersedia / kosong — skip (read-only)")

    if dcfg.get("enable_systemd", True):
        assets.extend(discover_systemd())

    if dcfg.get("enable_ports", True):
        ports: list[dict] = discover_ports()
        matched_ids = set()
        for p in ports:
            sig = match_signature(p["process"], p["port"])
            if sig:
                nid = f"{sig['provider']}@{p['port']}"
                if nid not in matched_ids:
                    matched_ids.add(nid)
                    assets.append({
                        "provider": sig["provider"], "service": sig["service"],
                        "asset_type": sig["asset_type"], "native_id": nid,
                        "environment": "prod",
                        "meta": {"process": p["process"], "port": p["port"],
                                 "version_probe": sig["version_probe"], "level": "L1"},
                    })
        unmatched = [p for p in ports if not match_signature(p["process"], p["port"])]
        if unmatched:
            notes.append(f"{len(unmatched)} port/proses tanpa adapter → tidak jadi asset "
                         "(discovered, L1 only saat adapter tersedia)")

    probe_versions([a for a in assets if a["provider"] in ("postgresql", "apache-airflow")])
    return {"assets": assets, "ports": ports, "notes": notes, "level": "L1"}
