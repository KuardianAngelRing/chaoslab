"""실험 완료 시 3구간(기준선/장애/회복) 소급 집계 + R지수 저장.

구간 경계(스펙 확정): 기준선 [started_at−5m, started_at] ·
장애 [started_at, started_at+duration] · 회복 [장애 종료, finished_at].
실패는 실험 상태를 건드리지 않고 경고 로그로 격리.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.db.models import Experiment
from app.services import r_index
from app.services.interfaces import PrometheusService

logger = logging.getLogger(__name__)

BASELINE_WINDOW_S = 300
_PODKILL_GRACE_S = 30  # experiments.py 워처와 동일 값


def _aware_utc(dt: datetime) -> datetime:
    """SQLite 재로드로 naive가 된 UTC 값을 aware로 정규화.

    naive인 채 두면 (a) aware finished_at과의 뺄셈이 TypeError,
    (b) .timestamp()가 로컬시간(KST)으로 해석돼 쿼리 구간이 9시간 밀린다.
    """
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def collect_experiment_metrics(session: Session, exp: Experiment,
                               prometheus: PrometheusService) -> None:
    try:
        app = exp.app
        # k3s는 실험 전용 ns(ADR-0009)에서 관측 — eks는 exp.namespace가 비어 앱 ns 사용
        namespace = exp.namespace or app.namespace
        duration = int(exp.params.get("duration_s") or _PODKILL_GRACE_S)
        injected = _aware_utc(exp.started_at)
        fault_end = injected + timedelta(seconds=duration)
        recovered = _aware_utc(exp.finished_at) if exp.finished_at else fault_end

        baseline = prometheus.phase_summary(
            namespace, app.name, "baseline",
            injected - timedelta(seconds=BASELINE_WINDOW_S), injected)
        fault = prometheus.phase_summary(
            namespace, app.name, "fault", injected, fault_end)
        recovery = prometheus.phase_summary(
            namespace, app.name, "recovery", fault_end, recovered)
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
