"""최종 회귀 결과 보고서 데이터와 Chromium PDF 렌더링."""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from app.config import settings
from app.rendering import templates


def report_context(run) -> dict:
    results = run.results or []
    baseline_results = run.baseline_results or []
    comparison = run.comparison or {}
    return {
        "run": run,
        "app": run.app,
        "preparation": run.preparation_session,
        "scenario": run.scenario or {},
        "baseline_results": baseline_results,
        "results": results,
        "comparison": comparison,
        "before": comparison.get("before") or {},
        "after": comparison.get("after") or {},
        "r": comparison.get("r") or {},
        "changes": comparison.get("changes") or [],
        "scenario_comparisons": comparison.get("scenarios") or [],
        "narrative": run.report_content or {},
        "cleanup_count": sum(item.get("cleanup_completed") is True for item in results),
        "total": len((run.scenario or {}).get("experiments") or []),
        "generated_at": run.finished_at or run.updated_at,
        "verdict_ko": _verdict_ko,
        "metric": _metric,
    }


def report_html(run) -> str:
    return templates.get_template("reports/company_scenario_report.html").render(**report_context(run))


def report_pdf(run) -> bytes:
    chrome = _chromium_executable()
    if chrome is None:
        raise RuntimeError("PDF 렌더링에 사용할 Chromium을 찾을 수 없습니다")
    with tempfile.TemporaryDirectory(prefix="chaoslab-report-") as directory:
        root = Path(directory)
        html_path = root / "report.html"
        pdf_path = root / "report.pdf"
        html_path.write_text(report_html(run), encoding="utf-8")
        process = subprocess.Popen(
            [
                chrome,
                "--headless",
                "--disable-gpu",
                "--no-sandbox",
                "--no-pdf-header-footer",
                f"--user-data-dir={root / 'profile'}",
                f"--print-to-pdf={pdf_path}",
                html_path.as_uri(),
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 30
        last_size = -1
        stable_checks = 0
        while time.monotonic() < deadline:
            size = pdf_path.stat().st_size if pdf_path.exists() else 0
            if size > 0 and size == last_size:
                stable_checks += 1
                if stable_checks >= 3:
                    break
            else:
                stable_checks = 0
                last_size = size
            if process.poll() is not None and size > 0:
                break
            time.sleep(0.2)
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        content = pdf_path.read_bytes() if pdf_path.exists() else b""
        if not content:
            detail = process.stderr.read().decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Chromium이 PDF를 생성하지 못했습니다: {detail}" if detail else
                               "Chromium이 PDF를 생성하지 못했습니다")
        return content


def report_filename(run) -> str:
    app = re.sub(r"[^a-zA-Z0-9-]+", "-", run.app.name).strip("-") or "app"
    return f"chaoslab-{app}-{run.id}-report.pdf"


def _chromium_executable() -> str | None:
    candidates = [
        settings.chromium_path,
        shutil.which("chromium") or "",
        shutil.which("chromium-browser") or "",
        shutil.which("google-chrome") or "",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    return next((path for path in candidates if path and Path(path).is_file()), None)


def _verdict_ko(value: str) -> str:
    return {"passed": "통과", "failed": "실패", "inconclusive": "판정 불가"}.get(value, value)


def _metric(value, suffix: str = "") -> str:
    return "관측 없음" if value is None else f"{value}{suffix}"
