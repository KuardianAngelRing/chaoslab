# 대시보드 정직화 + 비주얼 polish — 설계

날짜: 2026-06-07 · 범위: **대시보드 한 페이지(`pages/dashboard.html`)** 한정

## 목표

대시보드는 비주얼 완성도는 높으나 **하드코딩 가짜 데이터로 가득**하다(틀린 Phase 표기, 존재하지 않는 Supabase, 가짜 비용/지표/활동). CLAUDE.md 규칙 "템플릿 하드코딩 금지 / mock은 seed"를 위반한다.

이 작업은 **가짜를 지우는 것이 아니라 seed/DB로 이동**시켜, 데모가 여전히 꽉 차 보이되 모든 숫자가 DB에서 추적 가능하게 만든다(접근 A: seed 기반 정직화). 동시에 빈 상태·죽은 버튼·라벨 버그 등 비주얼을 정리한다.

**비목표:** 전면 리디자인, 다른 5개 페이지, 실 클러스터 연동(real 모드), Slice 3~5 기능 구현.

## 핵심 내러티브 (정직화의 축)

대시보드 중앙은 **"진행중 실험(`running[0]`) 한 건"을 설명하는 단일 카드**다 — 진행중 실험 정보와 AI Agent 분석을 **하나의 `tds-card`로 합친다**(사용자 요청 9):

- 카드 상단 = `running[0]`의 app·chaos_type + 경과 시간 + fault/baseline 지표 + R지수 차트
- 카드 하단(같은 카드 내 구분 섹션) = 같은 `running[0]`의 **최신 iteration**의 observer/analyst/recommender

→ 진행중 실험이 없으면 **카드 전체가 empty-state**로 빠진다(가짜 spring-boot-demo 폴백 제거).

레이아웃: 기존 "3열 그리드(실험 2칸 + AI 1칸)"를 **풀폭 단일 카드**로 교체. **반응형**: wide(xl+)=좌우 2열(좌 실험 지표·차트 / 우 AI 진단), narrow=상하 적층. 사이는 구분선(`border-t` 또는 세로 `border-l`)으로 묶음 시각화.

### 합친 카드 최종 구조 (확정: "최신 진단 크게 + 차트가 이력")

```
┌─ 🧪 {app} · {chaos_type} ──────────── ⏱ {elapsed}분 ─┐
│ 주입: {params 요약 예: delay 200ms · 5m}              │   ← (1) iteration N/10 줄 제거, (2) "주입 중" 배지 제거
│ ┌─에러율─┐┌─p99──┐┌─R지수─┐                          │
│ │ 2.1%  ││ 412ms ││ 0.65▲ │  ← fault vs baseline 비교 │
│ └──────┘└─────┘└──────┘                          │
│ [ R지수 추이 차트  baseline→iters ]                   │
│┈┈┈┈┈┈ AI 진단 (Phase3·seed) ┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈│   ← 구분선
│ 👁 관찰  {latest_iter.observer_output}                │
│ 💡 가설  {latest_iter.analyst_output}                │
│ ✨ 권고  {latest_iter.recommender_output}             │   ← (3) 자동적용+재실험 버튼 제거
└──────────────────────────────────────────────────────┘
```

- 좌측 = 주입 파라미터 + 3 지표박스(fault_metrics vs baseline_metrics 비교 표기) + R지수 추이 차트
- 우측(또는 하단) = AI 진단: **최신 iteration**의 관찰(👁 observer)/가설(💡 analyst)/권고(✨ recommender) 3행. 상단에 "Phase 3 예정 · seed 예시" 배지
- 과거 iteration 흐름은 별도 타임라인 없이 **R지수 추이 차트가 이력 역할**
- **자동 적용 + 재실험 버튼 삭제** (Phase 3 액션, 무의미)
- "주입 중" 상태 배지 삭제(상태는 헤더 "N분 경과"로 충분), iteration 카운트 줄 삭제

## 데이터 출처 (이미 존재)

- `Experiment`: chaos_type, params, status, baseline_r, r_index, target_r, `baseline_metrics`/`fault_metrics`(JSON), iterations
- `AgentIteration`: iteration, observer/analyst/recommender_output, r_index, verdict, `llm_cost_usd`, created_at
- `App`/`Build`: name, framework, status, current_sha, created_at / status, image_tag, started_at
- `k8s.components()` → Prometheus/Grafana/Loki/Chaos Mesh/ArgoCD, `k8s.nodes()` → 노드 목록

## 요소별 처리

사용자 확정 지시(번호=요청 항목):

