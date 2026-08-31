# 가설 수립 단계 설계 (2026-08-25 · 2차 개정)

## 목표

실험의 첫 단계 **가설 수립**을 엔드투엔드로 얇게 배선한다: 위저드에서 "후보 생성
요청" → AI가 실험 후보 카드 N개 생성 → 승인 게이트에서 단일 선택(또는 직접 입력)
→ **선택 후 detailing(params 구체화)** → 기존 실험 생성 경로로 실행. 목업(타이머
stub)으로만 있던 후보 화면이 실데이터로 동작하는 것까지가 범위다.

에이전트는 **퓨어 Python + claude 구독제 CLI(`claude -p`)** (ADR-0010). UX 골격은
기존 ADR을 그대로 따른다 — 항상 AI 후보 선택형(ADR-0006), 근거형 카드·단일
선택·후보 도착은 페이지+SSE(ADR-0007).

## 개정 이력

- **1차 (grill 세션)**: params 생성 시점 포함(단일 호출) 확정.
- **2차 (2026-08-25, 시웅 결정)**: **후보 생성 → 선택 후 detailing 2단 구조로 전환**
  (ChaosPilot 구조 채택 — 1차 결정 번복). 하이브리드 품질 장치 1~5 전부 채택.
  선행 작업으로 **장애 유형 9종 확장** 완료(`chaos_specs` 슬러그 키 전환).

## 확정 결정

| 결정 | 내용 |
|---|---|
| 에이전트 위상 | LangGraph 폐기 확정(ADR-0010). `HypothesisAgentService` Protocol 뒤 첫 구현체가 `claude -p` |
| 실행 위치 | 대시보드 호스트에서 subprocess. 호스트에 claude 구독 로그인 전제. EC2 운영 방안은 범위 외 |
| 능력 모델 | **조립 페이로드 → 순수 추론** — 대시보드가 입력 JSON 조립, 에이전트는 도구 없이 JSON만 출력. 클러스터 자격증명 미전달 |
| 대상 환경 | **k3s 먼저** — 저장된 manifest 기반이라 조립이 결정적. 계약은 환경 중립, EKS는 조립기만 추후 추가 |
| **에이전트 구조 (2차 개정)** | **2단 프로세스** — ① `generate`: 서사형 후보 N개(params 없음) ② 사용자가 1개 선택 ③ `detail`: 선택 후보의 params 구체화 → `chaos_specs` 검증 → 실험 생성. 직접 입력은 `concretize`로 후보 1개 합류 후 동일 경로 |
| 장애 유형 | **9종** (선행 작업 완료): network-delay·loss·partition·bandwidth / pod-kill·pod-failure·container-kill / cpu-stress·memory-stress. `allowed_chaos`는 `CHAOS_SPECS`에서 자동 파생 |
| 품질 장치 (하이브리드 1~5 채택) | ① 프롬프트 규칙 5종 ② `(대상, chaos_type)` 중복 후보 폐기 ③ 서사 필드 최소 길이 게이트 ④ `HypothesisRun` 모델 스냅샷 ⑤ manifest 정적 분석 findings를 원문과 *함께* 페이로드 제공 |
| 직접 입력 | **이번 슬라이스 포함** — 자유 텍스트 + 동일 페이로드로 `concretize` 호출, 후보 1개(`source="user_input"`) 카드 합류. 선택 시 동일 detailing |
| 저장 | `HypothesisRun` + `ExperimentCandidate` 신설, `Experiment.candidate_id` FK — 가설↔결과 추적(Slice 5 대비) |
| 신뢰성 | 생성: 검증(아래) + 전멸 시 교정 재시도 1회. detailing: `validate_params` 불통과 시 교정 재시도 1회, 재실패면 후보 `failed`(다른 후보 선택·재시도 가능). 타임아웃 180초/호출 |
| 설정 | 모델 미지정 기본(CLI 기본 모델). `hypothesis_agent`("stub"|"claude", 선택형)·`claude_bin`·`hypothesis_model` 키. 후보 수 기본 5(1~10 클램프) |

