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
