from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import get_session
from app.db.repositories import (
    AppRepository,
    BuildRepository,
    ExperimentRepository,
    ScenarioRunRepository,
)
from app.deps import get_app_count, get_k8s, get_local_k8s, get_tunnel
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
    ctx = {
        "active_nav": "dashboard",
        "app_count": app_count,
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
    # apps는 새 실험 위저드 step 1(대상 앱 선택)용 — 목록 테이블은 정적 시안
    apps = AppRepository(session).list_all()
    ctx = {"active_nav": "experiments", "app_count": app_count, "apps": apps}
    return render_page(request, "pages/experiments.html", ctx)


@router.get("/experiments/{exp_id}")
def experiment_detail(
    request: Request,
    exp_id: int,
    app_id: int | None = None,
    objective: str = "",
    scenario_run_id: int | None = None,
    session: Session = Depends(get_session),
    app_count: int = Depends(get_app_count),
):
    if exp_id not in (1, 2, 3):
        raise HTTPException(status_code=404, detail="experiment not found")
    scenario_run = ScenarioRunRepository(session).get(scenario_run_id) if scenario_run_id is not None else None
    if scenario_run_id is not None and scenario_run is None:
        raise HTTPException(status_code=404, detail="scenario run not found")
    workflow_app = scenario_run.app if scenario_run else (
        AppRepository(session).get(app_id) if app_id is not None else None
    )
    if app_id is not None and workflow_app is None:
        raise HTTPException(status_code=404, detail="app not found")
    ctx = {"active_nav": "experiments", "app_count": app_count,
           "workflow_app": workflow_app, "workflow_objective": objective,
           "scenario_run": scenario_run}
    return render_page(request, "pages/experiment_detail.html", ctx)


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


@router.get("/infra/local")
def local_infra_page(
    request: Request,
    app_count: int = Depends(get_app_count),
    local_k8s: interfaces.LocalK8sService = Depends(get_local_k8s),
    tunnel: interfaces.TunnelService = Depends(get_tunnel),
):
    ctx = {"active_nav": "local-infra", "app_count": app_count,
           "is_stub": not settings.local_kubeconfig,
           "tunnel": tunnel.status(),
           **local_k8s.overview()}
    return render_page(request, "pages/infra_local.html", ctx)


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
