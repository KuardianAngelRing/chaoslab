# 카오스 테스트 모니터링 목업 개선 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 스펙(`docs/superpowers/specs/2026-08-04-chaos-monitoring-data-design.md`)의 "실험 서사형" 모니터링 화면을 experiment_detail 페이지에 seed 데이터로 구동되는 목업으로 구현한다 — 이벤트 피드·안전장치 카드·R지수 분해(개요 탭) + baseline 오버레이·주입 구간 음영(메트릭 탭).

**Architecture:** 외부 시스템 데이터(K8s 이벤트)는 기존 패턴대로 `Protocol` 메서드 추가 + Stub 구현으로 공급한다(이벤트 DB 테이블 신설 보류 — 스펙 결정). R지수 분해는 Slice 5에서 재사용할 순수 함수(`services/r_index.py`)로 만들고 라우터가 seed된 metrics JSON으로 계산한다. 차트 오버레이는 서버가 `data-baseline` 속성으로 기준선 값을 내려주고 app.js가 점선 데이터셋 + 인라인 Chart.js 플러그인(음영)으로 그린다.

**Tech Stack:** FastAPI + Jinja + HTMX, Chart.js(CDN, 외부 플러그인 추가 금지), SQLite + Repository, pytest(hermetic).

## Global Constraints

- Python 3.12 고정. venv는 `.venv`(→`.venv.nosync` 심링크).
- 색은 전부 CSS 변수 — 하드코딩 금지. 인라인은 `style="color: var(--muted-foreground)"` 패턴. 카드/배지/버튼은 `tds-*` 클래스.
- mock 데이터는 `db/seed.py` 또는 Stub 서비스에서만 — 템플릿 하드코딩 금지.
- DB 스키마 변경 없음 (마이그레이션 없는 프로젝트 — 기존 JSON 컬럼만 사용).
- 아이콘: `<iconify-icon>` (UI는 `solar:*`).
- app.js는 전역 리스너 이벤트 위임 패턴 유지 — 요소별 리스너 부착 금지.
- 테스트는 hermetic: `tests/conftest.py`의 `client` fixture(in-memory SQLite + seed + Stub 강제)를 그대로 사용.
- **커밋은 사용자 명시 요청 시에만** (CLAUDE.md 최우선 규칙). 각 태스크의 커밋 스텝은 사용자가 커밋을 허락한 경우에만 수행하고, 아니면 건너뛴다. 커밋 컨벤션: `✨기능 ♻️리팩 ✅테스트 📝문서`, 파일단위 원자적.
- 실행 확인: `source .venv/bin/activate && pytest -q` (기존 89개 통과 유지).

## 파일 구조

| 파일 | 책임 |
|---|---|
| Create `app/services/r_index.py` | R지수 구성요소 계산 — 순수 함수, IO 없음 (Slice 5 재사용 예정) |
| Create `tests/test_r_index.py` | r_index 단위 테스트 |
| Modify `app/db/seed.py` | baseline `rate` 추가, `recovery_metrics`(ttr 포함) 채움 |
| Modify `app/services/interfaces.py` | `K8sService.events()` 프로토콜 추가 |
| Modify `app/services/stubs.py` | `StubK8s.events()` mock 이벤트 |
| Modify `app/routers/pages.py` | experiment_detail ctx: 이벤트 병합·r_comp·chaos spec·LLM 실비용 |
| Modify `app/templates/pages/experiment_detail.html` | 개요 탭: 이벤트 피드·안전장치 카드 신규, 현재 상태 카드에 R분해. 메트릭 탭: `data-baseline` 속성·범례 캡션 |
| Modify `app/static/js/app.js` | 차트 baseline 점선 데이터셋 + 주입 구간 음영 플러그인 |
| Modify `tests/test_seed.py`, `tests/test_stubs_contract.py`, `tests/test_pages.py` | 각 변경의 테스트 |

---

### Task 1: R지수 구성요소 순수 함수

**Files:**
- Create: `app/services/r_index.py`
- Test: `tests/test_r_index.py`

