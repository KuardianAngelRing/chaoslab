"""AI Agent 전달 데이터(핸드오프) REST API — 이 레포 유일의 순수 JSON 라우터.

스냅샷 저장형: POST가 조립·저장, AI 루프는 GET …/latest 소비.
계약·예시는 /docs (Swagger) 에서 확인 — 별도 대시보드 UI 없음.
"""
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.db.database import get_session
from app.db.models import AgentHandoff
from app.db.repositories import ExperimentRepository, HandoffRepository
from app.deps import get_handoff_source
from app.services.agent.assembler import assemble_handoff
from app.services.agent.handoff_schema import AgentHandoffPayload
from app.services.interfaces import HandoffSourceService

router = APIRouter(tags=["handoffs"])


def _meta(h: AgentHandoff) -> dict:
    return {
        "id": h.id,
        "experiment_id": h.experiment_id,
        "schema_version": h.schema_version,
        "created_at": h.created_at.isoformat(),
        "updated_at": h.updated_at.isoformat(),
    }


def _full(h: AgentHandoff) -> dict:
    return {**_meta(h), "payload": h.payload}


def _require_experiment(session: Session, exp_id: int):
    exp = ExperimentRepository(session).get(exp_id)
    if exp is None:
        raise HTTPException(status_code=404, detail="실험을 찾을 수 없어요")
    return exp


@router.post("/experiments/{exp_id}/handoffs", status_code=201)
def create_handoff(
    exp_id: int,
    session: Session = Depends(get_session),
    source: HandoffSourceService = Depends(get_handoff_source),
) -> dict:
    """현재 실험 데이터로 전달 페이로드를 조립해 스냅샷으로 저장."""
    exp = _require_experiment(session, exp_id)
    payload = assemble_handoff(session, source, exp)
    handoff = HandoffRepository(session).create(
        experiment_id=exp.id,
        schema_version=payload.schema_version,
        payload=payload.model_dump(),
    )
    return _full(handoff)


@router.get("/experiments/{exp_id}/handoffs")
def list_handoffs(exp_id: int, session: Session = Depends(get_session)) -> list[dict]:
    """스냅샷 메타 목록 (최신순, payload 제외)."""
    _require_experiment(session, exp_id)
    return [_meta(h) for h in HandoffRepository(session).list_for_experiment(exp_id)]


@router.get("/experiments/{exp_id}/handoffs/latest")
def latest_handoff(exp_id: int, session: Session = Depends(get_session)) -> dict:
    """최신 스냅샷 전체 — AI 루프 소비 지점."""
    _require_experiment(session, exp_id)
    handoff = HandoffRepository(session).latest_for_experiment(exp_id)
    if handoff is None:
        raise HTTPException(status_code=404, detail="전달 데이터 스냅샷이 없어요")
    return _full(handoff)


@router.get("/handoffs/{handoff_id}")
def get_handoff(handoff_id: int, session: Session = Depends(get_session)) -> dict:
    handoff = HandoffRepository(session).get(handoff_id)
    if handoff is None:
        raise HTTPException(status_code=404, detail="스냅샷을 찾을 수 없어요")
    return _full(handoff)


@router.put("/handoffs/{handoff_id}")
def update_handoff(
    handoff_id: int,
    payload: AgentHandoffPayload,  # body 계약 검증 — 위반 시 FastAPI가 422
    session: Session = Depends(get_session),
) -> dict:
    repo = HandoffRepository(session)
    handoff = repo.get(handoff_id)
    if handoff is None:
        raise HTTPException(status_code=404, detail="스냅샷을 찾을 수 없어요")
    repo.update_payload(handoff, payload.model_dump(), payload.schema_version)
    return _full(handoff)


@router.delete("/handoffs/{handoff_id}", status_code=204)
def delete_handoff(handoff_id: int, session: Session = Depends(get_session)) -> Response:
    repo = HandoffRepository(session)
    handoff = repo.get(handoff_id)
    if handoff is None:
        raise HTTPException(status_code=404, detail="스냅샷을 찾을 수 없어요")
    repo.delete(handoff)
    return Response(status_code=204)
