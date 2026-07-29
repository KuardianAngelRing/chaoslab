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


def _plan_stub(app, candidate: str, custom_text: str) -> dict:
    """계획 구체화 목업 — 검토 화면 시안 3종(B/C/E)이 공유하는 데이터.

    실배선 시 ExperimentPlanAgent 결과 + ce_agents 이벤트로 대체.
    """
    ns = f"exp-{app.name}-a1b2"
    cands = _candidate_stub(app)
    idx = {"1": 0, "2": 1, "3": 2}.get(candidate)
    if candidate == "custom":
        cand = {"type": "PodChaos", "title": "직접 입력 실험",
                "hypothesis": custom_text or "직접 서술한 장애 방향", "target": f"{app.namespace}/{app.name}"}
    elif idx is not None:
        cand = cands[idx]
    else:
        cand = cands[0]

    yaml_by_type = {
        "PodChaos": (
            f"apiVersion: chaos-mesh.org/v1alpha1\nkind: PodChaos\nmetadata:\n"
            f"  name: {ns}-podkill\n  namespace: {ns}\nspec:\n  action: pod-kill\n  mode: one\n"
            f"  selector:\n    namespaces:\n      - {ns}\n    labelSelectors:\n      app: {app.name}\n"
            f"  duration: \"30s\""),
        "NetworkChaos": (
            f"apiVersion: chaos-mesh.org/v1alpha1\nkind: NetworkChaos\nmetadata:\n"
            f"  name: {ns}-netdelay\n  namespace: {ns}\nspec:\n  action: delay\n  mode: all\n"
            f"  selector:\n    namespaces:\n      - {ns}\n    labelSelectors:\n      app: {app.name}\n"
            f"  delay:\n    latency: \"200ms\"\n    jitter: \"50ms\"\n  duration: \"60s\""),
        "StressChaos": (
            f"apiVersion: chaos-mesh.org/v1alpha1\nkind: StressChaos\nmetadata:\n"
            f"  name: {ns}-cpustress\n  namespace: {ns}\nspec:\n  mode: one\n"
            f"  selector:\n    namespaces:\n      - {ns}\n    labelSelectors:\n      app: {app.name}\n"
            f"  stressors:\n    cpu:\n      workers: 2\n      load: 80\n  duration: \"60s\""),
    }
    fault_by_type = {
        "PodChaos": ("pod-kill · 30초", "파드 1개를 강제종료"),
        "NetworkChaos": ("delay 200ms(±50ms) · 60초", "서비스 간 지연 200ms를 주입"),
        "StressChaos": ("CPU 80% · worker 2 · 60초", "CPU 부하 80%를 주입"),
    }
    fault, action_ko = fault_by_type[cand["type"]]

    conditions = [
        {"label": "대상", "value": f"app={app.name} · {cand['target']}", "mono": True},
        {"label": "장애", "value": f"{cand['type']} · {fault}"},
        {"label": "부하", "value": "k6 · 10 VUs · 60초 · GET /healthz", "mono": True,
         "warn": "부하 경로 /healthz 잠정 — ADR-0005 재논의 대상" if cand["type"] == "NetworkChaos" else None},
        {"label": "격리 namespace", "value": f"{ns} (실험 후 자동 삭제)", "mono": True},
        {"label": "판정 기준", "value": "장애 중 ready 파드 유지 · 60초 내 복구 · 에러율 5% 미만"},
    ]
    events = [
        {"emoji": "🙋", "text": f"후보 승인 — {cand['title']}", "dur": "14:02:11", "kind": "start"},
        {"emoji": "🔍", "text": f"대상 서비스 구조 분석 완료 — deployment 3개 확인, {app.name} replicas 1 (단일 복제본)", "dur": "3.2초"},
        {"emoji": "🛠️", "text": f"Chaos Mesh 스펙 생성 완료 — {fault} · k6 10 VUs", "dur": "18.4초"},
        {"emoji": "🩹", "text": "검증 실패 1건 → 보정 완료 — selector 라벨을 labelSelectors 아래로 중첩", "dur": "12.1초", "kind": "warn"},
    ]
    checks = [
        {"title": "대상이 맞나요?", "badge": "가장 중요",
         "desc": f"app={app.name} 이(가) 장애 대상이에요. 다른 서비스가 잡혀 있으면 여기서 멈추세요."},
        {"title": "장애 유형과 강도", "badge": None,
         "desc": f"{cand['type']} · {fault} — k6 부하 10 VUs를 60초간 /healthz로 흘려요."},
        {"title": "판정 기준", "badge": None,
         "desc": "장애 중 ready 파드 유지 · 60초 내 복구 · 에러율 5% 미만 — 하나라도 어기면 실패 판정 후 자동 개선 루프로 넘어가요."},
    ]
    return {
        "candidate": cand,
        "summary": f"격리 공간 {ns}에서 {app.name}에 {action_ko}하고, 60초간 k6 부하를 흘리며 복구를 관측해요.",
        "namespace": ns,
        "yaml": yaml_by_type[cand["type"]],
        "conditions": conditions,
        "events": events,
        "checks": checks,
        "repair_note": "selector 라벨을 labelSelectors 아래로 중첩했어요",
        "total_sec": "33.7초",
    }


