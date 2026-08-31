"""RealChaos — Chaos Mesh CRD 주입/조회/삭제 (운영, use_real_services=true).

render_chaos_manifest는 순수 함수(테스트 가능). k8s 호출은 메서드 안에서 lazy import.
chaos_type은 chaos_specs의 슬러그(예: "network-delay") — CRD kind·action은 스펙에서 해석.
"""
from __future__ import annotations

from app.services.chaos_specs import CHAOS_SPECS, kind_of

_GROUP = "chaos-mesh.org"
_VERSION = "v1alpha1"

CHAOS_PLURALS = {
    "NetworkChaos": "networkchaos",
    "PodChaos": "podchaos",
    "StressChaos": "stresschaos",
}

# bandwidth action 필수 상수 (Chaos Mesh 요구값 — 사용자 입력은 rate만)
_BANDWIDTH_LIMIT = 20_971_520
_BANDWIDTH_BUFFER = 10_000


def _plural(chaos_type: str) -> str:
    return CHAOS_PLURALS[kind_of(chaos_type)]


def render_chaos_manifest(chaos_type: str, namespace: str, app_name: str, params: dict,
                          label_selector: bool = True) -> dict:
    """Chaos Mesh CRD 매니페스트.

    selector: EKS는 generic-app 차트의 `app:` 라벨(label_selector=True),
    k3s 현장 배포(ADR-0009)는 실험 전용 ns 전체(label_selector=False —
    다중 서비스 manifest는 서비스별 app 라벨이라 앱 이름 매칭 불가).
    params는 chaos_specs.validate_params로 사전 검증된 값이어야 한다.
    """
    chaos_spec = CHAOS_SPECS[chaos_type]
    kind, action = chaos_spec["kind"], chaos_spec["action"]

    selector: dict = {"namespaces": [namespace]}
    if label_selector:
        selector["labelSelectors"] = {"app": app_name}
    spec: dict = {"selector": selector, "mode": "all"}

    if kind == "NetworkChaos":
        spec["action"] = action
        if action == "delay":
            spec["delay"] = {"latency": f"{params['latency_ms']}ms"}
        elif action == "loss":
            spec["loss"] = {"loss": str(params["loss_percent"])}
        elif action == "partition":
            spec["direction"] = "both"  # target 미지정 — 선택 파드를 전체와 단절
        elif action == "bandwidth":
            spec["bandwidth"] = {"rate": f"{params['rate_mbps']}mbps",
                                 "limit": _BANDWIDTH_LIMIT, "buffer": _BANDWIDTH_BUFFER}
    elif kind == "PodChaos":
        spec["action"] = action
        if action == "container-kill":
            spec["containerNames"] = [params["container_name"]]
    elif kind == "StressChaos":
        if action == "cpu":
            spec["stressors"] = {"cpu": {"workers": 1, "load": params["cpu_load"]}}
        elif action == "memory":
            spec["stressors"] = {"memory": {"workers": 1, "size": f"{params['memory_mb']}MiB"}}

    if "duration_s" in params:
        spec["duration"] = f"{params['duration_s']}s"
    return {
        "apiVersion": f"{_GROUP}/{_VERSION}",
        "kind": kind,
        "metadata": {"generateName": f"exp-{app_name}-", "namespace": namespace},
        "spec": spec,
    }


class RealChaos:
    """Chaos Mesh CRD 주입/조회/삭제 — 생성 시 namespace 바인딩.

    EKS: 기본(in-cluster/기본 kubeconfig) + sut_namespace + app 라벨 selector.
    k3s: 로컬 kubeconfig(SSH 터널) + 실험 전용 ns + ns 전체 selector (ADR-0009).
    """

    def __init__(self, settings, namespace: str | None = None,
                 kubeconfig: str = "", label_selector: bool = True):
        self.s = settings
        self.namespace = namespace or settings.sut_namespace
        self.kubeconfig = kubeconfig
        self.label_selector = label_selector

    def _api(self):
        from kubernetes import client, config  # lazy

        if self.kubeconfig:  # k3s: SSH 터널 경유 로컬 kubeconfig 바인딩 (ADR-0009)
            import os
            api_client = config.new_client_from_config(
                config_file=os.path.expanduser(self.kubeconfig))
            return client.CustomObjectsApi(api_client)
        from app.services.real.kube import load_kube

        load_kube(self.s)
        return client.CustomObjectsApi()

    def inject(self, namespace: str, app_name: str, chaos_type: str, params: dict) -> str:
        assert namespace == self.namespace, "chaos CRD는 바인딩된 namespace에만 생성해야 함"
        manifest = render_chaos_manifest(chaos_type, namespace, app_name, params,
                                         label_selector=self.label_selector)
        resp = self._api().create_namespaced_custom_object(
            group=_GROUP, version=_VERSION, namespace=namespace,
            plural=_plural(chaos_type), body=manifest,
        )
        return resp["metadata"]["name"]

    def phase(self, chaos_type: str, crd_name: str) -> str:
        """status.conditions 기반: AllRecovered=True → recovered, AllInjected=True → running, 그 외 injecting."""
        obj = self._api().get_namespaced_custom_object(
            group=_GROUP, version=_VERSION, namespace=self.namespace,
            plural=_plural(chaos_type), name=crd_name,
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
                group=_GROUP, version=_VERSION, namespace=self.namespace,
                plural=_plural(chaos_type), name=crd_name,
            )
        except ApiException as e:
            if e.status != 404:  # 이미 없으면 idempotent 성공
                raise
