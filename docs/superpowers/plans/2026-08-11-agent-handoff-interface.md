# AI Agent 전달 데이터(핸드오프) 인터페이스 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 노션 「AI Agent 전달 데이터」 §2를 Pydantic 계약으로 고정하고, 실험별 전달 페이로드를 스냅샷으로 저장·조회·수정·삭제하는 REST 인터페이스를 만든다.

**Architecture:** 계약(`services/agent/handoff_schema.py`) → 저장(`agent_handoffs` 새 테이블 + Repository) → 조립(`HandoffSourceService` Protocol + Stub, `assembler.py`) → REST(`routers/handoffs.py`, 순수 JSON). UI 변경 없음 — 조회는 `/docs`(Swagger).

**Tech Stack:** FastAPI · Pydantic v2 · SQLAlchemy 2.0 · pytest (hermetic in-memory SQLite)

## Global Constraints

- 스펙: `docs/superpowers/specs/2026-08-11-agent-handoff-interface-design.md`
- **UI(템플릿·app.js) 변경 금지** — 준영·시웅 작업 영역과 충돌 방지
- Experiment 테이블 컬럼 추가 금지(마이그레이션 부재) — 새 테이블만
- mock 데이터는 `db/seed.py`에서만, 테스트는 conftest가 Stub 강제(hermetic)
- 커밋 컨벤션: ✨기능 ✅테스트 📝문서, 파일단위 원자적. 브랜치 `feat/agent-handoff-interface`(이미 생성됨)
- 실행: `source .venv/bin/activate` 후 `pytest -q` (기존 89개 통과 유지)
- up.sh/클러스터 불필요 — 전부 Stub

---

### Task 1: 전달 데이터 계약 스키마

**Files:**
- Create: `app/services/agent/handoff_schema.py`
- Test: `tests/test_handoff_schema.py`

**Interfaces:**
- Produces: `SCHEMA_VERSION: str = "1.0"`, `PhaseSummary`, `PhaseSummaries`, `ExperimentInfo`, `IstioConfig`, `DeploymentInfo`, `K8sEvent`, `RIndexBreakdown`, `ImprovementAttempt`, `Budget`, `AgentHandoffPayload` — 모두 `extra="forbid"` Pydantic 모델. Task 3~5가 이 이름들을 그대로 import.

- [ ] **Step 1: Write the failing test**

`tests/test_handoff_schema.py`:

```python
"""전달 데이터 계약 단위 테스트 — 노션 §2 매핑 필드·엄격성 검증."""
import pytest
from pydantic import ValidationError

from app.services.agent.handoff_schema import PhaseSummary


def summary_kwargs(**over) -> dict:
    """유효한 PhaseSummary 인자 한 벌 (테스트 공용)."""
    base = dict(
        rps_avg=42.0, rps_min=30.0, rps_max=55.0,
        error_rate_avg=0.4, error_rate_peak=1.2, http_5xx_count=3,
        status_code_dist={"200": 1200, "503": 3},
        latency_p50_avg_ms=35.0, latency_p50_peak_ms=60.0,
        latency_p95_avg_ms=120.0, latency_p95_peak_ms=180.0,
        latency_p99_avg_ms=200.0, latency_p99_peak_ms=310.0,
        min_ready_pods=3, restart_count=0,
    )
    base.update(over)
    return base


def test_phase_summary_valid():
    s = PhaseSummary(**summary_kwargs())
    assert s.recovery_seconds is None  # recovery 단계만 채우는 선택 필드


def test_phase_summary_rejects_unknown_field():
    with pytest.raises(ValidationError):
        PhaseSummary(**summary_kwargs(), typo_field=1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_handoff_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: app.services.agent.handoff_schema`

- [ ] **Step 3: Write the schema module**

`app/services/agent/handoff_schema.py`:

