"""RealK8s — 클러스터 조회/쓰기 (운영, use_real_services=true).

k8s SDK는 메서드 안에서 lazy import → stub/테스트는 의존성 불필요.
"""
from __future__ import annotations

from app.services.real.kube import load_kube


class RealK8s:
    def __init__(self, settings):
        self.s = settings

    def _api(self):
        from kubernetes import client  # lazy

        load_kube(self.s)
        return client.CoreV1Api()

    def apply_env_secret(self, namespace: str, name: str, data: dict[str, str]) -> None:
        """Opaque Secret 생성, 이미 있으면 교체(idempotent)."""
        from kubernetes import client
        from kubernetes.client.rest import ApiException

        api = self._api()
        body = client.V1Secret(
            metadata=client.V1ObjectMeta(name=name),
            string_data={str(k): str(v) for k, v in data.items()},
            type="Opaque",
        )
        try:
            api.create_namespaced_secret(namespace=namespace, body=body)
        except ApiException as e:
            if e.status == 409:
                api.replace_namespaced_secret(name=name, namespace=namespace, body=body)
            else:
                raise

    def restart_deployment(self, namespace: str, name: str) -> None:
        """kubectl rollout restart와 동일 — 파드 템플릿 annotation 갱신으로 재기동."""
        from datetime import datetime, timezone

        from kubernetes import client  # lazy

        load_kube(self.s)
        client.AppsV1Api().patch_namespaced_deployment(
            name=name, namespace=namespace,
            body={"spec": {"template": {"metadata": {"annotations": {
                "kubectl.kubernetes.io/restartedAt":
                    datetime.now(timezone.utc).isoformat()
            }}}}},
        )

    def nodes(self) -> list[dict]:
        api = self._api()
        out = []
        for n in api.list_node().items:
            conds = n.status.conditions or []
            ready = any(c.type == "Ready" and c.status == "True" for c in conds)
            labels = n.metadata.labels or {}
            out.append({
                "name": n.metadata.name,
                "type": labels.get("node.kubernetes.io/instance-type", ""),
                "status": "Ready" if ready else "NotReady",
                "role": labels.get("role", ""),
            })
        return out

    def pods(self, namespace: str) -> list[dict]:
        api = self._api()
        out = []
        for p in api.list_namespaced_pod(namespace).items:
            restarts = sum(cs.restart_count for cs in (p.status.container_statuses or []))
            out.append({
                "name": p.metadata.name, "namespace": namespace,
                "status": p.status.phase, "restarts": restarts,
            })
        return out

    _COMPONENTS = [("Prometheus", "monitoring", "prometheus"),
                   ("Grafana", "monitoring", "grafana"),
                   ("Loki", "monitoring", "loki"),
                   ("Chaos Mesh", "chaos-mesh", "chaos"),
                   ("ArgoCD", "argocd", "argocd")]

    def components(self) -> list[dict]:
        api = self._api()
        out = []
        for display, ns, keyword in self._COMPONENTS:
            try:
                pods = api.list_namespaced_pod(ns).items
                healthy = any(keyword in p.metadata.name and p.status.phase == "Running"
                              for p in pods)
            except Exception:
                healthy = False
            out.append({"name": display, "status": "Healthy" if healthy else "Down"})
        return out
