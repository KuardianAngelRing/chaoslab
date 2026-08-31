"""FastAPI Depends 제공자. use_real_services 플래그로 Stub↔Real 전환(DIP).

make_* 팩토리는 백그라운드 작업에서도 재사용(요청 컨텍스트 밖). get_*는 Depends용 래퍼.
"""
from fastapi import Depends
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import get_session
from app.db.repositories import AppRepository
from app.services import interfaces, stubs


def make_builder() -> interfaces.BuilderService:
    if settings.use_real_services:
        from app.services.real.builder import RealBuilder  # lazy: k8s SDK
        return RealBuilder(settings)
    return stubs.StubBuilder()


def make_gitops() -> interfaces.GitOpsService:
    if settings.use_real_services:
        from app.services.real.gitops import RealGitOps  # lazy: boto3/git
        return RealGitOps(settings)
    return stubs.StubGitOps()


def make_k8s() -> interfaces.K8sService:
    if settings.use_real_services:
        from app.services.real.k8s import RealK8s  # lazy: k8s SDK
        return RealK8s(settings)
    return stubs.StubK8s()


def make_chaos(env: str = "eks", namespace: str | None = None) -> interfaces.ChaosService:
    """앱 환경 기반 라우팅(ADR-0002): k3s는 SSH 터널 경유 로컬 kubeconfig + 실험 전용 ns
    전체 selector(ADR-0009), eks는 기존(sut_namespace + app 라벨). Real 게이트는
    k3s=local_kubeconfig(로컬 인프라와 동일), eks=use_real_services."""
    if env == "k3s":
        if settings.local_kubeconfig:
            from app.services.real.chaos import RealChaos  # lazy: k8s SDK
            return RealChaos(settings, namespace=namespace,
                             kubeconfig=settings.local_kubeconfig, label_selector=False)
        return stubs.StubChaos()
    if settings.use_real_services:
        from app.services.real.chaos import RealChaos  # lazy: k8s SDK
        return RealChaos(settings)
    return stubs.StubChaos()


def make_k3s_workload() -> interfaces.K3sWorkloadService:
    if settings.local_kubeconfig:
        from app.services.real.k3s_workload import RealK3sWorkload  # lazy: k8s SDK
        return RealK3sWorkload(settings)
    return stubs.StubK3sWorkload()


_tunnel: interfaces.TunnelService | None = None


def make_tunnel() -> interfaces.TunnelService:
    """터널은 프로세스 생명주기를 갖는 싱글턴 — 매 호출 새로 만들지 않는다."""
    global _tunnel
    if _tunnel is None:
        if settings.local_ssh_host:
            from app.services.real.tunnel import RealTunnel  # lazy
            _tunnel = RealTunnel(settings)
        else:
            _tunnel = stubs.StubTunnel()
    return _tunnel


def make_local_k8s() -> interfaces.LocalK8sService:
    # use_real_services(AWS)와 독립 — 로컬 k3s는 kubeconfig 경로 설정 여부로 전환.
    if settings.local_kubeconfig:
        from app.services.real.local_k8s import RealLocalK8s  # lazy: k8s SDK
        return RealLocalK8s(settings)
    return stubs.StubLocalK8s()


def make_hypothesis_agent() -> interfaces.HypothesisAgentService:
    # use_real_services(AWS)와 독립 — HYPOTHESIS_AGENT 선택형 게이트(ADR-0010).
    # "claude"=구독제 CLI 실호출(호스트 로그인 전제) · 그 외/"stub"=Stub.
    # 새 에이전트(예: codex)는 구현체 추가 + 여기 분기 한 줄이 전부.
    if settings.hypothesis_agent == "claude":
        from app.services.real.claude_agent import ClaudeCliHypothesisAgent  # lazy: subprocess
        return ClaudeCliHypothesisAgent(settings)
    return stubs.StubHypothesisAgent()


def make_prometheus() -> interfaces.PrometheusService:
    if settings.use_real_services:
        from app.services.real.prometheus import RealPrometheus  # lazy: httpx
        return RealPrometheus(settings)
    return stubs.StubPrometheus()


def make_loki() -> interfaces.LokiService:
    if settings.use_real_services:
        from app.services.real.loki import RealLoki  # lazy: httpx
        return RealLoki(settings)
    return stubs.StubLoki()


def make_handoff_source() -> interfaces.HandoffSourceService:
    if settings.use_real_services:
        from app.services.real.handoff_source import RealHandoffSource  # lazy: k8s SDK
        return RealHandoffSource(settings)
    return stubs.StubHandoffSource()


def get_builder() -> interfaces.BuilderService:
    return make_builder()


def get_gitops() -> interfaces.GitOpsService:
    return make_gitops()


def get_chaos() -> interfaces.ChaosService:
    return make_chaos()


def get_prometheus() -> interfaces.PrometheusService:
    return make_prometheus()


def get_loki() -> interfaces.LokiService:
    return make_loki()


def get_k8s() -> interfaces.K8sService:
    return make_k8s()


def get_local_k8s() -> interfaces.LocalK8sService:
    return make_local_k8s()


def get_tunnel() -> interfaces.TunnelService:
    return make_tunnel()


def get_handoff_source() -> interfaces.HandoffSourceService:
    return make_handoff_source()


def get_app_count(session: Session = Depends(get_session)) -> int:
    """사이드바 Apps 카운트 — 한 곳에서만 계산 (DRY)."""
    return len(AppRepository(session).list_all())
