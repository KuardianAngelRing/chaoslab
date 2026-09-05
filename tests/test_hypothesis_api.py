"""가설 수립 라우터 + 워처 — hermetic (conftest가 Stub 강제)."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db.repositories import AppRepository, ExperimentRepository, HypothesisRepository
from app.services.agent.hypothesis_assembler import assemble_hypothesis_input

_K3S_MANIFEST = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: demo-api
spec:
  replicas: 1
  selector:
    matchLabels:
      app: demo-api
  template:
    metadata:
      labels:
        app: demo-api
    spec:
      containers:
        - name: server
          image: demo:latest
"""


# ── 라우트 (client fixture — seed: order-msa=app 4, run 1 ready + 후보 3) ──

def test_seeded_hypothesis_page_renders_workflow_shell(client):
    resp = client.get("/hypothesis/1")
    assert resp.status_code == 200
    for stage in ("후보 선택", "순차 실행·개선", "최종 회귀 검증", "결과"):
        assert stage in resp.text
    assert "HYP-1" in resp.text
    assert 'data-initial-stage="plan"' in resp.text
    assert 'data-workflow-select-mode="single"' in resp.text
    assert 'type="radio" name="candidate_id"' in resp.text
    assert "order-api" in resp.text                 # Stub 후보 대상 = manifest findings 워크로드
    assert "선택한 후보로 실험 시작" in resp.text
    assert 'hx-post="/hypothesis/1/select"' in resp.text
    assert 'hx-post="/hypothesis/1/freeform"' in resp.text
    # 하드코딩 시안 잔재 없음 — 사전 점검 "3/3 통과"·SAMPLE·데모 후보
    for stale in ("사전 점검 3/3 통과", "SAMPLE", "Frontend Pod 1개 손실", "data-candidate-execution"):
        assert stale not in resp.text
    assert "manifest 정적 분석" in resp.text     # 배너는 조립 근거만 말한다


def test_view_beyond_current_stage_clamps_to_plan(client):
    resp = client.get("/hypothesis/1?view=execute")   # 실험 없음 → 2단계 미개방
    assert 'data-initial-stage="plan"' in resp.text
    resp = client.get("/hypothesis/1?view=result")
    assert 'data-initial-stage="plan"' in resp.text


def test_create_run_for_k3s_app(client):
    resp = client.post("/hypothesis", data={
        "app_id": "4", "objective": "지연에도 응답 유지", "max_candidates": "3"})
    assert resp.status_code == 200
    assert "후보를 만들고 있어요" in resp.text        # generating 페이지
    assert resp.headers.get("hx-push-url", "").endswith("?view=plan")
    assert 'data-hypothesis-active="1"' in resp.text  # 생성 중 → SSE 구독 훅


def test_create_run_rejects_eks_app(client):
    resp = client.post("/hypothesis", data={"app_id": "1"})
    assert resp.status_code == 400


def test_select_marks_candidate_detailing(client):
    resp = client.post("/hypothesis/1/select", data={"candidate_id": "1"})
    assert resp.status_code == 200
    assert "구체화 중" in resp.text
    assert 'hx-post="/hypothesis/1/select"' not in resp.text   # detailing 중엔 재선택 CTA 없음
    assert 'data-hypothesis-active="1"' in resp.text
    # 같은 후보 재선택은 409 (이미 detailing)
    resp = client.post("/hypothesis/1/select", data={"candidate_id": "1"})
    assert resp.status_code == 409


def test_freeform_flow(client):
    resp = client.post("/hypothesis/1/freeform", data={"user_text": ""})
    assert resp.status_code == 422
    resp = client.post("/hypothesis/1/freeform", data={"user_text": "메모리 압박도 확인"})
    assert resp.status_code == 200
    assert "구체화하고 있어요" in resp.text
    # 생성 중 재요청은 409
    resp = client.post("/hypothesis/1/freeform", data={"user_text": "또 하나"})
    assert resp.status_code == 409


def test_unknown_run_404(client):
    assert client.get("/hypothesis/999").status_code == 404


# ── 워처 (experiments 워처 테스트 패턴 미러 — SessionLocal 몽키패치) ──

def _engine_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _make_run(Session, status="generating"):
    s = Session()
    app = AppRepository(s).create(name="demo", repo_url="k3s://manifest-upload",
                                  env="k3s", framework="manifest",
                                  manifest=_K3S_MANIFEST, status="registered")
    payload = assemble_hypothesis_input(s, app, "목표 텍스트", 3)
    run = HypothesisRepository(s).create_run(
        app_id=app.id, goal_text=payload.goal_text, candidate_count=3,
        input_payload=payload.model_dump(), status=status)
    run_id = run.id
    s.close()
    return run_id


