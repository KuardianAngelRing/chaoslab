"""HandoffRepository CRUD — hermetic in-memory DB.

seed가 만든 스냅샷과 섞이지 않게 전용 실험을 새로 만들어 검증한다.
"""
from app.db.repositories import ExperimentRepository, HandoffRepository
from app.db.seed import seed_data


def _fresh_experiment(db_session):
    seed_data(db_session)
    return ExperimentRepository(db_session).create(
        app_id=1, chaos_type="PodChaos", params={"action": "pod-kill"}, status="completed",
    )


def test_handoff_crud_roundtrip(db_session):
    exp = _fresh_experiment(db_session)
    repo = HandoffRepository(db_session)

    h1 = repo.create(experiment_id=exp.id, schema_version="1.0", payload={"a": 1})
    h2 = repo.create(experiment_id=exp.id, schema_version="1.0", payload={"b": 2})

    assert [h.id for h in repo.list_for_experiment(exp.id)] == [h2.id, h1.id]  # 최신순
    assert repo.latest_for_experiment(exp.id).id == h2.id

    repo.update_payload(h1, {"c": 3}, "1.1")
    assert repo.get(h1.id).payload == {"c": 3}
    assert repo.get(h1.id).schema_version == "1.1"
    assert repo.get(h1.id).updated_at is not None

    repo.delete(h2)
    assert repo.get(h2.id) is None


def test_latest_none_when_empty(db_session):
    exp = _fresh_experiment(db_session)
    assert HandoffRepository(db_session).latest_for_experiment(exp.id) is None
