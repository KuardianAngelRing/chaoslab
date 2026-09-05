"""R지수 계산 — 순수 함수 (IO 없음). R = 0.4·가용성 + 0.3·레이턴시점수 + 0.3·복구속도.

입력 dict 키는 PhaseSummary 계약(handoff_schema.py)과 동일:
error_rate_avg(%), latency_p99_avg_ms, recovery_seconds.
"""
WEIGHTS = {"availability": 0.4, "latency": 0.3, "recovery": 0.3}
RECOVERY_CAP_S = 300.0  # 5분 내 회복 기준 — 즉시 회복=1, 상한 초과=0


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def traffic_observed(fault: dict) -> bool | None:
    """장애 구간에 HTTP 트래픽 근거가 있는가. 트래픽 키 자체가 없는(구형·부분) 요약은 None(판단 보류)."""
    keys = ("rps_max", "rps_avg", "http_5xx_count", "status_code_dist")
    if not any(k in fault for k in keys):
        return None
    return (float(fault.get("rps_max") or 0) > 0 or float(fault.get("rps_avg") or 0) > 0
            or int(fault.get("http_5xx_count") or 0) > 0
            or bool(sum((fault.get("status_code_dist") or {}).values())))


def compute(baseline: dict, fault: dict, recovery: dict) -> dict:
    """항목 점수는 항상 계산(핸드오프 내역용). 종합 r은 장애 구간 트래픽이 없으면 None(팀 결정 B3) —
    HTTP 메트릭 미노출 앱(k3s nginx)은 오류율 0·p99 0으로 가용성·레이턴시가 자동 만점이 돼 근거 없는 고점이 나온다."""
    availability = _clamp01(1.0 - float(fault.get("error_rate_avg") or 0.0) / 100.0)

    fault_p99 = float(fault.get("latency_p99_avg_ms") or 0.0)
    base_p99 = float(baseline.get("latency_p99_avg_ms") or 0.0)
    latency_score = 1.0 if fault_p99 <= 0 else _clamp01(base_p99 / fault_p99)

    rec_s = recovery.get("recovery_seconds")
    recovery_score = 0.0 if rec_s is None else _clamp01(1.0 - float(rec_s) / RECOVERY_CAP_S)

    observed = traffic_observed(fault)
    r = (WEIGHTS["availability"] * availability
         + WEIGHTS["latency"] * latency_score
         + WEIGHTS["recovery"] * recovery_score)
    return {
        "availability": round(availability, 4),
        "latency_score": round(latency_score, 4),
        "recovery_score": round(recovery_score, 4),
        "r": None if observed is False else round(r, 4),
        "traffic_observed": observed,
        "reason": "" if observed is not False else "장애 구간 HTTP 트래픽 없음 — 가용성·레이턴시 근거 부재로 미산정",
    }
