from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (AgentHandoff, AgentIteration, App, Build, Experiment,
                           ExperimentCandidate, ExperimentSession, HypothesisRun,
                           ImprovementProposal, ScenarioRun, _now)


class AppRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, **kwargs) -> App:
        obj = App(**kwargs)
        self.session.add(obj)
        self.session.commit()
        return obj

    def get(self, app_id: int) -> App | None:
        return self.session.get(App, app_id)

    def list_all(self) -> list[App]:
        return list(self.session.scalars(select(App).order_by(App.id)))


class BuildRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, **kwargs) -> Build:
        obj = Build(**kwargs)
        self.session.add(obj)
        self.session.commit()
        return obj

    def list_for_app(self, app_id: int) -> list[Build]:
        stmt = select(Build).where(Build.app_id == app_id).order_by(Build.id.desc())
        return list(self.session.scalars(stmt))


class ExperimentRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, **kwargs) -> Experiment:
        obj = Experiment(**kwargs)
        self.session.add(obj)
        self.session.commit()
        return obj

    def get(self, exp_id: int) -> Experiment | None:
        return self.session.get(Experiment, exp_id)

    def list_all(self) -> list[Experiment]:
        return list(self.session.scalars(select(Experiment).order_by(Experiment.id.desc())))


class ExperimentSessionRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, **kwargs) -> ExperimentSession:
        obj = ExperimentSession(**kwargs)
        self.session.add(obj)
        self.session.commit()
        return obj

    def get(self, session_id: int) -> ExperimentSession | None:
        return self.session.get(ExperimentSession, session_id)

    def preparing_for_app(self, app_id: int) -> ExperimentSession | None:
        stmt = (
            select(ExperimentSession)
            .where(ExperimentSession.app_id == app_id,
                   ExperimentSession.status.in_(("queued", "preparing")))
            .order_by(ExperimentSession.id.desc())
        )
        return self.session.scalars(stmt).first()

    def ready_for_app(self, app_id: int) -> list[ExperimentSession]:
        stmt = (
            select(ExperimentSession)
            .where(ExperimentSession.app_id == app_id,
                   ExperimentSession.status == "ready")
            .order_by(ExperimentSession.id.desc())
        )
        return list(self.session.scalars(stmt))


class ScenarioRunRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, **kwargs) -> ScenarioRun:
        obj = ScenarioRun(**kwargs)
        self.session.add(obj)
        self.session.commit()
        return obj

    def get(self, run_id: int) -> ScenarioRun | None:
        return self.session.get(ScenarioRun, run_id)

    def active_for_session(self, preparation_session_id: int) -> ScenarioRun | None:
        stmt = (
            select(ScenarioRun)
            .where(ScenarioRun.preparation_session_id == preparation_session_id,
                   ScenarioRun.status.in_(("queued", "running")))
            .order_by(ScenarioRun.id.desc())
        )
        return self.session.scalars(stmt).first()

    def latest_for_hypothesis(self, hypothesis_run_id: int) -> ScenarioRun | None:
        stmt = (
            select(ScenarioRun)
            .where(ScenarioRun.hypothesis_run_id == hypothesis_run_id)
            .order_by(ScenarioRun.id.desc())
        )
        return self.session.scalars(stmt).first()


class IterationRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, **kwargs) -> AgentIteration:
        obj = AgentIteration(**kwargs)
        self.session.add(obj)
        self.session.commit()
        return obj

    def list_for_experiment(self, experiment_id: int) -> list[AgentIteration]:
        stmt = (
            select(AgentIteration)
            .where(AgentIteration.experiment_id == experiment_id)
            .order_by(AgentIteration.iteration)
        )
        return list(self.session.scalars(stmt))


class HandoffRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, **kwargs) -> AgentHandoff:
        obj = AgentHandoff(**kwargs)
        self.session.add(obj)
        self.session.commit()
        return obj

    def get(self, handoff_id: int) -> AgentHandoff | None:
        return self.session.get(AgentHandoff, handoff_id)

    def list_for_experiment(self, experiment_id: int) -> list[AgentHandoff]:
        stmt = (
            select(AgentHandoff)
            .where(AgentHandoff.experiment_id == experiment_id)
            .order_by(AgentHandoff.id.desc())
        )
        return list(self.session.scalars(stmt))

    def latest_for_experiment(self, experiment_id: int) -> AgentHandoff | None:
        rows = self.list_for_experiment(experiment_id)
        return rows[0] if rows else None

    def update_payload(self, handoff: AgentHandoff, payload: dict,
                       schema_version: str) -> AgentHandoff:
        handoff.payload = payload
        handoff.schema_version = schema_version
        handoff.updated_at = _now()
        self.session.commit()
        return handoff

    def delete(self, handoff: AgentHandoff) -> None:
        self.session.delete(handoff)
        self.session.commit()