```python
"""AI Agent 전달 데이터 계약 (Phase 3 공통 인터페이스).

08/04 회의 노션 「카오스 테스트 — 모니터링 표시 데이터 & AI Agent 전달 데이터」 §2 매핑.
전달 시점: 기준선/장애/회복 단계 요약 3벌 + 추가 자료 8종을 회복 종료 후 한 번에.
이 모델의 JSON Schema가 팀 공유 계약 — /docs 에 자동 노출된다.
"""
from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 오타 필드가 조용히 통과하지 않게


class PhaseSummary(_Strict):
    """단계별 지표 요약 (노션 §2-①). 키는 화면 지표와 같은 원천의 집계값."""

    rps_avg: float
    rps_min: float
    rps_max: float
    error_rate_avg: float        # %
    error_rate_peak: float       # %
    http_5xx_count: int
    status_code_dist: dict[str, int]
    latency_p50_avg_ms: float
    latency_p50_peak_ms: float
    latency_p95_avg_ms: float
    latency_p95_peak_ms: float
    latency_p99_avg_ms: float
    latency_p99_peak_ms: float
    min_ready_pods: int
    restart_count: int
    recovery_seconds: float | None = None  # recovery 단계만 채움


class PhaseSummaries(_Strict):
    baseline: PhaseSummary
    fault: PhaseSummary
    recovery: PhaseSummary


class ExperimentInfo(_Strict):
    """실험 정보 + 파라미터 허용 범위 — 개선안이 범위를 벗어나지 않게."""

    id: int
    app_name: str
    namespace: str
    chaos_type: str
    status: str
    params: dict
    allowed_ranges: dict  # chaos_specs.CHAOS_SPECS[chaos_type]["fields"]
    started_at: str | None
    finished_at: str | None


class IstioConfig(_Strict):
    """AI가 고칠 대상 원본 — timeout·retry(VS), circuit breaker(DR)."""

    virtual_service_yaml: str
    destination_rule_yaml: str


class DeploymentInfo(_Strict):
    replicas: int
    probes: dict
    resources: dict


class K8sEvent(_Strict):
    timestamp: str
    type: str
    reason: str
    object: str
    message: str


class RIndexBreakdown(_Strict):
    """R = 0.4·가용성 + 0.3·레이턴시점수 + 0.3·복구속도 — 항목별 내역."""

    availability: float
    latency_score: float
    recovery_score: float
    weights: dict[str, float] = Field(
        default_factory=lambda: {"availability": 0.4, "latency": 0.3, "recovery": 0.3}
    )
    baseline_r: float | None
    current_r: float | None
    target_r: float


class ImprovementAttempt(_Strict):
    """이전 개선 시도 1건 (AgentIteration 대응) — 같은 개선을 반복하지 않게."""

    iteration: int
    params_before: dict
    params_after: dict
    r_index: float | None
    verdict: str


class Budget(_Strict):
    llm_cost_used_usd: float
    llm_cost_remaining_usd: float
    iterations_remaining: int


class AgentHandoffPayload(_Strict):
    schema_version: str = SCHEMA_VERSION
    experiment: ExperimentInfo
    phase_summaries: PhaseSummaries
    istio_config: IstioConfig
    deployment_info: DeploymentInfo
    k8s_events: list[K8sEvent]
    error_log_samples: list[str] = Field(default_factory=list, max_length=20)
    r_index: RIndexBreakdown
    improvement_history: list[ImprovementAttempt]
    budget: Budget
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_handoff_schema.py -v`
Expected: 2 PASS

- [ ] **Step 5: Add payload-level strictness tests (failing 확인 없이 바로 — 같은 모듈)**

`tests/test_handoff_schema.py`에 추가:

```python
from app.services.agent.handoff_schema import AgentHandoffPayload


def test_error_log_samples_max_20():
    """노션 §2-②: 에러 로그 샘플은 최대 20개."""
    with pytest.raises(ValidationError):
        AgentHandoffPayload.model_validate(
            {"error_log_samples": [f"log {i}" for i in range(21)]}
        )


def test_payload_requires_all_sections():
    """9개 섹션 중 하나라도 빠지면 거부 — 계약의 이빨."""
    with pytest.raises(ValidationError):
        AgentHandoffPayload.model_validate({"schema_version": "1.0"})
```

Run: `pytest tests/test_handoff_schema.py -v`
Expected: 4 PASS

- [ ] **Step 6: Commit**

```bash
git add app/services/agent/handoff_schema.py tests/test_handoff_schema.py
git commit -m "✨ AI 전달 데이터 계약 스키마 (노션 §2 → Pydantic, extra=forbid)"
```

---

### Task 2: AgentHandoff 모델 + HandoffRepository

**Files:**
- Modify: `app/db/models.py` (파일 끝에 클래스 추가 + Experiment에 relationship 1줄)
- Modify: `app/db/repositories.py` (파일 끝에 클래스 추가 + import 수정)
- Test: `tests/test_handoff_repository.py`

**Interfaces:**
- Consumes: 없음 (Task 1과 독립)
- Produces: `AgentHandoff` 모델(id·experiment_id·schema_version·payload·created_at·updated_at), `HandoffRepository`(`create(**kwargs)`, `get(handoff_id)`, `list_for_experiment(experiment_id)` 최신순, `latest_for_experiment(experiment_id)`, `update_payload(handoff, payload: dict, schema_version: str)`, `delete(handoff)`) — Task 5·6이 사용.

- [ ] **Step 1: Write the failing test**

`tests/test_handoff_repository.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_handoff_repository.py -v`
Expected: FAIL — `ImportError: cannot import name 'HandoffRepository'`

- [ ] **Step 3: Add the model**

`app/db/models.py` — `AgentIteration` 클래스 아래(파일 끝)에 추가:

```python
class AgentHandoff(Base):
    """AI Agent 전달 페이로드 스냅샷 — 계약 검증된 JSON을 통째로 저장."""

    __tablename__ = "agent_handoffs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id"))
    schema_version: Mapped[str] = mapped_column(String(10), default="1.0")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    experiment: Mapped["Experiment"] = relationship(back_populates="handoffs")
```

`Experiment` 클래스의 relationship 블록(68행 `iterations` 아래)에 1줄 추가:

```python
    handoffs: Mapped[list["AgentHandoff"]] = relationship(back_populates="experiment")
```

- [ ] **Step 4: Add the repository**

`app/db/repositories.py` — import 수정 후 파일 끝에 추가:

```python
from app.db.models import AgentHandoff, AgentIteration, App, Build, Experiment, _now
```

