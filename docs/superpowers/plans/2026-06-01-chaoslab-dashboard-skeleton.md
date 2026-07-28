# ChaosLab 대시보드 — 걷는 뼈대 (Slice 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `uvicorn app.main:app` 한 번으로 목업과 동일한 비주얼의 6개 화면이 HTMX 네비게이션으로 뜨고, mock 데이터(실제 SQLite + seed)로 채워지며, 외부 시스템은 인터페이스 뒤 스텁으로 추상화된, 아키텍처가 완성된 대시보드 골격.

**Architecture:** 단일 FastAPI 프로세스. Jinja2 + HTMX(부분 스왑) + Alpine/vanilla JS(탭·모달·테마) + Chart.js. 우리가 소유한 데이터는 SQLAlchemy 모델 + Repository 패턴으로 SQLite에 저장하고 `seed.py`로 mock 행을 채운다. 외부 시스템(빌더·GitOps·카오스·Prometheus·Loki·K8s)은 `Protocol` 인터페이스 + `Stub` 구현으로 두어, 라우터가 인터페이스에만 의존(DIP)하게 한다. 풀/부분 렌더링 분기는 `rendering.render_page` 한 곳에 둔다.

**Tech Stack:** Python 3.12, FastAPI, Uvicorn, Jinja2, SQLAlchemy 2.0, pydantic-settings, sse-starlette, pytest, httpx. UI 라이브러리(Tailwind/Chart.js/iconify/htmx/alpine)는 CDN.

**참조 소스(읽기 필수):** `../Iac-aws/docs/graduation-dashboard-mockup.html` (2135줄, 목업). 설계 스펙: `docs/superpowers/specs/2026-06-01-chaoslab-dashboard-skeleton-design.md`.

> **커밋 컨벤션** (README): ✨새기능 🐛버그 ♻️리팩토링 🔧설정 📝문서 ✅테스트 🔥삭제.
> **TDD 규칙**: 백엔드 로직은 테스트 먼저. 템플릿/CSS 포팅은 라우트 스모크 테스트(특정 한글 라벨 존재)로 검증.

---

## File Structure

```
chaoslab/
├── requirements.txt                  # 런타임+테스트 의존성
├── .env.example                      # 환경 변수 템플릿
├── app/
│   ├── __init__.py
│   ├── main.py                       # FastAPI 앱, 라우터/정적/템플릿 마운트
│   ├── config.py                     # pydantic-settings (.env)
│   ├── deps.py                       # DI 와이어링 (Depends)
│   ├── rendering.py                  # render_page — HX-Request 분기
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── pages.py                  # GET 6개 페이지
│   │   ├── apps.py                   # 앱 액션 (스텁)
│   │   ├── experiments.py            # 실험 액션 (스텁)
│   │   ├── stream.py                 # SSE (mock 틱)
│   │   └── webhook.py                # 자리만 (스텁)
│   ├── services/
│   │   ├── __init__.py
│   │   ├── interfaces.py             # Protocol 6종
│   │   ├── stubs.py                  # Stub 구현 6종
│   │   └── agent/__init__.py         # Phase 3 자리
│   ├── db/
│   │   ├── __init__.py
│   │   ├── database.py               # 엔진/세션
│   │   ├── models.py                 # SQLAlchemy 모델 4종
│   │   ├── repositories.py           # Repository 4종
│   │   └── seed.py                   # mock 행 삽입
│   ├── templates/
│   │   ├── base.html                 # 셸
│   │   ├── _partial.html             # HX용 빈 레이아웃
│   │   ├── partials/_sidebar.html    # nav 1곳
│   │   ├── macros/components.html     # 재사용 매크로
│   │   └── pages/{dashboard,apps,experiments,experiment_detail,infra,settings}.html
│   └── static/
│       ├── css/tds.css               # 목업 <style> 추출
│       └── js/app.js                 # 테마/메뉴/탭/다이얼로그/차트
└── tests/
    ├── __init__.py
    ├── conftest.py                   # 테스트 클라이언트/DB fixture
    ├── test_repositories.py
    ├── test_seed.py
    ├── test_stubs_contract.py
    ├── test_rendering.py
    ├── test_pages.py
    └── test_stream.py
```

---

## Phase 0 — 프로젝트 스캐폴드

### Task 1: 프로젝트 부트스트랩 + 앱 기동 확인

**Files:**
- Create: `requirements.txt`
- Create: `app/__init__.py` (빈 파일)
- Create: `app/config.py`
- Create: `app/main.py`
- Create: `tests/__init__.py` (빈 파일)
- Create: `tests/conftest.py`
- Test: `tests/test_pages.py`

- [ ] **Step 1: requirements.txt 작성**

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
jinja2==3.1.5
sqlalchemy==2.0.36
pydantic-settings==2.7.1
sse-starlette==2.2.1
python-multipart==0.0.20
pytest==8.3.4
httpx==0.28.1
```

- [ ] **Step 2: 가상환경 + 설치**

Run:
```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```
Expected: 모든 패키지 설치 성공.

- [ ] **Step 3: app/config.py 작성**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "ChaosLab"
    database_url: str = "sqlite:///./chaoslab.db"

    # 외부 시스템 (Slice 1 미사용, 구조만)
    k8s_context: str = ""
    prometheus_url: str = "http://localhost:9090"
    loki_url: str = "http://localhost:3100"

    # AI (Phase 3)
    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-4-6"
    target_r: float = 0.7


settings = Settings()
```

- [ ] **Step 4: 빈 `app/__init__.py`, `tests/__init__.py` 생성**

```bash
touch app/__init__.py tests/__init__.py
```

- [ ] **Step 5: app/main.py 작성 (최소 — 루트만)**

```python
from fastapi import FastAPI

from app.config import settings

app = FastAPI(title=settings.app_name)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "app": settings.app_name}
```

- [ ] **Step 6: tests/conftest.py 작성**

```python
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)
```

- [ ] **Step 7: 첫 실패 테스트 — tests/test_pages.py**

```python
def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
```

- [ ] **Step 8: 테스트 실행 → 통과 확인**

Run: `pytest tests/test_pages.py::test_healthz -v`
Expected: PASS.

- [ ] **Step 9: 수동 기동 확인**

Run: `uvicorn app.main:app --reload` → 브라우저 `http://localhost:8000/healthz` → `{"status":"ok",...}`. 확인 후 Ctrl+C.

- [ ] **Step 10: 커밋**

```bash
git add requirements.txt app/__init__.py app/config.py app/main.py tests/__init__.py tests/conftest.py tests/test_pages.py
git commit -m "✨ FastAPI 앱 스캐폴드 + 설정 + healthz"
```

---

## Phase 1 — 데이터 레이어 (TDD)

### Task 2: DB 엔진/세션 + Base

**Files:**
- Create: `app/db/__init__.py` (빈 파일)
- Create: `app/db/database.py`

- [ ] **Step 1: app/db/database.py 작성**

```python
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
```

- [ ] **Step 2: 빈 `app/db/__init__.py` 생성**

```bash
touch app/db/__init__.py
```

- [ ] **Step 3: 커밋 (모델 추가 후 테스트하므로 여기선 구조만)**

```bash
git add app/db/__init__.py app/db/database.py
git commit -m "✨ SQLAlchemy 엔진/세션/Base"
```

### Task 3: 도메인 모델 4종

**Files:**
- Create: `app/db/models.py`

- [ ] **Step 1: app/db/models.py 작성**

```python
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class App(Base):
    __tablename__ = "apps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    repo_url: Mapped[str] = mapped_column(String(300))
    framework: Mapped[str] = mapped_column(String(50))
    health_path: Mapped[str] = mapped_column(String(100), default="/healthz")
    port: Mapped[int] = mapped_column(Integer, default=8080)
    namespace: Mapped[str] = mapped_column(String(100), default="default")
    image_repo: Mapped[str] = mapped_column(String(300), default="")
    current_sha: Mapped[str] = mapped_column(String(40), default="")
    status: Mapped[str] = mapped_column(String(30), default="unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    builds: Mapped[list["Build"]] = relationship(back_populates="app")
    experiments: Mapped[list["Experiment"]] = relationship(back_populates="app")


class Build(Base):
    __tablename__ = "builds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("apps.id"))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    image_tag: Mapped[str] = mapped_column(String(40), default="")
    workflow_name: Mapped[str] = mapped_column(String(120), default="")
    log_ref: Mapped[str] = mapped_column(String(200), default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    app: Mapped["App"] = relationship(back_populates="builds")


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("apps.id"))
    chaos_type: Mapped[str] = mapped_column(String(40))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    baseline_metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    fault_metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    recovery_metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    baseline_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    r_index: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_r: Mapped[float] = mapped_column(Float, default=0.7)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    app: Mapped["App"] = relationship(back_populates="experiments")
    iterations: Mapped[list["AgentIteration"]] = relationship(back_populates="experiment")


class AgentIteration(Base):
    __tablename__ = "agent_iterations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id"))
    iteration: Mapped[int] = mapped_column(Integer)
    observer_output: Mapped[str] = mapped_column(Text, default="")
    analyst_output: Mapped[str] = mapped_column(Text, default="")
    recommender_output: Mapped[str] = mapped_column(Text, default="")
    params_before: Mapped[dict] = mapped_column(JSON, default=dict)
    params_after: Mapped[dict] = mapped_column(JSON, default=dict)
    r_index: Mapped[float | None] = mapped_column(Float, nullable=True)
    verdict: Mapped[str] = mapped_column(String(30), default="")
    llm_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    experiment: Mapped["Experiment"] = relationship(back_populates="iterations")
```

