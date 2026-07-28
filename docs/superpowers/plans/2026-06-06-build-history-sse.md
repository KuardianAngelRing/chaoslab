# 빌드 이력 UI + watch→SSE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 앱별 빌드 이력 모달(정적)과, 빌드 완료 시 앱 카드 배지를 실시간 전환하는 상태 전용 SSE를 추가한다.

**Architecture:** 신규 `routers/builds.py`가 이력 부분 렌더(`GET /apps/{id}/builds`, HTMX 모달 본문)와 상태 SSE(`GET /apps/{id}/builds/stream`, `SessionLocal`로 `App.status` 폴링)를 제공. 클라이언트(app.js)는 building 카드만 EventSource 구독하고 `completed` 수신 시 `htmx.ajax`로 `/apps`를 새로고침해 배지·sha를 서버 렌더 단일 소스로 갱신. `_watch_build`(Argo 폴링, 기존)와 독립적으로 같은 DB를 읽음.

**Tech Stack:** FastAPI · sse-starlette · SQLAlchemy(SQLite) · Jinja/HTMX · vanilla EventSource

> **테스트 주의(advisor):** SSE 제너레이터는 `SessionLocal`(파일 DB)을 쓰므로, SSE 테스트는 반드시 `monkeypatch.setattr("app.routers.builds.SessionLocal", <테스트 세션>)`로 격리해야 한다(안 하면 `status=None`으로 즉시 completed → false positive). 이력 라우트는 `Depends(get_session)`이라 기존 `client` 픽스처로 hermetic. SSE 테스트는 반드시 종료(break)하는 입력만 사용(무한 스트림은 suite를 행시킴).

---

### Task 1: builds 라우터 — 이력 부분 렌더 + build_duration + 부분 템플릿 + 마운트

**Files:**
- Create: `app/routers/builds.py`
- Create: `app/templates/partials/_build_history.html`
- Modify: `app/main.py:11` (import), `:30` (include_router)
- Test: `tests/test_builds.py` (신규)

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_builds.py`:
```python
"""빌드 이력 라우트 + build_duration — stub 모드(기본)."""
from datetime import datetime, timedelta, timezone

from app.db.models import App, Build
from app.routers.builds import build_duration


def test_build_duration_unfinished():
    assert build_duration(datetime.now(timezone.utc), None) == "—"


def test_build_duration_roundtrip(db_session):
    """DB 라운드트립(SQLite는 naive 반환) 후에도 정상 계산."""
    app = App(name="d", repo_url="https://github.com/x/d", framework="fastapi")
    db_session.add(app)
    db_session.commit()
    start = datetime.now(timezone.utc)
    b = Build(app_id=app.id, started_at=start, finished_at=start + timedelta(seconds=125))
    db_session.add(b)
    db_session.commit()
    db_session.refresh(b)
    assert build_duration(b.started_at, b.finished_at) == "2분 5초"


def test_build_history_lists_builds(client):
    # seed app id=1 (online-boutique)에는 빌드 1건(image_tag a1b2c3d4)
    r = client.get("/apps/1/builds")
    assert r.status_code == 200
    assert "a1b2c3d4" in r.text


def test_build_history_empty_state(client):
    # seed app id=2 (payment-api)는 빌드 없음
    r = client.get("/apps/2/builds")
    assert r.status_code == 200
    assert "빌드 이력이 없어요" in r.text


def test_build_history_unknown_404(client):
    assert client.get("/apps/99999/builds").status_code == 404
