# AI DataOps Intelligence — Product Requirements Document (PRD)
*Referensi: diskusi ChatGPT (share 6ad1de8d), diterima 16 Okt 2026. Version/status: 0.1 — Draft for product and engineering alignment. Scope note: conceptual PRD; integrations and regulatory mappings have not yet been implemented or validated.*

## Document Control

| Field | Value |
| --- | --- |
| Product | AI DataOps Intelligence |
| Document | Product Requirements Document |
| Version/status | 0.1 — Draft for product and engineering alignment |
| Date | 15 October 2026 |
| Audience | Product, engineering, data platform, cloud, security, governance |

## 1. Product Summary

AI DataOps Intelligence mengumpulkan dan menormalisasi metadata/telemetry dari platform data dan cloud, mengevaluasi kontrol, menampilkan temuan berbasis evidence, dan menggunakan AI agents untuk menjelaskan masalah serta merekomendasikan langkah yang dapat diverifikasi.

## 2. Problem Statement

Tim mengoperasikan pipeline lintas database, orchestration tools, processing engines, cloud services, dan sistem security/governance. Bukti tersebar, troubleshooting manual, dan rekomendasi sering tidak terhubung ke knowledge otoritatif atau bukti workload.

## 3. Product Goals

- Menemukan resource yang didukung dan menampilkan status capability integrasi secara eksplisit.
- Menyediakan view pipeline health dan source-to-sink relationships sejauh evidence tersedia.
- Menjalankan pemeriksaan quality, privacy, security, governance, dan operasional secara repeatable/auditable.
- Menghasilkan penjelasan dan rekomendasi AI yang grounded pada evidence serta knowledge sources berversi.
- Memungkinkan provider/service baru ditambahkan tanpa menulis ulang shared evaluation logic.

## 4. Non-goals for MVP

- Mendukung semua layanan dari semua cloud provider.
- Remediation produksi otomatis tanpa approval.
- Menjamin lineage lengkap tanpa instrumentasi atau metadata.
- Menggantikan legal counsel atau menyatakan compliance tanpa konteks.
- Menjalankan kode/SQL arbitrer buatan AI terhadap produksi.
- Sizing resource presisi tanpa asumsi, pengukuran, atau benchmark.

## 5. Personas dan Jobs-to-be-done

| Persona | Job-to-be-done |
| --- | --- |
| Data Engineer | Menemukan job gagal/lambat, dependencies, dan source-to-sink behavior. |
| DBA | Menganalisis bottleneck dengan metrics, plans, dan configuration evidence. |
| SRE / Platform Engineer | Mengorelasikan incidents, logs, resource pressure, retries, availability. |
| Governance / Security | Menilai policy conformance, sensitive data, ownership, dan auditability. |
| Cloud / FinOps | Menemukan penggunaan tidak efisien dan trade-off biaya/performa. |
| Data Architect | Membandingkan desain dan memperkirakan resource dengan asumsi jelas. |

## 6. Terminologi Produk

| Term | Definisi |
| --- | --- |
| Provider connector | Integrasi untuk auth, account/project discovery, API behavior, retry, pagination, limits. |
| Service adapter | Logika service-specific untuk discovery, evidence collection, dan checks. |
| Integration Registry | Registry provider/service, tested versions, permissions, capabilities, limitations. |
| Canonical model | Representasi normalisasi assets, jobs, runs, evidence, metrics, lineage, findings. |
| Knowledge source | Referensi terkelola seperti dokumentasi resmi, standar, regulasi, riset, atau policy internal. |
| Control | Requirement/condition yang dapat dievaluasi terhadap evidence. |
| Finding | Masalah aktual atau indikasi masalah yang terkait ke control, asset, evidence, dan next steps. |
| Assessment run | Eksekusi berversi dari sekumpulan controls pada scope tertentu. |

## 7. Functional Requirements

