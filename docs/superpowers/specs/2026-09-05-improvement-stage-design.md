# 개선 단계(휴먼인더루프, Phase 3 착수) — 설계 (2026-09-05)

## 배경·목표

가설 경로의 3단계 최종 회귀는 `improvements: []`라 baseline과 final을 같은 조건으로 돌리고, 보고서에는 "적용된 개선 없음"이 찍힌다(09/05 통합 설계 §1). 회귀 판정 구조 교정(결정 메모 A1+B1+B3)으로 nginx pod-kill baseline이 passed 근처에 오면서 **개선 전후 차이가 판정에 드러날 자리**가 생겼다.

목표: 2단계 실험 종료 후 **AI가 개선안 1~3개를 제안 → 사용자가 승인/편집/제외 → 3단계 회귀가 baseline → 승인 개선 적용 → final**로 돌아가게 한다. 개선은 회귀용 전용 ns의 Deployment에만 적용되며 **앱의 저장 manifest는 건드리지 않는다**(영구 반영은 사용자가 manifest를 재등록 — 백로그).

```
2단계 실험 종료 → [AI 개선안 생성] → 카드 1~3개(diff 미리보기·근거) → 승인/편집/제외
                → 3단계 "최종 회귀 시작" → baseline → 승인 개선 적용(rollout 확인) → final → 보고서(전후 표)
```

범위 밖: Istio timeout/retry/circuitBreaker(중간보고서 확정 범위지만 k3s에 Istio 없음 — **EKS 전용, Real 소스 연결 시 `manifest_patch`와 나란히 `istio_patch` 타입 추가**) · 개선 반복 루프(자동 재제안) · manifest 영구 반영 · `order-resilience-lab` YAML 경로(그대로).

## 결정 사항

### 1. 데이터 (`db/models.py` · `repositories.py` · `database.py`)

**`ImprovementProposal`** (신규 테이블 `improvement_proposals`, `HypothesisRun` 1:N — `create_all`로 생성):

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `run_id` | FK hypothesis_runs | 소속 Run |
| `experiment_id` | FK experiments (nullable) | 제안 근거가 된 2단계 실험 |
| `type` | str | `"deployment_env"` \| `"manifest_patch"` |
| `title` | str | 카드 제목(에이전트 산출, 예: "readinessProbe 주기 단축") |
| `deployment` / `container` | str | 대상. `manifest_patch`에서 `spec.replicas`만 바꾸면 `container=""` |
| `key` / `value` | str | `deployment_env` 전용 |
| `patch` | JSON | `manifest_patch` 전용 — Deployment 루트 기준 strategic merge patch (아래 §3) |
| `rationale` | Text | 실험 근거(페이로드 사실 인용) |
| `expected_effect` | Text | 기대 효과 한두 문장 |
| `status` | str | `proposed` \| `approved` \| `rejected` |
| `source` | str | `agent` \| `user_edit`(승인 시 편집됨) |
| `created_at` | | |

**`HypothesisRun`** 컬럼 추가(`freeform_status` 선례): `improvement_status`(`""` \| `generating` \| `ready` \| `failed`) · `improvement_error`(Text). SQLite 구 DB는 `database._upgrade_hypothesis_runs`(ALTER, `_upgrade_scenario_runs`와 동일 패턴)로 보완 → **구 DB 삭제 불필요**.

`HypothesisRepository`에 `list_proposals(run_id)` · `replace_proposals(run_id, experiment_id, proposals)`(재생성 시 기존 행 삭제 후 삽입) · `set_improvement(run, status, error="")` · `decide_proposals(run_id, approved_ids, edits)` 추가.

위저드의 "개선 반복" 입력(`max_improvements`)은 **반복 횟수** 의미라 이번 제안 개수와 다르다 — 그대로 두고 제안 개수는 `_MAX_PROPOSALS = 3` 상수.

### 2. 생성 — `HypothesisAgentService.propose_improvements(payload, feedback="") -> list`

계약(`services/agent/hypothesis_schema.py`에 추가 — 같은 에이전트의 3번째 단계이므로 파일 분리 안 함):