```

- [ ] **Step 2: 실패 확인**

Run: `source .venv/bin/activate && pytest tests/test_builds.py -v`
Expected: FAIL — `ModuleNotFoundError: app.routers.builds` (수집 에러)

- [ ] **Step 3: 라우터 구현** — `app/routers/builds.py`:
```python
"""빌드 read/observe — 이력 부분 렌더 + 상태 SSE. 트리거(POST)는 apps.py."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.database import get_session
from app.db.repositories import AppRepository, BuildRepository
from app.rendering import templates

router = APIRouter()


def build_duration(started: datetime, finished: datetime | None) -> str:
    """빌드 소요시간 문자열. 미완료(finished 없음)면 '—'."""
    if not finished:
        return "—"
    secs = int((finished - started).total_seconds())
    m, s = divmod(secs, 60)
    return f"{m}분 {s}초" if m else f"{s}초"


@router.get("/apps/{app_id}/builds")
def build_history(app_id: int, request: Request, session: Session = Depends(get_session)):
    app = AppRepository(session).get(app_id)
    if app is None:
        raise HTTPException(status_code=404, detail="app not found")
    builds = BuildRepository(session).list_for_app(app_id)
    return templates.TemplateResponse(
        request, "partials/_build_history.html",
        {"app": app, "builds": builds, "duration": build_duration},
    )
```

- [ ] **Step 4: 부분 템플릿 작성** — `app/templates/partials/_build_history.html`:
```html
{% from "macros/components.html" import badge %}
<div class="px-6 pb-6 pt-2">
  <div class="text-sm font-bold mb-3" style="color: var(--muted-foreground);">{{ app.name }}</div>
  {% if builds %}
  <div class="space-y-2">
    {% for b in builds %}
    <div class="tds-card p-3 flex items-center justify-between text-xs">
      <div class="flex items-center gap-3">
        {% if b.status == "succeeded" %}{{ badge("성공", "success") }}
        {% elif b.status == "failed" %}{{ badge("실패", "danger") }}
        {% elif b.status == "running" %}{{ badge("빌드 중", "info") }}
        {% else %}{{ badge(b.status, "muted") }}{% endif %}
        <code class="mono font-bold">{{ b.image_tag or "—" }}</code>
      </div>
      <div class="flex items-center gap-4" style="color: var(--muted-foreground);">
        <span>{{ b.started_at.strftime("%m/%d %H:%M") }}</span>
        <span>{{ duration(b.started_at, b.finished_at) }}</span>
        <code class="mono truncate max-w-[160px]">{{ b.workflow_name or "—" }}</code>
      </div>
    </div>
    {% endfor %}
  </div>
  {% else %}
  <div class="text-center py-10" style="color: var(--muted-foreground);">
    <div class="text-3xl mb-2">📜</div>
    <div class="text-sm">빌드 이력이 없어요. 빌드를 실행하면 여기 기록돼요.</div>
  </div>
  {% endif %}
</div>
```

- [ ] **Step 5: main.py 마운트** — `app/main.py`에서 import 줄을 교체:
```python
from app.routers import apps, builds, pages, stream
```
그리고 `app.include_router(stream.router)` 아래에 추가:
```python
app.include_router(builds.router)
```

- [ ] **Step 6: 통과 확인**

Run: `pytest tests/test_builds.py -v`
Expected: PASS (5개). 이어 `pytest -q` → 전체 PASS.

- [ ] **Step 7: 커밋**

```bash
git add app/routers/builds.py app/templates/partials/_build_history.html app/main.py tests/test_builds.py
git commit -m "✨ 빌드 이력 부분 렌더(/apps/{id}/builds) + build_duration"
```

---

### Task 2: 상태 SSE 스트림 (/apps/{id}/builds/stream)

**Files:**
- Modify: `app/routers/builds.py` (import 추가 + stream 라우트)
- Test: `tests/test_builds.py`

- [ ] **Step 1: 실패 테스트 추가** — `tests/test_builds.py` 하단에 추가:
```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base


def _engine_with_status(status):
    """단일 App(id=1, 주어진 status)을 가진 격리 엔진+세션메이커."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = Session()
    s.add(App(name="demo", repo_url="https://github.com/x/demo",
              framework="fastapi", status=status))
    s.commit()
    s.close()
    return Session


class _FlipSession:
    """폴링마다 다음 status를 돌려주는 가짜 세션 (시간 전이 모사)."""
    def __init__(self, statuses):
        self._statuses = list(statuses)

    def get(self, model, pk):
        st = self._statuses.pop(0) if self._statuses else "healthy"
        return App(name="demo", repo_url="https://github.com/x/demo",
                   framework="fastapi", status=st)

    def close(self):
        pass


def test_build_stream_immediate_completed_when_not_building(monkeypatch, client):
    Session = _engine_with_status("healthy")
    monkeypatch.setattr("app.routers.builds.SessionLocal", Session)
    with client.stream("GET", "/apps/1/builds/stream") as r:
        body = "".join(r.iter_text())
    assert "event: completed" in body
    assert '"status": "healthy"' in body


def test_build_stream_completed_after_transition(monkeypatch, client):
    # building → building → healthy: 전이 후 completed 발송
    monkeypatch.setattr("app.routers.builds.SessionLocal",
                        lambda: _FlipSession(["building", "building", "healthy"]))

    async def _no_sleep(*a, **k):
        return None

    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    with client.stream("GET", "/apps/1/builds/stream") as r:
        body = "".join(r.iter_text())
    assert "event: status" in body          # building 동안 status 이벤트
    assert "event: completed" in body        # healthy 전이 시 completed
    assert '"status": "healthy"' in body
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_builds.py -v -k stream`
Expected: FAIL — 404 (stream 라우트 없음) → `event: completed` 미포함

- [ ] **Step 3: stream 라우트 구현** — `app/routers/builds.py` import 블록에 추가:
```python
import asyncio
import json

