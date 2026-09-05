"""Slice 1 스텁 — mock 데이터 반환. 외부 시스템 호출 없음. 운영은 services/real/ 사용."""
from datetime import datetime, timezone

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
        self.patches: dict[tuple[str, str], dict] = {}  # (ns, deployment) → 누적 적용 patch

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

    def patch_deployment(self, namespace: str, deployment: str, patch: dict,
                         timeout_s: int = 180) -> dict:
        from app.services.improvement_specs import project

        identity = (namespace, deployment)
        before = project(self.patches.get(identity, {}), patch)
        merged = _deep_merge(self.patches.get(identity, {}), patch)
        self.patches[identity] = merged
        return {
            "type": "manifest_patch",
            "deployment": deployment,
            "patch": patch,
            "before": before,
            "after": project(merged, patch),
            "rollout_ready": True,
        }

    def teardown(self, namespace: str) -> None:
        return None


def _deep_merge(base: dict, patch: dict) -> dict:
    """Stub용 strategic merge 근사 — dict 재귀 병합, containers는 name 매칭, None은 삭제."""
    out = dict(base)
    for key, value in patch.items():
        if value is None:
            out.pop(key, None)
        elif isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        elif isinstance(value, list) and all(isinstance(i, dict) and "name" in i for i in value):
            existing = {i["name"]: i for i in out.get(key) or [] if isinstance(i, dict) and "name" in i}
            for item in value:
                existing[item["name"]] = _deep_merge(existing.get(item["name"], {}), item)
            out[key] = list(existing.values())
        else:
            out[key] = value
    return out


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


LIVE_SNAPSHOT_KEYS = ("ts", "rps", "error_rate_pct", "p95_ms", "p99_ms", "ready_pods")


def _stub_live_series(tick: int) -> dict:
    """호출 횟수(tick, 0부터) 기반 결정적 즉시값 — 정상(0~4) → 악화(5~14) → 회복(15~).

    ts는 호출자가 채운다(순수 함수). 값 키는 live_snapshot 계약에서 ts를 뺀 것.
    """
    if tick < 5:      # 정상
        return {"rps": 42.0 + (tick % 3), "error_rate_pct": 0.3,
                "p95_ms": 118.0 + 4 * (tick % 2), "p99_ms": 205.0 + 6 * (tick % 2),
                "ready_pods": 3}
    if tick < 15:     # 장애 주입 — 오류율·레이턴시 상승, ready 파드 감소
        k = tick - 5  # 0~9
        return {"rps": round(38.0 - 2.4 * k, 1),
                "error_rate_pct": round(min(23.1, 3.0 + 2.3 * k), 1),
                "p95_ms": round(460.0 + 43.0 * k, 1), "p99_ms": round(1120.0 + 118.0 * k, 1),
                "ready_pods": 1 if k >= 3 else 2}
    k = min(tick - 15, 8)  # 회복 — 8틱에 걸쳐 기준선 복귀 후 유지
    return {"rps": round(14.0 + 3.5 * k, 1),
            "error_rate_pct": round(max(0.3, 12.0 - 1.5 * k), 1),
            "p95_ms": round(max(118.0, 850.0 - 92.0 * k), 1),
            "p99_ms": round(max(205.0, 2100.0 - 237.0 * k), 1),
            "ready_pods": 3 if k >= 2 else 2}


