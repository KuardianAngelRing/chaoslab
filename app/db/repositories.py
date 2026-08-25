from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AgentHandoff,
    AgentIteration,
    App,
    Build,
    Experiment,
    ExperimentSession,
    ScenarioRun,
    _now,
)


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