- [ ] **Step 2: 테이블 생성 스모크 확인**

Run:
```bash
python -c "from app.db.database import init_db, engine; init_db(); from sqlalchemy import inspect; print(sorted(inspect(engine).get_table_names()))"
```
Expected: `['agent_iterations', 'apps', 'builds', 'experiments']`

- [ ] **Step 3: 생성된 임시 DB 삭제 (seed로 재생성할 것)**

```bash
rm -f chaoslab.db
```

- [ ] **Step 4: 커밋**

```bash
git add app/db/models.py
git commit -m "✨ 도메인 모델 4종 (apps/builds/experiments/agent_iterations)"
```

### Task 4: Repository 4종 (TDD)

**Files:**
- Create: `app/db/repositories.py`
- Test: `tests/test_repositories.py`

- [ ] **Step 1: 실패 테스트 작성 — tests/test_repositories.py**

```python
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
```

- [ ] **Step 2: 실행 → 실패 확인**

Run: `pytest tests/test_repositories.py -v`
Expected: FAIL — `ModuleNotFoundError: app.db.repositories`.

- [ ] **Step 3: app/db/repositories.py 작성**

```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AgentIteration, App, Build, Experiment


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
```

- [ ] **Step 4: 실행 → 통과 확인**

Run: `pytest tests/test_repositories.py -v`
Expected: 3 PASS.

- [ ] **Step 5: 커밋**

```bash
git add app/db/repositories.py tests/test_repositories.py
git commit -m "✨ Repository 4종 + 테스트"
```

### Task 5: seed.py (mock 데이터)

**Files:**
- Create: `app/db/seed.py`
- Test: `tests/test_seed.py`

- [ ] **Step 1: 실패 테스트 작성 — tests/test_seed.py**

```python
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
```

- [ ] **Step 2: 실행 → 실패 확인**

Run: `pytest tests/test_seed.py -v`
Expected: FAIL — `ModuleNotFoundError: app.db.seed`.

- [ ] **Step 3: app/db/seed.py 작성**

```python
"""목업 화면을 채우는 대표 mock 데이터. `python -m app.db.seed`로 실행."""
from sqlalchemy.orm import Session

from app.db.database import SessionLocal, init_db
from app.db.repositories import (
    AppRepository,
    BuildRepository,
    ExperimentRepository,
    IterationRepository,
)


def seed_data(session: Session) -> None:
    apps = AppRepository(session)
    builds = BuildRepository(session)
    exps = ExperimentRepository(session)
    iters = IterationRepository(session)

    boutique = apps.create(
        name="online-boutique", repo_url="https://github.com/demo/boutique",
        framework="go", namespace="online-boutique",
        image_repo="123.dkr.ecr/boutique", current_sha="a1b2c3d4", status="healthy",
    )
    apps.create(
        name="payment-api", repo_url="https://github.com/demo/payment",
        framework="python", namespace="payment", current_sha="e5f6a7b8", status="healthy",
    )
    apps.create(
        name="order-worker", repo_url="https://github.com/demo/order",
        framework="node", namespace="order", current_sha="c9d0e1f2", status="degraded",
    )

    builds.create(app_id=boutique.id, status="succeeded", image_tag="a1b2c3d4",
                  workflow_name="build-boutique-a1b2c3d4")

    exp = exps.create(
        app_id=boutique.id, chaos_type="NetworkChaos",
        params={"action": "delay", "delay": "200ms", "duration": "5m"},
        status="running", baseline_r=0.42, r_index=0.65, target_r=0.7,
    )
    for i, (r, verdict) in enumerate([(0.51, "improved"), (0.59, "improved"), (0.65, "improved")], start=1):
        iters.create(
            experiment_id=exp.id, iteration=i,
            observer_output=f"iter {i}: p99 상승 감지", analyst_output="타임아웃 부족 추정",
            recommender_output="timeout 1s→3s, retry 2회", r_index=r, verdict=verdict,
            llm_cost_usd=0.012,
        )


def main() -> None:
    init_db()
    session = SessionLocal()
    try:
        if AppRepository(session).list_all():
            print("이미 seed 됨 — 건너뜀")
            return
        seed_data(session)
        print("seed 완료")
    finally:
        session.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 실행 → 통과 확인**

Run: `pytest tests/test_seed.py -v`
Expected: PASS.

- [ ] **Step 5: 로컬 DB seed 생성 + 확인**

Run: `python -m app.db.seed`
Expected: `seed 완료`. (`chaoslab.db` 생성 — gitignore됨)

- [ ] **Step 6: 커밋**

```bash
git add app/db/seed.py tests/test_seed.py
git commit -m "✨ seed.py — mock 데이터 + 테스트"
```

---

## Phase 2 — 서비스 레이어 (SOLID / TDD)

### Task 6: 외부 시스템 Protocol 인터페이스

**Files:**
- Create: `app/services/__init__.py` (빈 파일)
- Create: `app/services/interfaces.py`
- Create: `app/services/agent/__init__.py` (빈 파일 — Phase 3 자리)

- [ ] **Step 1: 빈 패키지 파일 생성**

```bash
touch app/services/__init__.py && mkdir -p app/services/agent && touch app/services/agent/__init__.py
```

- [ ] **Step 2: app/services/interfaces.py 작성**

```python
"""외부 시스템 계약. 라우터는 이 Protocol에만 의존(DIP). Slice 1=Stub, 이후=Real로 교체."""
from typing import Protocol


class BuilderService(Protocol):
    def trigger_build(self, app_id: int, git_sha: str) -> str:
        """빌드 트리거. workflow 이름 반환."""
        ...

    def build_status(self, workflow_name: str) -> str:
        """빌드 상태 문자열 반환 (pending/running/succeeded/failed)."""
        ...


class GitOpsService(Protocol):
    def bootstrap_app(self, name: str, repo_url: str, framework: str) -> None:
        """ArgoCD Application + values.yaml 커밋."""
        ...

    def update_image_tag(self, name: str, image_tag: str) -> None:
        ...


class ChaosService(Protocol):
    def inject(self, namespace: str, chaos_type: str, params: dict) -> str:
        """Chaos CRD 주입. CRD 이름 반환."""
        ...

    def delete(self, crd_name: str) -> None:
        ...


class PrometheusService(Protocol):
    def red_metrics(self, namespace: str) -> dict:
        """rate/error/duration(p99) 반환."""
        ...


class LokiService(Protocol):
    def tail(self, namespace: str, limit: int = 100) -> list[str]:
        ...


class K8sService(Protocol):
    def nodes(self) -> list[dict]:
        ...

    def pods(self, namespace: str) -> list[dict]:
        ...

    def components(self) -> list[dict]:
        """시스템 컴포넌트 상태 (Prometheus/Grafana/Loki/Chaos Mesh/ArgoCD)."""
        ...
```

- [ ] **Step 3: import 스모크**

Run: `python -c "from app.services import interfaces; print('ok')"`
Expected: `ok`

- [ ] **Step 4: 커밋**

```bash
git add app/services/__init__.py app/services/interfaces.py app/services/agent/__init__.py
git commit -m "✨ 외부 시스템 Protocol 인터페이스 6종"
```

### Task 7: Stub 구현 + 계약 테스트 (TDD)

**Files:**
- Create: `app/services/stubs.py`
- Test: `tests/test_stubs_contract.py`

- [ ] **Step 1: 실패 테스트 작성 — tests/test_stubs_contract.py**

```python
from app.services import interfaces, stubs


def test_stubs_satisfy_protocols():
    # 각 Stub이 대응 Protocol을 구조적으로 만족하는지 (isinstance + runtime_checkable 없이 호출로 검증)
    b: interfaces.BuilderService = stubs.StubBuilder()
    assert isinstance(b.trigger_build(1, "abc123"), str)
    assert b.build_status("wf") in {"pending", "running", "succeeded", "failed"}

    c: interfaces.ChaosService = stubs.StubChaos()
    assert isinstance(c.inject("ns", "NetworkChaos", {"delay": "1s"}), str)

    p: interfaces.PrometheusService = stubs.StubPrometheus()
    red = p.red_metrics("ns")
    assert {"rate", "error", "duration"} <= set(red)

    k: interfaces.K8sService = stubs.StubK8s()
    assert isinstance(k.nodes(), list)
    assert isinstance(k.components(), list)