기각한 대안: 도구형 탐색(kubectl 읽기 — 재현성·속도·자격증명 부담), 후보 미저장
(이력·추적 포기), 무한 재시도(실패는 유저가 보고 다시 누르는 게 Human-in-the-loop와
일치), 결정론 directives·2-pass 제한 추론·라이브 eligible 게이트(ChaosPilot 비교
문서 참조 — 약한 모델 보상 장치라 미이식). 추론 실시간 스트리밍은 후속 증분.

## 1. 계약 (`app/services/agent/hypothesis_schema.py`)

`handoff_schema.py`와 대칭 — pydantic `extra="forbid"`, `HYPOTHESIS_SCHEMA_VERSION = "1.0"`.

```python
class AllowedChaos(_Strict):          # chaos_specs.CHAOS_SPECS 1종 대응 (9종)
    chaos_type: str                   # 슬러그 (예: network-delay, pod-failure)
    kind: str                         # Chaos Mesh CRD kind
    action: str
    label: str
    fields: dict                      # {name: {min, max, label} | {type: "str", label}}

class ManifestFinding(_Strict):       # 하이브리드 5 — 서버 정적 분석 요약 1건
    workload: str                     # Deployment 이름
    finding: str                      # 예: "replicas: 1 — 단일 파드", "livenessProbe 없음"

class PastExperimentSummary(_Strict): # 같은 앱 과거 실험 1건 — 중복 제안 회피
    chaos_type: str
    params: dict
    status: str
    r_index: float | None

class HypothesisInputPayload(_Strict):
    schema_version: str = HYPOTHESIS_SCHEMA_VERSION
    app: dict                         # name · env · port · health_path
    manifest_yaml: str                # k3s: 저장 원문 그대로 — 요약·파싱으로 정보 깎지 않음
    manifest_findings: list[ManifestFinding]  # 정적 분석 요약 — 원문 대체 아님(하이브리드 5)
    allowed_chaos: list[AllowedChaos] # 가드레일: 이 범위 안에서만 제안
    goal_text: str = ""               # 검증 목표(선택)
    past_experiments: list[PastExperimentSummary]
    candidate_count: int              # 1~10, 기본 5

class CandidateProposal(_Strict):     # 1차(generate/concretize) 출력 1건 — params 없음
    title: str
    chaos_type: str                   # 슬러그
    target_workload: str              # manifest 내 Deployment 이름
    hypothesis: str                   # 가설 한 줄 — 실패 예상형
    expected_impact: str

class DetailingResult(_Strict):       # 2차(detail) 출력 — 선택된 후보 1건의 params
    params: dict                      # chaos_specs.validate_params 통과 필수
    rationale: str = ""               # 값 선정 근거 한 줄(카드 미노출, 이력용)
```

조립기 `assemble_hypothesis_input(session, app, goal_text, candidate_count)`:
App 행 + `CHAOS_SPECS` + `ExperimentRepository`(같은 앱 최신순 요약) +
**manifest 정적 분석**(순수 함수 — yaml 파싱으로 replicas·probe·resources 검사)으로
조립. k3s는 외부 조회가 없어 순수 함수적. EKS 조립기는 추후.

## 2. 저장 (`db/models.py` + `db/repositories.py`)

```python
class HypothesisRun(Base):            # 가설 수립 요청 (GLOSSARY)
    __tablename__ = "hypothesis_runs"
    id / app_id(FK) / goal_text: Text
    candidate_count: int
    status: str                       # generating | ready | failed
    error: Text, default ""
    freeform_status: str, default ""  # "" | generating | failed — 직접 입력 진행 표시
    freeform_error: Text, default ""
    input_payload: JSON               # 스냅샷 — 재현·디버깅용
    model_name: str, default ""       # 하이브리드 4 — 재현성 (CLI가 보고한 모델)
    cli_version: str, default ""      # claude --version
    created_at / finished_at

class ExperimentCandidate(Base):
    __tablename__ = "experiment_candidates"
    id / run_id(FK)
    title / chaos_type / target_workload / hypothesis / expected_impact
    source: str                       # "agent" | "user_input"
    detail_status: str                # proposed | detailing | detailed | failed
    params: JSON, nullable            # detailing 성공 시 채움
    detail_rationale: Text, default ""
    error: Text, default ""
    created_at
```

