"""앱 등록(bootstrap) + 수동 빌드 트리거. 무거운 IO는 BackgroundTasks로 위임."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import SessionLocal, get_session
from app.db.models import App, Build
from app.db.repositories import AppRepository, BuildRepository
from app.deps import get_app_count, make_builder, make_gitops, make_k8s
from app.rendering import render_page
from app.services.interfaces import BuildRequest
from app.services.real.gitops import derive_app_name, split_env  # 순수 함수 (IO 의존 없음)

router = APIRouter()
logger = logging.getLogger(__name__)


def parse_env_json(raw: str) -> list[dict]:
    """env_json(폼) → [{key,value,is_secret}] 정규화. 깨진 입력은 빈 리스트."""
    try:
        data = json.loads(raw or "[]")
    except (ValueError, TypeError):
        return []
    out: list[dict] = []
    if isinstance(data, list):
        for e in data:
            if isinstance(e, dict) and str(e.get("key") or "").strip():
                out.append({"key": str(e["key"]).strip(),
                            "value": e.get("value", ""),
                            "is_secret": bool(e.get("is_secret"))})
    return out


def _ago(dt: datetime | None) -> str | None:
    """상대시각 한국어 표기 (방금 전 / N분 전 / N시간 전 / N일 전)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    s = (datetime.now(timezone.utc) - dt).total_seconds()
    if s < 60:
        return "방금 전"
    if s < 3600:
        return f"{int(s // 60)}분 전"
    if s < 86400:
        return f"{int(s // 3600)}시간 전"
    return f"{int(s // 86400)}일 전"


def deploy_ago_map(apps) -> dict[int, str | None]:
    """앱별 마지막 배포(성공 빌드) 상대시각. 성공 빌드가 없으면 None."""
    out: dict[int, str | None] = {}
    for a in apps:
        done = [b.finished_at or b.started_at
                for b in a.builds if b.status == "succeeded" and b.image_tag]
        out[a.id] = _ago(max(done)) if done else None
    return out


def _apps_response(request: Request, session: Session):
    apps = AppRepository(session).list_all()
    return render_page(
        request, "pages/apps.html",
        {"active_nav": "apps", "app_count": len(apps), "apps": apps,
         "deployed_ago": deploy_ago_map(apps)},
    )


# ── 등록 ──────────────────────────────────────────────────────
@router.post("/apps")
def register_app(
    request: Request,
    background: BackgroundTasks,
    repo_url: str = Form(...),
    branch: str = Form("main"),
    framework: str = Form("docker"),  # Dockerfile 전제 — 빌드 워크플로 파라미터용 기본값
    health_path: str = Form("/healthz"),
    port: int = Form(8080),
    env_json: str = Form("[]"),
    session: Session = Depends(get_session),
):
    name = derive_app_name(repo_url)
    if settings.use_real_services:
        from app.services.real.gitops import detect_framework
        framework = detect_framework(repo_url, branch, settings.github_token)
    env_vars = parse_env_json(env_json)
    repo = AppRepository(session)
    existing = next((a for a in repo.list_all() if a.name == name), None)
    if existing is None:
        repo.create(
            name=name, repo_url=repo_url, branch=branch, framework=framework,
            health_path=health_path, port=port,
            namespace=settings.sut_namespace, status="registering",
            env_vars=env_vars,
        )
    else:
        existing.repo_url = repo_url
        existing.branch = branch
        existing.framework = framework
        existing.health_path = health_path
        existing.port = port
        existing.env_vars = env_vars
        existing.status = "registering"
        session.commit()
    background.add_task(_bootstrap, name)
    return _apps_response(request, session)


K3S_SOURCE = "k3s://manifest-upload"  # 환경 배지 판별용 소스 마킹 — App 모델에 환경 필드 생기면 교체


# ── k3s 등록 (ADR-0003/0004) — 목업 stub: manifest 저장·apply 없이 App 행만 생성 ──
@router.post("/apps/k3s")
def register_k3s_app(
    request: Request,
    name: str = Form(...),
    health_path: str = Form("/healthz"),
    namespace: str = Form(""),
    session: Session = Depends(get_session),
):
    ns = namespace.strip() or name  # ADR-0004: 네임스페이스는 앱 이름 자동 파생
    repo = AppRepository(session)
    existing = next((a for a in repo.list_all() if a.name == name), None)
    if existing is None:
        repo.create(
            name=name, repo_url=K3S_SOURCE, branch="", framework="manifest",
            health_path=health_path.strip() or "/healthz", namespace=ns, status="healthy",
        )
    else:
        existing.health_path = health_path.strip() or "/healthz"
        existing.namespace = ns
        existing.status = "healthy"
        session.commit()
    return _apps_response(request, session)


def _bootstrap(name: str) -> None:
    """DB env 기반: 비밀→K8s Secret, 평문→values.yaml. 완료 시 status 갱신."""
    gitops = make_gitops()
    k8s = make_k8s()
    s = SessionLocal()
    try:
        app = next((a for a in AppRepository(s).list_all() if a.name == name), None)
        if app is None:
            return
        plain, secret = split_env(app.env_vars or [])
        secret_name = f"{name}-env" if secret else ""
        try:
            if secret:
                k8s.apply_env_secret(app.namespace, secret_name, secret)
            gitops.bootstrap_app(name, app.repo_url, app.port, app.health_path, plain, secret_name)
            status = "ready"
        except Exception:
            logger.exception("bootstrap failed for app %s", name)
            status = "register-failed"
        app.status = status
        s.commit()
    finally:
        s.close()


