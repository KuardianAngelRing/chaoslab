"""최종 회귀 실행 생성과 진행 상태 스트림."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.db.database import SessionLocal, get_session
from app.db.repositories import (
    ExperimentSessionRepository,
    HypothesisRepository,
    ScenarioRunRepository,
)
from app.services.regression import (
    run_regression,
    scenario_snapshot,
    scenario_snapshot_from_hypothesis,
)

router = APIRouter()
_TERMINAL = {"completed", "failed"}


def scenario_run_payload(row) -> dict:
    return {
        "id": row.id,
        "status": row.status,
        "hypothesis_run_id": row.hypothesis_run_id,
        "scenario": row.scenario or {},
        "progress": row.progress or {},
        "baseline_results": row.baseline_results or [],
        "results": row.results or [],
        "improvement_changes": row.improvement_changes or [],
        "comparison": row.comparison or {},
        "error": row.error or "",
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }


@router.post("/scenario-runs", status_code=201)
def create_scenario_run(
    background: BackgroundTasks,
    session_id: int = Form(...),
    selected_ids: str = Form(""),
    hypothesis_run_id: int | None = Form(None),
    session: Session = Depends(get_session),
):
    """hypothesis_run_id가 있으면 selected_ids는 무시하고 승인 후보로 시나리오를 조립한다."""
    preparation = ExperimentSessionRepository(session).get(session_id)
    if preparation is None:
        raise HTTPException(status_code=404, detail="준비 세션을 찾을 수 없습니다")
    if preparation.status != "ready":
        raise HTTPException(status_code=409, detail="환경 준비가 완료된 뒤 실행할 수 있습니다")

    repo = ScenarioRunRepository(session)
    if repo.active_for_session(preparation.id) is not None:
        raise HTTPException(status_code=409, detail="최종 회귀가 이미 진행 중입니다")
    hypothesis_run = None
    if hypothesis_run_id is not None:
        hypothesis_run = HypothesisRepository(session).get_run(hypothesis_run_id)
        if hypothesis_run is None:
            raise HTTPException(status_code=404, detail="가설 요청을 찾을 수 없습니다")
        if hypothesis_run.app_id != preparation.app_id:
            raise HTTPException(status_code=422, detail="가설 요청과 준비 세션의 앱이 다릅니다")
    try:
        if hypothesis_run is not None:
            scenario = scenario_snapshot_from_hypothesis(hypothesis_run, preparation.app)
        else:
            scenario = scenario_snapshot(
                preparation.app.name,
                [item for item in selected_ids.split(",") if item],
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    row = repo.create(
        app_id=preparation.app_id,
        preparation_session_id=preparation.id,
        hypothesis_run_id=hypothesis_run.id if hypothesis_run else None,
        status="queued",
        scenario=scenario,
        progress={"current": 0, "total": len(scenario["experiments"]),
                  "round": "baseline", "stage": "queued",
                  "message": "개선 전 검증을 시작합니다"},
        baseline_results=[],
        results=[],
        improvement_changes=[],
        comparison={},
        report_content={},
    )
    background.add_task(run_regression, row.id)
    return scenario_run_payload(row)


@router.get("/scenario-runs/{run_id}")
def get_scenario_run(run_id: int, session: Session = Depends(get_session)):
    row = ScenarioRunRepository(session).get(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="최종 회귀 실행을 찾을 수 없습니다")
    return scenario_run_payload(row)


@router.get("/scenario-runs/{run_id}/stream")
async def scenario_run_stream(run_id: int, request: Request):
    async def gen():
        last = None
        while not await request.is_disconnected():
            session = SessionLocal()
            try:
                row = ScenarioRunRepository(session).get(run_id)
                payload = scenario_run_payload(row) if row else {"status": "missing"}
            finally:
                session.close()
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            if encoded != last:
                yield {"event": "progress", "data": encoded}
                last = encoded
            if payload["status"] in _TERMINAL | {"missing"}:
                yield {"event": "completed", "data": encoded}
                break
            await asyncio.sleep(1)

    return EventSourceResponse(gen())
