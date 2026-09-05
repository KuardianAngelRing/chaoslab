# 2단계 실시간 차트 채우기 — 설계 (2026-09-06)

## 배경·문제

실행 카드(`partials/_hypothesis_execute.html`)의 실시간 차트(`app.js` `watchLiveMetrics`)는 rps·오류율·p95·p99 4개 시리즈만 그린다. 값은 `LocalPrometheus.live_queries`가 `chaospilot_http_requests_total{status}`·`chaospilot_http_request_duration_seconds_bucket`을 조회해 만드는데, 09/06 라이브(HYP-15·16 녹화)에서 두 샘플 모두 차트가 비어 있었다. 원인 세 가지:

1. **Ready 파드 수는 실측되는데 헤더 텍스트로만 표시** — 녹화 중 9→4→9로 움직였지만 차트가 아님.
2. **order-resilience-lab `/metrics`가 계약과 안 맞음** — 이름 `chaoslab_http_requests_total`(접두어 다름) · `status` 라벨 없음 · duration 히스토그램 없음. 게다가 YAML 블록 스칼라 안의 `"\\n"`이 Python 문자열에서 백슬래시+n 두 글자가 되어 **본문이 한 줄로 붙는다**(Prometheus 텍스트 파서 실패 → 시리즈 자체가 없음). nginx는 메트릭이 없다.
3. **단독 실험(2단계) 동안 아무도 요청을 보내지 않는다** — 회귀(3단계)만 `take_sample`이 샘플당 3회 요청한다. 트래픽이 0이면 rps·오류율 시리즈는 빈 벡터(None).

목표: k3s 단독 실험에서 "장애 주입 → 지표 악화 → 회복"이 세 차트(Ready 파드 · 트래픽 · 레이턴시)에 보이게 한다. 범위 밖: EKS(Istio 메트릭 + 실트래픽 전제), nginx 메트릭 익스포터, 회귀 경로 차트.

## 결정 사항

### 1. Ready 파드 차트 시리즈
- 실행 카드 그리드를 `grid-cols-3`으로 바꾸고 **Ready 파드 차트를 맨 앞**에 둔다(모든 앱에서 항상 값이 있는 유일한 시리즈). 계단형(`stepped: true`) 라인, y축 정수 눈금(`precision: 0`), 색 `--success`.
- 헤더의 `data-live-metrics-pods` 텍스트·HTTP 미노출 안내 문구는 유지. 스트림 계약(`_LIVE_KEYS`·`live_snapshot`)은 이미 `ready_pods`를 포함하므로 **백엔드 변경 없음**.
- `app.js` 수정 → `base.html` `?v=` 갱신.

### 2. 샘플 `/metrics`를 `chaospilot_http_*` 계약으로 교체
- `app/samples/k3s/order-resilience-lab.yaml` ConfigMap `app.py`:
  - `chaospilot_http_requests_total{service,status}` 카운터 — 비즈니스 경로(`/orders`·`/work`)만 계수(기존 `requests_total` 자리). probe(`/live`·`/ready`)·`/metrics`·404는 세지 않는다 — 프로브 트래픽이 rps를 지배하고 `/ready` 503이 오류율에 섞이는 것을 막는다.
  - `chaospilot_http_request_duration_seconds` 히스토그램(`_bucket{le}`·`_sum`·`_count`, Prometheus 기본 버킷 0.005~10s) — 같은 경로의 응답 시간.
  - `ThreadingHTTPServer`라 카운터는 `threading.Lock`으로 보호. 본문은 `"\n".join(lines)`로 조립(블록 스칼라 이스케이프 문제 제거).
  - 리슨 포트 `PORT` env(기본 8080) — 테스트가 서브프로세스로 띄워 계약을 검증하기 위함. manifest는 그대로 8080.
- 검증: `tests/test_sample_app_metrics.py` — manifest에서 `app.py`를 꺼내 서브프로세스로 기동, `/orders` 호출 후 `/metrics`가 `local_live_queries`가 기대하는 이름·라벨(`status`, `le`)·줄바꿈을 갖는지 확인.
- 샘플 YAML을 바꾸면 **샘플 재등록**(동명 앱 갱신)이 필요하다(09/06 항목과 동일 주의).

### 3. 단독 실험 중 관측 트래픽 (k3s)
- 새 모듈 `app/services/live_traffic.py` `TrafficGenerator` — 데몬 스레드 1개가 `workload.probe_http(namespace, service, path)`를 `interval_s`(기본 0.5s ≈ 2 rps) 간격으로 반복. `start()`/`stop(timeout)`, 예외는 삼키고 카운트(`requests`·`failures`)만 남긴다. 결과는 어디에도 저장하지 않는다 — 목적은 Prometheus에 잡힐 부하뿐이며, 관측·판정은 기존대로 소급 집계(`metrics_collector`)가 담당.
- 관측 대상 해석을 **한 곳**으로: `regression.observation_for_app(app) -> dict | None`(service=`app.observe_service or entry_service(...)`, path=`app.health_path or "/"`, expected_status 200). `scenario_snapshot_from_hypothesis`도 이 헬퍼를 쓴다(미해결 시 기존 ValueError 유지).
- 워처(`routers/experiments._watch_experiment`) k3s 분기: `wait_ready` 직후 `TrafficGenerator.start()` → `finally`에서 `stop()` 후 ns teardown. 관측 Service를 알 수 없으면 경고 로그만 남기고 트래픽 없이 진행(실험은 막지 않는다). 스레드 실행 중 실패는 워처 상태에 영향 없음.
- 부하 규모: API 서버 서비스 프록시 경유 2 rps — SSH 터널·apiserver에 무시할 수준. Stub 경로(테스트)는 `StubK3sWorkload.probe_http`를 호출할 뿐이며 워처 종료 시 함께 멈춘다.

## 파일 경계

| 수정 | 파일 |
|---|---|
| 추가 | `app/services/live_traffic.py` · `tests/test_live_traffic.py` · `tests/test_sample_app_metrics.py` |
| 수정 | `app/templates/partials/_hypothesis_execute.html` · `app/static/js/app.js`(`watchLiveMetrics`만) · `app/templates/base.html`(`?v=`) · `app/samples/k3s/order-resilience-lab.yaml`(ConfigMap `app.py`만) · `app/services/regression.py`(`observation_for_app` 추가 + snapshot이 사용) · `app/routers/experiments.py`(k3s 워처 start/stop) · `tests/test_experiments.py` · `tests/test_regression*.py` |
| 불변 | `interfaces.py` · `local_prometheus.py` · `stubs.py` · 스트림 라우트 · `metrics_collector.py` |

## 검증 계획
- `pytest -q` 전체 통과.
- k3s 라이브: order-resilience-lab 샘플 재등록 → 가설 → payment-api pod-failure 실험 → 2단계 카드에서 Ready 파드 계단·rps ≈ 2·오류율 상승/복귀·p95 곡선 확인. nginx는 Ready 파드 차트만 움직이고 안내 문구가 뜨는지 확인.