`Experiment.candidate_id: FK experiment_candidates.id, nullable` 추가.
⚠️ 기존 테이블 컬럼 추가라 구 `chaoslab.db`를 깨뜨림 — 관례대로 재기동 전 DB 삭제.

`HypothesisRepository`: `create_run` / `get_run` / `latest_run_for_app` /
`set_status`(error·finished_at 포함) / `add_candidates` / `get_candidate` /
`list_candidates` / `set_candidate_detail`(status·params·rationale·error).

## 3. 에이전트 서비스 (`interfaces.py` + `services/real/claude_agent.py`)

```python
class HypothesisAgentService(Protocol):
    def generate(self, payload: HypothesisInputPayload) -> list[CandidateProposal]: ...
    def concretize(self, payload: HypothesisInputPayload, user_text: str) -> CandidateProposal: ...
    def detail(self, payload: HypothesisInputPayload, candidate: CandidateProposal) -> DetailingResult: ...
```

- `StubHypothesisAgent`(`stubs.py`): `generate`=고정 후보 3개 즉시 반환,
  `concretize`=user_text 반영 고정 1개, `detail`=chaos_type별 유효 params 고정 반환.
- `ClaudeCliHypothesisAgent`(real, lazy import): subprocess로
  `{claude_bin} -p --output-format json` (+ `--model {hypothesis_model}` 설정 시).
  프롬프트(stdin) = 역할·출력 JSON 스키마 명세 + 페이로드 JSON. **도구 사용 차단**
  플래그로 순수 추론만. 타임아웃 180초. 첫 호출 시 `claude --version` 캡처해
  Run에 모델 스냅샷 기록.
- **프롬프트 규칙 5종** (하이브리드 1 — generate·concretize·detail 공통):
  ① 근거는 페이로드의 사실만 인용, 수치·장애이력 날조 금지 ② 매출 손실·데이터
  유실 등 임팩트 환각 금지 ③ 비전문가용 한국어(용어 미설명 사용 금지 — ADR-0007)
  ④ 제공된 수단으로 고칠 수 있는 약점만("전부 죽이면 당연히 죽는다" 류 배제)
  ⑤ 가설은 실패 예상형. 추가: fault 유형 중복 금지(하이브리드 2).
- **생성 검증**(서비스 밖 공통 함수 — Stub·Real 동일 적용):
  ① pydantic 파싱 → ② `chaos_type ∈ CHAOS_SPECS` → ③ `(target_workload,
  chaos_type)` 중복 후보 폐기(하이브리드 2) → ④ 서사 필드 최소 길이(제목 4자·
  가설/예상 영향 10자, 하이브리드 3) → ⑤ 생존 1개 이상(요청 수 미달 허용).
  전멸 시 검증 에러 요약 덧붙여 **1회만** 재호출, 재실패면 예외.
- **detailing 검증**: pydantic 파싱 → `chaos_specs.validate_params`. 불통과 시
  에러 요약 덧붙여 1회 재호출, 재실패면 후보 `failed`.
- `deps.py`: `make_hypothesis_agent()` 팩토리 — **독립 선택형 게이트 `HYPOTHESIS_AGENT`**("stub"|"claude" — 추후 "codex" 등 구현체 추가 대비)(`use_real_services`(AWS)와 무관, `local_kubeconfig` 선례와 동일 패턴 — 로컬에서 에이전트만 Real 테스트 가능).
- `config.py` 신설: `claude_bin: str = "claude"` · `hypothesis_model: str = ""`
  (비면 CLI 기본 모델) · `hypothesis_timeout_seconds: int = 180`.