- `ImprovementInputPayload(_Strict)`: `schema_version` · `app`{name, env, port, health_path} · `manifest_yaml`(원문) · `manifest_findings` · `candidate`{title, chaos_type, target_workload, hypothesis, params} · `experiment`{id, status, r_index, started_at, finished_at} · `phase_summaries`{baseline, fault, recovery: dict — 저장 `*_metrics` 그대로, 없으면 `{}`} · `allowed_improvements`(§3 화이트리스트를 에이전트에 설명하는 구조 — `chaos_specs`의 `allowed_chaos`와 같은 역할) · `max_proposals`(1~3).
- `ImprovementProposalOut(_Strict)`: `title` · `type` · `deployment` · `container=""` · `key=""` · `value=""` · `patch: dict = {}` · `rationale` · `expected_effect`.

조립기 `services/agent/improvement_assembler.py::assemble_improvement_input(session, run, experiment)` — 순수(외부 조회 없음): Run의 `input_payload`에서 manifest·findings 재사용, 승인 후보·실험 행에서 나머지.

> 핸드오프 노트의 "핸드오프 계약(`/handoffs/latest`) 입력"은 **부분 채택**: 핸드오프의 `phase_summaries`는 그대로 싣되 `istio_config`·`deployment_info`·`k8s_events`·`error_log_samples`는 **싣지 않는다**. k3s에서 `make_handoff_source()`는 Stub이라 그 값이 섞이면 프롬프트 규칙 1("페이로드 사실만 인용")을 스스로 깨게 된다. Deployment 정보는 manifest 원문에 있다. EKS Real 소스가 붙으면 그때 통째로 싣는다.

검증 `services/agent/hypothesis_validation.py`에 `validate_proposals(raw_list, manifest_yaml) -> (survivors, errors)` + `run_proposing(agent, payload) -> list[ImprovementProposalOut]`(전멸 시 교정 재시도 1회 — `run_generation`과 동일 패턴). 제안 단위 폐기: pydantic → `improvement_specs.validate_improvement`(§3) → manifest에 `deployment`·`container` 존재 → (deployment, type, key 또는 patch 지문) 중복 폐기 → 생존 1개 이상. `max_proposals` 초과분은 잘라낸다.

- **Stub** (`stubs.StubHypothesisAgent`): manifest 첫 Deployment·첫 컨테이너에 대해 결정적 2안 — ① readinessProbe: 이미 있으면 `periodSeconds: 2, failureThreshold: 2`, 없으면 `tcpSocket: {port: 컨테이너 첫 포트(없으면 app.port)}` 포함해 추가 · ② `lifecycle.preStop.sleep: {seconds: 5}`(종료 신호 후 유예 — 롤링/파드 종료 시 요청 유실 완화).
- **claude** (`real/claude_agent.py`): 기존 `_RULES` + 출력 스키마 + `allowed_improvements` 설명을 프롬프트로, JSON 배열 파싱. 도구 차단 동일.

### 3. 허용 범위 화이트리스트 — `services/improvement_specs.py` (순수, chaos_specs 대응)

`validate_improvement(raw: dict) -> (normalized: dict, errors: list[str])`:

- `deployment_env`: `deployment`·`container`·`key`(`^[A-Z][A-Z0-9_]*$`)·`value`(str, 200자 이하) 필수. (기존 YAML 경로 `_IMPROVEMENT_KEYS`도 이 함수로 검증하도록 통일.)
- `manifest_patch`: `patch`는 Deployment 루트 dict이고 허용 경로 밖 키가 있으면 거부.
  - `spec.replicas`: int 1~10
  - `spec.template.spec.containers[]`: 각 항목 `name` 필수, 그 외 키는 다음만
    - `readinessProbe` / `livenessProbe`: `initialDelaySeconds`·`periodSeconds`·`timeoutSeconds`·`successThreshold`·`failureThreshold`(int 1~300) + 핸들러 `httpGet{path, port}` / `tcpSocket{port}` / `exec{command: list[str]}` 중 최대 1개
    - `lifecycle.preStop`: `sleep{seconds: 1~60}` 또는 `exec{command}` 중 1개
    - `resources.requests|limits`: `cpu`·`memory` — k8s quantity 정규식(`^\d+(\.\d+)?(m|Mi|Gi|M|G|Ki)?$`)
  - `env`는 `manifest_patch`에서 **거부**(→ `deployment_env` 타입 사용 — 타입 간 중복 경로 없음)
