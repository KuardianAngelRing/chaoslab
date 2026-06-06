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