# ── 빌드 (수동 트리거) ─────────────────────────────────────────
@router.post("/apps/{app_id}/build")
def build_app(
    app_id: int,
    request: Request,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
):
    app = AppRepository(session).get(app_id)
    if app is None:
        raise HTTPException(status_code=404, detail="app not found")

    if settings.use_real_services:
        from app.services.real.gitops import resolve_head_sha
        sha = resolve_head_sha(app.repo_url, app.branch or "HEAD") or "unknown00"
    else:
        sha = "manual00"
    sha8 = sha[:8]
    registry = settings.ecr_registry or "local.registry"
    image = f"{registry}/{app.name}:{sha8}"

    build = BuildRepository(session).create(app_id=app.id, status="running", image_tag=sha8)
    app.status = "building"
    session.commit()

    wf = make_builder().trigger_build(BuildRequest(
        app_name=app.name, repo_url=app.repo_url, framework=app.framework,
        git_sha=sha, image=image,
    ))
    build.workflow_name = wf
    session.commit()

    background.add_task(_watch_build, build.id, app.id, app.name, image, wf)
    return _apps_response(request, session)


# ── 카드 드롭다운 액션: 재배포 / 배포 중지 / 빌드 중지 ────────────
def _restart_task(namespace: str, name: str) -> None:
    try:
        make_k8s().restart_deployment(namespace, name)
    except Exception:
        logger.exception("redeploy(restart) failed for app %s", name)


def _set_replicas_task(name: str, replicas: int) -> None:
    try:
        make_gitops().set_replicas(name, replicas)
    except Exception:
        logger.exception("set_replicas(%s) failed for app %s", replicas, name)


def _stop_build_task(workflow_name: str) -> None:
    try:
        make_builder().stop_build(workflow_name)
    except Exception:
        logger.exception("stop_build failed for workflow %s", workflow_name)


@router.post("/apps/{app_id}/redeploy")
def redeploy_app(
    app_id: int,
    request: Request,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
):
    """중지 상태면 replicas 1로 재개(GitOps), 아니면 rollout restart(파드 재기동)."""
    app = AppRepository(session).get(app_id)
    if app is None:
        raise HTTPException(status_code=404, detail="app not found")
    if app.status == "building":
        raise HTTPException(status_code=409, detail="build in progress")
    if app.status == "stopped":
        app.status = "ready"
        session.commit()
        background.add_task(_set_replicas_task, app.name, 1)
    else:
        background.add_task(_restart_task, app.namespace, app.name)
    return _apps_response(request, session)


@router.post("/apps/{app_id}/deploy/stop")
def stop_deploy(
    app_id: int,
    request: Request,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
):
    """배포 중지 = gitops replicas 0 커밋 (selfHeal이라 직접 scale은 되돌려짐)."""
    app = AppRepository(session).get(app_id)
    if app is None:
        raise HTTPException(status_code=404, detail="app not found")
    if app.status != "stopped":
        app.status = "stopped"
        session.commit()
        background.add_task(_set_replicas_task, app.name, 0)
    return _apps_response(request, session)


@router.post("/apps/{app_id}/build/stop")
def stop_build(
    app_id: int,
    request: Request,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
):
    """진행 중 워크플로 shutdown → _watch_build가 terminal(Failed)을 보고 상태 정리."""
    app = AppRepository(session).get(app_id)
    if app is None:
        raise HTTPException(status_code=404, detail="app not found")
    active = [b for b in BuildRepository(session).list_for_app(app_id)
              if b.status in ("pending", "running") and b.workflow_name]
    if not active:
        raise HTTPException(status_code=409, detail="no build in progress")
    background.add_task(_stop_build_task, active[0].workflow_name)
    return _apps_response(request, session)


def _watch_build(build_id: int, app_id: int, app_name: str, image: str, workflow_name: str) -> None:
    """워크플로 상태 폴링 → 성공 시 image tag 갱신(배포). Stub면 즉시 succeeded."""
    builder = make_builder()
    gitops = make_gitops()
    s = SessionLocal()
    try:
        status = "running"
        for _ in range(120):  # 최대 ~10분 (5s 간격)
            status = builder.build_status(workflow_name)
            if status in ("succeeded", "failed"):
                break
            time.sleep(5)

        build = s.get(Build, build_id)
        app = s.get(App, app_id)
        if status == "succeeded":
            try:
                gitops.update_image_tag(app_name, image)
            except Exception:
                logger.exception("deploy(update_image_tag) failed for app %s", app_name)
            if build:
                build.status = "succeeded"
                build.finished_at = datetime.now(timezone.utc)
            if app:
                app.current_sha = image.rsplit(":", 1)[-1]
                app.status = "healthy"
        else:
            if build:
                build.status = "failed"
                build.finished_at = datetime.now(timezone.utc)
            if app:
                app.status = "build-failed"
        s.commit()
    finally:
        s.close()