```python
class HandoffRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, **kwargs) -> AgentHandoff:
        obj = AgentHandoff(**kwargs)
        self.session.add(obj)
        self.session.commit()
        return obj

    def get(self, handoff_id: int) -> AgentHandoff | None:
        return self.session.get(AgentHandoff, handoff_id)

    def list_for_experiment(self, experiment_id: int) -> list[AgentHandoff]:
        stmt = (
            select(AgentHandoff)
            .where(AgentHandoff.experiment_id == experiment_id)
            .order_by(AgentHandoff.id.desc())
        )
        return list(self.session.scalars(stmt))

    def latest_for_experiment(self, experiment_id: int) -> AgentHandoff | None:
        rows = self.list_for_experiment(experiment_id)
        return rows[0] if rows else None

    def update_payload(self, handoff: AgentHandoff, payload: dict,
                       schema_version: str) -> AgentHandoff:
        handoff.payload = payload
        handoff.schema_version = schema_version
        handoff.updated_at = _now()
        self.session.commit()
        return handoff

    def delete(self, handoff: AgentHandoff) -> None:
        self.session.delete(handoff)
        self.session.commit()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_handoff_repository.py -v && pytest -q`
Expected: 2 PASS + 기존 전체 통과 (새 테이블 추가는 `create_all` 안전)

- [ ] **Step 6: Commit**

```bash
git add app/db/models.py app/db/repositories.py tests/test_handoff_repository.py
git commit -m "✨ agent_handoffs 테이블 + HandoffRepository (스냅샷 저장소)"
```

---

### Task 3: HandoffSourceService Protocol + Stub + 설정

**Files:**
- Modify: `app/services/interfaces.py` (파일 끝에 Protocol 추가)
- Modify: `app/services/stubs.py` (파일 끝에 Stub 추가)
- Modify: `app/config.py` (AI 섹션에 2줄)
- Modify: `app/deps.py` (팩토리 2개 추가)
- Test: `tests/test_handoff_source_stub.py`

**Interfaces:**
- Consumes: Task 1의 `PhaseSummary`, `IstioConfig`, `DeploymentInfo`, `K8sEvent` (테스트에서 형태 검증용)
- Produces: `HandoffSourceService` Protocol(`phase_summary(namespace, app_name, phase) -> dict`, `istio_config(namespace, app_name) -> dict`, `deployment_info(namespace, app_name) -> dict`, `events(namespace, app_name) -> list[dict]`, `error_logs(namespace, app_name, limit=20) -> list[str]`), `stubs.StubHandoffSource`, `deps.make_handoff_source()` / `deps.get_handoff_source()`, `settings.llm_budget_usd`(기본 5.0) / `settings.max_agent_iterations`(기본 2) — Task 4·5가 사용.

- [ ] **Step 1: Write the failing test**

`tests/test_handoff_source_stub.py`:

```python
"""StubHandoffSource 출력이 계약 모델로 그대로 검증되는지 — 조립 전 형태 보증."""
from app.services.agent.handoff_schema import (
    DeploymentInfo, IstioConfig, K8sEvent, PhaseSummary,
)
from app.services.stubs import StubHandoffSource


def test_phase_summaries_validate_against_contract():
    stub = StubHandoffSource()
    for phase in ("baseline", "fault", "recovery"):
        s = PhaseSummary(**stub.phase_summary("sut", "online-boutique", phase))
        if phase == "recovery":
            assert s.recovery_seconds is not None  # 회복 소요 시간은 recovery만
        else:
            assert s.recovery_seconds is None


def test_fault_phase_is_degraded():
    stub = StubHandoffSource()
    base = stub.phase_summary("sut", "ob", "baseline")
    fault = stub.phase_summary("sut", "ob", "fault")
    assert fault["error_rate_peak"] > base["error_rate_peak"]  # 장애 구간이 더 나쁨
    assert fault["latency_p99_peak_ms"] > base["latency_p99_peak_ms"]


def test_other_sources_validate():
    stub = StubHandoffSource()
    IstioConfig(**stub.istio_config("sut", "ob"))
    DeploymentInfo(**stub.deployment_info("sut", "ob"))
    for e in stub.events("sut", "ob"):
        K8sEvent(**e)
    logs = stub.error_logs("sut", "ob", limit=20)
    assert 0 < len(logs) <= 20
    assert len(logs) == len(set(logs))  # 중복 제거 (노션 §2-②)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_handoff_source_stub.py -v`
Expected: FAIL — `ImportError: cannot import name 'StubHandoffSource'`

- [ ] **Step 3: Add the Protocol**

`app/services/interfaces.py` 파일 끝에 추가:

```python
class HandoffSourceService(Protocol):
    """AI 전달 페이로드 재료 중 외부 시스템산(産) — Real 구현은 Slice 4·5에서.

    반환 dict의 키는 services/agent/handoff_schema.py 계약 모델과 1:1.
    """

    def phase_summary(self, namespace: str, app_name: str, phase: str) -> dict:
        """단계(baseline|fault|recovery)별 지표 요약. PhaseSummary와 동일 키."""

    def istio_config(self, namespace: str, app_name: str) -> dict:
        """{"virtual_service_yaml": str, "destination_rule_yaml": str}."""

    def deployment_info(self, namespace: str, app_name: str) -> dict:
        """{"replicas": int, "probes": dict, "resources": dict}."""

    def events(self, namespace: str, app_name: str) -> list[dict]:
        """K8s 이벤트 원본 목록. K8sEvent와 동일 키."""

    def error_logs(self, namespace: str, app_name: str, limit: int = 20) -> list[str]:
        """중복 제거된 에러 로그 샘플, 최대 limit개."""
```