# 주의: /experiments/{exp_id}보다 먼저 등록해야 "plan-review"가 경로 파라미터로 안 잡힌다
@router.get("/experiments/plan-review")
def experiment_plan_review(
    request: Request,
    app_id: int = 1,
    candidate: str = "1",
    custom_text: str = "",
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
        "plan": _plan_stub(app, candidate, custom_text.strip()),
    }
    return render_page(request, "pages/experiment_plan_review.html", ctx)


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


# 로컬(라즈베리파이 k3s) 인프라 목업 — 실배선 시 SSH 터널 경유 k8s API·Prometheus 조회로 대체.
# 노드 온도는 node-exporter(hwmon), CPU·메모리는 metrics-server(kubectl top) 기준 값.
LOCAL_K3S_STUB = {
    "cluster": {"name": "chaospilot-k3s", "version": "v1.32.3+k3s1", "arch": "arm64",
                "access": "SSH 터널 · localhost:6443"},
    "pod_count": 24,
    "namespaces": ["kube-system", "chaos-mesh", "chaospilot-observability", "order-msa"],
    "nodes": [
        {"name": "masternode", "model": "Raspberry Pi 4B 8GB", "role": "control-plane · etcd",
         "cpu_pct": 21, "mem_pct": 48, "temp_c": 52.1, "status": "Ready"},
        {"name": "worker1", "model": "Raspberry Pi 4B 4GB", "role": "worker",
         "cpu_pct": 34, "mem_pct": 61, "temp_c": 55.3, "status": "Ready"},
        {"name": "worker2", "model": "Raspberry Pi 4B 4GB", "role": "worker",
         "cpu_pct": 18, "mem_pct": 44, "temp_c": 49.8, "status": "Ready"},
    ],
    "components": [
        {"name": "Chaos Mesh", "detail": "controller 1/1 · daemon 3/3", "ns": "chaos-mesh"},
        {"name": "Prometheus", "detail": "메트릭 수집 · service proxy 조회", "ns": "chaospilot-observability"},
        {"name": "Loki", "detail": "로그 저장 · LogQL 조회", "ns": "chaospilot-observability"},
        {"name": "kube-state-metrics", "detail": "리소스 상태 메트릭", "ns": "chaospilot-observability"},
        {"name": "Alloy", "detail": "로그 수집 에이전트 (DaemonSet 3/3)", "ns": "chaospilot-observability"},
    ],
}


@router.get("/infra/local")
def local_infra_page(
    request: Request,
    app_count: int = Depends(get_app_count),
):
    ctx = {"active_nav": "local-infra", "app_count": app_count, **LOCAL_K3S_STUB}
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
