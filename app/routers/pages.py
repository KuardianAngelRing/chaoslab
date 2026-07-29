from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import get_session
from app.db.repositories import (
    AppRepository,
    BuildRepository,
    ExperimentRepository,
    IterationRepository,
)
from app.deps import get_app_count, get_k8s, get_loki
from app.rendering import render_page
from app.services import interfaces

router = APIRouter()


def _recent_activity(session, limit: int = 5) -> list[dict]:
    """전용 활동 테이블 없이 apps·builds·experiments를 최근순으로 합쳐 상위 N개."""
    items: list[dict] = []
    for app in AppRepository(session).list_all():
        items.append({"icon": "solar:add-circle-bold", "badge": None,
                      "text": f"{app.name} 신규 등록", "ts": app.created_at})
        for b in BuildRepository(session).list_for_app(app.id):
            if not b.image_tag:  # 빌드 진행/실패 중엔 SHA가 비어 "새 SHA  배포" 오표기 방지
                continue
            items.append({"icon": "solar:rocket-bold", "badge": b.status,
                          "text": f"{app.name} 새 SHA {b.image_tag[:8]} 배포", "ts": b.started_at})
    for exp in ExperimentRepository(session).list_all():
        items.append({"icon": "solar:bug-bold", "badge": exp.status,
                      "text": f"{exp.app.name}에 {exp.chaos_type} 주입", "ts": exp.started_at})
    items.sort(key=lambda x: x["ts"], reverse=True)
    return items[:limit]


@router.get("/")
def dashboard(
    request: Request,
    session: Session = Depends(get_session),
    app_count: int = Depends(get_app_count),
    k8s: interfaces.K8sService = Depends(get_k8s),
):
    exps = ExperimentRepository(session).list_all()
    running = [e for e in exps if e.status == "running"]
    latest_exp = max(exps, key=lambda e: e.started_at) if exps else None
    iterations = sorted(latest_exp.iterations, key=lambda i: i.iteration) if latest_exp else []
    latest_iter = iterations[-1] if iterations else None
    r_series = ([latest_exp.baseline_r] + [it.r_index for it in iterations]) if latest_exp else []
    r_labels = (["기준선"] + [f"개선 {it.iteration}회차" for it in iterations]) if latest_exp else []
    llm_cost_total = sum(it.llm_cost_usd for e in exps for it in e.iterations)
    latest_r = next((f"{e.r_index:.2f}" for e in exps if e.r_index is not None), "—")
    ctx = {
        "active_nav": "dashboard",
        "app_count": app_count,
        "running_count": len(running),
        "latest_exp": latest_exp,
        "iterations": iterations,
        "latest_iter": latest_iter,
        "r_series": r_series,
        "r_labels": r_labels,
        "llm_cost_total": llm_cost_total,
        "latest_r": latest_r,
        "components": k8s.components(),
        "node_count": len(k8s.nodes()),
        "recent": _recent_activity(session),
    }
    return render_page(request, "pages/dashboard.html", ctx)


@router.get("/apps")
def apps_page(
    request: Request,
    session: Session = Depends(get_session),
    app_count: int = Depends(get_app_count),
):
    from app.routers.apps import deploy_ago_map

    apps = AppRepository(session).list_all()
    ctx = {"active_nav": "apps", "app_count": app_count, "apps": apps,
           "deployed_ago": deploy_ago_map(apps)}
    return render_page(request, "pages/apps.html", ctx)


@router.get("/experiments")
def experiments_page(
    request: Request,
    session: Session = Depends(get_session),
    app_count: int = Depends(get_app_count),
):
    exps = ExperimentRepository(session).list_all()
    apps = AppRepository(session).list_all()
    ctx = {"active_nav": "experiments", "app_count": app_count,
           "experiments": exps, "apps": apps}
    return render_page(request, "pages/experiments.html", ctx)


def _candidate_stub(app) -> list[dict]:
    """AI 후보 생성 목업 — Phase 3 배선 전 stub. 근거형 카드 필드 (ADR-0006/0007)."""
    target = f"{app.namespace}/{app.name}"
    return [
        {"type": "PodChaos", "title": f"{app.name} 파드 강제종료", "target": target,
         "hypothesis": "복제본이 부족하면 파드 장애가 곧바로 요청 유실로 이어질 거예요",
         "impact": "가용성 · 복구 속도"},
        {"type": "NetworkChaos", "title": "서비스 간 지연 200ms 주입", "target": target,
         "hypothesis": "타임아웃·재시도가 없으면 하위 서비스의 지연이 상위 응답 지연으로 전파될 거예요",
         "impact": "응답 지연"},
        {"type": "StressChaos", "title": "CPU 부하 80% 주입", "target": target,
         "hypothesis": "리소스 limit이 없으면 부하 시 같은 노드의 다른 파드까지 느려질 거예요",
         "impact": "응답 지연 · 안정성"},
    ]


