"""외부 시스템 계약. 라우터는 이 Protocol에만 의존(DIP). Slice 1=Stub, 이후=Real로 교체."""
from typing import Protocol


class BuilderService(Protocol):
    def trigger_build(self, app_id: int, git_sha: str) -> str:
        """빌드 트리거. workflow 이름 반환."""
        ...

    def build_status(self, workflow_name: str) -> str:
        """빌드 상태 문자열 반환 (pending/running/succeeded/failed)."""
        ...


class GitOpsService(Protocol):
    def bootstrap_app(self, name: str, repo_url: str, framework: str) -> None:
        """ArgoCD Application + values.yaml 커밋."""
        ...

    def update_image_tag(self, name: str, image_tag: str) -> None:
        ...


class ChaosService(Protocol):
    def inject(self, namespace: str, chaos_type: str, params: dict) -> str:
        """Chaos CRD 주입. CRD 이름 반환."""
        ...

    def delete(self, crd_name: str) -> None:
        ...


class PrometheusService(Protocol):
    def red_metrics(self, namespace: str) -> dict:
        """rate/error/duration(p99) 반환."""
        ...


class LokiService(Protocol):
    def tail(self, namespace: str, limit: int = 100) -> list[str]:
        ...


class K8sService(Protocol):
    def nodes(self) -> list[dict]:
        ...

    def pods(self, namespace: str) -> list[dict]:
        ...

    def components(self) -> list[dict]:
        """시스템 컴포넌트 상태 (Prometheus/Grafana/Loki/Chaos Mesh/ArgoCD)."""
        ...
