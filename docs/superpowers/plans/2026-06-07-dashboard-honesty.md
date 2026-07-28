# 대시보드 정직화 + 비주얼 polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 대시보드의 하드코딩 가짜 데이터를 seed/DB 단일출처로 옮겨 정직화하고, 진행중 실험+AI 분석을 단일 반응형 카드로 합치며, 사이드바 active 하이라이트 버그와 불필요 UI를 정리한다.

**Architecture:** 접근 A(seed 기반 정직화) — 가짜를 지우지 않고 seed/DB로 이동해 화면은 채우되 모든 숫자가 추적 가능. 라우터가 실 context를 조립(작은 헬퍼로 핸들러 얇게), 템플릿은 그것만 렌더. 차트·사이드바 active는 기존 JS 위임 패턴으로 처리. **최소 변경·추측성 추상화 금지·기존 패턴 준수.**

**Tech Stack:** FastAPI + Jinja + HTMX + Chart.js · SQLite/SQLAlchemy · pytest(in-memory StaticPool + seed fixture)

---

## 구현 원칙 (모든 태스크 공통)

- **최소 변경·최소 구현.** 요청된 것만. 추측성 추상화 금지. 추후 리팩토링 쉽게(작은 헬퍼, 얇은 핸들러).
- 기존 패턴 준수: `render_page`(풀셸/부분 분기), Repository, JS 이벤트 위임.
- 깔끔하게: 주변 코드의 주석 밀도·네이밍·관용구에 맞춤.
- 커밋은 각 태스크 끝에서. 메시지는 CLAUDE.md 컨벤션(✨🐛♻️🔧📝✅) 따름.

---

## File Structure

- `app/db/seed.py` — running 실험에 baseline/fault metrics 추가 (Task 1)
- `app/routers/pages.py` — `dashboard` 핸들러 context 보강 + `_recent_activity`·`_elapsed_min` 헬퍼 (Task 2)
- `app/templates/pages/dashboard.html` — hero·KPI·합친 카드·시스템상태 (Task 3·4·5)
- `app/static/js/app.js` — rIndexChart 데이터 주입 + 사이드바 active 동기화 (Task 6)
- `app/templates/partials/_sidebar.html` — EKS 박스 제거 (Task 7)
- `tests/test_pages.py` — 라우트 content 어서션 추가 (Task 1·2·3·4·5·7)

---

## Task 1: seed에 baseline/fault metrics 보강

**Files:**
- Modify: `app/db/seed.py:36-40` (exp 생성 부분)
- Test: `tests/test_seed.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_seed.py`에 추가:

```python
def test_seed_running_experiment_has_metrics(db_session):
    from app.db.seed import seed_data
    from app.db.repositories import ExperimentRepository

    seed_data(db_session)
    running = [e for e in ExperimentRepository(db_session).list_all() if e.status == "running"]
    assert running, "running 실험이 seed돼야 함"
    exp = running[0]
    assert exp.baseline_metrics.get("p99") == 89
    assert exp.fault_metrics.get("p99") == 412
    assert exp.fault_metrics.get("error") == 2.1
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_seed.py::test_seed_running_experiment_has_metrics -v`
Expected: FAIL — `assert {} .get("p99") == 89` (metrics 비어있음)

- [ ] **Step 3: seed 보강**

`app/db/seed.py`의 `exp = exps.create(...)` 호출에 두 인자 추가:

```python
    exp = exps.create(
        app_id=boutique.id, chaos_type="NetworkChaos",
        params={"action": "delay", "delay": "200ms", "duration": "5m"},
        status="running", baseline_r=0.42, r_index=0.65, target_r=0.7,
        baseline_metrics={"error": 0.3, "p99": 89},
        fault_metrics={"error": 2.1, "p99": 412},
    )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_seed.py -v`
Expected: PASS (기존 seed 테스트도 회귀 없음)

- [ ] **Step 5: 커밋**

```bash
git add app/db/seed.py tests/test_seed.py
git commit -m "✅ seed: running 실험에 baseline/fault metrics 보강"
```

---

## Task 2: 라우터 context 보강 + 헬퍼

