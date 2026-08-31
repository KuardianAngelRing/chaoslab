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

def test_seeded_hypothesis_page(client):
    resp = client.get("/hypothesis/1")
    assert resp.status_code == 200
    assert "가설 수립" in resp.text
    assert "order-api" in resp.text                 # Stub 후보 대상 = manifest findings 워크로드
    assert "이 후보로 실험 시작" in resp.text


def test_create_run_for_k3s_app(client):
    resp = client.post("/hypothesis", data={
        "app_id": "4", "objective": "지연에도 응답 유지", "max_candidates": "3"})
    assert resp.status_code == 200
    assert "후보를 만들고 있어요" in resp.text        # generating 페이지
    assert resp.headers.get("hx-push-url", "").startswith("/hypothesis/")


def test_create_run_rejects_eks_app(client):
    resp = client.post("/hypothesis", data={"app_id": "1"})
    assert resp.status_code == 400


def test_select_marks_candidate_detailing(client):
    resp = client.post("/hypothesis/1/select", data={"candidate_id": "1"})
    assert resp.status_code == 200
    assert "구체화 중" in resp.text
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
