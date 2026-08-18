"""RealK3sWorkload — k3s 실험용 현장 배포/정리 (ADR-0009).

실험마다 전용 namespace를 만들어 앱 manifest를 apply하고, 실험이 끝나면
namespace째 삭제한다. SSH 터널 경유 로컬 kubeconfig 사용 (RealLocalK8s와 동일 게이트).
k8s SDK·yaml은 lazy import — stub/테스트는 의존성 불필요.
"""
from __future__ import annotations

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
        from kubernetes import client, utils  # lazy
        from kubernetes.client.rest import ApiException

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
        for doc in docs:
            # manifest에 namespace가 박혀 있어도 실험 전용 ns로 강제
            doc.setdefault("metadata", {})["namespace"] = namespace
            utils.create_from_dict(api_client, doc, namespace=namespace)

    def wait_ready(self, namespace: str, timeout_s: int = 180) -> bool:
        from kubernetes import client  # lazy

        apps = client.AppsV1Api(self._api_client())
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            deployments = apps.list_namespaced_deployment(
                namespace, _request_timeout=_TIMEOUT).items
            if deployments and all(
                (d.status.ready_replicas or 0) >= (d.spec.replicas or 1)
                for d in deployments
            ):
                return True
            time.sleep(_POLL_S)
        return False

    def teardown(self, namespace: str) -> None:
        from kubernetes import client  # lazy
        from kubernetes.client.rest import ApiException

        core = client.CoreV1Api(self._api_client())
        try:
            core.delete_namespace(namespace, _request_timeout=_TIMEOUT)
        except ApiException as e:
            if e.status != 404:  # 이미 없으면 idempotent 성공
                raise
