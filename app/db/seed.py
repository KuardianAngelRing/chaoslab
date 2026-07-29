"""목업 화면을 채우는 대표 mock 데이터. `python -m app.db.seed`로 실행."""
from sqlalchemy.orm import Session

from app.db.database import SessionLocal, init_db
from app.db.repositories import (
    AppRepository,
    BuildRepository,
    ExperimentRepository,
    IterationRepository,
)


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
    # repo_url의 "k3s://" 접두가 환경 배지 판별 마킹 (App 모델에 환경 필드 생기면 교체)
    apps.create(
        name="order-msa", repo_url="k3s://manifest-upload",
        framework="manifest", namespace="order-msa", current_sha="", status="healthy",
    )

    builds.create(app_id=boutique.id, status="succeeded", image_tag="a1b2c3d4",
                  workflow_name="build-boutique-a1b2c3d4")

    exp = exps.create(
        app_id=boutique.id, chaos_type="NetworkChaos",
        params={"action": "delay", "delay": "200ms", "duration": "5m"},
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
