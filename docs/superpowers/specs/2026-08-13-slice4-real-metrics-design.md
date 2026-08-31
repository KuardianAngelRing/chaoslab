# Slice 4 — 실측 데이터 연동 + R지수 설계 (2026-08-13)

## 목표

실험이 끝나면 Prometheus/Loki/K8s에서 **진짜 지표를 소급 집계**해 계약(PhaseSummary)
형태로 저장하고, R지수를 실계산한다. 08/11 회의 태윤 담당분 — UI 배선은 팀원 영역이라
제외(백엔드가 채운 값을 화면이 읽기만 하면 되는 상태로 만든다).

## 확정 결정

| 결정 | 내용 |
|---|---|
| 기준선 측정 | **과거 데이터 소급** — 주입 전 5분을 Prometheus range 쿼리로 집계. 워처 생명주기 변경 없음 |
| 구간 경계 | 기준선 `[started_at−5m, started_at]` · 장애 `[started_at, started_at+duration]` · 회복 `[장애 종료, finished_at]`. 회복 소요 = finished_at − 장애 종료. **스키마 변경 없음**(기존 컬럼으로 계산 가능) |
| 저장 형태 | 3구간 집계를 **PhaseSummary 계약 형태 그대로** `Experiment.*_metrics`에 저장 → 핸드오프 조립기의 "저장값 우선" 규칙이 자동으로 실데이터를 사용 |
| R지수 | R = 0.4·가용성 + 0.3·레이턴시 + 0.3·복구속도. 가용성=1−장애 에러율 · 레이턴시=min(1, 기준p99÷장애p99) · 복구속도=max(0, 1−회복초÷300). 각 0~1 클램프. 순수 함수 `services/r_index.py`, 완료 시 `exp.r_index` 저장. 핸드오프 항목별 내역도 같은 함수로 재계산(자리값 제거). `baseline_r`은 Phase 3 영역 — 미변경 |
| 실패 격리 | 지표 수집·R계산 실패는 실험을 failed로 만들지 않음 — 경고 로그 + metrics 비움(핸드오프는 Stub 폴백) |
| 라이브 접근 | 맥에서 실행: kubeconfig는 up.sh가 로컬 구성, Prometheus/Loki는 EC2 SSH 터널(`-L 9090 -L 3100`) |

## 1. Protocol 확장 (`services/interfaces.py`)

`PrometheusService`에 추가:
```python
def phase_summary(self, namespace: str, app_name: str, phase: str,
                  start: datetime, end: datetime) -> dict:
    """구간 소급 집계 — PhaseSummary 계약과 동일 키. recovery_seconds는 호출자가 채움."""
```
- Stub: `phase`로 기존 `_PHASE_SUMMARY_SAMPLES` 반환(시각 무시) → 워처가 stub 모드에서도 동작.
- 기존 `red_metrics` 계약 유지(대시보드 카드용).

## 2. RealPrometheus (`services/real/prometheus.py`)

- 순수 함수(테스트 대상): PromQL 빌더 + `/api/v1/query`·`query_range` 응답 파서
  (`summarize_series(values) -> avg/min/max/peak`, NaN·빈 결과 → 0).
- 쿼리 (Istio 표준 메트릭, `reporter="destination"`, `destination_workload=<app>`,
  `destination_workload_namespace=<ns>`, step 15s):
  - RPS: `sum(rate(istio_requests_total{...}[1m]))` range → avg/min/max
  - 에러율: `100 * 5xx rate ÷ 전체 rate` range → avg/peak
  - 5xx 건수·상태코드 분포: `sum [by (response_code)] (increase(istio_requests_total{...}[<W>s]))` instant
  - p50/95/99: `histogram_quantile(q, sum by (le) (rate(istio_request_duration_milliseconds_bucket{...}[1m])))` range → avg/peak
  - Ready 파드 최소: `sum(kube_pod_status_ready{condition="true", namespace, pod=~"<app>-.*"})` range → code에서 min
  - 재시작: `sum(increase(kube_pod_container_status_restarts_total{...}[<W>s]))` instant
- HTTP는 httpx 동기 클라이언트, `settings.prometheus_url`, 타임아웃 10s.
- `red_metrics`도 실구현(rate/5xx%/p99 instant 3종).

## 3. RealLoki (`services/real/loki.py`)

- `tail(namespace, limit)`: `/loki/api/v1/query_range`, `{namespace="<ns>"}`, 최근 5분.
- `error_logs(namespace, app, limit=20)`: `{namespace, app="<app>"} |~ "(?i)(error|exception|fail)"`,
  메시지 문자열 기준 중복 제거 후 limit.

## 4. RealHandoffSource (`services/real/handoff_source.py`)

| 메서드 | 소스 |
|---|---|
| `phase_summary` | RealPrometheus 위임(최근 5분 창) — 저장값 우선 규칙 때문에 폴백 전용 |
| `istio_config` | CustomObjectsApi `networking.istio.io/v1beta1` VirtualService·DestinationRule get → yaml 문자열. 없으면 빈 문자열(스키마 허용) |
| `deployment_info` | AppsV1Api read: replicas·probe·resources |
| `events` | CoreV1 `list_namespaced_event`, involvedObject 이름이 `<app>` 접두인 것, K8sEvent 키로 매핑 |
| `error_logs` | RealLoki 위임 |

