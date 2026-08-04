"""R지수 구성요소 계산 — 순수 함수 (IO 없음). 산식: R = 0.4·가용성 + 0.3·레이턴시점수 + 0.3·복구속도.

목업/Slice 5 공용. 정규화 기준:
- 가용성 = 1 - fault 구간 에러율(%)/100
- 레이턴시점수 = baseline p99 / fault p99 (baseline보다 빨라도 최대 1)
- 복구속도 = 1 - TTR(s)/300 (5분 이상 걸리면 0점)
"""

_MAX_TTR_S = 300.0


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def r_components(baseline: dict, fault: dict, recovery: dict) -> dict | None:
    """세 단계 metrics dict → 구성요소·R. fault 스냅샷이 없으면 None (계산 불가)."""
    if not fault:
        return None
    availability = _clamp(1.0 - float(fault.get("error", 0.0)) / 100.0)
    base_p99 = float(baseline.get("p99", 0.0)) if baseline else 0.0
    fault_p99 = float(fault.get("p99", 0.0))
    latency = _clamp(base_p99 / fault_p99) if base_p99 > 0 and fault_p99 > 0 else 0.0
    ttr = recovery.get("ttr_s") if recovery else None
    recovery_speed = _clamp(1.0 - float(ttr) / _MAX_TTR_S) if ttr is not None else 0.0
    r = 0.4 * availability + 0.3 * latency + 0.3 * recovery_speed
    return {
        "availability": round(availability, 2),
        "latency_score": round(latency, 2),
        "recovery_speed": round(recovery_speed, 2),
        "r": round(r, 2),
    }
