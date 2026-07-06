"""실험 생성/중지/watch/SSE — 빌드 파이프라인 패턴 미러."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.config import settings
from app.db.database import SessionLocal, get_session
from app.db.models import Experiment
from app.db.repositories import AppRepository, ExperimentRepository
from app.deps import get_app_count, make_chaos
from app.rendering import render_page
from app.services.chaos_specs import validate_params

router = APIRouter()
logger = logging.getLogger(__name__)

_POLL_S = 5           # watcher 폴링 간격
_RECOVER_CAP = 60     # duration 후 회복 대기 상한 (5s × 60 = 5분)
_PODKILL_GRACE_S = 30  # pod-kill 원샷 유예


def _experiments_response(request: Request, session: Session):
    exps = ExperimentRepository(session).list_all()
    apps = AppRepository(session).list_all()
    return render_page(
        request, "pages/experiments.html",
        {"active_nav": "experiments", "app_count": len(apps),
         "experiments": exps, "apps": apps},
    )


@router.post("/experiments")
def create_experiment(
    request: Request,
    background: BackgroundTasks,
    app_id: int = Form(...),
    chaos_type: str = Form(...),
    latency_ms: str = Form(""),
    duration_s: str = Form(""),
    cpu_load: str = Form(""),
    session: Session = Depends(get_session),
):
    app = AppRepository(session).get(app_id)
    if app is None:
        raise HTTPException(status_code=404, detail="app not found")

    params, errors = validate_params(chaos_type, {
        "latency_ms": latency_ms, "duration_s": duration_s, "cpu_load": cpu_load,
    })
    if errors:
        raise HTTPException(status_code=422, detail=" / ".join(errors))

    busy = [e for e in app.experiments if e.status in ("pending", "running")]
    if busy:
        raise HTTPException(status_code=409, detail="이 앱에 진행 중인 실험이 있어요")

    exp = ExperimentRepository(session).create(
        app_id=app.id, chaos_type=chaos_type, params=params, status="pending")
    try:
        crd = make_chaos().inject(settings.sut_namespace, app.name, chaos_type, params)
        exp.crd_name = crd
        exp.status = "running"
        session.commit()
    except Exception:
        logger.exception("chaos inject failed (app %s, type %s)", app.name, chaos_type)
        exp.status = "inject-failed"
        session.commit()
        return _experiments_response(request, session)

    background.add_task(_watch_experiment, exp.id)
    return _experiments_response(request, session)


def _watch_experiment(exp_id: int) -> None:
    """duration 경과·회복 확인 → CRD 삭제 + completed. 오류/상한 → failed."""
    chaos = make_chaos()
    s = SessionLocal()
    try:
        exp = s.get(Experiment, exp_id)
        if exp is None:
            return
        chaos_type, crd_name = exp.chaos_type, exp.crd_name
        duration = int(exp.params.get("duration_s") or _PODKILL_GRACE_S)

        status = "completed"
        try:
            waited = 0
            while waited < duration:          # 장애 지속 구간
                time.sleep(_POLL_S)
                waited += _POLL_S
            for _ in range(_RECOVER_CAP):     # 회복 대기 (최대 5분)
                if chaos.phase(chaos_type, crd_name) == "recovered":
                    break
                time.sleep(_POLL_S)
            chaos.delete(chaos_type, crd_name)
        except Exception:
            logger.exception("experiment watch failed (exp %s)", exp_id)
            try:
                chaos.delete(chaos_type, crd_name)
            except Exception:
                logger.exception("chaos cleanup failed (exp %s)", exp_id)
            status = "failed"

        exp = s.get(Experiment, exp_id)
        if exp and exp.status == "running":   # stop이 먼저 처리했으면 덮어쓰지 않음
            exp.status = status
            exp.finished_at = datetime.now(timezone.utc)
            s.commit()
    finally:
        s.close()


@router.post("/experiments/{exp_id}/stop")
def stop_experiment(
    exp_id: int,
    request: Request,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
):
    exp = ExperimentRepository(session).get(exp_id)
    if exp is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    if exp.status != "running":
        raise HTTPException(status_code=409, detail="진행 중인 실험이 아니에요")

    exp.status = "stopped"
    exp.finished_at = datetime.now(timezone.utc)
    session.commit()
    background.add_task(_delete_crd_task, exp.chaos_type, exp.crd_name)
    return _experiments_response(request, session)


def _delete_crd_task(chaos_type: str, crd_name: str) -> None:
    try:
        make_chaos().delete(chaos_type, crd_name)
    except Exception:
        logger.exception("chaos delete failed (%s/%s)", chaos_type, crd_name)


@router.get("/experiments/{exp_id}/stream")
async def experiment_stream(exp_id: int, request: Request):
    """Experiment.status DB 폴링 — running을 벗어나면 completed 이벤트 후 종료 (builds/stream 미러)."""
    async def gen():
        last = None
        for _ in range(1260):  # ~42분 (2s 간격) > watcher 상한
            if await request.is_disconnected():
                break
            s = SessionLocal()
            try:
                exp = s.get(Experiment, exp_id)
                status = exp.status if exp else None
            finally:
                s.close()
            if status != last:
                yield {"event": "status", "data": json.dumps({"status": status})}
                last = status
            if status != "running":
                yield {"event": "completed", "data": json.dumps({"status": status})}
                break
            await asyncio.sleep(2)

    return EventSourceResponse(gen())
