"""RealEksWorkload — EKS 앱의 in-place 회귀용 워크로드 서비스 (설계 2026-09-29 §1).

k3s 워크로드 서비스와 같은 K8s API(readiness·probe_http·patch_deployment·apply_deployment_env)를
기본 kubeconfig(real/kube.py, k8s_context)로 쓴다. 배포·삭제는 하지 않는다 — 준비 세션이 실제 SUT
네임스페이스를 그대로 가리키므로 deploy는 거부, teardown은 no-op(라이브 ns 삭제 원천 차단, 가드 1).
"""
from __future__ import annotations

import logging

from app.services.real.k3s_workload import RealK3sWorkload
from app.services.real.kube import load_kube

logger = logging.getLogger(__name__)


class RealEksWorkload(RealK3sWorkload):
    def _api_client(self):
        from kubernetes import client  # lazy: k8s SDK

        if self._client is None:
            load_kube(self.s)
            self._client = client.ApiClient()
        return self._client

    def deploy(self, namespace: str, manifest_yaml: str) -> None:
        raise NotImplementedError("EKS 앱은 in-place 검증 — 회귀 전용 배포를 하지 않는다")

    def teardown(self, namespace: str) -> None:
        logger.info("EKS in-place 세션 — namespace %s는 삭제하지 않는다", namespace)
