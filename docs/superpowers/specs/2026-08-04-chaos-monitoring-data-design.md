# 카오스 테스트 — 모니터링 표시 데이터 & AI Agent 전달 데이터 설계

- 날짜: 2026-08-04
- 배경: 팀 회의(다음 주 카오스 테스트 사이드바 UI 확정) 준비. ① 모니터링 화면에 보여줄 데이터, ② AI Agent에 넘겨줄 데이터를 정의하고, 이를 기반으로 실험 상세 페이지 목업을 개선한다. ②는 노션(08/04 회의록 하위)에 기록해 팀 공유.
- 범위: **실험 상세 페이지(experiment_detail)만.** 인프라 모니터링 페이지(Slice 4)는 별도.
- 참고: 카오스 도구 공통 표시 요소(AWS FIS·Gremlin·Steadybit·Chaos Mesh 대시보드) — 실험 진행 타임라인, 주입 대상(blast radius), 골든 시그널 메트릭, 안전장치(중단 조건), 이벤트 피드. 여기에 본 프로젝트 차별점인 R지수·AI 루프를 얹는다.

## 데이터 소스 (스택 한정)

| 소스 | 제공 데이터 |
|---|---|
| Istio sidecar (Prometheus) | `istio_requests_total`, `istio_request_duration_milliseconds_bucket` — RPS·에러율·레이턴시 분위수 |
| K8s API | Pod ready/desired, restart 횟수, 이벤트(Killing·Unhealthy·BackOff·OOMKilled 등), Deployment/probe/리소스 설정 |
| Chaos Mesh | CRD 상태·이벤트 (적용/주입 시작/주입 종료/삭제) |
| Loki | 앱 로그 (ERROR/WARN 필터) |

분산 트레이싱은 제외(중간보고서 확정 사항).

## 1. 모니터링 화면 표시 데이터 (B안 — "실험 서사형")

기존 탭 구조(개요·메트릭·AI 루프·개선·로그) 유지. ①③④⑤는 개요 탭, ②는 메트릭 탭.

### ① 실험 단계 타임라인 (기존 유지)
`기준선 측정 → 카오스 주입 → 메트릭 수집 → 회복 감지 → R지수 계산`. 각 단계에 시작 시각·경과 시간. `Experiment.status` 전이와 1:1 매핑.

### ② 골든 시그널 4카드 (메트릭 탭)
- **Request Rate** (req/s) — 트래픽 생존 확인. 소스: Istio.
- **Error Rate** (%) — 5xx 비율. R지수 가용성 항의 원천. 소스: Istio.
- **p99 Latency** (ms) + p50/p95/p99 분위수 카드 — 레이턴시점수 항의 원천. 소스: Istio.
- **Pod Availability** (ready/desired) — 소스: K8s API.
- 각 차트: 시계열 + **baseline 평균 점선 오버레이** + **카오스 주입 구간 음영**. "주입 전 대비 얼마나 나빠졌나"를 한눈에 보이게 하는 것이 핵심.

### ③ 이벤트 피드 (신규)
시간순 통합 타임라인. 차트의 "왜 저기서 꺾였지?"에 대한 답을 같은 화면에서 제공.
- Chaos Mesh: CRD 적용 / 주입 시작 / 주입 종료 / 삭제
- K8s: `Killing`, `Started`, `Unhealthy`(probe 실패), `BackOff`, `OOMKilled`
- 플랫폼: 단계 전환, 수동 중지, AI iteration 시작/종료

### ④ 안전장치 카드 (일부 신규)
- 주입 파라미터 vs 허용 범위(`chaos_specs`: latency 10–10000ms · cpu 1–100% · duration 30–1800s) — 기존
- **자동 중단 조건** 상태 표시 (예: "Error Rate > 50%가 60초 지속 시 자동 중단") — **신규 개념** (AWS FIS stop condition 상당). 목업에서는 표시만, 실제 로직은 후속. 도입 여부는 팀 논의(열린 이슈).
- 수동 중단 버튼 — 기존

### ⑤ R지수 카드
현재 R / baseline R / 목표 R + **구성요소 분해**: `0.4×가용성(__) + 0.3×레이턴시점수(__) + 0.3×복구속도(__)`. "R이 왜 이 값인지" 설명 가능하게.

## 2. AI Agent 전달 데이터

**전달 시점: 단계별 스냅샷.** baseline / fault / recovery 각 단계 종료 시 집계 스냅샷 생성 → recovery 종료 후 스냅샷 3벌 + 컨텍스트 번들을 Observer에 전달해 iteration 시작. (실시간 스트리밍 아님 — 단순·토큰 효율, 현 Experiment 모델의 baseline/fault/recovery_metrics 구조와 일치.)