from sse_starlette.sse import EventSourceResponse

from app.db.database import SessionLocal
from app.db.models import App
```
(`from app.db.database import get_session` 줄은 `from app.db.database import SessionLocal, get_session`로 합쳐도 됨.)

`build_history` 아래에 추가:
```python
@router.get("/apps/{app_id}/builds/stream")
async def build_stream(app_id: int, request: Request):
    """App.status를 폴링해 빌드 완료(=building 벗어남) 시 completed 발송·종료.

    EventSource는 스트림 종료 시 자동 재연결 → 상한을 _watch_build(~10분)보다
    높게 둠. _watch_build가 terminal로 만들면 다음 폴링에서 completed로 끝남.
    """
    async def gen():
        last = None
        for _ in range(360):  # ~12분 (2s 간격)
            if await request.is_disconnected():
                break
            s = SessionLocal()
            try:
                app = s.get(App, app_id)
                status = app.status if app else None
            finally:
                s.close()
            if status != last:
                yield {"event": "status", "data": json.dumps({"status": status})}
                last = status
            if status != "building":
                yield {"event": "completed", "data": json.dumps({"status": status})}
                break
            await asyncio.sleep(2)

    return EventSourceResponse(gen())
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_builds.py -v`
Expected: PASS (7개). 이어 `pytest -q` → 전체 PASS.

- [ ] **Step 5: 커밋**

```bash
git add app/routers/builds.py tests/test_builds.py
git commit -m "✨ 빌드 상태 SSE(/apps/{id}/builds/stream) — building 폴링→completed"
```

---

### Task 3: UI — 이력 버튼 + 모달 + 카드 배지 live watch

**Files:**
- Modify: `app/templates/pages/apps.html` (이력 버튼·공유 모달·building 배지 data 속성)
- Modify: `app/static/js/app.js` (watchBuilds)

- [ ] **Step 1: 카드 building 배지에 data 속성 추가** — `app/templates/pages/apps.html`에서 building 배지 줄을 교체. 현재:
```html
        {% elif app.status == "building" %}
        <span class="tds-badge badge-info"><span class="w-1.5 h-1.5 rounded-full pulse-dot" style="background: var(--info);"></span>빌드 중</span>
```
교체:
```html
        {% elif app.status == "building" %}
        <span class="tds-badge badge-info" data-building-app="{{ app.id }}"><span class="w-1.5 h-1.5 rounded-full pulse-dot" style="background: var(--info);"></span>빌드 중</span>
```

- [ ] **Step 2: 카드 버튼 행에 "이력" 버튼 추가** — 같은 파일에서 "카오스 실험" 버튼 블록 바로 아래(github 링크 위)에 삽입:
```html
        <button class="tds-btn-muted text-xs h-9 px-3" hx-get="/apps/{{ app.id }}/builds" hx-target="#builds-body" hx-swap="innerHTML" onclick="openDialog('builds')" title="빌드 이력">
          <iconify-icon icon="solar:history-bold" width="14"></iconify-icon>
        </button>
```

- [ ] **Step 3: 공유 빌드 이력 모달 추가** — 같은 파일에서 등록 다이얼로그(`<div class="dialog-backdrop" id="dialog-newApp">`) **앞**(또는 `{% endblock %}` 바로 위)에 추가:
```html
<!-- DIALOG: 빌드 이력 (공유, HTMX가 본문 채움) -->
<div class="dialog-backdrop" id="dialog-builds">
  <div class="dialog-card">
    <div class="px-6 pt-6 pb-2 flex items-center justify-between">
      <div class="flex items-center gap-2">
        <span class="tossface">📜</span>
        <h2 class="font-extrabold text-xl">빌드 이력</h2>
      </div>
      <button class="p-1 rounded-lg hover:bg-muted" onclick="closeDialog('builds')">
        <iconify-icon icon="lucide:x" width="20"></iconify-icon>
      </button>
    </div>
    <div id="builds-body" class="flex-1 overflow-auto"></div>
  </div>
</div>
```

- [ ] **Step 4: app.js에 watchBuilds 추가** — `app/static/js/app.js` 끝에 추가:
```javascript

