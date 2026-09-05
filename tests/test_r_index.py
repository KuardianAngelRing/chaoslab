"""R = 0.4·가용성 + 0.3·레이턴시 + 0.3·복구속도 — 경계값 검증."""
from app.services.r_index import compute


def test_normal_case():
    out = compute(
        baseline={"latency_p99_avg_ms": 200.0},
        fault={"error_rate_avg": 10.0, "latency_p99_avg_ms": 400.0},
        recovery={"recovery_seconds": 60.0},
    )
    assert out["availability"] == 0.9          # 1 - 10%
    assert out["latency_score"] == 0.5         # 200/400
    assert out["recovery_score"] == 0.8        # 1 - 60/300
    assert out["r"] == round(0.4 * 0.9 + 0.3 * 0.5 + 0.3 * 0.8, 4)


def test_boundaries():
    # 에러율 100% → 가용성 0, 장애 p99=0(트래픽 없음) → 레이턴시 1, 회복 시간 없음 → 복구 0
    out = compute(
        baseline={"latency_p99_avg_ms": 0.0},
        fault={"error_rate_avg": 100.0, "latency_p99_avg_ms": 0.0},
        recovery={},
    )
    assert out["availability"] == 0.0
    assert out["latency_score"] == 1.0
    assert out["recovery_score"] == 0.0

    # 회복이 상한(300s) 초과 → 0으로 클램프, 기준 p99가 장애보다 커도 1로 클램프
    out2 = compute(
        baseline={"latency_p99_avg_ms": 500.0},
        fault={"error_rate_avg": 0.0, "latency_p99_avg_ms": 100.0},
        recovery={"recovery_seconds": 900.0},
    )
    assert out2["latency_score"] == 1.0
    assert out2["recovery_score"] == 0.0
    assert out2["availability"] == 1.0


def test_no_traffic_in_fault_window_yields_no_r():
    """팀 결정 B3: 장애 구간 HTTP 트래픽 근거가 없으면 종합 r은 None — 항목 점수는 내역용으로 유지."""
    fault = {"error_rate_avg": 0.0, "latency_p99_avg_ms": 0.0, "rps_max": 0.0, "rps_avg": 0.0,
             "http_5xx_count": 0, "status_code_dist": {}}
    out = compute(baseline={"latency_p99_avg_ms": 0.0}, fault=fault, recovery={"recovery_seconds": 6.2})
    assert out["r"] is None and out["traffic_observed"] is False and out["reason"]
    assert out["availability"] == 1.0 and out["recovery_score"] == round(1 - 6.2 / 300, 4)

    with_traffic = {**fault, "rps_max": 7.2, "status_code_dist": {"200": 2156}}
    out2 = compute(baseline={"latency_p99_avg_ms": 0.0}, fault=with_traffic, recovery={"recovery_seconds": 6.2})
    assert out2["r"] is not None and out2["traffic_observed"] is True

    # 트래픽 키가 아예 없는 요약(구형·부분)은 판단 보류 → 기존처럼 계산
    out3 = compute(baseline={}, fault={"error_rate_avg": 10.0}, recovery={})
    assert out3["r"] is not None and out3["traffic_observed"] is None
