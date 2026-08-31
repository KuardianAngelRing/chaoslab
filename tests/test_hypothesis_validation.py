"""생성·detailing 검증 + 교정 재시도 1회 — Stub·Real 공통 함수."""
import pytest

from app.services.agent.hypothesis_schema import CandidateProposal
from app.services.agent.hypothesis_validation import (
    HypothesisValidationError,
    run_detailing,
    run_generation,
    validate_candidates,
)
from app.services.chaos_specs import CHAOS_SPECS
from app.services.stubs import StubHypothesisAgent


def _cand(**over) -> dict:
    base = dict(title="파드 강제 종료 검증", chaos_type="pod-kill",
                target_workload="order-api",
                hypothesis="파드가 강제 종료되면 요청이 실패할 것이다",
                expected_impact="오류율이 잠시 상승할 것으로 예상돼요")
    base.update(over)
    return base


def test_unknown_chaos_type_dropped():
    survivors, errors = validate_candidates([_cand(chaos_type="DiskChaos")])
    assert survivors == [] and any("chaos_type" in e for e in errors)


def test_duplicate_pair_dropped():
    survivors, errors = validate_candidates([_cand(), _cand(title="같은 대상 같은 유형")])
    assert len(survivors) == 1 and any("중복" in e for e in errors)


def test_existing_pairs_block_freeform_duplicates():
    survivors, _ = validate_candidates([_cand()], existing_pairs={("order-api", "pod-kill")})
    assert survivors == []


def test_short_narrative_dropped():
    survivors, errors = validate_candidates([_cand(hypothesis="짧음")])
    assert survivors == [] and any("짧음" in e for e in errors)


def test_non_list_output_rejected():
    survivors, errors = validate_candidates({"not": "a list"})
    assert survivors == [] and errors


class _RetryAgent:
    """1차는 무효 출력, 2차(feedback 포함)는 유효 — 재시도 경로 검증."""

    def __init__(self, good):
        self.calls = 0
        self.good = good

    def generate(self, payload, feedback=""):
        self.calls += 1
        return [] if self.calls == 1 else self.good

    def detail(self, payload, candidate, feedback=""):
        self.calls += 1
        if self.calls == 1:
            return {"params": {"latency_ms": "5", "duration_s": "60"}}  # 범위 이탈
        return {"params": {"latency_ms": "200", "duration_s": "60"}, "rationale": "근거"}


def test_run_generation_retries_once_then_succeeds():
    agent = _RetryAgent(good=[_cand()])
    assert len(run_generation(agent, payload=None)) == 1
    assert agent.calls == 2


def test_run_generation_fails_after_retry():
    agent = _RetryAgent(good=[])
    with pytest.raises(HypothesisValidationError):
        run_generation(agent, payload=None)


def test_run_detailing_retries_then_normalizes():
    agent = _RetryAgent(good=None)
    candidate = CandidateProposal(**_cand(chaos_type="network-delay"))
    params, rationale = run_detailing(agent, None, candidate)
    assert agent.calls == 2
    assert params == {"action": "delay", "latency_ms": 200, "duration_s": 60}
    assert rationale == "근거"


def test_run_detailing_fails_after_retry():
    class _Bad:
        def detail(self, payload, candidate, feedback=""):
            return {"params": {"latency_ms": "1", "duration_s": "60"}}

    with pytest.raises(HypothesisValidationError):
        run_detailing(_Bad(), None, CandidateProposal(**_cand(chaos_type="network-delay")))


def test_stub_agent_passes_common_validation():
    """Stub 출력도 Real과 같은 검증을 통과해야 함 — 9종 전 유형 detail 포함."""
    from app.services.agent.hypothesis_schema import HypothesisInputPayload

    payload = HypothesisInputPayload(
        app={"name": "demo", "env": "k3s", "port": 8080, "health_path": "/healthz"},
        manifest_yaml="", manifest_findings=[], allowed_chaos=[],
        past_experiments=[], candidate_count=3)
    agent = StubHypothesisAgent()
    candidates = run_generation(agent, payload)
    assert len(candidates) == 3

    for chaos_type in CHAOS_SPECS:
        candidate = CandidateProposal(**_cand(chaos_type=chaos_type))
        params, _ = run_detailing(agent, payload, candidate)
        assert params["action"] == CHAOS_SPECS[chaos_type]["action"]
