"""Agent main: enrol via token → discovery → collect → push (buffer+retry).

Jalankan: python -m agent.main --config agent/agent.yaml [--once]
Key disimpan di agent_key.txt (lokal, 0600); TIDAK pernah dikirim balik ke cloud
setelah enrol. Creds target hanya dibaca dari config/env, tidak pernah di-payload.
"""
import argparse
import json
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

from .buffer import Buffer, flush_buffer, push_with_retry
from .collectors import (AF_EVIDENCE_TYPE, PG_EVIDENCE_TYPE, collect_airflow,
                         collect_postgresql, source_ref)
from .config import load_config
from .discovery import run_discovery

KEY_FILE = Path("agent_key.txt")


def save_key(key: str) -> None:
    KEY_FILE.write_text(key)
    KEY_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600


def load_key() -> str:
    return KEY_FILE.read_text().strip() if KEY_FILE.exists() else ""


def enroll(cfg: dict) -> str:
    """Enrol sekali via token; key disimpan lokal."""
    key = load_key()
    if key:
        return key
    token = cfg["cloud"].get("enroll_token") or os.environ.get("DATAOPS_ENROLL_TOKEN", "")
    if not token:
        print("ERROR: belum ada agent_key & enroll_token kosong", file=sys.stderr)
        sys.exit(2)
    r = push_with_retry(cfg["cloud"]["base_url"], "/ingest/enroll",
                        {"enroll_token": token, "agent_name": cfg["agent"]["name"]},
                        headers={}, max_attempts=3, ca_cert=cfg["cloud"].get("ca_cert", ""))
    if not r.get("ok"):
        print(f"ERROR enrol gagal: {r.get('error')}", file=sys.stderr)
        sys.exit(2)
    save_key(r["body"]["agent_key"])
    print("enrol sukses; agent_key disimpan lokal (agent_key.txt, 0600)")
    return r["body"]["agent_key"]


def collect_and_push(cfg: dict, key: str, buf: Buffer) -> None:
    headers = {"X-Agent-Key": key}
    base = cfg["cloud"]["base_url"]
    ca = cfg["cloud"].get("ca_cert", "")

    # 1) discovery (kanonis)
    disc = run_discovery(cfg)
    disc_payload = {"assets": disc["assets"]}
    r = push_with_retry(base, "/ingest/discovery", disc_payload, headers,
                        buffer=buf, kind="discovery", ca_cert=ca)
    print(f"discovery push: ok={r.get('ok')} assets={len(disc['assets'])} "
          f"{'(dibuffer)' if not r.get('ok') else ''}")
    for note in disc["notes"]:
        print(f"  note: {note}")

    # map native_id → asset untuk evidence
    asset_ids = [a["native_id"] for a in disc["assets"]]
    pg_asset = next((a["native_id"] for a in disc["assets"]
                     if a["provider"] == "postgresql"), asset_ids[0] if asset_ids else "unknown")
    af_asset = next((a["native_id"] for a in disc["assets"]
                     if a["provider"] == "apache-airflow"), asset_ids[0] if asset_ids else "unknown")

    # 2) collectors — degrade gracefully → evidence kosong + flag
    evidence_items = []
    cpg = cfg["collectors"]["postgresql"]
    if cpg.get("enabled", True):
        res = collect_postgresql(cpg.get("dsn", ""))
        payload = res.to_payload("postgresql", "database", pg_asset)
        if res.degraded:
            payload["evidence_status"] = "degraded"
            print(f"  pg DEGRADED: {res.reason}")
        evidence_items.append({
            "asset_native_id": pg_asset, "evidence_type": PG_EVIDENCE_TYPE,
            "source_ref": source_ref(cfg["agent"]["name"], "postgresql", pg_asset),
            "collected_at": _now(), "payload": payload,
            "freshness": "stale" if res.degraded else "fresh",
            "access_classification": "internal",
        })

    caf = cfg["collectors"]["airflow"]
    if caf.get("enabled", True):
        auth = caf.get("auth", {})
        res = collect_airflow(caf.get("base_url", ""), auth.get("username", ""),
                              auth.get("password", ""))
        payload = res.to_payload("apache-airflow", "orchestration", af_asset)
        if res.degraded:
            payload["evidence_status"] = "degraded"
            print(f"  airflow DEGRADED: {res.reason}")
        evidence_items.append({
            "asset_native_id": af_asset, "evidence_type": AF_EVIDENCE_TYPE,
            "source_ref": source_ref(cfg["agent"]["name"], "airflow", af_asset),
            "collected_at": _now(), "payload": payload,
            "freshness": "stale" if res.degraded else "fresh",
            "access_classification": "internal",
        })

    if evidence_items:
        r = push_with_retry(base, "/ingest/evidence", {"evidence": evidence_items},
                            headers, buffer=buf, kind="evidence", ca_cert=ca)
        print(f"evidence push: ok={r.get('ok')} items={len(evidence_items)} "
              f"{'(dibuffer)' if not r.get('ok') else ''}")

    # 3) flush buffer lama
    left = flush_buffer(buf, base, lambda kind: headers, ca_cert=ca)
    if left:
        print(f"buffer: {left} entry tertahan (cloud unreachable), retry cycle berikut")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    ap = argparse.ArgumentParser(description="AI DataOps agent")
    ap.add_argument("--config", default="agent/agent.yaml")
    ap.add_argument("--once", action="store_true", help="satu cycle lalu keluar")
    args = ap.parse_args()

    cfg = load_config(args.config)
    key = enroll(cfg)
    buf = Buffer(cfg["buffer"]["path"], cfg["buffer"].get("max_bytes", 52428800))

    while True:
        collect_and_push(cfg, key, buf)
        if args.once:
            break
        import time
        time.sleep(cfg["agent"].get("interval_s", 300))


if __name__ == "__main__":
    main()
