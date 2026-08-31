# Slice 4 — 실측 데이터 연동 + R지수 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 실험 완료 시 Prometheus 소급 집계로 계약 형태 metrics 3벌 + R지수를 저장하고, Real 서비스 4종(Prometheus/Loki/K8s/HandoffSource)을 배선한다.

**Architecture:** 워처 종료 훅 → `metrics_collector`(구간 경계 계산) → `PrometheusService.phase_summary`(Protocol 확장, Stub=샘플/Real=range 쿼리) → `Experiment.*_metrics` 저장 → `r_index.compute`(순수 함수). 핸드오프 조립기는 저장값 우선 규칙으로 자동 연결.

**Tech Stack:** httpx 0.28(동기) · kubernetes SDK(lazy import) · PyYAML(k8s SDK 동반) · pytest hermetic

## Global Constraints

- 스펙: `docs/superpowers/specs/2026-08-13-slice4-real-metrics-design.md`
- 스키마 변경 금지 — 구간 경계는 `started_at`/`params.duration_s`/`finished_at`으로 계산
- 지표 수집·R계산 실패는 실험을 failed로 만들지 않음 (경고 로그 + 격리)
- Real 구현은 lazy import(테스트는 SDK 불필요), 네트워크 경로는 라이브 검증으로 갈음
- UI(템플릿·app.js·pages.py) 변경 금지 — 팀원 영역
- 브랜치 `feat/slice4-real-metrics`(생성됨) · 커밋 ✨/✅/📝 파일단위 원자적 · `pytest -q` 118+ 유지

---

### Task 1: R지수 순수 함수

**Files:**
- Create: `app/services/r_index.py`
- Test: `tests/test_r_index.py`

**Interfaces:**
- Produces: `compute(baseline: dict, fault: dict, recovery: dict) -> dict` — 키 `availability/latency_score/recovery_score/r`(각 0~1, r=0.4a+0.3l+0.3r 반올림 4자리), `RECOVERY_CAP_S = 300.0`. dict 키는 PhaseSummary 계약 키를 읽음(`error_rate_avg`, `latency_p99_avg_ms`, `recovery_seconds`).

- [ ] **Step 1: Write the failing test**

`tests/test_r_index.py`:

```python
"""R = 0.4·가용성 + 0.3·레이턴시 + 0.3·복구속도 — 경계값 검증."""
from app.services.r_index import compute


def test_normal_case():
    out = compute(
        baseline={"latency_p99_avg_ms": 200.0},
        fault={"error_rate_avg": 10.0, "latency_p99_avg_ms": 400.0},
        recovery={"recovery_seconds": 60.0},
    )
    assert out["availability"] == 0.9          # 1 - 10%
    assert out["latency_score"] == 0.5         # 200/400
    assert out["recovery_score"] == 0.8        # 1 - 60/300
    assert out["r"] == round(0.4 * 0.9 + 0.3 * 0.5 + 0.3 * 0.8, 4)


def test_boundaries():
    # 에러율 100% → 가용성 0, 장애 p99=0(트래픽 없음) → 레이턴시 1, 회복 시간 없음 → 복구 0
    out = compute(
        baseline={"latency_p99_avg_ms": 0.0},
        fault={"error_rate_avg": 100.0, "latency_p99_avg_ms": 0.0},
        recovery={},
    )
    assert out["availability"] == 0.0
    assert out["latency_score"] == 1.0
    assert out["recovery_score"] == 0.0

    # 회복이 상한(300s) 초과 → 0으로 클램프, 기준 p99가 장애보다 커도 1로 클램프
    out2 = compute(
        baseline={"latency_p99_avg_ms": 500.0},
        fault={"error_rate_avg": 0.0, "latency_p99_avg_ms": 100.0},
        recovery={"recovery_seconds": 900.0},
    )
    assert out2["latency_score"] == 1.0
    assert out2["recovery_score"] == 0.0
    assert out2["availability"] == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_r_index.py -v`
Expected: FAIL — `ModuleNotFoundError: app.services.r_index`

- [ ] **Step 3: Implement**

`app/services/r_index.py`:

```python
"""R지수 계산 — 순수 함수 (IO 없음). R = 0.4·가용성 + 0.3·레이턴시점수 + 0.3·복구속도.

입력 dict 키는 PhaseSummary 계약(handoff_schema.py)과 동일:
error_rate_avg(%), latency_p99_avg_ms, recovery_seconds.
"""
WEIGHTS = {"availability": 0.4, "latency": 0.3, "recovery": 0.3}
RECOVERY_CAP_S = 300.0  # 5분 내 회복 기준 — 즉시 회복=1, 상한 초과=0


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def compute(baseline: dict, fault: dict, recovery: dict) -> dict:
    availability = _clamp01(1.0 - float(fault.get("error_rate_avg") or 0.0) / 100.0)

    fault_p99 = float(fault.get("latency_p99_avg_ms") or 0.0)
    base_p99 = float(baseline.get("latency_p99_avg_ms") or 0.0)
    latency_score = 1.0 if fault_p99 <= 0 else _clamp01(base_p99 / fault_p99)

    rec_s = recovery.get("recovery_seconds")
    recovery_score = 0.0 if rec_s is None else _clamp01(1.0 - float(rec_s) / RECOVERY_CAP_S)

    r = (WEIGHTS["availability"] * availability
         + WEIGHTS["latency"] * latency_score
         + WEIGHTS["recovery"] * recovery_score)
    return {
        "availability": round(availability, 4),
        "latency_score": round(latency_score, 4),
        "recovery_score": round(recovery_score, 4),
        "r": round(r, 4),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_r_index.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/r_index.py tests/test_r_index.py
git commit -m "✨ R지수 계산 순수 함수 (0.4·가용성 + 0.3·레이턴시 + 0.3·복구속도)"
```

