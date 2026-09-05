"""외부 시스템 계약. 라우터는 이 Protocol에만 의존(DIP). Slice 1=Stub, 이후=Real로 교체."""
from dataclasses import dataclass
from datetime import datetime
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


class K3sWorkloadService(Protocol):
    """k3s 실험용 현장 배포(ADR-0009) — 실험마다 전용 ns에 manifest 배포, 종료 시 삭제."""

    def deploy(self, namespace: str, manifest_yaml: str) -> None:
        """ns 생성(idempotent) + manifest 문서들 apply."""
        ...

    def wait_ready(self, namespace: str, timeout_s: int = 180) -> bool:
        """ns 안 Deployment 전부 ready될 때까지 대기. 타임아웃이면 False."""
        ...

    def readiness(self, namespace: str) -> dict:
        """2단계 UI가 보여줄 Deployment/Pod 준비 상태 스냅샷."""
        ...

    def probe_http(self, namespace: str, service: str, path: str) -> dict:
        """API server의 Service proxy로 사용자 경로를 1회 호출한다."""
        ...

    def apply_deployment_env(self, namespace: str, deployment: str, container: str,
                             key: str, value: str, timeout_s: int = 180) -> dict:
        """허용된 Deployment 환경변수를 변경하고 rollout 완료까지 확인한다."""
        ...

    def teardown(self, namespace: str) -> None:
        """ns 통째 삭제 (idempotent — 이미 없으면 성공)."""
        ...


class ChaosService(Protocol):
    def inject(self, namespace: str, app_name: str, chaos_type: str, params: dict,
               target_selector: dict[str, str] | None = None) -> str:
        """Chaos CRD 생성 (selector = app 라벨). CRD 이름 반환."""
        ...

    def phase(self, chaos_type: str, crd_name: str) -> str:
        """injecting | running | recovered (CRD conditions 기반)."""
        ...

    def delete(self, chaos_type: str, crd_name: str) -> None:
        ...


class PrometheusService(Protocol):
    def phase_summary(self, namespace: str, app_name: str, phase: str,
                      start: datetime, end: datetime) -> dict:
        """[start, end] 구간 소급 집계 — PhaseSummary 계약과 동일 키.

        recovery_seconds는 항상 None으로 반환(구간 경계를 아는 호출자가 채움).
        """
        ...

    def red_metrics(self, namespace: str) -> dict:
        """rate/error/duration(p99) 반환."""
        ...

    def live_snapshot(self, namespace: str, app_name: str) -> dict:
        """최근 1분 rate 기준 즉시값. 키: ts(iso), rps, error_rate_pct, p95_ms, p99_ms, ready_pods.

        조회 실패 시 예외 대신 값 None (스트림은 끊기지 않는다).
        """
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


class TunnelService(Protocol):
    """SSH 터널 생명주기 — 로컬 k3s API(localhost:6443) 접근 경로를 앱이 소유.

    lifespan에서 start/stop 1회씩 호출되는 싱글턴(deps.make_tunnel).
    """

    async def start(self) -> None:
        """감시 태스크 시작 — 터널을 열고, 끊기면 백오프 재접속."""
        ...

    async def stop(self) -> None:
        """감시 태스크와 ssh 프로세스 정리."""
        ...

    def status(self) -> dict:
        """{"state": "disabled|connecting|connected|retrying", "detail": str}."""
        ...


class LocalK8sService(Protocol):
    """로컬(라즈베리파이 k3s) 클러스터 현황 — SSH 터널 경유 kubeconfig 읽기 전용 조회."""

    def overview(self) -> dict:
        """infra_local 페이지 컨텍스트 스냅샷.

        {"cluster": {name, version, arch, access, healthy},
         "pod_count": int, "namespaces": [str],
         "nodes": [{name, model, role, cpu_pct, mem_pct, temp_c(None 가능), status}],
         "components": [{name, detail, ns, status}],
         "error": str}  # error 키는 조회 실패 시에만
        """
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


class HypothesisAgentService(Protocol):
    """가설 수립 에이전트 (ADR-0010) — 조립 페이로드 → 순수 추론, 도구 없음.

    반환은 검증 전 원시 JSON 호환 데이터 — 검증·재시도는 hypothesis_validation
    공통 함수가 담당(Stub·Real 동일 적용). feedback은 교정 재시도용 오류 요약.
    """

    def generate(self, payload, feedback: str = "") -> list:
        """서사형 후보 N개(params 없음) — CandidateProposal 호환 dict 배열."""
        ...

    def concretize(self, payload, user_text: str, feedback: str = "") -> dict:
        """직접 입력 텍스트 → 후보 1개 — CandidateProposal 호환 dict."""
        ...

    def detail(self, payload, candidate, feedback: str = "") -> dict:
        """선택 후보의 params 구체화 — DetailingResult 호환 dict."""
        ...

    def snapshot(self) -> dict:
        """{"model_name": str, "cli_version": str} — 재현성 기록(하이브리드 4)."""
        ...
