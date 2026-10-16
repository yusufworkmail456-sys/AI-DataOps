# AI DataOps Intelligence — Desain Teknis v1 (disepakati 16 Okt 2026)

## Keputusan (locked)
- D1 Use case pilot: PostgreSQL + Apache Airflow (agent-based).
- D2 Deployment: hybrid. Dashboard+backend di VPS 69.5.22.24 (ys.amital.co.id/dataops/), agent di server target. Agent PUSH outbound HTTPS; TIDAK ada inbound ke target. NAT/bridge VMware OK.
- D3 LLM: GLM via 9router endpoint 'coding' (pola sama dgn ensire/KC; SSE: strip 'data: [DONE]').
- D4 Cloud provider adapter: tunda ke P2.
- D5 Remediasi MVP: recommendation-only + UI approval flow (dry-run preview, tanpa eksekusi nyata). L5 eksekusi = fase berikut dgn allowlist command.
- D6 Repo: github.com/yusufworkmail456-sys/AI-DataOps (private). Clone lokal: /root/dataops-intelligence/repo.
- D7 UI: dark (slate-950 + biru), ikut mockup. 6 tab: topology, engine, agents, incidents, governance, maturity.
- D8 Port: 9150 (FastAPI), nginx /dataops/. Verifikasi port belum dipakai sebelum deploy.
- D9 DB backend: SQLite via SQLAlchemy (MVP), swap PostgreSQL mudah krn ORM.
- D10 Tenant: tenant_id di semua tabel sejak awal (AC-09), pilot 1 tenant.

## Arsitektur
1. AGENT (Python, systemd, di server target): discovery → collect → normalize → buffer lokal → push outbound (TLS + agent key) → pull job (assigned actions; MVP: none).
2. BACKEND (FastAPI di VPS, :9150): ingest API (verify agent key), store evidence, RULE ENGINE (jalan di cloud, bukan agent — versioning konsisten & auditable), findings, integration registry, AI supervisor API, serve dashboard.
3. DASHBOARD: vanilla JS + Tailwind-style, ikut mockup-ui.html. Tab switch instant tanpa reload penuh (preferensi user).

## Discovery agent (otomatis saat bootstrap, read-only)
1. Docker socket /var/run/docker.sock → container, image, port, health.
2. systemd list-units --type=service → monolith services.
3. ss -tlnp + /proc → listening ports + proses.
4. Signature match → Integration Registry (proses name, port default, path config, env).
5. Version probe: SELECT version(), GET /api/v1/health Airflow, --version.
Hasil: L1 Discover tanpa creds. L2+ (metrics) aktif setelah user isi read-only creds via dashboard → agent tarik terenkripsi, creds TIDAK dikirim balik ke cloud. Tool tanpa adapter → "discovered, L1 only" (jujur, FR-01).

## Kontrak API agent↔cloud
- POST /ingest/enroll {enroll_token} → {agent_key} (sekali).
- POST /ingest/discovery (X-Agent-Key) → assets upsert kanonis.
- POST /ingest/evidence (batch, idempotent by source_ref+collected_at).
- GET  /agent/config → interval, rules version, creds refs (terenkripsi).
- Semua response JSON; error = {error, code}; agent retry exponential backoff, buffer file lokal kalau unreachable.

## Canonical model (SQLite via SQLAlchemy)
assets(asset_id PK, tenant_id, provider, service, asset_type, native_id, environment, owner, classification, observed_at)
integrations(integration_id PK, provider, service, adapter_version, support_status, capabilities JSON, permissions JSON, limitations)
controls(control_id PK, version, domain, statement, applicability JSON, test_method, rule_type, params JSON, severity, knowledge_ref)
evidence_records(evidence_id PK, tenant_id, asset_id FK, evidence_type, source_ref UNIQUE, payload JSON, collected_at, freshness, access_classification)
assessment_runs(assessment_id PK, tenant_id, scope JSON, started_at, completed_at, engine_version, policy_set_version)
control_results(result_id PK, assessment_id FK, control_id FK, status pass|fail|unknown|not_applicable, evidence_refs JSON, evaluated_at)
findings(finding_id PK, tenant_id, asset_id FK, control_id FK, severity, status open|acknowledged|remediating|resolved|accepted_risk, evidence_refs JSON, knowledge_refs JSON, first_seen_at, last_seen_at)
exceptions(exception_id PK, finding_id FK, rationale, owner, approver, expiry, status)
audit_events(event_id PK, tenant_id, actor, action, target, outcome, timestamp) — append-only
users/users_sessions minimal (RBAC: admin, sre, dba, viewer) — auth session cookie.

## Rule types (7, tervalidasi, TANPA eksekusi kode arbitrer)
field_check, threshold_check, schema_check, data_profile_check, access_policy_check, lineage_check, evidence_check.
Aturan missing evidence → unknown (JANGAN pass). Unknown ≠ compliant.

## Katalog rule pilot (PG + Airflow)
PG: RULE-ENG-001 lock duration < 300s (pg_stat_activity); RULE-DBA-003 dead tuple ratio < 15% (pg_stat_user_tables); RULE-SEC-004 TLS aktif (pg_stat_ssl); RULE-GOV-009 audit purge evidence_check.
Airflow: RULE-OPR-001 DAG run success rate; RULE-OPR-002 task duration vs SLA threshold; RULE-LIN-002 lineage facets lengkap.
Target: tiap rule punya fixture test pass/fail/unknown/na (PRD §12).

## AI layer
Supervisor: klasifikasi intent → pilih tool (query findings/evidence, knowledge search) → sintesis jawaban. Kontrak output: {claims[], evidence_refs[], knowledge_refs[], uncertainty, risks[], verification_steps[]}. Jawaban wajib citation; bukti tak ada → bilang tidak ada. Prompt injection dari retrieved docs: dokumen = data, bukan instruksi.

## Knowledge layer MVP
knowledge_sources + source_versions (NIST CSF, NIST Privacy, OpenLineage spec, PG docs, Airflow docs, corp policy placeholder). Seed manual, review_status approved/deprecated. Chunks + retrieval filter domain/teknologi/versi.

## Acceptance mapping MVP = AC-01..AC-10 (PRD §11). DoD = PRD §16.
## Testing: pytest; rule fixtures; connector tests mock; security test tenant isolation; replay suite.

## Status & Next Steps
- [x] Dokumen proposal.md, prd.md, mockup-ui.html, design.md (file ini).
- [ ] P0 scaffold: FastAPI backend + models + rule engine + ingest + dashboard stub + agent pkg + installer + tests.
- [ ] Deploy VPS (9150 + nginx /dataops/ + systemd dataops-backend).
- [ ] Agent installer untuk VM target (butuh dari user: PG & Airflow versi, docker atau bare metal, read-only creds).
- [ ] P1: chatbot evidence-bound + knowledge seed.
