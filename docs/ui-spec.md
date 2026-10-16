# UI Spec — AI DataOps Intelligence (target: mirip mockup user, dark)

Tech: single page, no build step. Tailwind via CDN (cdn.tailwindcss.com) + Font Awesome 6.5.1 + Google Fonts (Plus Jakarta Sans, JetBrains Mono). Config Tailwind: brand=blue scale, font sans JPS, mono JBM. Semua bahasa Indonesia.

Tokens: bg `bg-slate-950`, card `bg-slate-900 border border-slate-800 rounded-2xl`, inner `bg-slate-950/70 border-slate-800`, teks utama `text-slate-100`, sekunder `text-slate-400`, muted `text-slate-500`, aksen `blue-600/500`, sukses `emerald-500/20+text-emerald-300`, fail `rose-500/20+text-rose-300`, warn `amber-500/20+text-amber-300`, na `slate-700/60`. Font size dasar xs/13px; angka KPI text-2xl bold; label uppercase text-[11px] tracking-wider.

## Shell
- Header h-16 sticky bg-slate-900/90 blur border-b slate-800: logo kotak gradient blue→indigo ikon fa-microchip, judul "AI DataOps Intelligence" + badge mono "v0.1 PILOT MVP" (blue-500/10 border-blue-500/20), subjudul "Platform Intelijen Pipeline Data Berbasis Bukti Deterministik", selector target pilot (dot emerald pulse + "Target Pilot: PostgreSQL (Production) + Apache Airflow").
- Kanan header: persona switcher (4 tombol pill: Semua/Data Eng & DBA/SRE & Platform/Governance & FinOps; aktif bg-blue-600), badge shield "Read-Only Default" (emerald), bell dengan dot rose, avatar inisial.
- Sub-header bar bg-slate-900 border-b: nav 6 tab (ikon FA + label): topology=fa-diagram-project "Pipeline Observability & Lineage", engine=fa-square-check "Rule Engine Deterministik" + counter, agents=fa-robot "Orkestrasi AI & Supervisor (P0)", incidents=fa-triangle-exclamation(rose) "Insiden & Human-in-the-Loop" + counter approval, governance=fa-book-bookmark "Knowledge & Standar Otoritatif", maturity=fa-layer-group "Maturitas L1–L5 & Roadmap". Aktif: border-b-2 blue-500 text-blue-400. Kanan: pill "100% Verifikasi Bukti: Ketiadaan bukti telemetri ≠ kepatuhan".
- Tab switching: instant, toggle hidden, tanpa reload (sudah ada). Toast bawah-kanan (info blue, success emerald, error rose, warning amber; ikon FA; auto-hilang 3.5s).

## KPI bar (4 kartu, grid 4)
1. Status Rule Engine: angka pass-rate % + "N Pass" emerald; caption "X Fail • Y Unknown • Z N/A" — hitung dari /api control results.
2. Active Pipelines: jumlah DAG/asset Airflow + "N Degradasi" rose bila ada finding; caption versi.
3. Spesialis AI Aktif: "4 Agen" + "Supervisor P0"; caption "SRE, DE, DBA, FinOps".
4. Maturitas Operasi: "Tingkat L4" + "Diagnose" amber; caption "Menuju L5 Act (Human-in-the-Loop)".
Tiap kartu: ikon kanan dalam kotak rounded berwarna (calculator emerald, network-wired blue, users-gear purple, stairs amber).

## Tab 1 Topology
- Card judul "Topologi Data Plane & Silsilah OpenLineage (L2 Observe)" + badge "Live Heartbeat 10s" (emerald) + tombol "Refresh Metrik" (fa-arrows-rotate) & "Simulasi Anomali Pipeline" (rose).
- Panel flow bg-slate-950/80: 4 node kartu klikable (PG Core → Apache Airflow → Staging Lakehouse → BI Data Mart), masing2: label kecil mono uppercase, dot status, ikon dalam kotak (database blue, wind cyan, server indigo, chart-pie emerald), nama + id, footer 2 metrik. Node bermasalah: border rose + badge "Degradasi"; normal emerald; warn amber. Bawah: 3 label panah antar-node ("Extract & Load (CDC)", "Transform Pipeline (SQL Lock)", "Semantic Catalog Sync").
- Drawer detail node bila diklik: judul + ID evidence + deskripsi penyebab; tombol "Minta Diagnosis AI Supervisor" (blue) & "Buka Remediasi (Human-in-the-Loop)".
- Dua kolom bawah: (a) "Model Kanonis & Standarisasi Metadata (Lapisan 02)" — blok JSON mono (eventTime/producer/job/inputs/runFacets) + caption centang; (b) "Koleksi Telemetri Runtime Real-Time (Lapisan 01)" — list 3 baris evidence: dot status + nama sumber + sub + durasi/nilai kanan. Data dari evidence terbaru (fallback contoh saat kosong, tandai "contoh").