---

### Task 2: PrometheusService.phase_summary Protocol 확장 + Stub

**Files:**
- Modify: `app/services/interfaces.py` (`PrometheusService`에 메서드 추가 + datetime import)
- Modify: `app/services/stubs.py` (`StubPrometheus`에 메서드 추가)
- Modify: `tests/test_stubs_contract.py` (계약 테스트 확장)

**Interfaces:**
- Produces: `PrometheusService.phase_summary(namespace: str, app_name: str, phase: str, start: datetime, end: datetime) -> dict` — PhaseSummary 계약 키, `recovery_seconds`는 항상 None(호출자가 채움). Stub은 `phase`로 `_PHASE_SUMMARY_SAMPLES` 반환(시각 무시). Task 3(Real)·4(collector)가 사용.

- [ ] **Step 1: Write the failing test**

`tests/test_stubs_contract.py`에 추가:

```python
def test_stub_prometheus_phase_summary_matches_contract():
    from datetime import datetime, timezone

    from app.services.agent.handoff_schema import PhaseSummary

    p = stubs.StubPrometheus()
    t = datetime(2026, 8, 13, tzinfo=timezone.utc)
    for phase in ("baseline", "fault", "recovery"):
        s = PhaseSummary(**p.phase_summary("sut", "demo", phase, t, t))
        if phase == "recovery":
            assert s.recovery_seconds is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_stubs_contract.py -v`
Expected: FAIL — `AttributeError: 'StubPrometheus' object has no attribute 'phase_summary'`

- [ ] **Step 3: Implement**

`app/services/interfaces.py` — 파일 상단 import에 `from datetime import datetime` 추가,
`PrometheusService`(65행 부근)에 메서드 추가:

```python
class PrometheusService(Protocol):
    def red_metrics(self, namespace: str) -> dict:
        """rate/error/duration(p99) — 대시보드 카드용."""

    def phase_summary(self, namespace: str, app_name: str, phase: str,
                      start: datetime, end: datetime) -> dict:
        """[start, end] 구간 소급 집계 — PhaseSummary 계약과 동일 키.

        recovery_seconds는 항상 None으로 반환(구간 경계를 아는 호출자가 채움).
        """
```

`app/services/stubs.py` — `StubPrometheus`에 추가 (모듈 하단 `_PHASE_SUMMARY_SAMPLES` 재사용,
호출 시점 해석이라 클래스가 위에 있어도 동작):

```python
class StubPrometheus:
    def red_metrics(self, namespace: str) -> dict:
        return {"rate": 42.0, "error": 1.8, "duration": 380.0}

    def phase_summary(self, namespace: str, app_name: str, phase: str,
                      start, end) -> dict:
        return dict(_PHASE_SUMMARY_SAMPLES[phase])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_stubs_contract.py -v && pytest -q`
Expected: 확장 테스트 PASS + 전체 통과

- [ ] **Step 5: Commit**

```bash
git add app/services/interfaces.py app/services/stubs.py tests/test_stubs_contract.py
git commit -m "✨ PrometheusService.phase_summary 계약 + Stub 샘플 구현"
```

---

### Task 3: RealPrometheus (쿼리 빌더·파서 순수 함수 + HTTP)

**Files:**
- Create: `app/services/real/prometheus.py`
- Test: `tests/test_prometheus_parsers.py`

**Interfaces:**
- Consumes: Task 2의 Protocol 시그니처, `settings.prometheus_url`
- Produces: 순수 함수 `istio_selector(namespace, app_name) -> str`, `range_values(resp: dict) -> list[float]`, `instant_value(resp: dict) -> float`, `instant_by_label(resp: dict, label: str) -> dict[str, float]`, `summarize(values: list[float]) -> dict`(avg/min/max/peak, 빈 리스트→전부 0.0) · 클래스 `RealPrometheus(settings)`(red_metrics + phase_summary)

- [ ] **Step 1: Write the failing test**

`tests/test_prometheus_parsers.py`:

```python
"""Prometheus HTTP 응답 파서·요약 순수 함수 — canned JSON, 네트워크 없음."""
import math

from app.services.real.prometheus import (
    instant_by_label, instant_value, istio_selector, range_values, summarize,
)


def _range_resp(values):
    return {"data": {"result": [{"values": [[0, str(v)] for v in values]}]}}


def test_range_values_filters_nan_and_empty():
    assert range_values(_range_resp([1.0, 2.5])) == [1.0, 2.5]
    assert range_values({"data": {"result": []}}) == []
    assert range_values(_range_resp([1.0, math.nan])) == [1.0]


def test_summarize():
    s = summarize([1.0, 3.0, 2.0])
    assert s == {"avg": 2.0, "min": 1.0, "max": 3.0, "peak": 3.0}
    assert summarize([]) == {"avg": 0.0, "min": 0.0, "max": 0.0, "peak": 0.0}


def test_instant_helpers():
    resp = {"data": {"result": [
        {"metric": {"response_code": "200"}, "value": [0, "120"]},
        {"metric": {"response_code": "503"}, "value": [0, "7.4"]},
    ]}}
    assert instant_by_label(resp, "response_code") == {"200": 120.0, "503": 7.0}
    assert instant_value({"data": {"result": [{"value": [0, "3.5"]}]}}) == 3.5
    assert instant_value({"data": {"result": []}}) == 0.0


def test_istio_selector():
    sel = istio_selector("sut", "demo")
    assert 'destination_workload="demo"' in sel
    assert 'destination_workload_namespace="sut"' in sel
    assert 'reporter="destination"' in sel
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_prometheus_parsers.py -v`
Expected: FAIL — 모듈 없음

- [ ] **Step 3: Implement**

`app/services/real/prometheus.py`:

```python
"""Prometheus 실조회 — Istio 표준 메트릭 + kube-state-metrics.

쿼리 빌더·응답 파서는 순수 함수(hermetic 테스트), HTTP는 RealPrometheus만.
"""
import math

import httpx

_TIMEOUT_S = 10.0
_STEP_S = 15  # Prometheus scrapeInterval과 동일


def istio_selector(namespace: str, app_name: str) -> str:
    return (f'destination_workload="{app_name}",'
            f'destination_workload_namespace="{namespace}",reporter="destination"')


def range_values(resp: dict) -> list[float]:
    """query_range 첫 시리즈 → float 리스트 (NaN 제외). 시리즈 없으면 []."""
    result = resp.get("data", {}).get("result", [])
    if not result:
        return []
    out = []
    for _ts, v in result[0].get("values", []):
        f = float(v)
        if not math.isnan(f):
            out.append(f)
    return out


def instant_value(resp: dict) -> float:
    result = resp.get("data", {}).get("result", [])
    if not result:
        return 0.0
    f = float(result[0]["value"][1])
    return 0.0 if math.isnan(f) else f


def instant_by_label(resp: dict, label: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for series in resp.get("data", {}).get("result", []):
        key = series.get("metric", {}).get(label, "")
        f = float(series["value"][1])
        if key and not math.isnan(f):
            out[key] = float(int(f))  # increase()는 소수 보정치 — 건수로 절사
    return out


def summarize(values: list[float]) -> dict:
    if not values:
        return {"avg": 0.0, "min": 0.0, "max": 0.0, "peak": 0.0}
    return {
        "avg": round(sum(values) / len(values), 2),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "peak": round(max(values), 2),
    }


class RealPrometheus:
    def __init__(self, settings):
        self.s = settings

    def _get(self, path: str, params: dict) -> dict:
        r = httpx.get(f"{self.s.prometheus_url}{path}", params=params, timeout=_TIMEOUT_S)
        r.raise_for_status()
        return r.json()

    def _range(self, query: str, start, end) -> list[float]:
        return range_values(self._get("/api/v1/query_range", {
            "query": query, "start": start.timestamp(), "end": end.timestamp(),
            "step": _STEP_S,
        }))

    def _instant(self, query: str, at) -> dict:
        return self._get("/api/v1/query", {"query": query, "time": at.timestamp()})

    def red_metrics(self, namespace: str) -> dict:
        """네임스페이스 전체 RED 3종 (대시보드 카드) — 최근 1분 rate."""
        ns = f'destination_workload_namespace="{namespace}",reporter="destination"'
        rate_q = f'sum(rate(istio_requests_total{{{ns}}}[1m]))'
        err_q = (f'100 * sum(rate(istio_requests_total{{{ns},response_code=~"5.."}}[1m]))'
                 f' / sum(rate(istio_requests_total{{{ns}}}[1m]))')
        p99_q = (f'histogram_quantile(0.99, sum by (le) '
                 f'(rate(istio_request_duration_milliseconds_bucket{{{ns}}}[1m])))')
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        return {
            "rate": round(instant_value(self._instant(rate_q, now)), 2),
            "error": round(instant_value(self._instant(err_q, now)), 2),
            "duration": round(instant_value(self._instant(p99_q, now)), 2),
        }

    def phase_summary(self, namespace: str, app_name: str, phase: str,
                      start, end) -> dict:
        sel = istio_selector(namespace, app_name)
        window_s = max(int((end - start).total_seconds()), 60)

        rps = summarize(self._range(f'sum(rate(istio_requests_total{{{sel}}}[1m]))',
                                    start, end))
        err = summarize(self._range(
            f'100 * sum(rate(istio_requests_total{{{sel},response_code=~"5.."}}[1m]))'
            f' / sum(rate(istio_requests_total{{{sel}}}[1m]))', start, end))

        def pct(q: float) -> dict:
            return summarize(self._range(
                f'histogram_quantile({q}, sum by (le) '
                f'(rate(istio_request_duration_milliseconds_bucket{{{sel}}}[1m])))',
                start, end))

        p50, p95, p99 = pct(0.5), pct(0.95), pct(0.99)

        dist = instant_by_label(self._instant(
            f'sum by (response_code) (increase(istio_requests_total{{{sel}}}[{window_s}s]))',
            end), "response_code")
        five_xx = int(sum(v for code, v in dist.items() if code.startswith("5")))

        pod_sel = f'namespace="{namespace}",pod=~"{app_name}-.*"'
        ready = self._range(
            f'sum(kube_pod_status_ready{{condition="true",{pod_sel}}})', start, end)
        restarts = instant_value(self._instant(
            f'sum(increase(kube_pod_container_status_restarts_total{{{pod_sel}}}'
            f'[{window_s}s]))', end))

        return {
            "rps_avg": rps["avg"], "rps_min": rps["min"], "rps_max": rps["max"],
            "error_rate_avg": err["avg"], "error_rate_peak": err["peak"],
            "http_5xx_count": five_xx,
            "status_code_dist": {k: int(v) for k, v in dist.items()},
            "latency_p50_avg_ms": p50["avg"], "latency_p50_peak_ms": p50["peak"],
            "latency_p95_avg_ms": p95["avg"], "latency_p95_peak_ms": p95["peak"],
            "latency_p99_avg_ms": p99["avg"], "latency_p99_peak_ms": p99["peak"],
            "min_ready_pods": int(min(ready)) if ready else 0,
            "restart_count": int(restarts),
            "recovery_seconds": None,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_prometheus_parsers.py -v && pytest -q`