**Files:**
- Modify: `app/routers/pages.py:1-37` (import + `dashboard` 핸들러, 상단에 헬퍼 2개)
- Test: `tests/test_pages.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_pages.py`에 추가:

```python
def test_recent_activity_assembles_and_limits(db_session):
    from app.db.seed import seed_data
    from app.routers.pages import _recent_activity

    seed_data(db_session)
    items = _recent_activity(db_session)
    assert len(items) <= 5
    assert all({"icon", "text", "ts"} <= set(it) for it in items)
    # seed의 앱/실험/빌드가 텍스트로 등장
    joined = " ".join(it["text"] for it in items)
    assert "online-boutique" in joined


def test_elapsed_min_handles_naive_datetime():
    from datetime import datetime, timezone, timedelta
    from app.routers.pages import _elapsed_min

    assert _elapsed_min(None) is None
    past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=12)
    assert _elapsed_min(past) >= 11  # 대략 12분
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_pages.py::test_recent_activity_assembles_and_limits tests/test_pages.py::test_elapsed_min_handles_naive_datetime -v`
Expected: FAIL — `ImportError: cannot import name '_recent_activity'`

- [ ] **Step 3: 헬퍼 + 핸들러 구현**

`app/routers/pages.py` 상단 import에 추가:

```python
from datetime import datetime, timezone

from app.db.repositories import (
    AppRepository,
    BuildRepository,
    ExperimentRepository,
    IterationRepository,
)
```

(기존 import에 `BuildRepository` 없으면 추가. `IterationRepository`는 이미 있음.)

`router = APIRouter()` 아래에 헬퍼 2개 추가:

```python
def _elapsed_min(started_at) -> int | None:
    """started_at(naive/aware 모두) ~ 현재의 경과 분. None이면 None."""
    if started_at is None:
        return None
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return int((datetime.now(timezone.utc) - started_at).total_seconds() // 60)


def _recent_activity(session, limit: int = 5) -> list[dict]:
    """전용 활동 테이블 없이 apps·builds·experiments를 최근순으로 합쳐 상위 N개."""
    items: list[dict] = []
    for app in AppRepository(session).list_all():
        items.append({"icon": "solar:add-circle-bold", "badge": None,
                      "text": f"{app.name} 신규 등록", "ts": app.created_at})
        for b in BuildRepository(session).list_for_app(app.id):
            items.append({"icon": "solar:rocket-bold", "badge": b.status,
                          "text": f"{app.name} 새 SHA {b.image_tag[:8]} 배포", "ts": b.started_at})
    for exp in ExperimentRepository(session).list_all():
        items.append({"icon": "solar:bug-bold", "badge": exp.status,
                      "text": f"{exp.app.name}에 {exp.chaos_type} 주입", "ts": exp.started_at})
    items.sort(key=lambda x: x["ts"], reverse=True)
    return items[:limit]
```

`dashboard` 핸들러 본문 교체:

```python
@router.get("/")
def dashboard(
    request: Request,
    session: Session = Depends(get_session),
    app_count: int = Depends(get_app_count),
    k8s: interfaces.K8sService = Depends(get_k8s),
):
    exps = ExperimentRepository(session).list_all()
    running = [e for e in exps if e.status == "running"]
    running_exp = running[0] if running else None
    iterations = sorted(running_exp.iterations, key=lambda i: i.iteration) if running_exp else []
    latest_iter = iterations[-1] if iterations else None
    r_series = ([running_exp.baseline_r] + [it.r_index for it in iterations]) if running_exp else []
    r_labels = (["기준"] + [f"iter {it.iteration}" for it in iterations]) if running_exp else []
    llm_cost_total = sum(it.llm_cost_usd for e in exps for it in e.iterations)
    latest_r = next((f"{e.r_index:.2f}" for e in exps if e.r_index is not None), "—")
    ctx = {
        "active_nav": "dashboard",
        "app_count": app_count,
        "running_count": len(running),
        "running_exp": running_exp,
        "iterations": iterations,
        "latest_iter": latest_iter,
        "r_series": r_series,
        "r_labels": r_labels,
        "elapsed_min": _elapsed_min(running_exp.started_at) if running_exp else None,
        "llm_cost_total": llm_cost_total,
        "latest_r": latest_r,
        "components": k8s.components(),
        "node_count": len(k8s.nodes()),
        "recent": _recent_activity(session),
    }
    return render_page(request, "pages/dashboard.html", ctx)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_pages.py -v`
