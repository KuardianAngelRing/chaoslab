"""전달 페이로드 조립 — DB산(실험·iteration)은 세션에서, 외부산은 HandoffSourceService에서.

단계 요약 규칙: Experiment.*_metrics가 계약(PhaseSummary) 형태로 저장돼 있으면 우선,
아니면(비었거나 Slice 5 이전의 임의 형태) Stub/Real 소스 값 사용.
"""
import logging

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Experiment
from app.db.repositories import IterationRepository
from app.services.agent.handoff_schema import (
    AgentHandoffPayload,
    Budget,
    DeploymentInfo,
    ExperimentInfo,
    ImprovementAttempt,
    IstioConfig,
    K8sEvent,
    PhaseSummaries,
    PhaseSummary,
    RIndexBreakdown,
)
from app.services import r_index
from app.services.chaos_specs import CHAOS_SPECS
from app.services.interfaces import HandoffSourceService

logger = logging.getLogger(__name__)

_PHASE_COLUMNS = {
    "baseline": "baseline_metrics",
    "fault": "fault_metrics",
    "recovery": "recovery_metrics",
}

def _phase_summary(exp: Experiment, source: HandoffSourceService, phase: str) -> PhaseSummary:
    stored = getattr(exp, _PHASE_COLUMNS[phase])
    if stored:
        try:
            return PhaseSummary(**stored)
        except ValidationError:
            # 무음 대체 금지 — AI가 진짜/샘플 데이터를 구분할 근거를 로그로 남김
            logger.warning(
                "저장된 %s metrics가 계약과 불일치 — 소스 샘플로 대체 (exp=%s)",
                phase, exp.id,
            )
    return PhaseSummary(**source.phase_summary(exp.app.namespace, exp.app.name, phase))


def assemble_handoff(session: Session, source: HandoffSourceService,
                     exp: Experiment) -> AgentHandoffPayload:
    app = exp.app
    iterations = IterationRepository(session).list_for_experiment(exp.id)
    used_usd = sum(it.llm_cost_usd for it in iterations)

    summaries = PhaseSummaries(
        baseline=_phase_summary(exp, source, "baseline"),
        fault=_phase_summary(exp, source, "fault"),
        recovery=_phase_summary(exp, source, "recovery"),
    )
    # 항목별 점수는 페이로드에 실리는 바로 그 요약으로 계산 — AI가 받은 숫자와 항상 일관
    scores = r_index.compute(summaries.baseline.model_dump(),
                             summaries.fault.model_dump(),
                             summaries.recovery.model_dump())

    return AgentHandoffPayload(
        experiment=ExperimentInfo(
            id=exp.id,
            app_name=app.name,
            namespace=app.namespace,
            chaos_type=exp.chaos_type,
            status=exp.status,
            params=exp.params,
            allowed_ranges=CHAOS_SPECS.get(exp.chaos_type, {}).get("fields", {}),
            started_at=exp.started_at.isoformat() if exp.started_at else None,
            finished_at=exp.finished_at.isoformat() if exp.finished_at else None,
        ),
        phase_summaries=summaries,
        istio_config=IstioConfig(**source.istio_config(app.namespace, app.name)),
        deployment_info=DeploymentInfo(**source.deployment_info(app.namespace, app.name)),
        k8s_events=[K8sEvent(**e) for e in source.events(app.namespace, app.name)],
        error_log_samples=source.error_logs(app.namespace, app.name, limit=20),
        r_index=RIndexBreakdown(
            availability=scores["availability"],
            latency_score=scores["latency_score"],
            recovery_score=scores["recovery_score"],
            baseline_r=exp.baseline_r,
            current_r=exp.r_index,
            target_r=exp.target_r,
        ),
        improvement_history=[
            ImprovementAttempt(
                iteration=it.iteration,
                params_before=it.params_before,
                params_after=it.params_after,
                r_index=it.r_index,
                verdict=it.verdict,
            )
            for it in iterations
        ],
        budget=Budget(
            llm_cost_used_usd=round(used_usd, 4),
            llm_cost_remaining_usd=round(max(settings.llm_budget_usd - used_usd, 0.0), 4),
            iterations_remaining=max(settings.max_agent_iterations - len(iterations), 0),
        ),
    )
