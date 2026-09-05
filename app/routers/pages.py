from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import get_session
from app.db.repositories import (
    AppRepository,
    BuildRepository,
    ExperimentRepository,
    HypothesisRepository,
    ScenarioRunRepository,
)
from app.deps import get_app_count, get_k8s, get_local_k8s, get_tunnel
from app.rendering import EXPERIMENT_STATUS_LABELS, render_page
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


# ── 실험 목록: 가설 Run 행 뷰모델 (배지·라벨은 서버 렌더 단일 소스) ──


def hypothesis_run_rows(session) -> list[dict]:
    from app.routers.apps import _ago

    repo = HypothesisRepository(session)
    scenario_repo = ScenarioRunRepository(session)
    rows = []
    for run in repo.list_runs():
        candidates = repo.list_candidates(run.id)
        exp = repo.experiment_for_run(run.id)
        chosen = next((c for c in candidates if c.detail_status in ("detailing", "detailed")), None)
        scenario_run = scenario_repo.latest_for_hypothesis(run.id)
        if scenario_run is not None:
            # 3·4단계 — 승인 후보로 조립한 최종 회귀(ScenarioRun.hypothesis_run_id)
            comparison = scenario_run.comparison or {}
            ts = scenario_run.finished_at or scenario_run.updated_at
            if scenario_run.status in ("completed", "failed"):
                stage, step, view = "결과", "4/4", "result"
                after_r = (comparison.get("r") or {}).get("after") or {}
                if scenario_run.status == "failed":
                    label, badge, verdict = "실행 실패", "badge-danger", "판정 불가"
                else:
                    label, badge = {
                        "passed": ("전체 통과", "badge-success"),
                        "failed": ("기준 미충족", "badge-danger"),
                    }.get(comparison.get("verdict", ""), ("판정 불가 포함", "badge-warning"))
                    verdict = (f"R={after_r['score']}" if after_r.get("available")
                               else "R 산정 불가")
            else:
                stage, step, view = "최종 회귀 검증", "3/4", "verify"
                label, badge, verdict = "회귀 진행 중", "badge-info", "판정 전"
        elif exp is not None:
            label, badge = EXPERIMENT_STATUS_LABELS.get(exp.status, (exp.status, "badge-muted"))
            stage, step, view = "순차 실행·개선", "2/4", "execute"
            verdict = (f"R={exp.r_index:.4f}" if exp.r_index is not None
                       else ("판정 전" if exp.status in ("pending", "deploying", "running") else "R 산정 불가"))
            ts = exp.finished_at or exp.started_at
        else:
            stage, step, view = "후보 선택", "1/4", "plan"
            if run.status == "generating":
                label, badge, verdict = "후보 생성 중", "badge-info", "판정 전"
            elif run.status == "failed":
                label, badge, verdict = "생성 실패", "badge-danger", "후보 없음"
            elif chosen is not None:
                label, badge, verdict = "파라미터 구체화 중", "badge-info", "판정 전"
            else:
                label, badge, verdict = "선택 필요", "badge-warning", "판정 전"
            ts = run.finished_at or run.created_at
        rows.append({
            "id": run.id, "code": f"HYP-{run.id}", "app_name": run.app.name,
            "goal": run.goal_text or f"{run.app.name} 복원력 검증",
            "stage": stage, "step": step, "view": view,
            "selected": (chosen.title if chosen else f"{len(candidates)}개 후보"),
            "verdict": verdict, "updated": _ago(ts) or "-",
            "status": label, "badge": badge, "experiment": exp,
        })
    return rows


def experiments_context(session) -> dict:
    """실험 목록 페이지 ctx — pages·experiments 라우터 공용 (위저드용 apps + 가설 Run 행 + KPI)."""
    rows = hypothesis_run_rows(session)
    kpi = {
        "total": len(rows),
        "needs_choice": sum(1 for r in rows if r["status"] == "선택 필요"),
        "running": sum(1 for r in rows if r["badge"] == "badge-info"),
        "completed": sum(1 for r in rows if r["badge"] == "badge-success"),
    }
    return {"apps": AppRepository(session).list_all(),
            "hypothesis_rows": rows, "hypothesis_kpi": kpi}


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
    ctx = {"active_nav": "experiments", "app_count": app_count, **experiments_context(session)}
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
