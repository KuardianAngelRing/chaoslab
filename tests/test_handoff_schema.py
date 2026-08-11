"""전달 데이터 계약 단위 테스트 — 노션 §2 매핑 필드·엄격성 검증."""
import pytest
from pydantic import ValidationError

from app.services.agent.handoff_schema import AgentHandoffPayload, PhaseSummary


def summary_kwargs(**over) -> dict:
    """유효한 PhaseSummary 인자 한 벌 (테스트 공용)."""
    base = dict(
        rps_avg=42.0, rps_min=30.0, rps_max=55.0,
        error_rate_avg=0.4, error_rate_peak=1.2, http_5xx_count=3,
        status_code_dist={"200": 1200, "503": 3},
        latency_p50_avg_ms=35.0, latency_p50_peak_ms=60.0,
        latency_p95_avg_ms=120.0, latency_p95_peak_ms=180.0,
        latency_p99_avg_ms=200.0, latency_p99_peak_ms=310.0,
        min_ready_pods=3, restart_count=0,
    )
    base.update(over)
    return base


def test_phase_summary_valid():
    s = PhaseSummary(**summary_kwargs())
    assert s.recovery_seconds is None  # recovery 단계만 채우는 선택 필드


def test_phase_summary_rejects_unknown_field():
    with pytest.raises(ValidationError):
        PhaseSummary(**summary_kwargs(), typo_field=1)


def test_error_log_samples_max_20():
    """노션 §2-②: 에러 로그 샘플은 최대 20개."""
    with pytest.raises(ValidationError):
        AgentHandoffPayload.model_validate(
            {"error_log_samples": [f"log {i}" for i in range(21)]}
        )


def test_payload_requires_all_sections():
    """9개 섹션 중 하나라도 빠지면 거부 — 계약의 이빨."""
    with pytest.raises(ValidationError):
        AgentHandoffPayload.model_validate({"schema_version": "1.0"})
