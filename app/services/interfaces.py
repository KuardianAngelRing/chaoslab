"""외부 시스템 계약. 라우터는 이 Protocol에만 의존(DIP). Slice 1=Stub, 이후=Real로 교체."""
from dataclasses import dataclass
from typing import Protocol, TypedDict


@dataclass
class BuildRequest:
    """빌드 1건에 필요한 정보 — 라우터가 DB/설정에서 조립해 Builder에 전달."""
    app_name: str
    repo_url: str
    framework: str
    git_sha: str
    image: str            # 전체 ECR 대상: <registry>/<app>:<sha8>
    dockerfile: str = "Dockerfile"


class EnvVar(TypedDict):
    key: str
    value: str
    is_secret: bool


class BuilderService(Protocol):
    def trigger_build(self, req: BuildRequest) -> str:
        """빌드 워크플로 생성. workflow 이름 반환."""
        ...

    def build_status(self, workflow_name: str) -> str:
        """빌드 상태 문자열 반환 (pending/running/succeeded/failed)."""
        ...

    def stop_build(self, workflow_name: str) -> None:
        """진행 중인 빌드 워크플로 중지."""
        ...


class GitOpsService(Protocol):
    def bootstrap_app(self, name: str, repo_url: str, port: int, health: str,
                      env: dict[str, str], secret_name: str) -> None:
        """ECR 레포 + ArgoCD Application + values.yaml(평문 env·secretName 포함) 커밋/푸시."""
        ...

    def update_image_tag(self, name: str, image: str) -> None:
        """gitops values.yaml 의 image를 갱신하고 커밋/푸시 (= 배포 트리거)."""
        ...

    def set_replicas(self, name: str, replicas: int) -> None:
        """gitops values.yaml 의 replicas 변경 커밋/푸시 (0=배포 중지, 1=재개)."""
        ...


class ChaosService(Protocol):
    def inject(self, namespace: str, app_name: str, chaos_type: str, params: dict) -> str:
        """Chaos CRD 생성 (selector = app 라벨). CRD 이름 반환."""
        ...

    def phase(self, chaos_type: str, crd_name: str) -> str:
        """injecting | running | recovered (CRD conditions 기반)."""
        ...

    def delete(self, chaos_type: str, crd_name: str) -> None:
        ...


class PrometheusService(Protocol):
    def red_metrics(self, namespace: str) -> dict:
        """rate/error/duration(p99) 반환."""
        ...


class LokiService(Protocol):
    def tail(self, namespace: str, limit: int = 100) -> list[str]:
        ...


class K8sService(Protocol):
    def apply_env_secret(self, namespace: str, name: str, data: dict[str, str]) -> None:
        """앱 시크릿을 K8s Secret(Opaque)으로 생성/갱신 (git에 안 들어감)."""
        ...

    def restart_deployment(self, namespace: str, name: str) -> None:
        """Deployment rollout restart — 파드 재기동(재배포)."""
        ...

    def nodes(self) -> list[dict]:
        ...

    def pods(self, namespace: str) -> list[dict]:
        ...

    def components(self) -> list[dict]:
        """시스템 컴포넌트 상태 (Prometheus/Grafana/Loki/Chaos Mesh/ArgoCD)."""
        ...


class HandoffSourceService(Protocol):
    """AI 전달 페이로드 재료 중 외부 시스템산(産) — Real 구현은 Slice 4·5에서.

    반환 dict의 키는 services/agent/handoff_schema.py 계약 모델과 1:1.
    """

    def phase_summary(self, namespace: str, app_name: str, phase: str) -> dict:
        """단계(baseline|fault|recovery)별 지표 요약. PhaseSummary와 동일 키."""
        ...

    def istio_config(self, namespace: str, app_name: str) -> dict:
        """{"virtual_service_yaml": str, "destination_rule_yaml": str}."""
        ...

    def deployment_info(self, namespace: str, app_name: str) -> dict:
        """{"replicas": int, "probes": dict, "resources": dict}."""
        ...

    def events(self, namespace: str, app_name: str) -> list[dict]:
        """K8s 이벤트 원본 목록. K8sEvent와 동일 키."""
        ...

    def error_logs(self, namespace: str, app_name: str, limit: int = 20) -> list[str]:
        """중복 제거된 에러 로그 샘플, 최대 limit개."""
        ...
