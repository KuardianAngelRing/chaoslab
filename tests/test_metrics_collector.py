"""수집기 — Stub Prometheus로 3구간 저장 + R지수 기록, 실패 격리."""
from datetime import datetime, timedelta, timezone

from app.db.repositories import ExperimentRepository
from app.db.seed import seed_data
from app.services.agent.handoff_schema import PhaseSummary
from app.services.metrics_collector import collect_experiment_metrics
from app.services.stubs import StubPrometheus


def _completed_exp(db_session, duration_s=60):
    seed_data(db_session)
    start = datetime(2026, 8, 13, 3, 0, tzinfo=timezone.utc)
    return ExperimentRepository(db_session).create(
        app_id=1, chaos_type="NetworkChaos",
        params={"action": "delay", "latency_ms": 200, "duration_s": duration_s},
        status="completed", started_at=start,
        finished_at=start + timedelta(seconds=duration_s + 41),
    )


def test_collect_stores_contract_metrics_and_r(db_session):
    exp = _completed_exp(db_session)
    collect_experiment_metrics(db_session, exp, StubPrometheus())

    for stored in (exp.baseline_metrics, exp.fault_metrics, exp.recovery_metrics):
        PhaseSummary(**stored)  # 계약 형태로 저장됐는가
    assert exp.recovery_metrics["recovery_seconds"] == 41.0  # finished - (start+duration)
    assert exp.r_index is not None and 0.0 <= exp.r_index <= 1.0


def test_collect_failure_is_isolated(db_session, caplog):
    exp = _completed_exp(db_session)

    class Broken:
        def phase_summary(self, *a, **k):
            raise RuntimeError("prometheus down")

    collect_experiment_metrics(db_session, exp, Broken())
    assert exp.status == "completed"       # 실험 상태 불변
    assert exp.r_index is None
    assert "실측 지표 수집 실패" in caplog.text


def test_collect_queries_experiment_namespace_when_set(db_session):
    """k3s(ADR-0009)는 실험 전용 ns에서 관측 — 앱 ns가 아니라 exp.namespace로 조회해야 한다."""
    exp = _completed_exp(db_session)
    exp.namespace = "chaoslab-demo-9"
    db_session.commit()
    seen = []

    class Recording(StubPrometheus):
        def phase_summary(self, namespace, app_name, phase, start, end):
            seen.append(namespace)
            return super().phase_summary(namespace, app_name, phase, start, end)

    collect_experiment_metrics(db_session, exp, Recording())
    assert seen == ["chaoslab-demo-9"] * 3

    exp2 = ExperimentRepository(db_session).create(         # eks: exp.namespace 비어 있음 → 앱 ns
        app_id=1, chaos_type="pod-kill", params={}, status="completed",
        started_at=exp.started_at, finished_at=exp.finished_at)
    seen.clear()
    collect_experiment_metrics(db_session, exp2, Recording())
    assert seen == [exp2.app.namespace] * 3


def test_collect_queries_candidate_target_workload(db_session):
    """가설 후보가 있으면 R지수 집계는 app.name이 아니라 후보의 target_workload로 조회한다.

    다중 서비스 SUT(부띠끄=online-boutique 앱, 실제 장애 대상=adservice) — app.name으로
    Istio를 조회하면 매칭이 안 돼 R지수가 비는 09/07 라이브 발견의 회귀 가드."""
    from app.db.repositories import HypothesisRepository
    from app.services.agent.hypothesis_schema import CandidateProposal

    exp = _completed_exp(db_session)                     # app_id=1 = online-boutique
    repo = HypothesisRepository(db_session)
    run = repo.create_run(app_id=1, goal_text="t", candidate_count=1,
                          input_payload={}, status="ready")
    [cand] = repo.add_candidates(run.id, [CandidateProposal(
        title="adservice 파드 강제 종료 검증", chaos_type="pod-kill",
        target_workload="adservice", hypothesis="파드가 죽으면 실패할 것이다",
        expected_impact="오류율 상승 예상")])
    exp.candidate_id = cand.id
    db_session.commit()
    seen = []

    class Recording(StubPrometheus):
        def phase_summary(self, namespace, app_name, phase, start, end):
            seen.append(app_name)
            return super().phase_summary(namespace, app_name, phase, start, end)

    collect_experiment_metrics(db_session, exp, Recording())
    assert seen == ["adservice"] * 3                     # app.name(online-boutique)이 아니라 후보 대상


def test_observed_workload_name_falls_back_to_app_name(db_session):
    """후보 없는 폼 직접 경로는 app.name 유지(k3s·기존 EKS 폼 경로 회귀 없음)."""
    from app.services.metrics_collector import observed_workload_name

    exp = _completed_exp(db_session)                     # candidate_id 없음
    assert observed_workload_name(db_session, exp) == exp.app.name
