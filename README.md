# AI DataOps Intelligence

Platform intelijen DataOps berbasis bukti (evidence-first): rule engine deterministik + AI agents.

- docs/proposal.md — visi & scope
- docs/prd.md — FR, acceptance criteria, DoD MVP
- docs/design.md — keputusan teknis, arsitektur, kontrak API, skema DB

## P0 scaffold

```
repo/
  app/            # FastAPI backend (models, API, rule engine)
  agent/          # Agent package (discovery, collectors, buffer)
  dashboard/      # Dashboard statis (vanilla JS)
  tests/          # pytest
  scripts/        # util (dev.sh, init_db.py)
  data/           # SQLite dataops.db (dibuat saat init)
```

## Jalankan

```
source .venv/bin/activate
pip install -e ./agent
python scripts/init_db.py
bash scripts/dev.sh            # uvicorn di :9150
# dashboard: http://localhost:9150/dataops/
```

Agent: `python -m agent.main --config agent/agent.yaml` (enrol via token, discovery, collect, push).

## Prinsip

- Missing evidence → control result `unknown`, tidak pernah `pass` (AC-05).
- Rule engine hanya 7 rule types tervalidasi (tanpa eksekusi SQL/kode arbitrer).
- tenant_id di semua tabel; query ter-scope tenant; cross-tenant ditolak + diaudit (AC-09).
- Finding lifecycle (open/acknowledged/remediating/resolved/accepted_risk) terpisah dari control result status.
- audit_events append-only (tanpa UPDATE/DELETE).
- Creds agent tidak pernah dikirim balik ke cloud setelah enrol.