### A. 단계별 메트릭 스냅샷 (×3벌, 화면 ②와 같은 원천의 집계값)

| 항목 | 내용 |
|---|---|
| 기본 | phase, 시작/종료 시각, duration |
| 트래픽 | RPS 평균·최소·최대 |
| 에러 | error rate 평균·피크, 5xx 건수, 상태코드 분포(2xx/4xx/5xx) |
| 레이턴시 | p50/p95/p99 각각 평균·피크 |
| 가용성 | ready/desired 최소값, pod restart 횟수 |
| 회복 (fault·recovery만) | TTR — 에러율·레이턴시가 baseline 수준으로 복귀까지 걸린 시간 |

### B. 컨텍스트 번들 — 화면에는 없지만 AI에는 넘기는 것

1. **현재 Istio 설정 원본** — VirtualService timeout/retry, DestinationRule circuitBreaker/outlierDetection의 현재 yaml. AI 개선 범위가 정확히 이 3개이므로 최우선.
2. **실험 정의 + 허용 범위** — chaos_type, params, 대상 앱/namespace, `chaos_specs` 허용 범위 → 개선안이 사전 검증 범위를 벗어나지 않도록.
3. **K8s 워크로드 컨텍스트** — replica 수, readiness/liveness probe 설정, 리소스 request/limit → "probe가 느려 회복이 늦다" 류 판단 근거.
4. **K8s 이벤트 원본** — 화면 ③은 요약 피드, AI엔 원본 목록(reason·message·timestamp).
5. **에러 로그 샘플 (Loki)** — fault 구간 ERROR/WARN 중복 제거 후 상위 ~20개. 화면 로그 탭은 스트림 전체, AI엔 선별본(토큰 절약).
6. **R지수 분해** — 단계별 가용성/레이턴시점수/복구속도 값 + 산식(0.4/0.3/0.3) + 목표 R.
7. **이전 iteration 히스토리** — params_before/after, verdict, R 추이 → 동일 개선 반복 방지.
8. **예산/제약** — LLM 비용 잔여, 남은 iteration 수 → 에이전트 종료 판단 근거.

**정리 원칙**: 화면 = 사람이 읽는 추세와 사건(핵심만). AI = 화면 데이터의 집계본 + 판단에 필요한 원본(설정 yaml·이벤트·로그 샘플·히스토리). 프롬프트형 시나리오 생성 방식(자연어 → 시나리오 초안)이 도입돼도 1번(현재 설정)·2번(허용 범위)이 그대로 입력 컨텍스트가 된다.

## 3. 목업 구현 방향 (experiment_detail.html 개선)

- **개요 탭**: 이벤트 피드 카드 신규 · 안전장치 카드 신규 · R지수 카드에 구성요소 분해 바 추가(기존 "현재 상태" 카드 개편)
- **메트릭 탭**: 4개 차트에 baseline 평균 점선 + 주입 구간 음영 (Chart.js 데이터셋 추가 + 간단한 배경 플러그인, 외부 라이브러리 추가 없음)
- **데이터 공급**: mock은 `db/seed.py`에서만(CLAUDE.md 원칙). 이벤트 목록·단계별 스냅샷 mock도 seed 공급. **이벤트 저장 DB 테이블 신설은 보류** — Stub 서비스가 mock 이벤트를 반환하는 형태로 시작. 라이브 시 `ExperimentEvent` 테이블 vs 실시간 조회는 다음 주 회의에서 UI 확정 후 결정(마이그레이션 없는 스키마를 먼저 굳히지 않기 위함).
- 디자인은 tds.css 토큰·컴포넌트 클래스·기존 매크로 준수.

## 열린 이슈 (팀 논의)

1. 자동 중단 조건(stop condition) 도입 여부와 기본값 — 목업에는 표시만.
2. 프롬프트형 시나리오 생성(자연어 → 실험 초안)과의 연계 — 본 설계의 허용 범위·현재 설정 데이터가 입력이 된다는 것까지만 확인, 구조는 AI 파트(준영·시웅) 담당.
3. 이벤트 피드의 영속화 방식 (DB 테이블 vs 조회 시 실시간 합성) — UI 확정 후 결정.

## 테스트

- 목업 단계: 기존 hermetic 테스트 유지(Stub 강제). 신규 카드가 seed 데이터로 렌더되는지 라우터 테스트 추가.
- 스냅샷 스키마는 Phase 3(AI 루프 구현) 시 `services/agent/`에서 구체화 — 본 문서는 필드 정의까지만.
