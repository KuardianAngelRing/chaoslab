"""가설 수립 계약 — round-trip · extra=forbid (handoff_schema 테스트 미러)."""
import pytest
from pydantic import ValidationError

from app.services.agent.hypothesis_schema import (
    CandidateProposal,
    DetailingResult,
    HypothesisInputPayload,
)


def _payload(**over) -> HypothesisInputPayload:
    base = dict(
        app={"name": "demo", "env": "k3s", "port": 8080, "health_path": "/healthz"},
        manifest_yaml="kind: Deployment", manifest_findings=[], allowed_chaos=[],
        goal_text="", past_experiments=[], candidate_count=5,
    )
    base.update(over)
    return HypothesisInputPayload(**base)


def test_input_payload_round_trip():
    p = _payload(goal_text="60초 안에 정상화")
    assert HypothesisInputPayload(**p.model_dump()) == p
    assert p.schema_version == "1.0"


def test_candidate_has_no_params_field():
    # 2단 구조: 1차 출력에 params 금지 — extra=forbid가 막는다
    with pytest.raises(ValidationError):
        CandidateProposal(title="t", chaos_type="pod-kill", target_workload="w",
                          hypothesis="h", expected_impact="i", params={})


def test_extra_field_forbidden():
    with pytest.raises(ValidationError):
        _payload(unknown_field=1)


def test_detailing_result_defaults():
    d = DetailingResult(params={"duration_s": 60})
    assert d.rationale == ""
