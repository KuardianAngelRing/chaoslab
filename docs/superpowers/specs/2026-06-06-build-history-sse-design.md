# 설계 — 빌드 이력 UI + 빌드 watch→SSE (Slice 2 후속)

작성일: 2026-06-06 · 상태: 승인됨(구두) → 계획 진행

## 1. 목적

- **빌드 이력 UI**: `builds` 테이블에 기록은 쌓이나 전용 화면이 없음 → 앱별 빌드 타임라인 제공.
- **빌드 watch→SSE**: 현재 `_watch_build`는 Argo 폴링으로 DB만 갱신, UI는 수동 새로고침 필요 → 빌드 완료 시 **앱 카드 배지가 실시간 자동 전환**(빌드 중→배포됨/실패).

cloud-hub의 `BuildHistoryDialog`(테이블+더보기)·`BuildLogDialog`(EventSource) 패턴을 참고하되 chaoslab 규모로 축소.

## 2. 범위 / 비범위

**범위**: (1) 앱 카드별 빌드 이력 모달(정적 스냅샷, HTMX 부분 렌더), (2) 상태 전용 SSE로 building 카드 배지 실시간 전환.

**비범위**: Argo 파드 로그 스트리밍(cloud-hub BuildLogDialog 수준), 빌드 중단 버튼, 페이지네이션('더 보기'), 이력 모달 내부의 실시간 갱신(모달은 스냅샷). 로그 색상 렌더.

## 3. 핵심 설계 결정

1. **SSE = 서버측 DB 폴링.** SSE 제너레이터가 `SessionLocal`로 `App.status`를 2s 폴링. chaoslab의 "SQLite + worker 없음" 모델에 부합. `_watch_build`(Argo 폴링)와 **독립** — 공유 상태 없이 같은 DB를 읽을 뿐.
2. **completed 시 전체 목록 새로고침.** 배지 마크업을 JS에 복제하지 않고 `htmx.ajax('GET','/apps')`로 서버 렌더 단일 소스 유지 → 배지+마지막 sha 일관(flicker는 빌드 보통 1건이라 무시).
3. **building 카드만 구독.** healthy 카드는 EventSource 미개설 → 연결 최소화.
4. **즉시 종료 보장.** 스트림 열 때 status가 이미 "building"이 아니면 즉시 `completed`·close → 무한 대기 방지 + 테스트 가능.
5. **이력 모달 = 정적 스냅샷.** 실시간은 카드 배지에만(사용자 선택). 모달은 열 때 시점 데이터.
6. **vanilla EventSource.** htmx-sse 확장 미도입, 이벤트 위임 + onclick 전역(env 에디터와 동일 기조, HTMX 스왑 안전).

## 4. 데이터 흐름

```
[이력]  앱 카드 "이력" 버튼 → hx-get /apps/{id}/builds → 공유 모달 #dialog-builds 본문 채움
        GET /apps/{id}/builds → partials/_build_history.html (BuildRepository.list_for_app)
        테이블: 상태배지 · sha8(image_tag) · 시작시각 · 소요시간 · workflow명 · 빈 상태

[배지]  빌드 클릭 → build_app: Build(running)+app.status="building" → 카드 "빌드 중"(서버 렌더, data-building-app)
        app.js watchBuilds(): building 카드만 EventSource → GET /apps/{id}/builds/stream
        SSE: app.status 폴링; "building" 유지 중엔 status 이벤트, 벗어나면 completed·close
        클라이언트 completed → htmx.ajax GET /apps → 목록 새로고침(배지·sha 일관)
```

## 5. 변경 파일

| 파일 | 변경 |
|---|---|
| `app/routers/builds.py` (신규) | `GET /apps/{id}/builds`(이력 부분 렌더), `GET /apps/{id}/builds/stream`(SSE 상태), `build_duration()` 순수 헬퍼 |
| `app/main.py` | `from app.routers import ... builds` + `app.include_router(builds.router)` |
| `app/templates/partials/_build_history.html` (신규) | 빌드 테이블 부분 템플릿(base 미상속) + 빈 상태 |
| `app/templates/pages/apps.html` | 카드에 "이력" 버튼(hx-get+openDialog) · 공유 모달 `#dialog-builds` · building 배지에 `data-building-app="{{ app.id }}"` |
| `app/static/js/app.js` | `watchBuilds()` — building 카드 EventSource 구독, completed 시 `htmx.ajax` 새로고침, Set 중복가드, `htmx:afterSwap`/`DOMContentLoaded` 바인딩 |
| `tests/test_builds.py` (신규) | 이력 라우트(200·행/빈상태·404), `build_duration` 순수함수, SSE 비-building 앱 즉시 completed |

## 6. 인터페이스 스케치

```python
# routers/builds.py
def build_duration(started, finished) -> str:
    """소요시간 문자열. finished 없으면 '—'."""
    if not finished:
        return "—"
    secs = int((finished - started).total_seconds())
    m, s = divmod(secs, 60)
    return f"{m}분 {s}초" if m else f"{s}초"

@router.get("/apps/{app_id}/builds")          # 이력 부분 렌더 (HTMX 모달 본문)
@router.get("/apps/{app_id}/builds/stream")    # SSE: status 폴링 → completed
```

SSE 제너레이터 골자:
```python
async def gen():
    last = None
    for _ in range(150):  # ~5분 상한
        if await request.is_disconnected(): break
        s = SessionLocal(); app = s.get(App, app_id); status = app.status if app else None; s.close()
        if status != last:
            yield {"event": "status", "data": json.dumps({"status": status})}; last = status
        if status != "building":
            yield {"event": "completed", "data": json.dumps({"status": status})}; break
        await asyncio.sleep(2)
```

## 7. UI

- 앱 카드 버튼 행에 "이력" 버튼 추가(기존 빌드/카오스 버튼 옆). `hx-get="/apps/{{ app.id }}/builds"` `hx-target="#builds-body"` + `onclick="openDialog('builds')"`.
- 공유 모달 `#dialog-builds`(기존 dialog 패턴) 안에 `#builds-body`(HTMX 타깃).
- building 상태 배지에 `data-building-app="{{ app.id }}"` 부착.

## 8. 테스트

- `GET /apps/{id}/builds` → 200, seed 빌드 행(boutique) 노출; 빌드 없는 앱 → 빈 상태 문구; 없는 앱 → 404.
- `build_duration` 순수함수: finished 있음/없음, 분·초 경계.
- SSE: 비-building 앱(seed healthy)에 `GET /apps/{id}/builds/stream` → 즉시 `completed` 포함·종료(TestClient가 본문 끝까지 읽힘). hermetic(stub 강제).

## 9. minimal 메모

chaoslab은 cloud-hub보다 훨씬 단순. 로그 스트리밍/중단/페이지네이션/모달 실시간은 비범위.
신규 표면 = 라우터 1파일(2라우트+헬퍼) + 부분템플릿 1 + app.js 함수 1 + 카드 버튼/모달.
