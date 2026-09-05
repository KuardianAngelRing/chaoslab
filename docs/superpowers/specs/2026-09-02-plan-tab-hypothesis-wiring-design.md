# 후보 선택 탭 ↔ 가설 수립 라우터 배선 설계 (2026-09-02 · 추천안 승인 → 구현 완료)

## 목표

워크플로우 셸(`pages/experiment_detail.html`)의 1단계 "후보 선택" 탭이 템플릿 하드코딩 후보 3종 대신
`HypothesisRun`/`ExperimentCandidate`를 서버 렌더하고, 선택 → detailing → 실험 시작이 실제
`routers/hypothesis.py`로 이어지게 한다. 별도 페이지였던 `pages/hypothesis.html`은 이 탭이 흡수한다.

## 현재 상태 (2026-09-02)

| 경로 | 데이터 | 비고 |
|---|---|---|
| `GET /experiments/{1,2,3}` 워크플로우 셸 | 후보 3종·실행 샘플·사전 점검 배너 모두 템플릿 하드코딩 | 3·4단계(회귀·결과)는 `ScenarioRun` 실배선 |
| `GET /hypothesis/{run_id}` (`hypothesis.html`) | `HypothesisRun` 후보 카드 + 직접 입력 + 단일 선택 → detailing → `start_experiment` | 라이브 검증 완료(09/01) |
| 위저드 제출(`app.js` `data-candidate-request`) | `order-resilience-lab` → 데모 셸 / 그 외 → `POST /hypothesis` | 두 경로가 갈라짐 |
| `GET /experiments` 목록 | `demo_runs` 하드코딩 3행 — 실제 Experiment·HypothesisRun 미표시 | |

두 경로는 **선택 의미가 다르다**: 데모 셸은 2~3개 다중 선택 → YAML 시나리오 회귀(`regression.scenario_snapshot`,
`order-resilience-lab` 고정·criteria 필요), 가설 경로는 단일 선택(ADR-0007) → 실험 1건.
AI 후보에는 criteria·target_selector가 없어 회귀 모듈이 그대로 소비할 수 없다.

## 확정 대상 결정 (팀 확인 필요 — 추천안 굵게)

1. **셸의 키**: 가설 경로의 워크플로우 셸은 **`HypothesisRun.id`를 앵커**로 한다.
   `GET /hypothesis/{run_id}?view=plan|execute`가 `experiment_detail.html`을 렌더(`hypothesis.html` 삭제).
   `/experiments/{1,2,3}` 데모 라우트는 회귀 경로 전용으로 **이번 슬라이스에서는 손대지 않는다**.
2. **선택 방식**: **단일 선택(ADR-0007 유지)**. 카드는 radio, 하단 CTA "선택한 후보로 실험 시작" →
   `POST /hypothesis/{run_id}/select`. 다중 선택·최대 3개 로직은 회귀 경로에만 남긴다.
3. **선택 후 착지**: detailing → 실험 생성 시 SSE `completed` redirect를 `/experiments`(목록)가 아니라
   **`/hypothesis/{run_id}?view=execute`**로. 2단계 탭은 이 경로에서 **모의 애니메이션 대신 실제 Experiment 카드**
   (장애 유형·대상·detailing params·rationale·status 배지·완료 시 R지수)를 서버 렌더한다.
   개선 반복 루프(6단계 파이프라인 연출)는 Phase 3 — 이 슬라이스에서는 그리지 않는다.
   - 대안: 지금처럼 `/experiments` 목록으로 보내고 2단계는 비활성. 연결은 되지만 셸이 1단계에서 끝난다.
4. **사전 점검 배너**: 하드코딩 "3/3 통과"는 실제 검사가 없으므로 **제거**(2026-06-07 dashboard-honesty 원칙).
   자리는 Run 상태 배너로 대체 — `generating`(진행 표시) / `failed`(에러 + 다시 생성) /
   `ready`(정적 분석 findings N건 · 허용 장애 유형 N종 · 모델명). 게이트 3종(대상 유효성·관측·정리 보장)은
   실제 검사기가 생길 때 다시 넣는다(백로그).
5. **추가 후보 요청**: `data-candidate-generate` → `POST /hypothesis/{run_id}/freeform` 실배선.
   SAMPLE 예시 카드 제거. `freeform_status == generating`이면 카드 목록 끝에 진행 표시, `failed`면 에러 인라인.