class HypothesisRepository:
    def __init__(self, session: Session):
        self.session = session

    # ── Run ──
    def create_run(self, **kwargs) -> HypothesisRun:
        obj = HypothesisRun(**kwargs)
        self.session.add(obj)
        self.session.commit()
        return obj

    def get_run(self, run_id: int) -> HypothesisRun | None:
        return self.session.get(HypothesisRun, run_id)

    def latest_run_for_app(self, app_id: int) -> HypothesisRun | None:
        stmt = (select(HypothesisRun).where(HypothesisRun.app_id == app_id)
                .order_by(HypothesisRun.id.desc()).limit(1))
        return self.session.scalars(stmt).first()

    def list_runs(self) -> list[HypothesisRun]:
        """실험 목록 행용 — 최신순."""
        stmt = select(HypothesisRun).order_by(HypothesisRun.id.desc())
        return list(self.session.scalars(stmt))

    def set_status(self, run: HypothesisRun, status: str, error: str = "",
                   finished: bool = False) -> HypothesisRun:
        run.status = status
        run.error = error
        if finished:
            run.finished_at = _now()
        self.session.commit()
        return run

    def set_freeform(self, run: HypothesisRun, status: str, error: str = "") -> HypothesisRun:
        run.freeform_status = status
        run.freeform_error = error
        self.session.commit()
        return run

    def set_snapshot(self, run: HypothesisRun, model_name: str, cli_version: str) -> HypothesisRun:
        run.model_name = model_name
        run.cli_version = cli_version
        self.session.commit()
        return run

    # ── Candidate ──
    def add_candidates(self, run_id: int, proposals, source: str = "agent",
                       ) -> list[ExperimentCandidate]:
        rows = [
            ExperimentCandidate(
                run_id=run_id, title=p.title, chaos_type=p.chaos_type,
                target_workload=p.target_workload, hypothesis=p.hypothesis,
                expected_impact=p.expected_impact, source=source)
            for p in proposals
        ]
        self.session.add_all(rows)
        self.session.commit()
        return rows

    def get_candidate(self, candidate_id: int) -> ExperimentCandidate | None:
        return self.session.get(ExperimentCandidate, candidate_id)

    def list_candidates(self, run_id: int) -> list[ExperimentCandidate]:
        stmt = (select(ExperimentCandidate)
                .where(ExperimentCandidate.run_id == run_id)
                .order_by(ExperimentCandidate.id))
        return list(self.session.scalars(stmt))

    def set_candidate_detail(self, candidate: ExperimentCandidate, status: str,
                             params: dict | None = None, rationale: str = "",
                             error: str = "") -> ExperimentCandidate:
        candidate.detail_status = status
        if params is not None:
            candidate.params = params
        candidate.detail_rationale = rationale
        candidate.error = error
        self.session.commit()
        return candidate

    def experiment_for_run(self, run_id: int) -> Experiment | None:
        """이 Run의 후보로 만들어진 실험 (승인 완료 여부 판단용)."""
        cand_ids = select(ExperimentCandidate.id).where(ExperimentCandidate.run_id == run_id)
        stmt = (select(Experiment).where(Experiment.candidate_id.in_(cand_ids))
                .order_by(Experiment.id.desc()).limit(1))
        return self.session.scalars(stmt).first()

    # ── Improvement (개선 단계) ──
    def set_improvement(self, run: HypothesisRun, status: str, error: str = "") -> HypothesisRun:
        run.improvement_status = status
        run.improvement_error = error
        self.session.commit()
        return run

    def list_proposals(self, run_id: int) -> list[ImprovementProposal]:
        stmt = (select(ImprovementProposal)
                .where(ImprovementProposal.run_id == run_id)
                .order_by(ImprovementProposal.id))
        return list(self.session.scalars(stmt))

    def approved_proposals(self, run_id: int) -> list[ImprovementProposal]:
        return [p for p in self.list_proposals(run_id) if p.status == "approved"]

    def replace_proposals(self, run_id: int, experiment_id: int | None, proposals,
                          ) -> list[ImprovementProposal]:
        """재생성 = 기존 제안 전부 삭제 후 삽입 (승인 이력은 회귀 스냅샷에 남는다)."""
        for old in self.list_proposals(run_id):
            self.session.delete(old)
        rows = [
            ImprovementProposal(
                run_id=run_id, experiment_id=experiment_id, type=p.type, title=p.title,
                deployment=p.deployment, container=p.container, key=p.key, value=p.value,
                patch=p.patch, rationale=p.rationale, expected_effect=p.expected_effect)
            for p in proposals
        ]
        self.session.add_all(rows)
        self.session.commit()
        return rows

    def reopen_proposals(self, run_id: int) -> list[ImprovementProposal]:
        rows = self.list_proposals(run_id)
        for row in rows:
            row.status = "proposed"
        self.session.commit()
        return rows

    def decide_proposals(self, run_id: int, approved_ids: set[int],
                         edits: dict[int, dict] | None = None) -> list[ImprovementProposal]:
        """선택 → approved(편집분은 값 교체 + source=user_edit), 나머지 → rejected."""
        rows = self.list_proposals(run_id)
        for row in rows:
            edit = (edits or {}).get(row.id)
            if row.id in approved_ids:
                row.status = "approved"
                if edit is not None:
                    row.key, row.value, row.patch = edit["key"], edit["value"], edit["patch"]
                    row.source = "user_edit"
            else:
                row.status = "rejected"
        self.session.commit()
        return rows
