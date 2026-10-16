"""Buffer JSONL lokal (cloud unreachable) + push retry exponential backoff."""
import json
import os
import time
from pathlib import Path

import httpx


class Buffer:
    """JSONL append-only; entries dipush lalu di-truncate setelah sukses."""

    def __init__(self, path: str, max_bytes: int = 52428800):
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, kind: str, data: dict) -> None:
        """Tambah entry. Buffer penuh → drop entry terlama (data loss dijaga: bukti
        di-push ulang cycle berikut; drop hanya bila > max_bytes)."""
        if self.path.exists() and self.path.stat().st_size > self.max_bytes:
            lines = self.path.read_text().splitlines(keepends=True)
            keep = lines[len(lines) // 2:]  # buang paruh terlama
            self.path.write_text("".join(keep))
        with open(self.path, "a") as f:
            f.write(json.dumps({"kind": kind, "data": data}) + "\n")

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text().splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # skip baris rusak (crash saat tulis)
        return out

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()

    def __len__(self) -> int:
        return len(self.read_all())


def push_with_retry(base_url: str, path: str, payload: dict, headers: dict,
                    buffer: Buffer | None = None, kind: str = "",
                    max_attempts: int = 5, ca_cert: str = "") -> dict:
    """POST dengan exponential backoff. Gagal total → simpan ke buffer (kalau diberikan).

    Return {ok, status, attempts, buffered}.
    """
    url = f"{base_url.rstrip('/')}{path}"
    verify = ca_cert if ca_cert else True
    last_err = ""
    for attempt in range(1, max_attempts + 1):
        try:
            r = httpx.post(url, json=payload, headers=headers, timeout=15, verify=verify)
            if r.status_code < 300:
                return {"ok": True, "status": r.status_code, "attempts": attempt, "body": r.json()}
            last_err = f"HTTP {r.status_code}: {r.text[:200]}"
            if r.status_code in (400, 401, 403, 422):
                break  # tidak ada gunanya retry error client
        except (httpx.HTTPError, OSError) as e:
            last_err = f"{type(e).__name__}: {e}"
        if attempt < max_attempts:
            time.sleep(min(2 ** attempt, 60))
    if buffer is not None and kind:
        buffer.append(kind, payload)
    return {"ok": False, "error": last_err, "attempts": max_attempts, "buffered": buffer is not None}


def flush_buffer(buffer: Buffer, base_url: str, headers_for, ca_cert: str = "") -> int:
    """Push ulang semua entry buffer. Sukses semua → clear. Return jumlah entry tersisa."""
    entries = buffer.read_all()
    if not entries:
        return 0
    remaining: list[dict] = []
    for e in entries:
        r = push_with_retry(base_url, _path_for(e["kind"]), e["data"],
                            headers_for(e["kind"]), buffer=None, ca_cert=ca_cert,
                            max_attempts=2)
        if not r.get("ok"):
            remaining.append(e)
    if remaining:
        buffer.clear()
        for e in remaining:
            buffer.append(e["kind"], e["data"])
        return len(remaining)
    buffer.clear()
    return 0


def _path_for(kind: str) -> str:
    return {"discovery": "/ingest/discovery", "evidence": "/ingest/evidence"}.get(kind, "/ingest/evidence")
