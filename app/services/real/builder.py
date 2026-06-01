"""RealBuilder — Argo Workflows로 Kaniko 빌드 트리거 (운영, use_real_services=true).

build_workflow_manifest는 순수 함수(테스트 가능). k8s 호출은 메서드 안에서 lazy import.
"""
from __future__ import annotations

from app.services.interfaces import BuildRequest

_GROUP = "argoproj.io"
_VERSION = "v1alpha1"
_PLURAL = "workflows"

# Argo Workflows phase → 우리 상태 문자열
_PHASE_MAP = {
    "Pending": "pending",
    "Running": "running",
    "Succeeded": "succeeded",
    "Failed": "failed",
    "Error": "failed",
}


def build_workflow_manifest(req: BuildRequest, template: str, namespace: str) -> dict:
    """build-and-push WorkflowTemplate을 참조하는 Workflow 매니페스트."""
    return {
        "apiVersion": f"{_GROUP}/{_VERSION}",
        "kind": "Workflow",
        "metadata": {
            "generateName": f"build-{req.app_name}-",
            "namespace": namespace,
        },
        "spec": {
            "workflowTemplateRef": {"name": template},
            "arguments": {
                "parameters": [
                    {"name": "repo_url", "value": req.repo_url},
                    {"name": "revision", "value": req.git_sha},
                    {"name": "image", "value": req.image},
                    {"name": "framework", "value": req.framework},
                    {"name": "dockerfile", "value": req.dockerfile},
                ]
            },
        },
    }


class RealBuilder:
    def __init__(self, settings):
        self.s = settings

    def _api(self):
        from kubernetes import client, config  # lazy

        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        return client.CustomObjectsApi()

    def trigger_build(self, req: BuildRequest) -> str:
        manifest = build_workflow_manifest(req, self.s.build_workflow_template, self.s.argo_namespace)
        resp = self._api().create_namespaced_custom_object(
            group=_GROUP, version=_VERSION, namespace=self.s.argo_namespace,
            plural=_PLURAL, body=manifest,
        )
        return resp["metadata"]["name"]

    def build_status(self, workflow_name: str) -> str:
        obj = self._api().get_namespaced_custom_object(
            group=_GROUP, version=_VERSION, namespace=self.s.argo_namespace,
            plural=_PLURAL, name=workflow_name,
        )
        phase = (obj.get("status") or {}).get("phase", "")
        return _PHASE_MAP.get(phase, "pending")
