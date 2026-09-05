"""개선 제안 입력 페이로드 조립 — 순수(외부 조회 없음, 설계 2026-09-05 §2).

Run의 input_payload(manifest 원문·정적 분석)와 승인 후보·2단계 실험 행만으로 조립한다.
핸드오프의 istio/events/logs는 k3s에서 Stub 값이라 싣지 않는다 — EKS Real 소스 연결 시 확장.
"""
from __future__ import annotations

from app.db.models import Experiment, ExperimentCandidate, HypothesisRun
from app.services.agent.hypothesis_schema import ImprovementInputPayload, ManifestFinding
from app.services.improvement_specs import ALLOWED_IMPROVEMENTS

MAX_PROPOSALS = 3


def assemble_improvement_input(run: HypothesisRun, experiment: Experiment,
                               candidate: ExperimentCandidate | None,
                               max_proposals: int = MAX_PROPOSALS) -> ImprovementInputPayload:
    payload = run.input_payload or {}
    app = run.app
    return ImprovementInputPayload(
        app={"name": app.name, "env": app.env, "port": app.port, "health_path": app.health_path},
        manifest_yaml=payload.get("manifest_yaml") or app.manifest or "",
        manifest_findings=[ManifestFinding(**f) for f in payload.get("manifest_findings") or []],
        candidate={
            "title": candidate.title if candidate else "",
            "chaos_type": experiment.chaos_type,
            "target_workload": candidate.target_workload if candidate else app.name,
            "hypothesis": candidate.hypothesis if candidate else "",
            "params": experiment.params or {},
        },
        experiment={
            "id": experiment.id,
            "status": experiment.status,
            "r_index": experiment.r_index,
            "started_at": experiment.started_at.isoformat() if experiment.started_at else None,
            "finished_at": experiment.finished_at.isoformat() if experiment.finished_at else None,
        },
        phase_summaries={
            "baseline": experiment.baseline_metrics or {},
            "fault": experiment.fault_metrics or {},
            "recovery": experiment.recovery_metrics or {},
        },
        allowed_improvements=ALLOWED_IMPROVEMENTS,
        max_proposals=max(1, min(int(max_proposals), MAX_PROPOSALS)),
    )
