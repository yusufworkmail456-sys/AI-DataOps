#!/usr/bin/env bash
# Jalankan backend dev di :9150. D8: pastikan port bebas dulu.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q fastapi "uvicorn[standard]" sqlalchemy httpx pytest "psycopg[binary]" PyYAML
fi

if ss -tln | grep -q ':9150 '; then
  echo "ERROR: port 9150 sudah dipakai (D8)" >&2
  exit 1
fi

[ -f data/dataops.db ] || .venv/bin/python scripts/init_db.py

exec .venv/bin/uvicorn app.api:app --host 0.0.0.0 --port 9150 --reload