Expected: 4 PASS + 전체 통과

- [ ] **Step 5: Commit**

```bash
git add app/services/real/prometheus.py tests/test_prometheus_parsers.py
git commit -m "✨ RealPrometheus — Istio 구간 소급 집계 + RED (파서는 순수 함수)"
```

---

### Task 4: metrics_collector + 워처 훅 + deps 배선

**Files:**
- Create: `app/services/metrics_collector.py`
- Modify: `app/deps.py` (make_prometheus/make_loki 신설, get_* 팩토리 경유)
- Modify: `app/routers/experiments.py` (완료 확정 직후 수집 호출)
- Test: `tests/test_metrics_collector.py`

**Interfaces:**
- Consumes: Task 1 `r_index.compute`, Task 2 `phase_summary` 계약
- Produces: `collect_experiment_metrics(session, exp, prometheus) -> None` — completed 실험의 `baseline/fault/recovery_metrics`(계약 형태) + `recovery_metrics["recovery_seconds"]` + `exp.r_index` 저장, 실패는 경고 로그. `deps.make_prometheus()`/`deps.make_loki()`.

- [ ] **Step 1: Write the failing test**

`tests/test_metrics_collector.py`:

```python
"""수집기 — Stub Prometheus로 3구간 저장 + R지수 기록, 실패 격리."""
from datetime import datetime, timedelta, timezone

from app.db.repositories import ExperimentRepository
from app.db.seed import seed_data
from app.services.agent.handoff_schema import PhaseSummary
from app.services.metrics_collector import collect_experiment_metrics
from app.services.stubs import StubPrometheus


def _completed_exp(db_session, duration_s=60):
    seed_data(db_session)
    start = datetime(2026, 8, 13, 3, 0, tzinfo=timezone.utc)
    return ExperimentRepository(db_session).create(
        app_id=1, chaos_type="NetworkChaos",
        params={"action": "delay", "latency_ms": 200, "duration_s": duration_s},
        status="completed", started_at=start,
        finished_at=start + timedelta(seconds=duration_s + 41),
    )


def test_collect_stores_contract_metrics_and_r(db_session):
    exp = _completed_exp(db_session)
    collect_experiment_metrics(db_session, exp, StubPrometheus())

    for stored in (exp.baseline_metrics, exp.fault_metrics, exp.recovery_metrics):
        PhaseSummary(**stored)  # 계약 형태로 저장됐는가
    assert exp.recovery_metrics["recovery_seconds"] == 41.0  # finished - (start+duration)
    assert exp.r_index is not None and 0.0 <= exp.r_index <= 1.0


def test_collect_failure_is_isolated(db_session, caplog):
    exp = _completed_exp(db_session)

    class Broken:
        def phase_summary(self, *a, **k):
            raise RuntimeError("prometheus down")

    collect_experiment_metrics(db_session, exp, Broken())
    assert exp.status == "completed"       # 실험 상태 불변
    assert exp.r_index is None
    assert "실측 지표 수집 실패" in caplog.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_metrics_collector.py -v`