| # | 요소 | 처리 |
|---|---|---|
| 1 | Hero "졸업과제 · Phase 4" 문구 | **완전 제거** (Phase 2로 바꾸지 않고 줄 자체 삭제) |
| 2 | "대시보드 👋" 손 이모지 | **제거** → "대시보드" |
| 3 | Hero 부제 "현재 ~ 개선하고 있어요" | **완전 제거** |
| 4 | 새로고침 옆 "새 실험 시작" 버튼 | **제거** (새로고침 버튼은 유지, `hx-get="/"` 연결) |
| 5 | KPI 배포된 앱 "+1 어제 대비" 배지 | **제거** |
| 6 | KPI "활성 실험" | 라벨 → **"진행중인 실험"**, 배지 "진행 중" → **"{N}분 경과"**(`running[0].started_at` 기준 경과분; 없으면 배지 생략) |
| 7 | KPI 평균 R지수 "+0.29" 배지 | **제거** (라벨은 "최근 R 지수"로 정정) |
| 8 | KPI "이번 세션 LLM 비용" | 라벨 → **"총 소요된 LLM 비용"**, 값 = `Σ llm_cost_usd` 실합계, **"$5.00 한도" 제거** |
| 9 | 진행중 실험 + AI Agent 분석 | **하나의 풀폭 카드로 합침** (위 "합친 카드 최종 구조" 참조) |
| 10 | 진행중 실험 "Iteration 4/10" 줄 | **줄 자체 제거**. 헤더는 app·chaos_type·경과시간만 |
| 11 | "주입 중" 상태 배지 | **제거** (상태는 "N분 경과"로 충분) |
| 12 | rIndexChart `[0.42..]`(app.js 하드) | 캔버스 `data-series`로 iteration r_index 주입 → app.js가 읽음. 데이터 없으면 차트 미렌더 |
| 13 | 에러율 2.1%·p99 412ms·현재R | seed에 baseline/fault_metrics 보강 후 실렌더(fault vs baseline 비교). R은 `running[0].r_index` |
| 14 | AI 분석 텍스트 | `running[0]` 최신 iteration observer/analyst/recommender(관찰/가설/권고) + "Phase 3 예정 · seed 예시" 배지 |
| 15 | 자동적용+재실험 버튼 | **삭제** (Phase 3 액션, 무의미) |
| 16 | 최근 활동 4개 | DB 조립(아래) |
| 17 | 시스템 상태(+Supabase, sidecars) | components()+nodes()로 구동, Supabase 제거, "sidecars"→노드 수 |

## 최근 활동 — DB 조립 (전용 테이블 없이)

라우터에서 최근 항목을 모아 시각 역순 상위 5개:
- **빌드**: `Build` (image_tag, status, started_at) → "{app} 새 SHA {tag} 배포"
- **실험**: `Experiment` (chaos_type, status, started_at) → "{app}에 {chaos_type} 주입"
- **앱 등록**: `App.created_at` → "{app} 신규 등록"

각 항목 `{icon, text, ts, badge}` dict로 정규화 → `created_at`/`started_at` 역순 정렬 → `[:5]`.
seed timestamp가 전부 `now()`라 순서는 대략적이나 **전부 실데이터**. 활동 없으면 empty-state.

> 구현 위치 판단: 조립 로직은 라우터에 인라인하지 않고 작은 헬퍼(예: `pages.py` 내 `_recent_activity(session)`)로 분리해 dashboard 핸들러를 얇게 유지.

## 라우터 변경 (`routers/pages.py::dashboard`)

추가 context:
- `running_exp = running[0] if running else None`
- `iterations = running_exp.iterations` (정렬: iteration asc)
- `latest_iter = iterations[-1] if iterations else None`
- `r_series = [running_exp.baseline_r] + [it.r_index for it in iterations]` (차트용)
- `elapsed_min` = `running_exp.started_at` ~ 현재의 분(항목 6 배지용). 라우터에서 `datetime.now(timezone.utc) - started_at` → 분. 없으면 None
- `llm_cost_total = sum(it.llm_cost_usd for it in 모든 iteration)` — `IterationRepository`에 합계 메서드 또는 라우터 집계
- `components = k8s.components()`, `node_count` (이미 있음, 라벨만 수정)
- `recent = _recent_activity(session)`

> `running_count` KPI 배지는 더 이상 "진행 중" 정적 텍스트가 아니라 `elapsed_min`("N분 경과")을 표시.

## seed 보강 (`db/seed.py`)