**Interfaces:**
- Consumes: 없음 (순수 함수)
- Produces: `r_components(baseline: dict, fault: dict, recovery: dict) -> dict | None` — 반환 dict 키: `availability`, `latency_score`, `recovery_speed`, `r` (모두 float, 소수 2자리). fault가 빈 dict이면 `None`. Task 4의 라우터가 이 시그니처를 그대로 사용.

- [ ] **Step 1: Write the failing test**

`tests/test_r_index.py` 생성:

```python
from app.services.r_index import r_components


def test_r_components_from_seed_shape():
    """seed와 같은 형태의 metrics로 산식(0.4·가용성+0.3·레이턴시+0.3·복구속도) 검증."""
    comp = r_components(
        baseline={"rate": 38.0, "error": 0.3, "p99": 89},
        fault={"error": 2.1, "p99": 412},
        recovery={"error": 0.4, "p99": 120, "ttr_s": 95},
    )
    assert comp["availability"] == 0.98      # 1 - 2.1/100
    assert comp["latency_score"] == 0.22     # 89/412
    assert comp["recovery_speed"] == 0.68    # 1 - 95/300
    assert comp["r"] == 0.66                 # 0.4*0.979 + 0.3*0.216 + 0.3*0.683


def test_r_components_no_fault_returns_none():
    assert r_components(baseline={}, fault={}, recovery={}) is None


def test_r_components_missing_optional_parts():
    """baseline p99·recovery ttr이 없어도 죽지 않고 해당 항 0점 처리."""
    comp = r_components(baseline={}, fault={"error": 50.0, "p99": 900}, recovery={})
    assert comp["availability"] == 0.5
    assert comp["latency_score"] == 0.0
    assert comp["recovery_speed"] == 0.0
    assert comp["r"] == 0.2


def test_r_components_clamped_to_unit_range():
    """error>100%, ttr>300s 같은 극단값도 0~1로 클램프."""
    comp = r_components(baseline={"p99": 100}, fault={"error": 150.0, "p99": 50},
                        recovery={"ttr_s": 900})
    assert comp["availability"] == 0.0
    assert comp["latency_score"] == 1.0      # baseline보다 빨라도 최대 1
    assert comp["recovery_speed"] == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_r_index.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.r_index'`

- [ ] **Step 3: Write minimal implementation**

`app/services/r_index.py` 생성:

```python
"""R지수 구성요소 계산 — 순수 함수 (IO 없음). 산식: R = 0.4·가용성 + 0.3·레이턴시점수 + 0.3·복구속도.

목업/Slice 5 공용. 정규화 기준:
- 가용성 = 1 - fault 구간 에러율(%)/100
- 레이턴시점수 = baseline p99 / fault p99 (baseline보다 빨라도 최대 1)
- 복구속도 = 1 - TTR(s)/300 (5분 이상 걸리면 0점)
"""

_MAX_TTR_S = 300.0


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def r_components(baseline: dict, fault: dict, recovery: dict) -> dict | None:
    """세 단계 metrics dict → 구성요소·R. fault 스냅샷이 없으면 None (계산 불가)."""
    if not fault:
        return None
    availability = _clamp(1.0 - float(fault.get("error", 0.0)) / 100.0)
    base_p99 = float(baseline.get("p99", 0.0)) if baseline else 0.0
    fault_p99 = float(fault.get("p99", 0.0))
    latency = _clamp(base_p99 / fault_p99) if base_p99 > 0 and fault_p99 > 0 else 0.0
    ttr = recovery.get("ttr_s") if recovery else None
    recovery_speed = _clamp(1.0 - float(ttr) / _MAX_TTR_S) if ttr is not None else 0.0
    r = 0.4 * availability + 0.3 * latency + 0.3 * recovery_speed
    return {
        "availability": round(availability, 2),
        "latency_score": round(latency, 2),
        "recovery_speed": round(recovery_speed, 2),
        "r": round(r, 2),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_r_index.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit (사용자가 커밋 허락한 경우만)**

```bash
git add app/services/r_index.py && git commit -m "✨ R지수 구성요소 순수함수 (0.4·가용성+0.3·레이턴시+0.3·복구속도)"
git add tests/test_r_index.py && git commit -m "✅ r_index 단위 테스트"
```

---

### Task 2: seed 보강 — baseline rate·recovery_metrics

**Files:**
- Modify: `app/db/seed.py:36-42`
- Test: `tests/test_seed.py`

**Interfaces:**
- Consumes: 없음
- Produces: seed된 실험 1번의 `baseline_metrics = {"rate": 38.0, "error": 0.3, "p99": 89}`, `recovery_metrics = {"error": 0.4, "p99": 120, "ttr_s": 95}`. Task 4(라우터 r_comp 계산)와 Task 5(템플릿 `data-baseline`)가 이 키들을 사용.

- [ ] **Step 1: Write the failing test**

`tests/test_seed.py`에 추가 (기존 테스트 유지):

```python
def test_seed_experiment_metrics_complete(db_session):
    """목업 화면(R분해·baseline 오버레이)이 쓰는 metrics 키가 모두 seed되어야 한다."""
    from app.db.seed import seed_data
    from app.db.repositories import ExperimentRepository

    seed_data(db_session)
    exp = ExperimentRepository(db_session).list_all()[0]
    assert {"rate", "error", "p99"} <= set(exp.baseline_metrics)
    assert {"error", "p99", "ttr_s"} <= set(exp.recovery_metrics)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_seed.py -v`
Expected: 새 테스트 FAIL — `baseline_metrics`에 `rate` 없음

- [ ] **Step 3: Implement**

`app/db/seed.py`의 `exps.create(...)` 호출을 수정:

```python
    exp = exps.create(
        app_id=boutique.id, chaos_type="NetworkChaos",
        params={"action": "delay", "latency_ms": 200, "duration_s": 300},
        status="running", baseline_r=0.42, r_index=0.65, target_r=0.7,
        baseline_metrics={"rate": 38.0, "error": 0.3, "p99": 89},
        fault_metrics={"error": 2.1, "p99": 412},
        recovery_metrics={"error": 0.4, "p99": 120, "ttr_s": 95},
    )
```

주의: `params`도 `chaos_specs.py`의 실제 필드명(`latency_ms`/`duration_s`)으로 정정한다 — Task 4의 안전장치 카드가 "params vs 허용범위"를 필드명으로 매칭하기 때문. (기존 `"delay": "200ms", "duration": "5m"`는 스키마와 불일치하는 초기 mock.)

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_seed.py tests/test_pages.py tests/test_experiments.py -v`
Expected: 전부 PASS (기존 테스트가 `params` 표기에 의존하지 않는지 확인 — 의존하는 assert가 있으면 새 필드명 기준으로 갱신)

- [ ] **Step 5: Commit (사용자가 커밋 허락한 경우만)**

```bash
git add app/db/seed.py tests/test_seed.py && git commit -m "✨ seed 보강: baseline rate·recovery ttr + params를 chaos_specs 필드명으로 정정"
```

---

### Task 3: K8sService.events 프로토콜 + Stub

**Files:**
- Modify: `app/services/interfaces.py:76-93` (K8sService)
- Modify: `app/services/stubs.py:49-71` (StubK8s)
- Test: `tests/test_stubs_contract.py`

**Interfaces:**
- Consumes: 없음
- Produces: `K8sService.events(namespace: str) -> list[dict]` — 각 dict 키: `source`("chaos"|"k8s"), `reason`(str), `message`(str), `ts`(**naive UTC datetime**). Task 4의 라우터가 DB의 naive datetime과 정렬 병합하므로 **tz-aware 금지** (섞이면 `TypeError`).

- [ ] **Step 1: Write the failing test**

`tests/test_stubs_contract.py`에 추가:

