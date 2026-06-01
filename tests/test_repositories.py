import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.repositories import AppRepository, ExperimentRepository


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    s = SessionLocal()
    yield s
    s.close()


def test_app_create_and_list(session):
    repo = AppRepository(session)
    repo.create(name="boutique", repo_url="https://x/y", framework="go")
    apps = repo.list_all()
    assert len(apps) == 1
    assert apps[0].name == "boutique"


def test_app_get_by_id(session):
    repo = AppRepository(session)
    created = repo.create(name="api", repo_url="https://x/api", framework="python")
    fetched = repo.get(created.id)
    assert fetched is not None
    assert fetched.framework == "python"


def test_experiment_create_links_app(session):
    app_repo = AppRepository(session)
    app = app_repo.create(name="svc", repo_url="https://x/svc", framework="node")
    exp_repo = ExperimentRepository(session)
    exp = exp_repo.create(app_id=app.id, chaos_type="NetworkChaos", params={"delay": "200ms"})
    assert exp.id is not None
    assert exp_repo.list_all()[0].chaos_type == "NetworkChaos"
