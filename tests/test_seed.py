from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.repositories import AppRepository, ExperimentRepository
from app.db.seed import seed_data


def test_seed_populates_apps_and_experiments():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()

    seed_data(session)

    assert len(AppRepository(session).list_all()) >= 3
    assert len(ExperimentRepository(session).list_all()) >= 1


def test_seed_running_experiment_has_metrics(db_session):
    from app.db.seed import seed_data
    from app.db.repositories import ExperimentRepository

    seed_data(db_session)
    running = [e for e in ExperimentRepository(db_session).list_all() if e.status == "running"]
    assert running, "running 실험이 seed돼야 함"
    exp = running[0]
    assert exp.baseline_metrics.get("p99") == 89
    assert exp.fault_metrics.get("p99") == 412
    assert exp.fault_metrics.get("error") == 2.1