- [ ] **Step 4: Add the Stub**

`app/services/stubs.py` 파일 끝에 추가:

```python
_PHASE_SUMMARY_SAMPLES: dict[str, dict] = {
    "baseline": {
        "rps_avg": 42.0, "rps_min": 35.0, "rps_max": 51.0,
        "error_rate_avg": 0.3, "error_rate_peak": 0.8, "http_5xx_count": 4,
        "status_code_dist": {"200": 12480, "404": 21, "503": 4},
        "latency_p50_avg_ms": 34.0, "latency_p50_peak_ms": 52.0,
        "latency_p95_avg_ms": 118.0, "latency_p95_peak_ms": 161.0,
        "latency_p99_avg_ms": 205.0, "latency_p99_peak_ms": 280.0,
        "min_ready_pods": 3, "restart_count": 0, "recovery_seconds": None,
    },
    "fault": {
        "rps_avg": 38.0, "rps_min": 12.0, "rps_max": 49.0,
        "error_rate_avg": 6.4, "error_rate_peak": 23.1, "http_5xx_count": 312,
        "status_code_dist": {"200": 9120, "503": 298, "504": 14},
        "latency_p50_avg_ms": 88.0, "latency_p50_peak_ms": 240.0,
        "latency_p95_avg_ms": 460.0, "latency_p95_peak_ms": 890.0,
        "latency_p99_avg_ms": 1120.0, "latency_p99_peak_ms": 2300.0,
        "min_ready_pods": 1, "restart_count": 2, "recovery_seconds": None,
    },
    "recovery": {
        "rps_avg": 41.0, "rps_min": 28.0, "rps_max": 50.0,
        "error_rate_avg": 1.1, "error_rate_peak": 4.2, "http_5xx_count": 38,
        "status_code_dist": {"200": 11890, "503": 38},
        "latency_p50_avg_ms": 41.0, "latency_p50_peak_ms": 95.0,
        "latency_p95_avg_ms": 150.0, "latency_p95_peak_ms": 320.0,
        "latency_p99_avg_ms": 260.0, "latency_p99_peak_ms": 510.0,
        "min_ready_pods": 2, "restart_count": 1, "recovery_seconds": 41.0,
    },
}

_STUB_VS_YAML = """apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: {app}
  namespace: {ns}
spec:
  hosts: ["{app}"]
  http:
    - route:
        - destination:
            host: {app}
      timeout: 3s
      retries:
        attempts: 2
        perTryTimeout: 1s
        retryOn: 5xx
"""

_STUB_DR_YAML = """apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: {app}
  namespace: {ns}
spec:
  host: {app}
  trafficPolicy:
    outlierDetection:
      consecutive5xxErrors: 5
      interval: 10s
      baseEjectionTime: 30s
"""


class StubHandoffSource:
    """AI 팀이 실데이터(Slice 4·5) 전에 개발 착수할 수 있는 형태 충실 샘플."""

    def phase_summary(self, namespace: str, app_name: str, phase: str) -> dict:
        return dict(_PHASE_SUMMARY_SAMPLES[phase])

    def istio_config(self, namespace: str, app_name: str) -> dict:
        return {
            "virtual_service_yaml": _STUB_VS_YAML.format(app=app_name, ns=namespace),
            "destination_rule_yaml": _STUB_DR_YAML.format(app=app_name, ns=namespace),
        }

    def deployment_info(self, namespace: str, app_name: str) -> dict:
        return {
            "replicas": 3,
            "probes": {
                "readiness": {"httpGet": "/healthz", "periodSeconds": 10,
                              "failureThreshold": 3},
                "liveness": {"httpGet": "/healthz", "periodSeconds": 20},
            },
            "resources": {
                "requests": {"cpu": "100m", "memory": "128Mi"},
                "limits": {"cpu": "500m", "memory": "256Mi"},
            },
        }

    def events(self, namespace: str, app_name: str) -> list[dict]:
        return [
            {"timestamp": "2026-08-11T02:00:11Z", "type": "Normal",
             "reason": "Killing", "object": f"pod/{app_name}-7d9",
             "message": "Stopping container server (chaos pod-kill)"},
            {"timestamp": "2026-08-11T02:00:14Z", "type": "Warning",
             "reason": "Unhealthy", "object": f"pod/{app_name}-5fc",
             "message": "Readiness probe failed: connection refused"},
            {"timestamp": "2026-08-11T02:00:52Z", "type": "Normal",
             "reason": "Started", "object": f"pod/{app_name}-8b1",
             "message": "Started container server"},
        ]

    def error_logs(self, namespace: str, app_name: str, limit: int = 20) -> list[str]:
        samples = [
            f'[{app_name}] rpc error: code = Unavailable desc = connection refused',
            f'[{app_name}] HTTP 503 upstream connect error or disconnect/reset',
            f'[{app_name}] context deadline exceeded (client timeout 3s)',
            f'[{app_name}] readiness probe failed: Get "/healthz": dial tcp refused',
        ]
        return samples[:limit]
```

