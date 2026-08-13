"""Prometheus 실조회 — Istio 표준 메트릭 + kube-state-metrics.

쿼리 빌더·응답 파서는 순수 함수(hermetic 테스트), HTTP는 RealPrometheus만.
"""
import math
from datetime import datetime, timezone

import httpx

_TIMEOUT_S = 10.0
_STEP_S = 15  # Prometheus scrapeInterval과 동일


def _epoch(dt: datetime) -> float:
    """naive datetime은 UTC로 간주 — naive .timestamp()는 로컬(KST) 해석이라 9시간 어긋남."""
    return (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt).timestamp()


def istio_selector(namespace: str, app_name: str) -> str:
    return (f'destination_workload="{app_name}",'
            f'destination_workload_namespace="{namespace}",reporter="destination"')


def range_values(resp: dict) -> list[float]:
    """query_range 첫 시리즈 → float 리스트 (NaN 제외). 시리즈 없으면 []."""
    result = resp.get("data", {}).get("result", [])
    if not result:
        return []
    out = []
    for _ts, v in result[0].get("values", []):
        f = float(v)
        if not math.isnan(f):
            out.append(f)
    return out


def instant_value(resp: dict) -> float:
    result = resp.get("data", {}).get("result", [])
    if not result:
        return 0.0
    f = float(result[0]["value"][1])
    return 0.0 if math.isnan(f) else f


def instant_by_label(resp: dict, label: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for series in resp.get("data", {}).get("result", []):
        key = series.get("metric", {}).get(label, "")
        f = float(series["value"][1])
        if key and not math.isnan(f):
            out[key] = float(int(f))  # increase()는 소수 보정치 — 건수로 절사
    return out


def summarize(values: list[float]) -> dict:
    if not values:
        return {"avg": 0.0, "min": 0.0, "max": 0.0, "peak": 0.0}
    return {
        "avg": round(sum(values) / len(values), 2),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "peak": round(max(values), 2),
    }


class RealPrometheus:
    def __init__(self, settings):
        self.s = settings

    def _get(self, path: str, params: dict) -> dict:
        r = httpx.get(f"{self.s.prometheus_url}{path}", params=params, timeout=_TIMEOUT_S)
        r.raise_for_status()
        return r.json()

    def _range(self, query: str, start, end) -> list[float]:
        return range_values(self._get("/api/v1/query_range", {
            "query": query, "start": _epoch(start), "end": _epoch(end),
            "step": _STEP_S,
        }))

    def _instant(self, query: str, at) -> dict:
        return self._get("/api/v1/query", {"query": query, "time": _epoch(at)})

    def red_metrics(self, namespace: str) -> dict:
        """네임스페이스 전체 RED 3종 (대시보드 카드) — 최근 1분 rate."""
        ns = f'destination_workload_namespace="{namespace}",reporter="destination"'
        rate_q = f'sum(rate(istio_requests_total{{{ns}}}[1m]))'
        err_q = (f'100 * sum(rate(istio_requests_total{{{ns},response_code=~"5.."}}[1m]))'
                 f' / sum(rate(istio_requests_total{{{ns}}}[1m]))')
        p99_q = (f'histogram_quantile(0.99, sum by (le) '
                 f'(rate(istio_request_duration_milliseconds_bucket{{{ns}}}[1m])))')
        now = datetime.now(timezone.utc)
        return {
            "rate": round(instant_value(self._instant(rate_q, now)), 2),
            "error": round(instant_value(self._instant(err_q, now)), 2),
            "duration": round(instant_value(self._instant(p99_q, now)), 2),
        }

    def phase_summary(self, namespace: str, app_name: str, phase: str,
                      start, end) -> dict:
        sel = istio_selector(namespace, app_name)
        window_s = max(int((end - start).total_seconds()), 60)

        rps = summarize(self._range(f'sum(rate(istio_requests_total{{{sel}}}[1m]))',
                                    start, end))
        err = summarize(self._range(
            f'100 * sum(rate(istio_requests_total{{{sel},response_code=~"5.."}}[1m]))'
            f' / sum(rate(istio_requests_total{{{sel}}}[1m]))', start, end))

        def pct(q: float) -> dict:
            return summarize(self._range(
                f'histogram_quantile({q}, sum by (le) '
                f'(rate(istio_request_duration_milliseconds_bucket{{{sel}}}[1m])))',
                start, end))

        p50, p95, p99 = pct(0.5), pct(0.95), pct(0.99)

        dist = instant_by_label(self._instant(
            f'sum by (response_code) (increase(istio_requests_total{{{sel}}}[{window_s}s]))',
            end), "response_code")
        five_xx = int(sum(v for code, v in dist.items() if code.startswith("5")))

        pod_sel = f'namespace="{namespace}",pod=~"{app_name}-.*"'
        ready = self._range(
            f'sum(kube_pod_status_ready{{condition="true",{pod_sel}}})', start, end)
        restarts = instant_value(self._instant(
            f'sum(increase(kube_pod_container_status_restarts_total{{{pod_sel}}}'
            f'[{window_s}s]))', end))

        return {
            "rps_avg": rps["avg"], "rps_min": rps["min"], "rps_max": rps["max"],
            "error_rate_avg": err["avg"], "error_rate_peak": err["peak"],
            "http_5xx_count": five_xx,
            "status_code_dist": {k: int(v) for k, v in dist.items()},
            "latency_p50_avg_ms": p50["avg"], "latency_p50_peak_ms": p50["peak"],
            "latency_p95_avg_ms": p95["avg"], "latency_p95_peak_ms": p95["peak"],
            "latency_p99_avg_ms": p99["avg"], "latency_p99_peak_ms": p99["peak"],
            "min_ready_pods": int(min(ready)) if ready else 0,
            "restart_count": int(restarts),
            "recovery_seconds": None,
        }