class StubPrometheus:
    def __init__(self) -> None:
        self._tick = 0

    def red_metrics(self, namespace: str) -> dict:
        return {"rate": 42.0, "error": 1.8, "duration": 380.0}

    def phase_summary(self, namespace: str, app_name: str, phase: str,
                      start, end) -> dict:
        # 모듈 하단 _PHASE_SUMMARY_SAMPLES 재사용 (호출 시점 해석)
        return dict(_PHASE_SUMMARY_SAMPLES[phase])

    def live_snapshot(self, namespace: str, app_name: str) -> dict:
        snap = _stub_live_series(self._tick)
        self._tick += 1
        return {"ts": datetime.now(timezone.utc).isoformat(), **snap}


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

    def propose_improvements(self, payload, feedback: str = "") -> list:
        """manifest 약점 기반 결정적 제안(최대 max_proposals) — 순서대로
        ① 대상 replicas < 2 → 3 ② readinessProbe 주기 > 3s(또는 없음) → 2s/추가
        ③ 대상을 UPSTREAMS로 부르는 워크로드에 UPSTREAM_RETRIES가 있으면 0 → 2
        ④ 채움용 preStop sleep 5s. 검증은 바깥(validate_proposals)에서."""
        from app.services.improvement_specs import container_names, manifest_workloads

        workloads = manifest_workloads(payload.manifest_yaml)
        target = payload.candidate.get("target_workload")
        name = target if target in workloads else next(iter(workloads), None)
        if name is None:
            return []
        doc = workloads[name]
        containers = ((((doc.get("spec") or {}).get("template") or {}).get("spec") or {})
                      .get("containers") or [])
        container = containers[0] if containers else {}
        cname = (container_names(doc) or ["app"])[0]
        out = []

        replicas = int((doc.get("spec") or {}).get("replicas") or 1)
        if replicas < 2:
            out.append({
                "title": f"{name} 파드 개수 {replicas} → 3으로 증설", "type": "manifest_patch",
                "deployment": name, "container": cname, "patch": {"spec": {"replicas": 3}},
                "rationale": f"{name}는 파드가 {replicas}개뿐이라 파드 장애가 곧 서비스 중단이다 — "
                             "여분 파드가 있어야 하나가 죽어도 나머지가 요청을 받는다",
                "expected_effect": "장애 구간 오류율이 크게 줄고 Ready 파드가 0으로 떨어지지 않아요",
            })

        probe = container.get("readinessProbe")
        if probe and int(probe.get("periodSeconds") or 10) > 3:
            out.append({
                "title": "readinessProbe 주기 단축", "type": "manifest_patch", "deployment": name,
                "container": cname,
                "patch": {"spec": {"template": {"spec": {"containers": [
                    {"name": cname, "readinessProbe": {"initialDelaySeconds": 2, "periodSeconds": 2,
                                                       "failureThreshold": 2}}]}}}},
                "rationale": f"준비 확인 주기가 {probe.get('periodSeconds')}초라 교체 파드가 트래픽에 늦게 합류하고, "
                             "죽은 파드도 늦게 빠진다 — 준비 상태를 더 자주 확인한다",
                "expected_effect": "파드 교체 중 오류 응답 감소와 회복 시간 단축이 기대돼요",
            })
        elif not probe:
            ports = container.get("ports") or []
            port = (ports[0].get("containerPort") if ports else None) or payload.app.get("port") or 80
            out.append({
                "title": "readinessProbe 추가", "type": "manifest_patch", "deployment": name, "container": cname,
                "patch": {"spec": {"template": {"spec": {"containers": [
                    {"name": cname, "readinessProbe": {"tcpSocket": {"port": int(port)},
                                                       "periodSeconds": 2, "failureThreshold": 2}}]}}}},
                "rationale": "장애 구간에서 준비되지 않은 파드가 Ready로 남아 요청을 받으면 오류가 늘어난다 — "
                             "준비 상태를 확인해 트래픽에서 빨리 뺀다",
                "expected_effect": "파드 교체 중 오류 응답 감소와 회복 시간 단축이 기대돼요",
            })

        for caller_name, caller in workloads.items():
            for c in ((((caller.get("spec") or {}).get("template") or {}).get("spec") or {})
                      .get("containers") or []):
                env = {e.get("name"): str(e.get("value", "")) for e in (c.get("env") or []) if isinstance(e, dict)}
                if "UPSTREAM_RETRIES" in env and name in env.get("UPSTREAMS", "") and env["UPSTREAM_RETRIES"] == "0":
                    out.append({
                        "title": f"{caller_name} → {name} 호출 재시도 0 → 2회", "type": "deployment_env",
                        "deployment": caller_name, "container": c.get("name") or "app",
                        "key": "UPSTREAM_RETRIES", "value": "2",
                        "rationale": f"{caller_name}는 {name} 호출이 한 번 실패하면 곧바로 오류로 응답한다 — "
                                     "짧은 재시도로 파드 교체 순간의 일시적 실패를 흡수한다",
                        "expected_effect": "장애 구간의 일시적 연결 실패가 오류 응답으로 번지지 않아요",
                    })
                    break

        out.append({
            "title": "종료 전 유예(preStop sleep)", "type": "manifest_patch", "deployment": name,
            "container": cname,
            "patch": {"spec": {"template": {"spec": {"containers": [{"name": cname, "lifecycle": {"preStop": {"sleep": {"seconds": 5}}}}]}}}},
            "rationale": "파드 종료 신호와 서비스 엔드포인트 제거 사이의 시차 동안 들어온 요청이 끊긴다 — "
                         "종료 전 잠시 기다려 진행 중 요청을 마무리한다",
            "expected_effect": "파드 종료 순간의 연결 끊김(5xx) 감소가 기대돼요",
        })
        return out[:payload.max_proposals]

    def snapshot(self) -> dict:
        return {"model_name": "stub", "cli_version": "stub"}