- [ ] **Step 5: Add settings + factories**

`app/config.py` — `# AI (Phase 3)` 섹션(`target_r: float = 0.7` 아래)에 추가:

```python
    llm_budget_usd: float = 5.0        # 실험당 LLM 예산 상한 (Budget.remaining 계산)
    max_agent_iterations: int = 2      # 실험당 최대 개선 반복 (08/04 시안과 동일)
```

`app/deps.py` — `make_chaos` 아래에 추가:

```python
def make_handoff_source() -> interfaces.HandoffSourceService:
    # Real(Prometheus/Loki/K8s 실조회)은 Slice 4·5 — 그 전까지 항상 Stub.
    return stubs.StubHandoffSource()
```

`get_k8s` 아래에 추가:

```python
def get_handoff_source() -> interfaces.HandoffSourceService:
    return make_handoff_source()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_handoff_source_stub.py -v && pytest -q`
Expected: 3 PASS + 기존 전체 통과

- [ ] **Step 7: Commit**

```bash
git add app/services/interfaces.py app/services/stubs.py app/config.py app/deps.py tests/test_handoff_source_stub.py
git commit -m "✨ HandoffSourceService Protocol + Stub 샘플 + LLM 예산 설정"
```

---

### Task 4: 페이로드 조립기 (assembler)

**Files:**
- Create: `app/services/agent/assembler.py`
- Test: `tests/test_handoff_assembler.py`

**Interfaces:**
- Consumes: Task 1 계약 모델 전부, Task 3 `HandoffSourceService`·`settings.llm_budget_usd`·`settings.max_agent_iterations`, 기존 `IterationRepository.list_for_experiment`, `chaos_specs.CHAOS_SPECS`
- Produces: `assemble_handoff(session: Session, source: HandoffSourceService, exp: Experiment) -> AgentHandoffPayload` — Task 5(라우터)·Task 6(seed)이 사용.

- [ ] **Step 1: Write the failing test**

`tests/test_handoff_assembler.py`:

```python
"""assemble_handoff — seed 실험에서 계약 검증되는 페이로드가 나오는지."""
from app.db.repositories import ExperimentRepository
from app.db.seed import seed_data
from app.services.agent.assembler import assemble_handoff
from app.services.agent.handoff_schema import AgentHandoffPayload
from app.services.stubs import StubHandoffSource


def _seeded_exp(db_session):
    seed_data(db_session)
    return ExperimentRepository(db_session).list_all()[0]


def test_assemble_produces_valid_payload(db_session):
    exp = _seeded_exp(db_session)
    payload = assemble_handoff(db_session, StubHandoffSource(), exp)

    # round-trip: dump 후 재검증 가능해야 저장·PUT 계약과 동일
    AgentHandoffPayload.model_validate(payload.model_dump())

    assert payload.schema_version == "1.0"
    assert payload.experiment.app_name == "online-boutique"
    assert payload.experiment.allowed_ranges["latency_ms"]["max"] == 10_000
    assert payload.r_index.target_r == 0.7
    assert len(payload.improvement_history) == 3          # seed iteration 3건
    assert payload.budget.iterations_remaining == 0       # max 2 - 사용 3 → 0 (음수 금지)
    assert payload.budget.llm_cost_used_usd == 0.036      # 0.012 × 3
    assert len(payload.error_log_samples) <= 20


def test_stored_contract_metrics_win_over_stub(db_session):
    """Slice 5가 계약 형태로 저장해 두면 그 값이 Stub보다 우선."""
    exp = _seeded_exp(db_session)
    # Stub 출력은 계약 형태 — rps_avg만 바꿔 "저장된 계약형 metrics"를 흉내
    stored = StubHandoffSource().phase_summary("sut", "ob", "baseline")
    stored["rps_avg"] = 999.0
    exp.baseline_metrics = stored
    db_session.commit()

    payload = assemble_handoff(db_session, StubHandoffSource(), exp)
    assert payload.phase_summaries.baseline.rps_avg == 999.0


def test_legacy_metrics_fall_back_to_stub(db_session):
    """seed의 구형 {"error","p99"} 형태는 계약 불일치 → Stub 샘플로 대체."""
    exp = _seeded_exp(db_session)
    assert exp.baseline_metrics == {"error": 0.3, "p99": 89}

    payload = assemble_handoff(db_session, StubHandoffSource(), exp)
    assert payload.phase_summaries.baseline.rps_avg == 42.0  # Stub baseline 값
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_handoff_assembler.py -v`
Expected: FAIL — `ModuleNotFoundError: app.services.agent.assembler`

- [ ] **Step 3: Write the assembler**

`app/services/agent/assembler.py`:

