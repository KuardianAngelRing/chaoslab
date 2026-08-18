"""Slice 1 스텁 — mock 데이터 반환. 외부 시스템 호출 없음. 운영은 services/real/ 사용."""
from app.services.interfaces import BuildRequest


class StubBuilder:
    def trigger_build(self, req: BuildRequest) -> str:
        return f"build-{req.app_name}-{req.git_sha[:8]}"

    def build_status(self, workflow_name: str) -> str:
        return "succeeded"

    def stop_build(self, workflow_name: str) -> None:
        return None


class StubGitOps:
    def bootstrap_app(self, name: str, repo_url: str, port: int, health: str,
                      env: dict, secret_name: str) -> None:
        return None

    def update_image_tag(self, name: str, image: str) -> None:
        return None

    def set_replicas(self, name: str, replicas: int) -> None:
        return None


class StubChaos:
    def inject(self, namespace: str, app_name: str, chaos_type: str, params: dict) -> str:
        return f"exp-{app_name}-stub"

    def phase(self, chaos_type: str, crd_name: str) -> str:
        return "recovered"

    def delete(self, chaos_type: str, crd_name: str) -> None:
        return None


class StubPrometheus:
    def red_metrics(self, namespace: str) -> dict:
        return {"rate": 42.0, "error": 1.8, "duration": 380.0}


class StubLoki:
    def tail(self, namespace: str, limit: int = 100) -> list[str]:
        return [f"[{namespace}] mock log line {i}" for i in range(limit)]


class StubK8s:
    def apply_env_secret(self, namespace: str, name: str, data: dict) -> None:
        return None

    def restart_deployment(self, namespace: str, name: str) -> None:
        return None

    def nodes(self) -> list[dict]:
        return [
            {"name": "ng-ondemand-1", "type": "m5.large", "status": "Ready", "role": "platform"},
            {"name": "ng-spot-1", "type": "m5.xlarge", "status": "Ready", "role": "workload"},
            {"name": "ng-spot-2", "type": "m5.xlarge", "status": "Ready", "role": "workload"},
        ]

    def pods(self, namespace: str) -> list[dict]:
        return [
            {"name": "frontend-7d9", "namespace": namespace, "status": "Running", "restarts": 0},
            {"name": "cartservice-5fc", "namespace": namespace, "status": "Running", "restarts": 1},
        ]

    def components(self) -> list[dict]:
        names = ["Prometheus", "Grafana", "Loki", "Chaos Mesh", "ArgoCD"]
        return [{"name": n, "status": "Healthy"} for n in names]


_PHASE_SUMMARY_SAMPLES: dict[str, dict] = {
    "baseline": {
        "rps_avg": 42.0, "rps_min": 35.0, "rps_max": 51.0,
        "error_rate_avg": 0.3, "error_rate_peak": 0.8, "http_5xx_count": 4,
        "status_code_dist": {"200": 12480, "404": 21, "503": 4},
        "latency_p50_avg_ms": 34.0, "latency_p50_peak_ms": 52.0,
        "latency_p95_avg_ms": 118.0, "latency_p95_peak_ms": 161.0,
        "latency_p99_avg_ms": 205.0, "latency_p99_peak_ms": 280.0,
        "min_ready_pods": 3, "restart_count": 0, "recovery_seconds": None,
    },
    "fault": {
        "rps_avg": 38.0, "rps_min": 12.0, "rps_max": 49.0,
        "error_rate_avg": 6.4, "error_rate_peak": 23.1, "http_5xx_count": 312,
        "status_code_dist": {"200": 9120, "503": 298, "504": 14},
        "latency_p50_avg_ms": 88.0, "latency_p50_peak_ms": 240.0,
        "latency_p95_avg_ms": 460.0, "latency_p95_peak_ms": 890.0,
        "latency_p99_avg_ms": 1120.0, "latency_p99_peak_ms": 2300.0,
        "min_ready_pods": 1, "restart_count": 2, "recovery_seconds": None,
    },
    "recovery": {
        "rps_avg": 41.0, "rps_min": 28.0, "rps_max": 50.0,
        "error_rate_avg": 1.1, "error_rate_peak": 4.2, "http_5xx_count": 38,
        "status_code_dist": {"200": 11890, "503": 38},
        "latency_p50_avg_ms": 41.0, "latency_p50_peak_ms": 95.0,
        "latency_p95_avg_ms": 150.0, "latency_p95_peak_ms": 320.0,
        "latency_p99_avg_ms": 260.0, "latency_p99_peak_ms": 510.0,
        "min_ready_pods": 2, "restart_count": 1, "recovery_seconds": 41.0,
    },
}

_STUB_VS_YAML = """apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: {app}
  namespace: {ns}
spec:
  hosts: ["{app}"]
  http:
    - route:
        - destination:
            host: {app}
      timeout: 3s
      retries:
        attempts: 2
        perTryTimeout: 1s
        retryOn: 5xx
"""

_STUB_DR_YAML = """apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: {app}
  namespace: {ns}
spec:
  host: {app}
  trafficPolicy:
    outlierDetection:
      consecutive5xxErrors: 5
      interval: 10s
      baseEjectionTime: 30s
"""


class StubHandoffSource:
    """AI 팀이 실데이터(Slice 4·5) 전에 개발 착수할 수 있는 형태 충실 샘플."""

    def phase_summary(self, namespace: str, app_name: str, phase: str) -> dict:
        return dict(_PHASE_SUMMARY_SAMPLES[phase])

    def istio_config(self, namespace: str, app_name: str) -> dict:
        return {
            "virtual_service_yaml": _STUB_VS_YAML.format(app=app_name, ns=namespace),
            "destination_rule_yaml": _STUB_DR_YAML.format(app=app_name, ns=namespace),
        }

    def deployment_info(self, namespace: str, app_name: str) -> dict:
        return {
            "replicas": 3,
            "probes": {
                "readiness": {"httpGet": "/healthz", "periodSeconds": 10,
                              "failureThreshold": 3},
                "liveness": {"httpGet": "/healthz", "periodSeconds": 20},
            },
            "resources": {
                "requests": {"cpu": "100m", "memory": "128Mi"},
                "limits": {"cpu": "500m", "memory": "256Mi"},
            },
        }

    def events(self, namespace: str, app_name: str) -> list[dict]:
        return [
            {"timestamp": "2026-08-11T02:00:11Z", "type": "Normal",
             "reason": "Killing", "object": f"pod/{app_name}-7d9",
             "message": "Stopping container server (chaos pod-kill)"},
            {"timestamp": "2026-08-11T02:00:14Z", "type": "Warning",
             "reason": "Unhealthy", "object": f"pod/{app_name}-5fc",
             "message": "Readiness probe failed: connection refused"},
            {"timestamp": "2026-08-11T02:00:52Z", "type": "Normal",
             "reason": "Started", "object": f"pod/{app_name}-8b1",
             "message": "Started container server"},
        ]

    def error_logs(self, namespace: str, app_name: str, limit: int = 20) -> list[str]:
        samples = [
            f"[{app_name}] rpc error: code = Unavailable desc = connection refused",
            f"[{app_name}] HTTP 503 upstream connect error or disconnect/reset",
            f"[{app_name}] context deadline exceeded (client timeout 3s)",
            f'[{app_name}] readiness probe failed: Get "/healthz": dial tcp refused',
        ]
        return samples[:limit]
