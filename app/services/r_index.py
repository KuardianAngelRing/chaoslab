"""R지수 계산 — 순수 함수 (IO 없음). R = 0.4·가용성 + 0.3·레이턴시점수 + 0.3·복구속도.

입력 dict 키는 PhaseSummary 계약(handoff_schema.py)과 동일:
error_rate_avg(%), latency_p99_avg_ms, recovery_seconds.
"""
WEIGHTS = {"availability": 0.4, "latency": 0.3, "recovery": 0.3}
RECOVERY_CAP_S = 300.0  # 5분 내 회복 기준 — 즉시 회복=1, 상한 초과=0


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def compute(baseline: dict, fault: dict, recovery: dict) -> dict:
    availability = _clamp01(1.0 - float(fault.get("error_rate_avg") or 0.0) / 100.0)

    fault_p99 = float(fault.get("latency_p99_avg_ms") or 0.0)
    base_p99 = float(baseline.get("latency_p99_avg_ms") or 0.0)
    latency_score = 1.0 if fault_p99 <= 0 else _clamp01(base_p99 / fault_p99)

    rec_s = recovery.get("recovery_seconds")
    recovery_score = 0.0 if rec_s is None else _clamp01(1.0 - float(rec_s) / RECOVERY_CAP_S)

    r = (WEIGHTS["availability"] * availability
         + WEIGHTS["latency"] * latency_score
         + WEIGHTS["recovery"] * recovery_score)
    return {
        "availability": round(availability, 4),
        "latency_score": round(latency_score, 4),
        "recovery_score": round(recovery_score, 4),
        "r": round(r, 4),
    }