```python
"""전달 페이로드 조립 — DB산(실험·iteration)은 세션에서, 외부산은 HandoffSourceService에서.

단계 요약 규칙: Experiment.*_metrics가 계약(PhaseSummary) 형태로 저장돼 있으면 우선,
아니면(비었거나 Slice 5 이전의 임의 형태) Stub/Real 소스 값 사용.
"""
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Experiment
from app.db.repositories import IterationRepository
from app.services.agent.handoff_schema import (
    AgentHandoffPayload,
    Budget,
    DeploymentInfo,
    ExperimentInfo,
    ImprovementAttempt,
    IstioConfig,
    K8sEvent,
    PhaseSummaries,
    PhaseSummary,
    RIndexBreakdown,
)
from app.services.chaos_specs import CHAOS_SPECS
from app.services.interfaces import HandoffSourceService

_PHASE_COLUMNS = {
    "baseline": "baseline_metrics",
    "fault": "fault_metrics",
    "recovery": "recovery_metrics",
}

# R지수 항목별 점수 실계산은 Slice 5 — 그 전까지는 형태 보증용 자리값.
_STUB_COMPONENT_SCORES = {"availability": 0.82, "latency_score": 0.47, "recovery_score": 0.55}


def _phase_summary(exp: Experiment, source: HandoffSourceService, phase: str) -> PhaseSummary:
    stored = getattr(exp, _PHASE_COLUMNS[phase])
    if stored:
        try:
            return PhaseSummary(**stored)
        except ValidationError:
            pass  # 계약 이전 형태 — 소스 샘플로 대체
    return PhaseSummary(**source.phase_summary(exp.app.namespace, exp.app.name, phase))


def assemble_handoff(session: Session, source: HandoffSourceService,
                     exp: Experiment) -> AgentHandoffPayload:
    app = exp.app
    iterations = IterationRepository(session).list_for_experiment(exp.id)
    used_usd = sum(it.llm_cost_usd for it in iterations)

    return AgentHandoffPayload(
        experiment=ExperimentInfo(
            id=exp.id,
            app_name=app.name,
            namespace=app.namespace,
            chaos_type=exp.chaos_type,
            status=exp.status,
            params=exp.params,
            allowed_ranges=CHAOS_SPECS.get(exp.chaos_type, {}).get("fields", {}),
            started_at=exp.started_at.isoformat() if exp.started_at else None,
            finished_at=exp.finished_at.isoformat() if exp.finished_at else None,
        ),
        phase_summaries=PhaseSummaries(
            baseline=_phase_summary(exp, source, "baseline"),
            fault=_phase_summary(exp, source, "fault"),
            recovery=_phase_summary(exp, source, "recovery"),
        ),
        istio_config=IstioConfig(**source.istio_config(app.namespace, app.name)),
        deployment_info=DeploymentInfo(**source.deployment_info(app.namespace, app.name)),
        k8s_events=[K8sEvent(**e) for e in source.events(app.namespace, app.name)],
        error_log_samples=source.error_logs(app.namespace, app.name, limit=20),
        r_index=RIndexBreakdown(
            **_STUB_COMPONENT_SCORES,
            baseline_r=exp.baseline_r,
            current_r=exp.r_index,
            target_r=exp.target_r,
        ),
        improvement_history=[
            ImprovementAttempt(
                iteration=it.iteration,
                params_before=it.params_before,
                params_after=it.params_after,
                r_index=it.r_index,
                verdict=it.verdict,
            )
            for it in iterations
        ],
        budget=Budget(
            llm_cost_used_usd=round(used_usd, 4),
            llm_cost_remaining_usd=round(max(settings.llm_budget_usd - used_usd, 0.0), 4),
            iterations_remaining=max(settings.max_agent_iterations - len(iterations), 0),
        ),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_handoff_assembler.py -v && pytest -q`
Expected: 3 PASS + 기존 전체 통과

- [ ] **Step 5: Commit**

```bash
git add app/services/agent/assembler.py tests/test_handoff_assembler.py
git commit -m "✨ 전달 페이로드 조립기 — 저장 metrics 우선, 외부산은 소스 서비스"
```

---

### Task 5: REST 라우터 + 앱 등록

**Files:**
- Create: `app/routers/handoffs.py`
- Modify: `app/main.py:11` (import), `app/main.py:34` 근처 (include_router)
- Test: `tests/test_handoffs_api.py`

**Interfaces:**
- Consumes: Task 1 `AgentHandoffPayload`, Task 2 `HandoffRepository`, Task 3 `get_handoff_source`, Task 4 `assemble_handoff`, 기존 `ExperimentRepository`·`get_session`
- Produces: 6개 엔드포인트(아래 표). 응답 형태 `{id, experiment_id, schema_version, created_at, updated_at, payload}` (목록은 payload 제외 메타만) — AI 루프·시드가 소비.

- [ ] **Step 1: Write the failing test**

`tests/test_handoffs_api.py`:

