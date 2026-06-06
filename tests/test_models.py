"""App.env_vars JSON 컬럼 — 등록 시 env/secret 보관."""
from app.db.models import App


def test_app_has_env_vars_default_empty(db_session):
    app = App(name="demo", repo_url="https://github.com/x/demo", framework="fastapi")
    db_session.add(app)
    db_session.commit()
    assert app.env_vars == []


def test_app_env_vars_roundtrip(db_session):
    rows = [{"key": "DB_HOST", "value": "mysql", "is_secret": False},
            {"key": "JWT_SECRET", "value": "s3cr3t", "is_secret": True}]
    app = App(name="demo2", repo_url="https://github.com/x/d2", framework="spring",
              env_vars=rows)
    db_session.add(app)
    db_session.commit()
    db_session.refresh(app)
    assert app.env_vars[1]["key"] == "JWT_SECRET"
    assert app.env_vars[1]["is_secret"] is True