### FR-01 — Integration Registry
- Sistem menyimpan provider, service, integration type, adapter version, support status, tested scope, dan limitations.
- Capability dinyatakan per integrasi: discover, observe, evaluate, diagnose, act.
- Required permissions serta alasan capability unavailable harus terlihat.
- Dukungan satu service tidak boleh ditampilkan sebagai dukungan penuh seluruh provider.

### FR-02 — Connection Management
- User berizin dapat membuat, memvalidasi, memperbarui, dan mencabut koneksi.
- Credential disimpan di luar prompt dan ordinary application records.
- Validasi koneksi melaporkan permission yang kurang tanpa mengekspos secret.
- Read-only permission menjadi default MVP.

### FR-03 — Discovery dan Canonical Model
- Asset menyimpan stable ID, tenant, provider/service, native ID, environment, owner/classification bila tersedia.
- Job/run state dinormalisasi tanpa menghilangkan source-specific ID.
- Evidence menyimpan source reference dan collection timestamp.
- Informasi unavailable atau stale ditandai eksplisit.

### FR-04 — Observability dan Pipeline View
- Tampilkan job status serta metrics/log references yang tersedia.
- Tampilkan source-to-sink flow hanya bila ada lineage/relationship evidence.
- Bedakan fakta observasi dari hubungan yang diinferensikan.
- User dapat membuka finding dan memeriksa evidence.

### FR-05 — Rule dan Assessment Engine
- Rule types awal: field_check, threshold_check, schema_check, data_profile_check, access_policy_check, lineage_check, evidence_check.
- Setiap rule memiliki ID/version, scope/applicability, evaluation method, severity, expected evidence, dan status semantics.
- Control result: pass, fail, unknown, not_applicable.
- Assessment history menyimpan versi rule/policy yang digunakan.
- Missing evidence tidak boleh menghasilkan pass.

### FR-06 — Data Compliance
- MVP mendukung internal controls untuk schema, metadata/ownership, basic data quality, dan evidence completeness.
- PII detection adalah bukti deteksi/klasifikasi, bukan otomatis bukti pelanggaran hukum.
- Regulatory mappings menyimpan jurisdiction, sector/applicability, source version, locator, review status.
- Bedakan legal obligations, voluntary frameworks, vendor recommendations, dan internal policies.
- Exceptions memiliki owner, rationale, approver, expiry, dan audit history.

### FR-07 — Knowledge & Standards Layer
- Source registry menyimpan publisher, type, URL kanonis, version, dates, applicability, rights/access classification, review status.
- Ingestion mempertahankan provenance dan source locator.
- Retrieval mendukung filter domain, teknologi, versi, workload, yurisdiksi, dan source type bila tersedia.
- Klaim material dari knowledge retrieval menyertakan source references.
- Knowledge documents, recommendation patterns, dan executable controls adalah artefak terpisah.
- Source/control dapat deprecated tanpa menghapus histori assessment.

### FR-08 — AI Agent Orchestration
- Supervisor mengklasifikasi intent dan memilih tools/workflows yang diotorisasi.
- Specialists mengembalikan claim, evidence refs, knowledge refs, uncertainty, risks, dan verification steps.
- AI menyatakan bukti tidak cukup dan tidak boleh mengarang telemetry, citation, atau control outcomes.
- Diagnosis membedakan correlation dari causation.
- Tool calls memvalidasi tenant scope dan user permission secara independen dari LLM.

### FR-09 — Findings dan Recommendations
- Finding terkait ke asset, control, assessment, evidence, knowledge version, severity, dan timestamps.
- Finding lifecycle terpisah dari control result status.
- Rekomendasi menyertakan prerequisites, impact/risk, dan verification method bila relevan.
- User dapat acknowledge, assign, comment, resolve, atau meminta reassessment sesuai role.

### FR-10 — Remediation Governance
- MVP bersifat recommendation-only kecuali action workflow disetujui terpisah.
- Action execution di masa depan membutuhkan permission scope, approval, dry-run bila memungkinkan, audit, dan post-action verification.
- Perubahan high-impact memerlukan human approval.