6. **실험 목록 워크플로우 행**: `demo_runs` → **`HypothesisRun` 목록 서버 렌더**(앱·목표·상태·후보 수·실험 연결 여부·갱신 시각).
   행 클릭 → `/hypothesis/{id}?view=…`(실험 있으면 execute, 없으면 plan). 데모 셸은 위저드 분기로만 도달.
   - 대안: 이번엔 목록은 그대로 두고 셸만 배선. 단 "실험 현황 보기" 버튼이 데모 행으로 떨어지는 어색함이 남는다.
7. **위저드 분기(`app.js`)**: `order-resilience-lab` → 데모 셸 분기는 **유지**. 회귀 모듈이 가설 후보를 소비할 수
   있게 되면(criteria 부여 방법 논의 후) 분기를 제거한다(백로그).

## 1. 라우터 (`routers/hypothesis.py`)

- `_page()`가 `pages/experiment_detail.html`을 렌더. ctx: `hypothesis_run`, `candidates`, `experiment`,
  `hypothesis_active`, `chaos_labels`, `view`(쿼리 `view`, 기본 = experiment 있으면 `execute` 아니면 `plan`).
- `POST /hypothesis` → `HX-Push-Url: /hypothesis/{id}?view=plan` (기존 동작 유지).
- `GET /hypothesis/{run_id}`에 `view: str = "" ` 쿼리 추가. 허용 밖 값·아직 열리지 않은 단계는 기본 view로 강등
  (템플릿의 기존 `stage_meta.index > run.current` 규칙 재사용).
- `hypothesis_stream`: `redirect`를 `/hypothesis/{run_id}?view=execute`로 변경. 실험 없이 종료(생성 실패·detailing 실패)는
  기존대로 `""` → 같은 페이지 재요청.
- `POST /hypothesis/{run_id}/select`·`/freeform` 응답은 `_page()` 그대로(HTMX가 `#main-content` 스왑).
- 새 저장소 메서드: `HypothesisRepository.list_runs()` (최신순, app 조인) — 목록 행용.

## 2. 템플릿 (`pages/experiment_detail.html`)

셸 상단에서 `run` 메타를 두 소스로 분기(기존 `scenario_run` 분기와 같은 자리):

```
{% if hypothesis_run %}
  run = { code: "HYP-" ~ id, current: 2 if experiment else 1, default_view: ..., badge/status: run.status·experiment.status 기준 }
  제목 = hypothesis_run.goal_text or app.name ~ " 복원력 검증"
{% elif scenario_run %} …기존… {% else %} run_meta 데모 {% endif %}
```

- **1단계 섹션**을 `partials/_hypothesis_plan.html`로 분리. 셸은 `{% if hypothesis_run %}{% include %}{% else %}데모 마크업{% endif %}`.
  partial 내용: 상태 배너(결정 4) → 후보 카드 radio 목록(ADR-0007 근거형 필드: 제목·장애 유형 배지·대상·가설 한 줄·예상 영향·
  `user_input` 배지·detailing 진행/실패 인라인) → 추가 후보 요청 폼(결정 5) → 선택 요약 + CTA.
  카드 마크업은 기존 `workflow-candidate-card` 클래스 재사용. 반복되므로 `macros/components.html`에
  `candidate_card(...)` 매크로를 두고 데모 카드 3종도 같은 매크로로 치환(DRY, 선택 사항).
- **2단계 섹션**: `partials/_hypothesis_execute.html` — Experiment 카드 1장(결정 3). 상태 갱신은 셸에
  `data-experiment-watch="{{ experiment.id }}"`를 달고 기존 `/experiments/{id}/stream` 구독 → 종료 상태 오면
  `htmx.ajax GET /hypothesis/{run}?view=execute` (배지·값은 서버 렌더 단일 소스).
  k3s 준비 패널(`/experiment-sessions`)은 회귀 경로 전용이라 이 경로에서는 렌더하지 않는다
  (`start_experiment`가 전용 ns 배포를 자체 수행, ADR-0009).
- **3·4단계 탭 버튼**: 가설 경로에서는 disabled + title "회귀 검증은 시나리오 실험에서 지원 — 준비 중".
- `pages/hypothesis.html` 삭제.

## 3. 목록 (`pages/experiments.html` + `routers/pages.py`)

- `experiments_page` ctx에 `hypothesis_runs` 추가. `demo_runs` 블록 제거 후 같은 테이블 컬럼(실험 목표·현재 단계·
  선택 실험·판정 요약·최근 갱신·상태)을 Run 필드로 채운다. 판정 요약은 실험이 `completed`면 `R={{ r_index }}`, 아니면 상태 라벨.
- 빈 목록이면 기존 스타일의 빈 상태 카드("새 실험 시작으로 첫 가설을 만들어 보세요").