- `ALLOWED_IMPROVEMENTS`: 위 규칙의 선언형 요약(에이전트 페이로드 `allowed_improvements`에 실림).
- `flatten_patch(patch) -> list[str]`: 점 경로 목록(`spec.template.spec.containers[nginx].readinessProbe.periodSeconds`) — UI diff·보고서 표·중복 지문에 공용.
- `project(deployment_dict, patch) -> dict`: patch와 같은 모양으로 **원본 값을 뽑은 dict**(없는 경로는 `None`). 컨테이너는 `name`으로 매칭. 카드의 "전(manifest 원문) → 후(patch)" 미리보기와 Real의 `before` 기록·롤백 패치(§4)에 공용.

### 4. 적용 — `K3sWorkloadService.patch_deployment` (Protocol + Stub + Real)

```python
def patch_deployment(self, namespace: str, deployment: str, patch: dict, timeout_s: int = 180) -> dict:
    """strategic merge patch → rollout 완료 대기. {"type": "manifest_patch", "deployment", "patch",
    "before": project(원본, patch), "after": project(적용 후, patch), "rollout_ready": True}"""
```

- **Real** (`real/k3s_workload.py`): `read_namespaced_deployment` → `sanitize_for_serialization`으로 dict → `before = project(...)` → `patch_namespaced_deployment(body=patch)`(SDK 기본 content-type이 strategic-merge) → rollout 대기(기존 `apply_deployment_env`의 루프를 `_wait_rollout(apps, ns, name, timeout_s)`로 추출해 공용) → 재조회해 `after`. `before == after`면 패치 없이 반환(no-op).
- **롤백**: strategic merge patch에서 값 `null`은 필드 삭제이므로 **`before` 프로젝션이 곧 롤백 패치**다(없던 probe를 추가했으면 `readinessProbe: null`로 제거). `regression._apply_improvements`의 예외 경로에서 `patch_deployment(ns, name, change["before"])`.
- **Stub**: `patches[(ns, deployment)]`에 누적 저장, `before`는 직전 저장값 프로젝션(없으면 None), `after`는 patch.
- `regression._apply_improvements`: `spec["type"]` 분기(`deployment_env` → 기존 · `manifest_patch` → 위). 변경 기록에 `id`·`title`·`reason`·`applies_to` 병합은 동일. 진행 메시지는 `title` 사용.

### 5. 스냅샷 — `regression.scenario_snapshot_from_hypothesis`

`improvements` = Run의 **approved** 제안을 `validate_improvement`로 재검증한 명세 목록:
`{"id": f"imp-{p.id}", "type", "title", "deployment", "container", "key", "value", "patch", "reason": p.rationale, "applies_to": [모든 실험 id]}`. 승인분이 없으면 `[]`(현재 동작). `_snapshot_from_yaml`의 개선 검증도 같은 함수로 통일.

### 6. 라우터 — `routers/hypothesis.py`

| 라우트 | 동작 |
|---|---|
| `POST /hypothesis/{id}/improvements` | 생성 트리거. 409: 실험이 종료 상태(`completed`/`failed`)가 아님 · 이미 `generating` · 이 Run의 `ScenarioRun`이 존재. `improvement_status=generating` → 백그라운드 `_watch_improvements(run_id)` → `_page` |
| `POST /hypothesis/{id}/improvements/approve` | 폼 `proposal_ids`(checkbox 복수, 비면 전부 제외) + `patch_{pid}`(manifest_patch 편집 JSON) / `value_{pid}`(env 편집). 편집분은 `validate_improvement` 재검증 — 실패 시 422 대신 카드에 오류 렌더(`_page`에 `improvement_form_errors` 전달). 선택 → approved, 나머지 → rejected. 409: `ScenarioRun` 존재 |

`_watch_improvements`: `SessionLocal` 직접(기존 워처 패턴) → `assemble_improvement_input` → `run_proposing` → `replace_proposals` → `ready`; 예외 → `failed`+error.