기존 running 실험에:
- `baseline_metrics={"error": 0.3, "p99": 89}`, `fault_metrics={"error": 2.1, "p99": 412}` 추가
- iteration `llm_cost_usd`는 이미 0.012 — 유지(KPI 비용 합계 = 0.036)

> seed 값은 기존 목업 수치(2.1%/412ms)를 그대로 옮겨 화면 인상 유지.

## app.js 변경 (`rIndexChart`)

`initCharts()`의 하드코딩 `data: [0.42..]` 제거 → 캔버스의 `data-labels`/`data-series` 속성을 읽어 구성. 속성 없거나 빈 배열이면 차트 생성 스킵(empty-state는 템플릿이 처리). 다른 차트(`agentRChart2` 등)는 이 페이지 범위 밖이므로 불변.

## 비주얼 polish (한정)

- **empty-state 3종**: 진행중 실험 없음(합친 단일 카드 전체), iteration 없음(차트 자리), 앱 0개(KPI/활동)
- 가짜 delta 배지 제거(+1/+0.29) 후 KPI 헤더 정렬 일관성 — 배지 자리 비면 헤더 레이아웃 깨지지 않게 정리
- 시스템 상태 행: components() 길이에 맞춰 동적 렌더
- 합친 카드 반응형: `grid xl:grid-cols-2`(좌우) → 좁으면 1열 적층, 구분선 방향도 전환(`xl:border-l xl:border-t-0`)

## 추가: 사이드바 수정 (대시보드 외, 같은 UI 패스)

### S1. nav active 하이라이트가 HTMX 이동 시 안 옮겨짐 (버그)

원인: `_sidebar.html`이 `base.html`에서 `#main-content` **바깥**에 위치. 네비 클릭은 `hx-target="#main-content"`로 본문만 교체 → 사이드바 DOM은 첫 풀페이지 로드 이후 재렌더 안 됨 → `active_nav`(서버 계산)가 반영 안 됨.

해결(경량 JS, `app.js`): 각 `.sidebar-nav-item`의 `hx-get` 속성을 현재 `location.pathname`과 비교해 `.active` 토글. 별도 경로↔nav 매핑 중복 없음(hx-get이 진실원천).

```js
function syncSidebarActive() {
  const path = location.pathname;
  document.querySelectorAll('.sidebar-nav-item').forEach((a) => {
    a.classList.toggle('active', a.getAttribute('hx-get') === path);
  });
}
// DOMContentLoaded + htmx:afterSwap(본문 스왑 후) + htmx:historyRestore(뒤로가기)에서 호출
```

> 서버 `active_nav` 템플릿 조건(`{{ 'active' if active_nav == ... }}`)은 첫 풀페이지 로드의 정확성을 위해 **유지**. JS는 이후 HTMX 이동을 보정. 두 메커니즘이 같은 결과를 내므로 충돌 없음.

### S2. 사이드바 하단 "EKS 정상 5/5" 박스 제거

`_sidebar.html`의 시스템 상태 박스(현재 `<!-- 시스템 상태 -->` div) **삭제**. 하드코딩 5/5라 정직화 대상이기도 함.

## 테스트

- `dashboard` 라우터: running 실험 있을 때 ctx 키(r_series, latest_iter, llm_cost_total, recent) 채워짐 / 없을 때 empty-state 분기(running_exp None)
- `_recent_activity`: builds+experiments+apps 혼합 정렬·상위 5개 단위테스트
- 부분 렌더 보장(HX-Request 시 풀셸 방지) 어서션 유지
- 기존 테스트(현재 통과 수) 회귀 없음

## 영향 파일

- `app/templates/pages/dashboard.html` (주 수정)
- `app/routers/pages.py` (dashboard 핸들러 + `_recent_activity` 헬퍼)
- `app/db/seed.py` (metrics 보강)
- `app/static/js/app.js` (rIndexChart 데이터 주입 + 사이드바 active 동기화 S1)
- `app/templates/partials/_sidebar.html` (S2: EKS 박스 제거)
- `tests/` (라우터·헬퍼 테스트)

> tds.css 변경 없음(반응형은 Tailwind 유틸 클래스로 처리). 버튼은 disable이 아니라 삭제이므로 disabled 규칙 불요.

## 구현 원칙

- **최소 변경·최소 구현.** 추측성 추상화 금지, 요청된 것만. 기존 패턴(render_page·repository·JS 위임) 따름.
- 추후 리팩토링 쉽게: 작은 헬퍼 분리, 핸들러 얇게, 하드코딩→seed/DB 단일출처.
- 깔끔하게: 주변 코드의 주석 밀도·네이밍·관용구에 맞춤.
