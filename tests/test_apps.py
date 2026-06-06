"""앱 등록/빌드 라우트 — stub 모드(기본). 외부 시스템 호출 없이 동작."""


def test_register_app_creates_and_lists(client):
    resp = client.post(
        "/apps",
        data={"repo_url": "https://github.com/foo/payment-svc",
              "framework": "fastapi", "health_path": "/healthz", "port": "8080"},
    )
    assert resp.status_code == 200
    assert "payment-svc" in resp.text  # 파생된 앱 이름이 목록에 노출


def test_build_app_returns_ok(client):
    # seed된 app id=1 (online-boutique)에 수동 빌드 트리거
    resp = client.post("/apps/1/build")
    assert resp.status_code == 200


def test_build_unknown_app_404(client):
    resp = client.post("/apps/99999/build")
    assert resp.status_code == 404


import json

from app.db.repositories import AppRepository
from app.routers.apps import parse_env_json


def test_parse_env_json_normalizes():
    raw = json.dumps([
        {"key": "DB_HOST", "value": "mysql", "is_secret": False},
        {"key": "  ", "value": "skip", "is_secret": False},   # 빈 키 제거
        {"key": "JWT", "value": "x", "is_secret": True},
    ])
    out = parse_env_json(raw)
    assert out == [
        {"key": "DB_HOST", "value": "mysql", "is_secret": False},
        {"key": "JWT", "value": "x", "is_secret": True},
    ]


def test_parse_env_json_broken_returns_empty():
    assert parse_env_json("not json") == []
    assert parse_env_json("") == []


def test_register_app_stores_env_vars(client):
    resp = client.post("/apps", data={
        "repo_url": "https://github.com/foo/env-svc", "framework": "spring",
        "health_path": "/actuator/health", "port": "8080",
        "env_json": json.dumps([{"key": "DB_HOST", "value": "mysql", "is_secret": False}]),
    })
    assert resp.status_code == 200
    from app.main import app as fastapi_app
    from app.db.database import get_session
    gen = fastapi_app.dependency_overrides[get_session]()
    session = next(gen)
    try:
        rec = next(a for a in AppRepository(session).list_all() if a.name == "env-svc")
        assert rec.env_vars == [{"key": "DB_HOST", "value": "mysql", "is_secret": False}]
    finally:
        gen.close()


def test_reregister_replaces_env_vars(client):
    base = {"repo_url": "https://github.com/foo/up-svc", "framework": "spring",
            "health_path": "/h", "port": "8080"}
    client.post("/apps", data={**base, "env_json": json.dumps(
        [{"key": "A", "value": "1", "is_secret": False}])})
    client.post("/apps", data={**base, "env_json": json.dumps(
        [{"key": "B", "value": "2", "is_secret": True}])})
    from app.main import app as fastapi_app
    from app.db.database import get_session
    gen = fastapi_app.dependency_overrides[get_session]()
    session = next(gen)
    try:
        rec = next(a for a in AppRepository(session).list_all() if a.name == "up-svc")
        assert rec.env_vars == [{"key": "B", "value": "2", "is_secret": True}]
    finally:
        gen.close()
