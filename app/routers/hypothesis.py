"""가설 수립 — Run 생성/후보 페이지/SSE/직접 입력/선택(detailing) (스펙 2026-08-25 2차 개정 §4).

builds·experiments의 워처+SSE 패턴 재사용. 2단 프로세스: generate(서사 후보)
→ 선택 → detail(params 구체화) → 기존 실험 생성 경로(start_experiment).
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.db.database import SessionLocal, get_session
from app.db.models import HypothesisRun
from app.db.repositories import AppRepository, HypothesisRepository, ScenarioRunRepository
from app.deps import make_hypothesis_agent
from app.rendering import render_page
from app.routers.experiments import _watch_experiment, start_experiment
from app.services.agent.hypothesis_assembler import assemble_hypothesis_input
from app.services.agent.hypothesis_schema import CandidateProposal, HypothesisInputPayload
from app.services.agent.hypothesis_validation import (
    run_concretize,
    run_detailing,
    run_generation,
    run_proposing,
)
from app.services.agent.improvement_assembler import assemble_improvement_input
from app.services.chaos_specs import CHAOS_SPECS
from app.services.improvement_specs import preview_rows, validate_improvement
from app.services.regression import DEFAULT_CRITERIA

router = APIRouter()
logger = logging.getLogger(__name__)

_MAX_FREEFORM_LEN = 200


_TERMINAL_EXPERIMENT = ("completed", "failed", "stopped")
_IMPROVEMENT_TYPE_LABELS = {"deployment_env": "환경변수", "manifest_patch": "매니페스트 패치"}


def _is_active(run: HypothesisRun, candidates) -> bool:
    return (run.status == "generating"
            or run.freeform_status == "generating"
            or any(c.detail_status == "detailing" for c in candidates))


def _stream_active(run: HypothesisRun, candidates, experiment) -> bool:
    """SSE 구독이 필요한 활동 — 후보/직접 입력/detailing(실험 전) 또는 개선안 생성(실험 후)."""
    return ((_is_active(run, candidates) and experiment is None)
            or run.improvement_status == "generating")


def _improvement_cards(proposals, manifest_yaml: str, form_errors: dict | None = None) -> list[dict]:
    """제안 카드 컨텍스트 — 전/후 미리보기 행은 서버가 manifest 원문에서 계산(배지·값 단일 소스)."""
    cards = []
    for p in proposals:
        spec = {"type": p.type, "deployment": p.deployment, "container": p.container,
                "key": p.key, "value": p.value, "patch": p.patch}
        cards.append({
            "proposal": p,
            "type_label": _IMPROVEMENT_TYPE_LABELS.get(p.type, p.type),
            "rows": preview_rows(spec, manifest_yaml),
            "patch_json": json.dumps(p.patch, ensure_ascii=False, indent=2) if p.type == "manifest_patch" else "",
            "errors": (form_errors or {}).get(p.id, []),
        })
    return cards


def _page(request: Request, session: Session, run: HypothesisRun,
          improvement_form_errors: dict | None = None):
    """워크플로우 셸(experiment_detail.html)을 가설 Run 앵커로 렌더.

    1단계(후보 선택)·2단계(실험 카드)는 partials/_hypothesis_*.html — view 결정·클램프는
    템플릿의 기존 stage_meta 규칙(run.current 초과 view는 기본 view로 강등)을 그대로 쓴다.
    3·4단계는 승인 후보로 조립한 ScenarioRun(hypothesis_run_id) 기준 — 셸의 verify/result 섹션 재사용.
    """
    repo = HypothesisRepository(session)
    candidates = repo.list_candidates(run.id)
    experiment = repo.experiment_for_run(run.id)
    experiment_candidate = (repo.get_candidate(experiment.candidate_id)
                            if experiment and experiment.candidate_id else None)
    scenario_run = ScenarioRunRepository(session).latest_for_hypothesis(run.id)
    proposals = repo.list_proposals(run.id)
    return render_page(
        request, "pages/experiment_detail.html",
        {"active_nav": "experiments",
         "app_count": len(AppRepository(session).list_all()),
         "hypothesis_run": run, "candidates": candidates,
         "experiment": experiment, "experiment_candidate": experiment_candidate,
         "hypothesis_active": _stream_active(run, candidates, experiment),
         # 개선 단계(설계 09/05 §7) — 3단계 상단 패널
         "improvement_cards": _improvement_cards(proposals, run.app.manifest or "",
                                                  improvement_form_errors),
         "improvement_undecided": any(p.status == "proposed" for p in proposals),
         "improvement_approved": sum(p.status == "approved" for p in proposals),
         "improvement_allowed": experiment is not None
                                and experiment.status in _TERMINAL_EXPERIMENT
                                and scenario_run is None,
         # 3단계 준비 세션(startPreparation)은 셸의 data-workflow-app-* 속성을 읽는다
         "workflow_app": run.app, "workflow_objective": run.goal_text,
         "scenario_run": scenario_run,
         "regression_candidates": [c for c in candidates
                                   if c.detail_status == "detailed" and c.params],
         "default_criteria": DEFAULT_CRITERIA,
         "chaos_labels": {k: v["label"] for k, v in CHAOS_SPECS.items()},
         "chaos_specs": CHAOS_SPECS},
    )


@router.post("/hypothesis")
def create_run(
    request: Request,
    background: BackgroundTasks,
    app_id: int = Form(...),
    objective: str = Form(""),
    max_candidates: str = Form("5"),
    session: Session = Depends(get_session),
):
    app = AppRepository(session).get(app_id)
    if app is None:
        raise HTTPException(status_code=404, detail="app not found")
    if app.env != "k3s":
        # k3s 먼저 — 저장 manifest 기반이라 조립이 결정적. EKS 조립기는 추후.
        raise HTTPException(status_code=400,
                            detail="가설 수립은 아직 k3s 앱만 지원해요 (EKS는 추후)")
    try:
        count = int(max_candidates)
    except (TypeError, ValueError):
        count = 5
    payload = assemble_hypothesis_input(session, app, objective.strip(), count)
    run = HypothesisRepository(session).create_run(
        app_id=app.id, goal_text=payload.goal_text,
        candidate_count=payload.candidate_count,
        input_payload=payload.model_dump(), status="generating")
    background.add_task(_watch_generation, run.id)
    resp = _page(request, session, run)
    resp.headers["HX-Push-Url"] = f"/hypothesis/{run.id}?view=plan"
    return resp


@router.get("/hypothesis/{run_id}")
def show_run(run_id: int, request: Request, session: Session = Depends(get_session)):
    run = HypothesisRepository(session).get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="hypothesis run not found")
    return _page(request, session, run)


@router.post("/hypothesis/{run_id}/freeform")
def add_freeform(
    run_id: int,
    request: Request,
    background: BackgroundTasks,
    user_text: str = Form(...),
    session: Session = Depends(get_session),
):
    repo = HypothesisRepository(session)
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="hypothesis run not found")
    if run.status != "ready":
        raise HTTPException(status_code=409, detail="후보가 준비된 뒤에 요청할 수 있어요")
    if run.freeform_status == "generating":
        raise HTTPException(status_code=409, detail="직접 입력 후보를 이미 만들고 있어요")
    text = user_text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="원하는 시나리오를 입력해 주세요")
    if len(text) > _MAX_FREEFORM_LEN:
        raise HTTPException(status_code=422,
                            detail=f"{_MAX_FREEFORM_LEN}자 이하로 입력해 주세요")
    repo.set_freeform(run, "generating")
    background.add_task(_watch_freeform, run.id, text)
    return _page(request, session, run)


@router.post("/hypothesis/{run_id}/select")
def select_candidate(
    run_id: int,
    request: Request,
    background: BackgroundTasks,
    candidate_id: int = Form(...),
    session: Session = Depends(get_session),
):
    repo = HypothesisRepository(session)
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="hypothesis run not found")
    candidate = repo.get_candidate(candidate_id)
    if candidate is None or candidate.run_id != run.id:
        raise HTTPException(status_code=404, detail="candidate not found")
    if repo.experiment_for_run(run.id) is not None:
        raise HTTPException(status_code=409, detail="이 요청에서는 이미 실험이 시작됐어요")
    if candidate.detail_status not in ("proposed", "failed"):
        raise HTTPException(status_code=409, detail="이미 구체화 중이거나 완료된 후보예요")
    busy = [e for e in run.app.experiments
            if e.status in ("pending", "deploying", "running")]
    if busy:
        raise HTTPException(status_code=409, detail="이 앱에 진행 중인 실험이 있어요")
    repo.set_candidate_detail(candidate, "detailing")
    background.add_task(_watch_detailing, candidate.id)
    return _page(request, session, run)


@router.post("/hypothesis/{run_id}/improvements")
def propose_improvements(
    run_id: int,
    request: Request,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
):
    """2단계 실험 종료 후 AI 개선안 생성 트리거 (재생성 = 기존 제안 교체)."""
    repo = HypothesisRepository(session)
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="hypothesis run not found")
    experiment = repo.experiment_for_run(run.id)
    if experiment is None or experiment.status not in _TERMINAL_EXPERIMENT:
        raise HTTPException(status_code=409, detail="실험이 끝난 뒤에 개선안을 만들 수 있어요")
    if run.improvement_status == "generating":
        raise HTTPException(status_code=409, detail="개선안을 이미 만들고 있어요")
    if ScenarioRunRepository(session).latest_for_hypothesis(run.id) is not None:
        raise HTTPException(status_code=409, detail="최종 회귀가 시작된 뒤에는 개선안을 바꿀 수 없어요")
    repo.set_improvement(run, "generating")
    background.add_task(_watch_improvements, run.id)
    return _page(request, session, run)


@router.post("/hypothesis/{run_id}/improvements/approve")
async def approve_improvements(
    run_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    """체크한 제안 → approved(편집분은 화이트리스트 재검증 후 교체), 나머지 → rejected.
    폼: proposal_ids(복수) · none=1(전부 제외) · patch_{id}(JSON) · value_{id}."""
    repo = HypothesisRepository(session)
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="hypothesis run not found")
    if run.improvement_status != "ready":
        raise HTTPException(status_code=409, detail="개선안이 준비된 뒤에 결정할 수 있어요")
    if ScenarioRunRepository(session).latest_for_hypothesis(run.id) is not None:
        raise HTTPException(status_code=409, detail="최종 회귀가 시작된 뒤에는 결정을 바꿀 수 없어요")
    form = await request.form()
    proposals = {p.id: p for p in repo.list_proposals(run.id)}
    approved: set[int] = set()
    if form.get("none") != "1":
        for raw in form.getlist("proposal_ids"):
            try:
                pid = int(raw)
            except (TypeError, ValueError):
                continue
            if pid in proposals:
                approved.add(pid)
    edits: dict[int, dict] = {}
    errors: dict[int, list[str]] = {}
    for pid in approved:
        p = proposals[pid]
        if p.type == "manifest_patch":
            text = (form.get(f"patch_{pid}") or "").strip()
            if not text:
                continue
            try:
                patch = json.loads(text)
            except json.JSONDecodeError as e:
                errors[pid] = [f"patch JSON 파싱 실패: {e.msg}"]
                continue
            if patch == p.patch:
                continue
            spec = {"type": p.type, "deployment": p.deployment, "container": p.container, "patch": patch}
        else:
            value = form.get(f"value_{pid}")
            if value is None or value == p.value:
                continue
            spec = {"type": p.type, "deployment": p.deployment, "container": p.container,
                    "key": p.key, "value": value}
        normalized, spec_errors = validate_improvement(spec)
        if spec_errors:
            errors[pid] = spec_errors
        else:
            edits[pid] = normalized
    if errors:
        return _page(request, session, run, improvement_form_errors=errors)
    repo.decide_proposals(run.id, approved, edits)
    return _page(request, session, run)


@router.post("/hypothesis/{run_id}/improvements/reopen")
def reopen_improvements(run_id: int, request: Request, session: Session = Depends(get_session)):
    """결정 취소 — 회귀 시작 전이면 전부 proposed로 되돌려 다시 고를 수 있게 (편집값은 유지)."""
    repo = HypothesisRepository(session)
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="hypothesis run not found")
    if ScenarioRunRepository(session).latest_for_hypothesis(run.id) is not None:
        raise HTTPException(status_code=409, detail="최종 회귀가 시작된 뒤에는 결정을 바꿀 수 없어요")
    repo.reopen_proposals(run.id)
    return _page(request, session, run)


# ── 백그라운드 워처 (builds·experiments 패턴 — SessionLocal 직접) ──

def _watch_improvements(run_id: int) -> None:
    s = SessionLocal()
    try:
        repo = HypothesisRepository(s)
        run = repo.get_run(run_id)
        if run is None or run.improvement_status != "generating":
            return
        try:
            experiment = repo.experiment_for_run(run.id)
            if experiment is None:
                raise RuntimeError("개선안 근거가 될 실험이 없어요")
            candidate = repo.get_candidate(experiment.candidate_id) if experiment.candidate_id else None
            payload = assemble_improvement_input(run, experiment, candidate)
            proposals = run_proposing(make_hypothesis_agent(), payload)
            repo.replace_proposals(run.id, experiment.id, proposals)
            repo.set_improvement(run, "ready")
        except Exception as e:
            logger.exception("improvement proposing failed (run %s)", run_id)
            repo.set_improvement(run, "failed", error=str(e))
    finally:
        s.close()


def _watch_generation(run_id: int) -> None:
    s = SessionLocal()
    try:
        repo = HypothesisRepository(s)
        run = repo.get_run(run_id)
        if run is None or run.status != "generating":
            return
        try:
            agent = make_hypothesis_agent()
            payload = HypothesisInputPayload(**run.input_payload)
            candidates = run_generation(agent, payload)
            repo.add_candidates(run.id, candidates, source="agent")
            snap = agent.snapshot()
            repo.set_snapshot(run, snap.get("model_name", ""), snap.get("cli_version", ""))
            repo.set_status(run, "ready", finished=True)
        except Exception as e:
            logger.exception("hypothesis generation failed (run %s)", run_id)
            repo.set_status(run, "failed", error=str(e), finished=True)
    finally:
        s.close()


def _watch_freeform(run_id: int, user_text: str) -> None:
    s = SessionLocal()
    try:
        repo = HypothesisRepository(s)
        run = repo.get_run(run_id)
        if run is None or run.freeform_status != "generating":
            return
        try:
            agent = make_hypothesis_agent()
            payload = HypothesisInputPayload(**run.input_payload)
            existing = {(c.target_workload, c.chaos_type)
                        for c in repo.list_candidates(run.id)}
            candidate = run_concretize(agent, payload, user_text, existing)
            repo.add_candidates(run.id, [candidate], source="user_input")
            repo.set_freeform(run, "")
        except Exception as e:
            logger.exception("hypothesis freeform failed (run %s)", run_id)
            repo.set_freeform(run, "failed", error=str(e))
    finally:
        s.close()


def _watch_detailing(candidate_id: int) -> None:
    """선택 후보 detailing → 검증 → 기존 실험 생성 경로 → 실험 워처 이어달리기."""
    exp_id: int | None = None
    s = SessionLocal()
    try:
        repo = HypothesisRepository(s)
        candidate = repo.get_candidate(candidate_id)
        if candidate is None or candidate.detail_status != "detailing":
            return
        run = candidate.run
        app = run.app
        try:
            agent = make_hypothesis_agent()
            payload = HypothesisInputPayload(**run.input_payload)
            proposal = CandidateProposal(
                title=candidate.title, chaos_type=candidate.chaos_type,
                target_workload=candidate.target_workload,
                hypothesis=candidate.hypothesis,
                expected_impact=candidate.expected_impact)
            params, rationale = run_detailing(agent, payload, proposal)
            # detailing 동안 다른 실험이 시작됐을 수 있음 — 실험 생성 직전 재확인
            busy = [e for e in app.experiments
                    if e.status in ("pending", "deploying", "running")]
            if busy:
                raise RuntimeError("이 앱에 진행 중인 실험이 있어요 — 종료 후 다시 선택해 주세요")
            repo.set_candidate_detail(candidate, "detailed",
                                      params=params, rationale=rationale)
            exp = start_experiment(s, app, candidate.chaos_type, params,
                                   candidate_id=candidate.id)
            if exp.status in ("deploying", "running"):
                exp_id = exp.id
        except Exception as e:
            logger.exception("hypothesis detailing failed (candidate %s)", candidate_id)
            repo.set_candidate_detail(candidate, "failed", error=str(e))
            return
    finally:
        s.close()
    if exp_id is not None:
        _watch_experiment(exp_id)  # 같은 백그라운드 스레드에서 실험 생명주기 계속


@router.get("/hypothesis/{run_id}/stream")
async def hypothesis_stream(run_id: int, request: Request):
    """상태 전용 SSE(DB 폴링) — 활동이 없으면 종료 (experiments/stream 미러).

    활동 = generating · freeform 생성 · 후보 detailing · (실험 후) 개선안 생성. 실험이 만들어지면
    completed(redirect=/hypothesis/{id}?view=execute)로 종료 — 셸 2단계(실험 카드)로 착지.
    개선안 생성이 끝나면 redirect=?view=verify(3단계 개선 패널). 배지·값은 항상 서버 렌더가 단일 소스.
    """
    async def gen():
        last = None
        for _ in range(400):  # ~13분 (2s 간격) > 타임아웃 180s × 재시도
            if await request.is_disconnected():
                break
            s = SessionLocal()
            try:
                repo = HypothesisRepository(s)
                run = repo.get_run(run_id)
                if run is None:
                    snapshot, active, redirect = {"status": None}, False, ""
                else:
                    candidates = repo.list_candidates(run.id)
                    experiment = repo.experiment_for_run(run.id)
                    snapshot = {
                        "status": run.status,
                        "freeform": run.freeform_status,
                        "details": {str(c.id): c.detail_status for c in candidates},
                        "experiment_id": experiment.id if experiment else None,
                        "improvements": run.improvement_status,
                    }
                    active = _stream_active(run, candidates, experiment)
                    if experiment and run.improvement_status in ("ready", "failed"):
                        redirect = f"/hypothesis/{run_id}?view=verify"
                    else:
                        redirect = f"/hypothesis/{run_id}?view=execute" if experiment else ""
            finally:
                s.close()
            if snapshot != last:
                yield {"event": "status", "data": json.dumps(snapshot)}
                last = snapshot
            if not active:
                yield {"event": "completed", "data": json.dumps({"redirect": redirect})}
                break
            await asyncio.sleep(2)

    return EventSourceResponse(gen())
