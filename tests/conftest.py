import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db.database import Base, get_session
from app.db.seed import seed_data
from app.main import app


@pytest.fixture(autouse=True)
def _force_stub_mode(monkeypatch):
    """테스트는 항상 Stub 모드 — 로컬 .env(USE_REAL_SERVICES=true)가 있어도
    boto3/git/k8s 실호출이 일어나지 않게 강제(hermetic·안전)."""
    monkeypatch.setattr(settings, "use_real_services", False)
    monkeypatch.setattr(settings, "local_kubeconfig", "")  # 로컬 k3s도 항상 Stub
    monkeypatch.setattr(settings, "local_ssh_host", "")    # SSH 터널도 항상 미관리(Stub)
    monkeypatch.setattr(settings, "hypothesis_agent", "stub")  # claude CLI 실호출도 항상 Stub


@pytest.fixture(autouse=True)
def _reset_sse_app_status():
    """sse-starlette의 전역 AppStatus.should_exit_event는 처음 await된 이벤트 루프에 묶인다.
    TestClient는 테스트마다 새 루프를 쓰므로, SSE 스트림을 끝까지 읽은 테스트 뒤에 오는
    스트림 테스트가 'bound to a different event loop'로 깨진다 — 매 테스트 초기화(공식 권장 패턴)."""
    from sse_starlette.sse import AppStatus

    AppStatus.should_exit_event = None
    yield
    AppStatus.should_exit_event = None


# 전역 SessionLocal(파일 DB)을 직접 쓰는 모듈 — 백그라운드 워처·SSE·워처 훅. client fixture가 전부
# "테이블만 있는 빈 in-memory DB"로 바꾼다: 요청은 seed된 DB를, 워처는 빈 DB를 보므로 워처가 행을 못 찾고
# 즉시 종료한다(파일 chaoslab.db에 테이블만 있고 테스트 행은 없던 예전 동작을 파일 없이 재현 — 없으면
# no such table, 있으면 오염). 워처가 데이터를 봐야 하는 테스트는 해당 모듈의 SessionLocal을 직접 monkeypatch한다.
_SESSIONLOCAL_MODULES = (
    "app.db.database", "app.routers.apps", "app.routers.builds", "app.routers.experiments",
    "app.routers.hypothesis", "app.routers.preparations", "app.routers.scenario_runs",
    "app.services.regression",
)


@pytest.fixture
def client(monkeypatch):
    """앱과 분리된 in-memory DB를 seed해서 주입 (hermetic — 파일 DB에 의존하지 않음)."""
    import importlib

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # 단일 연결 공유 → 모든 세션이 같은 in-memory DB
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    watcher_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=watcher_engine)
    WatcherSessionLocal = sessionmaker(bind=watcher_engine, autoflush=False, expire_on_commit=False)
    for name in _SESSIONLOCAL_MODULES:
        monkeypatch.setattr(importlib.import_module(name), "SessionLocal", WatcherSessionLocal)

    seed_session = TestingSessionLocal()
    seed_data(seed_session)
    seed_session.close()

    def override_get_session():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = Session()
    try:
        yield s
    finally:
        s.close()
