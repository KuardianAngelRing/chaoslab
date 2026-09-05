"""LocalPrometheus — 로컬(라즈베리파이 k3s) Prometheus 실조회 (PrometheusService 구현).

k3s 스택은 Istio가 없다. 관측 가능한 것은 kube-state-metrics(ready 파드·재시작)와
`prometheus.io/scrape` 어노테이션이 붙은 파드가 직접 노출하는 HTTP 메트릭
(`chaospilot_http_requests_total{status}` · `chaospilot_http_request_duration_seconds_*`)뿐이다.

접근은 RealLocalK8s._node_temps와 동일하게 **k8s API 서비스 프록시**(SSH 터널 6443 하나로 해결,
별도 port-forward 불필요). 쿼리는 실험 전용 namespace 단위(ADR-0009: ns 전체 = 앱).
HTTP 메트릭을 노출하지 않는 앱(nginx 샘플)은 rps/오류율/레이턴시가 None(즉시값) 또는 0(구간 집계)이다.
쿼리 빌더는 순수 함수(hermetic 테스트), HTTP는 LocalPrometheus만.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone

from app.services.real.prometheus import (
    _epoch, instant_by_label, instant_value, range_values, summarize,
)

_TIMEOUT = (3, 10)   # (connect, read)초 — 터널 다운 시 스트림 틱이 오래 안 멈추게
_STEP_S = 15         # k3s Prometheus scrape_interval과 동일
_PROM_SERVICE = "http:prometheus:9090"
_HTTP_TOTAL = "chaospilot_http_requests_total"
_HTTP_BUCKET = "chaospilot_http_request_duration_seconds_bucket"


def ns_selector(namespace: str) -> str:
    return f'namespace="{namespace}"'


def _quantile_q(q: float, namespace: str, window: str = "1m") -> str:
    return (f'1000 * histogram_quantile({q}, sum by (le) '
            f'(rate({_HTTP_BUCKET}{{{ns_selector(namespace)}}}[{window}])))')


def _error_rate_q(namespace: str, window: str = "1m") -> str:
    # 5xx 시리즈가 없으면 `sum()`이 빈 벡터라 나눗셈 결과도 비어 버린다 → vector(0)로 0%를 살린다.
    # 총량이 없으면(메트릭 미노출 앱) 그대로 빈 벡터 → 호출자가 None/0으로 해석.
    sel = ns_selector(namespace)
    return (f'100 * (sum(rate({_HTTP_TOTAL}{{{sel},status=~"5.."}}[{window}])) or vector(0))'
            f' / sum(rate({_HTTP_TOTAL}{{{sel}}}[{window}]))')


def local_live_queries(namespace: str) -> dict[str, str]:
    """live_snapshot용 즉시 쿼리 5종 — 키는 PrometheusService.live_snapshot 계약과 동일 (순수 함수)."""
    sel = ns_selector(namespace)
    return {
        "rps": f'sum(rate({_HTTP_TOTAL}{{{sel}}}[1m]))',
        "error_rate_pct": _error_rate_q(namespace),
        "p95_ms": _quantile_q(0.95, namespace),
        "p99_ms": _quantile_q(0.99, namespace),
        "ready_pods": f'sum(kube_pod_status_ready{{condition="true",{sel}}})',
    }


def instant_or_none(resp: dict) -> float | None:
    """즉시 쿼리 결과가 비었거나 NaN이면 None — 0(정상 무트래픽)과 '메트릭 없음'을 구분한다."""
    result = resp.get("data", {}).get("result", [])
    if not result:
        return None
    f = float(result[0]["value"][1])
    return None if math.isnan(f) else f


class LocalPrometheus:
    def __init__(self, settings):
        self.s = settings
        self._client = None

    def _api_client(self):
        from kubernetes import config  # lazy: k8s SDK

        if self._client is None:
            self._client = config.new_client_from_config(
                config_file=os.path.expanduser(self.s.local_kubeconfig))
        return self._client

    def _get(self, endpoint: str, params: dict) -> dict:
        path = (f"/api/v1/namespaces/{self.s.local_obs_namespace}/services/"
                f"{_PROM_SERVICE}/proxy/api/v1/{endpoint}")
        resp = self._api_client().call_api(
            path, "GET",
            query_params=[(k, str(v)) for k, v in params.items()],
            header_params={"Accept": "application/json"},
            auth_settings=["BearerToken"],
            _request_timeout=_TIMEOUT, _return_http_data_only=True,
            _preload_content=False)
        return json.loads(resp.data.decode("utf-8", errors="replace"))

    def _instant(self, query: str, at) -> dict:
        return self._get("query", {"query": query, "time": _epoch(at)})

    def _range(self, query: str, start, end) -> list[float]:
        return range_values(self._get("query_range", {
            "query": query, "start": _epoch(start), "end": _epoch(end), "step": _STEP_S,
        }))

    def red_metrics(self, namespace: str) -> dict:
        """네임스페이스 RED 3종 (대시보드 카드) — 메트릭 없으면 0."""
        now = datetime.now(timezone.utc)
        q = local_live_queries(namespace)
        return {
            "rate": round(instant_value(self._instant(q["rps"], now)), 2),
            "error": round(instant_value(self._instant(q["error_rate_pct"], now)), 2),
            "duration": round(instant_value(self._instant(q["p99_ms"], now)), 2),
        }

    def live_snapshot(self, namespace: str, app_name: str) -> dict:
        """now 시점 즉시값 — 시리즈 없음·조회 실패 모두 해당 키만 None (스트림은 끊기지 않는다)."""
        now = datetime.now(timezone.utc)
        out: dict = {"ts": now.isoformat()}
        for key, q in local_live_queries(namespace).items():
            try:
                v = instant_or_none(self._instant(q, now))
            except Exception:  # noqa: BLE001
                v = None
            if v is None:
                out[key] = None
            else:
                out[key] = int(v) if key == "ready_pods" else round(v, 2)
        return out

    def phase_summary(self, namespace: str, app_name: str, phase: str,
                      start, end) -> dict:
        """[start, end] 구간 집계 — PhaseSummary 계약 키. HTTP 메트릭 미노출 앱은 트래픽·레이턴시 0."""
        sel = ns_selector(namespace)
        window_s = max(int((end - start).total_seconds()), 60)

        rps = summarize(self._range(f'sum(rate({_HTTP_TOTAL}{{{sel}}}[1m]))', start, end))
        err = summarize(self._range(_error_rate_q(namespace), start, end))
        p50, p95, p99 = (summarize(self._range(_quantile_q(q, namespace), start, end))
                         for q in (0.5, 0.95, 0.99))

        dist = instant_by_label(self._instant(
            f'sum by (status) (increase({_HTTP_TOTAL}{{{sel}}}[{window_s}s]))', end), "status")
        five_xx = int(sum(v for code, v in dist.items() if code.startswith("5")))

        ready = self._range(f'sum(kube_pod_status_ready{{condition="true",{sel}}})', start, end)
        restarts = instant_value(self._instant(
            f'sum(increase(kube_pod_container_status_restarts_total{{{sel}}}[{window_s}s]))', end))

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
