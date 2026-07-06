"""RealChaos — Chaos Mesh CRD 주입/조회/삭제 (운영, use_real_services=true).

render_chaos_manifest는 순수 함수(테스트 가능). k8s 호출은 메서드 안에서 lazy import.
"""
from __future__ import annotations

_GROUP = "chaos-mesh.org"
_VERSION = "v1alpha1"

CHAOS_PLURALS = {
    "NetworkChaos": "networkchaos",
    "PodChaos": "podchaos",
    "StressChaos": "stresschaos",
}


def render_chaos_manifest(chaos_type: str, namespace: str, app_name: str, params: dict) -> dict:
    """Chaos Mesh CRD 매니페스트. selector는 generic-app 차트의 `app:` 라벨.

    params는 chaos_specs.validate_params로 사전 검증된 값이어야 한다.
    """
    spec: dict = {
        "selector": {"namespaces": [namespace], "labelSelectors": {"app": app_name}},
        "mode": "all",
    }
    if chaos_type == "NetworkChaos":
        spec["action"] = params["action"]
        spec["delay"] = {"latency": f"{params['latency_ms']}ms"}
    elif chaos_type == "PodChaos":
        spec["action"] = params["action"]
    elif chaos_type == "StressChaos":
        spec["stressors"] = {"cpu": {"workers": 1, "load": params["cpu_load"]}}
    if "duration_s" in params:
        spec["duration"] = f"{params['duration_s']}s"
    return {
        "apiVersion": f"{_GROUP}/{_VERSION}",
        "kind": chaos_type,
        "metadata": {"generateName": f"exp-{app_name}-", "namespace": namespace},
        "spec": spec,
    }


class RealChaos:
    """Chaos Mesh CRD 주입/조회/삭제. namespace 인자는 항상 settings.sut_namespace와 같아야 한다 (phase/delete가 sut_namespace를 쓰므로)."""

    def __init__(self, settings):
        self.s = settings

    def _api(self):
        from kubernetes import client, config  # lazy

        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        return client.CustomObjectsApi()

    def inject(self, namespace: str, app_name: str, chaos_type: str, params: dict) -> str:
        assert namespace == self.s.sut_namespace, "chaos CRD는 sut_namespace에만 생성해야 함"
        manifest = render_chaos_manifest(chaos_type, namespace, app_name, params)
        resp = self._api().create_namespaced_custom_object(
            group=_GROUP, version=_VERSION, namespace=namespace,
            plural=CHAOS_PLURALS[chaos_type], body=manifest,
        )
        return resp["metadata"]["name"]

    def phase(self, chaos_type: str, crd_name: str) -> str:
        """status.conditions 기반: AllRecovered=True → recovered, AllInjected=True → running, 그 외 injecting."""
        obj = self._api().get_namespaced_custom_object(
            group=_GROUP, version=_VERSION, namespace=self.s.sut_namespace,
            plural=CHAOS_PLURALS[chaos_type], name=crd_name,
        )
        conditions = {c.get("type"): c.get("status") for c in (obj.get("status") or {}).get("conditions", [])}
        if conditions.get("AllRecovered") == "True":
            return "recovered"
        if conditions.get("AllInjected") == "True":
            return "running"
        return "injecting"

    def delete(self, chaos_type: str, crd_name: str) -> None:
        from kubernetes.client.rest import ApiException  # lazy

        try:
            self._api().delete_namespaced_custom_object(
                group=_GROUP, version=_VERSION, namespace=self.s.sut_namespace,
                plural=CHAOS_PLURALS[chaos_type], name=crd_name,
            )
        except ApiException as e:
            if e.status != 404:  # 이미 없으면 idempotent 성공
                raise
