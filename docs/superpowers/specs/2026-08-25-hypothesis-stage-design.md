# 가설 수립 단계 설계 (2026-08-25)

## 목표

실험의 첫 단계 **가설 수립**을 엔드투엔드로 얇게 배선한다: 위저드에서 "후보 생성
요청" → AI가 실험 후보 카드 N개 생성 → 승인 게이트에서 단일 선택(또는 직접 입력)
→ 기존 실험 생성 경로로 실행. 목업(타이머 stub)으로만 있던 후보 화면이 실데이터로
동작하는 것까지가 범위다.

에이전트는 **퓨어 Python + claude 구독제 CLI(`claude -p`)** (ADR-0010). UX 골격은
기존 ADR을 그대로 따른다 — 항상 AI 후보 선택형(ADR-0006), 근거형 카드·단일
선택·후보 도착은 페이지+SSE(ADR-0007).

## 확정 결정 (grill 세션 2026-08-25)

| 결정 | 내용 |
|---|---|
| 에이전트 위상 | LangGraph 폐기 확정(ADR-0010). `HypothesisAgentService` Protocol 뒤 첫 구현체가 `claude -p` |
| 실행 위치 | 대시보드 호스트에서 subprocess. 호스트에 claude 구독 로그인 전제. EC2 운영 방안은 범위 외 |
| 능력 모델 | **조립 페이로드 → 순수 추론** — 대시보드가 입력 JSON 조립, 에이전트는 도구 없이 후보 JSON만 출력. 클러스터 자격증명 미전달 |
| 대상 환경 | **k3s 먼저** — 저장된 manifest 기반이라 조립이 결정적. 계약은 환경 중립, EKS는 조립기만 추후 추가 |
| params 시점 | **생성 시점에 포함** — 후보에 `chaos_type + params`까지. 선택 후에는 LLM 재호출 없이 기존 경로가 CRD 생성. 카드 노출은 근거형 유지(ADR-0007) |
| 직접 입력 | **이번 슬라이스 포함** — 자유 텍스트 + 동일 페이로드로 2차 호출, 후보 1개 구체화(`source="user_input"`), 동일 검증 후 카드로 합류 |
| 저장 | `HypothesisRun` + `ExperimentCandidate` 신설, `Experiment.candidate_id` FK — 가설↔결과 추적(Slice 5 대비) |
| 신뢰성 | 3단 검증(pydantic → chaos_specs → 최소 1개) + 교정 재시도 1회 + 실패 시 `failed`·수동 재생성. 타임아웃 180초 |
| 설정 | 모델 미지정 기본(CLI 기본 모델). `claude_bin`·`hypothesis_model` 키. 후보 수 기본 5(1~10 클램프) |

기각한 대안: 도구형 탐색(kubectl 읽기 — 재현성·속도·자격증명 부담, 페이로드로
충분한지 먼저 확인), 선택 후 구체화(호출·대기 2번), 후보 미저장(이력·추적 포기),
무한 재시도(실패는 유저가 보고 다시 누르는 게 Human-in-the-loop와 일치).

## 1. 계약 (`app/services/agent/hypothesis_schema.py`)

`handoff_schema.py`와 대칭 — pydantic `extra="forbid"`, `HYPOTHESIS_SCHEMA_VERSION = "1.0"`.

```python
class AllowedChaos(_Strict):          # chaos_specs.CHAOS_SPECS 1종 대응
    chaos_type: str                   # network-delay | pod-kill | cpu-stress
    fields: dict                      # {name: {min, max, default, unit, ...}}

class PastExperimentSummary(_Strict): # 같은 앱 과거 실험 1건 — 중복 제안 회피
    chaos_type: str
    params: dict
    status: str
    r_index: float | None

class HypothesisInputPayload(_Strict):
    schema_version: str = HYPOTHESIS_SCHEMA_VERSION
    app: dict                         # name · env · port · health_path
    manifest_yaml: str                # k3s: 저장 원문 그대로 — 요약·파싱으로 정보 깎지 않음
    allowed_chaos: list[AllowedChaos] # 가드레일: 이 범위 안에서만 제안
    goal_text: str = ""               # 검증 목표(선택)
    past_experiments: list[PastExperimentSummary]
    candidate_count: int              # 1~10, 기본 5

class CandidateProposal(_Strict):     # 에이전트 출력 1건 (근거형 카드 = ADR-0007 필드)
    title: str
    chaos_type: str
    target_workload: str              # manifest 내 Deployment 이름
    hypothesis: str                   # 가설 한 줄
    expected_impact: str
    params: dict                      # chaos_specs.validate_params 통과 필수
```

조립기 `assemble_hypothesis_input(session, app, goal_text, candidate_count)`:
App 행 + `CHAOS_SPECS` + `ExperimentRepository`(같은 앱 최신순 요약)만으로 조립 —
k3s는 외부 조회가 없어 순수 함수적. EKS 조립기는 추후.

## 2. 저장 (`db/models.py` + `db/repositories.py`)

```python
class HypothesisRun(Base):            # 가설 수립 요청 (GLOSSARY)
    __tablename__ = "hypothesis_runs"
    id / app_id(FK) / goal_text: Text
    candidate_count: int
    status: str                       # generating | ready | failed
    error: Text, default ""
    input_payload: JSON               # 스냅샷 — 재현·디버깅용
    created_at / finished_at

class ExperimentCandidate(Base):
    __tablename__ = "experiment_candidates"
    id / run_id(FK)
    title / chaos_type / target_workload / hypothesis / expected_impact
    params: JSON
    source: str                       # "agent" | "user_input"
    created_at
```

