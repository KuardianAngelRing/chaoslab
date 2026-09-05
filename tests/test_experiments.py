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
        "app_id": "2", "chaos_type": "network-delay",
        "latency_ms": "200", "duration_s": "30",
    })
    assert resp.status_code == 200
    assert "HYP-1" in resp.text  # 기존 POST가 돌아와도 목록은 가설 Run 행(서버 렌더)


def test_create_experiment_validation_error_422(client):
    resp = client.post("/experiments", data={
        "app_id": "1", "chaos_type": "network-delay",
        "latency_ms": "5", "duration_s": "30",  # latency min 10 미만
    })
    assert resp.status_code == 422


def test_create_experiment_conflict_409_when_app_busy(client):
    # seed의 online-boutique(1)에는 running 실험이 이미 있음
    resp = client.post("/experiments", data={
        "app_id": "1", "chaos_type": "pod-kill",
    })
    assert resp.status_code == 409


def test_create_experiment_unknown_app_404(client):
    resp = client.post("/experiments", data={"app_id": "99999", "chaos_type": "pod-kill"})
    assert resp.status_code == 404


def test_stop_running_experiment(client):
    # seed 실험 1번이 running
    resp = client.post("/experiments/1/stop")
    assert resp.status_code == 200
    assert "HYP-1" in resp.text  # 목록 = 가설 Run 행 (개별 Experiment 행은 백로그)


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
        app_id=app.id, chaos_type="pod-kill", params={"action": "pod-kill"},
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
    monkeypatch.setattr("app.routers.experiments.make_chaos", lambda *a, **k: _SpyChaos())
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
    assert deleted == [("pod-kill", "exp-demo-abc")]


