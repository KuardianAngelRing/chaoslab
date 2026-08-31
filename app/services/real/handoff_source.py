"""핸드오프 재료 실조회 — Istio 설정·배포 정보·이벤트는 K8s API, 로그는 Loki, 지표는 Prometheus."""
from datetime import datetime, timedelta, timezone

import yaml  # kubernetes SDK 동반 의존성

from app.services.real.kube import load_kube

_ISTIO_GROUP = "networking.istio.io"
_ISTIO_VERSION = "v1beta1"


class RealHandoffSource:
    def __init__(self, settings):
        self.s = settings

    def _custom(self):
        from kubernetes import client  # lazy

        load_kube(self.s)
        return client.CustomObjectsApi()

    def _core(self):
        from kubernetes import client  # lazy

        load_kube(self.s)
        return client.CoreV1Api()

    def phase_summary(self, namespace: str, app_name: str, phase: str) -> dict:
        # 저장값 우선 규칙 때문에 폴백 전용 — 최근 5분 창으로 집계
        from app.services.real.prometheus import RealPrometheus

        end = datetime.now(timezone.utc)
        return RealPrometheus(self.s).phase_summary(
            namespace, app_name, phase, end - timedelta(minutes=5), end)

    def _istio_yaml(self, plural: str, namespace: str, name: str) -> str:
        from kubernetes.client.rest import ApiException  # lazy

        try:
            obj = self._custom().get_namespaced_custom_object(
                _ISTIO_GROUP, _ISTIO_VERSION, namespace, plural, name)
        except ApiException as e:
            if e.status == 404:
                return ""  # DR 미배포 앱 등 — 스키마가 빈 문자열 허용
            raise
        obj.pop("status", None)
        obj.get("metadata", {}).pop("managedFields", None)
        return yaml.safe_dump(obj, allow_unicode=True, sort_keys=False)

    def istio_config(self, namespace: str, app_name: str) -> dict:
        return {
            "virtual_service_yaml": self._istio_yaml("virtualservices", namespace, app_name),
            "destination_rule_yaml": self._istio_yaml("destinationrules", namespace, app_name),
        }

    def deployment_info(self, namespace: str, app_name: str) -> dict:
        from kubernetes import client  # lazy

        load_kube(self.s)
        dep = client.AppsV1Api().read_namespaced_deployment(app_name, namespace)
        c = dep.spec.template.spec.containers[0]
        sanitize = client.ApiClient().sanitize_for_serialization
        return {
            "replicas": dep.spec.replicas or 0,
            "probes": {
                "readiness": sanitize(c.readiness_probe) or {},
                "liveness": sanitize(c.liveness_probe) or {},
            },
            "resources": sanitize(c.resources) or {},
        }

    def events(self, namespace: str, app_name: str) -> list[dict]:
        out = []
        for ev in self._core().list_namespaced_event(namespace).items:
            obj = ev.involved_object
            if not (obj and obj.name and obj.name.startswith(app_name)):
                continue
            ts = ev.last_timestamp or ev.event_time
            out.append({
                "timestamp": ts.isoformat() if ts else "",
                "type": ev.type or "", "reason": ev.reason or "",
                "object": f"{(obj.kind or 'object').lower()}/{obj.name}",
                "message": ev.message or "",
            })
        return out

    def error_logs(self, namespace: str, app_name: str, limit: int = 20) -> list[str]:
        from app.services.real.loki import RealLoki

        return RealLoki(self.s).error_logs(namespace, app_name, limit)
