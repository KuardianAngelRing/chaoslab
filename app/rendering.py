from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Experiment.status → (한국어 라벨, 배지 클래스). 목록 행·워크플로우 셸 헤더·실험 카드가 공유 (한 곳 원칙)
EXPERIMENT_STATUS_LABELS: dict[str, tuple[str, str]] = {
    "pending": ("실험 대기", "badge-info"),
    "deploying": ("환경 배포 중", "badge-info"),
    "running": ("장애 주입·관측 중", "badge-info"),
    "completed": ("실험 완료", "badge-success"),
    "failed": ("실험 실패", "badge-danger"),
    "stopped": ("중지됨", "badge-muted"),
}
templates.env.globals["exp_status_labels"] = EXPERIMENT_STATUS_LABELS


def resolve_layout(headers: dict) -> str:
    """HX-Request(소문자 키 기준)면 셸 없는 부분 레이아웃, 아니면 풀 셸."""
    normalized = {k.lower(): v for k, v in headers.items()}
    return "_partial.html" if "hx-request" in normalized else "base.html"


def render_page(request: Request, template: str, context: dict | None = None):
    ctx = dict(context or {})
    ctx["layout"] = resolve_layout(dict(request.headers))
    return templates.TemplateResponse(request, template, ctx)
