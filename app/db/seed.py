"""목업 화면을 채우는 대표 mock 데이터. `python -m app.db.seed`로 실행."""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.database import SessionLocal, init_db
from app.db.repositories import (
    AppRepository,
    BuildRepository,
    ExperimentRepository,
    HandoffRepository,
    HypothesisRepository,
    IterationRepository,
)
from app.deps import make_handoff_source
from app.services.agent.assembler import assemble_handoff
from app.services.agent.hypothesis_assembler import assemble_hypothesis_input
from app.services.agent.hypothesis_validation import run_generation
from app.services.stubs import StubHypothesisAgent


_ORDER_MSA_MANIFEST = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: order-api
spec:
  replicas: 1
  selector:
    matchLabels:
      app: order-api
  template:
    metadata:
      labels:
        app: order-api
    spec:
      containers:
        - name: server
          image: registry.local/order-api:latest
          ports:
            - containerPort: 8080
---
apiVersion: v1
kind: Service
metadata:
  name: order-api
spec:
  selector:
    app: order-api
  ports:
    - port: 8080
"""


def seed_data(session: Session) -> None:
    apps = AppRepository(session)
    builds = BuildRepository(session)
    exps = ExperimentRepository(session)
    iters = IterationRepository(session)

    boutique = apps.create(
        name="online-boutique", repo_url="https://github.com/demo/boutique",
        framework="go", namespace="online-boutique",
        image_repo="123.dkr.ecr/boutique", current_sha="a1b2c3d4", status="healthy",
    )
    apps.create(
        name="payment-api", repo_url="https://github.com/demo/payment",
        framework="python", namespace="payment", current_sha="e5f6a7b8", status="healthy",
    )
    apps.create(
        name="order-worker", repo_url="https://github.com/demo/order",
        framework="node", namespace="order", current_sha="c9d0e1f2", status="degraded",
    )
    # 온프레미스(k3s) manifest 업로드형 SUT — ChaosPilot 흡수 데모용.
    # 등록=저장만(ADR-0009) — 배포는 실험 시작 시 전용 ns에.
    order_msa = apps.create(
        name="order-msa", repo_url="k3s://manifest-upload", env="k3s",
        framework="manifest", namespace="order-msa", current_sha="", status="registered",
        manifest=_ORDER_MSA_MANIFEST,
    )

    builds.create(app_id=boutique.id, status="succeeded", image_tag="a1b2c3d4",
                  workflow_name="build-boutique-a1b2c3d4")

    exp = exps.create(
        app_id=boutique.id, chaos_type="network-delay",
        params={"action": "delay", "latency_ms": 200, "duration_s": 300},
        status="running", baseline_r=0.42, r_index=0.65, target_r=0.7,
        baseline_metrics={"error": 0.3, "p99": 89},
        fault_metrics={"error": 2.1, "p99": 412},
    )
    for i, (r, verdict) in enumerate([(0.51, "improved"), (0.59, "improved"), (0.65, "improved")], start=1):
        iters.create(
            experiment_id=exp.id, iteration=i,
            observer_output=f"iter {i}: p99 상승 감지", analyst_output="타임아웃 부족 추정",
            recommender_output="timeout 1s→3s, retry 2회", r_index=r, verdict=verdict,
            llm_cost_usd=0.012,
        )

    # 실환경 smoke 완주(2026-07-28) 스토리 재현 — 실패 판정→자동 개선→재검증 통과.
    # started_at을 과거로 둬서 대시보드 '최신 실험'은 계속 running인 boutique 실험이 잡히게 한다
    exps.create(
        app_id=order_msa.id, chaos_type="pod-kill",
        params={"action": "pod-kill"},
        status="completed",
        started_at=datetime(2026, 7, 28, 12, 53, tzinfo=timezone.utc),
        finished_at=datetime(2026, 7, 28, 12, 55, tzinfo=timezone.utc),
    )

    # AI 전달 데이터 스냅샷 1건 — 팀원이 /docs에서 바로 예시 확인 (하드코딩 JSON 금지)
    payload = assemble_handoff(session, make_handoff_source(), exp)
    HandoffRepository(session).create(
        experiment_id=exp.id,
        schema_version=payload.schema_version,
        payload=payload.model_dump(),
    )

    # 가설 수립 seed — ready Run 1건 + 후보 (Stub 조립 재사용, 하드코딩 JSON 금지)
    hyp = HypothesisRepository(session)
    hyp_payload = assemble_hypothesis_input(
        session, order_msa,
        goal_text="주문 API가 파드 장애에도 60초 안에 정상화되는지 확인", candidate_count=3)
    hyp_run = hyp.create_run(
        app_id=order_msa.id, goal_text=hyp_payload.goal_text,
        candidate_count=hyp_payload.candidate_count,
        input_payload=hyp_payload.model_dump(), status="generating")
    hyp_agent = StubHypothesisAgent()
    hyp.add_candidates(hyp_run.id, run_generation(hyp_agent, hyp_payload), source="agent")
    snap = hyp_agent.snapshot()
    hyp.set_snapshot(hyp_run, snap.get("model_name", ""), snap.get("cli_version", ""))
    hyp.set_status(hyp_run, "ready", finished=True)


def main() -> None:
    init_db()
    session = SessionLocal()
    try:
        if AppRepository(session).list_all():
            print("이미 seed 됨 — 건너뜀")
            return
        seed_data(session)
        print("seed 완료")
    finally:
        session.close()


if __name__ == "__main__":
    main()