def test_stub_loki_returns_lines():
    lines = stubs.StubLoki().tail("ns", limit=5)
    assert isinstance(lines, list) and len(lines) == 5
```

- [ ] **Step 2: 실행 → 실패 확인**

Run: `pytest tests/test_stubs_contract.py -v`
Expected: FAIL — `ModuleNotFoundError: app.services.stubs`.

- [ ] **Step 3: app/services/stubs.py 작성**

```python
"""Slice 1 스텁 — mock 데이터 반환. 외부 시스템 호출 없음. 이후 RealXxx로 교체."""


class StubBuilder:
    def trigger_build(self, app_id: int, git_sha: str) -> str:
        return f"build-{app_id}-{git_sha[:8]}"

    def build_status(self, workflow_name: str) -> str:
        return "succeeded"


class StubGitOps:
    def bootstrap_app(self, name: str, repo_url: str, framework: str) -> None:
        return None

    def update_image_tag(self, name: str, image_tag: str) -> None:
        return None


class StubChaos:
    def inject(self, namespace: str, chaos_type: str, params: dict) -> str:
        return f"{chaos_type.lower()}-{namespace}-stub"

    def delete(self, crd_name: str) -> None:
        return None


class StubPrometheus:
    def red_metrics(self, namespace: str) -> dict:
        return {"rate": 42.0, "error": 1.8, "duration": 380.0}


class StubLoki:
    def tail(self, namespace: str, limit: int = 100) -> list[str]:
        return [f"[{namespace}] mock log line {i}" for i in range(limit)]


class StubK8s:
    def nodes(self) -> list[dict]:
        return [
            {"name": "ng-ondemand-1", "type": "m5.large", "status": "Ready", "role": "platform"},
            {"name": "ng-spot-1", "type": "m5.xlarge", "status": "Ready", "role": "workload"},
            {"name": "ng-spot-2", "type": "m5.xlarge", "status": "Ready", "role": "workload"},
        ]

    def pods(self, namespace: str) -> list[dict]:
        return [
            {"name": "frontend-7d9", "namespace": namespace, "status": "Running", "restarts": 0},
            {"name": "cartservice-5fc", "namespace": namespace, "status": "Running", "restarts": 1},
        ]

    def components(self) -> list[dict]:
        names = ["Prometheus", "Grafana", "Loki", "Chaos Mesh", "ArgoCD"]
        return [{"name": n, "status": "Healthy"} for n in names]
```

- [ ] **Step 4: 실행 → 통과 확인**

Run: `pytest tests/test_stubs_contract.py -v`
Expected: 2 PASS.

- [ ] **Step 5: 커밋**

```bash
git add app/services/stubs.py tests/test_stubs_contract.py
git commit -m "✨ Stub 서비스 6종 + 계약 테스트"
```

### Task 8: deps.py — DI 와이어링

**Files:**
- Create: `app/deps.py`

- [ ] **Step 1: app/deps.py 작성**

```python
"""FastAPI Depends 제공자. 외부 시스템은 Stub을 주입(이후 Real로 한 줄 교체)."""
from app.db.database import get_session  # noqa: F401  — 라우터에서 재노출
from app.services import interfaces, stubs


def get_builder() -> interfaces.BuilderService:
    return stubs.StubBuilder()


def get_gitops() -> interfaces.GitOpsService:
    return stubs.StubGitOps()


def get_chaos() -> interfaces.ChaosService:
    return stubs.StubChaos()


def get_prometheus() -> interfaces.PrometheusService:
    return stubs.StubPrometheus()


def get_loki() -> interfaces.LokiService:
    return stubs.StubLoki()


def get_k8s() -> interfaces.K8sService:
    return stubs.StubK8s()
```

- [ ] **Step 2: import 스모크**

Run: `python -c "from app.deps import get_builder, get_k8s; print(get_k8s().components())"`
Expected: 컴포넌트 5개 리스트 출력.

- [ ] **Step 3: 커밋**

```bash
git add app/deps.py
git commit -m "✨ deps.py DI 와이어링 (Stub 주입)"
```

---

## Phase 3 — 렌더링 헬퍼 (TDD)

### Task 9: rendering.render_page — HX 분기

**Files:**
- Create: `app/rendering.py`
- Test: `tests/test_rendering.py`

설명: 페이지 템플릿은 `{% extends layout|default("base.html") %}`로 시작한다. `render_page`가 `HX-Request` 헤더 유무에 따라 `layout`을 `_partial.html`(셸 없음) 또는 `base.html`(풀 셸)로 주입한다. 이 분기 로직이 라우터마다 복붙되지 않게 한 곳에 둔다.

- [ ] **Step 1: 실패 테스트 작성 — tests/test_rendering.py**

```python
from app.rendering import resolve_layout


def test_resolve_layout_full_when_no_hx():
    assert resolve_layout({}) == "base.html"


def test_resolve_layout_partial_when_hx():
    assert resolve_layout({"hx-request": "true"}) == "_partial.html"
```

- [ ] **Step 2: 실행 → 실패 확인**

Run: `pytest tests/test_rendering.py -v`
Expected: FAIL — `ModuleNotFoundError: app.rendering`.

- [ ] **Step 3: app/rendering.py 작성**

```python
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def resolve_layout(headers: dict) -> str:
    """HX-Request(소문자 키 기준)면 셸 없는 부분 레이아웃, 아니면 풀 셸."""
    normalized = {k.lower(): v for k, v in headers.items()}
    return "_partial.html" if "hx-request" in normalized else "base.html"


def render_page(request: Request, template: str, context: dict | None = None):
    ctx = dict(context or {})
    ctx["request"] = request
    ctx["layout"] = resolve_layout(dict(request.headers))
    return templates.TemplateResponse(template, ctx)
```

- [ ] **Step 4: 실행 → 통과 확인**

Run: `pytest tests/test_rendering.py -v`
Expected: 2 PASS.

- [ ] **Step 5: 커밋**

```bash
git add app/rendering.py tests/test_rendering.py
git commit -m "✨ render_page — HX 풀/부분 렌더 분기"
```

---

## Phase 4 — 정적 자산 + 레이아웃 셸

### Task 10: tds.css 추출

**Files:**
- Create: `app/static/css/tds.css`

- [ ] **Step 1: 목업 CSS 추출**

`../Iac-aws/docs/graduation-dashboard-mockup.html`의 **18–296줄** `<style>` 내부 내용(`:root{...}`부터 `.tab-trigger.active .tab-count{...}`까지, `<style>`/`</style>` 태그 제외)을 그대로 `app/static/css/tds.css`로 복사한다. CSS 변수·컴포넌트 클래스 전부 포함. **내용 수정 없음** — 디자인 토큰 단일 출처.

- [ ] **Step 2: 추출 검증**

Run: `grep -c -- '--primary' app/static/css/tds.css && grep -c 'tds-card' app/static/css/tds.css`
Expected: 각각 1 이상.

- [ ] **Step 3: 커밋**

```bash
git add app/static/css/tds.css
git commit -m "🎨 TDS 디자인 토큰 CSS 추출"
```

### Task 11: app.js (테마/메뉴/탭/다이얼로그/차트)

**Files:**
- Create: `app/static/js/app.js`

설명: 목업의 **1999–2129줄** JS 로직을 포팅하되 — (1) `navigate()` 페이지전환은 HTMX가 대체하므로 **제거**, (2) 탭/유저메뉴/테마/다이얼로그는 그대로, (3) 차트 init은 `initCharts()`로 묶고 `DOMContentLoaded` + `htmx:afterSwap`에서 재실행(HTMX 스왑 후에도 차트가 그려지도록). 탭은 이벤트 위임으로 `document`에 1회 바인딩.

- [ ] **Step 1: app/static/js/app.js 작성**

```javascript
// ============== 유저 메뉴 ==============
document.addEventListener('click', (e) => {
  const btn = document.getElementById('userMenuBtn');
  const menu = document.getElementById('userMenu');
  if (!menu) return;
  if (btn && btn.contains(e.target)) { e.stopPropagation(); menu.classList.toggle('open'); return; }
  if (!menu.contains(e.target)) menu.classList.remove('open');
});

// ============== 테마 토글 ==============
document.addEventListener('click', (e) => {
  const t = e.target.closest && e.target.closest('#themeToggleBtn');
  if (!t) return;
  e.stopPropagation();
  const cur = document.documentElement.getAttribute('data-theme');
  const next = cur === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  const icon = document.getElementById('themeIcon');
  const label = document.getElementById('themeLabel');
  if (icon) icon.setAttribute('icon', next === 'dark' ? 'solar:sun-bold' : 'solar:moon-bold');
  if (label) label.textContent = next === 'dark' ? '라이트 모드' : '다크 모드';
  Object.values(window._charts || {}).forEach(c => c && c.update());
});

