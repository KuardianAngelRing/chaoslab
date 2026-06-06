"""RealK8s — 클러스터 직접 쓰기 (운영, use_real_services=true).

Slice 2 범위: apply_env_secret만. nodes/pods/components는 Slice 4에서 추가.
k8s SDK는 메서드 안에서 lazy import → stub/테스트는 의존성 불필요.
"""
from __future__ import annotations


class RealK8s:
    def __init__(self, settings):
        self.s = settings

    def _api(self):
        from kubernetes import client, config  # lazy

        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
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
