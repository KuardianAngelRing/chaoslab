"""앱 등록/빌드 라우트 — stub 모드(기본). 외부 시스템 호출 없이 동작."""

import json
import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db.models import App
from app.db.repositories import AppRepository
from app.routers.apps import _bootstrap, parse_env_json


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


def test_parse_env_json_nonstring_key_coerced():
    raw = json.dumps([{"key": 123, "value": "v", "is_secret": False}])
    assert parse_env_json(raw) == [{"key": "123", "value": "v", "is_secret": False}]


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


def test_classify_framework_by_signature_files():
    from app.services.real.gitops import classify_framework
    assert classify_framework({"build.gradle", "src"}) == "spring"
    assert classify_framework({"pom.xml"}) == "spring"
    assert classify_framework({"package.json", "next.config.ts"}) == "nextjs"  # next 우선
    assert classify_framework({"package.json"}) == "node"
    assert classify_framework({"go.mod", "main.go"}) == "go"
    assert classify_framework({"requirements.txt"}) == "python"
    assert classify_framework({"pyproject.toml"}) == "python"
    assert classify_framework({"Cargo.toml"}) == "rust"
    assert classify_framework({"README.md"}) == "docker"  # 미인식 fallback
    assert classify_framework(set()) == "docker"


def test_fetch_repo_root_files_bad_url_returns_empty():
    from app.services.real.gitops import fetch_repo_root_files
    assert fetch_repo_root_files("not-a-github-url") == set()
    assert fetch_repo_root_files("https://gitlab.com/x/y") == set()


def test_register_app_stores_branch(client):
    resp = client.post("/apps", data={
        "repo_url": "https://github.com/foo/branch-svc", "branch": "develop",
        "framework": "spring", "health_path": "/h", "port": "8080",
    })
    assert resp.status_code == 200
    from app.main import app as fastapi_app
    from app.db.database import get_session
    gen = fastapi_app.dependency_overrides[get_session]()
    session = next(gen)
    try:
        rec = next(a for a in AppRepository(session).list_all() if a.name == "branch-svc")
        assert rec.branch == "develop"
    finally:
        gen.close()


def test_register_app_defaults_branch_main(client):
    resp = client.post("/apps", data={
        "repo_url": "https://github.com/foo/nobr-svc", "framework": "spring",
    })
    assert resp.status_code == 200
    from app.main import app as fastapi_app
    from app.db.database import get_session
    gen = fastapi_app.dependency_overrides[get_session]()
    session = next(gen)
    try:
        rec = next(a for a in AppRepository(session).list_all() if a.name == "nobr-svc")
        assert rec.branch == "main"
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


class _SpyGitOps:
    def __init__(self):
        self.calls = []

    def bootstrap_app(self, name, repo_url, port, health, env, secret_name):
        self.calls.append((name, repo_url, port, health, env, secret_name))

    def update_image_tag(self, name, image):
        pass


class _FailGitOps(_SpyGitOps):
    def bootstrap_app(self, *a, **k):
        raise RuntimeError("push failed")


class _SpyK8s:
    def __init__(self):
        self.calls = []

    def apply_env_secret(self, namespace, name, data):
        self.calls.append((namespace, name, data))


def _engine_with_app(env_vars):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = Session()
    s.add(App(name="demo", repo_url="https://github.com/x/demo", framework="docker",
              health_path="/actuator/health", port=9000,
              namespace="sut", env_vars=env_vars, status="registering"))
    s.commit()
    s.close()
    return Session


def test_bootstrap_success_splits_and_sets_ready(monkeypatch):
    Session = _engine_with_app([
        {"key": "DB_HOST", "value": "mysql", "is_secret": False},
        {"key": "JWT", "value": "x", "is_secret": True},
    ])
    monkeypatch.setattr("app.routers.apps.SessionLocal", Session)
    gitops, k8s = _SpyGitOps(), _SpyK8s()
    monkeypatch.setattr("app.routers.apps.make_gitops", lambda: gitops)
    monkeypatch.setattr("app.routers.apps.make_k8s", lambda: k8s)

    _bootstrap("demo")

    assert k8s.calls == [("sut", "demo-env", {"JWT": "x"})]
    # bootstrap는 framework가 아니라 사용자가 입력한 port/health를 values.yaml에 써야 함
    assert gitops.calls == [
        ("demo", "https://github.com/x/demo", 9000, "/actuator/health", {"DB_HOST": "mysql"}, "demo-env")
    ]
    s = Session()
    app = next(a for a in AppRepository(s).list_all() if a.name == "demo")
    s.close()
    assert app.status == "ready"


def test_bootstrap_failure_logs_and_sets_register_failed(monkeypatch, caplog):
    Session = _engine_with_app([{"key": "DB_HOST", "value": "mysql", "is_secret": False}])
    monkeypatch.setattr("app.routers.apps.SessionLocal", Session)
    monkeypatch.setattr("app.routers.apps.make_gitops", lambda: _FailGitOps())
    monkeypatch.setattr("app.routers.apps.make_k8s", lambda: _SpyK8s())

    with caplog.at_level(logging.ERROR):
        _bootstrap("demo")

    s = Session()
    app = next(a for a in AppRepository(s).list_all() if a.name == "demo")
    s.close()
    assert app.status == "register-failed"
    assert "bootstrap failed" in caplog.text
