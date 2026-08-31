"""최종 회귀의 HTTP와 Kubernetes 관측값을 계산 가능한 형태로 요약한다."""
from __future__ import annotations

import math
import time


def take_sample(workload, namespace: str, observation: dict) -> dict:
    request = workload.probe_http(namespace, observation["service"], observation["path"])
    state = workload.readiness(namespace)
    expected = int(observation.get("expected_status", 200))
    return {
        "status_code": int(request.get("status_code") or 0),
        "latency_ms": float(request.get("latency_ms") or 0),
        "request_ok": int(request.get("status_code") or 0) == expected,
        "request_error": request.get("error") or "",
        "pods_ready": int(state.get("pods_ready") or 0),
        "pods_total": int(state.get("pods_total") or 0),
        "restart_count": int(state.get("restart_count") or 0),
        "observed_at": time.time(),
    }


def summarize(samples: list[dict]) -> dict:
    if not samples:
        return {
            "observed": False,
            "request_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "error_rate_pct": None,
            "p95_latency_ms": None,
            "min_ready_pods": None,
            "restart_count": None,
        }
    latencies = sorted(float(item["latency_ms"]) for item in samples)
    p95_index = max(0, math.ceil(len(latencies) * 0.95) - 1)
    successes = sum(bool(item["request_ok"]) for item in samples)
    return {
        "observed": True,
        "request_count": len(samples),
        "success_count": successes,
        "failure_count": len(samples) - successes,
        "error_rate_pct": round((len(samples) - successes) / len(samples) * 100, 1),
        "p95_latency_ms": round(latencies[p95_index], 1),
        "min_ready_pods": min(int(item["pods_ready"]) for item in samples),
        "max_ready_pods": max(int(item["pods_ready"]) for item in samples),
        "restart_count": max(int(item["restart_count"]) for item in samples),
        "status_codes": _counts(int(item["status_code"]) for item in samples),
        "errors": list(dict.fromkeys(item["request_error"] for item in samples if item["request_error"])),
    }


def _counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return counts