SSE `/hypothesis/{id}/stream`: 활동 정의 확장 — `_is_active`에 `improvement_status == "generating"` 포함하고, **실험이 있어도** 개선 생성 중이면 활성. 스냅샷에 `improvements: status` 추가. 종료 redirect: 실험 있음 + 개선 생성 끝 → `?view=verify`, 그 외 기존(`?view=execute`). `_page`의 `hypothesis_active` 계산도 같은 규칙 → 기존 `watchHypothesis()`(`data-hypothesis-active`) 재구독 그대로 동작, app.js 수정 없음.

`POST /scenario-runs`(`routers/scenario_runs.py`): 변경 없음 — 스냅샷 조립기가 승인분을 읽는다. 단 가설 경로에서 `improvement_status == "ready"`이고 **미결(proposed) 제안이 남아 있으면 422**("개선안을 승인하거나 제외해 주세요") — 실수로 개선 없이 도는 것을 막는다.

### 7. UI — `partials/_hypothesis_improve.html` (3단계 상단 패널)

셸 `experiment_detail.html` verify 섹션의 `data-hypothesis-regression-setup` 카드 **위**에 include(가설 경로 + `scenario_run` 없음일 때만). 상태별 서버 렌더:

- `""`(미요청): 카드 "AI 개선안 제안" — 실험 요약 한 줄(장애 구간 오류율·최소 Ready·회복 시간) + 버튼 `hx-post=/hypothesis/{id}/improvements`. 실험이 `failed`여도 허용(원인 개선이 목적).
- `generating`: 스피너 카드(후보 생성 중 카드와 동일 톤) — SSE로 갱신.
- `failed`: 오류 + "다시 생성".
- `ready`: `<form data-improvement-form>` 안에 제안 카드(후보 선택 탭의 `workflow-candidate-card` 마크업 재사용, **checkbox**): 제목 · `badge-info` 타입 라벨(`환경변수`/`매니페스트 패치`) · 대상 `deployment/container` mono · **변경 미리보기 표**(`flatten_patch` 경로별 `전(manifest) → 후`; env는 key: `전 → 후`) · 근거 · 기대 효과 · 상태 배지(`승인됨`/`제외됨`). `<details>` "편집"에 patch JSON textarea(`patch_{id}`) 또는 value input. 하단 버튼 2개: **"선택 항목 승인"**(`hx-post=…/approve`, `hx-include=[data-improvement-form]`) · **"개선 없이 진행"**(같은 라우트, `hx-vals='{"none": "1"}'`). 결정 후에는 카드가 잠기고(`disabled`) "다시 결정" 링크로 재열람.

기존 "승인 후보로 최종 회귀 조립" 카드의 설명 문구를 상태에 맞게: 승인 N건 → "승인한 개선 N건을 baseline 뒤에 적용해요" / 0건 → 현재 문구. 미결 제안이 있으면 "최종 회귀 시작" 버튼 `disabled` + title 안내(서버 렌더).

`app.js`: 체크박스 카드 시각 동기화는 기존 `syncWorkflowCandidates`가 `[data-workflow-candidate]`를 잡으므로 **속성 재사용**으로 끝 — 다만 그 함수는 단일/다중 선택 모드·다음 버튼을 셸 기준으로 계산하므로 개선 카드에는 `data-improvement-candidate`를 따로 두고 체크 시 `.selected` 토글만 하는 위임 분기 1개 추가(전역 리스너 1개 원칙). `base.html` `?v=` → `improve-1`.

### 8. 보고서 — `report_writer.deterministic_report` · `reports/company_scenario_report.html`

- `changes` 항목이 `manifest_patch`면 표를 경로 단위 행으로: `flatten_patch` 경로마다 `before → after`(reports.py `report_context`에 `change_rows(change) -> [{path, before, after}]` 도우미 — `improvement_specs.flatten_patch`+`project` 조합, UI 미리보기와 같은 함수).
- `deterministic_report`의 `improvement_explanation` 문장: env는 기존 문장, patch는 "`{deployment}`의 `{경로}`를 `{before}`에서 `{after}`로 변경하고 rollout Ready를 확인했습니다"(경로마다 1문장). LLM 경로(`_validate_content`)의 숫자 검증은 facts에 before/after가 포함되므로 그대로 통과.

