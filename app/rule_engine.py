"""Rule engine: 7 rule types tervalidasi. Missing evidence → unknown (AC-05, JANGAN pass).

Tanpa eksekusi SQL/kode arbitrer — evaluator murni baca payload JSON evidence.
"""
import json
import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("ruleengine")

ENGINE_VERSION = "0.1.0"

RULE_TYPES = (
    "field_check", "threshold_check", "schema_check", "data_profile_check",
    "access_policy_check", "lineage_check", "evidence_check",
)

PASS, FAIL, UNKNOWN, NOT_APPLICABLE = "pass", "fail", "unknown", "not_applicable"


@dataclass
class Evaluation:
    control_id: str
    control_version: int
    status: str            # pass|fail|unknown|not_applicable
    evidence_refs: list[str] = field(default_factory=list)
    reason: str = ""
    knowledge_refs: list[str] = field(default_factory=list)


def _pick(payload: dict[str, Any], path: str) -> tuple[bool, Any]:
    """Baca nilai nested via dotted path. Tidak ada evaluasi ekspresi."""
    cur: Any = payload
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return False, None
    return True, cur


def _is_missing(v: Any) -> bool:
    """Nilai 'tidak ada bukti': None, '', [], {}, "null"/"none" string."""
    if v is None:
        return True
    if isinstance(v, (str, list, dict)) and len(v) == 0:
        return True
    if isinstance(v, str) and v.strip().lower() in ("null", "none"):
        return True
    return False