### FR-11 — Per-pipeline Chatbot
- Session terikat ke pipeline/asset dan permission user yang terautentikasi.
- Chatbot menjawab menggunakan findings, evidence, dan approved knowledge sources.
- Jawaban membedakan fakta, hipotesis, dan rekomendasi.
- Referensi evidence/source ditampilkan untuk kesimpulan material.

### FR-12 — Reporting dan Audit
- Assessment summary menampilkan control outcomes, findings by severity, unknown controls, dan coverage.
- Audit perubahan policy, source approvals, exceptions, permissions, dan remediation.
- Temuan dan evidence references dapat diekspor dalam format terdokumentasi.

## 8. Initial Data Model

| Entity | Minimum fields |
| --- | --- |
| assets | asset_id, tenant_id, provider, service, asset_type, native_id, environment, owner, classification, observed_at |
| integrations | integration_id, provider, service, adapter_version, support_status, capabilities, permissions, limitations |
| knowledge_sources | source_id, publisher, source_type, canonical_url, authority_scope, rights_classification |
| source_versions | version_id, source_id, version_label, published_at, effective_from/to, retrieved_at, review_status |
| controls | control_id, domain, statement, applicability, test_method, severity, version |
| evidence_records | evidence_id, tenant_id, asset_id, evidence_type, source_ref, collected_at, freshness, access_classification |
| assessment_runs | assessment_id, scope, started_at, completed_at, engine_version, policy_set_version |
| control_results | result_id, assessment_id, control_id, status, evidence_refs, evaluated_at |
| findings | finding_id, asset_id, control_id, severity, status, evidence_refs, knowledge_refs, first_seen_at, last_seen_at |
| exceptions | exception_id, finding/control, rationale, owner, approver, expiry, status |
| audit_events | event_id, tenant_id, actor, action, target, timestamp, outcome |

## 9. Non-functional Requirements

| Area | Requirement |
| --- | --- |
| Security | Tenant isolation, least privilege, secret isolation, RBAC, encryption in transit/at rest as applicable. |
| Privacy | Data minimization, avoid raw sensitive data in prompts/logs by default, configurable retention. |
| Auditability | Versioned policies, sources, adapters, assessments, approvals, actions. |
| Reliability | Connector retries, timeouts, rate-limit handling, idempotent collection where possible. |
| Extensibility | Provider-specific behavior in adapters; shared evaluators use canonical contracts. |
| Explainability | Material claims link to evidence and knowledge; uncertainty explicit. |
| Performance | Collection bounded by timeouts, API rate limits, and profiling budgets. |
| Portability | Provider-independent domain model with vendor-specific extensions preserved. |

## 10. UX Requirements

- Integration setup menampilkan connection health, required permissions, dan capability matrix.
- Pipeline page menampilkan status, lineage bila diketahui, recent findings, dan chatbot.
- Finding detail menampilkan evidence, control, source references, severity, uncertainty, verification steps.
- Compliance dashboard menampilkan pass/fail/unknown/not-applicable, coverage, severity, dan exceptions.
- Single compliance score tidak boleh menyembunyikan critical failures atau unknown controls.

## 11. MVP Acceptance Criteria

| ID | Acceptance criterion |
| --- | --- |
| AC-01 | User dapat mendaftarkan dan memvalidasi minimal satu database integration dan satu orchestrator integration. |
| AC-02 | UI menampilkan tested capabilities dan limitations tiap integration. |
| AC-03 | Resource/pipeline dapat dinilai dengan versioned controls. |
| AC-04 | Control outcomes mencakup pass, fail, unknown, not_applicable. |
| AC-05 | Missing permission/evidence tidak menghasilkan false pass. |
| AC-06 | Setiap material finding merujuk ke evidence dan versi control. |
| AC-07 | Rekomendasi AI menyertakan knowledge refs yang disetujui atau menyatakan sumber relevan tidak ditemukan. |
| AC-08 | Historical assessment mempertahankan versi sumber dan rules. |
| AC-09 | Cross-tenant access ditolak dan dicatat. |
| AC-10 | Tidak ada production remediation tanpa approval pada MVP. |

