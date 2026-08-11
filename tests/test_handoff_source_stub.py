"""StubHandoffSource 출력이 계약 모델로 그대로 검증되는지 — 조립 전 형태 보증."""
from app.services.agent.handoff_schema import (
    DeploymentInfo, IstioConfig, K8sEvent, PhaseSummary,
)
from app.services.stubs import StubHandoffSource


def test_phase_summaries_validate_against_contract():
    stub = StubHandoffSource()
    for phase in ("baseline", "fault", "recovery"):
        s = PhaseSummary(**stub.phase_summary("sut", "online-boutique", phase))
        if phase == "recovery":
            assert s.recovery_seconds is not None  # 회복 소요 시간은 recovery만
        else:
            assert s.recovery_seconds is None


def test_fault_phase_is_degraded():
    stub = StubHandoffSource()
    base = stub.phase_summary("sut", "ob", "baseline")
    fault = stub.phase_summary("sut", "ob", "fault")
    assert fault["error_rate_peak"] > base["error_rate_peak"]  # 장애 구간이 더 나쁨
    assert fault["latency_p99_peak_ms"] > base["latency_p99_peak_ms"]


def test_other_sources_validate():
    stub = StubHandoffSource()
    IstioConfig(**stub.istio_config("sut", "ob"))
    DeploymentInfo(**stub.deployment_info("sut", "ob"))
    for e in stub.events("sut", "ob"):
        K8sEvent(**e)
    logs = stub.error_logs("sut", "ob", limit=20)
    assert 0 < len(logs) <= 20
    assert len(logs) == len(set(logs))  # 중복 제거 (노션 §2-②)