// ============== 탭 전환 (이벤트 위임) ==============
document.addEventListener('click', (e) => {
  const t = e.target.closest && e.target.closest('[data-tab-trigger]');
  if (!t) return;
  const group = t.dataset.tabGroup;
  const target = t.dataset.tabTrigger;
  document.querySelectorAll(`[data-tab-trigger][data-tab-group="${group}"]`).forEach(el => el.classList.remove('active'));
  t.classList.add('active');
  document.querySelectorAll(`[data-tab-content][data-tab-group="${group}"]`).forEach(el => el.classList.remove('active'));
  const content = document.querySelector(`[data-tab-content="${target}"][data-tab-group="${group}"]`);
  if (content) content.classList.add('active');
});

// ============== 다이얼로그 ==============
function openDialog(name) { const d = document.getElementById(`dialog-${name}`); if (d) d.classList.add('open'); }
function closeDialog(name) { const d = document.getElementById(`dialog-${name}`); if (d) d.classList.remove('open'); }
document.addEventListener('click', (e) => {
  if (e.target.classList && e.target.classList.contains('dialog-backdrop')) e.target.classList.remove('open');
});

// ============== Chart.js ==============
const tdsTextColor = () => getComputedStyle(document.documentElement).getPropertyValue('--muted-foreground').trim();
const tdsBorderColor = () => getComputedStyle(document.documentElement).getPropertyValue('--border').trim();

function chartCommon() {
  return {
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      x: { grid: { display: false }, ticks: { color: tdsTextColor(), font: { size: 10 } } },
      y: { grid: { color: tdsBorderColor() }, ticks: { color: tdsTextColor(), font: { size: 10 } } }
    }
  };
}

function makeTimeSeries(canvasId, color, base, variance, isStep = false) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;
  const labels = Array.from({ length: 30 }, (_, i) => `${30 - i}m`).reverse();
  const data = labels.map((_, i) => {
    if (i < 5) return base * 0.3;
    if (i < 18) return base + (Math.random() - 0.5) * variance;
    return base * 0.4 + (Math.random() - 0.5) * (variance * 0.3);
  });
  const cc = chartCommon();
  window._charts[canvasId] = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets: [{ data, borderColor: color, backgroundColor: color + '22', fill: true, tension: isStep ? 0 : 0.4, stepped: isStep, pointRadius: 0, borderWidth: 2 }] },
    options: { ...cc, scales: { ...cc.scales, x: { display: false } } }
  });
}

function initCharts() {
  // 기존 차트 파기 (HTMX 재스왑 대비)
  Object.values(window._charts || {}).forEach(c => c && c.destroy());
  window._charts = {};
  const cc = chartCommon();

  const rIdx = document.getElementById('rIndexChart');
  if (rIdx) {
    window._charts.rIndex = new Chart(rIdx, {
      type: 'line',
      data: { labels: ['iter 1', 'iter 2', 'iter 3', 'iter 4'], datasets: [{ data: [0.42, 0.51, 0.59, 0.65], borderColor: '#004b3e', backgroundColor: 'rgba(0,75,62,0.15)', fill: true, tension: 0.3, pointRadius: 5, pointBackgroundColor: '#004b3e', borderWidth: 3 }] },
      options: { ...cc, scales: { ...cc.scales, y: { ...cc.scales.y, min: 0.3, max: 0.8 } } }
    });
  }

  const agentR = document.getElementById('agentRChart2');
  if (agentR) {
    window._charts.agentR2 = new Chart(agentR, {
      type: 'line',
      data: { labels: ['iter 1', 'iter 2', 'iter 3', 'iter 4', 'iter 5', 'iter 6', 'iter 7'], datasets: [
        { label: '실측', data: [0.42, 0.51, 0.59, 0.65, null, null, null], borderColor: '#004b3e', backgroundColor: 'rgba(0,75,62,0.2)', fill: true, tension: 0.3, pointRadius: 6, pointBackgroundColor: '#004b3e', borderWidth: 3 },
        { label: '예측', data: [null, null, null, 0.65, 0.69, 0.71, 0.73], borderColor: '#0d9488', borderDash: [6, 6], tension: 0.3, pointRadius: 4, borderWidth: 2 },
        { label: '목표', data: [0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7], borderColor: '#dc2626', borderDash: [3, 3], tension: 0, pointRadius: 0, borderWidth: 1.5 }
      ] },
      options: { ...cc, plugins: { legend: { display: true, position: 'bottom', labels: { font: { size: 10 }, color: tdsTextColor() } } }, scales: { ...cc.scales, y: { ...cc.scales.y, min: 0.3, max: 0.85 } } }
    });
  }

  makeTimeSeries('metricRate2', '#004b3e', 42, 8);
  makeTimeSeries('metricError2', '#dc2626', 1.8, 1.5);
  makeTimeSeries('metricLatency2', '#f59e0b', 380, 80);

  const pods = document.getElementById('metricPods2');
  if (pods) {
    const labels = Array.from({ length: 30 }, (_, i) => `${30 - i}m`).reverse();
    window._charts.pods2 = new Chart(pods, {
      type: 'line',
      data: { labels, datasets: [{ data: labels.map(() => 2), borderColor: '#16a34a', backgroundColor: 'rgba(22,163,74,0.15)', fill: true, stepped: true, pointRadius: 0, borderWidth: 2 }] },
      options: { ...cc, scales: { ...cc.scales, x: { display: false }, y: { ...cc.scales.y, min: 0, max: 3 } } }
    });
  }
}

window._charts = {};
document.addEventListener('DOMContentLoaded', initCharts);
document.body.addEventListener('htmx:afterSwap', initCharts);
```

- [ ] **Step 2: 커밋**

```bash
git add app/static/js/app.js
git commit -m "✨ app.js — 테마/메뉴/탭/다이얼로그/차트 (HTMX 재초기화)"
```

### Task 12: base.html + _partial.html + _sidebar.html + 매크로

**Files:**
- Create: `app/templates/base.html`
- Create: `app/templates/_partial.html`
- Create: `app/templates/partials/_sidebar.html`
- Create: `app/templates/macros/components.html`

- [ ] **Step 1: _partial.html (HX용 빈 레이아웃)**

```html
{% block content %}{% endblock %}
```

- [ ] **Step 2: macros/components.html — 반복 컴포넌트만**

```html
{% macro badge(text, variant="muted") %}
<span class="tds-badge badge-{{ variant }}">{{ text }}</span>
{% endmacro %}

{% macro kpi_card(icon, label, value, delta=None, delta_variant="success") %}
<div class="tds-card p-5 hover-lift">
  <div class="flex items-center justify-between mb-3">
    <iconify-icon icon="{{ icon }}" width="22" style="color: var(--primary);"></iconify-icon>
    {% if delta %}<span class="tds-badge badge-{{ delta_variant }}">{{ delta }}</span>{% endif %}
  </div>
  <div class="text-2xl font-extrabold">{{ value }}</div>
  <div class="text-xs mt-1" style="color: var(--muted-foreground);">{{ label }}</div>
</div>
{% endmacro %}

{% macro app_card(app) %}
<div class="tds-card p-5 hover-lift">
  <div class="flex items-center justify-between mb-2">
    <div class="font-bold">{{ app.name }}</div>
    {{ badge(app.status, "success" if app.status == "healthy" else "warning") }}
  </div>
  <div class="text-xs mono" style="color: var(--muted-foreground);">{{ app.framework }} · {{ app.namespace }}</div>
  <div class="text-xs mono mt-1" style="color: var(--muted-foreground);">{{ app.current_sha[:8] }}</div>
</div>
{% endmacro %}

{% macro experiment_row(exp) %}
<tr class="border-b" style="border-color: var(--border);">
  <td class="py-3 px-2 font-semibold">#{{ exp.id }}</td>
  <td class="py-3 px-2">{{ badge(exp.chaos_type, "info") }}</td>
  <td class="py-3 px-2">{{ badge(exp.status, "warning" if exp.status == "running" else "success") }}</td>
  <td class="py-3 px-2 mono">{{ "%.2f"|format(exp.r_index) if exp.r_index is not none else "—" }}</td>