```python
def test_stub_k8s_events_shape():
    """이벤트 피드 계약: source/reason/message/ts, ts는 naive UTC(DB datetime과 정렬 호환)."""
    from app.services.stubs import StubK8s

    events = StubK8s().events("online-boutique")
    assert len(events) >= 3
    for e in events:
        assert {"source", "reason", "message", "ts"} <= set(e)
        assert e["source"] in ("chaos", "k8s")
        assert e["ts"].tzinfo is None  # naive — DB datetime과 비교 가능해야 함
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_stubs_contract.py -v`
Expected: 새 테스트 FAIL — `AttributeError: 'StubK8s' object has no attribute 'events'`

- [ ] **Step 3: Implement**

`app/services/interfaces.py`의 `K8sService`에 메서드 추가 (`components` 아래):

```python
    def events(self, namespace: str) -> list[dict]:
        """네임스페이스 K8s 이벤트 (Chaos Mesh 이벤트도 K8s 이벤트로 방출되므로 이 메서드 하나로 조회).
        각 항목: {source: 'chaos'|'k8s', reason, message, ts(naive UTC)}."""
        ...
```

`app/services/stubs.py` 상단 import 추가 후 `StubK8s`에 구현:

```python
from datetime import datetime, timedelta, timezone
```

```python
    def events(self, namespace: str) -> list[dict]:
        # ts는 naive UTC — DB(DateTime 컬럼)의 naive datetime과 정렬 병합되므로 tzinfo를 붙이지 않는다
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        return [
            {"source": "chaos", "reason": "Applied",
             "message": f"NetworkChaos CRD 적용 (namespace={namespace})", "ts": now - timedelta(minutes=4)},
            {"source": "chaos", "reason": "Started",
             "message": "delay 200ms 주입 시작", "ts": now - timedelta(minutes=3, seconds=50)},
            {"source": "k8s", "reason": "Unhealthy",
             "message": "readiness probe 실패: frontend-7d9", "ts": now - timedelta(minutes=3)},
            {"source": "k8s", "reason": "BackOff",
             "message": "cartservice-5fc 재시작 백오프", "ts": now - timedelta(minutes=2, seconds=30)},
            {"source": "k8s", "reason": "Started",
             "message": "frontend-7d9 컨테이너 시작", "ts": now - timedelta(minutes=1)},
        ]
```

(Real 구현은 Slice 4 라이브 검증 때 `services/real/k8s.py`에 추가 — 이번 범위 아님.)

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_stubs_contract.py -v`
Expected: PASS

- [ ] **Step 5: Commit (사용자가 커밋 허락한 경우만)**

```bash
git add app/services/interfaces.py app/services/stubs.py tests/test_stubs_contract.py && git commit -m "✨ K8sService.events 프로토콜 + Stub mock 이벤트 (이벤트 피드용)"
```

---

### Task 4: 라우터 ctx + 개요 탭 (이벤트 피드·안전장치·R분해)

**Files:**
- Modify: `app/routers/pages.py:98-117` (experiment_detail)
- Modify: `app/templates/pages/experiment_detail.html:110-174` (개요 탭)
- Test: `tests/test_pages.py`

**Interfaces:**
- Consumes: Task 1 `r_components`, Task 2 seed 키, Task 3 `K8sService.events`
- Produces: 템플릿 ctx 키 — `events`(병합·최신순 list[dict]), `r_comp`(dict|None), `chaos_spec`(dict|None — `CHAOS_SPECS[exp.chaos_type]`), `llm_cost`(float). Task 5는 이 태스크의 템플릿 파일을 이어서 수정.

- [ ] **Step 1: Write the failing tests**

`tests/test_pages.py`에 추가:

```python
def test_experiment_detail_event_feed(client):
    resp = client.get("/experiments/1")
    assert resp.status_code == 200
    assert "이벤트 피드" in resp.text
    assert "주입 시작" in resp.text            # StubK8s chaos 이벤트
    assert "Unhealthy" in resp.text            # StubK8s k8s 이벤트
    assert "실험 시작" in resp.text            # 플랫폼 이벤트 (DB)


def test_experiment_detail_safety_card(client):
    resp = client.get("/experiments/1")
    assert "안전장치" in resp.text
    assert "허용 범위" in resp.text
    assert "10~10000" in resp.text             # chaos_specs latency_ms 범위
    assert "자동 중단 조건" in resp.text
    assert "예정" in resp.text                 # 자동 중단은 표시만 (신규 개념)


