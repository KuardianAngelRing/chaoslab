"""빌드 이력 라우트 + build_duration — stub 모드(기본)."""
from datetime import datetime, timedelta, timezone

from app.db.models import App, Build
from app.routers.builds import build_duration


def test_build_duration_unfinished():
    assert build_duration(datetime.now(timezone.utc), None) == "—"


def test_build_duration_roundtrip(db_session):
    """DB 라운드트립(SQLite는 naive 반환) 후에도 정상 계산."""
    app = App(name="d", repo_url="https://github.com/x/d", framework="fastapi")
    db_session.add(app)
    db_session.commit()
    start = datetime.now(timezone.utc)
    b = Build(app_id=app.id, started_at=start, finished_at=start + timedelta(seconds=125))
    db_session.add(b)
    db_session.commit()
    db_session.refresh(b)
    assert build_duration(b.started_at, b.finished_at) == "2분 5초"


def test_build_history_lists_builds(client):
    # seed app id=1 (online-boutique)에는 빌드 1건(image_tag a1b2c3d4)
    r = client.get("/apps/1/builds")
    assert r.status_code == 200
    assert "a1b2c3d4" in r.text


def test_build_history_empty_state(client):
    # seed app id=2 (payment-api)는 빌드 없음
    r = client.get("/apps/2/builds")
    assert r.status_code == 200
    assert "빌드 이력이 없어요" in r.text


def test_build_history_unknown_404(client):
    assert client.get("/apps/99999/builds").status_code == 404


import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base


@pytest.fixture(autouse=True)
def _reset_sse_app_status():
    """sse_starlette의 AppStatus.should_exit_event를 테스트 간 초기화.

    TestClient가 테스트마다 새 이벤트 루프를 생성하므로, 이전 루프에서
    만들어진 anyio.Event는 재사용 시 RuntimeError(bound to different loop)를
    일으킨다. 각 테스트 전·후 None으로 리셋해 다음 루프에서 새로 생성되게 함.
    """
    try:
        from sse_starlette.sse import AppStatus
        AppStatus.should_exit_event = None
        AppStatus.should_exit = False
    except ImportError:
        pass
    yield
    try:
        from sse_starlette.sse import AppStatus
        AppStatus.should_exit_event = None
        AppStatus.should_exit = False
    except ImportError:
        pass


def _engine_with_status(status):
    """단일 App(id=1, 주어진 status)을 가진 격리 엔진의 세션메이커."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = Session()
    s.add(App(name="demo", repo_url="https://github.com/x/demo",
              framework="fastapi", status=status))
    s.commit()
    s.close()
    return Session


class _FlipSession:
    """폴링마다 다음 status를 돌려주는 가짜 세션 (시간 전이 모사)."""
    def __init__(self, statuses):
        self._statuses = list(statuses)

    def get(self, model, pk):
        st = self._statuses.pop(0) if self._statuses else "healthy"
        return App(name="demo", repo_url="https://github.com/x/demo",
                   framework="fastapi", status=st)

    def close(self):
        pass


def test_build_stream_immediate_completed_when_not_building(monkeypatch, client):
    Session = _engine_with_status("healthy")
    monkeypatch.setattr("app.routers.builds.SessionLocal", Session)
    with client.stream("GET", "/apps/1/builds/stream") as r:
        body = "".join(r.iter_text())
    assert "event: completed" in body
    assert '"status": "healthy"' in body


def test_build_stream_completed_after_transition(monkeypatch, client):
    # building → building → healthy: 전이 후 completed 발송
    # _FlipSession 인스턴스를 공유해야 poll마다 상태가 진행됨
    flip = _FlipSession(["building", "building", "healthy"])
    monkeypatch.setattr("app.routers.builds.SessionLocal", lambda: flip)

    async def _no_sleep(*a, **k):
        return None

    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    with client.stream("GET", "/apps/1/builds/stream") as r:
        body = "".join(r.iter_text())
    assert "event: status" in body          # building 동안 status 이벤트
    assert "event: completed" in body        # healthy 전이 시 completed
    assert '"status": "healthy"' in body
