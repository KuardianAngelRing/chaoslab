# AI Agent 전달 데이터(핸드오프) 인터페이스 설계 (2026-08-11)

## 목표

08/04 회의 결정("카오스 테스트에 필요한 데이터들 넘겨주는 공통 인터페이스 작성 +
넘길 데이터 정리")을 구현한다. 노션 문서 「카오스 테스트 — 모니터링 표시 데이터 &
AI Agent 전달 데이터」 §2를 **Pydantic 계약**으로 고정하고, 실험별 전달 페이로드를
**스냅샷으로 저장·조회·수정·삭제**할 수 있는 REST 인터페이스를 만든다.

**UI는 건드리지 않는다** — 준영·시웅이 이번 주 experiments 목업 UI를 수정 중이므로
템플릿·app.js 변경 없음. "편하게 보기"는 FastAPI `/docs`(Swagger)가 담당한다.

## 확정 결정

| 결정 | 내용 |
|---|---|
| 형태 | **스냅샷 저장형** — 조회 시마다 즉석 조립이 아니라, 조립 결과를 `agent_handoffs` 테이블에 저장. 수정·삭제 가능, AI 루프는 안정된 스냅샷 소비 |
| 계약 | **Pydantic 모델 + `schema_version`** — 회의 거치며 진화 전제. 저장·수정 시 서버가 스키마 검증(422 + 필드별 오류) |
| 전달 시점(노션) | 기준선/장애/회복 각 단계 요약 3벌 + 추가 자료 8종을 **회복 종료 후 한 번에** — 실시간 스트리밍 아님 |
| 조립 | 기존 Protocol+Stub/Real 패턴. DB에서 뽑을 수 있는 것(실험·iteration)은 DB, 외부 것(Istio yaml·이벤트·로그·단계 지표)은 `HandoffSourceService` — Real 구현은 Slice 4·5에서, 지금은 Stub 샘플 |
| 저장소 | **새 테이블** `agent_handoffs` — Experiment 컬럼 추가는 마이그레이션 부재로 기존 DB를 깨뜨리므로 배제. `create_all`의 새 테이블 추가는 안전 |
| up.sh | **불필요** — 전부 Stub으로 동작(`USE_REAL_SERVICES=false`) |

기각한 대안: 즉석 조립형(수정·삭제 불가 → 요구사항 미충족), Experiment 컬럼
확장(기존 DB 파손), 대시보드 페이지 신설(이번 요구는 백엔드/인프라 — UI 아님).

## 1. 전달 데이터 계약 (`app/services/agent/handoff_schema.py`)

빈 Phase 3 디렉토리(`services/agent/`)의 첫 파일. 노션 §2 → Pydantic 매핑:

| 노션 정의 | 스키마 필드 |
|---|---|
| ① 단계별 지표 요약 ×3벌 | `phase_summaries: {baseline, fault, recovery}` — 각 `PhaseSummary` |
| ② Istio 설정 원본 (timeout·retry·CB yaml) | `istio_config: {virtual_service_yaml, destination_rule_yaml}` |
| ② 실험 정보 + 파라미터 허용 범위 | `experiment: {…, params, allowed_ranges}` — 범위는 `chaos_specs.CHAOS_SPECS` 재사용 |
| ② 앱 배포 정보 (replica·probe·리소스) | `deployment_info: {replicas, probes, resources}` |
| ② K8s 이벤트 원본 목록 | `k8s_events: list[K8sEvent]` |
| ② 에러 로그 샘플 ~20개 (중복 제거) | `error_log_samples: list[str]` (max 20) |
| ② R지수 계산 내역 + 목표 R | `r_index: RIndexBreakdown` (0.4·가용성 + 0.3·지연점수 + 0.3·회복속도 항목별) |
| ② 이전 개선 시도 기록 | `improvement_history: list[ImprovementAttempt]` — `AgentIteration`에서 |
| ② LLM 비용 잔여·남은 반복 | `budget: {llm_cost_used_usd, llm_cost_remaining_usd, iterations_remaining}` |

```python
class PhaseSummary(BaseModel):
    rps_avg: float; rps_min: float; rps_max: float
    error_rate_avg: float; error_rate_peak: float          # %
    http_5xx_count: int
    status_code_dist: dict[str, int]                       # {"200": 1234, "503": 17}
    latency_p50_avg_ms: float; latency_p50_peak_ms: float
    latency_p95_avg_ms: float; latency_p95_peak_ms: float
    latency_p99_avg_ms: float; latency_p99_peak_ms: float
    min_ready_pods: int
    restart_count: int
    recovery_seconds: float | None = None                  # recovery 단계만 채움

class ImprovementAttempt(BaseModel):                       # AgentIteration 1행 대응
    iteration: int
    params_before: dict; params_after: dict
    r_index: float | None; verdict: str

class RIndexBreakdown(BaseModel):
    availability: float; latency_score: float; recovery_score: float   # 항목별 0~1
    weights: dict[str, float] = {"availability": 0.4, "latency": 0.3, "recovery": 0.3}
    baseline_r: float | None; current_r: float | None; target_r: float

class AgentHandoffPayload(BaseModel):
    schema_version: str = "1.0"
    experiment: ExperimentInfo        # id·app_name·namespace·chaos_type·status·시각
                                      # + params + allowed_ranges
    phase_summaries: PhaseSummaries   # baseline · fault · recovery
    istio_config: IstioConfig
    deployment_info: DeploymentInfo
    k8s_events: list[K8sEvent]
    error_log_samples: list[str]      # max_length=20
    r_index: RIndexBreakdown
    improvement_history: list[ImprovementAttempt]
    budget: Budget
```

- `model_config = ConfigDict(extra="forbid")` — 오타 필드가 조용히 통과하지 않게.
- 이 모델의 JSON Schema가 곧 팀 공유 계약 — `/docs`에서 자동 노출.

## 2. 저장 (`db/models.py` + `db/repositories.py`)

```python
class AgentHandoff(Base):
    __tablename__ = "agent_handoffs"
    id: int PK
    experiment_id: FK experiments.id
    schema_version: String(10), default "1.0"
    payload: JSON, default dict
    created_at / updated_at: DateTime (_now)
```

`HandoffRepository`: `create` / `get` / `list_for_experiment`(최신순) /
`latest_for_experiment` / `update_payload`(payload 교체 + `updated_at` 갱신) / `delete`.
기존 repository 스타일(생성 즉시 commit) 유지.

## 3. 조립 (`services/agent/assembler.py` + `HandoffSourceService`)

`interfaces.py`에 Protocol 추가 (Real 구현은 Slice 4·5 — 지금은 Stub만):

```python
class HandoffSourceService(Protocol):
    def phase_summary(self, namespace: str, app_name: str, phase: str) -> dict: ...
    def istio_config(self, namespace: str, app_name: str) -> dict: ...      # yaml 문자열 2개
    def deployment_info(self, namespace: str, app_name: str) -> dict: ...
    def events(self, namespace: str, app_name: str) -> list[dict]: ...
    def error_logs(self, namespace: str, app_name: str, limit: int = 20) -> list[str]: ...
```

- `StubHandoffSource`(`services/stubs.py`): 그럴듯한 고정 샘플 반환 — AI 팀이
  실데이터 없이 개발 착수할 수 있는 수준의 형태 충실도가 목적.
- `deps.py`에 `make_handoff_source()` 팩토리 (`use_real_services` 분기, Real은
  Slice 4 전까지 Stub 반환).
- `assemble_handoff(session, source, experiment) -> AgentHandoffPayload`:
  - 단계 요약: `experiment.baseline_metrics` 등 저장값이 비어 있지 않으면 우선,
    비었으면 `source.phase_summary()` (Slice 5 전 기본 경로).
  - `allowed_ranges`: `chaos_specs.CHAOS_SPECS[chaos_type]["fields"]`.
  - `improvement_history`: `IterationRepository.list_for_experiment`.
  - `budget`: `sum(iteration.llm_cost_usd)` + 설정값(`llm_budget_usd`,
    `max_agent_iterations` — `config.py`에 기본값 신설: 5.0 USD / 2회).
  - `r_index`: 저장된 `baseline_r`/`r_index`/`target_r` + Stub 항목별 점수
    (실계산은 Slice 5).

## 4. REST 인터페이스 (`routers/handoffs.py` 신설)

JSON API — 이 레포 최초의 순수 JSON 라우터(기존은 HTML/HTMX). `/docs`에 자동 문서화.

| 메서드·경로 | 동작 |
|---|---|
| `POST /experiments/{exp_id}/handoffs` | 조립 → 스냅샷 저장, 201 + 전체 반환. 실험 없으면 404 |
| `GET /experiments/{exp_id}/handoffs` | 메타 목록(id·schema_version·created/updated_at) 최신순 |
| `GET /experiments/{exp_id}/handoffs/latest` | 최신 스냅샷 전체 — **AI 루프 소비 지점**. 없으면 404 |
| `GET /handoffs/{handoff_id}` | 단건 전체. 없으면 404 |
| `PUT /handoffs/{handoff_id}` | body를 `AgentHandoffPayload`로 검증 후 교체. 위반 시 422 + 필드별 오류 |
| `DELETE /handoffs/{handoff_id}` | 삭제, 204 |

응답 공통 형태: `{id, experiment_id, schema_version, created_at, updated_at, payload}`.
PUT 검증이 FastAPI body 타입으로 자동 수행되므로 라우터는 얇게 유지.
PUT 시 행의 `schema_version`은 페이로드의 `schema_version`으로 동기화.

## 5. 시드·테스트

- `db/seed.py`: seed 실험(`status="running"`)에 핸드오프 스냅샷 1건 생성(assembler
  재사용 — 하드코딩 JSON 금지). 팀원이 `uvicorn` 띄우면 `/docs`에서 바로 예시 확인 가능.
  POST에 실험 status 가드는 두지 않음 — 노션의 "회복 종료 후 전달"은 전달 시점 권고이고,
  스냅샷 생성 자체는 개발·큐레이션 목적상 어느 상태에서든 허용.
- 테스트 (hermetic, conftest가 Stub 강제):
  - 계약: 유효 페이로드 round-trip / `extra="forbid"` 위반 / 로그 21개 초과 거부.
  - assembler: seed 실험 → 유효한 `AgentHandoffPayload` 산출, 저장 metrics 우선 규칙.
  - 라우터: POST 201·404 / GET 목록·latest·단건 404 / PUT 정상·422 / DELETE 204.

## 범위 제외 (YAGNI)

- 대시보드 UI(페이지·템플릿·app.js) 변경 — 준영·시웅 작업 영역.
- Real `HandoffSourceService`(Prometheus/Loki/K8s 실조회) — Slice 4.
- R지수 실계산 — Slice 5. 여기서는 계약 필드와 저장값 전달만.
- LLM 에이전트 루프 자체(LangGraph) — Phase 3.
- 인증·권한, 페이지네이션, 스냅샷 diff/버전 비교.