# 주의: /experiments/{exp_id}보다 먼저 등록해야 "candidates"가 경로 파라미터로 안 잡힌다
@router.get("/experiments/candidates")
def experiment_candidates(
    request: Request,
    app_id: int = 1,
    objective: str = "",
    session: Session = Depends(get_session),
    app_count: int = Depends(get_app_count),
):
    app = next((a for a in AppRepository(session).list_all() if a.id == app_id), None)
    if app is None:
        raise HTTPException(status_code=404, detail="app not found")
    ctx = {
        "active_nav": "experiments",
        "app_count": app_count,
        "app": app,
        "objective": objective.strip(),
        "candidates": _candidate_stub(app),
    }
    return render_page(request, "pages/experiment_candidates.html", ctx)


@router.get("/experiments/{exp_id}")
def experiment_detail(
    request: Request,
    exp_id: int,
    session: Session = Depends(get_session),
    app_count: int = Depends(get_app_count),
    loki: interfaces.LokiService = Depends(get_loki),
):
    exp = ExperimentRepository(session).get(exp_id)
    if exp is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    iterations = IterationRepository(session).list_for_experiment(exp_id)
    ctx = {
        "active_nav": "experiments",
        "app_count": app_count,
        "exp": exp,
        "iterations": iterations,
        "logs": loki.tail(exp.app.namespace, limit=20),
    }
    return render_page(request, "pages/experiment_detail.html", ctx)


# ChaosPilot(온프레미스 AI 루프) 파이프라인 시연용 정적 정의 — DB·실서비스 미연결 데모
CHAOSPILOT_STAGES = [
    {"emoji": "🔍", "label": "전처리",
     "desc": "업로드된 manifest와 클러스터 리소스를 분석해 실험 대상 서비스와 의존 관계를 파악해요."},
    {"emoji": "💡", "label": "후보 생성",
     "desc": "LLM이 전처리 근거를 바탕으로 장애 가설과 실험 후보 목록을 제안해요."},
    {"emoji": "🙋", "label": "후보 선택", "gate": True, "gate_label": "pod-kill 후보 선택 (모의)",
     "desc": "제안된 후보 중 실행할 실험을 사용자가 직접 골라요. 승인 전에는 진행되지 않아요."},
    {"emoji": "📋", "label": "상세 계획",
     "desc": "선택한 후보를 Chaos Mesh 스펙으로 구체화하고 검증·보정해요."},
    {"emoji": "⚡", "label": "실험 실행",
     "desc": "전용 namespace에 장애를 주입하고 k6 부하로 시스템 반응을 관측해요."},
    {"emoji": "📊", "label": "분석·판정",
     "desc": "관측값 기반으로 통과/실패를 판정해요. 실패하면 개선 패치를 적용하고 같은 실험을 다시 돌려요."},
    {"emoji": "📝", "label": "보고",
     "desc": "실험 결과·개선 이력·회복력 지표를 보고서로 정리해요."},
]


@router.get("/workflow")
def workflow_page(
    request: Request,
    app_count: int = Depends(get_app_count),
):
    ctx = {"active_nav": "workflow", "app_count": app_count, "stages": CHAOSPILOT_STAGES}
    return render_page(request, "pages/workflow.html", ctx)


@router.get("/infra")
def infra_page(
    request: Request,
    session: Session = Depends(get_session),
    app_count: int = Depends(get_app_count),
    k8s: interfaces.K8sService = Depends(get_k8s),
):
    ctx = {
        "active_nav": "infra",
        "app_count": app_count,
        "nodes": k8s.nodes(),
        "components": k8s.components(),
    }
    return render_page(request, "pages/infra.html", ctx)


@router.get("/settings")
def settings_page(
    request: Request,
    session: Session = Depends(get_session),
    app_count: int = Depends(get_app_count),
):
    ctx = {
        "active_nav": "settings",
        "app_count": app_count,
        "llm_model": settings.llm_model,
        "target_r": settings.target_r,
    }
    return render_page(request, "pages/settings.html", ctx)
