"""관측 샘플 — 샘플당 요청 3회, 오류율·p95는 요청 수 기준 (팀 결정 B1, 2026-09-05)."""
from app.services.observations import REQUESTS_PER_SAMPLE, summarize, take_sample

_OBS = {"service": "nginx", "path": "/", "expected_status": 200}


class _Workload:
    def __init__(self, codes):
        self._codes = list(codes)
        self.calls = 0

    def probe_http(self, namespace, service, path):
        code = self._codes[self.calls % len(self._codes)]
        self.calls += 1
        return {"status_code": code, "latency_ms": 10.0 * self.calls,
                "error": "" if code == 200 else "upstream"}

    def readiness(self, namespace):
        return {"pods_ready": 1, "pods_total": 2, "restart_count": 0}


def test_take_sample_probes_three_times_and_requires_all_ok():
    wl = _Workload([200, 503, 200])
    s = take_sample(wl, "ns", _OBS)
    assert wl.calls == REQUESTS_PER_SAMPLE == 3
    assert s["request_count"] == 3 and s["success_count"] == 2
    assert s["request_ok"] is False                      # 하나라도 실패면 샘플은 실패(회복 루프 기준)
    assert s["request_error"] == "upstream" and s["latency_ms"] == 30.0
    assert [r["ok"] for r in s["requests"]] == [True, False, True]
    assert s["pods_ready"] == 1

    ok = take_sample(_Workload([200]), "ns", _OBS)
    assert ok["request_ok"] is True and ok["request_error"] == ""


def test_summarize_counts_requests_not_samples():
    wl = _Workload([200, 200, 200, 200, 200, 503])      # 6요청 중 1실패
    samples = [take_sample(wl, "ns", _OBS), take_sample(wl, "ns", _OBS)]
    out = summarize(samples)
    assert out["sample_count"] == 2 and out["request_count"] == 6
    assert out["failure_count"] == 1
    assert out["error_rate_pct"] == 16.7                 # 1/6 — 샘플 기준(1/2=50%)이 아니다
    assert out["p95_latency_ms"] == 60.0
    assert out["status_codes"] == {"200": 5, "503": 1}
    assert out["min_ready_pods"] == 1 and out["errors"] == ["upstream"]


def test_summarize_accepts_legacy_single_request_samples():
    legacy = [{"status_code": 200, "latency_ms": 12.0, "request_ok": True, "request_error": "",
               "pods_ready": 2, "restart_count": 0},
              {"status_code": 0, "latency_ms": 0.0, "request_ok": False, "request_error": "refused",
               "pods_ready": 0, "restart_count": 1}]
    out = summarize(legacy)
    assert out["request_count"] == 2 and out["error_rate_pct"] == 50.0
    assert out["min_ready_pods"] == 0 and out["restart_count"] == 1


def test_summarize_empty():
    out = summarize([])
    assert out["observed"] is False and out["error_rate_pct"] is None and out["request_count"] == 0