def test_experiment_detail_r_breakdown(client):
    resp = client.get("/experiments/1")
    assert "가용성" in resp.text and "복구속도" in resp.text
    assert "0.98" in resp.text                 # availability (seed 기준 r_components)
    assert "0.68" in resp.text                 # recovery_speed
    assert "$1.23" not in resp.text            # 하드코딩 LLM 비용 제거
    assert "$0.04" in resp.text                # seed 실비용 3×0.012 반올림
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pages.py -v -k experiment_detail`
Expected: 새 테스트 3개 FAIL (기존 detail 테스트는 PASS 유지)

- [ ] **Step 3: Implement — 라우터**

`app/routers/pages.py` — import 추가:

```python
from app.deps import get_app_count, get_k8s, get_loki
from app.services.chaos_specs import CHAOS_SPECS
from app.services.r_index import r_components
```

(`get_k8s`는 이미 import되어 있음.) 모듈 레벨에 헬퍼 추가:

```python
def _platform_events(exp, iterations) -> list[dict]:
    """DB 상태에서 만드는 플랫폼 이벤트 — 실험 시작/종료, AI iteration."""
    events = [{"source": "platform", "reason": "ExperimentStarted",
               "message": f"{exp.chaos_type} 실험 시작", "ts": exp.started_at}]
    for it in iterations:
        events.append({"source": "platform", "reason": "AgentIteration",
                       "message": f"AI iteration {it.iteration} — {it.verdict}", "ts": it.created_at})
    if exp.finished_at:
        events.append({"source": "platform", "reason": "ExperimentFinished",
                       "message": "실험 종료", "ts": exp.finished_at})
    return events
```

`experiment_detail` 핸들러 시그니처에 `k8s: interfaces.K8sService = Depends(get_k8s)` 추가하고 ctx 확장:

```python
    events = sorted(
        k8s.events(exp.app.namespace) + _platform_events(exp, iterations),
        key=lambda e: e["ts"], reverse=True,
    )[:20]
    ctx = {
        "active_nav": "experiments",
        "app_count": app_count,
        "exp": exp,
        "iterations": iterations,
        "logs": loki.tail(exp.app.namespace, limit=20),
        "events": events,
        "r_comp": r_components(exp.baseline_metrics, exp.fault_metrics, exp.recovery_metrics),
        "chaos_spec": CHAOS_SPECS.get(exp.chaos_type),
        "llm_cost": sum(it.llm_cost_usd for it in iterations),
    }
```

- [ ] **Step 4: Implement — 개요 탭 템플릿**

`app/templates/pages/experiment_detail.html` 개요 탭(`data-tab-content="overview"`) 수정.

4-a. "현재 상태" 카드(라인 140-171)의 하드코딩 LLM 비용 줄을 실데이터로 교체하고, R 분해 블록을 카드 하단에 추가:

```jinja
                  <div class="flex items-center justify-between">
                    <span style="color: var(--muted-foreground);">LLM 비용</span>
                    <span class="font-bold mono">${{ "%.2f"|format(llm_cost) }}</span>
                  </div>
```

기존 progress-track 블록 아래에 추가:

```jinja
                  {% if r_comp %}
                  <div class="pt-3 mt-3 border-t" style="border-color: var(--border);">
                    <div class="text-[11px] font-bold uppercase mb-2" style="color: var(--muted-foreground);">
                      R = 0.4×가용성 + 0.3×레이턴시 + 0.3×복구속도
                    </div>
                    {% for label, val in [("가용성", r_comp.availability), ("레이턴시", r_comp.latency_score), ("복구속도", r_comp.recovery_speed)] %}
                    <div class="flex items-center gap-2 mb-1.5">
                      <span class="text-xs w-14" style="color: var(--muted-foreground);">{{ label }}</span>
                      <div class="progress-track flex-1"><div class="progress-fill" style="width: {{ (val * 100)|round|int }}%;"></div></div>
                      <span class="text-xs font-bold mono w-9 text-right">{{ "%.2f"|format(val) }}</span>
                    </div>
                    {% endfor %}
                  </div>
                  {% endif %}
