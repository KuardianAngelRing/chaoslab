"""개선 단계 라우터·워처·SSE (설계 2026-09-05 §6·§7) — hermetic (conftest가 Stub 강제)."""
import json

from app.db.repositories import HypothesisRepository, ScenarioRunRepository
from app.services.stubs import StubChaos, StubK3sWorkload
from tests.test_hypothesis_api import _engine_session, _prep_detailing


def _run_experiment(monkeypatch, Session):
    """후보 detailing → Stub 실험 completed까지 (개선안 생성 전제)."""
    from app.routers.hypothesis import _watch_detailing

    run_id, cand_id = _prep_detailing(Session)
    monkeypatch.setattr("app.routers.hypothesis.SessionLocal", Session)
    monkeypatch.setattr("app.routers.experiments.SessionLocal", Session)
    monkeypatch.setattr("app.routers.experiments.make_chaos", lambda *a, **k: StubChaos())
    monkeypatch.setattr("app.routers.experiments.make_k3s_workload", lambda: StubK3sWorkload())
    monkeypatch.setattr("app.routers.experiments.time.sleep", lambda n: None)
    _watch_detailing(cand_id)
    return run_id


def _override_session(client, Session):
    from app.db.database import get_session
    from app.main import app as fastapi_app

    def _override():
        s = Session()
        try:
            yield s
        finally:
            s.close()
    fastapi_app.dependency_overrides[get_session] = _override


def _sse_events(client, run_id):
    with client.stream("GET", f"/hypothesis/{run_id}/stream") as r:
        body = "".join(chunk for chunk in r.iter_text())
    events, name = [], ""
    for line in body.splitlines():
        if line.startswith("event:"):
            name = line[len("event:"):].strip()
        elif line.startswith("data:"):
            events.append((name, json.loads(line[len("data:"):])))
    return events


def test_propose_requires_terminal_experiment(monkeypatch, client):
    Session = _engine_session()
    run_id, _ = _prep_detailing(Session)      # 실험 없음
    _override_session(client, Session)
    resp = client.post(f"/hypothesis/{run_id}/improvements")
    assert resp.status_code == 409
    assert client.post("/hypothesis/999/improvements").status_code == 404


def test_watch_improvements_ready_then_approve_and_edit(monkeypatch, client):
    """생성 트리거 → 워처(Stub 2안) → 카드 렌더(전/후 미리보기) → 편집 승인 → 배지·회귀 시작 버튼."""
    from app.routers.hypothesis import _watch_improvements

    Session = _engine_session()
    run_id = _run_experiment(monkeypatch, Session)
    _override_session(client, Session)

    # 3단계 기본 view — 생성 전 패널 + 회귀 시작 가능(개선 없이)
    resp = client.get(f"/hypothesis/{run_id}")
    assert 'data-initial-stage="verify"' in resp.text
    assert "AI 개선안 제안" in resp.text and f'hx-post="/hypothesis/{run_id}/improvements"' in resp.text
    assert "data-hypothesis-regression-start disabled" not in resp.text

    resp = client.post(f"/hypothesis/{run_id}/improvements")   # BackgroundTasks → 워처 동기 실행(Stub)
    assert resp.status_code == 200
    s = Session()
    repo = HypothesisRepository(s)
    run = repo.get_run(run_id)
    assert run.improvement_status == "ready"
    proposals = repo.list_proposals(run_id)
    assert [p.title for p in proposals] == [
        "demo-api 파드 개수 1 → 3으로 증설", "readinessProbe 추가", "종료 전 유예(preStop sleep)"]
    assert all(p.status == "proposed" and p.experiment_id is not None for p in proposals)
    replicas_id, probe_id, prestop_id = [p.id for p in proposals]
    s.close()

    resp = client.get(f"/hypothesis/{run_id}?view=verify")
    assert "AI 개선안 3개" in resp.text and "결정 필요" in resp.text
    assert "spec.replicas" in resp.text                                 # replicas 1 → 3 미리보기
    assert "containers[server].readinessProbe.tcpSocket" in resp.text   # manifest에 probe 없음 → 추가 제안
    assert 'name="proposal_ids"' in resp.text and f'name="patch_{probe_id}"' in resp.text
    assert "data-hypothesis-regression-start disabled" in resp.text      # 미결 → 회귀 시작 잠금
    assert "개선안을 승인하거나 제외해 주세요" in resp.text
    assert "data-hypothesis-active" not in resp.text                     # ready면 SSE 구독 없음

    # 편집 검증 실패 → 저장 안 됨, 카드에 오류
    bad = json.dumps({"spec": {"template": {"spec": {"containers": [{"name": "server", "image": "x"}]}}}})
    resp = client.post(f"/hypothesis/{run_id}/improvements/approve",
                       data={"proposal_ids": [str(probe_id)], f"patch_{probe_id}": bad})
    assert resp.status_code == 200 and "편집 값 검증 실패" in resp.text
    s = Session()
    assert all(p.status == "proposed" for p in HypothesisRepository(s).list_proposals(run_id))
    s.close()

    # 편집(periodSeconds 2→1) + 1개 승인 → approved(user_edit)·rejected
    edited = {"spec": {"template": {"spec": {"containers": [{"name": "server",
              "readinessProbe": {"tcpSocket": {"port": 8080}, "periodSeconds": 1, "failureThreshold": 2}}]}}}}
    resp = client.post(f"/hypothesis/{run_id}/improvements/approve",
                       data={"proposal_ids": [str(probe_id)], f"patch_{probe_id}": json.dumps(edited)})
    assert resp.status_code == 200
    assert "승인됨" in resp.text and "제외됨" in resp.text and "편집됨" in resp.text
    assert "승인 1건 · 제외 2건" in resp.text
    assert "승인한 개선 1건" in resp.text
    assert "data-hypothesis-regression-start disabled" not in resp.text  # 결정 완료 → 시작 가능
    s = Session()
    by_id = {p.id: p for p in HypothesisRepository(s).list_proposals(run_id)}
    assert by_id[probe_id].status == "approved" and by_id[probe_id].source == "user_edit"
    assert by_id[probe_id].patch == edited
    assert by_id[prestop_id].status == "rejected" and by_id[replicas_id].status == "rejected"
    s.close()

    # 다시 결정 → 전부 proposed(편집값 유지)
    resp = client.post(f"/hypothesis/{run_id}/improvements/reopen")
    assert resp.status_code == 200 and "결정 필요" in resp.text
    s = Session()
    by_id = {p.id: p for p in HypothesisRepository(s).list_proposals(run_id)}
    assert all(p.status == "proposed" for p in by_id.values()) and by_id[probe_id].patch == edited
    s.close()

    # 개선 없이 진행 → 전부 rejected
    resp = client.post(f"/hypothesis/{run_id}/improvements/approve", data={"none": "1"})
    assert "개선 없이 진행 — baseline·final이 같은 조건" in resp.text
    s = Session()
    assert all(p.status == "rejected" for p in HypothesisRepository(s).list_proposals(run_id))
    s.close()


