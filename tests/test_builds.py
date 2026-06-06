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
