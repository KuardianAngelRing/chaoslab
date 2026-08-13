"""실험 생성/중지/워처/SSE — stub 모드(기본)."""
import logging
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db.models import App, Experiment
from app.db.repositories import AppRepository, ExperimentRepository


@pytest.fixture(autouse=True)
def _reset_sse_app_status():
    """sse_starlette의 AppStatus.should_exit_event를 테스트 간 초기화.

    TestClient가 테스트마다 새 이벤트 루프를 생성하므로, 이전 루프에서
    만들어진 anyio.Event는 재사용 시 RuntimeError(bound to different loop)를
    일으킨다. 각 테스트 전·후 None으로 리셋해 다음 루프에서 새로 생성되게 함.
    (tests/test_builds.py와 동일 패턴.)
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


def test_experiments_page_is_disconnected_workflow_demo(client):
    resp = client.get("/experiments")
    assert resp.status_code == 200
    assert "online-boutique" in resp.text
    assert "spring-boot-demo" not in resp.text
    assert "총 12건" not in resp.text
    assert 'name="chaos_type"' not in resp.text
    assert "실험 중지" not in resp.text
    assert 'hx-post="/experiments"' not in resp.text
    assert "후보 생성 요청할게요" in resp.text   # 새 실험 위저드(2-step)는 유지 — AI 후보 선택형 (ADR-0006)


def test_create_experiment_success(client):
    # seed의 online-boutique(1)에는 running 실험이 이미 있어(409 대상) → 실험 없는 앱(2)으로 검증
    resp = client.post("/experiments", data={
        "app_id": "2", "chaos_type": "NetworkChaos",
        "latency_ms": "200", "duration_s": "30",
    })
    assert resp.status_code == 200
    assert "UI 디자인 시안" in resp.text  # 기존 POST가 돌아와도 새 화면은 정적 시안만 렌더


def test_create_experiment_validation_error_422(client):
    resp = client.post("/experiments", data={
        "app_id": "1", "chaos_type": "NetworkChaos",
        "latency_ms": "5", "duration_s": "30",  # latency min 10 미만
    })
    assert resp.status_code == 422


def test_create_experiment_conflict_409_when_app_busy(client):
    # seed의 online-boutique(1)에는 running 실험이 이미 있음
    resp = client.post("/experiments", data={
        "app_id": "1", "chaos_type": "PodChaos",
    })
    assert resp.status_code == 409


def test_create_experiment_unknown_app_404(client):
    resp = client.post("/experiments", data={"app_id": "99999", "chaos_type": "PodChaos"})
    assert resp.status_code == 404


def test_stop_running_experiment(client):
    # seed 실험 1번이 running
    resp = client.post("/experiments/1/stop")
    assert resp.status_code == 200
    assert "UI 디자인 시안" in resp.text  # 상태를 화면에 주입하지 않는 정적 시안


def test_stop_non_running_409(client):
    client.post("/experiments/1/stop")            # running → stopped
    assert client.post("/experiments/1/stop").status_code == 409


def _engine_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_watch_experiment_completes_and_cleans(monkeypatch):
    from app.routers.experiments import _watch_experiment

    Session = _engine_session()
    s = Session()
    app = AppRepository(s).create(name="demo", repo_url="", framework="docker")
    exp = ExperimentRepository(s).create(
        app_id=app.id, chaos_type="PodChaos", params={"action": "pod-kill"},
        status="running", crd_name="exp-demo-abc")
    exp_id = exp.id
    s.close()

    deleted = []

    class _SpyChaos:
        def phase(self, chaos_type, crd_name):
            return "recovered"
        def delete(self, chaos_type, crd_name):
            deleted.append((chaos_type, crd_name))

    monkeypatch.setattr("app.routers.experiments.SessionLocal", Session)
    monkeypatch.setattr("app.routers.experiments.make_chaos", lambda: _SpyChaos())
    monkeypatch.setattr("app.routers.experiments.time.sleep", lambda n: None)

    _watch_experiment(exp_id)

    s = Session()
    exp = ExperimentRepository(s).get(exp_id)
    assert exp.status == "completed"
    assert exp.finished_at is not None
    # Slice 4: 완주 시 실측 3구간 + R지수가 채워져야 함 (DB 왕복 naive datetime 경로 포함)
    assert exp.baseline_metrics and exp.fault_metrics and exp.recovery_metrics
    assert exp.recovery_metrics["recovery_seconds"] is not None
    assert exp.r_index is not None
    s.close()
    assert deleted == [("PodChaos", "exp-demo-abc")]


def test_watch_experiment_failure_marks_failed(monkeypatch, caplog):
    from app.routers.experiments import _watch_experiment

    Session = _engine_session()
    s = Session()
    app = AppRepository(s).create(name="demo", repo_url="", framework="docker")
    exp = ExperimentRepository(s).create(
        app_id=app.id, chaos_type="NetworkChaos",
        params={"action": "delay", "latency_ms": 200, "duration_s": 30},
        status="running", crd_name="exp-demo-abc")
    exp_id = exp.id
    s.close()

    class _BoomChaos:
        def phase(self, chaos_type, crd_name):
            raise RuntimeError("boom")
        def delete(self, chaos_type, crd_name):
            return None

    monkeypatch.setattr("app.routers.experiments.SessionLocal", Session)
    monkeypatch.setattr("app.routers.experiments.make_chaos", lambda: _BoomChaos())
    monkeypatch.setattr("app.routers.experiments.time.sleep", lambda n: None)

    with caplog.at_level(logging.ERROR):
        _watch_experiment(exp_id)

    s = Session()
    assert ExperimentRepository(s).get(exp_id).status == "failed"
    s.close()
    assert "experiment watch failed" in caplog.text


def test_watch_skips_when_already_stopped(monkeypatch):
    """이미 stopped인 실험 → 워처가 즉시 종료하고 CRD 재삭제·완료 처리를 하지 않음."""
    from app.routers.experiments import _watch_experiment

    Session = _engine_session()
    s = Session()
    app = AppRepository(s).create(name="demo", repo_url="", framework="docker")
    exp = ExperimentRepository(s).create(
        app_id=app.id, chaos_type="PodChaos", params={"action": "pod-kill"},
        status="stopped", crd_name="exp-demo-abc")
    exp_id = exp.id
    s.close()

    class _SpyChaos:
        def __init__(self):
            self.phase_calls = 0
            self.delete_calls = 0
        def phase(self, chaos_type, crd_name):
            self.phase_calls += 1
            return "recovered"
        def delete(self, chaos_type, crd_name):
            self.delete_calls += 1

    spy = _SpyChaos()
    monkeypatch.setattr("app.routers.experiments.SessionLocal", Session)
    monkeypatch.setattr("app.routers.experiments.make_chaos", lambda: spy)
    monkeypatch.setattr("app.routers.experiments.time.sleep", lambda n: None)

    _watch_experiment(exp_id)

    assert spy.phase_calls == 0
    assert spy.delete_calls == 0  # CRD 재삭제 없음 — stop이 이미 처리함
    s = Session()
    exp = ExperimentRepository(s).get(exp_id)
    assert exp.status == "stopped"
    assert exp.finished_at is None
    s.close()


def test_watch_early_exits_when_stopped_midway(monkeypatch):
    """워처 실행 도중 stop이 처리되면(status running→stopped) 즉시 종료하고 덮어쓰지 않음."""
    from app.routers.experiments import _watch_experiment

    Session = _engine_session()
    s = Session()
    app = AppRepository(s).create(name="demo", repo_url="", framework="docker")
    exp = ExperimentRepository(s).create(
        app_id=app.id, chaos_type="NetworkChaos",
        params={"action": "delay", "latency_ms": 200, "duration_s": 30},
        status="running", crd_name="exp-demo-abc")
    exp_id = exp.id
    s.close()

    class _SpyChaos:
        def __init__(self):
            self.phase_calls = 0
            self.delete_calls = 0
        def phase(self, chaos_type, crd_name):
            self.phase_calls += 1
            return "recovered"
        def delete(self, chaos_type, crd_name):
            self.delete_calls += 1

    spy = _SpyChaos()
    sleep_calls = []

    def _fake_sleep(n):
        sleep_calls.append(n)
        if len(sleep_calls) == 1:
            # 첫 폴링 직후 stop 라우트가 처리한 것처럼 DB 상태를 바꿈
            stop_s = Session()
            stopped_exp = ExperimentRepository(stop_s).get(exp_id)
            stopped_exp.status = "stopped"
            stopped_exp.finished_at = datetime.now(timezone.utc)
            stop_s.commit()
            stop_s.close()

    monkeypatch.setattr("app.routers.experiments.SessionLocal", Session)
    monkeypatch.setattr("app.routers.experiments.make_chaos", lambda: spy)
    monkeypatch.setattr("app.routers.experiments.time.sleep", _fake_sleep)

    _watch_experiment(exp_id)

    assert sleep_calls  # 최소 한 번은 폴링했음
    assert spy.phase_calls == 0  # 회복 폴링 루프까지 도달하지 않음
    assert spy.delete_calls == 0  # CRD 재삭제 없음 — stop이 이미 처리함
    s = Session()
    exp = ExperimentRepository(s).get(exp_id)
    assert exp.status == "stopped"
    s.close()


def _engine_with_experiment(status: str):
    """단일 App+Experiment(id=1, 주어진 status)를 가진 격리 엔진의 세션메이커.

    tests/test_builds.py의 _engine_with_status와 동일 패턴 — SSE 라우트가
    쓰는 SessionLocal은 client 픽스처의 override와 분리된 DB를 보므로,
    라우트가 실제로 조회할 엔진에 직접 시드한다.
    """
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = Session()
    app = App(name="demo", repo_url="https://github.com/x/demo", framework="docker")
    s.add(app)
    s.commit()
    s.add(Experiment(app_id=app.id, chaos_type="PodChaos", status=status))
    s.commit()
    s.close()
    return Session


def test_experiment_stream_completed_immediately(monkeypatch, client):
    # 격리 엔진에 stopped 실험(id=1)을 시드하고 스트림 접속 → 즉시 completed 이벤트
    Session = _engine_with_experiment("stopped")
    monkeypatch.setattr("app.routers.experiments.SessionLocal", Session)
    with client.stream("GET", "/experiments/1/stream") as r:
        body = "".join(chunk for chunk in r.iter_text())
    assert "event: completed" in body
    assert '"status": "stopped"' in body