def test_watch_improvements_failure_and_sse_redirect(monkeypatch, client):
    from app.routers.hypothesis import _watch_improvements

    Session = _engine_session()
    run_id = _run_experiment(monkeypatch, Session)
    _override_session(client, Session)

    class _Broken:
        def propose_improvements(self, payload, feedback=""):
            return [{"title": "x"}]           # 검증 전멸 → 재시도 후 예외
        def snapshot(self):
            return {}
    monkeypatch.setattr("app.routers.hypothesis.make_hypothesis_agent", lambda: _Broken())

    s = Session()
    repo = HypothesisRepository(s)
    repo.set_improvement(repo.get_run(run_id), "generating")
    s.close()
    # generating 동안 페이지는 SSE 구독 + 스피너, 회귀 시작 잠금
    resp = client.get(f"/hypothesis/{run_id}?view=verify")
    assert "data-hypothesis-active" in resp.text and "AI가 개선안을 만들고 있어요" in resp.text
    assert "data-hypothesis-regression-start disabled" in resp.text

    _watch_improvements(run_id)
    s = Session()
    run = HypothesisRepository(s).get_run(run_id)
    assert run.improvement_status == "failed" and "개선 제안 전멸" in run.improvement_error
    s.close()
    resp = client.get(f"/hypothesis/{run_id}?view=verify")
    assert "개선안 생성 실패" in resp.text and "다시 생성" in resp.text

    events = _sse_events(client, run_id)
    assert [n for n, _ in events] == ["status", "completed"]
    assert events[0][1]["improvements"] == "failed"
    assert events[1][1] == {"redirect": f"/hypothesis/{run_id}?view=verify"}


def test_improvements_locked_after_scenario_run(monkeypatch, client):
    Session = _engine_session()
    run_id = _run_experiment(monkeypatch, Session)
    _override_session(client, Session)
    s = Session()
    run = HypothesisRepository(s).get_run(run_id)
    from app.db.models import ExperimentSession
    prep = ExperimentSession(app_id=run.app_id, status="ready", namespace="ns")
    s.add(prep)
    s.commit()
    ScenarioRunRepository(s).create(app_id=run.app_id, preparation_session_id=prep.id,
                                    hypothesis_run_id=run_id, status="running", scenario={})
    HypothesisRepository(s).set_improvement(run, "ready")
    s.close()
    assert client.post(f"/hypothesis/{run_id}/improvements").status_code == 409
    assert client.post(f"/hypothesis/{run_id}/improvements/approve", data={"none": "1"}).status_code == 409
    assert client.post(f"/hypothesis/{run_id}/improvements/reopen").status_code == 409
