"""RealK3sWorkload — k3s 실험용 현장 배포/정리 (ADR-0009).

실험마다 전용 namespace를 만들어 앱 manifest를 apply하고, 실험이 끝나면
namespace째 삭제한다. SSH 터널 경유 로컬 kubeconfig 사용 (RealLocalK8s와 동일 게이트).
k8s SDK·yaml은 lazy import — stub/테스트는 의존성 불필요.
"""
from __future__ import annotations

import json
import os
import time

_TIMEOUT = (3, 30)
_POLL_S = 5


class RealK3sWorkload:
    def __init__(self, settings):
        self.s = settings
        self._client = None

    def _api_client(self):
        from kubernetes import config  # lazy

        if self._client is None:
            self._client = config.new_client_from_config(
                config_file=os.path.expanduser(self.s.local_kubeconfig))
        return self._client

    def deploy(self, namespace: str, manifest_yaml: str) -> None:
        import yaml  # lazy (kubernetes 의존성에 포함)
        from kubernetes import client  # lazy
        from kubernetes.client.rest import ApiException
        from kubernetes.dynamic import DynamicClient
        from kubernetes.dynamic.exceptions import NotFoundError

        docs = [d for d in yaml.safe_load_all(manifest_yaml or "") if d]
        if not docs:
            raise ValueError("배포할 manifest가 비어 있음 — 앱 등록 시 manifest 저장 필요")

        api_client = self._api_client()
        core = client.CoreV1Api(api_client)
        try:
            core.create_namespace(
                client.V1Namespace(metadata=client.V1ObjectMeta(
                    name=namespace, labels={"app.kubernetes.io/managed-by": "chaoslab"})),
                _request_timeout=_TIMEOUT)
        except ApiException as e:
            if e.status != 409:  # 이미 있으면 재사용
                raise
        dynamic = DynamicClient(api_client)
        for doc in docs:
            _upsert_manifest_resource(dynamic, doc, namespace, NotFoundError)

    def wait_ready(self, namespace: str, timeout_s: int = 180) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            snapshot = self.readiness(namespace)
            if snapshot["deployments_total"] and (
                snapshot["deployments_ready"] == snapshot["deployments_total"]
            ):
                return True
            time.sleep(_POLL_S)
        return False

    def readiness(self, namespace: str) -> dict:
        from kubernetes import client  # lazy

        api_client = self._api_client()
        deployments = client.AppsV1Api(api_client).list_namespaced_deployment(
            namespace, _request_timeout=_TIMEOUT).items
        pods = client.CoreV1Api(api_client).list_namespaced_pod(
            namespace, _request_timeout=_TIMEOUT).items
        blockers = []
        ready_pods = 0
        restart_count = 0
        for pod in pods:
            statuses = pod.status.container_statuses or []
            restart_count += sum(status.restart_count or 0 for status in statuses)
            is_ready = pod.status.phase == "Running" and bool(statuses) and all(s.ready for s in statuses)
            if is_ready:
                ready_pods += 1
                continue
            reason = pod.status.reason or pod.status.phase or "Pending"
            for status in statuses:
                waiting = status.state.waiting if status.state else None
                if waiting and waiting.reason:
                    reason = waiting.reason
                    break
            blockers.append({"name": pod.metadata.name, "reason": reason})
        return {
            "deployments_ready": sum(
                (d.status.ready_replicas or 0) >= (d.spec.replicas or 1) for d in deployments),
            "deployments_total": len(deployments),
            "pods_ready": ready_pods,
            "pods_total": len(pods),
            "restart_count": restart_count,
            "blockers": blockers[:3],
        }

    def probe_http(self, namespace: str, service: str, path: str) -> dict:
        from kubernetes import client  # lazy
        from kubernetes.client.rest import ApiException

        started = time.monotonic()
        status_code = 200
        payload = None
        error = ""
        try:
            core = client.CoreV1Api(self._api_client())
            # k3s v1.35 apiserver는 포트 미지정 서비스 프록시를 "no endpoints"로 거부
            # (라이브 08/31 확인) — 서비스 첫 포트를 조회해 name에 명시한다.
            port = core.read_namespaced_service(
                service, namespace, _request_timeout=_TIMEOUT).spec.ports[0].port
            raw = core.connect_get_namespaced_service_proxy_with_path(
                name=f"{service}:{port}",
                namespace=namespace,
                path=path.lstrip("/"),
                _request_timeout=_TIMEOUT,
            )
            try:
                # k8s client는 프록시 응답을 dict-repr 문자열로 줄 수 있음 —
                # 파싱 실패를 HTTP 실패(status 0)로 오판하지 않는다.
                payload = json.loads(raw) if isinstance(raw, str) and raw else raw
            except (TypeError, json.JSONDecodeError):
                payload = raw
        except ApiException as exc:
            status_code = int(exc.status or 0)
            error = str(exc.reason or exc)
            try:
                payload = json.loads(exc.body) if exc.body else None
            except (TypeError, json.JSONDecodeError):
                payload = None
        except Exception as exc:
            status_code = 0
            error = str(exc)
        return {
            "status_code": status_code,
            "latency_ms": round((time.monotonic() - started) * 1000, 1),
            "ok": 200 <= status_code < 300,
            "error": error,
            "payload": payload,
        }

    def apply_deployment_env(self, namespace: str, deployment: str, container: str,
                             key: str, value: str, timeout_s: int = 180) -> dict:
        from kubernetes import client  # lazy

        apps = client.AppsV1Api(self._api_client())
        current = apps.read_namespaced_deployment(deployment, namespace, _request_timeout=_TIMEOUT)
        target = next((item for item in current.spec.template.spec.containers
                       if item.name == container), None)
        if target is None:
            raise ValueError(f"Deployment {deployment}에서 container {container}를 찾을 수 없습니다")
        env = next((item for item in (target.env or []) if item.name == key), None)
        if env is None or env.value is None:
            raise ValueError(f"Deployment {deployment}에서 환경변수 {key}를 찾을 수 없습니다")
        before = env.value
        if before != value:
            apps.patch_namespaced_deployment(
                deployment,
                namespace,
                {"spec": {"template": {"spec": {"containers": [{
                    "name": container,
                    "env": [{"name": key, "value": value}],
                }]}}}},
                _request_timeout=_TIMEOUT,
            )
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                updated = apps.read_namespaced_deployment(
                    deployment, namespace, _request_timeout=_TIMEOUT)
                desired = updated.spec.replicas or 1
                status = updated.status
                if (status.observed_generation or 0) >= (updated.metadata.generation or 0) and (
                    status.updated_replicas or 0
                ) >= desired and (status.ready_replicas or 0) >= desired:
                    break
                time.sleep(_POLL_S)
            else:
                raise RuntimeError(f"Deployment {deployment} rollout 시간이 초과됐습니다")
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
        from kubernetes import client  # lazy
        from kubernetes.client.rest import ApiException

        core = client.CoreV1Api(self._api_client())
        try:
            core.delete_namespace(namespace, _request_timeout=_TIMEOUT)
        except ApiException as e:
            if e.status != 404:  # 이미 없으면 idempotent 성공
                raise


def _upsert_manifest_resource(dynamic, doc: dict, namespace: str, not_found_error: type) -> None:
    """namespace-scoped manifest를 생성하거나 기존 리소스에 merge patch한다."""
    metadata = doc.setdefault("metadata", {})
    metadata["namespace"] = namespace
    name = metadata.get("name")
    if not name:
        raise ValueError("현장 배포 manifest 리소스에는 metadata.name이 필요합니다")
    resource = dynamic.resources.get(api_version=doc["apiVersion"], kind=doc["kind"])
    if not resource.namespaced:
        raise ValueError(f"cluster-scoped 리소스는 배포할 수 없습니다: {doc['kind']}/{name}")
    try:
        resource.get(name=name, namespace=namespace)
    except not_found_error:
        resource.create(body=doc, namespace=namespace)
    else:
        resource.patch(
            name=name,
            namespace=namespace,
            body=doc,
            content_type="application/merge-patch+json",
        )
