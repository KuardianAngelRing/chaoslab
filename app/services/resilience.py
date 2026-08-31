"""최종 회귀 판정, 개선 전후 비교, R-1.0 계산."""
from __future__ import annotations

from statistics import mean


R_FORMULA = "R = 100 × (0.45P + 0.20E + 0.20H + 0.15T)"
R_VERSION = "R-1.0"


def evaluate_experiment(*, before: dict, during: dict, after: dict, criteria: dict,
                        injection_confirmed: bool, fault_window_completed: bool,
                        cleanup_completed: bool, recovery_seconds: float | None) -> dict:
    validity = {
        "baseline_observed": bool(before.get("observed")),
        "fault_injection_confirmed": injection_confirmed,
        "fault_window_completed": fault_window_completed,
        "cleanup_completed": cleanup_completed,
        "post_observed": bool(after.get("observed")),
    }
    checks = {
        "error_rate": _lte(during.get("error_rate_pct"), criteria["max_error_rate_pct"]),
        "p95_latency": _lte(during.get("p95_latency_ms"), criteria["max_p95_latency_ms"]),
        "ready_pods": _gte(during.get("min_ready_pods"), criteria["min_ready_pods"]),
        "post_recovered": _lte(after.get("error_rate_pct"), criteria["max_error_rate_pct"]),
        "recovery_time": _lte(recovery_seconds, criteria["max_recovery_seconds"]),
    }
    if not all(validity.values()):
        verdict = "inconclusive"
    elif all(checks.values()):
        verdict = "passed"
    else:
        verdict = "failed"
    return {
        "verdict": verdict,
        "validity": validity,
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }


def calculate_r(results: list[dict]) -> dict:
    if not results:
        return _unavailable("실행 결과가 없습니다")
    if any(item.get("status") == "inconclusive" for item in results):
        return _unavailable("판정 불가 시나리오가 있어 R 지수를 산정하지 않았습니다")

    p = sum(item.get("status") == "passed" for item in results) / len(results)
    all_checks = [passed for item in results for passed in (item.get("checks") or {}).values()]
    if not all_checks:
        return _unavailable("필수 판정 항목이 없습니다")
    e = sum(bool(value) for value in all_checks) / len(all_checks)
    health_scores = []
    recovery_scores = []
    for item in results:
        metrics = item.get("during") or {}
        criteria = item.get("criteria") or {}
        error_rate = metrics.get("error_rate_pct")
        p95 = metrics.get("p95_latency_ms")
        p95_limit = criteria.get("max_p95_latency_ms")
        recovery = item.get("recovery_seconds")
        recovery_limit = criteria.get("max_recovery_seconds")
        if None in (error_rate, p95, p95_limit, recovery, recovery_limit):
            return _unavailable("R 지수 구성값이 누락됐습니다")
        error_score = 1 - min(max(float(error_rate), 0) / 100, 1)
        latency_score = 1 - min(max(float(p95), 0) / (2 * float(p95_limit)), 1)
        health_scores.append((error_score + latency_score) / 2)
        recovery_scores.append(1 - min(max(float(recovery), 0) / float(recovery_limit), 1))
    h = mean(health_scores)
    t = mean(recovery_scores)
    score = round(100 * (0.45 * p + 0.20 * e + 0.20 * h + 0.15 * t), 1)
    return {
        "available": True,
        "version": R_VERSION,
        "formula": R_FORMULA,
        "score": score,
        "grade": "A" if score >= 85 else ("B" if score >= 70 else "C"),
        "components": {"P": round(p, 3), "E": round(e, 3), "H": round(h, 3), "T": round(t, 3)},
    }


def compare_runs(before_results: list[dict], after_results: list[dict], changes: list[dict]) -> dict:
    before_by_id = {item["scenario_experiment_id"]: item for item in before_results}
    after_by_id = {item["scenario_experiment_id"]: item for item in after_results}
    scenario_ids = [item["scenario_experiment_id"] for item in after_results]
    scenarios = []
    for scenario_id in scenario_ids:
        before = before_by_id.get(scenario_id) or {}
        after = after_by_id[scenario_id]
        scenarios.append({
            "id": scenario_id,
            "title": after.get("title") or before.get("title") or scenario_id,
            "before_verdict": before.get("status", "inconclusive"),
            "after_verdict": after.get("status", "inconclusive"),
            "before_metrics": _comparison_metrics(before),
            "after_metrics": _comparison_metrics(after),
            "improved": _is_improved(before, after),
            "failed_checks_before": before.get("failed_checks") or [],
            "failed_checks_after": after.get("failed_checks") or [],
        })
    before_r = calculate_r(before_results)
    after_r = calculate_r(after_results)
    r_delta = None
    if before_r["available"] and after_r["available"]:
        r_delta = round(after_r["score"] - before_r["score"], 1)
    return {
        "verdict": _suite_verdict(after_results),
        "before": _suite_summary(before_results),
        "after": _suite_summary(after_results),
        "scenarios": scenarios,
        "changes": changes,
        "r": {"before": before_r, "after": after_r, "delta": r_delta},
    }


def _suite_summary(results: list[dict]) -> dict:
    return {
        "total": len(results),
        "passed": sum(item.get("status") == "passed" for item in results),
        "failed": sum(item.get("status") == "failed" for item in results),
        "inconclusive": sum(item.get("status") == "inconclusive" for item in results),
        "pass_rate_pct": round(sum(item.get("status") == "passed" for item in results) / len(results) * 100, 1) if results else 0,
        "error_rate_pct": _mean_metric(results, "during", "error_rate_pct"),
        "p95_latency_ms": _mean_metric(results, "during", "p95_latency_ms"),
        "recovery_seconds": _mean_values(item.get("recovery_seconds") for item in results),
    }


def _comparison_metrics(item: dict) -> dict:
    during = item.get("during") or {}
    return {
        "error_rate_pct": during.get("error_rate_pct"),
        "p95_latency_ms": during.get("p95_latency_ms"),
        "min_ready_pods": during.get("min_ready_pods"),
        "restart_delta": item.get("restart_delta"),
        "recovery_seconds": item.get("recovery_seconds"),
    }


def _is_improved(before: dict, after: dict) -> bool:
    rank = {"inconclusive": 0, "failed": 1, "passed": 2}
    if rank.get(after.get("status"), 0) > rank.get(before.get("status"), 0):
        return True
    before_error = (before.get("during") or {}).get("error_rate_pct")
    after_error = (after.get("during") or {}).get("error_rate_pct")
    return before_error is not None and after_error is not None and after_error < before_error


def _suite_verdict(results: list[dict]) -> str:
    if any(item.get("status") == "inconclusive" for item in results):
        return "inconclusive"
    return "passed" if results and all(item.get("status") == "passed" for item in results) else "failed"


def _mean_metric(results: list[dict], phase: str, key: str) -> float | None:
    return _mean_values((item.get(phase) or {}).get(key) for item in results)


def _mean_values(values) -> float | None:
    actual = [float(value) for value in values if value is not None]
    return round(mean(actual), 1) if actual else None


def _lte(value, limit) -> bool:
    return value is not None and float(value) <= float(limit)


def _gte(value, limit) -> bool:
    return value is not None and float(value) >= float(limit)


def _unavailable(reason: str) -> dict:
    return {"available": False, "version": R_VERSION, "formula": R_FORMULA, "reason": reason,
            "score": None, "grade": None, "components": {}}
