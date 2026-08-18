"""RealLocalK8s — 로컬(라즈베리파이 k3s) 클러스터 현황 조회 (읽기 전용).

SSH 터널(localhost:6443)이 떠 있고 settings.local_kubeconfig가 그 터널을
가리키는 kubeconfig일 때 동작. k8s SDK는 lazy import — stub/테스트는 의존성 불필요.

데이터 출처: 노드/네임스페이스/Pod = k8s API · CPU·메모리 사용률 = metrics-server
(metrics.k8s.io) · 온도 = Prometheus service proxy(node-exporter hwmon — 스택에
없으면 None → 화면 '—'). 터널이 죽어 있으면 error 키를 담은 빈 스냅샷 반환.
"""
from __future__ import annotations

import json
import os

_TIMEOUT = (3, 10)  # (connect, read)초 — 터널 다운 시 페이지가 오래 안 멈추게

# 노드 이름 → 기기 모델 — k8s API로는 알 수 없어 하드코딩 (로컬 인프라는 불변 전제).
# 새 노드가 생기면 os_image 폴백으로 표시됨.
_NODE_MODELS = {
    "master-node": "Raspberry Pi 4B 8GB",
    "worker-node-1": "Raspberry Pi 4B 4GB",
    "worker-node-2": "Raspberry Pi 4B 4GB",
}

# 워크로드 이름 → 화면 표시명 (템플릿 아이콘 매칭과 일치)
_DISPLAY_NAMES = {
    "prometheus": "Prometheus",
    "loki": "Loki",
    "alloy": "Alloy",
    "chaos-controller-manager": "Chaos Mesh",
}


def parse_cpu(quantity: str) -> float:
    """k8s CPU 수량 → 코어 수 (예: '250m'→0.25, '1500000n'→0.0015, '2'→2.0)."""
    q = quantity.strip()
    if q.endswith("n"):
        return float(q[:-1]) / 1e9
    if q.endswith("u"):
        return float(q[:-1]) / 1e6
    if q.endswith("m"):
        return float(q[:-1]) / 1e3
    return float(q)


def parse_mem(quantity: str) -> float:
    """k8s 메모리 수량 → 바이트 (예: '512Mi', '8Gi', '1024Ki', '1000000')."""
    q = quantity.strip()
    for suffix, mult in (("Ki", 2**10), ("Mi", 2**20), ("Gi", 2**30), ("Ti", 2**40),
                         ("K", 1e3), ("M", 1e6), ("G", 1e9), ("T", 1e12)):
        if q.endswith(suffix):
            return float(q[: -len(suffix)]) * mult
    return float(q)


def usage_pct(used: float, total: float) -> int:
    """사용률 % (0–100 클램프). total이 0 이하면 0."""
    if total <= 0:
        return 0
    return round(min(used / total, 1.0) * 100)