def test_watch_generation_ready(monkeypatch):
    from app.routers.hypothesis import _watch_generation

    Session = _engine_session()
    run_id = _make_run(Session)
    monkeypatch.setattr("app.routers.hypothesis.SessionLocal", Session)

    _watch_generation(run_id)

    s = Session()
    repo = HypothesisRepository(s)
    run = repo.get_run(run_id)
    assert run.status == "ready"
    assert run.finished_at is not None
    assert run.model_name == "stub" and run.cli_version == "stub"
    candidates = repo.list_candidates(run_id)
    assert len(candidates) == 3
    assert all(c.detail_status == "proposed" and c.params is None for c in candidates)
    s.close()


def test_watch_generation_failure_marks_failed(monkeypatch):
    from app.routers.hypothesis import _watch_generation

    class _Boom:
        def generate(self, payload, feedback=""):
            raise RuntimeError("CLI 죽음")

    Session = _engine_session()
    run_id = _make_run(Session)
    monkeypatch.setattr("app.routers.hypothesis.SessionLocal", Session)
    monkeypatch.setattr("app.routers.hypothesis.make_hypothesis_agent", lambda: _Boom())

    _watch_generation(run_id)

    s = Session()
    run = HypothesisRepository(s).get_run(run_id)
    assert run.status == "failed" and "CLI 죽음" in run.error
    s.close()


def _prep_detailing(Session, chaos_type="pod-kill"):
    from app.services.agent.hypothesis_schema import CandidateProposal

    run_id = _make_run(Session, status="ready")
    s = Session()
    repo = HypothesisRepository(s)
    [cand] = repo.add_candidates(run_id, [CandidateProposal(
        title="파드 강제 종료 검증", chaos_type=chaos_type, target_workload="demo-api",
        hypothesis="파드가 강제 종료되면 요청이 실패할 것이다",
        expected_impact="오류율이 잠시 상승할 것으로 예상돼요")])
    repo.set_candidate_detail(cand, "detailing")
    cand_id = cand.id
    s.close()
    return run_id, cand_id


def test_watch_detailing_creates_experiment(monkeypatch):
    from app.routers.hypothesis import _watch_detailing
    from app.services.stubs import StubChaos, StubK3sWorkload

    Session = _engine_session()
    run_id, cand_id = _prep_detailing(Session)
    monkeypatch.setattr("app.routers.hypothesis.SessionLocal", Session)
    monkeypatch.setattr("app.routers.experiments.SessionLocal", Session)
    monkeypatch.setattr("app.routers.experiments.make_chaos", lambda *a, **k: StubChaos())
    monkeypatch.setattr("app.routers.experiments.make_k3s_workload", lambda: StubK3sWorkload())
    monkeypatch.setattr("app.routers.experiments.time.sleep", lambda n: None)

    _watch_detailing(cand_id)

    s = Session()
    repo = HypothesisRepository(s)
    cand = repo.get_candidate(cand_id)
    assert cand.detail_status == "detailed"
    assert cand.params == {"action": "pod-kill"}    # Stub detail + validate_params 정규화
    exp = repo.experiment_for_run(run_id)
    assert exp is not None and exp.candidate_id == cand_id
    assert exp.status == "completed"                # k3s 현장 배포 → 주입 → 회복 → 정리
    s.close()


