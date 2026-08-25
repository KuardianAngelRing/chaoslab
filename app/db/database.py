from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
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
    _upgrade_scenario_runs()


def _upgrade_scenario_runs() -> None:
    """create_all이 갱신하지 못하는 기존 SQLite의 보고서 스냅샷 컬럼을 보완한다."""
    if engine.dialect.name != "sqlite" or "scenario_runs" not in inspect(engine).get_table_names():
        return
    existing = {column["name"] for column in inspect(engine).get_columns("scenario_runs")}
    columns = {
        "baseline_results": "JSON",
        "improvement_changes": "JSON",
        "comparison": "JSON",
        "r_index": "JSON",
        "report_content": "JSON",
        "report_generated_at": "DATETIME",
    }
    with engine.begin() as connection:
        for name, ddl_type in columns.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE scenario_runs ADD COLUMN {name} {ddl_type}"))


def get_session() -> Iterator[Session]:
    """FastAPI Depends용 세션 제공자."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
