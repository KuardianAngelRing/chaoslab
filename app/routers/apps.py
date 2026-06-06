"""앱 등록(bootstrap) + 수동 빌드 트리거. 무거운 IO는 BackgroundTasks로 위임."""
from __future__ import annotations

import json
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


def parse_env_json(raw: str) -> list[dict]:
    """env_json(폼) → [{key,value,is_secret}] 정규화. 깨진 입력은 빈 리스트."""
    try:
        data = json.loads(raw or "[]")
    except (ValueError, TypeError):
        return []
    out: list[dict] = []
    if isinstance(data, list):
        for e in data:
            if isinstance(e, dict) and (e.get("key") or "").strip():
                out.append({"key": e["key"].strip(),
                            "value": e.get("value", ""),
                            "is_secret": bool(e.get("is_secret"))})
    return out


def _apps_response(request: Request, session: Session):
    apps = AppRepository(session).list_all()
    return render_page(
        request, "pages/apps.html",
        {"active_nav": "apps", "app_count": len(apps), "apps": apps},
    )


# ── 등록 ──────────────────────────────────────────────────────
@router.post("/apps")
def register_app(
    request: Request,
    background: BackgroundTasks,
    repo_url: str = Form(...),
    framework: str = Form(...),
    health_path: str = Form("/healthz"),
    port: int = Form(8080),
    env_json: str = Form("[]"),
    session: Session = Depends(get_session),
):
    name = derive_app_name(repo_url)
    env_vars = parse_env_json(env_json)
    repo = AppRepository(session)
    existing = next((a for a in repo.list_all() if a.name == name), None)
    if existing is None:
        repo.create(
            name=name, repo_url=repo_url, framework=framework,
            health_path=health_path, port=port,
            namespace=settings.sut_namespace, status="registering",
            env_vars=env_vars,
        )
    else:
        existing.repo_url = repo_url
        existing.framework = framework
        existing.health_path = health_path
        existing.port = port
        existing.env_vars = env_vars
        existing.status = "registering"
        session.commit()
    background.add_task(_bootstrap, name)
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
            gitops.bootstrap_app(name, app.repo_url, app.framework, plain, secret_name)
            status = "ready"
        except Exception:
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
        sha = resolve_head_sha(app.repo_url) or "unknown00"
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
                pass
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