Expected: FAIL — 모듈 없음

- [ ] **Step 3: Implement collector**

`app/services/metrics_collector.py`:

```python
"""실험 완료 시 3구간(기준선/장애/회복) 소급 집계 + R지수 저장.

구간 경계(스펙 확정): 기준선 [started_at−5m, started_at] ·
장애 [started_at, started_at+duration] · 회복 [장애 종료, finished_at].
실패는 실험 상태를 건드리지 않고 경고 로그로 격리.
"""
import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from app.db.models import Experiment
from app.services import r_index
from app.services.interfaces import PrometheusService

logger = logging.getLogger(__name__)

BASELINE_WINDOW_S = 300
_PODKILL_GRACE_S = 30  # experiments.py 워처와 동일 값


def collect_experiment_metrics(session: Session, exp: Experiment,
                               prometheus: PrometheusService) -> None:
    try:
        app = exp.app
        duration = int(exp.params.get("duration_s") or _PODKILL_GRACE_S)
        injected = exp.started_at
        fault_end = injected + timedelta(seconds=duration)
        recovered = exp.finished_at or fault_end

        baseline = prometheus.phase_summary(
            app.namespace, app.name, "baseline",
            injected - timedelta(seconds=BASELINE_WINDOW_S), injected)
        fault = prometheus.phase_summary(
            app.namespace, app.name, "fault", injected, fault_end)
        recovery = prometheus.phase_summary(
            app.namespace, app.name, "recovery", fault_end, recovered)
        recovery["recovery_seconds"] = round(
            max((recovered - fault_end).total_seconds(), 0.0), 1)

        exp.baseline_metrics = baseline
        exp.fault_metrics = fault
        exp.recovery_metrics = recovery
        exp.r_index = r_index.compute(baseline, fault, recovery)["r"]
        session.commit()
    except Exception:
        logger.warning("실측 지표 수집 실패 — 실험 상태는 유지 (exp=%s)",
                       exp.id, exc_info=True)
```

- [ ] **Step 4: deps 팩토리**

`app/deps.py` — `make_chaos` 아래에 추가, 기존 `get_prometheus`/`get_loki`를 팩토리 경유로 교체:

```python
def make_prometheus() -> interfaces.PrometheusService:
    if settings.use_real_services:
        from app.services.real.prometheus import RealPrometheus  # lazy: httpx
        return RealPrometheus(settings)
    return stubs.StubPrometheus()


def make_loki() -> interfaces.LokiService:
    if settings.use_real_services:
        from app.services.real.loki import RealLoki  # lazy: httpx
        return RealLoki(settings)
    return stubs.StubLoki()
```

```python
def get_prometheus() -> interfaces.PrometheusService:
    return make_prometheus()


def get_loki() -> interfaces.LokiService:
    return make_loki()
```

(`RealLoki`는 Task 6에서 생성 — lazy import라 stub 모드 테스트는 지금도 통과)

- [ ] **Step 5: 워처 훅**

`app/routers/experiments.py` — 최종 상태 기록 블록(126–130행 부근):

```python
        fresh = s.get(Experiment, exp_id)
        if fresh and fresh.status == "running":
            fresh.status = final_status
            fresh.finished_at = datetime.now(timezone.utc)
            s.commit()
            if final_status == "completed":
                # 실측 3구간 소급 집계 + R지수 (실패해도 실험 상태 불변)
                collect_experiment_metrics(s, fresh, make_prometheus())
```

- import에 `from app.deps import make_chaos, make_prometheus`(기존 make_chaos import 라인 확장),
  `from app.services.metrics_collector import collect_experiment_metrics` 추가.
