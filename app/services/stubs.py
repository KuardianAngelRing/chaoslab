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


class StubK3sWorkload:
    def __init__(self):
        self.env_values = {
            ("checkout-api", "app", "UPSTREAM_TIMEOUT_SECONDS"): "0.45",
            ("order-api", "app", "UPSTREAM_TIMEOUT_SECONDS"): "0.45",
        }

    def deploy(self, namespace: str, manifest_yaml: str) -> None:
        return None

    def wait_ready(self, namespace: str, timeout_s: int = 180) -> bool:
        return True

    def readiness(self, namespace: str) -> dict:
        return {"deployments_ready": 1, "deployments_total": 1,
                "pods_ready": 10, "pods_total": 10, "restart_count": 0, "blockers": []}

    def probe_http(self, namespace: str, service: str, path: str) -> dict:
        return {"status_code": 200, "latency_ms": 48.0, "ok": True, "error": ""}

    def apply_deployment_env(self, namespace: str, deployment: str, container: str,
                             key: str, value: str, timeout_s: int = 180) -> dict:
        identity = (deployment, container, key)
        before = self.env_values.get(identity, "")
        self.env_values[identity] = value
        return {
            "type": "deployment_env",
            "deployment": deployment,
            "container": container,
            "key": key,
            "before": before,
            "after": value,
            "rollout_ready": True,
        }

    def teardown(self, namespace: str) -> None:
        return None


class StubChaos:
    def inject(self, namespace: str, app_name: str, chaos_type: str, params: dict,
               target_selector: dict[str, str] | None = None) -> str:
        return f"exp-{app_name}-stub"

    def phase(self, chaos_type: str, crd_name: str) -> str:
        return "recovered"

    def delete(self, chaos_type: str, crd_name: str) -> None:
        return None


class StubTunnel:
    """터널 미관리 모드(LOCAL_SSH_HOST 미설정) — start/stop 무동작."""

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    def status(self) -> dict:
        return {"state": "disabled", "detail": "LOCAL_SSH_HOST 미설정 — 수동 터널 전제"}


class StubLocalK8s:
    """로컬 k3s 목업 — Real(services/real/local_k8s.py)은 SSH 터널 경유 실조회.

    노드 온도는 node-exporter(hwmon), CPU·메모리는 metrics-server(kubectl top) 기준 값.
    """

    def overview(self) -> dict:
        return {
            "cluster": {"name": "chaospilot-k3s", "version": "v1.32.3+k3s1", "arch": "arm64",
                        "access": "SSH 터널 · localhost:6443", "healthy": True},
            "pod_count": 24,
            "namespaces": ["kube-system", "chaos-mesh", "chaospilot-observability", "order-msa"],
            "nodes": [
                {"name": "masternode", "model": "Raspberry Pi 4B 8GB", "role": "control-plane · etcd",
                 "cpu_pct": 21, "mem_pct": 48, "temp_c": 52.1, "status": "Ready"},
                {"name": "worker1", "model": "Raspberry Pi 4B 4GB", "role": "worker",
                 "cpu_pct": 34, "mem_pct": 61, "temp_c": 55.3, "status": "Ready"},
                {"name": "worker2", "model": "Raspberry Pi 4B 4GB", "role": "worker",
                 "cpu_pct": 18, "mem_pct": 44, "temp_c": 49.8, "status": "Ready"},
            ],
            "components": [
                {"name": "Chaos Mesh", "detail": "controller 1/1 · daemon 3/3",
                 "ns": "chaos-mesh", "status": "Running"},
                {"name": "Prometheus", "detail": "메트릭 수집 · service proxy 조회",
                 "ns": "chaospilot-observability", "status": "Running"},
                {"name": "Loki", "detail": "로그 저장 · LogQL 조회",
                 "ns": "chaospilot-observability", "status": "Running"},
                {"name": "kube-state-metrics", "detail": "리소스 상태 메트릭",
                 "ns": "chaospilot-observability", "status": "Running"},
                {"name": "Alloy", "detail": "로그 수집 에이전트 (DaemonSet 3/3)",
                 "ns": "chaospilot-observability", "status": "Running"},
            ],
        }


class StubPrometheus:
    def red_metrics(self, namespace: str) -> dict:
        return {"rate": 42.0, "error": 1.8, "duration": 380.0}

    def phase_summary(self, namespace: str, app_name: str, phase: str,
                      start, end) -> dict:
        # 모듈 하단 _PHASE_SUMMARY_SAMPLES 재사용 (호출 시점 해석)
        return dict(_PHASE_SUMMARY_SAMPLES[phase])


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


_STUB_PARAM_PREFS = {"latency_ms": 300, "duration_s": 60, "cpu_load": 80,
                     "loss_percent": 25, "rate_mbps": 10, "memory_mb": 256}

_STUB_CANDIDATE_TYPES = [
    ("pod-kill", "파드 강제 종료를 버티는지"),
    ("network-delay", "네트워크 지연에도 응답을 지키는지"),
    ("cpu-stress", "CPU 압박에도 처리량을 지키는지"),
]


class StubHypothesisAgent:
    """가설 수립 스텁 — 페이로드에서 대상을 골라 결정적으로 즉시 반환.

    검증(hypothesis_validation)은 Real과 동일하게 바깥에서 적용된다.
    """

    def _target(self, payload) -> str:
        if payload.manifest_findings:
            return payload.manifest_findings[0].workload
        return payload.app.get("name", "app")

    def generate(self, payload, feedback: str = "") -> list:
        target = self._target(payload)
        count = max(1, min(payload.candidate_count, len(_STUB_CANDIDATE_TYPES)))
        out = []
        for chaos_type, angle in _STUB_CANDIDATE_TYPES[:count]:
            from app.services.chaos_specs import CHAOS_SPECS
            label = CHAOS_SPECS[chaos_type]["label"]
            out.append({
                "title": f"{target} {label} 검증",
                "chaos_type": chaos_type,
                "target_workload": target,
                "hypothesis": f"{target}가 {angle} 확인하면, 현재 구성에서는 응답 오류가 발생할 것이다",
                "expected_impact": f"{label} 구간 동안 응답 지연과 오류율 상승이 예상돼요",
            })
        return out

    def concretize(self, payload, user_text: str, feedback: str = "") -> dict:
        target = self._target(payload)
        return {
            "title": "직접 입력 시나리오 검증",
            "chaos_type": "memory-stress",
            "target_workload": target,
            "hypothesis": f"요청 시나리오({user_text[:80]})에서 {target}의 응답이 실패할 것이다",
            "expected_impact": "메모리 압박 구간에서 응답 지연과 재시작이 발생할 것으로 예상돼요",
        }

    def detail(self, payload, candidate, feedback: str = "") -> dict:
        from app.services.chaos_specs import CHAOS_SPECS
        params = {}
        for name, rule in CHAOS_SPECS[candidate.chaos_type]["fields"].items():
            if rule.get("type") == "str":
                params[name] = candidate.target_workload
            else:
                params[name] = min(max(rule["min"], _STUB_PARAM_PREFS.get(name, rule["min"])),
                                   rule["max"])
        return {"params": params, "rationale": "스텁 기본값 — 필드 범위 안의 대표값"}

    def snapshot(self) -> dict:
        return {"model_name": "stub", "cli_version": "stub"}
