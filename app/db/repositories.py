from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (AgentHandoff, AgentIteration, App, Build, Experiment,
                           ExperimentCandidate, HypothesisRun, _now)


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