## 4. 라우터 + 워처 + SSE (`routers/hypothesis.py`)

builds·experiments의 워처+SSE 패턴 재사용:

| 메서드·경로 | 동작 |
|---|---|
| `POST /hypothesis` | 위저드 제출(app_id·goal·count). k3s 앱 검증 → Run(`generating`) 생성 + 백그라운드 태스크(generate) → 후보 페이지로 이동(HTMX) |
| `GET /hypothesis/{run_id}` | 후보 페이지 — 생성 중이면 진행 표시, `ready`면 카드 1..N + "직접 입력" 폼(마지막 선택지, ADR-0006), `failed`면 에러 + "다시 생성"(새 Run). 선택 후보가 `detailing`이면 해당 카드에 진행 표시 |
| `GET /hypothesis/{run_id}/stream` | 상태 전용 SSE(DB 폴링) — Run status + 후보 detail_status 변화 시 이벤트, app.js가 `htmx.ajax`로 재요청(서버 렌더 단일 소스) |
| `POST /hypothesis/{run_id}/freeform` | 자유 텍스트 → 백그라운드 `concretize` → 생성 검증 → 후보 추가(`source="user_input"`) → 카드로 합류 |
| `POST /hypothesis/{run_id}/select` | candidate_id 승인 → 후보 `detailing` + 백그라운드 태스크: `detail` → 검증 → params 저장(`detailed`) → **기존 실험 생성 경로 호출**(`candidate_id` 연결) → SSE로 실험 화면 이동. 실패 시 후보 `failed` + error(다른 후보 선택 가능) |

백그라운드 태스크: `make_hypothesis_agent()` 재사용, 매 단계 DB 재확인(중지 시
조기종료). detailing 중 앱에 진행 중 실험이 생겼으면(409 조건) 실험 생성 전 중단.

## 5. UI 배선 (`pages/experiments.html` + `app.js`)

- 위저드 제출을 stub 타이머 → `POST /hypothesis`로 교체.
- 후보 화면은 목업 마크업 재사용하되 데이터는 서버 렌더(mock 하드코딩 제거,
  ADR-0007 근거형 필드만 노출 — params·YAML은 카드에 없음. detailing 결과 params는
  실험 상세에서 확인).
- `app.js`에 `watchHypothesis()` — `watchExperiments()`와 동일 구조.

## 6. 시드·테스트

- `db/seed.py`: `ready` Run 1건 + 후보 3개(Stub 조립 재사용, 하드코딩 JSON 금지).
- 테스트(hermetic, conftest가 Stub 강제):
  - 계약: 입력/출력 round-trip · `extra="forbid"` 위반.
  - 조립기: seed 앱 → 유효 페이로드(manifest 원문 + findings + past_experiments).
  - 생성 검증: 범위 밖 chaos_type 폐기 · `(대상, 유형)` 중복 폐기 · 서사 길이
    미달 폐기 · 전멸 → 재시도 1회 → 실패 경로.
  - detailing 검증: 범위 이탈 params → 재시도 → 실패 시 후보 `failed`.
  - 라우터: POST 생성→`generating` / SSE 종료 이벤트 / select → detailing →
    Experiment 생성 + `candidate_id` / freeform → `user_input` 후보 추가 / EKS 앱 400.

## 범위 제외 (YAGNI)

- EKS 조립기(git/values 기반) — 계약만 환경 중립으로 준비.
- 도구형 탐색(에이전트에 kubectl) — 페이로드 부족이 판명되면 증분.
- 추론 실시간 스트리밍(`claude -p --output-format stream-json`) — 후속 증분.
- 실험 묶음·복수 선택(ADR-0007 보류 그대로), 개선 반복 루프(Phase 3 본체).
- EC2에서의 구독 로그인 운영, `handoff_schema.Budget` USD 필드 개정(ADR-0010 결과).
