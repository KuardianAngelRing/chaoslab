"""최종 회귀 HTML 보고서와 PDF 다운로드."""
import subprocess

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.db.database import get_session
from app.db.repositories import ScenarioRunRepository
from app.rendering import templates
from app.services.reports import report_context, report_filename, report_pdf

router = APIRouter()
_TERMINAL = {"completed", "failed"}


def _completed_run(session: Session, run_id: int):
    run = ScenarioRunRepository(session).get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="최종 회귀 실행을 찾을 수 없습니다")
    if run.status not in _TERMINAL:
        raise HTTPException(status_code=409, detail="최종 회귀 실행이 끝난 뒤 보고서를 만들 수 있습니다")
    return run


@router.get("/scenario-runs/{run_id}/report")
def scenario_report(request: Request, run_id: int, session: Session = Depends(get_session)):
    run = _completed_run(session, run_id)
    return templates.TemplateResponse(request, "reports/company_scenario_report.html", report_context(run))


@router.get("/scenario-runs/{run_id}/report.pdf")
def scenario_report_pdf(run_id: int, session: Session = Depends(get_session)):
    run = _completed_run(session, run_id)
    try:
        content = report_pdf(run)
    except (RuntimeError, subprocess.SubprocessError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{report_filename(run)}"'},
    )