- 기존 finished_at 기록 방식(파일 내 기존 datetime 사용부)을 그대로 따르되 위치만 유지.

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_metrics_collector.py tests/test_experiments.py -v 2>&1 | tail -5 && pytest -q`
Expected: 신규 2 PASS + 기존 워처 테스트 통과(stub 완주 시 metrics 자동 저장돼도 무해) + 전체 통과

- [ ] **Step 7: Commit**

```bash
git add app/services/metrics_collector.py app/deps.py app/routers/experiments.py tests/test_metrics_collector.py
git commit -m "✨ 실험 완료 시 실측 3구간 소급 집계 + R지수 저장 (워처 훅)"
```

---

### Task 5: 조립기 R지수 실계산 연결

**Files:**
- Modify: `app/services/agent/assembler.py` (`_STUB_COMPONENT_SCORES` 제거 → `r_index.compute`)
- Test: `tests/test_handoff_assembler.py` (검증 추가)

**Interfaces:**
- Consumes: Task 1 `r_index.compute`
- Produces: 핸드오프 `r_index.availability/latency_score/recovery_score`가 실제 공식 값(같은 PhaseSummaries 입력 기준). `current_r`는 여전히 `exp.r_index` 저장값.

- [ ] **Step 1: Write the failing test**

`tests/test_handoff_assembler.py`에 추가:

```python
def test_r_breakdown_is_computed_not_placeholder(db_session):
    """항목별 점수가 자리값이 아니라 페이로드의 phase_summaries로 계산된 값."""
    from app.services import r_index

    exp = _seeded_exp(db_session)
    payload = assemble_handoff(db_session, StubHandoffSource(), exp)

    expected = r_index.compute(
        payload.phase_summaries.baseline.model_dump(),
        payload.phase_summaries.fault.model_dump(),
        payload.phase_summaries.recovery.model_dump(),
    )
    assert payload.r_index.availability == expected["availability"]
    assert payload.r_index.latency_score == expected["latency_score"]
    assert payload.r_index.recovery_score == expected["recovery_score"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_handoff_assembler.py -v`
Expected: 신규 테스트 FAIL (자리값 0.82 ≠ 계산값)

- [ ] **Step 3: Implement**

`app/services/agent/assembler.py`:
- import에 `from app.services import r_index` 추가, `_STUB_COMPONENT_SCORES` 상수 삭제.
- `assemble_handoff` 내 `phase_summaries` 조립을 지역 변수로 뽑고 점수 계산:

```python
    summaries = PhaseSummaries(
        baseline=_phase_summary(exp, source, "baseline"),
        fault=_phase_summary(exp, source, "fault"),
        recovery=_phase_summary(exp, source, "recovery"),
    )
    scores = r_index.compute(summaries.baseline.model_dump(),
                             summaries.fault.model_dump(),
                             summaries.recovery.model_dump())
```

- `AgentHandoffPayload(...)` 호출부에서 `phase_summaries=summaries`,

```python
        r_index=RIndexBreakdown(
            availability=scores["availability"],
            latency_score=scores["latency_score"],
            recovery_score=scores["recovery_score"],
            baseline_r=exp.baseline_r,
            current_r=exp.r_index,
            target_r=exp.target_r,
        ),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_handoff_assembler.py -v && pytest -q`
Expected: 전체 통과

- [ ] **Step 5: Commit**

```bash
git add app/services/agent/assembler.py tests/test_handoff_assembler.py
git commit -m "♻️ 핸드오프 R지수 항목별 점수 자리값 제거 — r_index.compute 실계산"
```

---

### Task 6: kube 공용 헬퍼 + RealK8s 확장 + RealLoki + RealHandoffSource

**Files:**
- Create: `app/services/real/kube.py`, `app/services/real/loki.py`, `app/services/real/handoff_source.py`
- Modify: `app/services/real/k8s.py` (nodes/pods/components 구현 + kube 헬퍼 사용), `app/services/real/chaos.py:51-55`, `app/services/real/builder.py:53-57` (헬퍼로 교체), `app/deps.py` (`make_handoff_source` real 분기)
- Test: `tests/test_deps_factories.py`

**Interfaces:**
- Consumes: Task 3 `RealPrometheus`, Task 4 `make_loki`
- Produces: `kube.load_kube(settings)`(incluster→kubeconfig(context) 폴백), `RealLoki(settings)`(tail + `error_logs(namespace, app_name, limit=20)`), `RealHandoffSource(settings)`(HandoffSourceService 5메서드), `RealK8s.nodes/pods/components`(Stub과 동일 키), `make_handoff_source()` real 분기

- [ ] **Step 1: Write the failing test**

`tests/test_deps_factories.py`:

```python
"""팩토리 stub 모드 검증 + real 모듈 import 무결성 (네트워크 호출 없음)."""
from app.deps import make_handoff_source, make_loki, make_prometheus
from app.services.stubs import StubHandoffSource, StubLoki, StubPrometheus


def test_factories_return_stubs_in_stub_mode():
    assert isinstance(make_prometheus(), StubPrometheus)
    assert isinstance(make_loki(), StubLoki)
    assert isinstance(make_handoff_source(), StubHandoffSource)


def test_real_modules_importable():
    """lazy import 대상 모듈이 문법·의존성 수준에서 깨지지 않았는지."""
    from app.services.real import handoff_source, kube, loki, prometheus  # noqa: F401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_deps_factories.py -v`
Expected: FAIL — `loki`/`handoff_source`/`kube` 모듈 없음

- [ ] **Step 3: kube 헬퍼 + 중복 제거**

`app/services/real/kube.py`:

```python
"""kubeconfig 로딩 공용 헬퍼 — incluster → 로컬 kubeconfig(k8s_context) 폴백."""


def load_kube(settings) -> None:
    from kubernetes import config  # lazy: k8s SDK

    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config(context=settings.k8s_context or None)
```

`real/k8s.py`의 `_api()` 2곳(:16-19, :47-50), `real/chaos.py:51-55`, `real/builder.py:53-57`의
try/except 블록을 `load_kube(self.s)` 호출로 교체 (`from app.services.real.kube import load_kube`).

- [ ] **Step 4: RealK8s nodes/pods/components**

`app/services/real/k8s.py`에 추가 (Stub 키와 동일 — `test_stubs_contract.py` 참조):

```python
    def nodes(self) -> list[dict]:
        api = self._api()
        out = []
        for n in api.list_node().items:
            conds = n.status.conditions or []
            ready = any(c.type == "Ready" and c.status == "True" for c in conds)
            labels = n.metadata.labels or {}
            out.append({
                "name": n.metadata.name,
                "type": labels.get("node.kubernetes.io/instance-type", ""),
                "status": "Ready" if ready else "NotReady",
                "role": labels.get("role", ""),
            })
        return out

    def pods(self, namespace: str) -> list[dict]:
        api = self._api()
        out = []
        for p in api.list_namespaced_pod(namespace).items:
            restarts = sum(cs.restart_count for cs in (p.status.container_statuses or []))
            out.append({
                "name": p.metadata.name, "namespace": namespace,
                "status": p.status.phase, "restarts": restarts,
            })
        return out

    _COMPONENTS = [("Prometheus", "monitoring", "prometheus"),
                   ("Grafana", "monitoring", "grafana"),
                   ("Loki", "monitoring", "loki"),
                   ("Chaos Mesh", "chaos-mesh", "chaos"),
                   ("ArgoCD", "argocd", "argocd")]

    def components(self) -> list[dict]:
        api = self._api()
        out = []
        for display, ns, keyword in self._COMPONENTS:
            try:
                pods = api.list_namespaced_pod(ns).items
                healthy = any(keyword in p.metadata.name and p.status.phase == "Running"
                              for p in pods)
            except Exception:
                healthy = False
            out.append({"name": display, "status": "Healthy" if healthy else "Down"})
        return out
```

- [ ] **Step 5: RealLoki**

`app/services/real/loki.py`:

```python
"""Loki 실조회 — query_range 기반 로그 tail + 에러 로그 선별(중복 제거)."""
from datetime import datetime, timedelta, timezone

import httpx

_TIMEOUT_S = 10.0
_LOOKBACK_MIN = 5


def parse_streams(resp: dict) -> list[str]:
    """query_range 응답 → (ts, line) 평탄화 후 최신순 라인 리스트."""
    entries: list[tuple[str, str]] = []
    for stream in resp.get("data", {}).get("result", []):
        for ts, line in stream.get("values", []):
            entries.append((ts, line))
    entries.sort(key=lambda e: e[0], reverse=True)
    return [line for _, line in entries]


class RealLoki:
    def __init__(self, settings):
        self.s = settings

    def _query(self, logql: str, limit: int) -> list[str]:
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=_LOOKBACK_MIN)
        r = httpx.get(f"{self.s.loki_url}/loki/api/v1/query_range", params={
            "query": logql, "limit": limit, "direction": "backward",
            "start": int(start.timestamp() * 1e9), "end": int(end.timestamp() * 1e9),
        }, timeout=_TIMEOUT_S)
        r.raise_for_status()
        return parse_streams(r.json())

    def tail(self, namespace: str, limit: int = 100) -> list[str]:
        return self._query(f'{{namespace="{namespace}"}}', limit)

    def error_logs(self, namespace: str, app_name: str, limit: int = 20) -> list[str]:
        lines = self._query(
            f'{{namespace="{namespace}", app="{app_name}"}} |~ "(?i)(error|exception|fail)"',
            limit * 5)
        seen: list[str] = []
        for line in lines:
            if line not in seen:
                seen.append(line)
            if len(seen) >= limit:
                break
        return seen
```

- [ ] **Step 6: RealHandoffSource**

`app/services/real/handoff_source.py`:

```python
"""핸드오프 재료 실조회 — Istio 설정·배포 정보·이벤트는 K8s API, 로그는 Loki, 지표는 Prometheus."""
from datetime import datetime, timedelta, timezone

import yaml  # kubernetes SDK 동반 의존성

from app.services.real.kube import load_kube

_ISTIO_GROUP = "networking.istio.io"
_ISTIO_VERSION = "v1beta1"


class RealHandoffSource:
    def __init__(self, settings):
        self.s = settings

    def _custom(self):
        from kubernetes import client
        load_kube(self.s)
        return client.CustomObjectsApi()

    def _core(self):
        from kubernetes import client
        load_kube(self.s)
        return client.CoreV1Api()

    def phase_summary(self, namespace: str, app_name: str, phase: str) -> dict:
        # 저장값 우선 규칙 때문에 폴백 전용 — 최근 5분 창으로 집계
        from app.services.real.prometheus import RealPrometheus
        end = datetime.now(timezone.utc)
        return RealPrometheus(self.s).phase_summary(
            namespace, app_name, phase, end - timedelta(minutes=5), end)

    def _istio_yaml(self, plural: str, namespace: str, name: str) -> str:
        from kubernetes.client.rest import ApiException
        try:
            obj = self._custom().get_namespaced_custom_object(
                _ISTIO_GROUP, _ISTIO_VERSION, namespace, plural, name)
        except ApiException as e:
            if e.status == 404:
                return ""  # DR 미배포 앱 등 — 스키마가 빈 문자열 허용
            raise
        obj.pop("status", None)
        obj.get("metadata", {}).pop("managedFields", None)
        return yaml.safe_dump(obj, allow_unicode=True, sort_keys=False)

    def istio_config(self, namespace: str, app_name: str) -> dict:
        return {
            "virtual_service_yaml": self._istio_yaml("virtualservices", namespace, app_name),
            "destination_rule_yaml": self._istio_yaml("destinationrules", namespace, app_name),
        }

    def deployment_info(self, namespace: str, app_name: str) -> dict:
        from kubernetes import client
        load_kube(self.s)
        dep = client.AppsV1Api().read_namespaced_deployment(app_name, namespace)
        c = dep.spec.template.spec.containers[0]
        sanitize = client.ApiClient().sanitize_for_serialization
        return {
            "replicas": dep.spec.replicas or 0,
            "probes": {
                "readiness": sanitize(c.readiness_probe) or {},
                "liveness": sanitize(c.liveness_probe) or {},
            },
            "resources": sanitize(c.resources) or {},
        }

    def events(self, namespace: str, app_name: str) -> list[dict]:
        out = []
        for ev in self._core().list_namespaced_event(namespace).items:
            obj = ev.involved_object
            if not (obj and obj.name and obj.name.startswith(app_name)):
                continue
            ts = ev.last_timestamp or ev.event_time
            out.append({
                "timestamp": ts.isoformat() if ts else "",
                "type": ev.type or "", "reason": ev.reason or "",
                "object": f"{(obj.kind or 'object').lower()}/{obj.name}",
                "message": ev.message or "",
            })
        return out

    def error_logs(self, namespace: str, app_name: str, limit: int = 20) -> list[str]:
        from app.services.real.loki import RealLoki
        return RealLoki(self.s).error_logs(namespace, app_name, limit)
```

- [ ] **Step 7: deps 분기**

`app/deps.py`의 `make_handoff_source`를 교체:

```python
def make_handoff_source() -> interfaces.HandoffSourceService:
    if settings.use_real_services:
        from app.services.real.handoff_source import RealHandoffSource  # lazy: k8s SDK
        return RealHandoffSource(settings)
    return stubs.StubHandoffSource()
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_deps_factories.py -v && pytest -q`
Expected: 2 PASS + 전체 통과 (기존 real 헬퍼 테스트 포함 — kube 리팩터가 순수 함수를 안 건드림)

- [ ] **Step 9: Commit**

```bash
git add app/services/real/kube.py app/services/real/loki.py app/services/real/handoff_source.py app/services/real/k8s.py app/services/real/chaos.py app/services/real/builder.py app/deps.py tests/test_deps_factories.py
git commit -m "✨ RealLoki·RealHandoffSource·RealK8s(nodes/pods/components) + kubeconfig 공용화"
```

---

### Task 7: 문서 갱신 + 전체 검증

**Files:**
- Modify: `CLAUDE.md` (Slice 4 항목 체크)
- Test: 전체 스위트

- [ ] **Step 1: CLAUDE.md 진행 현황 갱신**

`- [ ] **Slice 4 — 모니터링**: …` 줄을 다음으로 교체:

```markdown
- [x] **Slice 4 — 실측 연동** (백엔드, stub 테스트 검증·라이브는 별도 확인): 실험 완료 시 Prometheus 소급 집계(기준선=주입 전 5분/장애/회복)를 계약 형태로 `*_metrics` 저장 + `r_index` 실계산(`services/r_index.py`, 복구 상한 300s) · Real 4종(`real/prometheus·loki·handoff_source` + `RealK8s` nodes/pods/components) · kubeconfig 공용화(`real/kube.py`, `k8s_context` 지원) · Iac-aws: sut Istio 스크레이프 + generic-app DestinationRule. 차트 실데이터·SSE 갱신 등 화면 배선은 팀원 영역으로 이관
```

- [ ] **Step 2: 전체 검증**

Run: `pytest -q && rm -f chaoslab.db && USE_REAL_SERVICES=false python -c "
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as c:
    assert c.get('/healthz').status_code == 200
    r = c.post('/experiments/1/handoffs')
    assert r.status_code == 201
    assert 0 <= r.json()['payload']['r_index']['availability'] <= 1
print('smoke OK')" && rm -f chaoslab.db`
Expected: 전체 통과 + `smoke OK`

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "📝 진행 현황 — Slice 4 실측 연동(백엔드) 완료 표기"
```

---

## 완료 후

1. `superpowers:requesting-code-review`로 리뷰 → 수정 반영
2. 라이브 검증(스펙 §11): up.sh 완료 대기 → `argo/apply.sh` → SSH 터널(9090/3100) →
   `.env` USE_REAL_SERVICES=true → 앱 등록·배포 → loadgen 파드 → sut 메트릭 실존 확인 →
   NetworkChaos 실험 → `*_metrics`/`r_index`/핸드오프 실데이터 확인
3. PR 생성(pykido 스타일, 데이터 중심) — 라이브 검증 결과 포함
