# 가설 경로 ↔ 최종 회귀·보고서 통합 — 설계 (2026-09-05)

## 배경·목표

워크플로우 셸(`pages/experiment_detail.html`)의 3단계(최종 회귀 검증)·4단계(결과·보고서)는 `ScenarioRun` 흐름이 담당하는데, 시나리오 스냅샷이 `order-resilience-lab.yaml` 하나에 하드코딩돼 있다(`services/regression.py::scenario_snapshot`이 앱 이름을 검사해 예외). 가설 경로(`HypothesisRun`, 09/02 배선)는 1·2단계까지만 연결돼 있어 nginx 같은 일반 k3s 앱은 최종 R지수 비교·보고서 PDF까지 못 간다.

목표: **가설 경로에서 승인(detailing 완료)된 후보를 회귀 시나리오로 소비**해 nginx에서도 3단계 실행 → 4단계 결과·보고서 다운로드가 되게 한다. `order-resilience-lab`의 기존 YAML 경로는 그대로 동작해야 한다(회귀 방지).

범위 밖: AI 개선 제안·승인(Phase 3), 실시간 메트릭 차트(병행 작업), 대시보드.

## 결정 사항

### 1. 시나리오 스냅샷 조립기 분기
`services/regression.py`:
- 기존 `scenario_snapshot(app_name, selected_ids)` → 내부를 `_snapshot_from_yaml(...)`로 이름만 옮기고 시그니처·동작 유지.
- 신규 `scenario_snapshot_from_hypothesis(run: HypothesisRun, app: App) -> dict`:
  - 대상 = `run.candidates` 중 `detail_status == "detailed"`이고 `params`가 있는 것(현재 구조상 1개; 최소 **1개**로 완화 — YAML 경로의 "2개 이상" 조건은 그대로).
  - 각 후보 → 실험 스펙: `id = f"cand-{candidate.id}"`, `title = candidate.title`, `chaos_type`, `params`(chaos_specs `validate_params` 재검증), `target_selector = {"app.kubernetes.io/name": candidate.target_workload}`, `criteria = DEFAULT_CRITERIA` (아래).
  - `observation = {"service": app.name, "path": app.health_path or "/", "expected_status": 200}` — nginx는 Service명이 앱명과 같고 `health_path="/"`이다. Service명이 다른 앱은 이번 범위 밖(주석으로 명시).
  - `improvements = []` — 가설 경로는 아직 개선 명세가 없다. 회귀는 baseline·final 두 라운드를 **같은 조건**으로 돌리고 보고서에 "적용된 개선 없음"이 정직하게 표시된다(Phase 3에서 채움).
  - 스냅샷 `id = f"hyp-{run.id}"`, `title = run.goal_text or f"{app.name} 복원력 검증"`, `app = app.name`.
- `DEFAULT_CRITERIA` 모듈 상수: `{"max_error_rate_pct": 20, "max_p95_latency_ms": 1500, "max_recovery_seconds": 30, "min_ready_pods": 1}`. `min_ready_pods`는 `nginx` 매니페스트 replicas 2 기준으로 1이 안전. 값은 팀 튜닝 대상이므로 상수 한 곳.
- `_run_one`은 스펙 형태만 같으면 그대로 동작(수정 최소화). `_apply_improvements`는 빈 리스트면 즉시 `[]`.

### 2. 데이터 모델
`db/models.py` `ScenarioRun`에 `hypothesis_run_id: Mapped[int | None] = mapped_column(ForeignKey("hypothesis_runs.id"), nullable=True)` + `relationship()` 추가. 마이그레이션 없음(`create_all`) — CLAUDE.md의 "재기동 전 구 DB 삭제" 항목에 이 컬럼 추가를 한 줄 덧붙인다. `repositories.py` `ScenarioRunRepository`에 `latest_for_hypothesis(run_id)` 추가.

### 3. 라우터
- `POST /scenario-runs`(`routers/scenario_runs.py`): 폼에 `hypothesis_run_id: int | None = Form(None)` 추가. 있으면 `selected_ids` 무시하고 `scenario_snapshot_from_hypothesis`로 조립, `hypothesis_run_id` 저장. 준비 세션(`ExperimentSession`, status ready) 요구는 동일 — 3단계 진입 시 프론트가 기존 `startPreparation`으로 만든다(아래 5).
- `GET /hypothesis/{id}`(`routers/hypothesis.py::_page`): 컨텍스트에 `scenario_run = ScenarioRunRepository.latest_for_hypothesis(run.id)` 추가. `view=verify|result` 허용.
- 보고서 라우트(`routers/reports.py`)·`services/reports.py`는 `ScenarioRun` 기준이라 수정 불필요. `report_context`의 `preparation`·`scenario.title`이 가설 스냅샷으로도 채워지는지 확인만.

