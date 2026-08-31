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
