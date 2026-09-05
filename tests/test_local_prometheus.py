"""LocalPrometheus(k3s) — 쿼리 빌더 순수 함수 + 가짜 응답으로 계약 검증 (네트워크·k8s SDK 없음)."""
import math
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.services import interfaces
from app.services.agent.handoff_schema import PhaseSummary
from app.services.real.local_prometheus import (
    LocalPrometheus, instant_or_none, local_live_queries,
)
from app.services.stubs import LIVE_SNAPSHOT_KEYS


def test_local_live_queries_are_namespace_scoped_and_match_contract():
    q = local_live_queries("chaoslab-nginx-7")
    assert set(q) == set(LIVE_SNAPSHOT_KEYS) - {"ts"}
    assert all('namespace="chaoslab-nginx-7"' in v for v in q.values())
    assert "istio" not in " ".join(q.values())          # k3s 스택엔 Istio가 없다
    assert "kube_pod_status_ready" in q["ready_pods"]
    # 5xx 시리즈가 없을 때 0%가 빈 벡터로 사라지지 않도록 vector(0) 폴백
    assert "or vector(0)" in q["error_rate_pct"]
    assert q["p95_ms"].startswith("1000 * histogram_quantile(0.95")


def test_instant_or_none_distinguishes_missing_from_zero():
    assert instant_or_none({"data": {"result": []}}) is None
    assert instant_or_none({"data": {"result": [{"value": [0, "0"]}]}}) == 0.0
    assert instant_or_none({"data": {"result": [{"value": [0, str(math.nan)]}]}}) is None


def _fake(monkeypatch, prom: LocalPrometheus, instant: dict[str, object], ranges=None):
    """_get을 가로채 endpoint·query별 canned 응답 — instant는 {부분문자열: 값|None}."""
    calls = []

    def _get(endpoint, params):
        calls.append((endpoint, params["query"]))
        if endpoint == "query":
            for needle, v in instant.items():
                if needle in params["query"]:
                    if v is None:
                        return {"data": {"result": []}}
                    if isinstance(v, dict):   # by-label 벡터
                        return {"data": {"result": [
                            {"metric": {"status": k}, "value": [0, str(n)]} for k, n in v.items()]}}
                    return {"data": {"result": [{"value": [0, str(v)]}]}}
            return {"data": {"result": []}}
        values = (ranges or {}).get(next((k for k in (ranges or {}) if k in params["query"]), ""), [])
        return {"data": {"result": [{"values": [[0, str(v)] for v in values]}] if values else []}}

    monkeypatch.setattr(prom, "_get", _get)
    return calls


def test_live_snapshot_none_for_missing_http_metrics(monkeypatch):
    """nginx 샘플처럼 HTTP 메트릭을 노출하지 않는 앱: Ready 파드만 실측, 나머지는 None."""
    prom: interfaces.PrometheusService = LocalPrometheus(settings)
    _fake(monkeypatch, prom, {"kube_pod_status_ready": 2})
    snap = prom.live_snapshot("chaoslab-nginx-7", "nginx")
    assert set(snap) == set(LIVE_SNAPSHOT_KEYS)
    assert snap["ready_pods"] == 2 and isinstance(snap["ready_pods"], int)
    assert all(snap[k] is None for k in ("rps", "error_rate_pct", "p95_ms", "p99_ms"))


def test_live_snapshot_rounds_and_isolates_failures(monkeypatch):
    prom = LocalPrometheus(settings)
    _fake(monkeypatch, prom, {"kube_pod_status_ready": 10, "status=~": 0,
                              "rate(chaospilot_http_requests_total": 7.1333})
    fake_get = prom._get

    def boom(endpoint, params):
        if "histogram_quantile" in params["query"]:
            raise RuntimeError("proxy timeout")
        return fake_get(endpoint, params)

    monkeypatch.setattr(prom, "_get", boom)
    snap = prom.live_snapshot("ns", "app")
    assert snap["rps"] == 7.13 and snap["error_rate_pct"] == 0.0
    assert snap["p95_ms"] is None and snap["p99_ms"] is None   # 조회 실패는 해당 키만 None
    assert snap["ready_pods"] == 10


def test_phase_summary_matches_contract_with_zero_traffic(monkeypatch):
    prom = LocalPrometheus(settings)
    _fake(monkeypatch, prom,
          {"sum by (status)": {"200": 2156.4, "503": 0}, "restarts_total": 1},
          ranges={"kube_pod_status_ready": [2, 1, 2], "rate(chaospilot_http_requests_total": [7.0, 7.4]})
    end = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    out = prom.phase_summary("ns", "app", "fault", end - timedelta(seconds=30), end)
    PhaseSummary(**out)                                    # 계약 형태
    assert out["min_ready_pods"] == 1 and out["restart_count"] == 1
    assert out["status_code_dist"] == {"200": 2156, "503": 0} and out["http_5xx_count"] == 0
    assert out["rps_avg"] == 7.2 and out["latency_p99_avg_ms"] == 0.0   # 버킷 없음 → 0
    assert out["recovery_seconds"] is None


def test_proxy_path_uses_obs_namespace(monkeypatch):
    """k8s API 서비스 프록시 경로 — SSH 터널 6443 하나로 Prometheus 접근 (별도 port-forward 없음)."""
    prom = LocalPrometheus(settings)
    seen = {}

    class _Resp:
        data = b'{"data": {"result": []}}'

    class _Client:
        def call_api(self, path, method, **kw):
            seen["path"], seen["method"], seen["params"] = path, method, dict(kw["query_params"])
            return _Resp()

    monkeypatch.setattr(prom, "_api_client", lambda: _Client())
    prom.live_snapshot("ns", "app")
    assert seen["path"] == (f"/api/v1/namespaces/{settings.local_obs_namespace}/services/"
                            "http:prometheus:9090/proxy/api/v1/query")
    assert seen["method"] == "GET" and "query" in seen["params"] and "time" in seen["params"]