## 4. JS (`static/js/app.js`)

- `syncWorkflowCandidates`: 셸에 `data-workflow-select-mode="single"`이면 max 로직을 건너뛰고
  `next.disabled = selected < 1`, 요약 문구 단수형. 기존 다중 로직은 그대로(데모 셸).
- CTA는 `hx-post="/hypothesis/{run}/select" hx-include="closest form"` — `[data-workflow-go]` 클릭 핸들러가
  가로채지 않도록 CTA에서 `data-workflow-go` 제거(탭 전환은 SSE redirect가 담당).
- `watchHypothesis()` 재사용: 셸에 `data-hypothesis-run`·`data-hypothesis-active` 부착. 재요청 URL을
  `/hypothesis/{id}?view=현재 view`로(탭 유지).
- `showGeneratedCandidate`·SAMPLE 관련 코드 삭제. `playExecutionDemo`는 데모 셸에만 남긴다
  (`maybePlayExecution`이 `[data-candidate-execution]`을 못 찾으면 자연히 no-op).

## 5. 시드·테스트

- `db/seed.py`: 기존 `ready` Run 1건 + 후보 3개 유지. 목록 행 렌더 확인용으로 충분.
- `tests/test_hypothesis_api.py` 갱신: `GET /hypothesis/{id}`가 워크플로우 셸(탭 4개·후보 제목) 렌더 ·
  `?view=execute`는 실험 없으면 plan으로 강등 · select 후 SSE `completed.redirect == /hypothesis/{id}?view=execute` ·
  `GET /experiments` 목록에 seed Run 표시 · `GET /experiments/1`(데모) 기존 응답 불변.

## 범위 제외 (YAGNI · 백로그)

- 회귀 모듈이 가설 후보를 소비(criteria·selector 부여) → 위저드 분기 제거·다중 선택 통합.
- 개선 반복 루프·6단계 파이프라인 실데이터(Phase 3) · 결과 탭 R지수 추이(Slice 5).
- 사전 점검 게이트 3종의 실제 검사기.
- EKS 앱 가설 수립.
- 실험 목록에 개별 `Experiment`(가설 없이 만든 실험) 행 노출 — 별도 논의.

## 구현 결과 (2026-09-02)

추천안 1~7 그대로. 구현 중 스펙과 달라진 점:

- **§4 JS 삭제 범위 축소**: `showGeneratedCandidate`·SAMPLE 생성 코드는 데모 셸(회귀 경로, 결정 1·7로 미수정)이
  아직 쓰므로 남겼다. 가설 partial은 `data-candidate-generate` 훅을 쓰지 않아(HTMX `hx-post` 직결) 데모 JS와 충돌 없음.
  예시 칩(`data-candidate-prompt-example`)만 재사용.
- **셸 재요청 URL**: `data-hypothesis-refresh="/hypothesis/{id}?view={view}"`를 셸에 달아 `watchHypothesis()`가
  현재 탭을 유지한 채 재요청. 실험 생성 `completed`는 `history.replaceState`로 URL도 `?view=execute`에 맞춤.
- **2단계 실험 카드 SSE**: 새 워처 대신 `watchExperiments()`에 `data-running-exp-refresh`(종료 시 재요청 URL)를
  추가해 재사용. 미지정이면 기존처럼 `/experiments`.
- **목록 ctx 공용화**: `routers/pages.py::experiments_context()`(위저드 apps + 가설 Run 행 + KPI 4종)를
  `experiments.py::_experiments_response`도 사용 — 실험 생성/중지 POST 응답에도 같은 목록이 렌더된다.
  KPI 카드·"총 N건"도 실값(하드코딩 3/1/1/1 제거), "UI 디자인 시안" 배너 제거.
- **테스트 인프라**: sse-starlette 2.2.1의 전역 `AppStatus.should_exit_event`가 첫 루프에 묶여, 스트림을 끝까지
  읽는 테스트 뒤의 스트림 테스트가 깨짐 → `conftest.py` autouse fixture로 매 테스트 초기화.
- 파일: `routers/hypothesis.py`(셸 렌더·redirect) · `routers/pages.py`(목록 ctx) · `routers/experiments.py` ·
  `db/repositories.py`(`list_runs`) · `templates/pages/experiment_detail.html`(가설 분기) ·
  `templates/partials/_hypothesis_plan.html`·`_hypothesis_execute.html`(신규) · `templates/pages/experiments.html` ·
  `templates/pages/hypothesis.html`(삭제) · `static/js/app.js` · `base.html`(캐시 버스트) · 테스트 4파일. pytest 200 통과.
