"""실험 완료 시 3구간(기준선/장애/회복) 소급 집계 + R지수 저장.

구간 경계(스펙 확정): 기준선 [started_at−5m, started_at] ·
장애 [started_at, started_at+duration] · 회복 [장애 종료, finished_at].
실패는 실험 상태를 건드리지 않고 경고 로그로 격리.
"""
import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from app.db.models import Experiment
from app.services import r_index
from app.services.interfaces import PrometheusService

logger = logging.getLogger(__name__)

BASELINE_WINDOW_S = 300
_PODKILL_GRACE_S = 30  # experiments.py 워처와 동일 값


def collect_experiment_metrics(session: Session, exp: Experiment,
                               prometheus: PrometheusService) -> None:
    try:
        app = exp.app
        duration = int(exp.params.get("duration_s") or _PODKILL_GRACE_S)
        injected = exp.started_at
        fault_end = injected + timedelta(seconds=duration)
        recovered = exp.finished_at or fault_end

        baseline = prometheus.phase_summary(
            app.namespace, app.name, "baseline",
            injected - timedelta(seconds=BASELINE_WINDOW_S), injected)
        fault = prometheus.phase_summary(
            app.namespace, app.name, "fault", injected, fault_end)
        recovery = prometheus.phase_summary(
            app.namespace, app.name, "recovery", fault_end, recovered)
        recovery["recovery_seconds"] = round(
            max((recovered - fault_end).total_seconds(), 0.0), 1)

        exp.baseline_metrics = baseline
        exp.fault_metrics = fault
        exp.recovery_metrics = recovery
        exp.r_index = r_index.compute(baseline, fault, recovery)["r"]
        session.commit()
    except Exception:
        logger.warning("실측 지표 수집 실패 — 실험 상태는 유지 (exp=%s)",
                       exp.id, exc_info=True)
