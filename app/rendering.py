from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def resolve_layout(headers: dict) -> str:
    """HX-Request(소문자 키 기준)면 셸 없는 부분 레이아웃, 아니면 풀 셸."""
    normalized = {k.lower(): v for k, v in headers.items()}
    return "_partial.html" if "hx-request" in normalized else "base.html"


def render_page(request: Request, template: str, context: dict | None = None):
    ctx = dict(context or {})
    ctx["layout"] = resolve_layout(dict(request.headers))
    return templates.TemplateResponse(request, template, ctx)