`Experiment.candidate_id: FK experiment_candidates.id, nullable` 추가.
⚠️ 기존 테이블 컬럼 추가라 구 `chaoslab.db`를 깨뜨림 — 관례대로 재기동 전 DB 삭제.

`HypothesisRepository`: `create_run` / `get_run` / `latest_run_for_app` /
`set_status`(error·finished_at 포함) / `add_candidates` / `get_candidate` /
`list_candidates`.

## 3. 에이전트 서비스 (`interfaces.py` + `services/real/claude_agent.py`)

```python
class HypothesisAgentService(Protocol):
    def generate(self, payload: HypothesisInputPayload) -> list[CandidateProposal]: ...
    def concretize(self, payload: HypothesisInputPayload, user_text: str) -> CandidateProposal: ...
```

- `StubHypothesisAgent`(`stubs.py`): 고정 후보 3개 즉시 반환. `concretize`는
  user_text를 hypothesis에 반영한 고정 1개. 테스트·`USE_REAL_SERVICES=false` 개발용.
- `ClaudeCliHypothesisAgent`(real, lazy import): subprocess로
  `{claude_bin} -p --output-format json` (+ `--model {hypothesis_model}` 설정 시).
  프롬프트(stdin) = 역할·출력 JSON 스키마 명세 + 페이로드 JSON. **도구 사용 차단**
  플래그로 순수 추론만. 타임아웃 180초.
- 검증 3단은 서비스 밖 공통 함수(라우터/워처에서 Stub·Real 동일 적용):
  ① pydantic 파싱 → ② `chaos_specs.validate_params` (불통과 후보는 폐기) →
  ③ 생존 후보 1개 이상이면 통과(요청 수 미달 허용). 전멸 시 검증 에러 요약을
  덧붙여 **1회만** 재호출, 재실패면 예외.
- `deps.py`: `make_hypothesis_agent()` 팩토리 (`use_real_services` 분기).
- `config.py` 신설: `claude_bin: str = "claude"` · `hypothesis_model: str = ""`
  (비면 CLI 기본 모델) · `hypothesis_timeout_seconds: int = 180`.

## 4. 라우터 + 워처 + SSE (`routers/hypothesis.py`)

builds·experiments의 워처+SSE 패턴 재사용:

| 메서드·경로 | 동작 |
|---|---|
| `POST /hypothesis` | 위저드 제출(app_id·goal·count). k3s 앱 검증 → Run(`generating`) 생성 + 백그라운드 태스크 → 후보 페이지로 이동(HTMX) |
| `GET /hypothesis/{run_id}` | 후보 페이지 — 생성 중이면 진행 표시, `ready`면 카드 1..N + "직접 입력" 폼(마지막 선택지, ADR-0006), `failed`면 에러 + "다시 생성"(새 Run) |
| `GET /hypothesis/{run_id}/stream` | 상태 전용 SSE(DB 폴링) — 종료 상태(`ready`/`failed`) 오면 app.js가 `htmx.ajax`로 재요청(서버 렌더 단일 소스) |
| `POST /hypothesis/{run_id}/freeform` | 자유 텍스트 → 백그라운드 `concretize` → 검증 → 후보 추가(`source="user_input"`) → 카드로 합류 |
| `POST /hypothesis/{run_id}/select` | candidate_id 승인 → 기존 실험 생성 경로 호출(`candidate_id` 연결) → 실험 화면으로 |

백그라운드 태스크: `make_hypothesis_agent()` 재사용, 매 단계 DB 재확인(중지 시
조기종료), 성공 시 후보 저장 + `ready`, 실패 시 `failed` + error.

## 5. UI 배선 (`pages/experiments.html` + `app.js`)

- 위저드 제출을 stub 타이머 → `POST /hypothesis`로 교체.
- 후보 화면은 목업 마크업 재사용하되 데이터는 서버 렌더(mock 하드코딩 제거,
  ADR-0007 근거형 필드만 노출 — params·YAML은 카드에 없음).
- `app.js`에 `watchHypothesis()` — `watchExperiments()`와 동일 구조.

## 6. 시드·테스트

- `db/seed.py`: `ready` Run 1건 + 후보 3개(Stub 조립 재사용, 하드코딩 JSON 금지).
- 테스트(hermetic, conftest가 Stub 강제):
  - 계약: 입력/출력 round-trip · `extra="forbid"` 위반.
  - 조립기: seed 앱 → 유효 페이로드(manifest 원문 포함·past_experiments 반영).
  - 검증: 범위 이탈 후보 폐기 · 전멸 → 재시도 1회 → 실패 경로.
  - 라우터: POST 생성→`generating` / SSE 종료 이벤트 / select → Experiment
    생성 + `candidate_id` / freeform → `user_input` 후보 추가 / EKS 앱 400.

## 범위 제외 (YAGNI)

- EKS 조립기(git/values 기반) — 계약만 환경 중립으로 준비.
- 도구형 탐색(에이전트에 kubectl) — 페이로드 부족이 판명되면 증분.
- 실험 묶음·복수 선택(ADR-0007 보류 그대로), 개선 반복 루프(Phase 3 본체).
- EC2에서의 구독 로그인 운영, `handoff_schema.Budget` USD 필드 개정(ADR-0010 결과).