```

4-b. "실험 정보" grid(라인 111-172) 아래에 안전장치 카드 + 이벤트 피드 카드를 새 grid로 추가 (개요 탭 닫는 `</div>` 직전):

```jinja
            <!-- 안전장치 + 이벤트 피드 -->
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div class="tds-card p-6">
                <div class="flex items-center gap-2 mb-4">
                  <iconify-icon icon="solar:shield-check-bold" width="18" style="color: var(--primary);"></iconify-icon>
                  <div class="font-extrabold">안전장치</div>
                </div>
                <div class="space-y-3 text-sm">
                  <div class="text-[11px] font-bold uppercase" style="color: var(--muted-foreground);">주입 파라미터 · 허용 범위</div>
                  {% if chaos_spec and chaos_spec.fields %}
                  {% for name, rule in chaos_spec.fields.items() %}
                  <div class="flex items-center justify-between">
                    <span style="color: var(--muted-foreground);">{{ rule.label }}</span>
                    <span>
                      <span class="font-bold mono">{{ exp.params.get(name, "—") }}</span>
                      <span class="text-xs ml-1" style="color: var(--muted-foreground);">(허용 범위 {{ rule.min }}~{{ rule.max }})</span>
                    </span>
                  </div>
                  {% endfor %}
                  {% else %}
                  <div style="color: var(--muted-foreground);">원샷 주입 — 범위 파라미터 없음</div>
                  {% endif %}
                  <div class="pt-3 border-t" style="border-color: var(--border);">
                    <div class="text-[11px] font-bold uppercase mb-2" style="color: var(--muted-foreground);">자동 중단 조건</div>
                    <div class="flex items-center justify-between">
                      <span style="color: var(--muted-foreground);">Error Rate &gt; 50% · 60초 지속</span>
                      <span class="tds-badge badge-muted">예정</span>
                    </div>
                  </div>
                </div>
              </div>

              <div class="tds-card p-6">
                <div class="flex items-center gap-2 mb-4">
                  <iconify-icon icon="solar:history-bold" width="18" style="color: var(--primary);"></iconify-icon>
                  <div class="font-extrabold">이벤트 피드</div>
                </div>
                <div class="space-y-2.5 overflow-y-auto" style="max-height: 320px;">
                  {% for e in events %}
                  <div class="flex items-start gap-2.5 text-sm">
                    <iconify-icon width="16" class="mt-0.5 shrink-0"
                      icon="{% if e.source == 'chaos' %}solar:bug-bold{% elif e.source == 'k8s' %}solar:box-bold{% else %}solar:magic-stick-3-bold{% endif %}"
                      style="color: {% if e.reason in ('Unhealthy', 'BackOff') %}var(--warning){% else %}var(--muted-foreground){% endif %};"></iconify-icon>
                    <div class="flex-1 min-w-0">
                      <span class="text-xs font-bold mr-1.5">{{ e.reason }}</span>
                      <span class="text-xs" style="color: var(--muted-foreground);">{{ e.message }}</span>
                    </div>
                    <span class="text-[11px] mono shrink-0" style="color: var(--muted-foreground);">{{ e.ts.strftime("%H:%M:%S") }}</span>
                  </div>
                  {% endfor %}
                </div>
              </div>
            </div>
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_pages.py -v`
Expected: 전부 PASS

- [ ] **Step 6: Commit (사용자가 커밋 허락한 경우만)**

```bash
git add app/routers/pages.py && git commit -m "✨ 실험 상세 ctx: 이벤트 병합·R분해·허용범위·LLM 실비용"
git add app/templates/pages/experiment_detail.html && git commit -m "✨ 개요 탭: 이벤트 피드·안전장치 카드 + R지수 구성요소 분해"
git add tests/test_pages.py && git commit -m "✅ 실험 상세 신규 카드 테스트"
```

---

### Task 5: 메트릭 탭 — baseline 점선 오버레이 + 주입 구간 음영

**Files:**
- Modify: `app/static/js/app.js:145-226` (Chart.js 구역)
- Modify: `app/templates/pages/experiment_detail.html:176-261` (메트릭 탭)
- Test: `tests/test_pages.py`

**Interfaces:**
- Consumes: Task 2의 seed `baseline_metrics` 키(`rate`/`error`/`p99`), Task 4가 수정한 템플릿 파일
- Produces: canvas `data-baseline` 속성 규약 — `makeTimeSeries`가 읽어 점선 데이터셋 생성. 인라인 플러그인 `faultShade`(옵션 `{from, to}` 라벨 인덱스).

- [ ] **Step 1: Write the failing test**

`tests/test_pages.py`에 추가:

```python
def test_experiment_detail_baseline_overlay_attrs(client):
    """메트릭 탭 차트가 서버 렌더된 기준선 값을 data-baseline으로 받는다."""
    resp = client.get("/experiments/1")
    assert 'id="metricRate2" data-baseline="38' in resp.text
    assert 'id="metricError2" data-baseline="0.3"' in resp.text
    assert 'id="metricLatency2" data-baseline="89"' in resp.text
    assert "주입 구간" in resp.text            # 범례 캡션
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pages.py::test_experiment_detail_baseline_overlay_attrs -v`
Expected: FAIL — canvas에 `data-baseline` 없음

- [ ] **Step 3: Implement — 템플릿**

메트릭 탭의 canvas 3개에 속성 추가 (Pod 차트는 기준선 무의미 — 제외):

```jinja
<div class="chart-box"><canvas id="metricRate2" data-baseline="{{ exp.baseline_metrics.get('rate', '') }}"></canvas></div>
<div class="chart-box"><canvas id="metricError2" data-baseline="{{ exp.baseline_metrics.get('error', '') }}"></canvas></div>
<div class="chart-box"><canvas id="metricLatency2" data-baseline="{{ exp.baseline_metrics.get('p99', '') }}"></canvas></div>
```

"시간 범위" 필터 카드(라인 179-189)의 `<div class="flex-1"></div>` 앞에 범례 캡션 추가:

```jinja
              <span class="text-xs flex items-center gap-1.5" style="color: var(--muted-foreground);">
                <span style="border-top: 2px dashed var(--muted-foreground); width: 16px; display: inline-block;"></span> 기준선 평균
                <span class="inline-block w-4 h-3 rounded-sm ml-2" style="background: color-mix(in srgb, var(--danger) 8%, transparent);"></span> 주입 구간
              </span>