// ── 빌드 상태 watch (building 카드만 EventSource, 완료 시 목록 새로고침) ──
const _buildStreams = new Set();
function watchBuilds() {
  document.querySelectorAll('[data-building-app]').forEach((el) => {
    const id = el.dataset.buildingApp;
    if (_buildStreams.has(id)) return;
    _buildStreams.add(id);
    const es = new EventSource(`/apps/${id}/builds/stream`);
    es.addEventListener('completed', () => {
      es.close(); _buildStreams.delete(id);
      // 배지 마크업을 JS에 복제하지 않고 서버 렌더로 목록 새로고침(배지·sha 일관)
      if (window.htmx) htmx.ajax('GET', '/apps', { target: '#main-content', swap: 'innerHTML' });
    });
    es.onerror = () => { es.close(); _buildStreams.delete(id); };
  });
}
document.addEventListener('DOMContentLoaded', watchBuilds);
document.body.addEventListener('htmx:afterSwap', watchBuilds);
```

- [ ] **Step 5: 회귀 + 렌더 스모크**

Run: `source .venv/bin/activate && pytest -q` → 전체 PASS.
이어 마크업 스모크:
```bash
python -c "
import app.config as c; c.settings.use_real_services=False
from fastapi.testclient import TestClient; from app.main import app
cl=TestClient(app); html=cl.get('/apps').text
for t in ['/apps/1/builds','id=\"dialog-builds\"','id=\"builds-body\"','data-building-app']:
    print(('OK ' if t in html else 'MISS '), t)
js=cl.get('/static/js/app.js').text
print(('OK ' if 'function watchBuilds' in js else 'MISS '), 'watchBuilds')
"
```
Expected: 모두 OK. (참고: seed 앱은 building 상태가 없어 `data-building-app`은 HTML에 없을 수 있음 — 그 경우 MISS 정상. 핵심은 `/apps/1/builds`·`dialog-builds`·`builds-body`·`watchBuilds` OK.)

- [ ] **Step 6: (선택) 수동 브라우저 확인** — `uvicorn app.main:app` 후 `/apps`에서 "이력" 버튼 클릭 → 모달에 boutique 빌드 1건 표시 확인. (live 배지 전환은 building 앱이 있어야 하므로 up.sh 라이브에서 검증.)

- [ ] **Step 7: 커밋**

```bash
git add app/templates/pages/apps.html app/static/js/app.js
git commit -m "✨ 앱 카드 이력 버튼·모달 + building 배지 SSE live watch"
```

---

### Task 4: 전체 검증 + CLAUDE.md 갱신

**Files:**
- Modify: `CLAUDE.md` (gitignore — 로컬, 커밋 안 함)

- [ ] **Step 1: 전체 테스트**

Run: `cd /Users/taeyunemacbook/Documents/chaoslab && source .venv/bin/activate && pytest -q`
Expected: 전체 PASS (기존 38 + 신규 7 = 45).

- [ ] **Step 2: CLAUDE.md 갱신** — Slice 2 후속의 `빌드 이력 UI`·`빌드 watch → SSE` 두 항목을 `[x]`로 바꾸고 한 줄 메모(구현 완료; live 배지 전환은 up.sh 검증) 추가. (gitignore라 커밋하지 않음.)

- [ ] **Step 3: 정직성 메모** — 최종 요약 시 명시: SSE의 즉시-completed·전이 로직은 단위테스트로 검증됨. 단 **실제 브라우저 배지 live 전환(EventSource→htmx 새로고침)은 up.sh 라이브에서 검증** 예정(단위테스트 범위 밖). 모달이 열린 채 빌드 완료되면 새로고침으로 모달이 닫히는 엣지는 알려진 한계.

---

## 알려진 한계 / 라이브 검증 항목 (up.sh)

- **모달 닫힘 엣지:** 빌드 완료 시 `htmx.ajax GET /apps`가 `#main-content`를 스왑 → 그 안의 `#dialog-builds`도 교체되어, 빌드 완료 순간 이력 모달이 열려 있으면 닫힘. 드문 케이스, 현재 용인.
- **EventSource 재연결:** 스트림 360폴(~12분) 상한 도달 시 서버가 닫고 브라우저가 자동 재연결 → `_watch_build`가 terminal 보장하므로 결국 completed로 종료. 기능상 무해.
- **브라우저 live 배지 전환** 자체는 단위테스트 범위 밖 → 라이브에서 눈으로 확인.
