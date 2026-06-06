"""빌드 read/observe — 이력 부분 렌더 + 상태 SSE. 트리거(POST)는 apps.py."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.db.database import SessionLocal, get_session
from app.db.models import App
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
