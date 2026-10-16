"""Config agent: YAML file + env override (DATAOPS_*)."""
import os
from pathlib import Path

import yaml

DEFAULTS = {
    "cloud": {"base_url": "http://localhost:9150", "enroll_token": "", "ca_cert": ""},
    "buffer": {"path": "agent_buffer.jsonl", "max_bytes": 52428800},
    "agent": {"name": "agent-1", "interval_s": 300},
    "collectors": {
        "postgresql": {"enabled": True, "dsn": ""},
        "airflow": {"enabled": True, "base_url": "",
                    "auth": {"username": "", "password": ""}},
    },
    "discovery": {"docker_socket": "/var/run/docker.sock", "enable_docker": True,
                  "enable_systemd": True, "enable_ports": True},
}


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | None = None) -> dict:
    cfg = _merge(DEFAULTS, {})
    if path and Path(path).exists():
        with open(path) as f:
            cfg = _merge(cfg, yaml.safe_load(f) or {})
    # env override
    cfg["cloud"]["base_url"] = os.environ.get("DATAOPS_CLOUD_URL", cfg["cloud"]["base_url"])
    cfg["cloud"]["enroll_token"] = os.environ.get("DATAOPS_ENROLL_TOKEN",
                                                  cfg["cloud"].get("enroll_token", ""))
    cfg["agent"]["name"] = os.environ.get("DATAOPS_AGENT_NAME", cfg["agent"]["name"])
    pg = cfg["collectors"]["postgresql"]
    pg["dsn"] = os.environ.get("DATAOPS_PG_DSN", pg.get("dsn", ""))
    af = cfg["collectors"]["airflow"]
    af["base_url"] = os.environ.get("DATAOPS_AIRFLOW_URL", af.get("base_url", ""))
    af["auth"]["username"] = os.environ.get("DATAOPS_AIRFLOW_USER", af["auth"].get("username", ""))
    af["auth"]["password"] = os.environ.get("DATAOPS_AIRFLOW_PASSWORD",
                                            af["auth"].get("password", ""))
    cfg["buffer"]["path"] = os.environ.get("DATAOPS_BUFFER_PATH", cfg["buffer"]["path"])
    return cfg