def _numeric(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# --- Evaluators (murni, tanpa IO) ---

def eval_field_check(params: dict, payload: dict) -> tuple[str, str]:
    """field_check: field wajib ada & tidak kosong. params: {field, equals?, one_of?}"""
    path = params.get("field", "")
    found, value = _pick(payload, path)
    if not found or _is_missing(value):
        return UNKNOWN, f"field '{path}' tidak ada / kosong pada evidence"
    if "equals" in params and value != params["equals"]:
        return FAIL, f"'{path}'={value!r}, harus {params['equals']!r}"
    if "one_of" in params and value not in params["one_of"]:
        return FAIL, f"'{path}'={value!r}, harus salah satu dari {params['one_of']!r}"
    return PASS, f"'{path}'={value!r}"


def eval_threshold_check(params: dict, payload: dict) -> tuple[str, str]:
    """threshold_check: nilai numerik vs ambang. params: {field, op in gt|lt|gte|lte, value}"""
    path = params.get("field", "")
    op = params.get("op")
    if op not in ("gt", "lt", "gte", "lte"):
        return UNKNOWN, f"op threshold tidak valid: {op!r}"
    found, value = _pick(payload, path)
    if not found or _is_missing(value):
        return UNKNOWN, f"field '{path}' tidak ada / kosong pada evidence"
    num = _numeric(value)
    if num is None:
        return UNKNOWN, f"field '{path}' bukan numerik: {value!r}"
    thr = _numeric(params.get("value"))
    if thr is None:
        return UNKNOWN, "threshold 'value' tidak valid"
    ok = {"gt": num > thr, "lt": num < thr, "gte": num >= thr, "lte": num <= thr}[op]
    return (PASS, f"'{path}'={num} {op} {thr}") if ok else (FAIL, f"'{path}'={num} tidak {op} {thr}")


def eval_schema_check(params: dict, payload: dict) -> tuple[str, str]:
    """schema_check: keys & types pada payload/schema evidence. params: {required: {path: type}, forbidden?: [path]}"""
    required = params.get("required") or {}
    type_map = {"string": str, "number": (int, float), "integer": int,
                "boolean": bool, "array": list, "object": dict}
    missing, wrong = [], []
    for path, typ in required.items():
        found, value = _pick(payload, path)
        if not found or _is_missing(value):
            missing.append(path)
            continue
        want = type_map.get(str(typ))
        if want and not isinstance(value, want):
            wrong.append(f"{path}:{type(value).__name__}!={typ}")
    forbidden = params.get("forbidden") or []
    present_forbidden = [p for p in forbidden if _pick(payload, p)[0]]
    if missing:
        return UNKNOWN, f"schema fields tidak ada (missing evidence): {missing}"
    if wrong or present_forbidden:
        probs = wrong + [f"{p} tidak boleh ada" for p in present_forbidden]
        return FAIL, "; ".join(probs)
    return PASS, f"schema ok ({len(required)} fields)"


def eval_data_profile_check(params: dict, payload: dict) -> tuple[str, str]:
    """data_profile_check: profil numerik kolom/baris. params: {field, op, value} (sama keluarga threshold,
    tapi domain profiling: null_ratio, distinct_ratio, dst).

    Bentuk payload didukung:
      - {tables: {dead_tuple_ratio: {t1: 0.02}}} → nilai dikotak per kolom
      - {tables: {t1: 0.02}} → nilai langsung per baris
    """
    path = params.get("field", "")
    # fallback: bila path <...>.<leaf> tidak ditemukan, coba parent dict-nya
    found, value = _pick(payload, path)
    if not found and "." in path:
        parent_path, leaf = path.rsplit(".", 1)
        pfound, pvalue = _pick(payload, parent_path)
        if pfound and isinstance(pvalue, dict):
            found, value = True, pvalue
    if not found or _is_missing(value):
        return UNKNOWN, f"profile '{path}' tidak ada pada evidence"
    # dict: semua entri (kolom/leaf) harus lolos ambang
    if isinstance(value, dict):
        results = []
        for col, v in value.items():
            if isinstance(v, dict):
                continue  # level pengelompokan, bukan nilai
            num = _numeric(v)
            if num is None:
                return UNKNOWN, f"profile '{path}.{col}' bukan numerik: {v!r}"
            results.append((col, num))
        if not results:
            return UNKNOWN, f"profile '{path}' tidak berisi nilai numerik"
        thr = _numeric(params.get("value"))
        if thr is None:
            return UNKNOWN, "threshold 'value' tidak valid"
        op = params.get("op", "lte")
        bad = [c for c, n in results
               if not {"gt": n > thr, "lt": n < thr, "gte": n >= thr, "lte": n <= thr}[op]]
        return (FAIL, f"kolom melewati ambang {path} {op} {thr}: {bad}") if bad else (
            PASS, f"semua {len(results)} kolom {path} {op} {thr}")
    return eval_threshold_check(params, payload)


def eval_access_policy_check(params: dict, payload: dict) -> tuple[str, str]:
    """access_policy_check: hak akses/ssl/roles. params: {field, one_of?} atau {forbidden_users?: [..]}
    Missing → unknown; deny → fail."""
    path = params.get("field", "")
    found, value = _pick(payload, path)
    if not found or _is_missing(value):
        return UNKNOWN, f"access field '{path}' tidak ada pada evidence"
    if "forbidden_values" in params and value in params["forbidden_values"]:
        return FAIL, f"'{path}'={value!r} termasuk nilai terlarang"
    if "one_of" in params and value not in params["one_of"]:
        return FAIL, f"'{path}'={value!r}, harus salah satu dari {params['one_of']!r}"
    if "equals" in params and value != params["equals"]:
        return FAIL, f"'{path}'={value!r}, harus {params['equals']!r}"
    return PASS, f"'{path}'={value!r} sesuai policy"


def eval_lineage_check(params: dict, payload: dict) -> tuple[str, str]:
    """lineage_check: facets lineage wajib ada. params: {required_facets: [..]} pada payload.facets
    (atau payload langsung). Facet missing (key tidak ada/None) → unknown bila semua missing,
    fail bila sebagian. Facet berisi dict/list kosong tetap dianggap ADA (struktur terkirim)."""
    found, facets = _pick(payload, params.get("facets_field", "facets"))
    if not found or not isinstance(facets, dict):
        return UNKNOWN, "lineage facets tidak ada pada evidence"
    required = params.get("required_facets") or []
    missing = [f for f in required if facets.get(f) is None]
    if not required:
        return UNKNOWN, "required_facets tidak ditentukan"
    if missing and len(missing) == len(required):
        return UNKNOWN, f"facets lineage missing semua: {missing}"
    if missing:
        return FAIL, f"facets lineage tidak lengkap: {missing}"
    return PASS, f"facets lengkap: {required}"


def eval_evidence_check(params: dict, payload: dict) -> tuple[str, str]:
    """evidence_check: keberadaan/kelengkapan bukti itu sendiri (mis. audit purge).
    params: {field?, expect_exists?: bool, one_of?}. Evidence field hilang → unknown."""
    path = params.get("field", "")
    if path:
        found, value = _pick(payload, path)
        if not found or _is_missing(value):
            return UNKNOWN, f"evidence '{path}' tidak ada — tidak dapat memverifikasi"
        expect = params.get("expect_exists")
        if expect is True and _is_missing(value):
            return FAIL, f"'{path}' seharusnya ada"
        if "one_of" in params and value not in params["one_of"]:
            return FAIL, f"'{path}'={value!r}, harus salah satu dari {params['one_of']!r}"
        return PASS, f"evidence '{path}' ada: {value!r}"
    # tanpa field: payload non-kosong = bukti ada
    if _is_missing(payload):
        return UNKNOWN, "evidence kosong"
    return PASS, "evidence tersedia"


EVALUATORS = {
    "field_check": eval_field_check,
    "threshold_check": eval_threshold_check,
    "schema_check": eval_schema_check,
    "data_profile_check": eval_data_profile_check,
    "access_policy_check": eval_access_policy_check,
    "lineage_check": eval_lineage_check,
    "evidence_check": eval_evidence_check,
}


def evaluate(control, evidence: dict | None) -> Evaluation:
    """Evaluasi satu control terhadap evidence payload (dict) atau None.

    evidence None/kosong → UNKNOWN. Tidak pernah pass tanpa bukti.
    """
    ev = Evaluation(control_id=control.control_id, control_version=control.version,
                    status=UNKNOWN, reason="")
    ev.knowledge_refs = [control.knowledge_ref] if control.knowledge_ref else []
    if control.rule_type not in EVALUATORS:
        ev.status, ev.reason = UNKNOWN, f"rule_type '{control.rule_type}' tidak dikenal"
        return ev
    # applicability: provider/service mismatch → not_applicable (keputusan eksplisit, bukan missing)
    app = control.applicability or {}
    if evidence:
        payload_for_app = evidence.get("payload") or {}
        for k in ("provider", "service"):
            v = evidence.get(k, payload_for_app.get(k))
            if k in app and v not in (None, app[k]):
                ev.status, ev.reason = NOT_APPLICABLE, f"control tidak berlaku utk {k}={v!r}"
                return ev
    payload = (evidence or {}).get("payload") if isinstance(evidence, dict) else None
    if not payload or not isinstance(payload, dict) or _is_missing(payload):
        ev.status, ev.reason = UNKNOWN, "evidence tidak tersedia (missing) — unknown, bukan pass"
        return ev
    ev.evidence_refs = [str(evidence.get("source_ref"))] if isinstance(evidence, dict) and evidence.get("source_ref") else []
    status, reason = EVALUATORS[control.rule_type](control.params or {}, payload)
    ev.status, ev.reason = status, reason
    return ev


def evaluate_controls(controls: list, evidence_by_asset: dict[str, dict]) -> list[Evaluation]:
    """Evaluasi semua control. evidence_by_asset: {asset_id: evidence-dict|None}."""
    return [evaluate(c, evidence_by_asset.get(getattr(c, "_asset_id", ""), None)) for c in controls]


def catalog_seed() -> list[dict]:
    """Katalog rule pilot (design.md) — sumber seed controls."""
    return json.loads(_CATALOG_JSON)


_CATALOG_JSON = r'''
[
  {
    "control_id": "RULE-ENG-001", "version": 1, "domain": "engineering",
    "statement": "Durasi lock PostgreSQL aktif < 300 detik",
    "applicability": {"provider": "postgresql", "service": "database"},
    "test_method": "pg_stat_activity: xact_start lock duration < 300s",
    "rule_type": "threshold_check",
    "params": {"field": "max_lock_duration_s", "op": "lt", "value": 300},
    "severity": "high", "knowledge_ref": "postgresql-docs/pg_stat_activity"
  },
  {
    "control_id": "RULE-DBA-003", "version": 1, "domain": "dba",
    "statement": "Dead tuple ratio PostgreSQL < 15%",
    "applicability": {"provider": "postgresql", "service": "database"},
    "test_method": "pg_stat_user_tables: n_dead_tup/(n_live_tup+n_dead_tup) < 0.15",
    "rule_type": "data_profile_check",
    "params": {"field": "tables.dead_tuple_ratio", "op": "lt", "value": 0.15},
    "severity": "medium", "knowledge_ref": "postgresql-docs/routine-vacuuming"
  },
  {
    "control_id": "RULE-SEC-004", "version": 1, "domain": "security",
    "statement": "Koneksi PostgreSQL menggunakan TLS",
    "applicability": {"provider": "postgresql", "service": "database"},
    "test_method": "pg_stat_ssl: ssl = on untuk semua koneksi user",
    "rule_type": "access_policy_check",
    "params": {"field": "ssl_enabled", "equals": true},
    "severity": "high", "knowledge_ref": "postgresql-docs/ssl-tcp"
  },
  {
    "control_id": "RULE-GOV-009", "version": 1, "domain": "governance",
    "statement": "Audit purge memiliki evidence retention tercatat",
    "applicability": {"provider": "postgresql", "service": "database"},
    "test_method": "evidence_check: audit purge log & retention policy tersedia",
    "rule_type": "evidence_check",
    "params": {"field": "audit_purge.last_purge_at"},
    "severity": "medium", "knowledge_ref": "corp-policy/audit-retention"
  },
  {
    "control_id": "RULE-OPR-001", "version": 1, "domain": "ops",
    "statement": "Airflow DAG run success rate >= 95%",
    "applicability": {"provider": "apache-airflow", "service": "orchestration"},
    "test_method": "Airflow REST /api/v1/dags: success ratio dag run",
    "rule_type": "threshold_check",
    "params": {"field": "dag_run_success_rate", "op": "gte", "value": 0.95},
    "severity": "high", "knowledge_ref": "airflow-docs/stable-rest-api"
  },
  {
    "control_id": "RULE-OPR-002", "version": 1, "domain": "ops",
    "statement": "Durasi task Airflow dalam SLA",
    "applicability": {"provider": "apache-airflow", "service": "orchestration"},
    "test_method": "task instance duration vs SLA threshold",
    "rule_type": "threshold_check",
    "params": {"field": "max_task_duration_s", "op": "lt", "value": 3600},
    "severity": "medium", "knowledge_ref": "airflow-docs/sla"
  },
  {
    "control_id": "RULE-LIN-002", "version": 1, "domain": "lineage",
    "statement": "Facets lineage Airflow lengkap (run, task, data)",
    "applicability": {"provider": "apache-airflow", "service": "orchestration"},
    "test_method": "lineage facets: run_facets, task_facets, data_facets",
    "rule_type": "lineage_check",
    "params": {"required_facets": ["run_facets", "task_facets", "data_facets"]},
    "severity": "medium", "knowledge_ref": "openlineage-spec/facets"
  }
]
'''