```python
"""핸드오프 REST API — client 픽스처(seed 포함, Stub 강제).

seed가 스냅샷을 미리 만들 수 있으므로(개수 가정 금지) 상대 검증만 한다.
"""


def test_create_then_read_flow(client):
    created = client.post("/experiments/1/handoffs")
    assert created.status_code == 201
    body = created.json()
    hid = body["id"]
    assert body["experiment_id"] == 1
    assert body["payload"]["schema_version"] == "1.0"
    assert body["payload"]["experiment"]["app_name"] == "online-boutique"

    listing = client.get("/experiments/1/handoffs")
    assert listing.status_code == 200
    assert listing.json()[0]["id"] == hid          # 최신순
    assert "payload" not in listing.json()[0]      # 목록은 메타만

    latest = client.get("/experiments/1/handoffs/latest")
    assert latest.status_code == 200
    assert latest.json()["id"] == hid

    single = client.get(f"/handoffs/{hid}")
    assert single.status_code == 200
    assert single.json()["payload"]["budget"]["llm_cost_used_usd"] == 0.036


def test_create_404_unknown_experiment(client):
    assert client.post("/experiments/999/handoffs").status_code == 404
    assert client.get("/experiments/999/handoffs").status_code == 404
    assert client.get("/experiments/999/handoffs/latest").status_code == 404


def test_put_replaces_after_validation(client):
    created = client.post("/experiments/1/handoffs").json()
    payload = created["payload"]
    payload["budget"]["iterations_remaining"] = 1

    res = client.put(f"/handoffs/{created['id']}", json=payload)
    assert res.status_code == 200
    assert res.json()["payload"]["budget"]["iterations_remaining"] == 1


def test_put_rejects_contract_violation(client):
    created = client.post("/experiments/1/handoffs").json()
    payload = created["payload"]
    payload["surprise_field"] = True  # extra=forbid

    res = client.put(f"/handoffs/{created['id']}", json=payload)
    assert res.status_code == 422


def test_delete_then_404(client):
    hid = client.post("/experiments/1/handoffs").json()["id"]
    assert client.delete(f"/handoffs/{hid}").status_code == 204
    assert client.get(f"/handoffs/{hid}").status_code == 404
    assert client.delete(f"/handoffs/{hid}").status_code == 404


def test_latest_404_when_no_snapshot(client):
    for meta in client.get("/experiments/1/handoffs").json():
        client.delete(f"/handoffs/{meta['id']}")
    assert client.get("/experiments/1/handoffs/latest").status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_handoffs_api.py -v`
Expected: FAIL — POST가 404/405 (라우터 미등록)

- [ ] **Step 3: Write the router**

`app/routers/handoffs.py`:

```python
"""AI Agent 전달 데이터(핸드오프) REST API — 이 레포 유일의 순수 JSON 라우터.

스냅샷 저장형: POST가 조립·저장, AI 루프는 GET …/latest 소비.
계약·예시는 /docs (Swagger) 에서 확인 — 별도 대시보드 UI 없음.
"""
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.db.database import get_session
from app.db.models import AgentHandoff
from app.db.repositories import ExperimentRepository, HandoffRepository
from app.deps import get_handoff_source
from app.services.agent.assembler import assemble_handoff
from app.services.agent.handoff_schema import AgentHandoffPayload
from app.services.interfaces import HandoffSourceService

router = APIRouter(tags=["handoffs"])


def _meta(h: AgentHandoff) -> dict:
    return {
        "id": h.id,
        "experiment_id": h.experiment_id,
        "schema_version": h.schema_version,
        "created_at": h.created_at.isoformat(),
        "updated_at": h.updated_at.isoformat(),
    }


def _full(h: AgentHandoff) -> dict:
    return {**_meta(h), "payload": h.payload}


def _require_experiment(session: Session, exp_id: int):
    exp = ExperimentRepository(session).get(exp_id)
    if exp is None:
        raise HTTPException(status_code=404, detail="실험을 찾을 수 없어요")
    return exp


@router.post("/experiments/{exp_id}/handoffs", status_code=201)
def create_handoff(
    exp_id: int,
    session: Session = Depends(get_session),
    source: HandoffSourceService = Depends(get_handoff_source),
) -> dict:
    """현재 실험 데이터로 전달 페이로드를 조립해 스냅샷으로 저장."""
    exp = _require_experiment(session, exp_id)
    payload = assemble_handoff(session, source, exp)
    handoff = HandoffRepository(session).create(
        experiment_id=exp.id,
        schema_version=payload.schema_version,
        payload=payload.model_dump(),
    )
    return _full(handoff)


@router.get("/experiments/{exp_id}/handoffs")
def list_handoffs(exp_id: int, session: Session = Depends(get_session)) -> list[dict]:
    """스냅샷 메타 목록 (최신순, payload 제외)."""
    _require_experiment(session, exp_id)
    return [_meta(h) for h in HandoffRepository(session).list_for_experiment(exp_id)]


@router.get("/experiments/{exp_id}/handoffs/latest")
def latest_handoff(exp_id: int, session: Session = Depends(get_session)) -> dict:
    """최신 스냅샷 전체 — AI 루프 소비 지점."""
    _require_experiment(session, exp_id)
    handoff = HandoffRepository(session).latest_for_experiment(exp_id)
    if handoff is None:
        raise HTTPException(status_code=404, detail="전달 데이터 스냅샷이 없어요")
    return _full(handoff)


@router.get("/handoffs/{handoff_id}")
def get_handoff(handoff_id: int, session: Session = Depends(get_session)) -> dict:
    handoff = HandoffRepository(session).get(handoff_id)
    if handoff is None:
        raise HTTPException(status_code=404, detail="스냅샷을 찾을 수 없어요")
    return _full(handoff)


@router.put("/handoffs/{handoff_id}")
def update_handoff(
    handoff_id: int,
    payload: AgentHandoffPayload,  # body 계약 검증 — 위반 시 FastAPI가 422
    session: Session = Depends(get_session),
) -> dict:
    repo = HandoffRepository(session)
    handoff = repo.get(handoff_id)
    if handoff is None:
        raise HTTPException(status_code=404, detail="스냅샷을 찾을 수 없어요")
    repo.update_payload(handoff, payload.model_dump(), payload.schema_version)
    return _full(handoff)


@router.delete("/handoffs/{handoff_id}", status_code=204)
def delete_handoff(handoff_id: int, session: Session = Depends(get_session)) -> Response:
    repo = HandoffRepository(session)
    handoff = repo.get(handoff_id)
    if handoff is None:
        raise HTTPException(status_code=404, detail="스냅샷을 찾을 수 없어요")
    repo.delete(handoff)
    return Response(status_code=204)
```

