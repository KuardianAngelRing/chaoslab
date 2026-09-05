"""실험 생성/중지/watch/SSE — 빌드 파이프라인 패턴 미러."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request, Response
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.config import settings
from app.db.database import SessionLocal, get_session
from app.db.models import Experiment
from app.db.repositories import AppRepository, ExperimentRepository
from app.deps import make_chaos, make_k3s_workload, make_prometheus
from app.rendering import render_page
from app.services.chaos_specs import validate_params
from app.services.metrics_collector import collect_experiment_metrics

router = APIRouter()
logger = logging.getLogger(__name__)

_POLL_S = 5           # watcher 폴링 간격
_RECOVER_CAP = 60     # duration 후 회복 대기 상한 (5s × 60 = 5분)
_PODKILL_GRACE_S = 30  # pod-kill 원샷 유예


def _experiments_response(request: Request, session: Session):
    from app.routers.pages import experiments_context  # 목록 ctx 단일 소스

    ctx = experiments_context(session)
    return render_page(
        request, "pages/experiments.html",
        {"active_nav": "experiments", "app_count": len(ctx["apps"]), **ctx},
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
    loss_percent: str = Form(""),
    rate_mbps: str = Form(""),
    memory_mb: str = Form(""),
    container_name: str = Form(""),
    session: Session = Depends(get_session),
):
    app = AppRepository(session).get(app_id)
    if app is None:
        raise HTTPException(status_code=404, detail="app not found")

    params, errors = validate_params(chaos_type, {
        "latency_ms": latency_ms, "duration_s": duration_s, "cpu_load": cpu_load,
        "loss_percent": loss_percent, "rate_mbps": rate_mbps,
        "memory_mb": memory_mb, "container_name": container_name,
    })
    if errors:
        raise HTTPException(status_code=422, detail=" / ".join(errors))

    busy = [e for e in app.experiments if e.status in ("pending", "deploying", "running")]
    if busy:
        raise HTTPException(status_code=409, detail="이 앱에 진행 중인 실험이 있어요")

    exp = start_experiment(session, app, chaos_type, params)
    if exp.status in ("deploying", "running"):
        background.add_task(_watch_experiment, exp.id)
    return _experiments_response(request, session)


def start_experiment(session: Session, app, chaos_type: str, params: dict,
                     candidate_id: int | None = None) -> Experiment:
    """실험 생성 + 환경 분기 — 폼 라우트와 가설 detailing 워처가 공유.

    k3s(ADR-0009): 전용 ns 예약 + deploying (배포→주입은 워처).
    eks: 즉시 주입 — 실패 시 inject-failed. 반환 exp.status가
    deploying/running이면 호출자가 _watch_experiment를 스케줄해야 한다.
    """
    exp = ExperimentRepository(session).create(
        app_id=app.id, chaos_type=chaos_type, params=params, status="pending",
        candidate_id=candidate_id)

    if app.env == "k3s":
        # ADR-0009: 현장 배포 — 전용 ns에 배포→ready→주입까지 전부 워처(백그라운드)가 수행
        exp.namespace = f"chaoslab-{app.name}-{exp.id}"[:63].rstrip("-")
        exp.status = "deploying"
        session.commit()
        return exp

    try:
        crd = make_chaos(app.env, settings.sut_namespace).inject(
            settings.sut_namespace, app.name, chaos_type, params)
        exp.crd_name = crd
        exp.status = "running"
        session.commit()
    except Exception:
        logger.exception("chaos inject failed (app %s, type %s)", app.name, chaos_type)
        exp.status = "inject-failed"
        session.commit()
    return exp


def _watch_experiment(exp_id: int) -> None:
    """실험 생명주기 워처.

    EKS: (CRD는 라우트가 이미 주입) duration 경과·회복 확인 → CRD 삭제 + completed.
    k3s(ADR-0009): 전용 ns 배포 → ready 대기 → CRD 주입 → 동일 진행 → ns까지 삭제.
    매 폴링마다 DB status 재조회 — stop으로 중지된 경우(정리는 stop 라우트 담당)
    즉시 return. 오류/상한 → failed (k3s는 이때도 ns 정리).
    """
    s = SessionLocal()
    try:
        exp = s.get(Experiment, exp_id)
        if exp is None:
            return
        app = exp.app
        is_k3s = app.env == "k3s"
        namespace = exp.namespace if is_k3s else settings.sut_namespace
        chaos = make_chaos(app.env, namespace)
        chaos_type, crd_name = exp.chaos_type, exp.crd_name
        duration = int(exp.params.get("duration_s") or _PODKILL_GRACE_S)
        params, app_name = exp.params, app.name

        def _still_active() -> bool:
            # identity map 캐시 무시하고 최신 DB status를 읽기 위해 expire 후 재조회
            s.expire_all()
            cur = s.get(Experiment, exp_id)
            return bool(cur and cur.status in ("deploying", "running"))

        status = "completed"
        try:
            if is_k3s:                        # 현장 배포 단계
                workload = make_k3s_workload()
                workload.deploy(namespace, app.manifest or "")
                if not workload.wait_ready(namespace):
                    raise RuntimeError(f"워크로드가 준비되지 않음 ({namespace})")
                if not _still_active():
                    return
                crd_name = chaos.inject(namespace, app_name, chaos_type, params)
                exp = s.get(Experiment, exp_id)
                exp.crd_name = crd_name
                exp.status = "running"
                s.commit()
            waited = 0
            while waited < duration:          # 장애 지속 구간
                if not _still_active():
                    return
                time.sleep(_POLL_S)
                waited += _POLL_S
            recovered = False
            for _ in range(_RECOVER_CAP):     # 회복 대기 (최대 5분)
                if not _still_active():
                    return
                phase = chaos.phase(chaos_type, crd_name)
                if phase == "recovered":
                    recovered = True
                    break
                if chaos_type in ("pod-kill", "container-kill") and phase == "running":
                    # 원샷 액션은 AllRecovered로 전환되지 않음(라이브 08/31 확인) —
                    # 주입 확인 후 파드 ready 재확인으로 회복 판정 (pr-8 regression과 동일 규칙)
                    recovered = (not is_k3s) or make_k3s_workload().wait_ready(namespace)
                    break
                time.sleep(_POLL_S)
            chaos.delete(chaos_type, crd_name)
            if not recovered:                 # 주입 실패·회복 미확인을 completed로 오표기하지 않음
                status = "failed"
        except Exception:
            logger.exception("experiment watch failed (exp %s)", exp_id)
            try:
                if crd_name:
                    chaos.delete(chaos_type, crd_name)
            except Exception:
                logger.exception("chaos cleanup failed (exp %s)", exp_id)
            status = "failed"
        finally:
            if is_k3s:                        # 성공·실패·중지 모두 ns 정리 (idempotent)
                try:
                    make_k3s_workload().teardown(namespace)
                except Exception:
                    logger.exception("namespace teardown failed (%s)", namespace)

        exp = s.get(Experiment, exp_id)
        if exp and exp.status in ("deploying", "running"):  # stop이 먼저면 덮어쓰지 않음
            exp.status = status
            exp.finished_at = datetime.now(timezone.utc)
            s.commit()
            if status == "completed":
                # 실측 3구간 소급 집계 + R지수 (실패해도 실험 상태 불변)
                collect_experiment_metrics(s, exp, make_prometheus(exp.app.env))
    finally:
        s.close()


@router.post("/experiments/{exp_id}/stop")
def stop_experiment(
    exp_id: int,
    request: Request,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
    next: str = Form(""),
):
    exp = ExperimentRepository(session).get(exp_id)
    if exp is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    if exp.status not in ("deploying", "running"):
        raise HTTPException(status_code=409, detail="진행 중인 실험이 아니에요")

    env = exp.app.env
    namespace = exp.namespace if env == "k3s" else settings.sut_namespace
    exp.status = "stopped"
    exp.finished_at = datetime.now(timezone.utc)
    session.commit()
    background.add_task(_cleanup_task, env, namespace, exp.chaos_type, exp.crd_name)
    if next and next.startswith("/") and not next.startswith("//"):
        # 가설 셸(2단계 카드)에서 중지 → 목록 대신 그 view로 복귀. htmx HX-Location = ajax GET + 스왑 (전체 리로드 없음)
        return Response(status_code=204, headers={
            "HX-Location": json.dumps({"path": next, "target": "#main-content", "swap": "innerHTML"})})
    return _experiments_response(request, session)


def _cleanup_task(env: str, namespace: str, chaos_type: str, crd_name: str) -> None:
    """중지 시 정리: CRD 삭제 + (k3s) 실험 전용 ns 삭제. 모두 idempotent."""
    try:
        if crd_name:
            make_chaos(env, namespace).delete(chaos_type, crd_name)
    except Exception:
        logger.exception("chaos delete failed (%s/%s)", chaos_type, crd_name)
    if env == "k3s":
        try:
            make_k3s_workload().teardown(namespace)
        except Exception:
            logger.exception("namespace teardown failed (%s)", namespace)


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
            if status not in ("deploying", "running"):
                yield {"event": "completed", "data": json.dumps({"status": status})}
                break
            await asyncio.sleep(2)

    return EventSourceResponse(gen())


_LIVE_ACTIVE = ("pending", "deploying", "running")
_LIVE_KEYS = ("rps", "error_rate_pct", "p95_ms", "p99_ms", "ready_pods")
_LIVE_INTERVAL_S = 3  # 메트릭 스트림 틱 간격


@router.get("/experiments/{exp_id}/metrics/stream")
async def experiment_metrics_stream(exp_id: int, request: Request):
    """실험 진행 중 Prometheus 즉시값(live_snapshot) 3초 간격 SSE — status 스트림과 분리.

    매 틱 DB 재조회 → 활성 상태를 벗어나면 completed 이벤트 후 종료. pending(k3s 배포 전)이면
    값 None인 metric 틱을 보내되 스트림은 유지. 네임스페이스는 exp.namespace(k3s 전용 ns) 우선.
    """
    prom = None  # 앱 env(k3s/eks)에 따라 구현체가 달라 첫 틱에서 결정

    async def gen():
        nonlocal prom
        for _ in range(1260):  # 3s × 1260 ≈ 63분 상한 (> watcher 상한)
            if await request.is_disconnected():
                break
            s = SessionLocal()
            try:
                exp = s.get(Experiment, exp_id)
                status = exp.status if exp else None
                namespace = (exp.namespace or exp.app.namespace) if exp else ""
                app_name = exp.app.name if exp else ""
                if prom is None:
                    prom = make_prometheus(exp.app.env if exp else "eks")
            finally:
                s.close()
            if status not in _LIVE_ACTIVE:
                yield {"event": "completed", "data": json.dumps({"status": status})}
                break
            if status == "pending":
                snap = {"ts": datetime.now(timezone.utc).isoformat(),
                        **{k: None for k in _LIVE_KEYS}}
            else:
                snap = await asyncio.to_thread(prom.live_snapshot, namespace, app_name)
            yield {"event": "metric", "data": json.dumps({**snap, "status": status})}
            await asyncio.sleep(_LIVE_INTERVAL_S)

    return EventSourceResponse(gen())
