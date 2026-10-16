"""Rule fixtures: ≥1 rule per rule type dengan 4 status (pass/fail/unknown/not_applicable)."""
import pytest

from app.rule_engine import (FAIL, NOT_APPLICABLE, PASS, UNKNOWN, catalog_seed,
                             eval_access_policy_check, eval_data_profile_check,
                             eval_evidence_check, eval_field_check,
                             eval_lineage_check, eval_schema_check,
                             eval_threshold_check, evaluate)

# --- stub control untuk unit test evaluator murni ---

class C:
    def __init__(self, control_id="T-1", version=1, rule_type="threshold_check",
                 params=None, applicability=None, knowledge_ref=""):
        self.control_id, self.version = control_id, version
        self.rule_type, self.params = rule_type, params or {}
        self.applicability = applicability or {}
        self.knowledge_ref = knowledge_ref


def ev(control, payload, source_ref="src-1"):
    return evaluate(control, {"payload": payload, "source_ref": source_ref} if payload else None)


class TestThresholdCheck:
    """RULE-ENG-001 & RULE-OPR-001/002 keluarga."""

    def test_pass(self):
        c = C(params={"field": "max_lock_duration_s", "op": "lt", "value": 300})
        assert ev(c, {"max_lock_duration_s": 42}).status == PASS

    def test_fail(self):
        c = C(params={"field": "max_lock_duration_s", "op": "lt", "value": 300})
        assert ev(c, {"max_lock_duration_s": 900}).status == FAIL

    def test_unknown_missing(self):
        c = C(params={"field": "max_lock_duration_s", "op": "lt", "value": 300})
        assert ev(c, {"other": 1}).status == UNKNOWN
        assert ev(c, {"max_lock_duration_s": None}).status == UNKNOWN

    def test_unknown_no_evidence(self):
        c = C(params={"field": "x", "op": "lt", "value": 1})
        assert ev(c, None).status == UNKNOWN

    def test_not_applicable(self):
        c = C(params={"field": "x", "op": "lt", "value": 1},
              applicability={"provider": "postgresql"})
        assert ev(c, {"provider": "apache-airflow", "x": 5}).status == NOT_APPLICABLE


class TestDataProfileCheck:
    """RULE-DBA-003 dead tuple ratio."""

    def test_pass(self):
        c = C(rule_type="data_profile_check", params={"field": "tables.dead_tuple_ratio", "op": "lt", "value": 0.15})
        assert ev(c, {"tables": {"dead_tuple_ratio": {"t1": 0.02, "t2": 0.10}}}).status == PASS

    def test_fail(self):
        c = C(rule_type="data_profile_check", params={"field": "tables.dead_tuple_ratio", "op": "lt", "value": 0.15})
        r = ev(c, {"tables": {"dead_tuple_ratio": {"t1": 0.02, "t2": 0.40}}})
        assert r.status == FAIL and "t2" in r.reason

    def test_unknown(self):
        c = C(rule_type="data_profile_check", params={"field": "tables.dead_tuple_ratio", "op": "lt", "value": 0.15})
        assert ev(c, {}).status == UNKNOWN
        assert ev(c, {"tables": {"dead_tuple_ratio": {"t1": "n/a"}}}).status == UNKNOWN

    def test_na(self):
        c = C(rule_type="data_profile_check", params={"field": "tables.dead_tuple_ratio", "op": "lt", "value": 0.15},
              applicability={"provider": "postgresql"})
        assert ev(c, {"provider": "mysql", "tables": {}}).status == NOT_APPLICABLE


class TestAccessPolicyCheck:
    """RULE-SEC-004 TLS."""

    def test_pass(self):
        c = C(rule_type="access_policy_check", params={"field": "ssl_enabled", "equals": True})
        assert ev(c, {"ssl_enabled": True}).status == PASS

    def test_fail(self):
        c = C(rule_type="access_policy_check", params={"field": "ssl_enabled", "equals": True})
        assert ev(c, {"ssl_enabled": False}).status == FAIL

    def test_unknown(self):
        c = C(rule_type="access_policy_check", params={"field": "ssl_enabled", "equals": True})
        assert ev(c, {}).status == UNKNOWN

    def test_na(self):
        c = C(rule_type="access_policy_check", params={"field": "ssl_enabled", "equals": True},
              applicability={"provider": "postgresql"})
        assert ev(c, {"provider": "apache-airflow", "ssl_enabled": True}).status == NOT_APPLICABLE