## Tab 2 Rule Engine
Header card: judul "Rule Engine Deterministik (Lapisan 04 Evaluation)" + badge "Tanpa Risiko Halusinasi LLM", caption prinsip. Filter pills: Semua/Pass/Fail/Unknown/Not Applicable + count (aktif bg-blue-600).
Tabel: kolom ID & Aturan (ID mono + deskripsi kecil), Entitas Target (chip mono), Hasil (badge status), Bukti Telemetri (mono kecil berwarna status), Rujukan Regulasi (blue), Aksi "Lihat Bukti". Baris filter per status; hover bg-slate-800/40.
Modal evidence: judul "Bukti Telemetri: <ID>", badge status, uraian, pre payload JSON + hash. Footer tutup.
Footer card: info "Engine deterministik memverifikasi fakta biner sebelum LLM memberi konteks" + latency engine.

## Tab 3 Agents
Grid 3 kolom (1 panel + chat 2 kolom):
- Panel kiri: judul "Supervisor & Agen Spesialis" + caption. Kartu Supervisor (gradient blue-950, ikon crown, badge ONLINE emerald). 4 baris agen klikable: SRE (fa-server cyan), Data Engineer (fa-code-branch purple), DBA (fa-database amber), Compliance & FinOps (fa-scale-balanced emerald) — nama + deskripsi + dot status. Footer isolasi: "Isolasi Tenant: Strict Airgap" emerald, "Akses Mutasi Data: Blocked (Read-Only)" rose.
- Chat kanan (h-[520px] flex col): header (dot ping emerald, "DataOps Verified Copilot" + badge "Penyelaras Multi-Agen", caption "Menjawab berdasarkan bukti telemetri & regulasi resmi"), area scroll pesan: bubble user bg-blue-600 kanan; balasan supervisor kiri: header "Sintesis DataOps Supervisor (Berdasarkan N Agen)" + badge bukti emerald mono, paragraf, quote per agen (border-l-2 warna agen, bg-slate-900), footer rekomendasi + tombol "Review & Setujui" (rose, pindah ke tab incidents). Quick prompts awal (3 chip). Input bawah + tombol Kirim.
- POST ke /api/chat (endpoint baru sederhana, jawaban LLM evidence-bound) — fallback jawaban deterministik dari findings bila LLM off.

## Tab 4 Incidents
Header: judul + badge "Tingkat L5 Act Berizin" rose + caption "Remediasi otomatis tanpa persetujuan eksplisit DILARANG" + chip "Audit Trail Immutability Enabled".
Kartu insiden (border-rose-500/40 bg-slate-950/80): header ID mono rose + judul + waktu/target + badge "Menunggu Approval". Grid 3: Bukti Telemetri (mono rose), Dampak Lintas Tim (amber), Remediasi Disarankan (emerald + code). Blok "Dry-Run Command Plan" (mono, langkah, chip "Zero Destructive DDL"). Baris aksi: "Otorisasi oleh: Teknisi SRE / DBA On-Duty" + tombol Tolak (slate) & "Setujui & Eksekusi Remediasi (L5 Act)" (emerald; saat MVP tombol menghasilkan toast "MVP recommendation-only — eksekusi L5 belum diaktifkan" + audit event).
Bawah: "Log Riwayat Audit (Immutable)" — list dari /api/audit-events: [SUKSES]/[VERIFIED] + aksi + approver + waktu.

## Tab 5 Governance
Judul "Standar & Repositori Pengetahuan Terkelola" + caption. Grid 4 kartu sumber: Standar Global (fa-globe blue, "21 Kontrol Aktif"), Cloud Framework (fa-cloud cyan), OpenLineage (fa-code-fork purple, "Spec v1.1.0 Parser"), Policy Internal (fa-building-shield emerald) — hover border-blue.
Bawah: "Protokol Keamanan & Perlindungan Berlapis": 3 kartu (Read-Only Default, Isolasi Tenant, Minimisasi Paparan Data).

## Tab 6 Maturity
"Kategori Strategi Integrasi": grid 5 kartu L1 Discover…L5 Act: L1-L3 emerald + "Selesai (100%)", L4 blue + "Fokus Pilot Aktif" + dot pulse, L5 slate + ikon lock + "Roadmap Fase P1".
Roadmap: grid 4 kartu P0 Fondasi Inti (badge Aktif emerald), P1 Runtime MVP (badge "Pilot Sekarang" blue), P2 Cloud & Lineage, P3 Ekspansi Multi-Cloud (badge Mendatang slate).

## Data wiring
Semua angka dari API nyata: /api/summary (baru: kpi aggregates), /api/assets, /api/findings, /api/assessment/latest, /api/audit-events, /api/integrations, /api/chat. Kalau data kosong → tampil state kosong jujur ("Belum ada evidence — hubungkan agent") KECUALI contoh ilustratif yang HARUS diberi badge "contoh/demo". Tidak boleh angka palsu tanpa label.

## Jangan
- Jangan full-page reload antar tab; jangan framework baru (React dkk); jangan hapus auth flow; jangan hardcode kredensial.
