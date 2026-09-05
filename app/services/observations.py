"""최종 회귀의 HTTP와 Kubernetes 관측값을 계산 가능한 형태로 요약한다.

샘플 1개 = 요청 REQUESTS_PER_SAMPLE회 + 파드 상태 1회. 오류율·p95는 샘플 수가 아니라
**요청 수** 기준(2026-09-05 팀 결정 B1) — 장애 구간 샘플이 2~3개일 때 1건 실패가 33~50%로 튀던 문제 해소.
"""
from __future__ import annotations

import math
import time

REQUESTS_PER_SAMPLE = 3


def take_sample(workload, namespace: str, observation: dict,
                requests: int = REQUESTS_PER_SAMPLE) -> dict:
    expected = int(observation.get("expected_status", 200))
    probes = []
    for _ in range(max(1, requests)):
        r = workload.probe_http(namespace, observation["service"], observation["path"])
        code = int(r.get("status_code") or 0)
        probes.append({
            "status_code": code,
            "latency_ms": float(r.get("latency_ms") or 0),
            "ok": code == expected,
            "error": r.get("error") or "",
        })
    state = workload.readiness(namespace)
    success = sum(p["ok"] for p in probes)
    return {
        # 샘플 수준 요약(회복 판정 루프·기존 소비자용): 요청이 전부 성공해야 request_ok
        "status_code": probes[-1]["status_code"],
        "latency_ms": max(p["latency_ms"] for p in probes),
        "request_ok": success == len(probes),
        "request_error": next((p["error"] for p in probes if p["error"]), ""),
        "request_count": len(probes),
        "success_count": success,
        "requests": probes,
        "pods_ready": int(state.get("pods_ready") or 0),
        "pods_total": int(state.get("pods_total") or 0),
        "restart_count": int(state.get("restart_count") or 0),
        "observed_at": time.time(),
    }


def _requests_of(sample: dict) -> list[dict]:
    """요청 단위 레코드 — 구형 샘플(요청 1회, requests 키 없음)도 같은 형태로."""
    if sample.get("requests"):
        return sample["requests"]
    return [{"status_code": int(sample.get("status_code") or 0),
             "latency_ms": float(sample.get("latency_ms") or 0),
             "ok": bool(sample.get("request_ok")),
             "error": sample.get("request_error") or ""}]


def summarize(samples: list[dict]) -> dict:
    if not samples:
        return {
            "observed": False,
            "sample_count": 0,
            "request_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "error_rate_pct": None,
            "p95_latency_ms": None,
            "min_ready_pods": None,
            "restart_count": None,
        }
    requests = [r for s in samples for r in _requests_of(s)]
    latencies = sorted(float(r["latency_ms"]) for r in requests)
    p95_index = max(0, math.ceil(len(latencies) * 0.95) - 1)
    successes = sum(bool(r["ok"]) for r in requests)
    return {
        "observed": True,
        "sample_count": len(samples),
        "request_count": len(requests),
        "success_count": successes,
        "failure_count": len(requests) - successes,
        "error_rate_pct": round((len(requests) - successes) / len(requests) * 100, 1),
        "p95_latency_ms": round(latencies[p95_index], 1),
        "min_ready_pods": min(int(item["pods_ready"]) for item in samples),
        "max_ready_pods": max(int(item["pods_ready"]) for item in samples),
        "restart_count": max(int(item["restart_count"]) for item in samples),
        "status_codes": _counts(int(r["status_code"]) for r in requests),
        "errors": list(dict.fromkeys(r["error"] for r in requests if r["error"])),
    }


def _counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return counts
