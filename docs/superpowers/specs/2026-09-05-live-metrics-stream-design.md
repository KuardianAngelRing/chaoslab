# 실험 진행 중 실시간 메트릭 스트리밍 — 설계 (2026-09-05)

## 배경·목표

현재 실험 SSE(`GET /experiments/{id}/stream`)는 `Experiment.status`만 2초마다 흘려보내고, 메트릭은 실험 **완료 후** Prometheus 소급 집계(`metrics_collector.py`)로 한 번 저장된다. 그래서 워크플로우 셸 2단계(`partials/_hypothesis_execute.html`)에 실험이 running인 동안 보이는 것은 상태 배지뿐이다.

목표: 실험이 `deploying`/`running`인 동안 **RPS · 오류율 · p95/p99 레이턴시 · Ready 파드 수**를 수 초 간격으로 실행 카드 위 차트에 그려 시연에서 "장애 주입 → 지표 악화 → 회복"이 눈에 보이게 한다. 완료 후에는 차트가 남고(마지막 스냅샷 유지) 기존 서버 렌더 값(R지수 등)이 단일 소스라는 원칙은 그대로.

범위 밖: 개선 루프(Phase 3), 회귀 경로(3·4단계) 차트, 대시보드 페이지 차트 교체.

## 결정 사항

1. **별도 SSE 엔드포인트** `GET /experiments/{id}/metrics/stream` — 기존 status 스트림과 분리(status 스트림은 `app.js`의 `watchExperiments()`·`data-running-exp` 재요청 로직이 의존하므로 건드리지 않는다).
2. **`PrometheusService`에 즉시 조회 메서드 추가** — `interfaces.py`:
   ```python
   def live_snapshot(self, namespace: str, app_name: str) -> dict:
       """최근 1분 rate 기준 즉시값. 키: ts(iso), rps, error_rate_pct, p95_ms, p99_ms, ready_pods.
       조회 실패 시 예외 대신 값 None (스트림은 끊기지 않는다)."""
   ```
   - `real/prometheus.py` `RealPrometheus.live_snapshot`: `phase_summary`와 동일한 `istio_selector`·pod 패턴 쿼리를 `_instant`로 now 시점 조회. 기존 `red_metrics`(네임스페이스 전체)와 구분.
   - `stubs.py` `StubPrometheus.live_snapshot`: 호출 횟수 기반 결정적 시퀀스(처음 몇 틱 정상 → 악화 → 회복)로 Stub에서도 차트가 움직이게. 테스트가 값 형태를 검증할 수 있도록 순수 함수로 분리(`_stub_live_series(tick)`).
   - `tests/test_stubs_contract.py`에 계약 키 검증 추가.
3. **스트림 구현** (`routers/experiments.py`에 라우트 추가, 워처 패턴 그대로):
   - 매 틱 DB에서 `Experiment` 재조회 → `status ∉ {pending, deploying, running}`이면 `completed` 이벤트 후 종료. 상한 ~42분(기존 스트림과 동일 1260틱).
   - 간격 **3초**. `make_prometheus()`로 서비스 획득(라우터 모듈의 기존 import 재사용). 네임스페이스는 `exp.namespace or app.namespace`(k3s 전용 ns 우선).
   - 이벤트: `metric` (data=`live_snapshot` dict + `"status"`), `completed`.
   - 실험이 `pending`(k3s 배포 전)이면 값 None인 틱을 보내되 스트림은 유지.
4. **템플릿** — `partials/_hypothesis_execute.html`의 실행 카드 안, "가설" 블록과 "장애 유형/시작/종료" 그리드 사이에 차트 블록 추가:
   - `<div data-live-metrics="{{ exp.id }}" data-live-metrics-final="{{ 'true' if 종료 상태 }}">` 안에 `<canvas>` 2개(레이턴시 p95/p99 · 오류율+RPS) + Ready 파드 수 텍스트.
   - 종료 상태에서는 저장된 `fault_metrics`/`recovery_metrics` 요약값(있으면)을 카드 하단 작은 표로 서버 렌더 — 없으면 "실측 집계 없음(Stub)".
   - 색은 CSS 변수만(`--primary`, `--danger`, `--warning`, `--muted-foreground`), 다크 전환 시 재렌더는 기존 `initCharts()`가 쓰는 `chartCommon()` 헬퍼 재사용.
5. **app.js** — 함수 **하나만** 추가: `watchLiveMetrics(root)`. `data-live-metrics` 요소를 찾아 EventSource 구독, Chart.js 라인 차트 2개를 rolling window(최근 60틱)로 갱신, `completed`에서 close. 등록은 기존 패턴대로 `htmx:afterSwap` + `DOMContentLoaded` 리스너 1줄씩. 요소별 리스너 부착 금지, 전역 상태는 `let _liveMetricsStream = null` 하나.
   - 다른 함수(`watchExperiments`, `watchHypothesis`, 시나리오 회귀 관련 함수) **수정 금지** — 병행 작업(가설↔회귀 통합)이 같은 파일의 다른 영역을 수정한다.

## 파일 경계 (병행 작업 충돌 방지)

| 수정 | 파일 |
|---|---|
| 추가·수정 | `app/services/interfaces.py`(PrometheusService만) · `app/services/stubs.py`(StubPrometheus만) · `app/services/real/prometheus.py` · `app/routers/experiments.py`(라우트 1개 추가) · `app/templates/partials/_hypothesis_execute.html` · `app/static/js/app.js`(새 함수 1개 + 등록 2줄, 파일 끝부분) · `tests/test_experiments.py`(스트림 테스트) · `tests/test_stubs_contract.py` · `tests/test_real_helpers.py`(쿼리 문자열 헬퍼가 있다면) |
| 금지 | `app/templates/pages/experiment_detail.html` · `app/routers/pages.py` · `app/routers/scenario_runs.py` · `app/services/regression.py` · `app/db/models.py` · `tests/conftest.py` |

## 테스트

- 스트림: Stub으로 실험 생성 후 `/experiments/{id}/metrics/stream` 첫 이벤트가 `metric`이고 키가 계약과 일치, 실험을 completed로 바꾸면 `completed`로 종료(기존 `test_experiments.py`의 SSE 테스트 패턴 따라 `should_exit_event` 리셋은 conftest가 이미 처리).
- Stub 시퀀스 순수 함수 단위 테스트.
- Real 쿼리 문자열은 기존 `test_real_helpers.py` 방식으로 selector 포함 여부만.
- `pytest -q` 전체 통과(기준 200 + 추가분).

## 검증 시나리오 (구현 후 수동)

`uvicorn` 기동 → nginx로 가설 생성 → 후보 선택 → 2단계 카드에서 실험 running 동안 차트가 3초마다 갱신되고, 완료 후 차트가 멈추고 R지수가 서버 렌더로 표시.
