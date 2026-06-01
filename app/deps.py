"""FastAPI Depends 제공자. 외부 시스템은 Stub을 주입(이후 Real로 한 줄 교체)."""
from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.database import get_session
from app.db.repositories import AppRepository
from app.services import interfaces, stubs


def get_builder() -> interfaces.BuilderService:
    return stubs.StubBuilder()


def get_gitops() -> interfaces.GitOpsService:
    return stubs.StubGitOps()


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