def test_run_with_experiment_lands_on_execute_stage(monkeypatch, client):
    """실험이 생기면 실험 카드(파라미터·근거) 렌더, SSE는 execute로 redirect.
    실험이 종료(Stub은 즉시 completed)되면 3단계(최종 회귀)가 열리고 기본 view도 verify.

    experiments의 stream 테스트 패턴 미러 — client fixture(lifespan) + SessionLocal 몽키패치,
    페이지 렌더는 dependency_overrides를 격리 엔진으로 덮어씀(fixture가 정리)."""
    from app.db.database import get_session
    from app.main import app as fastapi_app
    from app.routers.hypothesis import _watch_detailing
    from app.services.stubs import StubChaos, StubK3sWorkload

    Session = _engine_session()
    run_id, cand_id = _prep_detailing(Session)
    monkeypatch.setattr("app.routers.hypothesis.SessionLocal", Session)
    monkeypatch.setattr("app.routers.experiments.SessionLocal", Session)
    monkeypatch.setattr("app.routers.experiments.make_chaos", lambda *a, **k: StubChaos())
    monkeypatch.setattr("app.routers.experiments.make_k3s_workload", lambda: StubK3sWorkload())
    monkeypatch.setattr("app.routers.experiments.time.sleep", lambda n: None)
    _watch_detailing(cand_id)

    def _override():
        s = Session()
        try:
            yield s
        finally:
            s.close()
    fastapi_app.dependency_overrides[get_session] = _override

    resp = client.get(f"/hypothesis/{run_id}?view=execute")
    assert resp.status_code == 200
    assert 'data-initial-stage="execute"' in resp.text
    assert "파드 강제 종료 검증" in resp.text and "실험 완료" in resp.text
    assert "구체화된 파라미터" in resp.text
    assert 'hx-post="/hypothesis/' not in resp.text   # 실험 이후 선택·직접 입력 CTA 없음
    assert 'data-workflow-go="verify"' in resp.text and "최종 회귀로" in resp.text
    assert 'data-workflow-current-stage="3"' in resp.text
    assert 'data-workflow-app-id=' in resp.text and 'data-workflow-app-env="k3s"' in resp.text
    # 실험 종료 → 기본 view=verify(3단계) — 승인 후보 목록·기본 기준·시작 버튼은 서버 렌더
    resp = client.get(f"/hypothesis/{run_id}")
    assert 'data-initial-stage="verify"' in resp.text
    assert "data-hypothesis-regression-start" in resp.text and "최종 회귀 시작" in resp.text
    assert "파드 강제 종료 검증" in resp.text and "demo-api" in resp.text
    assert "최소 Ready Pod" in resp.text
    assert "data-preparation-panel" in resp.text
    assert "준비 중" not in resp.text                     # 3·4단계 "준비 중" 툴팁 제거
    resp = client.get(f"/hypothesis/{run_id}?view=result")   # 회귀 전 → verify로 클램프
    assert 'data-initial-stage="verify"' in resp.text
    with client.stream("GET", f"/hypothesis/{run_id}/stream") as r:
        body = "".join(chunk for chunk in r.iter_text())
    # completed 이벤트의 data JSON을 실제로 파싱 — 문자열 포함 검사보다 형식 변경에 민감
    import json
    events, name = [], ""
    for line in body.splitlines():   # sse-starlette는 \r\n 구분 — 줄 단위로 event/data 쌍을 모은다
        if line.startswith("event:"):
            name = line[len("event:"):].strip()
        elif line.startswith("data:"):
            events.append((name, json.loads(line[len("data:"):])))
    assert [n for n, _ in events] == ["status", "completed"]
    assert events[0][1]["experiment_id"] == 1 and events[0][1]["details"] == {"1": "detailed"}
    assert events[1][1] == {"redirect": f"/hypothesis/{run_id}?view=execute"}

    # 후보 다시 보기(plan): 승인 후보만 checked+disabled, CTA 대신 "실험 보기", 직접 입력 폼 없음
    resp = client.get(f"/hypothesis/{run_id}?view=plan")
    assert 'data-initial-stage="plan"' in resp.text
    assert "승인됨" in resp.text and "실험 보기" in resp.text
    assert "승인한 후보로 실험이 시작됐어요" in resp.text
    assert 'data-workflow-selection-next' not in resp.text
    assert "후보로 추가" not in resp.text
    assert f'data-workflow-run-id="{run_id}"' in resp.text


def test_watch_detailing_validation_failure(monkeypatch):
    from app.routers.hypothesis import _watch_detailing

    class _BadDetail:
        def detail(self, payload, candidate, feedback=""):
            return {"params": {"latency_ms": "1", "duration_s": "60"}}  # 항상 범위 이탈

    Session = _engine_session()
    run_id, cand_id = _prep_detailing(Session, chaos_type="network-delay")
    monkeypatch.setattr("app.routers.hypothesis.SessionLocal", Session)
    monkeypatch.setattr("app.routers.hypothesis.make_hypothesis_agent", lambda: _BadDetail())

    _watch_detailing(cand_id)

    s = Session()
    repo = HypothesisRepository(s)
    cand = repo.get_candidate(cand_id)
    assert cand.detail_status == "failed" and cand.error
    assert repo.experiment_for_run(run_id) is None
    s.close()