</tr>
{% endmacro %}
```

- [ ] **Step 3: partials/_sidebar.html — nav 1곳 정의**

목업의 **305–396줄**(`<aside ...>`부터 `</aside>`까지) 구조를 그대로 옮기되, 각 `data-nav` 항목을 HTMX 링크로 변환한다. 변환 규칙:
- `<div class="sidebar-nav-item ..." data-nav="X">` → `<a hx-get="{{ url }}" hx-target="#main-content" hx-swap="innerHTML" hx-push-url="true" class="sidebar-nav-item {{ 'active' if active_nav == 'X' }}">`
- 매핑: dashboard→`/`, apps→`/apps`, experiments→`/experiments`, infra→`/infra`, settings→`/settings`.
- 유저 프로필/테마 토글/시스템 상태 블록은 그대로 유지(`id="userMenuBtn"`, `id="themeToggleBtn"` 등 ID 보존 — app.js가 참조).

```html
<aside class="w-64 shrink-0 flex flex-col border-r" style="background: var(--sidebar); border-color: var(--sidebar-border);">
  <div class="px-4 pt-5 pb-5 flex items-center gap-2.5">
    <div class="w-9 h-9 rounded-xl flex items-center justify-center" style="background: var(--primary);">
      <iconify-icon icon="solar:atom-bold" style="color: white;" width="22"></iconify-icon>
    </div>
    <div class="font-extrabold text-base" style="color: var(--sidebar-foreground);">ChaosLab</div>
  </div>

  <nav class="flex-1 overflow-y-auto px-3 pb-4 space-y-0.5">
    <a hx-get="/" hx-target="#main-content" hx-swap="innerHTML" hx-push-url="true" class="sidebar-nav-item {{ 'active' if active_nav == 'dashboard' }}">
      <iconify-icon icon="solar:widget-bold" width="18"></iconify-icon><span class="text-sm">대시보드</span>
    </a>
    <a hx-get="/apps" hx-target="#main-content" hx-swap="innerHTML" hx-push-url="true" class="sidebar-nav-item {{ 'active' if active_nav == 'apps' }}">
      <iconify-icon icon="solar:server-square-bold" width="18"></iconify-icon><span class="text-sm flex-1">Apps</span>
      <span class="text-[11px] font-bold px-1.5 py-0.5 rounded-md" style="background: var(--muted); color: var(--muted-foreground);">{{ app_count }}</span>
    </a>
    <a hx-get="/experiments" hx-target="#main-content" hx-swap="innerHTML" hx-push-url="true" class="sidebar-nav-item {{ 'active' if active_nav == 'experiments' }}">
      <iconify-icon icon="solar:bug-bold" width="18"></iconify-icon><span class="text-sm flex-1">카오스 테스트</span>
      <span class="w-2 h-2 rounded-full pulse-dot" style="background: var(--danger);"></span>
    </a>
    <a hx-get="/infra" hx-target="#main-content" hx-swap="innerHTML" hx-push-url="true" class="sidebar-nav-item {{ 'active' if active_nav == 'infra' }}">
      <iconify-icon icon="logos:aws" width="18"></iconify-icon><span class="text-sm flex-1">EKS 인프라</span>
    </a>
    <a hx-get="/settings" hx-target="#main-content" hx-swap="innerHTML" hx-push-url="true" class="sidebar-nav-item {{ 'active' if active_nav == 'settings' }}">
      <iconify-icon icon="solar:settings-bold" width="18"></iconify-icon><span class="text-sm flex-1">설정</span>
    </a>
  </nav>

  <div class="mx-4 mb-3 p-2.5 rounded-xl" style="background: var(--sidebar-accent);">
    <div class="flex items-center justify-between text-[11px]">
      <div class="flex items-center gap-1.5" style="color: var(--sidebar-foreground);">
        <span class="w-1.5 h-1.5 rounded-full" style="background: var(--success);"></span>
        <span class="font-semibold">EKS 정상</span>
      </div>
      <span style="color: var(--sidebar-muted);">5/5</span>
    </div>
  </div>

  <div class="relative px-3 pb-4 border-t pt-3" style="border-color: var(--sidebar-border);">
    <button id="userMenuBtn" class="w-full flex items-center gap-3 px-2 py-1.5 rounded-xl hover:bg-sidebar-accent">
      <div class="w-9 h-9 rounded-full flex items-center justify-center font-extrabold text-white" style="background: linear-gradient(135deg, #004b3e, #0d9488);">태</div>
      <div class="flex-1 text-left min-w-0">
        <div class="text-sm font-bold truncate" style="color: var(--sidebar-foreground);">박태윤</div>
        <div class="text-[11px] truncate" style="color: var(--sidebar-muted);">taeyun02@treenod.com</div>
      </div>
      <iconify-icon icon="lucide:chevron-up" width="14" style="color: var(--sidebar-muted);"></iconify-icon>
    </button>
    <div id="userMenu" class="user-menu mx-3">
      <div class="user-menu-item" id="themeToggleBtn">
        <iconify-icon id="themeIcon" icon="solar:moon-bold" width="16"></iconify-icon>
        <span id="themeLabel">다크 모드</span>
      </div>
      <div class="user-menu-item" style="color: var(--danger);">
        <iconify-icon icon="solar:logout-3-bold" width="16"></iconify-icon>로그아웃
      </div>
    </div>
  </div>
</aside>
```

- [ ] **Step 4: base.html — 셸**

```html
<!DOCTYPE html>
<html lang="ko" data-theme="light">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>ChaosLab — AI 카오스 자동 개선 플랫폼</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://code.iconify.design/iconify-icon/2.1.0/iconify-icon.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <script src="https://unpkg.com/htmx.org@1.9.12"></script>
  <link rel="stylesheet" href="/static/css/tds.css" />
</head>
<body>
  <div class="flex h-screen overflow-hidden">
    {% include "partials/_sidebar.html" %}
    <main class="flex-1 overflow-y-auto">
      <div id="main-content">
        {% block content %}{% endblock %}
      </div>
    </main>
  </div>
  <script src="/static/js/app.js"></script>
</body>
</html>
```

- [ ] **Step 5: 매크로 문법 스모크 (렌더 오류 없는지)**

Run:
```bash
python -c "from app.rendering import templates; templates.get_template('macros/components.html'); templates.get_template('base.html'); print('templates ok')"
```
Expected: `templates ok`

- [ ] **Step 6: 커밋**

```bash
git add app/templates/base.html app/templates/_partial.html app/templates/partials/_sidebar.html app/templates/macros/components.html
git commit -m "🎨 레이아웃 셸 + 사이드바(HTMX) + 컴포넌트 매크로"
```

---

## Phase 5 — 페이지 라우트 + 포팅 (스모크 테스트)

> 공통 패턴: 각 페이지 템플릿 `app/templates/pages/<name>.html`은 `{% extends layout|default("base.html") %}`로 시작하고 `{% block content %}`에 목업 해당 `data-page` 섹션을 포팅한다. 라우터는 `render_page`로 응답하며 `active_nav`, `app_count`, 그리고 필요한 mock 데이터(repository/stub)를 context로 넘긴다. 포팅 시 `data-page` 래퍼 div는 제거(블록이 곧 콘텐츠), 탭/다이얼로그 마크업의 `data-tab-*`/`id="dialog-*"`/`onclick="openDialog(...)"`는 보존(app.js가 처리).

### Task 13: pages 라우터 + 대시보드

**Files:**
- Create: `app/routers/__init__.py` (빈 파일)
- Create: `app/routers/pages.py`
- Create: `app/templates/pages/dashboard.html`
- Modify: `app/main.py` (라우터/정적 마운트, startup seed)
- Test: `tests/test_pages.py`

- [ ] **Step 1: 실패 테스트 추가 — tests/test_pages.py (기존 파일에 append)**

```python
def test_dashboard_full_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "ChaosLab" in resp.text          # base 셸 포함
    assert "id=\"main-content\"" in resp.text


