from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    """모든 모델 테이블 생성 (idempotent)."""
    import app.db.models  # noqa: F401  — 모델 등록

    Base.metadata.create_all(bind=engine)


def get_session() -> Iterator[Session]:
    """FastAPI Depends용 세션 제공자."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
