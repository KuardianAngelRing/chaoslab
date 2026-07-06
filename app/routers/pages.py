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
    ctx = {"active_nav": "experiments", "app_count": app_count, "experiments": exps}
    return render_page(request, "pages/experiments.html", ctx)


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