def test_dashboard_partial_when_hx(client):
    resp = client.get("/", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    assert "<!DOCTYPE html>" not in resp.text  # 셸 없음 (부분만)
```

- [ ] **Step 2: 빈 `app/routers/__init__.py` 생성**

```bash
touch app/routers/__init__.py
```

- [ ] **Step 3: app/templates/pages/dashboard.html 작성**

목업 **404–647줄**(`<div data-page="dashboard" ...>` 내부)을 `{% block content %}`로 포팅. 래퍼 div 제거. KPI 카드 영역은 `components.html`의 `kpi_card` 매크로로 치환 가능(반복되면). R지수 차트 `<canvas id="rIndexChart">`는 보존(app.js가 그림). 골격이므로 정적 mock 텍스트 유지 OK.

```html
{% extends layout|default("base.html") %}
{% from "macros/components.html" import kpi_card, badge %}
{% block content %}
<div class="p-6 space-y-6">
  <div>
    <h1 class="text-2xl font-extrabold">대시보드</h1>
    <p class="text-sm" style="color: var(--muted-foreground);">카오스 테스트 현황 한눈에 보기</p>
  </div>
  <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
    {{ kpi_card("solar:server-square-bold", "등록 앱", app_count, "정상", "success") }}
    {{ kpi_card("solar:bug-bold", "진행중 실험", running_count, "running", "warning") }}
    {{ kpi_card("solar:chart-bold", "최근 R 지수", latest_r, "▲", "success") }}
    {{ kpi_card("solar:cpu-bolt-bold", "EKS 노드", node_count, "Ready", "success") }}
  </div>
  <div class="tds-card p-6">
    <div class="font-bold mb-4">R 지수 추이</div>
    <div class="chart-box"><canvas id="rIndexChart"></canvas></div>
  </div>
</div>
{% endblock %}
```
> 참고: 목업의 진행중 실험/AI분석 요약/최근활동/시스템상태 블록도 같은 방식으로 `data-page` 섹션에서 추가 포팅 가능. Slice 1 최소 기준은 위 구조(헤더+KPI+차트)이며, 목업 충실도를 높이려면 해당 섹션 마크업을 그대로 더 옮긴다.

- [ ] **Step 4: app/routers/pages.py 작성**

```python
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db.database import get_session
from app.db.repositories import AppRepository, ExperimentRepository
from app.deps import get_k8s
from app.rendering import render_page
from app.services import interfaces

router = APIRouter()


def _common(session: Session) -> dict:
    return {"app_count": len(AppRepository(session).list_all())}


@router.get("/")
def dashboard(request: Request, session: Session = Depends(get_session), k8s: interfaces.K8sService = Depends(get_k8s)):
    apps = AppRepository(session).list_all()
    exps = ExperimentRepository(session).list_all()
    running = [e for e in exps if e.status == "running"]
    latest_r = next((f"{e.r_index:.2f}" for e in exps if e.r_index is not None), "—")
    ctx = {
        "active_nav": "dashboard",
        "app_count": len(apps),
        "running_count": len(running),
        "latest_r": latest_r,
        "node_count": len(k8s.nodes()),
    }
    return render_page(request, "pages/dashboard.html", ctx)
```

- [ ] **Step 5: app/main.py 수정 — 라우터/정적 마운트 + startup seed**

```python
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db.database import SessionLocal, init_db
from app.db.repositories import AppRepository
from app.db.seed import seed_data
from app.routers import pages

app = FastAPI(title=settings.app_name)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
app.include_router(pages.router)


@app.on_event("startup")
def _startup():
    init_db()
    session = SessionLocal()
    try:
        if not AppRepository(session).list_all():
            seed_data(session)
    finally:
        session.close()


@app.get("/healthz")
def healthz():
    return {"status": "ok", "app": settings.app_name}
```

- [ ] **Step 6: 테스트 실행 → 통과 확인**

Run: `pytest tests/test_pages.py -v`
Expected: 모두 PASS (`test_healthz`, `test_dashboard_full_page`, `test_dashboard_partial_when_hx`).

- [ ] **Step 7: 커밋**

```bash
git add app/routers/__init__.py app/routers/pages.py app/templates/pages/dashboard.html app/main.py tests/test_pages.py
git commit -m "✨ pages 라우터 + 대시보드 (HTMX 풀/부분)"
```

### Task 14: /apps 페이지

**Files:**
- Create: `app/templates/pages/apps.html`
- Modify: `app/routers/pages.py` (라우트 추가)
- Test: `tests/test_pages.py`

- [ ] **Step 1: 실패 테스트 추가**

```python
def test_apps_page_lists_seeded(client):
    resp = client.get("/apps")
    assert resp.status_code == 200
    assert "online-boutique" in resp.text   # seed된 앱 이름
    assert "새 앱" in resp.text or "새 앱 등록" in resp.text
```

- [ ] **Step 2: 실행 → 실패 확인**

Run: `pytest tests/test_pages.py::test_apps_page_lists_seeded -v`
Expected: FAIL (404 — 라우트 없음).

- [ ] **Step 3: app/templates/pages/apps.html 작성**

목업 **648–834줄**을 포팅. 앱 카드 목록은 `app_card` 매크로로 `apps` 반복 렌더. "새 앱" 모달(`id="dialog-newApp"`, `onclick="openDialog('newApp')"`)은 보존.

```html
{% extends layout|default("base.html") %}
{% from "macros/components.html" import app_card %}
{% block content %}
<div class="p-6 space-y-6">
  <div class="flex items-center justify-between">
    <div>
      <h1 class="text-2xl font-extrabold">Apps</h1>
      <p class="text-sm" style="color: var(--muted-foreground);">GitOps로 배포되는 카오스 테스트 대상</p>
    </div>
    <button class="tds-btn-primary text-sm" onclick="openDialog('newApp')">
      <iconify-icon icon="solar:add-circle-bold" width="16"></iconify-icon>새 앱 등록
    </button>
  </div>
  <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
    {% for app in apps %}{{ app_card(app) }}{% endfor %}
  </div>
</div>
<div id="dialog-newApp" class="dialog-backdrop">
  <div class="dialog-card">
    <div class="px-6 py-4 border-t-0 font-bold text-lg">새 앱 등록</div>
    <div class="px-6 py-4 space-y-3">
      <input class="tds-input" placeholder="Git 레포 URL" />
      <input class="tds-input" placeholder="프레임워크 (go/python/node)" />
    </div>
    <div class="px-6 py-4 flex gap-2 justify-end border-t" style="border-color: var(--border);">
      <button class="tds-btn-muted text-sm" onclick="closeDialog('newApp')">닫기</button>
      <button class="tds-btn-primary text-sm">등록</button>
    </div>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 4: app/routers/pages.py에 라우트 추가**

```python
@router.get("/apps")
def apps_page(request: Request, session: Session = Depends(get_session)):
    apps = AppRepository(session).list_all()
    ctx = {"active_nav": "apps", "app_count": len(apps), "apps": apps}
    return render_page(request, "pages/apps.html", ctx)
```

- [ ] **Step 5: 실행 → 통과 확인**

Run: `pytest tests/test_pages.py::test_apps_page_lists_seeded -v`
Expected: PASS.

- [ ] **Step 6: 커밋**

```bash
git add app/templates/pages/apps.html app/routers/pages.py tests/test_pages.py
git commit -m "✨ /apps 페이지 (앱 카드 + 새 앱 모달)"
```

### Task 15: /experiments 페이지

**Files:**
- Create: `app/templates/pages/experiments.html`
- Modify: `app/routers/pages.py`
- Test: `tests/test_pages.py`

- [ ] **Step 1: 실패 테스트 추가**

```python
def test_experiments_page(client):
    resp = client.get("/experiments")
    assert resp.status_code == 200
    assert "NetworkChaos" in resp.text       # seed된 실험
    assert "카오스 테스트" in resp.text
```

- [ ] **Step 2: 실행 → 실패 확인**

Run: `pytest tests/test_pages.py::test_experiments_page -v`
Expected: FAIL (404).

- [ ] **Step 3: app/templates/pages/experiments.html 작성**

목업 **835–1056줄** 포팅. 실험 목록 테이블은 `experiment_row` 매크로로 `experiments` 반복. 행 클릭/상세 링크는 `hx-get="/experiments/{{ exp.id }}"` `hx-target="#main-content"` `hx-push-url="true"`. "새 실험" 모달(`id="dialog-newExperiment"`) 보존.

```html
{% extends layout|default("base.html") %}
{% from "macros/components.html" import experiment_row %}
{% block content %}
<div class="p-6 space-y-6">
  <div class="flex items-center justify-between">
    <h1 class="text-2xl font-extrabold">카오스 테스트</h1>
    <button class="tds-btn-primary text-sm" onclick="openDialog('newExperiment')">
      <iconify-icon icon="solar:bug-bold" width="16"></iconify-icon>새 실험
    </button>
  </div>
  <div class="tds-card p-6 overflow-x-auto">
    <table class="w-full text-sm">
      <thead><tr class="text-left" style="color: var(--muted-foreground);">
        <th class="py-2 px-2">ID</th><th class="py-2 px-2">종류</th><th class="py-2 px-2">상태</th><th class="py-2 px-2">R 지수</th>
      </tr></thead>
      <tbody>
        {% for exp in experiments %}
        <tr class="border-b cursor-pointer hover:bg-sidebar-accent" style="border-color: var(--border);"
            hx-get="/experiments/{{ exp.id }}" hx-target="#main-content" hx-swap="innerHTML" hx-push-url="true">
          <td class="py-3 px-2 font-semibold">#{{ exp.id }}</td>
          <td class="py-3 px-2"><span class="tds-badge badge-info">{{ exp.chaos_type }}</span></td>
          <td class="py-3 px-2"><span class="tds-badge badge-warning">{{ exp.status }}</span></td>
          <td class="py-3 px-2 mono">{{ "%.2f"|format(exp.r_index) if exp.r_index is not none else "—" }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
<div id="dialog-newExperiment" class="dialog-backdrop">
  <div class="dialog-card">
    <div class="px-6 py-4 font-bold text-lg">새 카오스 실험</div>
    <div class="px-6 py-4 space-y-3">
      <input class="tds-input" placeholder="대상 앱" />
      <input class="tds-input" placeholder="카오스 종류 (Network/Pod/Stress)" />
    </div>
    <div class="px-6 py-4 flex gap-2 justify-end border-t" style="border-color: var(--border);">
      <button class="tds-btn-muted text-sm" onclick="closeDialog('newExperiment')">닫기</button>
      <button class="tds-btn-primary text-sm">실험 시작할게요</button>
    </div>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 4: 라우트 추가 (app/routers/pages.py)**

```python
@router.get("/experiments")
def experiments_page(request: Request, session: Session = Depends(get_session)):
    apps = AppRepository(session).list_all()
    exps = ExperimentRepository(session).list_all()
    ctx = {"active_nav": "experiments", "app_count": len(apps), "experiments": exps}
    return render_page(request, "pages/experiments.html", ctx)
```

- [ ] **Step 5: 실행 → 통과 확인**

Run: `pytest tests/test_pages.py::test_experiments_page -v`
Expected: PASS.

- [ ] **Step 6: 커밋**

```bash
git add app/templates/pages/experiments.html app/routers/pages.py tests/test_pages.py
git commit -m "✨ /experiments 페이지 (목록 + 새 실험 모달)"
```

### Task 16: /experiments/{id} 상세 (5탭)

**Files:**
- Create: `app/templates/pages/experiment_detail.html`
- Modify: `app/routers/pages.py`
- Test: `tests/test_pages.py`

- [ ] **Step 1: 실패 테스트 추가**

```python
def test_experiment_detail(client):
    resp = client.get("/experiments/1")
    assert resp.status_code == 200
    assert "개요" in resp.text and "메트릭" in resp.text and "AI 루프" in resp.text


def test_experiment_detail_404(client):
    resp = client.get("/experiments/99999")
    assert resp.status_code == 404
```

- [ ] **Step 2: 실행 → 실패 확인**

Run: `pytest tests/test_pages.py -k experiment_detail -v`
Expected: FAIL (404 for both — 라우트 없음).

- [ ] **Step 3: app/templates/pages/experiment_detail.html 작성**

목업 **1057–1634줄** 포팅. 5탭(`data-tab-trigger`/`data-tab-content`, group="expDetail") + 차트 canvas(`agentRChart2`, `metricRate2`, `metricError2`, `metricLatency2`, `metricPods2`) 보존. iteration 목록은 `iterations` 반복.

```html
{% extends layout|default("base.html") %}
{% block content %}
<div class="p-6 space-y-6">
  <div>
    <h1 class="text-2xl font-extrabold">실험 #{{ exp.id }} — {{ exp.chaos_type }}</h1>
    <p class="text-sm" style="color: var(--muted-foreground);">대상: {{ exp.app.name }} · 상태: {{ exp.status }}</p>
  </div>

  <div class="tabs-list">
    <div class="tab-trigger active" data-tab-trigger="overview" data-tab-group="expDetail">개요</div>
    <div class="tab-trigger" data-tab-trigger="metrics" data-tab-group="expDetail">메트릭</div>
    <div class="tab-trigger" data-tab-trigger="ai" data-tab-group="expDetail">AI 루프</div>
    <div class="tab-trigger" data-tab-trigger="improve" data-tab-group="expDetail">개선 포인트</div>
    <div class="tab-trigger" data-tab-trigger="logs" data-tab-group="expDetail">로그</div>
  </div>

  <div data-tab-content="overview" data-tab-group="expDetail" class="active">
    <div class="tds-card p-6">
      <div class="font-bold mb-2">개요</div>
      <div class="text-sm mono">params: {{ exp.params }}</div>
      <div class="text-sm mt-2">baseline R: {{ exp.baseline_r }} → 현재 R: {{ exp.r_index }} (목표 {{ exp.target_r }})</div>
    </div>
  </div>

  <div data-tab-content="metrics" data-tab-group="expDetail">
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div class="tds-card p-5"><div class="text-sm font-bold mb-2">Rate</div><div class="chart-box-sm"><canvas id="metricRate2"></canvas></div></div>
      <div class="tds-card p-5"><div class="text-sm font-bold mb-2">Errors</div><div class="chart-box-sm"><canvas id="metricError2"></canvas></div></div>
      <div class="tds-card p-5"><div class="text-sm font-bold mb-2">Latency p99</div><div class="chart-box-sm"><canvas id="metricLatency2"></canvas></div></div>
      <div class="tds-card p-5"><div class="text-sm font-bold mb-2">Pods</div><div class="chart-box-sm"><canvas id="metricPods2"></canvas></div></div>
    </div>
  </div>

  <div data-tab-content="ai" data-tab-group="expDetail">
    <div class="tds-card p-6 mb-4">
      <div class="font-bold mb-4">R 지수 (실측 vs 예측 vs 목표)</div>
      <div class="chart-box"><canvas id="agentRChart2"></canvas></div>
    </div>
    <div class="space-y-2">
      {% for it in iterations %}
      <div class="tds-card p-4">
        <div class="font-bold text-sm">Iteration {{ it.iteration }} · R={{ "%.2f"|format(it.r_index) if it.r_index is not none else "—" }} · {{ it.verdict }}</div>
        <div class="text-xs mt-1" style="color: var(--muted-foreground);">👁️ {{ it.observer_output }} · 🧠 {{ it.analyst_output }} · 💡 {{ it.recommender_output }}</div>
      </div>
      {% endfor %}
    </div>
  </div>

  <div data-tab-content="improve" data-tab-group="expDetail">
    <div class="tds-card p-6"><div class="font-bold mb-2">개선 포인트 (Phase 3)</div><pre class="mono text-xs">timeout: 1s → 3s\nretry: 2회</pre></div>
  </div>

  <div data-tab-content="logs" data-tab-group="expDetail">
    <div class="tds-card p-6"><pre class="mono text-xs" style="color: var(--muted-foreground);">{% for line in logs %}{{ line }}\n{% endfor %}</pre></div>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 4: 라우트 추가 (app/routers/pages.py)**

```python
from fastapi import HTTPException

from app.db.repositories import IterationRepository
from app.deps import get_loki


@router.get("/experiments/{exp_id}")
def experiment_detail(request: Request, exp_id: int, session: Session = Depends(get_session), loki: interfaces.LokiService = Depends(get_loki)):
    exp = ExperimentRepository(session).get(exp_id)
    if exp is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    iterations = IterationRepository(session).list_for_experiment(exp_id)
    ctx = {
        "active_nav": "experiments",
        "app_count": len(AppRepository(session).list_all()),
        "exp": exp,
        "iterations": iterations,
        "logs": loki.tail(exp.app.namespace, limit=20),
    }
    return render_page(request, "pages/experiment_detail.html", ctx)
```

- [ ] **Step 5: 실행 → 통과 확인**

Run: `pytest tests/test_pages.py -k experiment_detail -v`
Expected: 2 PASS.

- [ ] **Step 6: 커밋**

```bash
git add app/templates/pages/experiment_detail.html app/routers/pages.py tests/test_pages.py
git commit -m "✨ /experiments/{id} 상세 5탭 + 차트/로그"
```

### Task 17: /infra 페이지 (조회 전용)

**Files:**
- Create: `app/templates/pages/infra.html`
- Modify: `app/routers/pages.py`
- Test: `tests/test_pages.py`

- [ ] **Step 1: 실패 테스트 추가**

```python
def test_infra_page(client):
    resp = client.get("/infra")
    assert resp.status_code == 200
    assert "Prometheus" in resp.text and "ng-spot-1" in resp.text
```

- [ ] **Step 2: 실행 → 실패 확인**

Run: `pytest tests/test_pages.py::test_infra_page -v`
Expected: FAIL (404).

- [ ] **Step 3: app/templates/pages/infra.html 작성**

목업 **1635–1749줄** 포팅. 노드/컴포넌트는 `nodes`/`components` 반복. 조회 전용(액션 버튼 없음).

```html
{% extends layout|default("base.html") %}
{% block content %}
<div class="p-6 space-y-6">
  <div>
    <h1 class="text-2xl font-extrabold">EKS 인프라</h1>
    <p class="text-sm" style="color: var(--muted-foreground);">클러스터 상태 (조회 전용)</p>
  </div>
  <div class="tds-card p-6">
    <div class="font-bold mb-4">노드</div>
    <div class="space-y-2">
      {% for n in nodes %}
      <div class="flex items-center justify-between text-sm border-b pb-2" style="border-color: var(--border);">
        <span class="mono">{{ n.name }} <span style="color: var(--muted-foreground);">({{ n.type }})</span></span>
        <span class="tds-badge badge-success">{{ n.status }}</span>
      </div>
      {% endfor %}
    </div>
  </div>
  <div class="tds-card p-6">
    <div class="font-bold mb-4">시스템 컴포넌트</div>
    <div class="grid grid-cols-2 md:grid-cols-5 gap-3">
      {% for c in components %}
      <div class="p-3 rounded-xl text-center" style="background: var(--muted);">
        <div class="text-sm font-semibold">{{ c.name }}</div>
        <span class="tds-badge badge-success mt-1">{{ c.status }}</span>
      </div>
      {% endfor %}
    </div>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 4: 라우트 추가**

```python
@router.get("/infra")
def infra_page(request: Request, session: Session = Depends(get_session), k8s: interfaces.K8sService = Depends(get_k8s)):
    ctx = {
        "active_nav": "infra",
        "app_count": len(AppRepository(session).list_all()),
        "nodes": k8s.nodes(),
        "components": k8s.components(),
    }
    return render_page(request, "pages/infra.html", ctx)
```

- [ ] **Step 5: 실행 → 통과 확인**

Run: `pytest tests/test_pages.py::test_infra_page -v`
Expected: PASS.

- [ ] **Step 6: 커밋**

```bash
git add app/templates/pages/infra.html app/routers/pages.py tests/test_pages.py
git commit -m "✨ /infra 페이지 (노드/컴포넌트 조회)"
```

### Task 18: /settings 페이지

**Files:**
- Create: `app/templates/pages/settings.html`
- Modify: `app/routers/pages.py`
- Test: `tests/test_pages.py`

- [ ] **Step 1: 실패 테스트 추가**

```python
def test_settings_page(client):
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert "설정" in resp.text and ("목표 R" in resp.text or "GitHub" in resp.text)
```

- [ ] **Step 2: 실행 → 실패 확인**

Run: `pytest tests/test_pages.py::test_settings_page -v`
Expected: FAIL (404).

- [ ] **Step 3: app/templates/pages/settings.html 작성**

목업 **1750–1976줄**(settings 섹션) 포팅. LLM 설정 / 목표R / 예산 + 외부 통합 키(GitHub PAT 등) 입력 폼. Slice 1은 저장 미동작(폼만).

```html
{% extends layout|default("base.html") %}
{% block content %}
<div class="p-6 space-y-6 max-w-2xl">
  <div>
    <h1 class="text-2xl font-extrabold">설정</h1>
    <p class="text-sm" style="color: var(--muted-foreground);">AI 루프 및 외부 통합</p>
  </div>
  <div class="tds-card p-6 space-y-4">
    <div class="font-bold">AI 설정</div>
    <div><label class="text-sm">LLM 모델</label><input class="tds-input mt-1" value="{{ llm_model }}" /></div>
    <div><label class="text-sm">목표 R 지수</label><input class="tds-input mt-1" value="{{ target_r }}" /></div>
  </div>
  <div class="tds-card p-6 space-y-4">
    <div class="font-bold">외부 통합</div>
    <div><label class="text-sm">GitHub Personal Access Token</label><input class="tds-input mt-1" type="password" placeholder="ghp_..." /></div>
    <div><label class="text-sm">Anthropic API Key</label><input class="tds-input mt-1" type="password" placeholder="sk-ant-..." /></div>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 4: 라우트 추가**

```python
from app.config import settings


@router.get("/settings")
def settings_page(request: Request, session: Session = Depends(get_session)):
    ctx = {
        "active_nav": "settings",
        "app_count": len(AppRepository(session).list_all()),
        "llm_model": settings.llm_model,
        "target_r": settings.target_r,
    }
    return render_page(request, "pages/settings.html", ctx)
```

- [ ] **Step 5: 실행 → 통과 확인**

Run: `pytest tests/test_pages.py::test_settings_page -v`
Expected: PASS.

- [ ] **Step 6: 커밋**

```bash
git add app/templates/pages/settings.html app/routers/pages.py tests/test_pages.py
git commit -m "✨ /settings 페이지 (AI 설정 + 외부 통합)"
```

---

## Phase 6 — SSE 배관 + 마무리

### Task 19: SSE 스트림 스텁 (TDD)

**Files:**
- Create: `app/routers/stream.py`
- Modify: `app/main.py` (라우터 등록)
- Test: `tests/test_stream.py`

- [ ] **Step 1: 실패 테스트 작성 — tests/test_stream.py**

```python
def test_stream_emits_event(client):
    # sse-starlette 스트림에서 최소 1개 이벤트 수신 확인
    with client.stream("GET", "/stream?once=1") as resp:
        assert resp.status_code == 200
        body = next(resp.iter_lines())
        # 첫 줄이 SSE 형식(data: ...) 또는 빈 줄
        assert body is not None
```

- [ ] **Step 2: 실행 → 실패 확인**

Run: `pytest tests/test_stream.py -v`
Expected: FAIL (404 — 라우트 없음).

- [ ] **Step 3: app/routers/stream.py 작성**

```python
import asyncio
import json

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

router = APIRouter()


@router.get("/stream")
async def stream(request: Request, once: int = 0):
    """Slice 1 스텁 — mock 하트비트. 실제 이벤트 소스는 이후 슬라이스."""

    async def event_gen():
        tick = 0
        while True:
            if await request.is_disconnected():
                break
            tick += 1
            yield {"event": "heartbeat", "data": json.dumps({"tick": tick})}
            if once:
                break
            await asyncio.sleep(2)

    return EventSourceResponse(event_gen())
```

- [ ] **Step 4: app/main.py에 라우터 등록**

`from app.routers import pages` 아래에 추가:
```python
from app.routers import stream
```
`app.include_router(pages.router)` 아래에 추가:
```python
app.include_router(stream.router)
```

- [ ] **Step 5: 실행 → 통과 확인**

Run: `pytest tests/test_stream.py -v`
Expected: PASS.

- [ ] **Step 6: 커밋**

```bash
git add app/routers/stream.py app/main.py tests/test_stream.py
git commit -m "✨ /stream SSE 스텁 (mock 하트비트)"
```

### Task 20: .env.example + 전체 검증 + 마무리

**Files:**
- Create: `.env.example`

- [ ] **Step 1: .env.example 작성**

```
APP_NAME=ChaosLab
DATABASE_URL=sqlite:///./chaoslab.db

# 외부 시스템 (Slice 1 미사용)
K8S_CONTEXT=
PROMETHEUS_URL=http://localhost:9090
LOKI_URL=http://localhost:3100

# AI (Phase 3)
ANTHROPIC_API_KEY=
LLM_MODEL=claude-sonnet-4-6
TARGET_R=0.7
```

- [ ] **Step 2: 전체 테스트 실행**

Run: `pytest -v`
Expected: 모든 테스트 PASS (repositories 3 · seed 1 · stubs 2 · rendering 2 · pages 8 · stream 1).

- [ ] **Step 3: 수동 E2E 확인**

Run: `rm -f chaoslab.db && uvicorn app.main:app --reload`
브라우저에서 확인:
- `http://localhost:8000/` → 대시보드(KPI+차트) 렌더
- 사이드바 클릭 → 페이지 전환(HTMX, URL 변경), 새로고침해도 동작
- 테마 토글 → light/dark 전환, 차트 색 갱신
- `/experiments` 행 클릭 → 상세 5탭, 탭 전환, 메트릭 차트 표시
- `/apps` "새 앱 등록" → 모달 open/close
확인 후 Ctrl+C.

- [ ] **Step 4: 커밋**

```bash
git add .env.example
git commit -m "🔧 .env.example + Slice 1 걷는 뼈대 완성"
```

---

## Self-Review 체크리스트 결과

- **Spec 커버리지**: 6페이지(Task 13–18) · SQLite+Repository+seed(Task 2–5) · 외부 스텁+인터페이스(Task 6–8) · HTMX 풀/부분 렌더(Task 9) · TDS CSS/매크로/사이드바 DRY(Task 10–12) · SSE 배관(Task 19) · 설정/실행(Task 1, 20). 스펙 §1–9 전부 대응됨.
- **비범위 준수**: 실제 빌드/카오스/모니터링/K8s/AI/인증/Iac-aws 변경 없음 — 전부 스텁 또는 후속 슬라이스.
- **타입 일관성**: Repository 메서드명(`list_all`/`get`/`create`/`list_for_app`/`list_for_experiment`), Protocol 시그니처, `render_page`/`resolve_layout`, `active_nav`/`app_count` context 키가 정의·사용처에서 일치.
- **플레이스홀더**: 모든 코드 스텝에 실제 코드 포함. 템플릿 포팅 스텝은 목업 line-range + 변환 규칙 + 스모크 테스트 단언으로 구체화(2000줄 복붙 대신 소스 파일 참조).

## 알려진 한계 (다음 슬라이스로)
- 대시보드/상세의 일부 목업 블록(진행중 실험·AI 요약·최근활동 카드 등)은 최소 골격만 포팅 — 충실도 향상은 같은 패턴으로 마크업 추가.
- Tailwind CDN은 프로덕션 비권장 → 빌드 전환은 Roadmap 항목.
- 폼(새 앱/새 실험/설정 저장)은 UI만 — 실제 처리는 Slice 2+.