## 파일 경계

| 수정 | 파일 |
|---|---|
| 추가 | `app/services/improvement_specs.py` · `app/services/agent/improvement_assembler.py` · `app/templates/partials/_hypothesis_improve.html` · `tests/test_improvement_specs.py` · `tests/test_improvements_api.py` |
| 수정 | `app/db/models.py` · `app/db/repositories.py` · `app/db/database.py` · `app/services/interfaces.py`(`K3sWorkloadService.patch_deployment` · `HypothesisAgentService.propose_improvements`) · `app/services/stubs.py`(두 Stub) · `app/services/real/k3s_workload.py` · `app/services/real/claude_agent.py` · `app/services/agent/hypothesis_schema.py` · `app/services/agent/hypothesis_validation.py` · `app/services/regression.py` · `app/services/report_writer.py` · `app/services/reports.py` · `app/routers/hypothesis.py` · `app/routers/scenario_runs.py`(미결 422 1곳) · `app/templates/pages/experiment_detail.html`(verify 섹션 include·문구·disabled) · `app/templates/reports/company_scenario_report.html`(changes 표) · `app/static/js/app.js`(위임 분기 1개) · `app/templates/base.html`(`?v=`) · `tests/test_scenario_runs.py` · `tests/test_hypothesis_api.py` · `tests/test_stubs_contract.py` · `CLAUDE.md`(진행 현황) |
| 금지 | `app/routers/experiments.py` · `app/services/observations.py` · `app/services/resilience.py` · `app/services/r_index.py` · `real/chaos.py` · `real/local_prometheus.py` |

## 테스트

- `improvement_specs`: 허용 패치 정규화 · `env` 경로/`spec.strategy`/미지 키 거부 · replicas 범위 · quantity 형식 · 핸들러 2개 거부 · `flatten_patch`·`project`(컨테이너 name 매칭, 없는 경로 None).
- `hypothesis_validation`: `validate_proposals` — manifest에 없는 deployment 폐기 · 중복 지문 폐기 · 전멸 시 재시도 1회 후 예외.
- Stub 계약(`test_stubs_contract`): `propose_improvements` 출력이 검증 통과 · `patch_deployment` 반환 키.
- `regression`: 승인 제안 → `scenario_snapshot_from_hypothesis().improvements` 반영(미승인·제외는 제외) · `_apply_improvements`가 `manifest_patch`를 `patch_deployment`로 적용, 두 번째 적용 실패 시 첫 변경을 `before`로 롤백 · YAML 경로 회귀 테스트 그대로 통과.
- 라우터: 생성 409 조건 3종 · `_watch_improvements` ready/failed · approve(선택·편집·전부 제외) → 상태 저장 + 페이지 렌더(배지) · 미결 상태 `POST /scenario-runs` 422 · SSE 스냅샷에 `improvements` + redirect `?view=verify`.
- `pytest -q` 전체 통과(현재 228).

## 라이브 검증 (k3s nginx, 브라우저)

1. 위저드 → `claude` 후보 → pod-kill 선택 → 2단계 실험 completed.
2. 3단계 "AI 개선안 제안" → 카드 1~3개(예: readinessProbe periodSeconds 단축 · preStop sleep) → 1개 승인, 나머지 제외.
3. "최종 회귀 시작" → 준비 세션 ready → baseline → 개선 적용 진행 메시지 → final. 적용 확인:
   ```bash
   kubectl get deploy nginx -n chaoslab-session-nginx-N -o jsonpath='{.spec.template.spec.containers[0].readinessProbe}'
   ```
4. 4단계 보고서 HTML/PDF "개선 조치 및 적용 현황" 표에 경로별 전후 값. R지수 전후(개선 효과는 클러스터 특성상 미미할 수 있음 — 판정이 아니라 **적용·기록 경로**가 검증 대상).
5. 실패 롤백 확인(선택): 편집으로 잘못된 이미지 없는 probe 포트를 넣어 rollout 타임아웃 → `failed` + 이전 변경 롤백 로그.