def test_watch_experiment_failure_marks_failed(monkeypatch, caplog):
    from app.routers.experiments import _watch_experiment

    Session = _engine_session()
    s = Session()
    app = AppRepository(s).create(name="demo", repo_url="", framework="docker")
    exp = ExperimentRepository(s).create(
        app_id=app.id, chaos_type="network-delay",
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
    monkeypatch.setattr("app.routers.experiments.make_chaos", lambda *a, **k: _BoomChaos())
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
        app_id=app.id, chaos_type="pod-kill", params={"action": "pod-kill"},
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
    monkeypatch.setattr("app.routers.experiments.make_chaos", lambda *a, **k: spy)
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
        app_id=app.id, chaos_type="network-delay",
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
    monkeypatch.setattr("app.routers.experiments.make_chaos", lambda *a, **k: spy)
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
    s.add(Experiment(app_id=app.id, chaos_type="pod-kill", status=status))
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


def _sse_events(text: str) -> list[tuple[str, dict]]:
    """SSE 본문 → [(event, data dict)] — 빈 줄로 구분된 블록 파싱."""
    import json

    out = []
    for block in text.replace("\r\n", "\n").strip().split("\n\n"):
        ev, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if ev:
            out.append((ev, data))
    return out


_LIVE_KEYS = {"ts", "rps", "error_rate_pct", "p95_ms", "p99_ms", "ready_pods", "status"}


def test_metrics_stream_completed_immediately_when_not_active(monkeypatch, client):
    Session = _engine_with_experiment("completed")
    monkeypatch.setattr("app.routers.experiments.SessionLocal", Session)
    with client.stream("GET", "/experiments/1/metrics/stream") as r:
        events = _sse_events("".join(r.iter_text()))
    assert events == [("completed", {"status": "completed"})]


def _flip_status_on_nth_session(Session, n: int, status: str):
    """TestClient는 스트림 본문을 응답 종료까지 모아서 돌려주므로 중간에 DB를 바꿀 수 없다 —
    라우트가 n번째로 SessionLocal()을 열기 직전에 실험 status를 바꿔 종료를 유도한다."""
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        if calls["n"] == n:
            s = Session()
            s.get(Experiment, 1).status = status
            s.commit()
            s.close()
        return Session()

    return factory


def test_metrics_stream_emits_metric_then_completed(monkeypatch, client):
    # running → 첫 이벤트는 계약 키를 가진 metric(Stub 즉시값), 완료로 바뀌면 completed로 종료
    Session = _engine_with_experiment("running")
    monkeypatch.setattr("app.routers.experiments.SessionLocal",
                        _flip_status_on_nth_session(Session, 3, "completed"))
    monkeypatch.setattr("app.routers.experiments._LIVE_INTERVAL_S", 0)
    with client.stream("GET", "/experiments/1/metrics/stream") as r:
        events = _sse_events("".join(r.iter_text()))
    assert [ev for ev, _ in events] == ["metric", "metric", "completed"]
    data = events[0][1]
    assert set(data) == _LIVE_KEYS
    assert data["status"] == "running"
    assert isinstance(data["rps"], float) and isinstance(data["ready_pods"], int)
    assert events[-1][1] == {"status": "completed"}


def test_metrics_stream_pending_sends_none_values(monkeypatch, client):
    # k3s 배포 전(pending)이면 값 None인 metric 틱 — 스트림은 유지되고 Prometheus는 조회하지 않는다
    Session = _engine_with_experiment("pending")
    monkeypatch.setattr("app.routers.experiments.SessionLocal",
                        _flip_status_on_nth_session(Session, 2, "stopped"))
    monkeypatch.setattr("app.routers.experiments._LIVE_INTERVAL_S", 0)

    def _boom(*a, **k):
        raise AssertionError("pending 상태에서는 live_snapshot을 호출하지 않는다")

    monkeypatch.setattr("app.services.stubs.StubPrometheus.live_snapshot", _boom)
    with client.stream("GET", "/experiments/1/metrics/stream") as r:
        events = _sse_events("".join(r.iter_text()))
    assert [ev for ev, _ in events] == ["metric", "completed"]
    data = events[0][1]
    assert data["status"] == "pending"
    assert all(data[k] is None for k in ("rps", "error_rate_pct", "p95_ms", "p99_ms", "ready_pods"))


def test_watch_k3s_experiment_deploys_injects_and_tears_down(monkeypatch):
    """ADR-0009: k3s 워처는 배포→ready→주입→관측→CRD 삭제→ns 삭제 순서로 전체 수행."""
    from app.routers.experiments import _watch_experiment

    Session = _engine_session()
    s = Session()
    app = AppRepository(s).create(
        name="msa", repo_url="k3s://manifest-upload", framework="manifest",
        env="k3s", manifest="kind: Deployment")
    exp = ExperimentRepository(s).create(
        app_id=app.id, chaos_type="pod-kill", params={"action": "pod-kill"},
        status="deploying", namespace="chaoslab-msa-1")
    exp_id = exp.id
    s.close()

    calls = []

    class _SpyWorkload:
        def deploy(self, ns, manifest):
            calls.append(("deploy", ns, manifest))
        def wait_ready(self, ns, timeout_s=180):
            calls.append(("ready", ns))
            return True
        def teardown(self, ns):
            calls.append(("teardown", ns))

    class _SpyChaos:
        def inject(self, ns, app_name, chaos_type, params):
            calls.append(("inject", ns))
            return "exp-msa-xyz"
        def phase(self, chaos_type, crd_name):
            return "recovered"
        def delete(self, chaos_type, crd_name):
            calls.append(("delete-crd", crd_name))

    monkeypatch.setattr("app.routers.experiments.SessionLocal", Session)
    monkeypatch.setattr("app.routers.experiments.make_chaos", lambda *a, **k: _SpyChaos())
    monkeypatch.setattr("app.routers.experiments.make_k3s_workload", lambda: _SpyWorkload())
    monkeypatch.setattr("app.routers.experiments.time.sleep", lambda n: None)

    _watch_experiment(exp_id)

    s = Session()
    exp = ExperimentRepository(s).get(exp_id)
    assert exp.status == "completed"
    assert exp.crd_name == "exp-msa-xyz"
    s.close()
    kinds = [c[0] for c in calls]
    assert kinds == ["deploy", "ready", "inject", "delete-crd", "teardown"]
    assert calls[0][1] == "chaoslab-msa-1" and calls[0][2] == "kind: Deployment"


def test_watch_k3s_deploy_failure_marks_failed_and_tears_down(monkeypatch, caplog):
    from app.routers.experiments import _watch_experiment

    Session = _engine_session()
    s = Session()
    app = AppRepository(s).create(
        name="msa", repo_url="k3s://manifest-upload", framework="manifest",
        env="k3s", manifest="")
    exp = ExperimentRepository(s).create(
        app_id=app.id, chaos_type="pod-kill", params={"action": "pod-kill"},
        status="deploying", namespace="chaoslab-msa-1")
    exp_id = exp.id
    s.close()

    torn = []

    class _BoomWorkload:
        def deploy(self, ns, manifest):
            raise ValueError("manifest 비어 있음")
        def wait_ready(self, ns, timeout_s=180):
            return True
        def teardown(self, ns):
            torn.append(ns)

    monkeypatch.setattr("app.routers.experiments.SessionLocal", Session)
    monkeypatch.setattr("app.routers.experiments.make_chaos", lambda *a, **k: object())
    monkeypatch.setattr("app.routers.experiments.make_k3s_workload", lambda: _BoomWorkload())
    monkeypatch.setattr("app.routers.experiments.time.sleep", lambda n: None)

    with caplog.at_level(logging.ERROR):
        _watch_experiment(exp_id)

    s = Session()
    assert ExperimentRepository(s).get(exp_id).status == "failed"
    s.close()
    assert torn == ["chaoslab-msa-1"]  # 실패해도 ns 정리


def test_watch_marks_failed_when_never_recovered(monkeypatch):
    """회복 상한까지 recovered가 안 오면(주입 실패 등) completed가 아니라 failed."""
    from app.routers.experiments import _watch_experiment

    Session = _engine_session()
    s = Session()
    app = AppRepository(s).create(name="demo", repo_url="", framework="docker")
    exp = ExperimentRepository(s).create(
        app_id=app.id, chaos_type="network-delay",
        params={"action": "delay", "latency_ms": 100, "duration_s": 30},
        status="running", crd_name="exp-demo-stuck")
    exp_id = exp.id
    s.close()

    deleted = []

    class _StuckChaos:
        def phase(self, chaos_type, crd_name):
            return "injecting"  # 영원히 회복 안 됨
        def delete(self, chaos_type, crd_name):
            deleted.append(crd_name)

    monkeypatch.setattr("app.routers.experiments.SessionLocal", Session)
    monkeypatch.setattr("app.routers.experiments.make_chaos", lambda *a, **k: _StuckChaos())
    monkeypatch.setattr("app.routers.experiments.time.sleep", lambda n: None)

    _watch_experiment(exp_id)

    s = Session()
    assert ExperimentRepository(s).get(exp_id).status == "failed"
    s.close()
    assert deleted == ["exp-demo-stuck"]  # CRD 정리는 여전히 수행
