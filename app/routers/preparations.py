"""순차 실행 전에 k3s 앱을 전용 namespace에 준비한다."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.db.database import SessionLocal, get_session
from app.db.models import ExperimentSession
from app.db.repositories import AppRepository, ExperimentSessionRepository, ScenarioRunRepository
from app.deps import make_k3s_workload

router = APIRouter()
logger = logging.getLogger(__name__)

_READY_TIMEOUT_S = 180
_POLL_S = 2
_TERMINAL = {"ready", "failed", "cancelled"}


def _namespace(app_name: str, session_id: int) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", app_name.lower()).strip("-") or "app"
    return f"chaoslab-session-{slug}-{session_id}"[:63].rstrip("-")


def _payload(row: ExperimentSession) -> dict:
    return {"id": row.id, "status": row.status, "namespace": row.namespace,
            "progress": row.progress or {}, "error": row.error or ""}


def _update(row: ExperimentSession, *, stage: str, message: str,
            snapshot: dict | None = None, status: str = "preparing", error: str = "") -> None:
    row.status = status
    row.error = error
    row.progress = {"stage": stage, "message": message, **(snapshot or {})}
    row.updated_at = datetime.now(timezone.utc)
    if status in _TERMINAL:
        row.finished_at = row.updated_at


@router.post("/experiment-sessions")
def create_preparation(
    background: BackgroundTasks,
    app_id: int = Form(...),
    objective: str = Form(""),
    session: Session = Depends(get_session),
):
    app = AppRepository(session).get(app_id)
    if app is None:
        raise HTTPException(status_code=404, detail="app not found")
    if app.env != "k3s":
        raise HTTPException(status_code=422, detail="로컬 환경 준비는 k3s 앱에만 필요합니다")
    if not (app.manifest or "").strip():
        raise HTTPException(status_code=422, detail="앱 manifest가 없어 환경을 준비할 수 없습니다")

    repo = ExperimentSessionRepository(session)
    if repo.preparing_for_app(app.id) is not None:
        raise HTTPException(status_code=409, detail="이 앱의 환경 준비가 진행 중입니다")

    # 새 실험 시작은 이전의 완료 환경을 대체한다. 과거 Ready 환경이 다음 실험을 막거나
    # namespace를 남기지 않도록 상태를 종료한 뒤 비동기로 정리한다.
    previous_ready = repo.ready_for_app(app.id)
    if any(ScenarioRunRepository(session).active_for_session(row.id) for row in previous_ready):
        raise HTTPException(status_code=409, detail="최종 회귀가 진행 중인 환경은 종료할 수 없습니다")
    for previous in previous_ready:
        _update(previous, stage="cancelled", message="새 실험을 시작해 이전 환경을 종료했습니다",
                status="cancelled")
    if previous_ready:
        session.commit()
        for previous in previous_ready:
            background.add_task(_teardown_session, previous.id)

    row = repo.create(app_id=app.id, objective=objective.strip(), status="queued",
                      progress={"stage": "starting", "message": "실험 환경 준비를 시작합니다"})
    row.namespace = _namespace(app.name, row.id)
    row.updated_at = datetime.now(timezone.utc)
    session.commit()
    return _payload(row)


@router.post("/experiment-sessions/{session_id}/start")
def start_preparation(
    session_id: int,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
):
    row = ExperimentSessionRepository(session).get(session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="experiment session not found")
    if row.status != "queued":
        raise HTTPException(status_code=409, detail="시작할 수 없는 환경 상태입니다")
    _update(row, stage="starting", message="실험 환경 준비를 시작합니다")
    session.commit()
    background.add_task(_prepare_environment, row.id)
    return _payload(row)


def _prepare_environment(session_id: int) -> None:
    s = SessionLocal()
    workload = None
    namespace = ""
    try:
        row = s.get(ExperimentSession, session_id)
        if row is None or row.status != "preparing":
            return
        namespace = row.namespace
        workload = make_k3s_workload()
        _update(row, stage="applying", message="전용 namespace 생성 및 manifest 적용 중")
        s.commit()
        workload.deploy(namespace, row.app.manifest or "")

        deadline = time.monotonic() + _READY_TIMEOUT_S
        while time.monotonic() < deadline:
            s.expire_all()
            row = s.get(ExperimentSession, session_id)
            if row is None or row.status != "preparing":
                return
            snapshot = workload.readiness(namespace)
            ready = snapshot["deployments_total"] and (
                snapshot["deployments_ready"] == snapshot["deployments_total"]
            )
            if ready:
                _update(row, stage="ready", message="워크로드 준비가 완료됐습니다",
                        snapshot=snapshot, status="ready")
                s.commit()
                return
            _update(row, stage="waiting_ready", message="워크로드 Ready 상태를 확인 중", snapshot=snapshot)
            s.commit()
            time.sleep(_POLL_S)
        raise RuntimeError(f"워크로드 준비 시간이 초과됐습니다 ({_READY_TIMEOUT_S}초)")
    except Exception as exc:
        logger.exception("environment preparation failed (session %s)", session_id)
        row = s.get(ExperimentSession, session_id)
        if row is not None and row.status != "cancelled":
            _update(row, stage="failed", message="환경 준비에 실패했습니다", status="failed", error=str(exc))
            s.commit()
    finally:
        row = s.get(ExperimentSession, session_id)
        if row is not None and row.status in {"failed", "cancelled"} and namespace:
            try:
                (workload or make_k3s_workload()).teardown(namespace)
            except Exception:
                logger.exception("environment teardown failed (%s)", namespace)
        s.close()


def _teardown_session(session_id: int) -> None:
    s = SessionLocal()
    try:
        row = s.get(ExperimentSession, session_id)
        if row and row.namespace:
            make_k3s_workload().teardown(row.namespace)
    except Exception:
        logger.exception("environment teardown failed (session %s)", session_id)
    finally:
        s.close()


@router.get("/experiment-sessions/{session_id}/stream")
async def preparation_stream(session_id: int, request: Request):
    async def gen():
        last = None
        for _ in range(180):
            if await request.is_disconnected():
                break
            s = SessionLocal()
            try:
                row = s.get(ExperimentSession, session_id)
                payload = _payload(row) if row else {"status": "missing"}
            finally:
                s.close()
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            if encoded != last:
                yield {"event": "progress", "data": encoded}
                last = encoded
            if payload["status"] in _TERMINAL | {"missing"}:
                yield {"event": "completed", "data": encoded}
                break
            await asyncio.sleep(_POLL_S)

    return EventSourceResponse(gen())