Expected: PASS. (이 시점 대시보드 템플릿은 아직 옛 변수 사용 → `/` 라우트는 여전히 200이어야 함. 만약 새 변수 미사용으로 깨지면 Task 3에서 해소. `test_dashboard_full_page`가 통과하는지 확인.)

- [ ] **Step 5: 커밋**

```bash
git add app/routers/pages.py tests/test_pages.py
git commit -m "✨ dashboard 라우터: 실 context 조립(_recent_activity·_elapsed_min·비용합계)"
```

---

## Task 3: 대시보드 hero + KPI 정직화 (템플릿)

**Files:**
- Modify: `app/templates/pages/dashboard.html:6-65` (Hero + KPI 4개)
- Test: `tests/test_pages.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_pages.py`에 추가:

```python
def test_dashboard_hero_and_kpi_honest(client):
    resp = client.get("/")
    assert resp.status_code == 200
    # 제거되어야 할 가짜들
    assert "Phase 4" not in resp.text
    assert "👋" not in resp.text
    assert "$5.00 한도" not in resp.text
    assert "+1 어제 대비" not in resp.text
    # 새 라벨
    assert "진행중인 실험" in resp.text
    assert "총 소요된 LLM 비용" in resp.text
    assert "최근 R 지수" in resp.text
    # 실 비용(seed 3 iter × 0.012 = 0.036) — $0.04 표기
    assert "$0.04" in resp.text
    # '새 실험 시작' 버튼 제거
    assert "새 실험 시작" not in resp.text
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_pages.py::test_dashboard_hero_and_kpi_honest -v`
Expected: FAIL — "Phase 4" 등 가짜 문구가 아직 존재

- [ ] **Step 3: Hero 교체**

`dashboard.html`의 Hero 블록(`<!-- Hero -->` ~ `gradient-line` 위)에서 Phase 라인·👋·부제·새 실험 시작 버튼 제거. 다음으로 교체:

```html
          <!-- Hero -->
          <div class="mb-8">
            <div class="flex items-end justify-between mb-2">
              <div>
                <h1 class="text-3xl font-extrabold">대시보드</h1>
              </div>
              <div class="flex items-center gap-2">
                <button class="tds-btn-muted text-sm"
                        hx-get="/" hx-target="#main-content" hx-swap="innerHTML">
                  <iconify-icon icon="solar:refresh-bold" width="16"></iconify-icon>
                  새로고침
                </button>
              </div>
            </div>
            <div class="gradient-line mt-6"></div>
          </div>
```

- [ ] **Step 4: KPI 4개 교체**

KPI 그리드(`<!-- KPI 카드 4개 -->`)의 4개 카드를 교체:

