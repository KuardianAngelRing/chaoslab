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


def get_builder() -> interfaces.BuilderService:
    return make_builder()


def get_gitops() -> interfaces.GitOpsService:
    return make_gitops()


def get_chaos() -> interfaces.ChaosService:
    return stubs.StubChaos()


def get_prometheus() -> interfaces.PrometheusService:
    return stubs.StubPrometheus()


def get_loki() -> interfaces.LokiService:
    return stubs.StubLoki()


def get_k8s() -> interfaces.K8sService:
    return stubs.StubK8s()


def get_app_count(session: Session = Depends(get_session)) -> int:
    """사이드바 Apps 카운트 — 한 곳에서만 계산 (DRY)."""
    return len(AppRepository(session).list_all())