### 4. 템플릿 (`pages/experiment_detail.html`)
- 가설 경로 `run` 딕셔너리: `current`를 실험 존재 시 2 → 실험 `completed|failed` 이면 **3**, `scenario_run`이 있으면 3, `scenario_run.status ∈ {completed, failed}` 이면 **4**. `default_view`도 같은 규칙.
- 탭 버튼 disabled 조건에서 `hypothesis_run and loop.index > 2` 툴팁("준비 중")을 제거하고 일반 규칙("현재 실행 단계가 완료된 뒤 열립니다")만 남긴다.
- verify/result 섹션은 이미 `scenario_run` 기준으로 렌더되므로 대부분 그대로. 가설 경로에서 `scenario_run`이 없을 때 verify 섹션에 **"최종 회귀 시작" 버튼**(`data-hypothesis-regression-start`)을 보여준다. 버튼 옆에 실행될 실험 목록(승인 후보 제목·장애 유형)과 기본 판정 기준을 서버 렌더.
- `_hypothesis_execute.html` 하단 버튼 영역: 실험이 종료 상태이면 "최종 회귀로 →"(`data-workflow-go="verify"`) 버튼 추가(이 파셜은 병행 작업이 차트 블록을 **중간**에 넣는다 — 하단 버튼 `<div class="flex justify-between">`만 수정).

### 5. app.js (회귀 영역 함수만)
- `startScenarioRun(root)`: `root.dataset.hypothesisRun`이 있으면 body에 `hypothesis_run_id` 추가(`selected_ids`는 빈 값). URL replaceState는 `/hypothesis/{id}?view=verify&scenario_run_id=…` 형태로.
- 클릭 위임: `[data-hypothesis-regression-start]` → `startPreparation(root)` 성공(ready) 후 `startScenarioRun(root)`. 기존 데모 경로의 `maybePlayExecution` 호출은 건드리지 않는다.
- 페이지 로드 시 `root.dataset.scenarioRunId`가 있고 상태가 종료가 아니면 `watchScenarioRun` 재구독(기존 로직 있으면 재사용).
- `watchExperiments`·`watchHypothesis`·`initCharts`·새로 추가될 `watchLiveMetrics`(병행 작업) 영역 **수정 금지**.

### 6. 실험 목록 (`routers/pages.py::experiments_context`)
가설 Run 행의 "현재 단계"를 `scenario_run` 존재·상태에 따라 3/4로, 판정 요약을 `comparison.verdict` 기준으로 표시(있을 때만). 회귀 결과 R지수는 `comparison.r.after.score`.

## 파일 경계 (병행 작업 충돌 방지)

| 수정 | 파일 |
|---|---|
| 추가·수정 | `app/services/regression.py` · `app/db/models.py`(ScenarioRun만) · `app/db/repositories.py`(ScenarioRunRepository만) · `app/routers/scenario_runs.py` · `app/routers/hypothesis.py` · `app/routers/pages.py` · `app/templates/pages/experiment_detail.html` · `app/templates/partials/_hypothesis_execute.html`(**하단 버튼 div만**) · `app/static/js/app.js`(회귀·워크플로우 함수 영역만) · `tests/test_scenario_runs.py` · `tests/test_hypothesis_api.py` · `tests/test_pages.py` · `CLAUDE.md`(진행 현황 1줄 + DB 삭제 주의) |
| 금지 | `app/services/interfaces.py` · `app/services/stubs.py`(Prometheus) · `app/services/real/prometheus.py` · `app/routers/experiments.py` · `tests/conftest.py` · `tests/test_experiments.py` |

## 테스트

- `scenario_snapshot_from_hypothesis`: detailed 후보 1개로 스펙 형태·criteria·observation 검증, detailed 없으면 `ValueError`.
- `POST /scenario-runs`에 `hypothesis_run_id` → 201, `ScenarioRun.hypothesis_run_id` 저장, 기존 YAML 경로 테스트 그대로 통과.
- `GET /hypothesis/{id}?view=verify` 200 + 시작 버튼 렌더, 회귀 completed 후 `?view=result` 200 + 보고서 링크.
- `pytest -q` 전체 통과.

## 검증 시나리오 (구현 후 수동, Stub)

nginx 가설 생성 → 후보 선택 → 실험 completed → "최종 회귀로" → 3단계에서 "최종 회귀 시작" → 준비 세션 ready → 회귀 진행 SSE → 4단계 결과에 R지수 전후·보고서 보기·PDF 다운로드 링크. `order-resilience-lab` 위저드 경로도 그대로 4단계까지.