## 5. RealK8s 확장 + kubeconfig 공용화

- `services/real/kube.py` 신설: `load_kube()` — incluster→kubeconfig 폴백 +
  `settings.k8s_context` 지원(현재 미사용 설정 활성화). 기존 4곳 중복 제거(builder·chaos·k8s×2).
- `RealK8s.nodes()/pods()/components()` 구현 — Stub과 동일 dict 키(계약 테스트로 고정).
  components는 monitoring/chaos-mesh/argocd/argo 네임스페이스 Deployment ready 여부.

## 6. 워처 확장 (`routers/experiments.py`)

`_watch_experiment`의 종료 직전(완료 확정 시점)에:
```
collect_experiment_metrics(session, exp) →
  prometheus.phase_summary ×3 (구간 경계는 위 표)
  recovery dict에 recovery_seconds 주입
  exp.baseline/fault/recovery_metrics 저장 (계약 형태)
  r = r_index.compute(baseline, fault, recovery) → exp.r_index 저장
```
- `stopped`/`failed` 실험은 수집 안 함(구간이 불완전). pod-kill은 duration=30s 유예 그대로.
- 수집 로직은 `services/metrics_collector.py`로 분리(워처는 호출 1줄) — deps `make_prometheus()` 재사용.

## 7. R지수 (`services/r_index.py`, 순수 함수)

```python
def compute(baseline: dict, fault: dict, recovery: dict) -> dict:
    """{availability, latency_score, recovery_score, r} — 각 0~1, r은 가중합."""
```
- 장애 p99가 0(트래픽 없음)이면 latency_score=1. recovery_seconds 없으면 recovery_score=0.
- 조립기(`assembler.py`): 저장 metrics가 계약 형태면 `compute()`로 항목별 점수 채움,
  아니면 기존 자리값 유지. `exp.r_index`는 저장값 그대로.

## 8. deps 배선 (`deps.py`)

`make_prometheus`/`make_loki` 신설 + `make_handoff_source`에 `use_real_services` 분기
(Real은 lazy import). `get_prometheus`/`get_loki`가 팩토리 경유하도록 변경.

## 9. Iac-aws 변경 (별도 레포 커밋)

- `terraform/2-platform/monitoring.tf`: additionalScrapeConfigs를 Istio 표준 방식으로 교체 —
  `role: pod` + `prometheus.io/*` 어노테이션 기반 relabel(사이드카 merged stats 15020),
  대상 네임스페이스에 **`sut`** 추가 (istio-system·online-boutique 유지)
- `helm/generic-app`: `destinationrule.yaml` 템플릿 신설 — `istio.circuitBreaker` values
  (기본 consecutive5xxErrors 5 · interval 10s · baseEjectionTime 30s), VS와 같은 토글.
  → AI 개선 대상 3종(timeout/retry/CB)이 전부 클러스터에 실존하게 됨
- 적용: monitoring은 `terraform apply`(up.sh가 수행), DR은 커밋·푸시(ArgoCD가 pull)

## 10. 테스트 (hermetic — 실클러스터 불요)

- PromQL 빌더·응답 파서·`summarize_series` 단위 (canned JSON).
- `r_index.compute` 경계값(에러율 100%·p99 0·회복 초과·정상 케이스).
- `metrics_collector`: StubPrometheus로 3구간 저장 + r_index 기록 검증.
- 워처 통합: stub 완주 시 metrics·r_index가 채워지는지 (기존 워처 테스트 스타일).
- 계약 테스트(`test_stubs_contract.py`) 확장: Stub `phase_summary` 반환이 PhaseSummary로 검증.
- Real 클래스의 네트워크 경로는 라이브 검증으로 갈음(기존 컨벤션).

## 11. 라이브 검증 절차 (up.sh 후)

1. `argo/apply.sh` · SSH 터널 `-L 9090 -L 3100` · `.env` USE_REAL_SERVICES=true
2. 앱 등록·배포(sut) → 트래픽 필요: `kubectl run loadgen -n sut --image=busybox -- /bin/sh -c "while true; do wget -q -O- http://<app>:<port>/; sleep 0.2; done"`
3. `curl 'localhost:9090/api/v1/query?query=istio_requests_total'`로 sut 메트릭 실존 확인 (스크레이프 수정 검증)
4. NetworkChaos delay 실험 → 완료 후 `Experiment.*_metrics`·`r_index` 실측 확인
5. `POST /experiments/{id}/handoffs` → payload가 실데이터인지 확인
6. down.sh는 사용자 결정

## 범위 제외 (YAGNI)

- UI 배선(pages.py 하드코딩 해소 포함 — 팀원 영역), 자동 부하 생성 기능화,
  자동 중단 안전장치, 실험 순차 큐, Supabase 전환, `red_metrics` 이상의 대시보드 실측.
