# k3s Prometheus 실측 연결 — 실시간 차트·소급 집계 실데이터 (2026-09-05)

## 배경·목표

09/05 실시간 메트릭 스트림(`GET /experiments/{id}/metrics/stream`)은 `deps.make_prometheus`가 `USE_REAL_SERVICES`(EKS 게이트)만 보므로 k3s 실험에서도 차트가 Stub 시퀀스를 그렸다. 실험 완료 시 소급 집계(`metrics_collector`)와 R지수도 같은 이유로 Stub 값이었다.

라즈베리파이 k3s 조사 결과(09/05):

| 항목 | 상태 |
|---|---|
| Prometheus | `chaospilot-observability/prometheus:9090` (scrape 15s) |
| 스크레이프 잡 | `kube-state-metrics` · `annotated-pods`(`prometheus.io/scrape=true` 파드, 전 네임스페이스) |
| Istio | 없음 → `istio_requests_total` 계열 쿼리 전부 빈 벡터 |
| 앱 HTTP 메트릭 | ChaosPilot 워크로드가 직접 노출: `chaospilot_http_requests_total{service,status,path}` · `chaospilot_http_request_duration_seconds_{count,sum}` (**버킷 없음** → 백분위 불가) |
| nginx 샘플 | `/metrics` 없음 → kube-state-metrics(Ready 파드·재시작)만 관측 가능 |
| `app/samples/k3s/order-resilience-lab.yaml` | 스크레이프 어노테이션 없음 → 세션 ns 파드는 수집 대상 아님 |

목표: k3s 실험에서 관측 가능한 만큼은 실측으로 — Ready 파드 수는 항상, HTTP 지표는 앱이 노출할 때. 노출하지 않는 값은 **None으로 정직하게**(0이나 Stub 값으로 위장하지 않음).

## 결정 사항

1. **`make_prometheus(env="eks")`** — `make_chaos`와 동일 규칙. `k3s` + `LOCAL_KUBECONFIG` → `LocalPrometheus`, `k3s` + 미설정 → Stub, `eks`는 기존 `USE_REAL_SERVICES` 게이트. 호출자 2곳(메트릭 스트림·완료 시 수집기)이 `exp.app.env`를 넘긴다.
2. **`services/real/local_prometheus.py` `LocalPrometheus`** (PrometheusService 구현):
   - 전송: **k8s API 서비스 프록시**(`/api/v1/namespaces/{LOCAL_OBS_NAMESPACE}/services/http:prometheus:9090/proxy/api/v1/…`) — `RealLocalK8s._node_temps`와 동일. SSH 터널 6443 하나로 해결, 별도 `port-forward`·`LOCAL_PROMETHEUS_URL` 없음.
   - 쿼리 범위: **실험 전용 namespace 전체**(ADR-0009 — ns = 앱, Chaos selector와 동일 의미). `local_live_queries(namespace)` 순수 함수.
   - `live_snapshot`: 시리즈 없음·NaN·조회 실패 모두 해당 키만 None(`instant_or_none`). 오류율 쿼리는 5xx 시리즈가 없을 때 0%가 빈 벡터로 사라지지 않도록 `(sum(rate(5xx)) or vector(0)) / sum(rate(total))`.
   - `phase_summary`: PhaseSummary 계약(float 필수)이라 미노출 지표는 0. 상태코드 분포는 `status` 라벨.
3. **수집기 네임스페이스 교정** — `collect_experiment_metrics`가 `exp.namespace or app.namespace`로 조회(k3s 전용 ns). 기존엔 항상 `app.namespace`라 k3s에선 빈 ns를 보고 있었다(Stub이라 드러나지 않음).
4. **샘플 매니페스트** `order-resilience-lab.yaml` Deployment 5개 파드 템플릿에 `prometheus.io/scrape|port|path` 어노테이션 — 재등록 시 세션 ns 파드가 수집된다(멀티 문서 YAML이라 앵커 공유 불가, 5회 원문).
5. **UI 안내** — 실행 카드에서 Ready 파드는 오는데 HTTP 지표가 전부 null이면 "HTTP 메트릭 미노출 앱 — Ready 파드만 실측" 문구(`data-live-metrics-note`, app.js 토글).

## 알려진 한계 (백로그)

- **백분위 없음**: ChaosPilot 앱 메트릭이 히스토그램 버킷을 노출하지 않아 p95/p99는 k3s에서 항상 None/0. `_sum/_count`로 평균 레이턴시는 가능하나 계약 키(p95/p99)에 평균을 넣는 건 왜곡이라 하지 않음 → 앱 측 버킷 노출 또는 계약에 `latency_avg_ms` 추가가 필요.
- **R지수 의미**: HTTP 미노출 앱(nginx)은 `r_index.compute`에서 오류율 0 → 가용성 1.0, p99 0 → 레이턴시 1.0이 되어 회복시간만 반영된다(≈0.99). Stub의 0.72보다 "좋아 보이지만" 근거 없는 값이므로, 무트래픽 실험의 R지수 미산정(또는 '판정 불가') 처리는 회귀 판정 기준 튜닝(팀 결정)과 함께 다룬다.
- 대시보드 RED 카드(`red_metrics`)는 라우터가 아직 팩토리를 env 없이 호출 — k3s 카드 연결은 범위 밖.

## 파일 경계

| 수정 | 파일 |
|---|---|
| 추가 | `app/services/real/local_prometheus.py` · `tests/test_local_prometheus.py` |
| 수정 | `app/deps.py`(make_prometheus) · `app/routers/experiments.py`(스트림·수집 호출 env, 중지 `next`) · `app/services/metrics_collector.py`(namespace) · `app/samples/k3s/order-resilience-lab.yaml`(어노테이션) · `app/templates/partials/_hypothesis_execute.html` · `app/static/js/app.js` · `app/templates/base.html`(`?v=`) · `tests/test_deps_factories.py` · `tests/test_metrics_collector.py` · `tests/test_experiments.py` |
| 불변 | `services/real/prometheus.py`(Istio 쿼리) · `interfaces.py` · `stubs.py` · `regression.py` · `resilience.py` |

## 검증

- 단위: 쿼리 빌더 키=계약 · ns selector · `vector(0)` 폴백 · None/0 구분 · 프록시 경로 · 팩토리 라우팅 · 수집기 ns · 스트림이 앱 env로 팩토리 호출.
- 라이브(09/05, 터널 경유 `LocalPrometheus` 직접 호출): `chaoslab-session-nginx-5` → ready_pods 2·HTTP None / `chaospilot-workload-93cf27bd` → rps 7.13·오류율 0.0·ready 10·상태코드 분포 `{200: 2156, 503: 0}` / 없는 ns → 전부 None.