- [ ] **Step 4: Register the router**

`app/main.py` 11행 import를:

```python
from app.routers import apps, builds, experiments, handoffs, pages, stream
```

`include_router` 블록 마지막(`experiments` 아래)에:

```python
app.include_router(handoffs.router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_handoffs_api.py -v && pytest -q`
Expected: 6 PASS + 기존 전체 통과

- [ ] **Step 6: Commit**

```bash
git add app/routers/handoffs.py app/main.py tests/test_handoffs_api.py
git commit -m "✨ 핸드오프 REST API — 스냅샷 CRUD + latest 소비 지점"
```

---

### Task 6: 시드 스냅샷 + 문서 갱신 + 전체 검증

**Files:**
- Modify: `app/db/seed.py` (import + `seed_data` 끝에 스냅샷 1건)
- Modify: `CLAUDE.md` (진행 현황에 1줄)
- Test: 기존 스위트 전체 (`pytest -q`)

**Interfaces:**
- Consumes: Task 2 `HandoffRepository`, Task 3 `make_handoff_source`, Task 4 `assemble_handoff`
- Produces: seed DB에 핸드오프 스냅샷 1건 — `uvicorn` 기동 직후 `/docs`에서 바로 예시 확인 가능.

- [ ] **Step 1: Update seed**

`app/db/seed.py` — import 블록에 추가:

```python
from app.db.repositories import (
    AppRepository,
    BuildRepository,
    ExperimentRepository,
    HandoffRepository,
    IterationRepository,
)
from app.deps import make_handoff_source
from app.services.agent.assembler import assemble_handoff
```

`seed_data()` 함수 끝(iteration 생성 for 루프 아래)에 추가:

```python
    # AI 전달 데이터 스냅샷 1건 — 팀원이 /docs에서 바로 예시 확인 (하드코딩 JSON 금지)
    payload = assemble_handoff(session, make_handoff_source(), exp)
    HandoffRepository(session).create(
        experiment_id=exp.id,
        schema_version=payload.schema_version,
        payload=payload.model_dump(),
    )
```

- [ ] **Step 2: Run the full suite**

Run: `pytest -q`
Expected: 전체 통과 — API 테스트는 스냅샷 개수를 가정하지 않도록 작성돼 있어 seed 추가에 안전.

- [ ] **Step 3: Smoke check the app boots and serves the contract**

Run:

```bash
rm -f chaoslab.db && USE_REAL_SERVICES=false python - <<'EOF'
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as c:
    r = c.get("/experiments/1/handoffs/latest")
    assert r.status_code == 200, r.text
    assert r.json()["payload"]["schema_version"] == "1.0"
    assert c.get("/openapi.json").status_code == 200
print("smoke OK")
EOF
rm -f chaoslab.db
```

Expected: `smoke OK` (lifespan seed → 스냅샷 자동 존재)

- [ ] **Step 4: Update CLAUDE.md**

`CLAUDE.md` 진행 현황의 Slice 3 항목 아래에 1줄 추가:

```markdown
- [x] **AI 전달 데이터 인터페이스** (08/04 회의): 노션 §2 계약(`services/agent/handoff_schema.py`, `schema_version` 1.0) · `agent_handoffs` 스냅샷 테이블 · 조립기(저장 metrics 우선, 외부산은 `HandoffSourceService` Stub — Real은 Slice 4·5) · REST CRUD(`routers/handoffs.py`, AI 루프 소비 지점은 `GET /experiments/{id}/handoffs/latest`, 계약 열람은 `/docs`)
```

- [ ] **Step 5: Commit**

```bash
git add app/db/seed.py CLAUDE.md
git commit -m "✨ seed 핸드오프 스냅샷 + 진행 현황 갱신"
```

---

## 완료 후

1. `pytest -q` 전체 통과 확인 (기존 89 + 신규 ~14)
2. superpowers:requesting-code-review 로 리뷰 후 PR 생성 (`gh pr create`) — base `main`, 브랜치 `feat/agent-handoff-interface`. PR 본문에 계약↔노션 매핑 표와 "UI 무변경 · up.sh 불필요" 명시.