```

- [ ] **Step 4: Implement — app.js**

`chartCommon()` 아래에 음영 플러그인 추가·등록 (한 번만):

```js
// ── 카오스 주입 구간 음영 (options.plugins.faultShade = {from, to} 라벨 인덱스) ──
const faultShade = {
  id: 'faultShade',
  beforeDatasetsDraw(chart, _args, opts) {
    if (opts.from == null) return;
    const { ctx, chartArea, scales } = chart;
    if (!scales.x) return;
    const x0 = scales.x.getPixelForValue(opts.from);
    const x1 = scales.x.getPixelForValue(opts.to);
    ctx.save();
    ctx.fillStyle = 'rgba(220, 38, 38, 0.07)';
    ctx.fillRect(x0, chartArea.top, x1 - x0, chartArea.bottom - chartArea.top);
    ctx.restore();
  }
};
Chart.register(faultShade);
```

`makeTimeSeries`를 확장 — `data-baseline` 점선 데이터셋 + 음영 구간(랜덤 mock 시리즈의 장애 구간인 인덱스 5~18과 일치):

```js
function makeTimeSeries(canvasId, color, base, variance, isStep = false) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;
  const labels = Array.from({ length: 30 }, (_, i) => `${30 - i}m`).reverse();
  const data = labels.map((_, i) => {
    if (i < 5) return base * 0.3;
    if (i < 18) return base + (Math.random() - 0.5) * variance;
    return base * 0.4 + (Math.random() - 0.5) * (variance * 0.3);
  });
  const datasets = [{ data, borderColor: color, backgroundColor: color + '22', fill: true, tension: isStep ? 0 : 0.4, stepped: isStep, pointRadius: 0, borderWidth: 2 }];
  const baseline = parseFloat(ctx.dataset.baseline);
  if (!isNaN(baseline)) {
    datasets.push({ data: labels.map(() => baseline), borderColor: tdsTextColor(), borderDash: [4, 4], pointRadius: 0, borderWidth: 1.5, fill: false });
  }
  const cc = chartCommon();
  window._charts[canvasId] = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets },
    options: { ...cc, plugins: { ...cc.plugins, faultShade: { from: 5, to: 18 } }, scales: { ...cc.scales, x: { display: false } } }
  });
}
```

(`chartCommon()`의 `plugins.legend`는 유지되도록 `...cc.plugins` 스프레드 주의. Pod 차트는 그대로 둔다.)

- [ ] **Step 5: Run tests + 수동 확인**

Run: `pytest tests/test_pages.py -v`
Expected: 전부 PASS

수동: `uvicorn app.main:app --reload` → `http://localhost:8000/experiments/1` 메트릭 탭에서 ① 점선 기준선 ② 붉은 음영(5~18 구간) ③ 다크 모드 토글 시 차트 재렌더 정상 확인.