## 12. Evaluation dan Test Strategy

- Connector tests: authentication failure, permission gaps, pagination, timeout, rate limit, malformed response.
- Rule fixtures: known pass/fail/unknown/not-applicable cases.
- Security tests: tenant isolation, RBAC, secret leakage, prompt injection dari retrieved docs, tool authorization.
- Knowledge tests: retrieval relevance, source version correctness, citation validity, deprecated-source exclusion.
- AI tests: unsupported-claim rate, citation accuracy, recommendation verifiability, uncertainty handling.
- PII tests: synthetic sensitive fields dan pengukuran false positive/false negative.
- Regression tests: replay incident representatif dan bandingkan dengan expected outcomes yang telah direview.

## 13. MVP Scope Recommendation

Pilot yang direkomendasikan: PostgreSQL + Apache Airflow untuk agent-based integration, ditambah satu cloud provider dan dua atau tiga data-related service adapters. Pilih provider berdasarkan kebutuhan customer, akses test environment, API availability, dan kemampuan tim.

- Bangun Integration Registry dan capability contracts sebelum menambah banyak connector.
- Mulai dari metadata, job status, basic metrics/log references, schema checks, dan knowledge catalog kecil yang telah direview.
- Deliver satu alur lengkap: connect → discover → collect evidence → evaluate → finding → grounded explanation.
- Design playground, advanced lineage, broad multi-cloud, dan automatic remediation berada di luar MVP awal kecuali terbukti wajib.

## 14. Dependencies dan Open Decisions

| Decision | Why it matters |
| --- | --- |
| Deployment model: SaaS/self-hosted/hybrid | Credential custody, data residency, networking, operations. |
| Cloud provider/service adapters pertama | Menentukan pekerjaan integrasi dan scope pilot. |
| LLM hosting dan data policy | Menentukan apakah prompt/metadata dapat keluar dari environment customer. |
| Initial compliance jurisdiction/sector | Menentukan sumber regulasi dan proses review. |
| Database/orchestrator versions | Menentukan compatibility dan test matrix. |
| Identity/RBAC model | Dibutuhkan untuk tenant isolation dan least privilege. |
| Evidence retention policy | Memengaruhi storage cost, privacy, auditability, deletion. |
| Knowledge review ownership | Menentukan siapa yang menyetujui sources, controls, recommendation patterns. |

## 15. Risks

| Risk | Mitigasi |
| --- | --- |
| Connector scope terlalu luas | Prioritaskan berdasarkan demand, reuse, evidence coverage, effort. |
| AI hallucination | Grounded retrieval, deterministic controls, citations, evaluation suite. |
| Knowledge outdated/misapplied | Versioning, applicability metadata, review, freshness monitoring. |
| PII exposure | Minimization, redaction, isolated processing, permissions, retention. |
| False positives | Tunable rules, reviewed thresholds, exceptions, feedback. |
| Unclear compliance claims | Pisahkan legal mapping dari technical checks; tampilkan unknown. |

## 16. Definition of Done untuk MVP

- Integration contract dan capability registry terdokumentasi dan berjalan.
- Minimal dua integration paths terbukti end-to-end di test environment.
- Knowledge catalog kecil, versioned, approved, dan searchable dengan provenance.
- Setidaknya satu deterministic rule per domain awal telah diuji.
- Findings memuat evidence, source/control versions, status, dan verification guidance.
- Tenant isolation, least-privilege access, audit trail, dan secret handling telah diuji.
- Replayable evaluation suite mencakup pass, fail, unknown, dan access-denied.

## 17. Referensi Awal

- Google Cloud Well-Architected Framework: https://docs.cloud.google.com/architecture/framework
- AWS Well-Architected Framework: https://docs.aws.amazon.com/wellarchitected/latest/framework/
- NIST Privacy Framework: https://www.nist.gov/privacy-framework
- NIST Cybersecurity Framework: https://www.nist.gov/cyberframework
- OpenLineage Specification: https://github.com/OpenLineage/OpenLineage/blob/main/spec/OpenLineage.md
