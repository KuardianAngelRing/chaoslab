"""order-resilience-lab 샘플 app.py의 /metrics가 LocalPrometheus 계약과 맞는지 — 서브프로세스로 실기동.

계약(`real/local_prometheus.py`): `chaospilot_http_requests_total{status}` 카운터 +
`chaospilot_http_request_duration_seconds_bucket{le}` 히스토그램. 09/06 이전 샘플은 이름·라벨이 달랐고
YAML 블록 안 `\\\\n` 때문에 본문이 한 줄로 붙어 Prometheus가 파싱하지 못했다.
"""
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

from app.services.real.local_prometheus import _HTTP_BUCKET, _HTTP_TOTAL

MANIFEST = Path(__file__).resolve().parents[1] / "app" / "samples" / "k3s" / "order-resilience-lab.yaml"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


@pytest.fixture
def sample_app(tmp_path):
    procs = []

    def start(**env) -> str:
        docs = yaml.safe_load_all(MANIFEST.read_text(encoding="utf-8"))
        src = next(d for d in docs if d.get("kind") == "ConfigMap")["data"]["app.py"]
        script = tmp_path / f"app-{len(procs)}.py"
        script.write_text(src, encoding="utf-8")
        port = _free_port()
        proc = subprocess.Popen(
            [sys.executable, str(script)],
            env={**os.environ, "SERVICE_NAME": "checkout-api", "PORT": str(port),
                 "UPSTREAMS": "", "UPSTREAM_TIMEOUT_SECONDS": "0.2", **env},
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        procs.append(proc)
        base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            if proc.poll() is not None:
                pytest.fail(f"sample app exited: {proc.stderr.read().decode()}")
            try:
                _get(base + "/live")
                return base
            except (urllib.error.URLError, OSError):
                time.sleep(0.05)
        pytest.fail("sample app did not start")

    yield start
    for proc in procs:
        proc.kill()
        proc.wait()


def test_sample_metrics_match_local_prometheus_contract(sample_app):
    base = sample_app()
    assert _get(base + "/orders")[0] == 200
    assert _get(base + "/orders")[0] == 200
    _get(base + "/live"); _get(base + "/ready"); _get(base + "/nope")   # probe·404는 계수하지 않음

    status, body = _get(base + "/metrics")
    assert status == 200
    lines = body.splitlines()
    assert len(lines) > 10 and "\\n" not in body                        # 줄바꿈 실제 개행(구 샘플 버그)
    assert f'{_HTTP_TOTAL}{{service="checkout-api",status="200"}} 2' in lines
    assert not any(l.startswith(_HTTP_TOTAL) and 'status="404"' in l for l in lines)
    assert f'{_HTTP_BUCKET}{{service="checkout-api",le="+Inf"}} 2' in lines
    assert f'{_HTTP_BUCKET}{{service="checkout-api",le="0.005"}}' in body  # 기본 버킷 경계
    assert 'chaospilot_http_request_duration_seconds_count{service="checkout-api"} 2' in lines
    assert "chaoslab_http" not in body


def test_sample_metrics_count_upstream_failures_as_503(sample_app):
    base = sample_app(UPSTREAMS="http://127.0.0.1:9")                   # 닫힌 포트 → 의존성 실패
    assert _get(base + "/orders")[0] == 503
    body = _get(base + "/metrics")[1]
    assert f'{_HTTP_TOTAL}{{service="checkout-api",status="503"}} 1' in body.splitlines()
    assert 'status="200"' not in body