class TestEvidenceCheck:
    """RULE-GOV-009 audit purge."""

    def test_pass(self):
        c = C(rule_type="evidence_check", params={"field": "audit_purge.last_purge_at"})
        assert ev(c, {"audit_purge": {"last_purge_at": "2026-10-01T00:00:00Z"}}).status == PASS

    def test_fail_forbidden(self):
        c = C(rule_type="evidence_check",
              params={"field": "purge_mode", "one_of": ["retention_aware"]})
        assert ev(c, {"purge_mode": "hard_delete"}).status == FAIL

    def test_unknown(self):
        c = C(rule_type="evidence_check", params={"field": "audit_purge.last_purge_at"})
        assert ev(c, {"audit_purge": {}}).status == UNKNOWN
        assert ev(c, None).status == UNKNOWN

    def test_na(self):
        c = C(rule_type="evidence_check", params={"field": "audit_purge.last_purge_at"},
              applicability={"provider": "postgresql"})
        assert ev(c, {"provider": "docker"}).status == NOT_APPLICABLE


class TestFieldCheck:
    def test_pass(self):
        c = C(rule_type="field_check", params={"field": "meta.owner", "one_of": ["data-eng", "platform"]})
        assert ev(c, {"meta": {"owner": "data-eng"}}).status == PASS

    def test_fail(self):
        c = C(rule_type="field_check", params={"field": "meta.owner", "one_of": ["data-eng"]})
        assert ev(c, {"meta": {"owner": "nobody"}}).status == FAIL

    def test_unknown(self):
        c = C(rule_type="field_check", params={"field": "meta.owner"})
        assert ev(c, {"meta": {}}).status == UNKNOWN

    def test_na(self):
        c = C(rule_type="field_check", params={"field": "x"},
              applicability={"service": "database"})
        assert ev(c, {"service": "orchestration", "x": 1}).status == NOT_APPLICABLE


class TestSchemaCheck:
    def test_pass(self):
        c = C(rule_type="schema_check",
              params={"required": {"col_a": "string", "col_b": "number"}})
        assert ev(c, {"col_a": "x", "col_b": 1}).status == PASS

    def test_fail(self):
        c = C(rule_type="schema_check",
              params={"required": {"col_a": "string"}, "forbidden": ["ssn"]})
        r = ev(c, {"col_a": "x", "ssn": "123"})
        assert r.status == FAIL and "ssn" in r.reason

    def test_unknown_on_missing_field(self):
        c = C(rule_type="schema_check", params={"required": {"col_a": "string"}})
        # field wajib tak ada = missing evidence → unknown (bukan fail: bisa belum terkumpul)
        assert ev(c, {"col_b": 1}).status == UNKNOWN

    def test_fail_wrong_type(self):
        c = C(rule_type="schema_check", params={"required": {"col_a": "number"}})
        assert ev(c, {"col_a": "not-a-number"}).status == FAIL

    def test_na(self):
        c = C(rule_type="schema_check", params={"required": {"a": "string"}},
              applicability={"provider": "postgresql"})
        assert ev(c, {"provider": "docker", "a": "x"}).status == NOT_APPLICABLE


class TestLineageCheck:
    def test_pass(self):
        c = C(rule_type="lineage_check", params={"required_facets": ["run_facets", "task_facets", "data_facets"]})
        assert ev(c, {"facets": {"run_facets": {}, "task_facets": {}, "data_facets": {}}}).status == PASS

    def test_fail_incomplete(self):
        c = C(rule_type="lineage_check", params={"required_facets": ["run_facets", "task_facets", "data_facets"]})
        r = ev(c, {"facets": {"run_facets": {}, "task_facets": {}}})
        assert r.status == FAIL and "data_facets" in r.reason

    def test_unknown_empty(self):
        c = C(rule_type="lineage_check", params={"required_facets": ["run_facets"]})
        assert ev(c, {"facets": {}}).status == UNKNOWN
        assert ev(c, None).status == UNKNOWN

    def test_na(self):
        c = C(rule_type="lineage_check", params={"required_facets": ["f"]},
              applicability={"provider": "apache-airflow"})
        assert ev(c, {"provider": "postgresql", "facets": {}}).status == NOT_APPLICABLE


def test_catalog_seed_7_rules():
    """Katalog pilot: 7 rule (design.md) dengan rule_type tervalidasi."""
    from app.rule_engine import RULE_TYPES
    seed = catalog_seed()
    ids = {c["control_id"] for c in seed}
    assert ids == {"RULE-ENG-001", "RULE-DBA-003", "RULE-SEC-004", "RULE-GOV-009",
                   "RULE-OPR-001", "RULE-OPR-002", "RULE-LIN-002"}
    assert len(seed) == 7
    assert all(c["rule_type"] in RULE_TYPES for c in seed)


def test_no_arbitrary_exec_rule_type():
    """Rule type di luar 7 tervalidasi ditolak → unknown (bukan eksekusi)."""
    c = C(rule_type="arbitrary_sql", params={"sql": "DROP TABLE x"})
    r = evaluate(c, {"payload": {"a": 1}, "source_ref": "s"})
    assert r.status == UNKNOWN
