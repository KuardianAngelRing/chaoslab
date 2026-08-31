from fastapi import BackgroundTasks
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db.models import App, ExperimentSession


def _session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _k3s_app(session):
    app = App(name="order-resilience-lab", repo_url="k3s://manifest-upload",
              framework="manifest", env="k3s", manifest="kind: Deployment")
    session.add(app)
    session.commit()
    return app


def test_create_preparation_only_creates_queued_session():
    from app.routers.preparations import create_preparation

    Session = _session_factory()
    s = Session()
    app = _k3s_app(s)
    background = BackgroundTasks()

    payload = create_preparation(background, app.id, "주문 흐름 복원력", s)

    assert payload["status"] == "queued"
    assert s.get(ExperimentSession, payload["id"]).namespace.endswith(f"-{payload['id']}")
    assert len(background.tasks) == 0
    s.close()


def test_new_preparation_replaces_ready_environment():
    from app.routers.preparations import create_preparation

    Session = _session_factory()
    s = Session()
    app = _k3s_app(s)
    previous = ExperimentSession(app_id=app.id, status="ready", namespace="chaoslab-session-order-1")
    s.add(previous)
    s.commit()
    background = BackgroundTasks()

    payload = create_preparation(background, app.id, "", s)

    assert s.get(ExperimentSession, previous.id).status == "cancelled"
    assert payload["status"] == "queued"
    assert len(background.tasks) == 1
    s.close()


def test_prepare_environment_persists_readiness(monkeypatch):
    from app.routers import preparations

    Session = _session_factory()
    s = Session()
    app = _k3s_app(s)
    row = ExperimentSession(app_id=app.id, status="preparing", namespace="chaoslab-session-order-1")
    s.add(row)
    s.commit()
    session_id = row.id
    s.close()

    class Workload:
        def deploy(self, namespace, manifest):
            assert namespace == "chaoslab-session-order-1"
            assert manifest == "kind: Deployment"

        def readiness(self, namespace):
            return {"deployments_ready": 5, "deployments_total": 5,
                    "pods_ready": 10, "pods_total": 10, "blockers": []}

        def teardown(self, namespace):
            raise AssertionError("ready environment must be kept for stages 3 and 4")

    monkeypatch.setattr(preparations, "SessionLocal", Session)
    monkeypatch.setattr(preparations, "make_k3s_workload", lambda: Workload())

    preparations._prepare_environment(session_id)

    s = Session()
    row = s.get(ExperimentSession, session_id)
    assert row.status == "ready"
    assert row.progress["pods_ready"] == 10
    s.close()