- [ ] **Step 6: Commit (사용자가 커밋 허락한 경우만)**

```bash
git add app/static/js/app.js && git commit -m "✨ 차트 baseline 점선 + 주입 구간 음영 플러그인"
git add app/templates/pages/experiment_detail.html && git commit -m "✨ 메트릭 탭: data-baseline 속성·범례 캡션"
git add tests/test_pages.py && git commit -m "✅ baseline 오버레이 속성 테스트"
```

---

### Task 6: 전체 검증

**Files:**
- 없음 (검증만)

**Interfaces:**
- Consumes: Task 1~5 전체
- Produces: 통과한 테스트 스위트

- [ ] **Step 1: 전체 테스트**

Run: `source .venv/bin/activate && pytest -q`
Expected: 기존 89개 + 신규(약 9개) 전부 PASS, FAIL 0

- [ ] **Step 2: 수동 스모크**

`uvicorn app.main:app --reload` 후 확인 체크리스트:
- `/experiments/1` 개요 탭: 이벤트 피드(플랫폼+chaos+k8s 섞여 최신순)·안전장치(지연 200, 허용 범위 10~10000)·R 분해 바 3개
- 메트릭 탭: 점선·음영·범례
- 다크 모드 토글: 색 전부 CSS 변수 따라 전환, 차트 재렌더
- HTMX 사이드바 네비로 나갔다 들어와도 차트 재생성 정상 (`htmx:afterSwap` → `initCharts`)

- [ ] **Step 3: 진행 현황 문서 갱신 제안**

CLAUDE.md 진행 현황에 목업 개선 내역 반영은 커밋과 함께 사용자에게 제안만 한다 (직접 커밋 금지).

---

## Self-Review 결과

- **Spec coverage**: 스펙 §3(개요 탭 3종 = Task 4, 메트릭 탭 오버레이 = Task 5, seed 공급 = Task 2·3, DB 테이블 보류 = 준수). 스펙 §1-④ 자동 중단 조건 "표시만" = Task 4의 badge-muted "예정". 스펙 §2(AI 전달 데이터)는 노션 문서화로 완료 — Phase 3 구현 범위라 본 계획에 태스크 없음(스펙에 명시됨).
- **Placeholder scan**: 없음.
- **Type consistency**: `r_components` 반환 키(`availability`/`latency_score`/`recovery_speed`/`r`)가 Task 1 구현·테스트·Task 4 템플릿에서 일치. `events` dict 키(`source`/`reason`/`message`/`ts`)가 Task 3 계약·Task 4 병합·템플릿에서 일치. naive datetime 제약이 Task 3 테스트로 고정됨.