class RealLocalK8s:
    def __init__(self, settings):
        self.s = settings
        self._client = None

    def _api_client(self):
        from kubernetes import config  # lazy

        if self._client is None:
            self._client = config.new_client_from_config(
                config_file=os.path.expanduser(self.s.local_kubeconfig))
        return self._client

    def overview(self) -> dict:
        try:
            return self._overview()
        except Exception as e:  # 터널 다운·kubeconfig 오류 — 페이지는 배너로 안내
            return {
                "cluster": {"name": self.s.local_cluster_name, "version": "—", "arch": "—",
                            "access": "SSH 터널 · localhost:6443", "healthy": False},
                "pod_count": 0, "namespaces": [], "nodes": [], "components": [],
                "error": f"클러스터 조회 실패({e.__class__.__name__}) — "
                         "SSH 터널(localhost:6443)과 kubeconfig를 확인하세요",
            }

    def _overview(self) -> dict:
        from kubernetes import client  # lazy

        api_client = self._api_client()
        core = client.CoreV1Api(api_client)

        version = client.VersionApi(api_client).get_code(_request_timeout=_TIMEOUT)
        nodes = core.list_node(_request_timeout=_TIMEOUT).items
        namespaces = [n.metadata.name
                      for n in core.list_namespace(_request_timeout=_TIMEOUT).items]
        running = core.list_pod_for_all_namespaces(
            field_selector="status.phase=Running", _request_timeout=_TIMEOUT).items

        metrics = self._node_metrics(api_client)
        temps = self._node_temps(api_client)
        node_rows = [self._node_row(n, metrics.get(n.metadata.name), temps) for n in nodes]

        return {
            "cluster": {
                "name": self.s.local_cluster_name,
                "version": version.git_version,
                "arch": (version.platform or "/").split("/")[-1],
                "access": "SSH 터널 · localhost:6443",
                "healthy": bool(node_rows) and all(r["status"] == "Ready" for r in node_rows),
            },
            "pod_count": len(running),
            "namespaces": namespaces,
            "nodes": node_rows,
            "components": self._components(api_client),
        }

    def _node_row(self, node, usage: dict | None, temps: dict[str, float]) -> dict:
        name = node.metadata.name
        labels = node.metadata.labels or {}
        is_cp = "node-role.kubernetes.io/control-plane" in labels
        role = "control-plane · etcd" if "node-role.kubernetes.io/etcd" in labels \
            else ("control-plane" if is_cp else "worker")

        conditions = node.status.conditions or []
        ready = next((c.status == "True" for c in conditions if c.type == "Ready"), False)

        cpu_pct = mem_pct = 0
        if usage:
            alloc = node.status.allocatable or {}
            cpu_pct = usage_pct(parse_cpu(usage["cpu"]), parse_cpu(alloc.get("cpu", "0")))
            mem_pct = usage_pct(parse_mem(usage["memory"]), parse_mem(alloc.get("memory", "0")))

        return {
            "name": name,
            "model": _NODE_MODELS.get(name, node.status.node_info.os_image),
            "role": role,
            "cpu_pct": cpu_pct,
            "mem_pct": mem_pct,
            "temp_c": temps.get(name),
            "status": "Ready" if ready else "NotReady",
        }

    def _node_metrics(self, api_client) -> dict[str, dict]:
        """metrics-server 노드 사용량. 없으면 빈 dict → 사용률 0으로 표시."""
        from kubernetes import client  # lazy

        try:
            data = client.CustomObjectsApi(api_client).list_cluster_custom_object(
                "metrics.k8s.io", "v1beta1", "nodes", _request_timeout=_TIMEOUT)
        except Exception:
            return {}
        return {i["metadata"]["name"]: i["usage"] for i in data.get("items", [])}

    def _node_temps(self, api_client) -> dict[str, float]:
        """Prometheus service proxy로 hwmon 온도 조회 — 메트릭 없으면 빈 dict."""
        path = (f"/api/v1/namespaces/{self.s.local_obs_namespace}/services/"
                "http:prometheus:9090/proxy/api/v1/query")
        try:
            resp = api_client.call_api(
                path, "GET",
                query_params=[("query", "node_hwmon_temp_celsius")],
                header_params={"Accept": "application/json"},
                auth_settings=["BearerToken"],
                _request_timeout=_TIMEOUT, _return_http_data_only=True,
                _preload_content=False)
            payload = json.loads(resp.data.decode("utf-8", errors="replace"))
        except Exception:
            return {}

        temps: dict[str, float] = {}
        for item in payload.get("data", {}).get("result", []):
            labels = item.get("metric", {})
            node = (labels.get("nodename") or labels.get("node")
                    or labels.get("instance", "").split(":")[0])
            try:
                value = float(item["value"][1])
            except (KeyError, IndexError, TypeError, ValueError):
                continue
            if node:  # 칩·센서가 여럿이면 노드당 최고 온도
                temps[node] = max(temps.get(node, value), value)
        return temps

    def _components(self, api_client) -> list[dict]:
        """관측(obs)·카오스 네임스페이스의 Deployment/DaemonSet 준비 상태."""
        from kubernetes import client  # lazy

        apps = client.AppsV1Api(api_client)
        rows: list[dict] = []
        for ns in (self.s.local_chaos_namespace, self.s.local_obs_namespace):
            for dep in apps.list_namespaced_deployment(ns, _request_timeout=_TIMEOUT).items:
                ready, want = dep.status.ready_replicas or 0, dep.spec.replicas or 0
                rows.append(self._component_row(dep.metadata.name, "Deployment", ready, want, ns))
            for ds in apps.list_namespaced_daemon_set(ns, _request_timeout=_TIMEOUT).items:
                ready = ds.status.number_ready or 0
                want = ds.status.desired_number_scheduled or 0
                rows.append(self._component_row(ds.metadata.name, "DaemonSet", ready, want, ns))
        return rows

    @staticmethod
    def _component_row(name: str, kind: str, ready: int, want: int, ns: str) -> dict:
        return {
            "name": _DISPLAY_NAMES.get(name, name),
            "detail": f"{kind} {ready}/{want}",
            "ns": ns,
            "status": "Running" if want > 0 and ready >= want else "Degraded",
        }