```html
          <!-- KPI 카드 4개 -->
          <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4 mb-8">
            <div class="tds-card p-5 hover-lift">
              <div class="flex items-start justify-between mb-3">
                <span class="tossface">📦</span>
              </div>
              <div class="text-3xl font-extrabold mb-1">{{ app_count }}</div>
              <div class="text-sm" style="color: var(--muted-foreground);">배포된 앱</div>
            </div>

            <div class="tds-card p-5 hover-lift">
              <div class="flex items-start justify-between mb-3">
                <span class="tossface">🧪</span>
                {% if elapsed_min is not none %}<span class="tds-badge badge-warning">{{ elapsed_min }}분 경과</span>{% endif %}
              </div>
              <div class="text-3xl font-extrabold mb-1">{{ running_count }}</div>
              <div class="text-sm" style="color: var(--muted-foreground);">진행중인 실험</div>
            </div>

            <div class="tds-card p-5 hover-lift">
              <div class="flex items-start justify-between mb-3">
                <span class="tossface">📈</span>
              </div>
              <div class="text-3xl font-extrabold mb-1">{{ latest_r }}</div>
              <div class="text-sm" style="color: var(--muted-foreground);">최근 R 지수</div>
            </div>

            <div class="tds-card p-5 hover-lift">
              <div class="flex items-start justify-between mb-3">
                <span class="tossface">💸</span>
              </div>
              <div class="text-3xl font-extrabold mb-1">${{ "%.2f"|format(llm_cost_total) }}</div>
              <div class="text-sm" style="color: var(--muted-foreground);">총 소요된 LLM 비용</div>
            </div>
          </div>
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `pytest tests/test_pages.py -v`
Expected: PASS (hero·KPI 테스트 + 기존 회귀 없음)

- [ ] **Step 6: 커밋**

```bash
git add app/templates/pages/dashboard.html tests/test_pages.py
git commit -m "✨ 대시보드 hero·KPI 정직화(가짜 delta/한도/Phase 제거, 실 비용·라벨)"
```

---

## Task 4: 진행중 실험 + AI 분석 = 단일 반응형 카드 (템플릿)

**Files:**
- Modify: `app/templates/pages/dashboard.html:67-160` (기존 "진행 중 카오스 실험 + AI 루프" 그리드 전체)
- Test: `tests/test_pages.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
def test_dashboard_merged_experiment_card(client):
    resp = client.get("/")
    assert resp.status_code == 200
    # 합친 카드의 실데이터(seed)
    assert "online-boutique" in resp.text and "NetworkChaos" in resp.text
    assert "관찰" in resp.text and "가설" in resp.text and "권고" in resp.text
    assert "timeout 1s→3s" in resp.text  # seed recommender_output
    # 제거 대상
    assert "자동 적용" not in resp.text       # Phase 3 버튼 삭제
    assert "주입 중" not in resp.text          # 상태 배지 삭제
    assert "Iteration 4 / 10" not in resp.text  # iteration 카운트 줄 삭제
    # 정직성 라벨
    assert "Phase 3" in resp.text  # AI 진단 배지
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_pages.py::test_dashboard_merged_experiment_card -v`
Expected: FAIL — "자동 적용"/"주입 중" 아직 존재, recommender 텍스트 미렌더

- [ ] **Step 3: 합친 카드로 교체**

기존 `<!-- 진행 중 카오스 실험 + AI 루프 -->` div(3열 그리드 전체, Active Experiment 카드 + LLM 추천 카드)를 다음 단일 카드로 교체:

```html
          <!-- 진행중 실험 + AI 진단 (단일 반응형 카드) -->
          <div class="tds-card p-6 mb-8">
            {% if running_exp %}
            <!-- 헤더 -->
            <div class="flex items-center justify-between mb-4">
              <div class="flex items-center gap-3">
                <span class="tossface-lg">🧪</span>
                <div>
                  <div class="font-extrabold text-lg">{{ running_exp.app.name }} · {{ running_exp.chaos_type }}</div>
                  <div class="text-xs" style="color: var(--muted-foreground);">
                    주입: {% for k, v in running_exp.params.items() %}{{ v }}{% if not loop.last %} · {% endif %}{% endfor %}
                  </div>
                </div>
              </div>
              {% if elapsed_min is not none %}
              <span class="tds-badge badge-muted">
                <iconify-icon icon="solar:clock-circle-bold" width="14"></iconify-icon>
                {{ elapsed_min }}분 경과
              </span>
              {% endif %}
            </div>

            <!-- 좌(지표·차트) / 우(AI 진단) : wide=2열, narrow=적층 -->
            <div class="grid grid-cols-1 xl:grid-cols-2 gap-6">
              <!-- 좌 -->
              <div>
                <div class="grid grid-cols-3 gap-3 mb-4">
                  <div class="p-3 rounded-2xl" style="background: var(--muted);">
                    <div class="text-[11px] font-semibold uppercase tracking-wide" style="color: var(--muted-foreground);">에러율</div>
                    <div class="text-xl font-extrabold mt-1" style="color: var(--danger);">{{ running_exp.fault_metrics.get("error", "—") }}%</div>
                    <div class="text-[10px]" style="color: var(--muted-foreground);">기준선 {{ running_exp.baseline_metrics.get("error", "—") }}%</div>
                  </div>
                  <div class="p-3 rounded-2xl" style="background: var(--muted);">
                    <div class="text-[11px] font-semibold uppercase tracking-wide" style="color: var(--muted-foreground);">p99 레이턴시</div>
                    <div class="text-xl font-extrabold mt-1" style="color: var(--warning);">{{ running_exp.fault_metrics.get("p99", "—") }}ms</div>
                    <div class="text-[10px]" style="color: var(--muted-foreground);">기준선 {{ running_exp.baseline_metrics.get("p99", "—") }}ms</div>
                  </div>
                  <div class="p-3 rounded-2xl" style="background: var(--muted);">
                    <div class="text-[11px] font-semibold uppercase tracking-wide" style="color: var(--muted-foreground);">현재 R 지수</div>
                    <div class="text-xl font-extrabold mt-1" style="color: var(--primary);">{{ "%.2f"|format(running_exp.r_index) if running_exp.r_index is not none else "—" }}</div>
                    <div class="text-[10px]" style="color: var(--muted-foreground);">목표 {{ "%.2f"|format(running_exp.target_r) }}</div>
                  </div>
                </div>
                {% if r_series %}
                <div class="chart-box">
                  <canvas id="rIndexChart" data-series='{{ r_series|tojson }}' data-labels='{{ r_labels|tojson }}'></canvas>
                </div>
                {% else %}
                <div class="chart-box flex items-center justify-center text-sm" style="color: var(--muted-foreground);">
                  아직 iteration 데이터가 없어요
                </div>
                {% endif %}
              </div>

              <!-- 우: AI 진단 -->
              <div class="xl:border-l xl:pl-6" style="border-color: var(--border);">
                <div class="flex items-center gap-2 mb-3">
                  <span class="tossface">🤖</span>
                  <div class="font-extrabold">AI Agent 진단</div>
                  <span class="tds-badge badge-info">Phase 3 예정 · seed 예시</span>
                </div>
                {% if latest_iter %}
                <div class="space-y-3">
                  <div class="p-3 rounded-2xl border" style="border-color: var(--border);">
                    <div class="flex items-center gap-1.5 mb-1">
                      <iconify-icon icon="solar:eye-bold" width="14" style="color: var(--info);"></iconify-icon>
                      <span class="text-xs font-bold">관찰</span>
                    </div>
                    <p class="text-xs" style="color: var(--muted-foreground);">{{ latest_iter.observer_output }}</p>
                  </div>
                  <div class="p-3 rounded-2xl border" style="border-color: var(--border);">
                    <div class="flex items-center gap-1.5 mb-1">
                      <iconify-icon icon="solar:lightbulb-bold" width="14" style="color: var(--warning);"></iconify-icon>
                      <span class="text-xs font-bold">가설</span>
                    </div>
                    <p class="text-xs" style="color: var(--muted-foreground);">{{ latest_iter.analyst_output }}</p>
                  </div>
                  <div class="p-3 rounded-2xl border-2" style="border-color: var(--primary); background: var(--primary-soft);">
                    <div class="flex items-center gap-1.5 mb-1">
                      <iconify-icon icon="solar:magic-stick-3-bold" width="14" style="color: var(--primary);"></iconify-icon>
                      <span class="text-xs font-bold" style="color: var(--primary-soft-foreground);">권고</span>
                    </div>
                    <p class="text-xs font-semibold" style="color: var(--primary-soft-foreground);">{{ latest_iter.recommender_output }}</p>
                  </div>
                </div>
                {% else %}
                <p class="text-sm" style="color: var(--muted-foreground);">아직 AI 진단 iteration이 없어요.</p>
                {% endif %}
              </div>
            </div>
            {% else %}
            <!-- empty-state: 진행중 실험 없음 -->
            <div class="py-12 text-center">
              <span class="tossface-lg">🧪</span>
              <div class="font-extrabold text-lg mt-2">진행 중인 실험이 없어요</div>
              <p class="text-sm mt-1" style="color: var(--muted-foreground);">카오스 테스트에서 새 실험을 시작하면 여기에 진단이 표시돼요.</p>
            </div>
            {% endif %}
          </div>
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_pages.py -v`
Expected: PASS (합친 카드 + 기존 회귀 없음)

- [ ] **Step 5: 커밋**

```bash
git add app/templates/pages/dashboard.html tests/test_pages.py
git commit -m "✨ 진행중 실험+AI 진단 단일 반응형 카드(실 iteration 구동, empty-state)"
```

---

## Task 5: 시스템 상태 실데이터 + 차트 데이터속성 (템플릿)

**Files:**
- Modify: `app/templates/pages/dashboard.html` (최근 활동 + 시스템 상태 그리드, 파일 하단부)
- Test: `tests/test_pages.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
def test_dashboard_system_status_real(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Supabase" not in resp.text          # 스택에 없는 항목 제거
    assert "sidecars" not in resp.text           # node_count 오표기 제거
    assert "Chaos Mesh" in resp.text             # components() 실항목
    # 최근 활동이 실데이터(seed 앱명)
    assert "online-boutique 신규 등록" in resp.text or "online-boutique 새 SHA" in resp.text
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_pages.py::test_dashboard_system_status_real -v`
Expected: FAIL — "Supabase"/"sidecars" 아직 존재

- [ ] **Step 3: 최근 활동 그리드 교체**

기존 `<!-- 최근 활동 + 시스템 상태 -->` div 전체를 교체:

```html
          <!-- 최근 활동 + 시스템 상태 -->
          <div class="grid grid-cols-1 xl:grid-cols-3 gap-4">

            <div class="xl:col-span-2 tds-card p-6">
              <div class="font-extrabold mb-4">최근 활동</div>
              {% if recent %}
              <div class="space-y-3">
                {% for it in recent %}
                <div class="flex items-start gap-3">
                  <div class="w-8 h-8 rounded-full flex items-center justify-center shrink-0" style="background: var(--muted);">
                    <iconify-icon icon="{{ it.icon }}" width="16" style="color: var(--primary);"></iconify-icon>
                  </div>
                  <div class="flex-1 min-w-0">
                    <div class="text-sm">{{ it.text }}</div>
                  </div>
                  {% if it.badge %}<span class="tds-badge badge-muted">{{ it.badge }}</span>{% endif %}
                </div>
                {% endfor %}
              </div>
              {% else %}
              <p class="text-sm" style="color: var(--muted-foreground);">아직 활동 기록이 없어요.</p>
              {% endif %}
            </div>

            <div class="tds-card p-6">
              <div class="font-extrabold mb-4">시스템 상태</div>
              <div class="space-y-3">
                {% for c in components %}
                <div class="flex items-center justify-between">
                  <span class="text-sm">{{ c.name }}</span>
                  <span class="tds-badge badge-success">{{ c.status }}</span>
                </div>
                {% endfor %}
                <div class="flex items-center justify-between">
                  <span class="text-sm">EKS 노드</span>
                  <span class="tds-badge badge-success">{{ node_count }} nodes</span>
                </div>
              </div>
            </div>
          </div>
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_pages.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add app/templates/pages/dashboard.html tests/test_pages.py
git commit -m "✨ 대시보드 최근활동 DB조립·시스템상태 components() 실데이터(Supabase·sidecars 제거)"
```

---

## Task 6: app.js — rIndexChart 데이터 주입 + 사이드바 active 동기화

**Files:**
- Modify: `app/static/js/app.js:83-90` (rIndexChart 블록), 파일 하단(사이드바 동기화 추가)

> JS 단위 테스트 인프라 없음 → 변경 후 **수동 검증**(서버 기동 후 브라우저). 회귀 안전을 위해 pytest 전체도 돌려 라우트 정상 확인.

- [ ] **Step 1: rIndexChart를 data 속성 기반으로 교체**

`initCharts()` 안의 `const rIdx = ...` 블록을 교체:

```javascript
  const rIdx = document.getElementById('rIndexChart');
  if (rIdx && rIdx.dataset.series) {
    const data = JSON.parse(rIdx.dataset.series);
    const labels = JSON.parse(rIdx.dataset.labels || '[]');
    if (data.length) {
      window._charts.rIndex = new Chart(rIdx, {
        type: 'line',
        data: { labels, datasets: [{ data, borderColor: '#004b3e', backgroundColor: 'rgba(0,75,62,0.15)', fill: true, tension: 0.3, pointRadius: 5, pointBackgroundColor: '#004b3e', borderWidth: 3 }] },
        options: { ...cc, scales: { ...cc.scales, y: { ...cc.scales.y, min: 0.3, max: 0.8 } } }
      });
    }
  }
```

- [ ] **Step 2: 사이드바 active 동기화 추가**

`app.js` 맨 아래에 추가:

```javascript
// ── 사이드바 active 동기화 (HTMX 부분 스왑은 사이드바 DOM을 안 바꿈) ──
function syncSidebarActive() {
  const path = location.pathname;
  document.querySelectorAll('.sidebar-nav-item').forEach((a) => {
    a.classList.toggle('active', a.getAttribute('hx-get') === path);
  });
}
document.addEventListener('DOMContentLoaded', syncSidebarActive);
document.body.addEventListener('htmx:afterSwap', syncSidebarActive);
document.body.addEventListener('htmx:historyRestore', syncSidebarActive);
```

- [ ] **Step 3: 회귀 확인(pytest) + 수동 검증**

Run: `pytest -q`
Expected: 전체 PASS

수동: `uvicorn app.main:app --reload` 후 브라우저에서
- 대시보드 R지수 차트가 seed 시리즈(0.42→0.65)로 렌더되는지
- 사이드바에서 Apps·카오스 테스트 클릭 시 active 하이라이트가 따라 옮겨지는지, 뒤로가기에도 맞는지

- [ ] **Step 4: 커밋**

```bash
git add app/static/js/app.js
git commit -m "🐛 사이드바 active HTMX 이동 동기화 + rIndexChart 실데이터(data속성) 주입"
```

---

## Task 7: 사이드바 "EKS 정상" 박스 제거

**Files:**
- Modify: `app/templates/partials/_sidebar.html:53-62` (시스템 상태 박스)
- Test: `tests/test_pages.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
def test_sidebar_no_eks_status_box(client):
    resp = client.get("/")          # 풀페이지(사이드바 포함)
    assert resp.status_code == 200
    assert "EKS 정상" not in resp.text
    assert "5/5" not in resp.text
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_pages.py::test_sidebar_no_eks_status_box -v`
Expected: FAIL — "EKS 정상" 존재

- [ ] **Step 3: 박스 제거**

`_sidebar.html`에서 `<!-- 시스템 상태 -->` 주석부터 해당 `</div>`까지(현재 53~62행) 삭제. 위(`</nav>`)와 아래(`<!-- 사용자 프로필 -->`)가 바로 인접하게 둔다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_pages.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add app/templates/partials/_sidebar.html tests/test_pages.py
git commit -m "🔥 사이드바 하단 하드코딩 'EKS 정상 5/5' 박스 제거"
```

---

## Slice 4 후속 (코드리뷰에서 식별, 실데이터 연동 시 처리)

실 상태값이 흐를 때 정직성을 위해 RealK8s/RealBuilder 작업과 함께 처리:
- **시스템 상태 배지 색상**: 현재 모든 component를 `badge-success` 고정. Real이 `Degraded`/`Unknown` 반환 시 status→색상 매핑 필요(`components()` 계약에 `badge_class` 추가 또는 템플릿 분기).
- **최근활동 배지 색상**: 현재 `badge-muted` 고정. `failed`/`succeeded`/`running` 등 status→색상 매핑(`_recent_activity`에서 badge_class 부여).
- **components empty-state**: `k8s.components()`가 `[]` 반환(연결 실패) 시 "컴포넌트 정보를 불러올 수 없어요" 표시.
- **합친 카드 메트릭 dash 접미사**(Task 4): metrics 키 부재 시 `—%`/`—ms` → dash 단독 표기로 정정.

## 최종 검증

- [ ] `pytest -q` 전체 통과 (기존 + 신규)
- [ ] `uvicorn app.main:app --reload`(USE_REAL_SERVICES=false)로 대시보드 육안 확인:
  - hero 깔끔(Phase/👋/부제/새실험 버튼 없음), KPI 4개 실값
  - 합친 카드: 지표·차트·AI 진단, "Phase 3 예시" 배지, 자동적용 버튼 없음
  - 최근활동 실데이터, 시스템상태 components()(Supabase 없음)
  - 사이드바 active 이동 정상, EKS 박스 없음
  - 반응형: 창 좁히면 카드 좌우→상하 적층
```
